"""Runs the Auth Server for the end-to-end tests, on a throwaway database.

    <auth-server python> tests/e2e/serve_api.py

Creates the database `auth_e2e` next to the server's TEST_DATABASE_URL (dropping its schema first), applies
the migrations, creates the administrator `e2e.admin`, then serves the API on 127.0.0.1:8010 with ISSUER set
to the e2e client origin (http://localhost:5182). Never touches the development database.
"""

import asyncio
import os
import sys
from pathlib import Path

SERVER_DIR = Path(__file__).resolve().parents[3] / "auth-server"
ADMIN = ("e2e.admin", "e2e-admin@example.com", "e2e-admin-password-1")
PORT = 8010
CLIENT_ORIGIN = "http://localhost:5182"

sys.path.insert(0, str(SERVER_DIR))
os.chdir(SERVER_DIR)

from dotenv import dotenv_values  # noqa: E402

env = dotenv_values(SERVER_DIR / ".env")
test_url = env.get("TEST_DATABASE_URL") or ""
if not test_url.endswith("_test"):
    raise SystemExit("auth-server/.env needs TEST_DATABASE_URL ending in _test")
e2e_url = test_url.rsplit("/", 1)[0] + "/auth_e2e"
redis_url = (env.get("TEST_REDIS_URL") or "redis://127.0.0.1:6379/15").rsplit("/", 1)[0] + "/14"

os.environ.update(
    ENVIRONMENT="development",
    DATABASE_URL=e2e_url,
    REDIS_URL=redis_url,
    ISSUER=CLIENT_ORIGIN,
    RUN_JOBS="false",
    CORS_ORIGINS="[]",
)


async def prepare() -> None:
    import asyncpg
    from redis.asyncio import Redis

    connection = await asyncpg.connect(test_url)
    if not await connection.fetchval("SELECT 1 FROM pg_database WHERE datname = 'auth_e2e'"):
        await connection.execute("CREATE DATABASE auth_e2e")
    await connection.close()

    connection = await asyncpg.connect(e2e_url)
    await connection.execute("DROP SCHEMA public CASCADE; CREATE SCHEMA public;")
    await connection.close()

    redis = Redis.from_url(redis_url, protocol=2)
    await redis.flushdb()
    await redis.aclose()

    from aerich import Command

    from database.config import TORTOISE_ORM, close_db, init_db

    command = Command(tortoise_config=TORTOISE_ORM, location="./migrations")
    await command.init()
    await command.upgrade(run_in_transaction=True)
    await command.aclose()

    await init_db()
    from cli import create_admin

    await create_admin(*ADMIN)
    await close_db()


if __name__ == "__main__":
    asyncio.run(prepare())
    import uvicorn

    uvicorn.run("main:app", host="127.0.0.1", port=PORT, log_level="warning")
