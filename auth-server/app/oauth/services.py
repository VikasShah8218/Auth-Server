"""OAuth 2.1 flows, written directly on joserfc.

aioauth was tried first. Its refresh flow reads and then revokes in two steps, with no token families,
grace window or reuse detection, and it has no token exchange. Those are the parts of this server that
matter most.

    authorization_code + PKCE   browser and mobile apps
    refresh_token               rotation with a grace window and reuse detection
    client_credentials          a server acting as itself
    token-exchange (RFC 8693)   a server acting for a user, with narrowing
"""

import hmac
from datetime import timedelta
from uuid import uuid4

from fastapi import Request
from tortoise.exceptions import DoesNotExist
from tortoise.transactions import in_transaction

from app.applications.models import Application, Permission, Role, RolePermission, UserAppState, UserRole
from app.applications.services import permission_bits_for_user
from app.audit.services import Actor, record_audit
from app.clients.models import OAuthClient
from app.clients.utils import OIDC_SCOPES
from app.identity.models import Session
from app.identity.services import is_session_live, revoke_session
from app.oauth.models import AuthorizationCode, RefreshToken
from app.oauth.utils import TOKEN_TYPE_ACCESS, OAuthError, basic_credentials, pkce_matches, profile_claims
from app.tokens import services as token_services
from app.tokens.services import verify_access_token
from app.users.models import User
from settings.settings import settings
from utilities import ratelimit
from utilities.common import client_ip, utcnow
from utilities.crypto import hash_token, new_opaque_token
from utilities.exceptions import AppError
from utilities.masks import WILDCARD_BIT, bits_to_mask, encode_mask


# Client authentication


async def authenticate_client(request: Request, form: dict[str, str]) -> OAuthClient:
    """client_secret_basic, client_secret_post, or none for a public client."""
    basic = basic_credentials(request)
    client_id, secret = basic or (form.get("client_id"), form.get("client_secret"))

    async def failed() -> OAuthError:
        await ratelimit.hit(f"rate:client:ip:{client_ip(request) or 'unknown'}", settings.TOKEN_LIMIT_PER_IP)
        return OAuthError("invalid_client", "Client authentication failed", 401)

    if not client_id:
        raise await failed()
    client = await OAuthClient.get_or_none(client_id=client_id, is_active=True).select_related("app")
    if client is None or not client.app.is_active:
        raise await failed()
    if client.type == "confidential":
        # The secret is 256 random bits, so a fast hash is enough. A password KDF here would hand anyone who
        # knows a client_id a cheap way to burn CPU.
        if not secret or not hmac.compare_digest(hash_token(secret), client.secret_hash or ""):
            raise await failed()
    elif secret:
        raise await failed()
    return client


# Access decisions


async def user_may_use_app(user: User, app: Application) -> bool:
    """A role in the app is required. The AUTH app is the exception, because every user may sign in to the
    console to manage their own account."""
    if app.key == settings.AUTH_APP_KEY:
        return True
    return await UserRole.filter(user_id=user.id, role__app_id=app.id).exists()


def validate_scope(client: OAuthClient, requested: str | None) -> str:
    scopes = (requested or "").split()
    allowed = set(client.scopes) | OIDC_SCOPES if client.type == "public" else set(client.scopes)
    if not set(scopes) <= allowed:
        raise OAuthError("invalid_scope", "A requested scope is not allowed for this client")
    return " ".join(sorted(set(scopes)))


# Token construction


async def _version(user: User, app: Application) -> int:
    state = await UserAppState.get_or_none(user_id=user.id, app_id=app.id)
    return state.version if state else 0


async def _access_token(
    user: User,
    app: Application,
    session: Session,
    client_id: str,
    lifetime: int,
    bits: set[int] | None = None,
    roles: list[str] | None = None,
    act: dict | None = None,
    scope: str = "",
    version: int | None = None,
) -> str:
    # The version is read first. A change landing mid-way then leaves new access under an old version,
    # which fails safe. The other order would let old access pass as current after a demotion.
    if version is None:
        version = await _version(user, app)
    if bits is None:
        bits = await permission_bits_for_user(user.id, app.id)
    if roles is None:
        roles = sorted(await Role.filter(app_id=app.id, users__user_id=user.id).values_list("name", flat=True))
    claims = {
        "token_use": "user",
        "sub": str(user.public_id),
        "aud": app.key,
        "sid": str(session.public_id),
        "client_id": client_id,
        "ver": version,
        "pm": encode_mask(bits_to_mask(bits)),
        "pv": app.perm_map_version,
        "roles": roles,
    }
    if act is not None:
        claims["act"] = act
    if scope:
        claims["scope"] = scope
    return await token_services.sign(claims, token_services.TYP_ACCESS, lifetime)


