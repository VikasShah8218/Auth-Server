"""Auth Server: central authentication and authorization (OAuth 2.1 / OpenID Connect).

Run:  py main.py
Docs: http://localhost:8000/docs   (not in production)
"""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from functools import partial

import uvicorn
from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from tortoise.contrib.fastapi import RegisterTortoise

from app.account.router import router as account_router
from app.account.webauthn_router import router as account_webauthn_router
from app.applications.router import router as applications_router
from app.audit.router import router as audit_router
from app.clients.router import router as clients_router
from app.console.router import router as console_router
from app.console.services import ensure_console_client
from app.dashboard.router import router as dashboard_router
from app.events.hub import hub
from app.events.router import admin_router as downstream_router
from app.events.router import apps_router as permission_map_router
from app.events.router import router as events_router
from app.events.services import downstream_report_tick, prune_outbox_tick
from app.health.router import router as health_router
from app.identity.router import admin_router as sessions_router
from app.identity.router import router as identity_router
from app.identity.services import cleanup_tick
from app.identity.webauthn_router import router as identity_webauthn_router
from app.keys.router import router as keys_router
from app.keys.services import ensure_signing_keys, key_rotation_tick
from app.oauth.router import router as oauth_router
from app.security.enforcement import apply_security_policy, policy_guard
from app.users.router import router as users_router
from database.config import TORTOISE_ORM
from settings.settings import settings
from utilities.common import configure_logging, logger, run_exclusive, run_periodic
from utilities.exceptions import register_error_handlers
from utilities.middleware import SecurityHeadersMiddleware
from utilities.redis import close_redis

# Background jobs: (name, advisory lock id, tick). The lock makes each one safe on any number of replicas.
JOBS = [
    ("cleanup", 725101, cleanup_tick),
    ("outbox-retention", 725102, prune_outbox_tick),
    ("key-rotation", 725103, key_rotation_tick),
    ("downstream-report", 725104, downstream_report_tick),
]


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    # Tortoise 1.x scopes connections to the task that opened them. Request tasks can't see a plain
    # Tortoise.init() from here, but RegisterTortoise shares them. Aerich owns the schema.
    async with RegisterTortoise(app, config=TORTOISE_ORM):
        await ensure_signing_keys()
        await ensure_console_client()
        hub.start()
        tasks = []
        if settings.RUN_JOBS:
            tasks = [
                asyncio.create_task(
                    run_periodic(name, settings.JOB_INTERVAL_SECONDS, partial(run_exclusive, lock_id, tick))
                )
                for name, lock_id, tick in JOBS
            ]
        logger.info("%s started (%s, jobs %s)", settings.APP_NAME, settings.ENVIRONMENT,
                    "on" if settings.RUN_JOBS else "off")
        try:
            yield
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            await hub.stop()
            await close_redis()


def create_app() -> FastAPI:
    configure_logging(settings.LOG_LEVEL)

    # Every route goes through the policy guard (app/security/enforcement.py), resolved from
    # app/security/policy.py. Routers carry their full prefix: never pass prefix= to include_router().
    app = FastAPI(
        title=settings.APP_NAME,
        version="0.1.0",
        lifespan=lifespan,
        dependencies=[Depends(policy_guard)],
        docs_url=None if settings.is_production else "/docs",
        redoc_url=None if settings.is_production else "/redoc",
        openapi_url=None if settings.is_production else "/openapi.json",
    )
    app.add_middleware(SecurityHeadersMiddleware, hsts=settings.is_production)
    if settings.CORS_ORIGINS:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.CORS_ORIGINS,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )
    register_error_handlers(app)

    for r in (
        health_router,
        oauth_router,
        identity_router,
        identity_webauthn_router,
        account_router,
        account_webauthn_router,
        console_router,
        events_router,
        permission_map_router,
        applications_router,
        users_router,
        sessions_router,
        clients_router,
        keys_router,
        audit_router,
        downstream_router,
        dashboard_router,
    ):
        app.include_router(r)

    apply_security_policy(app)
    return app


app = create_app()


if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host=settings.HOST,
        port=settings.PORT,
        proxy_headers=True,
        forwarded_allow_ips=settings.FORWARDED_ALLOW_IPS,
    )
