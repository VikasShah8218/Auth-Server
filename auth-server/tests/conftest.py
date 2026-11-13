"""Tests run against a real Postgres and Redis, with the schema built by the same
migrations that production uses. TEST_DATABASE_URL and TEST_REDIS_URL come from
the environment or from .env.
"""

import os
from urllib.parse import urlsplit

from dotenv import dotenv_values

_file = dotenv_values(".env")
_database_url = os.getenv("TEST_DATABASE_URL") or _file.get("TEST_DATABASE_URL") or ""
_redis_url = os.getenv("TEST_REDIS_URL") or _file.get("TEST_REDIS_URL") or ""

# The session fixture drops the whole schema, so this must never reach a real database.
if not urlsplit(_database_url).path.endswith("_test"):
    raise RuntimeError("TEST_DATABASE_URL must name a database ending in _test")
if not _redis_url:
    raise RuntimeError("TEST_REDIS_URL is required")

os.environ.update(
    ENVIRONMENT="test",
    DATABASE_URL=_database_url,
    REDIS_URL=_redis_url,
    MASTER_KEY="AAECAwQFBgcICQoLDA0ODxAREhMUFRYXGBkaGxwdHh8",
    ISSUER="http://localhost:8000",
    CORS_ORIGINS="[]",
    # A real server started by a test must not run background jobs against the test database.
    RUN_JOBS="false",
)

import httpx
import pytest
import pytest_asyncio
from aerich import Command
from tortoise import connections

from app.audit.services import Actor
from app.applications.models import Application
from app.applications.services import ADMIN_ROLE
from cli import create_admin
from settings.settings import get_settings
from database.config import TORTOISE_ORM, close_db, init_db
from utilities.redis import close_redis, get_redis
from app.users.models import User
from main import create_app
from app.tokens.schemas import Claims
from app.tokens import services as verifier
from app.keys.services import clear_key_cache, ensure_signing_keys

ADMIN_PASSWORD = "correct-horse-battery-staple"
ACTOR = Actor(id="test-actor", ip="127.0.0.1")

_KEEP_TABLES = {"aerich", "audit_logs"}


@pytest_asyncio.fixture(scope="session", autouse=True)
async def database():
    await init_db()
    connection = connections.get("default")
    await connection.execute_script("DROP SCHEMA public CASCADE; CREATE SCHEMA public;")
    await close_db()

    command = Command(tortoise_config=TORTOISE_ORM, location="./migrations")
    await command.init()
    await command.upgrade(run_in_transaction=True)
    await command.aclose()

    await init_db()
    yield
    await close_redis()
    await close_db()


async def clear_audit() -> None:
    """The trigger protects audit rows from everyone, including tests."""
    connection = connections.get("default")
    await connection.execute_script(
        "ALTER TABLE audit_logs DISABLE TRIGGER USER;"
        "TRUNCATE audit_logs RESTART IDENTITY;"
        "ALTER TABLE audit_logs ENABLE TRIGGER USER;"
    )


@pytest_asyncio.fixture(autouse=True)
async def clean_database():
    connection = connections.get("default")
    rows = await connection.execute_query_dict(
        "SELECT tablename FROM pg_tables WHERE schemaname = 'public'"
    )
    tables = [row["tablename"] for row in rows if row["tablename"] not in _KEEP_TABLES]
    await connection.execute_script(f"TRUNCATE {', '.join(tables)} RESTART IDENTITY CASCADE")
    await clear_audit()
    await get_redis().flushdb()
    clear_key_cache()
    await ensure_signing_keys()
    yield


@pytest.fixture(scope="session")
def app():
    return create_app()


@pytest_asyncio.fixture
async def client(app):
    # The real app, so routing and the policy guard are all under test.
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
        yield http


@pytest.fixture
def tokens(monkeypatch):
    """Stands in for signing until S3: a bearer string maps straight to claims."""
    issued: dict[str, Claims] = {}

    async def verify(token: str) -> Claims:
        return issued[token] if token in issued else await original(token)

    original = verifier.verify_access_token
    monkeypatch.setattr(verifier, "verify_access_token", verify)

    def issue(user: User | None = None, aud: str = "AUTH", roles=(ADMIN_ROLE,), pm: str = "") -> dict:
        token = f"token-{len(issued)}"
        issued[token] = Claims(
            sub=str(user.public_id) if user else "test-actor",
            sid="session",
            aud=aud,
            ver=0,
            pm=pm,
            roles=list(roles),
        )
        return {"Authorization": f"Bearer {token}"}

    return issue


@pytest_asyncio.fixture
async def admin_user() -> User:
    return await create_admin("root.admin", "root@example.com", ADMIN_PASSWORD)


@pytest_asyncio.fixture
async def admin(tokens, admin_user) -> dict:
    return tokens(admin_user)


@pytest.fixture
def settings():
    return get_settings()


async def make_app(client, admin, key="ANPR") -> Application:
    response = await client.post(
        "/v1/admin/applications", headers=admin, json={"key": key, "name": key.title()}
    )
    assert response.status_code == 201, response.text
    return await Application.get(key=key)
