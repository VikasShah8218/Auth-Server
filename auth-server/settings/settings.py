"""Validated configuration, loaded from `.env`. An invalid value stops the process at startup.

REDIS_URL and MASTER_KEY have no defaults, so a server can't start by accident on a value that exists only in
this file. In production the database password is checked against a list of known defaults.
"""

import base64
import binascii
from functools import lru_cache
from pathlib import Path
from typing import Literal
from urllib.parse import quote, urlsplit

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent

# Passwords that must never reach production, including the old server's default.
_KNOWN_WEAK_PASSWORDS = {"", "2024", "admin", "changeme", "password", "postgres", "secret"}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=BASE_DIR / ".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
        # Without this, a validation error would print the rejected secret.
        hide_input_in_errors=True,
    )

    # Server
    APP_NAME: str = "Auth Server"
    # Production is the default so that a forgotten setting gets the strict rules.
    ENVIRONMENT: Literal["development", "test", "production"] = "production"
    HOST: str = "0.0.0.0"
    PORT: int = 8000
    LOG_LEVEL: str = "INFO"
    # JSON list of exact browser origins. "*" is refused. The console is same-origin and needs none.
    CORS_ORIGINS: list[str] = []
    # Proxies whose X-Forwarded-For is trusted, so rate limits and audit see the real client address.
    FORWARDED_ALLOW_IPS: str = "127.0.0.1"

    # Database (PostgreSQL)
    DB_HOST: str = "localhost"
    DB_PORT: int = 5432
    DB_USER: str = "postgres"
    DB_PASSWORD: str = ""
    DB_NAME: str = "auth"
    # Optional full override, e.g. "postgres://user:pass@host:5432/auth".
    DATABASE_URL: str | None = None

    # Redis (rate limits and short-lived login challenges only)
    REDIS_URL: str

    # 32 random bytes in base64url. Encrypts signing keys, TOTP secrets and console tokens at rest.
    MASTER_KEY: str

    # Issuer: the address browsers use for this server
    ISSUER: str = "http://localhost:8000"
    AUTH_APP_KEY: str = "AUTH"
    LOGIN_PAGE_PATH: str = "/login"

    # Token and session lifetimes
    ACCESS_TOKEN_MINUTES: int = 10
    SERVICE_TOKEN_MINUTES: int = 15
    EXCHANGE_TOKEN_MINUTES: int = 5
    AUTH_CODE_SECONDS: int = 60
    REFRESH_GRACE_SECONDS: int = 10
    SESSION_DAYS: int = 14

    # Keys, events and downstream sync
    KEY_ROTATION_DAYS: int = 30
    EVENT_RETENTION_DAYS: int = 7
    DOWNSTREAM_LAG_SECONDS: int = 60

    # Rate limits and MFA
    LOGIN_LIMIT_PER_ACCOUNT: int = 5
    LOGIN_LIMIT_PER_IP: int = 30
    TOKEN_LIMIT_PER_IP: int = 120
    RATE_WINDOW_SECONDS: int = 900
    MFA_MAX_ATTEMPTS: int = 5
    MFA_CHALLENGE_SECONDS: int = 300

    # Background jobs (cleanup, outbox pruning, key rotation, downstream report)
    # Safe on every replica: each job takes a Postgres advisory lock, so only one runs it at a time.
    RUN_JOBS: bool = True
    JOB_INTERVAL_SECONDS: int = 60

    @field_validator("MASTER_KEY")
    @classmethod
    def _check_master_key(cls, value: str) -> str:
        try:
            raw = base64.urlsafe_b64decode(value.encode() + b"=" * (-len(value) % 4))
        except (binascii.Error, ValueError):
            raise ValueError("MASTER_KEY must be base64url") from None
        if len(raw) != 32:
            raise ValueError("MASTER_KEY must decode to exactly 32 bytes")
        if len(set(raw)) < 16:
            raise ValueError("MASTER_KEY is not random enough")
        return value

    @field_validator("CORS_ORIGINS")
    @classmethod
    def _check_cors(cls, value: list[str]) -> list[str]:
        if "*" in value:
            raise ValueError("CORS_ORIGINS must list exact origins, not *")
        return value

    @model_validator(mode="after")
    def _check_production(self) -> "Settings":
        if self.ENVIRONMENT != "production":
            return self
        password = urlsplit(self.db_url).password or ""
        if password.lower() in _KNOWN_WEAK_PASSWORDS:
            raise ValueError("The database has a missing or known default password")
        if not self.ISSUER.startswith("https://"):
            raise ValueError("ISSUER must use https in production")
        return self

    @property
    def is_production(self) -> bool:
        return self.ENVIRONMENT == "production"

    @property
    def db_url(self) -> str:
        if self.DATABASE_URL:
            return self.DATABASE_URL
        return (
            f"postgres://{quote(self.DB_USER)}:{quote(self.DB_PASSWORD)}"
            f"@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}"
        )

    @property
    def master_key_bytes(self) -> bytes:
        key = self.MASTER_KEY
        return base64.urlsafe_b64decode(key.encode() + b"=" * (-len(key) % 4))


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
