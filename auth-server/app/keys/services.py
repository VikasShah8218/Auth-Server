"""Signing keys.

Lifecycle: next -> active -> retired -> expired, or revoked at once on a leak.

A "next" key is published in JWKS before it signs anything, so downstream servers already hold it when it
becomes active. A retired key stays published until every token it signed has expired.
"""

import json
import secrets
import time
from datetime import timedelta
from typing import Protocol

from joserfc.jwk import ECKey
from tortoise import connections
from tortoise.transactions import in_transaction

from app.applications.models import Application
from app.events.services import KEYS_CHANNEL, publish_event
from app.keys.models import SigningKey
from settings.settings import settings
from utilities.common import logger, utcnow
from utilities.crypto import decrypt, encrypt
from utilities.exceptions import AppError

ALGORITHM = "ES256"
PUBLISHED = ("next", "active", "retired")

_CACHE_SECONDS = 30
_UNKNOWN_KID_RELOAD_SECONDS = 5
_KEY_LOCK = 725001

_verification: dict[str, ECKey] = {}
_verification_loaded = 0.0
_signing: tuple[ECKey, float] | None = None


class KeyProvider(Protocol):
    """Where private keys are protected. A Vault provider can replace this one."""

    def seal(self, kid: str, private_jwk: str) -> str: ...

    def open(self, kid: str, sealed: str) -> str: ...


class LocalKeyProvider:
    """Encrypts private keys under MASTER_KEY, which never enters the database."""

    def seal(self, kid: str, private_jwk: str) -> str:
        return encrypt(private_jwk, f"signing-key:{kid}")

    def open(self, kid: str, sealed: str) -> str:
        return decrypt(sealed, f"signing-key:{kid}")


provider: KeyProvider = LocalKeyProvider()


# Process caches


def clear_key_cache() -> None:
    global _verification_loaded, _signing
    _verification.clear()
    _verification_loaded = 0.0
    _signing = None


async def _lock_keys() -> None:
    """Serialises key changes across replicas until commit."""
    await connections.get("default").execute_query("SELECT pg_advisory_xact_lock($1)", [_KEY_LOCK])


async def _notify_key_change() -> None:
    """Every replica clears its key cache (app/events/hub.py), so a revoked key stops working everywhere."""
    await connections.get("default").execute_query("SELECT pg_notify($1, $2)", [KEYS_CHANNEL, "changed"])


# Lifecycle


async def _create_key(status: str) -> SigningKey:
    kid = secrets.token_urlsafe(12)
    key = ECKey.generate_key("P-256", parameters={"kid": kid, "use": "sig", "alg": ALGORITHM}, private=True)
    return await SigningKey.create(
        kid=kid,
        algorithm=ALGORITHM,
        encrypted_private_key=provider.seal(kid, json.dumps(key.as_dict(private=True))),
        public_jwk=key.as_dict(private=False),
        status=status,
        activated_at=utcnow() if status == "active" else None,
    )


async def ensure_signing_keys() -> None:
    """Make sure an active and a next key exist. Safe to run on every replica."""
    if await SigningKey.filter(status="active").exists() and await SigningKey.filter(status="next").exists():
        return
    async with in_transaction():
        await _lock_keys()
        if not await SigningKey.filter(status="active").exists():
            await _create_key("active")
        if not await SigningKey.filter(status="next").exists():
            await _create_key("next")


def _retire_after() -> timedelta:
    longest = max(settings.ACCESS_TOKEN_MINUTES, settings.SERVICE_TOKEN_MINUTES, settings.EXCHANGE_TOKEN_MINUTES)
    return timedelta(minutes=longest + 5)


async def _all_app_ids() -> list[int]:
    return await Application.all().values_list("id", flat=True)


async def _promote_next() -> SigningKey:
    promoted = await SigningKey.filter(status="next").first()
    if promoted is None:
        return await _create_key("active")
    promoted.status = "active"
    promoted.activated_at = utcnow()
    await promoted.save(update_fields=["status", "activated_at"])
    return promoted


async def rotate_keys() -> SigningKey:
    """next becomes active, active retires, and a new next is generated."""
    async with in_transaction():
        await _lock_keys()
        await SigningKey.filter(status="active").update(status="retired", not_after=utcnow() + _retire_after())
        promoted = await _promote_next()
        await _create_key("next")
        await publish_event(await _all_app_ids(), "key.rotated", {"kid": promoted.kid})
        await _notify_key_change()
    clear_key_cache()
    return promoted


async def revoke_key(kid: str) -> None:
    """A leaked key: out of JWKS now, and every downstream server drops it."""
    async with in_transaction():
        await _lock_keys()
        key = await SigningKey.get_or_none(kid=kid)
        if key is None or key.status == "expired":
            raise AppError(404, "not_found", "Signing key not found")
        was_active = key.status == "active"
        key.status = "revoked"
        await key.save(update_fields=["status"])
        await publish_event(await _all_app_ids(), "key.rotated", {"kid": kid, "revoked": True})
        if was_active:
            await _promote_next()
            await _create_key("next")
        await _notify_key_change()
    clear_key_cache()


async def expire_retired_keys() -> int:
    return await SigningKey.filter(status="retired", not_after__lte=utcnow()).update(status="expired")


# Using keys


def _load_private(row: SigningKey) -> ECKey:
    return ECKey.import_key(json.loads(provider.open(row.kid, row.encrypted_private_key)))


async def signing_key() -> ECKey:
    global _signing
    if _signing is not None and time.monotonic() - _signing[1] < _CACHE_SECONDS:
        return _signing[0]
    row = await SigningKey.filter(status="active").first()
    if row is None:
        raise AppError(503, "signing_unavailable", "Tokens can't be issued right now")
    key = _load_private(row)
    _signing = (key, time.monotonic())
    return key


async def _reload_verification() -> None:
    global _verification_loaded
    rows = await SigningKey.filter(status__in=PUBLISHED)
    _verification.clear()
    _verification.update({row.kid: ECKey.import_key(row.public_jwk) for row in rows})
    _verification_loaded = time.monotonic()


async def verification_key(kid: str) -> ECKey | None:
    age = time.monotonic() - _verification_loaded
    if age >= _CACHE_SECONDS or (kid not in _verification and age >= _UNKNOWN_KID_RELOAD_SECONDS):
        await _reload_verification()
    return _verification.get(kid)


async def public_jwks() -> dict:
    rows = await SigningKey.filter(status__in=PUBLISHED).order_by("id")
    return {"keys": [row.public_jwk for row in rows]}


# Background job


async def key_rotation_tick() -> None:
    """Keep an active and a next key, expire retired keys, and rotate every KEY_ROTATION_DAYS."""
    await ensure_signing_keys()
    await expire_retired_keys()
    active = await SigningKey.filter(status="active").first()
    age = timedelta(days=settings.KEY_ROTATION_DAYS)
    if active is not None and active.activated_at + age <= utcnow():
        promoted = await rotate_keys()
        logger.info("Signing key rotated to %s", promoted.kid)
