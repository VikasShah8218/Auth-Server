"""ORM configuration, shared by the application and Aerich (`aerich init -t database.config.TORTOISE_ORM`).

Aerich migrations own the schema, never the app: nothing here generates tables.
"""

from tortoise import Tortoise, connections

from settings.settings import settings

APP_MODELS = [
    "app.applications.models",
    "app.users.models",
    "app.identity.models",
    "app.clients.models",
    "app.oauth.models",
    "app.keys.models",
    "app.console.models",
    "app.events.models",
    "app.audit.models",
]

TORTOISE_ORM = {
    "connections": {"default": settings.db_url},
    "apps": {
        "models": {
            "models": [*APP_MODELS, "aerich.models"],
            "default_connection": "default",
        },
    },
}


async def init_db() -> None:
    """Connect for a single task, such as a CLI command. The server uses RegisterTortoise instead."""
    await Tortoise.init(config=TORTOISE_ORM)


async def close_db() -> None:
    await connections.close_all()


async def ping_db() -> None:
    await connections.get("default").execute_query("SELECT 1")
