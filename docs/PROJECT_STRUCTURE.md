# Base Project Structure (FastAPI + Tortoise ORM)

A reusable folder layout for Python backend services. Every new project starts from this skeleton and keeps
the same names and responsibilities, so any project is familiar at a glance.

---

## 1. Top-level layout

```
<project_root>/
├── main.py                  # Entry point: builds the FastAPI app, wires routers, lifespan, middleware
├── app/                     # All feature modules ("apps"), one sub-package per domain
│   ├── __init__.py
│   ├── home/                # example module
│   ├── users/               # example module
│   └── <module>/            # ...one folder per feature
├── settings/                # Configuration (env-driven)
│   ├── __init__.py
│   └── settings.py
├── database/                # Database / ORM configuration
│   ├── __init__.py
│   └── config.py
├── utilities/               # Shared, feature-agnostic helpers
│   ├── __init__.py
│   ├── common.py
│   └── pagination.py
├── migrations/              # Generated DB migrations (Aerich)
│   └── models/
│       └── <n>_<timestamp>_<name>.py
├── tests/                   # Pytest suite
│   ├── __init__.py
│   ├── conftest.py
│   └── test_<module>.py
├── docs/                    # Design notes, plans, this file
├── .env                     # Local config (never committed)
├── .env.example             # Every env key, documented, no secrets (committed)
├── .gitignore
├── pyproject.toml           # Tool config (Aerich, etc.)
├── pytest.ini
└── requirements.txt
```

**Rule of thumb:** `main.py` sits at the root; feature code lives under `app/`; cross-cutting infrastructure
(`settings/`, `database/`, `utilities/`) sits at the root beside it.

---

## 2. Feature modules — `app/<module>/`

Each feature (domain) is a self-contained package. Use only the files the module needs; the names are fixed.

```
app/<module>/
├── __init__.py
├── models.py      # ORM models (Tortoise Model classes) for this domain
├── schemas.py     # Pydantic request/response models (…Create, …Update, …Out)
├── router.py      # FastAPI APIRouter: HTTP endpoints only, thin
├── services.py    # Business logic, queries, transactions, background "tick" functions
└── utils.py       # Small pure helpers used only inside this module
```

### Responsibilities

| File          | Contains                                                                 | Should NOT contain                        |
|---------------|--------------------------------------------------------------------------|-------------------------------------------|
| `models.py`   | `Model` subclasses, fields, relations, enums tied to the table           | HTTP code, request validation             |
| `schemas.py`  | Pydantic `BaseModel` classes, field validators, input/output shapes      | DB queries                                |
| `router.py`   | `router = APIRouter(prefix="/api/v1/<module>", tags=["<Module>"])`, endpoint functions, `Depends`, `response_model` | Heavy logic — delegate to `services` |
| `services.py` | Domain logic, multi-step DB work, `in_transaction`, periodic jobs        | FastAPI route decorators                  |
| `utils.py`    | Stateless helper functions (parsing, formatting, calculations)           | DB access, side effects                   |

### Optional extra files (when a module grows)

Add them inside the same module folder, named by what they do:

| Pattern                         | Use when                                                    |
|---------------------------------|-------------------------------------------------------------|
| `deps.py`                       | Reusable FastAPI dependencies (auth guard, current user)    |
| `client.py`                     | Outbound HTTP client to another service                     |
| `permissions.py` / `policy.py`  | Access rules for the module                                 |
| `<sub>_router.py` + `<sub>_schemas.py` | A module has a clearly separate sub-area (e.g. `admin_router.py`, `admin_schemas.py`) |

### Routers: public vs internal

A module may expose two routers from `router.py`:

```python
router = APIRouter(prefix="/api/v1/<module>", tags=["<Module>"])            # public API
internal_router = APIRouter(prefix="/internal/v1/<module>", tags=["Internal"])  # service-to-service
```

### Import direction

```
router.py  ──►  services.py  ──►  models.py
    │               │
    └──► schemas.py ◄┘          utils.py (module-local)  ·  utilities/ (shared)
```

- Always import with absolute paths from the project root: `from app.users.models import User`.
- A module may import another module's `models`/`services` when needed; never import from `main.py`.
- Shared helpers go in `utilities/`, not copied between modules.

---

## 3. `settings/settings.py`

One `pydantic-settings` class, loaded from `.env`, exposed as a cached singleton.

```python
from functools import lru_cache
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=BASE_DIR / ".env", env_file_encoding="utf-8", extra="ignore")

    # Server
    APP_NAME: str = "My Service"
    HOST: str = "0.0.0.0"
    PORT: int = 8000
    LOG_LEVEL: str = "INFO"
    CORS_ORIGINS: str = "*"

    # Database
    DB_HOST: str = "localhost"
    DB_PORT: int = 5432
    DB_USER: str = "postgres"
    DB_PASSWORD: str = ""
    DB_NAME: str = "app"
    DATABASE_URL: str | None = None      # full override, e.g. "sqlite://:memory:" for tests

    @property
    def cors_origins(self) -> list[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]

    @property
    def db_url(self) -> str:
        return self.DATABASE_URL or (
            f"postgres://{self.DB_USER}:{self.DB_PASSWORD}@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}"
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
```

