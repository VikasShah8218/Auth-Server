"""Backend-for-frontend for the admin console.

Tokens stay on the server, encrypted. The browser holds one opaque HttpOnly cookie that JavaScript can't
read, so a script injected into the page has no token to steal. The console is an ordinary PKCE client of
this server's own OAuth flow.
"""

import hmac
import json
import secrets
from datetime import timedelta

from fastapi import Request
from redis.exceptions import RedisError

from app.applications.models import Application
from app.clients.models import OAuthClient
from app.console.models import BffSession
from app.identity.services import is_session_live
from app.oauth import services as oauth_services
from app.oauth.utils import OAuthError
from app.tokens.schemas import Claims
from app.tokens.services import verify_access_token
from settings.settings import settings
from utilities.common import utcnow
from utilities.crypto import decrypt, encrypt, hash_token
from utilities.exceptions import AppError, unavailable
from utilities.redis import get_redis

CONSOLE_CLIENT_ID = "auth-console"
CONSOLE_COOKIE = "auth_console"
CSRF_HEADER = "x-csrf-token"
STATE_COOKIE = "auth_console_state"
STATE_SECONDS = 300

_STATE_PREFIX = "bff:state:"
_SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


def redirect_uri() -> str:
    return f"{settings.ISSUER}/bff/callback"


async def ensure_console_client() -> None:
    """Create the console's OAuth client once the AUTH application exists."""
    app = await Application.get_or_none(key=settings.AUTH_APP_KEY)
    if app is None:
        return
    client, created = await OAuthClient.get_or_create(
        client_id=CONSOLE_CLIENT_ID,
        defaults={
            "name": "Admin Console",
            "app": app,
            "type": "public",
            "redirect_uris": [redirect_uri()],
            "scopes": ["openid", "profile", "email"],
        },
    )
    if not created and client.redirect_uris != [redirect_uri()]:
        client.redirect_uris = [redirect_uri()]
        await client.save(update_fields=["redirect_uris"])


async def console_client() -> OAuthClient:
    return await OAuthClient.get(client_id=CONSOLE_CLIENT_ID).select_related("app")


# Login state (Redis)


async def save_state(state: str, verifier: str, binding: str) -> None:
    try:
        await get_redis().set(
            _STATE_PREFIX + hash_token(state),
            json.dumps({"verifier": verifier, "binding": hash_token(binding)}),
            ex=STATE_SECONDS,
        )
    except RedisError:
        raise unavailable() from None


async def take_state(state: str) -> dict | None:
    """Single use: removed the moment it's read."""
    key = _STATE_PREFIX + hash_token(state)
    try:
        async with get_redis().pipeline(transaction=True) as pipe:
            pipe.get(key)
            pipe.delete(key)
            stored, _ = await pipe.execute()
    except RedisError:
        raise unavailable() from None
    return json.loads(stored) if stored else None


# Stored tokens


def _access_context(handle_hash: str) -> str:
    return f"bff-access:{handle_hash}"


def _refresh_context(handle_hash: str) -> str:
    return f"bff-refresh:{handle_hash}"


def _access_expiry(seconds: int):
    return utcnow() + timedelta(seconds=seconds)


async def create_bff_session(handle: str, session, tokens: dict) -> BffSession:
    handle_hash = hash_token(handle)
    return await BffSession.create(
        handle_hash=handle_hash,
        session=session,
        encrypted_access_token=encrypt(tokens["access_token"], _access_context(handle_hash)),
        encrypted_refresh_token=encrypt(tokens["refresh_token"], _refresh_context(handle_hash)),
        access_expires_at=_access_expiry(tokens["expires_in"]),
        csrf_token=secrets.token_urlsafe(32),
        expires_at=session.expires_at,
    )


async def load(request: Request) -> BffSession | None:
    handle = request.cookies.get(CONSOLE_COOKIE)
    if not handle:
        return None
    row = await BffSession.get_or_none(handle_hash=hash_token(handle)).select_related("session__user")
    if row is None or not await is_session_live(row.session):
        return None
    return row


def check_csrf(request: Request, row: BffSession) -> None:
    """A cookie is sent automatically, so a write must also prove it came from the console, which is the
    only page able to read this token."""
    if request.method in _SAFE_METHODS:
        return
    sent = request.headers.get(CSRF_HEADER, "")
    if not hmac.compare_digest(sent, row.csrf_token):
        raise AppError(403, "csrf_failed", "Missing or invalid CSRF token")


async def _refresh(row: BffSession) -> Claims | None:
    raw = decrypt(row.encrypted_refresh_token, _refresh_context(row.handle_hash))
    try:
        tokens = await oauth_services.refresh(await console_client(), {"refresh_token": raw})
    except OAuthError:
        await row.delete()
        return None
    row.encrypted_access_token = encrypt(tokens["access_token"], _access_context(row.handle_hash))
    # Absent when a parallel console request won the rotation. That request saves the new refresh token,
    # so this one must leave it alone.
    if "refresh_token" in tokens:
        row.encrypted_refresh_token = encrypt(tokens["refresh_token"], _refresh_context(row.handle_hash))
    row.access_expires_at = _access_expiry(tokens["expires_in"])
    await row.save(
        update_fields=[
            "encrypted_access_token",
            "access_expires_at",
            *(["encrypted_refresh_token"] if "refresh_token" in tokens else []),
        ]
    )
    return await verify_access_token(tokens["access_token"])


async def claims_from_cookie(request: Request) -> Claims | None:
    """The console's identity for the policy guard, renewing its token if needed.

    A failed check also renews, because a role change makes the token stale before it expires, and the
    console should pick that up without a new login.
    """
    row = await load(request)
    if row is None:
        return None
    check_csrf(request, row)
    if row.access_expires_at > utcnow():
        try:
            return await verify_access_token(decrypt(row.encrypted_access_token, _access_context(row.handle_hash)))
        except AppError:
            pass
    return await _refresh(row)
