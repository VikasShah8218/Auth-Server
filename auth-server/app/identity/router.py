"""Sign-in: password, then a TOTP code when the user has MFA.

router        /v1/identity          login, MFA verify          (FREE)
admin_router  /v1/admin/sessions    end any session            (Admin)
"""

import asyncio
from uuid import UUID

from fastapi import APIRouter, Depends, Request, Response, status
from tortoise.transactions import in_transaction

from app.audit.services import Actor, record_audit
from app.identity import mfa
from app.identity.models import Session
from app.identity.schemas import LoginRequest, LoginResponse, MfaVerifyRequest
from app.identity.services import finish_login, revoke_session
from app.security.deps import current_actor
from app.users.models import User
from app.users.utils import hash_password, needs_rehash, spend_password_time, verify_password
from settings.settings import settings
from utilities import ratelimit
from utilities.common import client_ip
from utilities.exceptions import AppError, not_found

router = APIRouter(prefix="/v1/identity", tags=["Identity"])
admin_router = APIRouter(prefix="/v1/admin/sessions", tags=["Admin: Sessions"])


def _invalid_credentials() -> AppError:
    # One message for every cause, so a caller can't discover which accounts exist.
    return AppError(401, "invalid_credentials", "Incorrect username or password")


@router.post("/login", response_model=LoginResponse,
             summary="Password sign-in. Sets the SSO cookie, or returns an MFA challenge")
async def login(data: LoginRequest, request: Request, response: Response):
    username = data.username.strip().lower()
    ip = client_ip(request)
    ip_key = f"rate:login:ip:{ip}"
    pair_key = f"rate:login:pair:{username}:{ip}"
    account_key = f"rate:login:account:{username}"

    # Only failures count. The limit that blocks is per account and IP, so a stranger can't lock someone
    # out of their own account from another address. The much higher account-wide ceiling still stops
    # guessing spread across many addresses.
    await ratelimit.check(ip_key, settings.LOGIN_LIMIT_PER_IP)
    await ratelimit.check(pair_key, settings.LOGIN_LIMIT_PER_ACCOUNT)
    await ratelimit.check(account_key, settings.LOGIN_LIMIT_PER_ACCOUNT * 10)

    # In a thread, because Argon2 would otherwise stall every request on this worker.
    user = await User.get_or_none(username=username)
    if user is None:
        await asyncio.to_thread(spend_password_time, data.password)
        valid = False
    else:
        valid = await asyncio.to_thread(verify_password, data.password, user.password_hash)

    if not valid or not user.is_active:
        for key in (ip_key, pair_key, account_key):
            await ratelimit.record(key)
        raise _invalid_credentials()

    await ratelimit.clear(pair_key)

    if needs_rehash(user.password_hash):
        user.password_hash = await asyncio.to_thread(hash_password, data.password)
        await user.save(update_fields=["password_hash"])

    factors = await mfa.confirmed_factors(user.id)
    if factors:
        return LoginResponse(
            status="mfa_required",
            challenge=await mfa.create_challenge(user, ip),
            methods=sorted({factor.type for factor in factors}),
        )
    return await finish_login(request, response, user, ["pwd"])


@router.post("/mfa/verify", response_model=LoginResponse, summary="Finish sign-in with a TOTP code")
async def verify_mfa(data: MfaVerifyRequest, request: Request, response: Response):
    stored = await mfa.load_challenge(data.challenge)
    await mfa.count_attempt(data.challenge)

    # A correct password clears the login counter, so without this per-user limit someone holding a
    # password could fetch new challenges and guess forever.
    mfa_key = f"rate:mfa:user:{stored['user_id']}"
    await ratelimit.hit(mfa_key, settings.MFA_MAX_ATTEMPTS * 2)

    user = await User.get_or_none(id=stored["user_id"], is_active=True)
    if user is None:
        await mfa.delete_challenge(data.challenge)
        raise mfa.challenge_expired()

    if not await mfa.verify_any_totp(user.id, data.code):
        raise mfa.bad_code()

    await mfa.delete_challenge(data.challenge)
    await ratelimit.clear(mfa_key)
    return await finish_login(request, response, user, ["pwd", "otp"])


@admin_router.delete("/{session_id}", status_code=status.HTTP_204_NO_CONTENT, summary="End one session")
async def end_session(session_id: UUID, actor: Actor = Depends(current_actor)):
    async with in_transaction():
        session = await Session.get_or_none(public_id=session_id)
        if session is None:
            raise not_found("Session")
        await revoke_session(session)
        await record_audit(actor, "session.revoke", target=str(session_id))
    return Response(status_code=status.HTTP_204_NO_CONTENT)
