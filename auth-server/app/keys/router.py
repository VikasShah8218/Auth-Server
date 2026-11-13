"""Signing key administration. Rotation also happens on schedule (key_rotation_tick)."""

from datetime import timedelta

from fastapi import APIRouter, Depends, Response, status
from tortoise.transactions import in_transaction

from app.audit.services import Actor, record_audit
from app.keys import services
from app.keys.models import SigningKey
from app.keys.schemas import SigningKeyOut
from app.security.deps import current_actor
from settings.settings import settings

router = APIRouter(prefix="/v1/admin/keys", tags=["Admin: Signing keys"])


def _key_view(key: SigningKey) -> SigningKeyOut:
    rotates_at = None
    if key.status == "active" and key.activated_at is not None:
        rotates_at = key.activated_at + timedelta(days=settings.KEY_ROTATION_DAYS)
    return SigningKeyOut(
        kid=key.kid,
        algorithm=key.algorithm,
        status=key.status,
        activated_at=key.activated_at,
        not_after=key.not_after,
        created_at=key.created_at,
        rotates_at=rotates_at,
    )


@router.get("", response_model=list[SigningKeyOut], summary="Published and revoked keys, newest first")
async def list_keys():
    return [_key_view(key) for key in await SigningKey.exclude(status="expired").order_by("-id")]


@router.post("/rotate", response_model=SigningKeyOut, summary="Rotate now: next becomes active")
async def rotate(actor: Actor = Depends(current_actor)):
    key = await services.rotate_keys()
    async with in_transaction():
        await record_audit(actor, "key.rotate", target=key.kid)
    return _key_view(key)


@router.delete("/{kid}", status_code=status.HTTP_204_NO_CONTENT,
               summary="Revoke a leaked key: every token it signed stops working")
async def revoke(kid: str, actor: Actor = Depends(current_actor)):
    await services.revoke_key(kid)
    async with in_transaction():
        await record_audit(actor, "key.revoke", target=kid)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
