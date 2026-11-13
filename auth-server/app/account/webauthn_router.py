"""Registering and removing my security keys. Both need my password first."""

from uuid import UUID

from fastapi import APIRouter, Depends, Response, status
from tortoise.transactions import in_transaction
from webauthn import generate_registration_options, options_to_json, verify_registration_response
from webauthn.helpers import base64url_to_bytes, bytes_to_base64url
from webauthn.helpers.exceptions import WebAuthnException
from webauthn.helpers.structs import PublicKeyCredentialDescriptor

from app.account.deps import current_user
from app.account.schemas import PasswordConfirm, WebAuthnRegistration
from app.account.services import confirm_password
from app.audit.services import Actor, record_audit
from app.identity import webauthn
from app.identity.models import MfaFactor
from app.security.deps import current_actor
from app.users.models import User
from settings.settings import settings
from utilities.common import utcnow
from utilities.exceptions import not_found

router = APIRouter(prefix="/v1/me/mfa/webauthn", tags=["Account"])


@router.post("/options", summary="WebAuthn registration options (needs my password)")
async def registration_options(data: PasswordConfirm, user: User = Depends(current_user)) -> Response:
    await confirm_password(user, data.password)
    existing = await webauthn.user_keys(user.id)
    options = generate_registration_options(
        rp_id=webauthn.rp_id(),
        rp_name=webauthn.RP_NAME,
        user_id=user.public_id.bytes,
        user_name=user.username,
        exclude_credentials=[PublicKeyCredentialDescriptor(id=base64url_to_bytes(f.credential_id)) for f in existing],
    )
    await webauthn.store_challenge(f"webauthn:register:{user.id}", options.challenge)
    return Response(options_to_json(options), media_type="application/json")


@router.post("/register", status_code=status.HTTP_204_NO_CONTENT, summary="Register a security key")
async def register(data: WebAuthnRegistration, user: User = Depends(current_user), actor: Actor = Depends(current_actor)):
    challenge = await webauthn.take_challenge(f"webauthn:register:{user.id}")
    try:
        verified = verify_registration_response(
            credential=data.credential,
            expected_challenge=challenge,
            expected_rp_id=webauthn.rp_id(),
            expected_origin=settings.ISSUER,
        )
    except (WebAuthnException, ValueError, KeyError):
        raise webauthn.invalid_credential() from None
    async with in_transaction():
        await MfaFactor.create(
            user=user,
            type="webauthn",
            name=data.name,
            credential_id=bytes_to_base64url(verified.credential_id),
            public_key=bytes_to_base64url(verified.credential_public_key),
            sign_count=verified.sign_count,
            confirmed_at=utcnow(),
        )
        await record_audit(actor, "mfa.enable", target=str(user.public_id), details={"type": "webauthn"})
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{factor_id}/remove", status_code=status.HTTP_204_NO_CONTENT,
             summary="Remove a security key (needs my password)")
async def remove(
    factor_id: UUID,
    data: PasswordConfirm,
    user: User = Depends(current_user),
    actor: Actor = Depends(current_actor),
):
    await confirm_password(user, data.password)
    factor = await MfaFactor.get_or_none(public_id=factor_id, user_id=user.id, type="webauthn")
    if factor is None:
        raise not_found("Security key")
    async with in_transaction():
        await factor.delete()
        await record_audit(actor, "mfa.disable", target=str(user.public_id), details={"type": "webauthn"})
    return Response(status_code=status.HTTP_204_NO_CONTENT)
