"""One pooled Redis client per process. Redis holds only data that can be lost: limits and challenges."""

from redis.asyncio import Redis

from settings.settings import settings

_client: Redis | None = None


def get_redis() -> Redis:
    """Only close_redis() may close the client."""
    global _client
    if _client is None:
        _client = Redis.from_url(
            settings.REDIS_URL,
            decode_responses=True,
            # RESP2, because Redis below version 6 has no HELLO command.
            protocol=2,
            socket_connect_timeout=2,
            socket_timeout=2,
        )
    return _client


async def close_redis() -> None:
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None


async def ping_redis() -> None:
    await get_redis().ping()