async def _id_token(
    user: User, session: Session, client: OAuthClient, scope: str, nonce: str | None, access_token: str
) -> str:
    claims = {
        "sub": str(user.public_id),
        "aud": client.client_id,
        "sid": str(session.public_id),
        "auth_time": int(session.auth_time.timestamp()),
        "amr": session.amr,
        "at_hash": token_services.at_hash(access_token),
        **profile_claims(user, scope),
    }
    if nonce:
        claims["nonce"] = nonce
    return await token_services.sign(claims, token_services.TYP_ID, settings.ACCESS_TOKEN_MINUTES * 60)


async def _new_refresh_token(session: Session, client: OAuthClient, family_id, scope: str) -> str:
    raw = new_opaque_token()
    await RefreshToken.create(
        token_hash=hash_token(raw),
        family_id=family_id,
        session=session,
        client=client,
        scope=scope,
        # Absolute: rotation can't keep a session alive past its own end.
        expires_at=session.expires_at,
    )
    return raw


async def _user_token_response(
    user: User,
    session: Session,
    client: OAuthClient,
    family_id,
    scope: str,
    nonce: str | None = None,
    issue_refresh: bool = True,
) -> dict:
    lifetime = settings.ACCESS_TOKEN_MINUTES * 60
    access_token = await _access_token(user, client.app, session, client.client_id, lifetime, scope=scope)
    response = {"access_token": access_token, "token_type": "Bearer", "expires_in": lifetime, "scope": scope}
    if issue_refresh:
        response["refresh_token"] = await _new_refresh_token(session, client, family_id, scope)
    if "openid" in scope.split():
        response["id_token"] = await _id_token(user, session, client, scope, nonce, access_token)
    return response


# Authorization code


async def create_authorization_code(
    client: OAuthClient, session: Session, redirect_uri: str, scope: str, code_challenge: str, nonce: str | None
) -> str:
    raw = new_opaque_token()
    await AuthorizationCode.create(
        code_hash=hash_token(raw),
        client=client,
        session=session,
        family_id=uuid4(),
        pkce_challenge=code_challenge,
        redirect_uri=redirect_uri,
        scope=scope,
        nonce=nonce,
        expires_at=utcnow() + timedelta(seconds=settings.AUTH_CODE_SECONDS),
    )
    return raw


async def _revoke_family(family_id) -> None:
    await RefreshToken.filter(family_id=family_id, revoked_at__isnull=True).update(revoked_at=utcnow())


async def exchange_code(client: OAuthClient, form: dict[str, str]) -> dict:
    invalid = OAuthError("invalid_grant", "The authorization code is not valid")
    code_row = await AuthorizationCode.get_or_none(code_hash=hash_token(form.get("code", ""))).select_related(
        "session__user"
    )
    if code_row is None or code_row.client_id != client.id:
        raise invalid

    # One conditional UPDATE, so only one of two concurrent requests can win.
    claimed = await AuthorizationCode.filter(id=code_row.id, used_at__isnull=True).update(used_at=utcnow())
    if claimed != 1:
        # A second use means the code leaked. Whatever it issued is cancelled.
        await _revoke_family(code_row.family_id)
        raise invalid

    if (
        code_row.expires_at <= utcnow()
        or code_row.redirect_uri != form.get("redirect_uri")
        or not pkce_matches(form.get("code_verifier", ""), code_row.pkce_challenge)
    ):
        raise invalid

    session = code_row.session
    if not await is_session_live(session):
        raise invalid
    user = session.user
    if not await user_may_use_app(user, client.app):
        raise invalid
    return await _user_token_response(user, session, client, code_row.family_id, code_row.scope, code_row.nonce)


# Refresh


async def refresh(client: OAuthClient, form: dict[str, str]) -> dict:
    invalid = OAuthError("invalid_grant", "The refresh token is not valid")
    row = await RefreshToken.get_or_none(token_hash=hash_token(form.get("refresh_token", ""))).select_related(
        "session__user"
    )
    if row is None or row.client_id != client.id or row.revoked_at is not None or row.expires_at <= utcnow():
        raise invalid

    session = row.session
    user = session.user
    if not await is_session_live(session) or not await user_may_use_app(user, client.app):
        raise invalid

    claimed = await RefreshToken.filter(id=row.id, used_at__isnull=True).update(used_at=utcnow())
    in_grace = claimed != 1
    if in_grace:
        await row.refresh_from_db(fields=["used_at"])
        if row.used_at + timedelta(seconds=settings.REFRESH_GRACE_SECONDS) < utcnow():
            # Replayed after the honest window: treat it as theft and end the login.
            async with in_transaction():
                await revoke_session(session)
                await record_audit(
                    Actor(id=str(user.public_id)),
                    "token.reuse_detected",
                    target=str(session.public_id),
                    app=client.app.key,
                )
            raise invalid

    scope = row.scope
    if form.get("scope"):
        narrowed = set(form["scope"].split())
        if not narrowed <= set(scope.split()):
            raise OAuthError("invalid_scope", "Scope can't be widened on refresh")
        scope = " ".join(sorted(narrowed))
    # The loser of an honest race gets an access token only. A second refresh token would start a branch
    # that never collides with the first, so a thief replaying inside the window could keep a session that
    # reuse detection never sees.
    return await _user_token_response(user, session, client, row.family_id, scope, issue_refresh=not in_grace)


