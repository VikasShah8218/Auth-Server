"""Self-service for the signed-in user: profile, password, sessions and TOTP. Policy: any token for AUTH."""

from uuid import UUID

from fastapi import APIRouter, Depends, Response, status
from tortoise.transactions import in_transaction

from app.account import services
from app.account.deps import current_user
from app.account.schemas import CodeRequest, FactorOut, PasswordChange, PasswordConfirm, SessionOut, TotpEnrolment
from app.account.utils import session_view
from app.audit.services import Actor, record_audit
from app.identity import mfa
from app.identity.models import MfaFactor, Session
from app.identity.services import live_sessions, revoke_session
from app.security.deps import current_actor, current_claims
from app.tokens.schemas import Claims
from app.users.models import User
from app.users.schemas import UserDetail
from app.users.services import user_detail
from utilities.exceptions import not_found

router = APIRouter(prefix="/v1/me", tags=["Account"])


@router.get("", response_model=UserDetail, summary="My profile and access")
async def me(user: User = Depends(current_user)):
    return await user_detail(user)


@router.post("/password", status_code=status.HTTP_204_NO_CONTENT,
             summary="Change my password. My other sessions end")
async def change_password(
    data: PasswordChange,
    user: User = Depends(current_user),
    claims: Claims = Depends(current_claims),
    actor: Actor = Depends(current_actor),
):
    await services.change_password(user, data.current_password, data.new_password, claims.sid, actor)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/sessions", response_model=list[SessionOut], summary="My live sessions")
async def my_sessions(user: User = Depends(current_user), claims: Claims = Depends(current_claims)):
    return [session_view(session, claims.sid) for session in await live_sessions(user.id)]


@router.delete("/sessions/{session_id}", status_code=status.HTTP_204_NO_CONTENT, summary="End one of my sessions")
async def end_my_session(session_id: UUID, user: User = Depends(current_user), actor: Actor = Depends(current_actor)):
    async with in_transaction():
        session = await Session.get_or_none(public_id=session_id, user_id=user.id)
        if session is None:
            raise not_found("Session")
        await revoke_session(session)
        await record_audit(actor, "session.revoke", target=str(session_id))
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/mfa", response_model=list[FactorOut], summary="My confirmed MFA factors")
async def my_factors(user: User = Depends(current_user)):
    factors = await MfaFactor.filter(user_id=user.id, confirmed_at__isnull=False).order_by("id")
    return [FactorOut(id=f.public_id, type=f.type, name=f.name, confirmed_at=f.confirmed_at) for f in factors]


@router.post("/mfa/totp", response_model=TotpEnrolment, status_code=status.HTTP_201_CREATED,
             summary="Start TOTP setup (needs my password). Active only after confirm")
async def start_totp(data: PasswordConfirm, user: User = Depends(current_user)):
    await services.confirm_password(user, data.password)
    secret, uri = await mfa.begin_totp_enrolment(user)
    return TotpEnrolment(secret=secret, otpauth_uri=uri)


@router.post("/mfa/totp/confirm", status_code=status.HTTP_204_NO_CONTENT, summary="Confirm TOTP with a first code")
async def confirm_totp(data: CodeRequest, user: User = Depends(current_user), actor: Actor = Depends(current_actor)):
    await services.limited_code(user, lambda: mfa.confirm_totp_enrolment(user, data.code))
    async with in_transaction():
        await record_audit(actor, "mfa.enable", target=str(user.public_id), details={"type": "totp"})
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/mfa/totp/remove", status_code=status.HTTP_204_NO_CONTENT, summary="Remove TOTP (needs a valid code)")
async def remove_totp(data: CodeRequest, user: User = Depends(current_user), actor: Actor = Depends(current_actor)):
    await services.limited_code(user, lambda: mfa.remove_totp(user, data.code))
    async with in_transaction():
        await record_audit(actor, "mfa.disable", target=str(user.public_id), details={"type": "totp"})
    return Response(status_code=status.HTTP_204_NO_CONTENT)
