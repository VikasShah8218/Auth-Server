"""Liveness and readiness probes."""

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from database.config import ping_db
from utilities.common import logger
from utilities.redis import ping_redis

router = APIRouter(prefix="/health", tags=["Health"])


@router.get("/live", summary="The process is running. Never touches a dependency")
async def live() -> dict[str, str]:
    return {"status": "alive"}


@router.get("/ready", summary="Whether this replica can serve traffic. Only the database decides")
async def ready() -> JSONResponse:
    """Redis is reported, but losing it degrades login rather than stopping the replica, so it must not take
    the replica out of rotation."""
    checks = {"database": "up", "redis": "up"}

    try:
        await ping_db()
    except Exception as exc:
        logger.error("Readiness: database unavailable: %s", type(exc).__name__)
        checks["database"] = "down"

    try:
        await ping_redis()
    except Exception as exc:
        logger.warning("Readiness: redis unavailable: %s", type(exc).__name__)
        checks["redis"] = "down"

    healthy = checks["database"] == "up"
    return JSONResponse(
        {"status": "ready" if healthy else "unavailable", **checks},
        status_code=200 if healthy else 503,
    )
