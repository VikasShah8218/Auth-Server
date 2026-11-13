"""TOTP factors and the short-lived MFA challenge that sits between the password and the second factor.

A factor protects nothing until its first valid code confirms it. Secrets are encrypted at rest, a code is
accepted once only, and guessing is limited per challenge and per user.
"""

import hmac
import json
import time

import pyotp
from redis.exceptions import RedisError
from tortoise.expressions import Q

from app.identity.models import MfaFactor
from app.users.models import User
from settings.settings import settings
from utilities.common import logger, utcnow
from utilities.crypto import decrypt, encrypt, hash_token, new_opaque_token
from utilities.exceptions import AppError, unavailable
from utilities.redis import get_redis

TOTP_PERIOD = 30
TOTP_ISSUER = "Auth Server"
_CHALLENGE_PREFIX = "mfa:challenge:"


def _secret_context(user_id: int) -> str:
    return f"totp:{user_id}"


def bad_code() -> AppError:
    return AppError(401, "invalid_code", "The code is not valid")


def challenge_expired() -> AppError:
    return AppError(401, "mfa_challenge_expired", "Sign in again to continue")


async def confirmed_factors(user_id: int) -> list[MfaFactor]:
    return await MfaFactor.filter(user_id=user_id, confirmed_at__isnull=False)


# Challenges


async def create_challenge(user: User, ip: str | None) -> str:
    raw = new_opaque_token()
    try:
        await get_redis().set(
            _CHALLENGE_PREFIX + hash_token(raw),
            json.dumps({"user_id": user.id, "ip": ip}),
            ex=settings.MFA_CHALLENGE_SECONDS,
        )
    except RedisError:
        raise unavailable() from None
    return raw


async def load_challenge(raw: str) -> dict:
    try:
        stored = await get_redis().get(_CHALLENGE_PREFIX + hash_token(raw))
    except RedisError:
        raise unavailable() from None
    if stored is None:
        raise challenge_expired()
    return json.loads(stored)


async def count_attempt(raw: str) -> None:
    """Charge one guess against the challenge, atomically. The challenge is destroyed at the limit, so
    guessing can't run for its whole lifetime."""
    key = _CHALLENGE_PREFIX + hash_token(raw) + ":attempts"
    try:
        attempts = await get_redis().incr(key)
        await get_redis().expire(key, settings.MFA_CHALLENGE_SECONDS)
        if attempts > settings.MFA_MAX_ATTEMPTS:
            await delete_challenge(raw)
            raise challenge_expired()
    except RedisError:
        raise unavailable() from None


async def delete_challenge(raw: str) -> None:
    try:
        await get_redis().delete(_CHALLENGE_PREFIX + hash_token(raw))
    except RedisError:
        logger.warning("Could not delete MFA challenge")


# TOTP


def _matching_step(secret: str, code: str) -> int | None:
    totp = pyotp.TOTP(secret, interval=TOTP_PERIOD)
    current = int(time.time()) // TOTP_PERIOD
    for step in (current - 1, current, current + 1):
        if hmac.compare_digest(totp.at(step * TOTP_PERIOD), code):
            return step
    return None


async def verify_totp(factor: MfaFactor, code: str) -> bool:
    secret = decrypt(factor.encrypted_secret, _secret_context(factor.user_id))
    step = _matching_step(secret, code)
    if step is None:
        return False
    # One conditional UPDATE, so two simultaneous uses of a code can't both pass.
    claimed = await MfaFactor.filter(
        Q(id=factor.id) & (Q(last_used_step__isnull=True) | Q(last_used_step__lt=step))
    ).update(last_used_step=step)
    return claimed == 1


async def verify_any_totp(user_id: int, code: str) -> bool:
    factors = await MfaFactor.filter(user_id=user_id, type="totp", confirmed_at__isnull=False)
    for factor in factors:
        if await verify_totp(factor, code):
            return True
    return False


async def begin_totp_enrolment(user: User) -> tuple[str, str]:
    """Create or replace the unconfirmed factor. Returns the secret and its otpauth URI."""
    if await MfaFactor.filter(user_id=user.id, type="totp", confirmed_at__isnull=False).exists():
        raise AppError(409, "mfa_already_enabled", "TOTP is already enabled")
    await MfaFactor.filter(user_id=user.id, type="totp", confirmed_at__isnull=True).delete()
    secret = pyotp.random_base32()
    await MfaFactor.create(user=user, type="totp", encrypted_secret=encrypt(secret, _secret_context(user.id)))
    uri = pyotp.TOTP(secret, interval=TOTP_PERIOD).provisioning_uri(name=user.username, issuer_name=TOTP_ISSUER)
    return secret, uri


async def confirm_totp_enrolment(user: User, code: str) -> None:
    factor = await MfaFactor.get_or_none(user_id=user.id, type="totp", confirmed_at__isnull=True)
    if factor is None:
        raise AppError(409, "no_enrolment", "Start TOTP setup first")
    if not await verify_totp(factor, code):
        raise bad_code()
    factor.confirmed_at = utcnow()
    await factor.save(update_fields=["confirmed_at"])


async def remove_totp(user: User, code: str) -> None:
    factor = await MfaFactor.get_or_none(user_id=user.id, type="totp", confirmed_at__isnull=False)
    if factor is None:
        raise AppError(404, "not_found", "TOTP is not enabled")
    if not await verify_totp(factor, code):
        raise bad_code()
    await factor.delete()
