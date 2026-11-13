"""WebAuthn (security key) helpers shared by sign-in and self-service registration."""

from urllib.parse import urlsplit

from redis.exceptions import RedisError
from webauthn.helpers import base64url_to_bytes, bytes_to_base64url

from app.identity.models import MfaFactor
from settings.settings import settings
from utilities.exceptions import AppError, unavailable
from utilities.redis import get_redis

CHALLENGE_SECONDS = 300
RP_NAME = "Auth Server"


def rp_id() -> str:
    return urlsplit(settings.ISSUER).hostname or "localhost"


def invalid_credential() -> AppError:
    return AppError(401, "invalid_credential", "The security key could not be verified")


async def store_challenge(key: str, challenge: bytes) -> None:
    try:
        await get_redis().set(key, bytes_to_base64url(challenge), ex=CHALLENGE_SECONDS)
    except RedisError:
        raise unavailable() from None


async def take_challenge(key: str) -> bytes:
    """Single use: a challenge is removed the moment it's read."""
    try:
        async with get_redis().pipeline(transaction=True) as pipe:
            pipe.get(key)
            pipe.delete(key)
            stored, _ = await pipe.execute()
    except RedisError:
        raise unavailable() from None
    if stored is None:
        raise invalid_credential()
    return base64url_to_bytes(stored)


async def user_keys(user_id: int) -> list[MfaFactor]:
    return await MfaFactor.filter(user_id=user_id, type="webauthn", confirmed_at__isnull=False)
