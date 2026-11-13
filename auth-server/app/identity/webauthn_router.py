"""Sign-in with a security key, as the second step after the password."""

from fastapi import APIRouter, Request, Response
from tortoise.expressions import Q
from webauthn import generate_authentication_options, options_to_json, verify_authentication_response
from webauthn.helpers import base64url_to_bytes
from webauthn.helpers.exceptions import WebAuthnException
from webauthn.helpers.structs import PublicKeyCredentialDescriptor

from app.identity import mfa, webauthn
from app.identity.models import MfaFactor
from app.identity.schemas import LoginResponse, WebAuthnLoginOptions, WebAuthnLoginVerify
from app.identity.services import finish_login
from app.users.models import User
from settings.settings import settings
from utilities import ratelimit
from utilities.crypto import hash_token

router = APIRouter(prefix="/v1/identity/webauthn", tags=["Identity"])


@router.post("/options", summary="WebAuthn assertion options for an MFA challenge")
async def authentication_options(data: WebAuthnLoginOptions) -> Response:
    stored = await mfa.load_challenge(data.challenge)
    factors = await webauthn.user_keys(stored["user_id"])
    if not factors:
        raise webauthn.invalid_credential()
    options = generate_authentication_options(
        rp_id=webauthn.rp_id(),
        allow_credentials=[PublicKeyCredentialDescriptor(id=base64url_to_bytes(f.credential_id)) for f in factors],
    )
    await webauthn.store_challenge(f"webauthn:login:{hash_token(data.challenge)}", options.challenge)
    return Response(options_to_json(options), media_type="application/json")


@router.post("/verify", response_model=LoginResponse, summary="Finish sign-in with a security key")
async def authentication_verify(data: WebAuthnLoginVerify, request: Request, response: Response):
    stored = await mfa.load_challenge(data.challenge)
    await mfa.count_attempt(data.challenge)
    mfa_key = f"rate:mfa:user:{stored['user_id']}"
    await ratelimit.hit(mfa_key, settings.MFA_MAX_ATTEMPTS * 2)

    user = await User.get_or_none(id=stored["user_id"], is_active=True)
    if user is None:
        raise webauthn.invalid_credential()
    factor = await MfaFactor.get_or_none(
        user_id=user.id, type="webauthn", credential_id=str(data.credential.get("id", ""))
    )
    if factor is None or factor.confirmed_at is None:
        raise webauthn.invalid_credential()

    challenge = await webauthn.take_challenge(f"webauthn:login:{hash_token(data.challenge)}")
    try:
        verified = verify_authentication_response(
            credential=data.credential,
            expected_challenge=challenge,
            expected_rp_id=webauthn.rp_id(),
            expected_origin=settings.ISSUER,
            credential_public_key=base64url_to_bytes(factor.public_key),
            credential_current_sign_count=factor.sign_count,
        )
    except (WebAuthnException, ValueError, KeyError):
        raise webauthn.invalid_credential() from None

    # Conditional, so a cloned key can't pass by racing the real one.
    updated = await MfaFactor.filter(
        Q(id=factor.id) & (Q(sign_count__lt=verified.new_sign_count) | Q(sign_count=0))
    ).update(sign_count=verified.new_sign_count)
    if updated != 1:
        raise webauthn.invalid_credential()

    await mfa.delete_challenge(data.challenge)
    await ratelimit.clear(mfa_key)
    return await finish_login(request, response, user, ["pwd", "hwk"])
