"""S0 exit checks: startup validation, error format and health."""

import base64
import os

import pytest
from pydantic import ValidationError
from tortoise.exceptions import OperationalError

from app.health import router as health
from settings.settings import Settings

GOOD_KEY = base64.urlsafe_b64encode(os.urandom(32)).decode()
BASE = {
    "ENVIRONMENT": "production",
    "DATABASE_URL": "postgres://auth:Str0ng-unique-pass@db:5432/auth",
    "REDIS_URL": "redis://redis:6379/0",
    "MASTER_KEY": GOOD_KEY,
    "ISSUER": "https://auth.example.com",
}


def build(**overrides) -> Settings:
    values = {**BASE, **overrides}
    return Settings(_env_file=None, **{k: v for k, v in values.items() if v is not None})


def test_valid_production_settings_load():
    assert build().is_production


@pytest.mark.parametrize("missing", ["DATABASE_URL", "REDIS_URL", "MASTER_KEY"])
def test_required_setting_missing_stops_startup(missing, monkeypatch):
    monkeypatch.delenv(missing, raising=False)
    with pytest.raises(ValidationError):
        build(**{missing: None})


@pytest.mark.parametrize(
    "key",
    [
        "SHAH-SUPREME-SECRET-KEY",  # the old server's default
        "short",
        base64.urlsafe_b64encode(b"\x00" * 32).decode(),  # right length, no randomness
    ],
)
def test_weak_master_key_stops_startup(key):
    with pytest.raises(ValidationError):
        build(MASTER_KEY=key)


@pytest.mark.parametrize("password", ["2024", "postgres", "changeme"])
def test_default_database_password_stops_production(password):
    with pytest.raises(ValidationError):
        build(DATABASE_URL=f"postgres://postgres:{password}@db:5432/auth")


def test_database_url_without_password_stops_production():
    with pytest.raises(ValidationError):
        build(DATABASE_URL="postgres://auth@db:5432/auth")


def test_wildcard_cors_stops_startup():
    with pytest.raises(ValidationError):
        build(CORS_ORIGINS=["*"])


def test_http_issuer_stops_production():
    with pytest.raises(ValidationError):
        build(ISSUER="http://auth.example.com")


def test_validation_error_does_not_print_the_secret():
    with pytest.raises(ValidationError) as caught:
        build(MASTER_KEY="SHAH-SUPREME-SECRET-KEY")
    assert "SHAH-SUPREME" not in str(caught.value)


async def test_live_needs_no_dependency(client):
    response = await client.get("/health/live")
    assert response.status_code == 200
    assert response.json() == {"status": "alive"}


async def test_ready_reports_both_dependencies(client):
    response = await client.get("/health/ready")
    assert response.status_code == 200
    assert response.json() == {"status": "ready", "database": "up", "redis": "up"}


async def test_ready_fails_when_database_is_down(client, monkeypatch):
    async def down():
        raise OperationalError("password=hunter2 connection refused")

    monkeypatch.setattr(health, "ping_db", down)
    response = await client.get("/health/ready")
    assert response.status_code == 503
    assert response.json()["database"] == "down"
    assert "hunter2" not in response.text


async def test_ready_stays_up_when_only_redis_is_down(client, monkeypatch):
    async def down():
        raise ConnectionError("redis refused")

    monkeypatch.setattr(health, "ping_redis", down)
    response = await client.get("/health/ready")
    assert response.status_code == 200
    assert response.json()["redis"] == "down"


async def test_unknown_error_hides_its_text(app, client, admin, monkeypatch):
    from app.applications import services as service

    async def boom(*_):
        raise RuntimeError("secret database detail")

    monkeypatch.setattr(service, "get_app", boom)
    response = await client.get("/v1/admin/applications/ANPR", headers=admin)
    assert response.status_code == 500
    assert response.json()["detail"]["code"] == "internal_error"
    assert "secret" not in response.text
