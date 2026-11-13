"""Attempt counters in Redis. They fail closed: with Redis down there is no way to stop password guessing,
so the attempt is refused rather than allowed through."""

from redis.exceptions import RedisError

from settings.settings import settings
from utilities.common import logger
from utilities.exceptions import AppError, unavailable
from utilities.redis import get_redis


def _blocked(retry_after: int) -> AppError:
    return AppError(
        429,
        "too_many_attempts",
        "Too many attempts. Try again later.",
        headers={"Retry-After": str(retry_after)},
    )


async def check(key: str, limit: int) -> None:
    """Refuse when the counter is at its limit, without counting this attempt."""
    try:
        count = await get_redis().get(key)
        ttl = await get_redis().ttl(key) if count else 0
    except RedisError as exc:
        logger.error("Rate limiter unavailable: %s", type(exc).__name__)
        raise unavailable() from None
    if count and int(count) >= limit:
        raise _blocked(ttl if ttl > 0 else settings.RATE_WINDOW_SECONDS)


async def record(key: str) -> int:
    """Count one attempt and return the total."""
    try:
        async with get_redis().pipeline(transaction=True) as pipe:
            pipe.incr(key)
            pipe.ttl(key)
            count, ttl = await pipe.execute()
        if ttl < 0:
            await get_redis().expire(key, settings.RATE_WINDOW_SECONDS)
    except RedisError as exc:
        logger.error("Rate limiter unavailable: %s", type(exc).__name__)
        raise unavailable() from None
    return count


async def hit(key: str, limit: int) -> None:
    """Count one attempt and refuse it above the limit."""
    if await record(key) > limit:
        raise _blocked(settings.RATE_WINDOW_SECONDS)


async def clear(key: str) -> None:
    try:
        await get_redis().delete(key)
    except RedisError:
        # The counter expires by itself, so losing this delete is harmless.
        logger.warning("Could not clear rate limit counter")