Conventions:
- Settings keys are `UPPER_CASE`, grouped with comments (`# Server`, `# Database`, …).
- Derived values are `@property` in lower_case.
- Every key added here is also added (with a comment, no secret) to `.env.example`.
- Code reads config only via `from settings.settings import settings`.

---

## 4. `database/config.py`

Single source of the ORM config, used by both the app and Aerich.

```python
from settings.settings import settings

APP_MODELS = [
    "app.users.models",
    "app.home.models",
    # add every module that has a models.py
]

TORTOISE_ORM = {
    "connections": {"default": settings.db_url},
    "apps": {
        "models": {
            "models": [*APP_MODELS, "aerich.models"],
            "default_connection": "default",
        },
    },
    "use_tz": True,
    "timezone": "UTC",
}
```

When a new module gets a `models.py`, register it in `APP_MODELS`.

---

## 5. `migrations/` + `pyproject.toml`

Migrations are managed by **Aerich**:

```toml
[tool.aerich]
tortoise_orm = "database.config.TORTOISE_ORM"
location = "./migrations"
src_folder = "./."
```

```bash
aerich init -t database.config.TORTOISE_ORM   # once
aerich init-db                                # first migration
aerich migrate --name <change_name>           # after model changes
aerich upgrade                                # apply
```

Files are generated as `migrations/models/<n>_<timestamp>_<change_name>.py` — never edit old ones.

---

## 6. `utilities/`

Feature-agnostic helpers shared by all modules, e.g.:

| File            | Typical content                                                  |
|-----------------|------------------------------------------------------------------|
| `common.py`     | `utcnow()`, `run_periodic(name, interval, func)` for background loops |
| `pagination.py` | `Page[T]` response model, `PageParams` dependency, `paginate(queryset, params)` |

If a helper is used by only one module, keep it in that module's `utils.py` instead.

---

## 7. `main.py`

The root entry point. Keeps wiring only — no business logic.

```python
"""<Service name>.

Run:  py main.py
Docs: http://localhost:8000/docs
"""
import asyncio
import logging
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from tortoise.contrib.fastapi import RegisterTortoise

from app.home.router import router as home_router
from app.users.router import router as users_router
from database.config import TORTOISE_ORM
from settings.settings import settings
from utilities.common import run_periodic

logging.basicConfig(level=settings.LOG_LEVEL, format="%(asctime)s %(levelname)-7s %(name)s: %(message)s")
logger = logging.getLogger("app")


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with RegisterTortoise(app, config=TORTOISE_ORM, generate_schemas=settings.db_url.startswith("sqlite")):
        tasks = [
            # asyncio.create_task(run_periodic("cleanup", 600, some_module.services.cleanup_tick)),
        ]
        logger.info("%s started", settings.APP_NAME)
        try:
            yield
        finally:
            for t in tasks:
                t.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)


app = FastAPI(title=settings.APP_NAME, version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware, allow_origins=settings.cors_origins, allow_methods=["*"], allow_headers=["*"]
)

for r in (home_router, users_router):
    app.include_router(r)


if __name__ == "__main__":
    uvicorn.run("main:app", host=settings.HOST, port=settings.PORT)
```

Order inside `main.py`: imports → logging → `lifespan` (DB + background tasks) → `FastAPI(...)` →
middleware → `include_router` loop → `uvicorn.run`.

---

## 8. `tests/`

```
tests/
├── __init__.py
├── conftest.py        # forces test-safe env BEFORE app imports
└── test_<module>.py   # one file per module / feature
```

`conftest.py` starts by overriding env so tests never touch a real database:

```python
import os
os.environ["DATABASE_URL"] = "sqlite://:memory:"
```

`pytest.ini`:

```ini
[pytest]
testpaths = tests
pythonpath = .
```

---

## 9. Adding a new module — checklist

1. Create `app/<module>/` with `__init__.py`, `models.py`, `schemas.py`, `router.py`, `services.py` (`utils.py` if needed).
2. In `router.py`: `router = APIRouter(prefix="/api/v1/<module>", tags=["<Module>"])`.
3. Register the models path in `database/config.py → APP_MODELS`.
4. Import the router in `main.py` and add it to the `include_router` loop.
5. Add any new settings to `settings/settings.py` **and** `.env.example`.
6. `aerich migrate --name <module>_init` → `aerich upgrade`.
7. Add `tests/test_<module>.py`.

---

## 10. Naming conventions

| Thing                  | Convention                                  | Example                          |
|------------------------|---------------------------------------------|----------------------------------|
| Module folder          | lowercase plural noun, snake_case           | `users`, `audit_logs`            |
| Model class            | PascalCase singular                         | `User`, `AuditLog`               |
| Schemas                | `<Name>Create`, `<Name>Update`, `<Name>Out` | `UserCreate`, `UserOut`          |
| Router variable        | `router` (+ `internal_router`)              | `from app.users.router import router as users_router` |
| API prefix             | `/api/v1/<module>`                          | `/api/v1/users`                  |
| Background job         | `<name>_tick` in `services.py`              | `cleanup_tick`                   |
| Settings key           | `UPPER_SNAKE_CASE`                          | `DB_HOST`, `LOG_LEVEL`           |
| Test file              | `test_<module>.py`                          | `test_users.py`                  |