# Client credentials


async def client_credentials(client: OAuthClient, form: dict[str, str]) -> dict:
    if client.type != "confidential":
        raise OAuthError("unauthorized_client", "Public clients can't use this grant")
    scope = validate_scope(client, form.get("scope")) or " ".join(sorted(client.scopes))
    audience = form.get("audience") or settings.AUTH_APP_KEY
    if audience != settings.AUTH_APP_KEY and audience not in client.audiences:
        raise OAuthError("invalid_target", "This client may not request that audience")

    lifetime = settings.SERVICE_TOKEN_MINUTES * 60
    token = await token_services.sign(
        {
            "token_use": "service",
            "sub": client.client_id,
            "client_id": client.client_id,
            "app": client.app.key,
            "aud": audience,
            "scope": scope,
            "ver": client.version,
        },
        token_services.TYP_ACCESS,
        lifetime,
    )
    return {"access_token": token, "token_type": "Bearer", "expires_in": lifetime, "scope": scope}


# Token exchange


async def _narrow(user: User, app: Application, codes: list[str]) -> tuple[set[int], list[str]]:
    """Requested permissions, held by the user, and only the roles they fully cover.

    Scope can only ever remove access. Without the role check a narrowed token would keep "Admin", and
    rules that check roles would ignore the narrowing.
    """
    held = await permission_bits_for_user(user.id, app.id)
    roles = await Role.filter(app_id=app.id, users__user_id=user.id).order_by("name")
    if not codes:
        return held, [role.name for role in roles]

    rows = await Permission.filter(app_id=app.id, code__in=codes, retired_at__isnull=True)
    requested = {row.bit for row in rows}
    if len(rows) != len(set(codes)) or (WILDCARD_BIT not in held and not requested <= held):
        raise OAuthError("invalid_scope", "Scope exceeds what the user holds")

    kept = []
    for role in roles:
        bits = set(await RolePermission.filter(role_id=role.id).values_list("permission__bit", flat=True))
        if bits and bits <= requested:
            kept.append(role.name)
    return requested, kept


async def token_exchange(client: OAuthClient, form: dict[str, str]) -> dict:
    if client.type != "confidential":
        raise OAuthError("unauthorized_client", "Only an authenticated service can exchange tokens")
    if form.get("subject_token_type") != TOKEN_TYPE_ACCESS:
        raise OAuthError("invalid_request", "subject_token_type must be an access token")
    if form.get("requested_token_type", TOKEN_TYPE_ACCESS) != TOKEN_TYPE_ACCESS:
        raise OAuthError("invalid_request", "Only access tokens can be requested")

    audience = form.get("audience")
    if not audience:
        raise OAuthError("invalid_request", "audience is required")
    # This server's own API takes no delegated tokens, or a service holding an admin's token could mint
    # itself admin access here.
    if audience == settings.AUTH_APP_KEY or audience not in client.audiences:
        raise OAuthError("invalid_target", "This client may not exchange for that audience")

    try:
        subject = await verify_access_token(form.get("subject_token", ""))
        payload = await token_services.decode(form.get("subject_token", ""), token_services.TYP_ACCESS)
    except AppError:
        raise OAuthError("invalid_grant", "The subject token is not valid") from None
    if subject.aud != client.app.key:
        raise OAuthError("invalid_grant", "The subject token was not issued to this service")
    if "act" in payload:
        raise OAuthError("invalid_grant", "An exchanged token can't be exchanged again")

    target = await Application.get_or_none(key=audience, is_active=True)
    if target is None:
        raise OAuthError("invalid_target", "Unknown audience")
    try:
        session = await Session.get(public_id=subject.sid).select_related("user")
    except DoesNotExist:
        raise OAuthError("invalid_grant", "The subject token is not valid") from None
    user = session.user
    if not await user_may_use_app(user, target):
        raise OAuthError("invalid_grant", "The user has no access to that application")

    version = await _version(user, target)
    bits, roles = await _narrow(user, target, sorted(set(form.get("scope", "").split())))
    lifetime = settings.EXCHANGE_TOKEN_MINUTES * 60
    token = await _access_token(
        user,
        target,
        session,
        client.client_id,
        lifetime,
        bits=bits,
        roles=roles,
        act={"sub": client.client_id, "app": client.app.key},
        version=version,
    )
    await record_audit(
        Actor(id=client.client_id),
        "token.exchange",
        target=str(user.public_id),
        app=target.key,
        details={"from": client.app.key, "scope": form.get("scope", "")},
    )
    return {
        "access_token": token,
        "issued_token_type": TOKEN_TYPE_ACCESS,
        "token_type": "Bearer",
        "expires_in": lifetime,
    }


# Revocation


async def revoke_token(client: OAuthClient, token: str) -> None:
    """RFC 7009: unknown tokens succeed, so this reveals nothing."""
    row = await RefreshToken.get_or_none(token_hash=hash_token(token))
    if row is not None and row.client_id == client.id:
        await _revoke_family(row.family_id)
