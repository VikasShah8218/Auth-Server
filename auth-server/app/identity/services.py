"""SSO sessions: creating one at login, finding it from the cookie, and revoking it everywhere.

A revoked session ends its refresh tokens and console session here, and its access tokens downstream
through a session.revoked event.
"""

from datetime import timedelta
from uuid import UUID

from fastapi import Request, Response
from tortoise.transactions import in_transaction

from app.applications.models import Application
from app.audit.services import Actor, record_audit
from app.console.models import BffSession
from app.events.services import lock_event_counters, publish_event
from app.identity.models import Session
from app.identity.schemas import LoginResponse
from app.identity.utils import set_sso_cookie
from app.oauth.models import AuthorizationCode, RefreshToken
from app.users.models import User
from settings.settings import settings
from utilities.common import client_ip, utcnow
from utilities.crypto import hash_token, new_opaque_token


async def create_session(user: User, amr: list[str], ip: str | None, user_agent: str | None) -> tuple[Session, str]:
    """Returns the session and its raw cookie value. Only the hash is stored."""
    raw = new_opaque_token()
    now = utcnow()
    session = await Session.create(
        user=user,
        token_hash=hash_token(raw),
        auth_time=now,
        amr=amr,
        ip=ip,
        user_agent=(user_agent or "")[:256] or None,
        expires_at=now + timedelta(days=settings.SESSION_DAYS),
    )
    return session, raw


async def finish_login(request: Request, response: Response, user: User, amr: list[str]) -> LoginResponse:
    """The last step of every login method: session, audit record and SSO cookie."""
    ip = client_ip(request)
    async with in_transaction():
        session, raw = await create_session(user, amr, ip, request.headers.get("user-agent"))
        await record_audit(Actor(id=str(user.public_id), ip=ip), "user.login", details={"amr": amr})
    set_sso_cookie(response, raw, session)
    return LoginResponse(status="authenticated")


async def is_session_live(session: Session | None) -> bool:
    if session is None or session.revoked_at is not None or session.expires_at <= utcnow():
        return False
    user = session.user if isinstance(session.user, User) else await session.user
    return user.is_active


async def session_from_cookie(raw: str | None) -> Session | None:
    if not raw:
        return None
    session = await Session.get_or_none(token_hash=hash_token(raw)).select_related("user")
    return session if await is_session_live(session) else None


async def live_sessions(user_id: int) -> list[Session]:
    return await Session.filter(user_id=user_id, revoked_at__isnull=True, expires_at__gt=utcnow()).order_by(
        "-auth_time"
    )


async def _session_app_ids(session: Session) -> set[int]:
    """Every app that may hold tokens for this session."""
    by_role = await Application.filter(roles__users__user_id=session.user_id).values_list("id", flat=True)
    by_token = await RefreshToken.filter(session_id=session.id).values_list("client__app_id", flat=True)
    return set(by_role) | set(by_token)


async def revoke_session(session: Session) -> None:
    """End one login: its refresh tokens, its console session, and its access tokens through a
    session.revoked event. Call inside a transaction."""
    if session.revoked_at is not None:
        return
    now = utcnow()
    session.revoked_at = now
    await session.save(update_fields=["revoked_at"])
    await RefreshToken.filter(session_id=session.id, revoked_at__isnull=True).update(revoked_at=now)
    await BffSession.filter(session_id=session.id).delete()
    await publish_event(
        await _session_app_ids(session),
        "session.revoked",
        {"sid": str(session.public_id), "sub": str((await session.user).public_id)},
    )


async def revoke_user_sessions(user_id: int, keep: UUID | None = None) -> int:
    """End every live login of a user, except `keep`. Call inside a transaction."""
    sessions = await Session.filter(user_id=user_id, revoked_at__isnull=True, expires_at__gt=utcnow()).order_by("id")
    targets = [s for s in sessions if keep is None or s.public_id != keep]
    app_ids: set[int] = set()
    for session in targets:
        app_ids |= await _session_app_ids(session)
    await lock_event_counters(app_ids)
    for session in targets:
        await revoke_session(session)
    return len(targets)


async def revoke_session_by_id(public_id: UUID) -> bool:
    async with in_transaction():
        session = await Session.get_or_none(public_id=public_id)
        if session is None:
            return False
        await revoke_session(session)
    return True


# Background job


async def cleanup_tick() -> None:
    """Remove expired codes, console sessions, refresh tokens and sessions.

    Revoked sessions stay until they would have expired, because snapshots must list them for as long as
    a token could name them.
    """
    now = utcnow()
    await AuthorizationCode.filter(expires_at__lt=now).delete()
    await BffSession.filter(expires_at__lt=now).delete()
    await RefreshToken.filter(expires_at__lt=now).delete()
    await Session.filter(expires_at__lt=now).delete()
