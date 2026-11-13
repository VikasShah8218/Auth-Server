"""Small helpers shared by every module: time, logging, background loops."""

import asyncio
import logging
import sys
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone

from tortoise import connections
from tortoise.transactions import in_transaction

logger = logging.getLogger("auth")


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def configure_logging(level: str = "INFO") -> None:
    """Log to stdout only. Containers collect it, and no log file can fill a disk."""
    if logger.handlers:
        return
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s"))
    logger.addHandler(handler)
    logger.setLevel(level)
    logger.propagate = False


def client_ip(request) -> str | None:
    return request.client.host if request.client else None


async def run_exclusive(lock_id: int, func: Callable[[], Awaitable[None]]) -> bool:
    """Run `func` while holding a Postgres advisory lock for its transaction.

    Returns False, without running it, when another replica already holds this job. That makes every
    background job safe to schedule on any number of replicas.
    """
    async with in_transaction():
        rows = await connections.get("default").execute_query_dict(
            "SELECT pg_try_advisory_xact_lock($1) AS locked", [lock_id]
        )
        if not rows[0]["locked"]:
            return False
        await func()
    return True


async def run_periodic(name: str, interval: float, func: Callable[[], Awaitable[None]]) -> None:
    """Run `func` forever every `interval` seconds; errors are logged, never fatal."""
    logger.info("Background loop '%s' started (every %ss)", name, interval)
    while True:
        try:
            await func()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Background loop '%s' failed", name)
        await asyncio.sleep(interval)
