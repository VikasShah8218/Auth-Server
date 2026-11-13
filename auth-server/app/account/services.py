"""Step-up checks for self-service changes. Both are rate limited, so a hijacked session can't be used
to guess a password or a code."""

import asyncio
from collections.abc import Awaitable, Callable
from uuid import UUID

from tortoise.transactions import in_transaction

from app.audit.services import Actor, record_audit
from app.identity.services import revoke_user_sessions
from app.users.models import User
from app.users.utils import hash_password, validate_password, verify_password
from settings.settings import settings
from utilities import ratelimit
from utilities.exceptions import AppError


async def confirm_password(user: User, password: str) -> None:
    key = f"rate:password:user:{user.id}"
    await ratelimit.check(key, settings.LOGIN_LIMIT_PER_ACCOUNT)
    if not await asyncio.to_thread(verify_password, password, user.password_hash):
        await ratelimit.record(key)
        raise AppError(401, "invalid_credentials", "Password is incorrect")
    await ratelimit.clear(key)


async def limited_code(user: User, attempt: Callable[[], Awaitable[None]]) -> None:
    """Run a code check, counting only wrong codes against the user's MFA limit."""
    key = f"rate:mfa:user:{user.id}"
    await ratelimit.check(key, settings.MFA_MAX_ATTEMPTS * 2)
    try:
        await attempt()
    except AppError as exc:
        if exc.code == "invalid_code":
            await ratelimit.record(key)
        raise


async def change_password(user: User, current: str, new: str, keep_sid: str, actor: Actor) -> None:
    await confirm_password(user, current)
    validate_password(new, user.username)
    password_hash = await asyncio.to_thread(hash_password, new)
    async with in_transaction():
        user.password_hash = password_hash
        await user.save(update_fields=["password_hash", "updated_at"])
        # Anyone holding another session may be the reason for the change.
        await revoke_user_sessions(user.id, keep=UUID(keep_sid))
        await record_audit(actor, "user.password_change", target=str(user.public_id))
