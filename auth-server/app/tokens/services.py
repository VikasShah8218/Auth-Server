"""Signing and verifying the JWTs this server issues.

Only ES256 is accepted when verifying, whatever a token's header claims, so "alg: none" and downgrades to an
HMAC signed with the public key both fail. Downstream servers learn about revocations by event; this server
holds the data itself, so verify_access_token() also checks the user, session, app and version on every call.
"""

import base64
import hashlib
import time
import uuid
from typing import Any
from uuid import UUID

from joserfc import jws, jwt
from joserfc.errors import JoseError
from pydantic import ValidationError

from app.applications.models import Application, UserAppState
from app.clients.models import OAuthClient
from app.identity.models import Session
from app.keys.services import ALGORITHM, signing_key, verification_key
from app.tokens.schemas import Claims, ServiceClaims
from app.users.models import User
from settings.settings import settings
from utilities.exceptions import AppError

TYP_ACCESS = "at+jwt"
TYP_ID = "JWT"
TYP_EVENT = "event+jwt"


# Signing


async def sign(claims: dict[str, Any], typ: str, lifetime: int) -> str:
    key = await signing_key()
    now = int(time.time())
    payload = {
        "iss": settings.ISSUER,
        "iat": now,
        "exp": now + lifetime,
        "jti": uuid.uuid4().hex,
        **claims,
    }
    return jwt.encode({"alg": ALGORITHM, "typ": typ, "kid": key.kid}, payload, key, algorithms=[ALGORITHM])


def at_hash(access_token: str) -> str:
    digest = hashlib.sha256(access_token.encode()).digest()[:16]
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode()


# Decoding


def _invalid() -> AppError:
    return AppError(401, "invalid_token", "Token could not be verified", headers={"WWW-Authenticate": "Bearer"})


def _revoked() -> AppError:
    return AppError(401, "invalid_token", "Token has been revoked", headers={"WWW-Authenticate": "Bearer"})


async def decode(token: str, typ: str) -> dict[str, Any]:
    """Check signature, algorithm, type, issuer and expiry. Audience is the caller's job."""
    try:
        header = jws.extract_compact(token.encode()).headers()
        key = await verification_key(str(header.get("kid", "")))
        if key is None:
            raise _invalid()
        verified = jwt.decode(token, key, algorithms=[ALGORITHM])
    except (JoseError, ValueError, UnicodeError):
        raise _invalid() from None

    claims = verified.claims
    if (
        header.get("typ") != typ
        or claims.get("iss") != settings.ISSUER
        or not isinstance(claims.get("exp"), int)
        or claims["exp"] <= time.time()
    ):
        raise _invalid()
    return claims


# User access tokens


async def verify_access_token(token: str) -> Claims:
    """Verify a user's access token, including its live state."""
    payload = await decode(token, TYP_ACCESS)
    if payload.get("token_use") != "user":
        raise _revoked()
    try:
        claims = Claims.model_validate(payload)
        sub = UUID(claims.sub)
        sid = UUID(claims.sid)
    except (ValidationError, ValueError):
        raise _revoked() from None

    user = await User.get_or_none(public_id=sub, is_active=True)
    if user is None:
        raise _revoked()
    if not await Session.filter(public_id=sid, user_id=user.id, revoked_at__isnull=True).exists():
        raise _revoked()
    app = await Application.get_or_none(key=claims.aud, is_active=True)
    if app is None:
        raise _revoked()
    state = await UserAppState.get_or_none(user_id=user.id, app_id=app.id)
    if (state.version if state else 0) != claims.ver:
        raise _revoked()
    issuer = claims.act["sub"] if claims.act else claims.client_id
    if not await OAuthClient.filter(client_id=issuer, is_active=True).exists():
        raise _revoked()
    return claims


# Service tokens


async def verify_service_token(token: str) -> ServiceClaims:
    """A service token for this server's own API. Its client must still be valid."""
    payload = await decode(token, TYP_ACCESS)
    if payload.get("token_use") != "service":
        raise _revoked()
    try:
        claims = ServiceClaims.model_validate(payload)
    except ValidationError:
        raise _revoked() from None
    if claims.aud != settings.AUTH_APP_KEY:
        raise _revoked()

    client = await OAuthClient.get_or_none(client_id=claims.client_id, is_active=True).select_related("app")
    if (
        client is None
        or client.version != claims.ver
        or not client.app.is_active
        or client.app.key != claims.app
    ):
        raise _revoked()
    return claims


async def verify_service_scope_alive(claims: ServiceClaims) -> bool:
    """Whether a long-lived stream's client is still valid."""
    return await OAuthClient.filter(
        client_id=claims.client_id, is_active=True, version=claims.ver, app__is_active=True
    ).exists()


def revoked_error() -> AppError:
    return _revoked()
