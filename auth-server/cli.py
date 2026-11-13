"""Operator commands.

    py cli.py create-admin --username admin --email admin@example.com
    py cli.py export-openapi [--out ../client/openapi/auth.json]

create-admin reads the password from a prompt, or from stdin with --password-stdin. It works only once: when
an active AUTH administrator exists it refuses and changes nothing. There is no default admin password.

export-openapi writes the API schema the React client generates its types from.
"""

import argparse
import asyncio
import getpass
import json
import sys
from pathlib import Path

from tortoise.transactions import in_transaction

from app.applications.models import Application, Role, UserRole
from app.applications.services import ADMIN_ROLE, bump_versions, create_app_records
from app.audit.services import SYSTEM_CLI, record_audit
from app.console.services import ensure_console_client
from app.users.models import User
from app.users.schemas import UserCreate
from app.users.utils import hash_password, validate_password
from database.config import close_db, init_db
from settings.settings import settings
from utilities.exceptions import AppError


async def create_admin(username: str, email: str | None, password: str) -> User:
    """Create the AUTH application if needed, then its first administrator."""
    data = UserCreate(username=username, email=email, password=password)
    validate_password(data.password, data.username)
    password_hash = hash_password(data.password)
    key = settings.AUTH_APP_KEY

    async with in_transaction():
        app = await Application.get_or_none(key=key)
        if app is None:
            app = await create_app_records(key, "Auth Server", "This server's own console")
            await record_audit(SYSTEM_CLI, "application.create", target=key, app=key)

        role = await Role.filter(app_id=app.id, name=ADMIN_ROLE).select_for_update().first()
        if await UserRole.filter(role_id=role.id, user__is_active=True).exists():
            raise AppError(409, "admin_exists", "An administrator already exists")

        user = await User.create(
            username=data.username,
            email=data.email,
            password_hash=password_hash,
            is_superuser=True,
        )
        await UserRole.create(user=user, role=role)
        await bump_versions(app.id, [user.id])
        await record_audit(SYSTEM_CLI, "admin.bootstrap", target=str(user.public_id), app=key)
    await ensure_console_client()
    return user


async def _run_create_admin(args: argparse.Namespace) -> int:
    password = sys.stdin.readline().rstrip("\r\n") if args.password_stdin else getpass.getpass()
    await init_db()
    try:
        user = await create_admin(args.username, args.email, password)
    except AppError as exc:
        print(f"Error: {exc.message}", file=sys.stderr)
        return 1
    finally:
        await close_db()
    print(f"Administrator created: {user.username}")
    return 0


def _export_openapi(args: argparse.Namespace) -> int:
    from main import create_app

    target = Path(args.out).resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(create_app().openapi(), indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {target}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(prog="py cli.py")
    commands = parser.add_subparsers(dest="command", required=True)

    admin = commands.add_parser("create-admin", help="Create the first administrator")
    admin.add_argument("--username", required=True)
    admin.add_argument("--email")
    admin.add_argument("--password-stdin", action="store_true")

    openapi = commands.add_parser("export-openapi", help="Write the OpenAPI schema for the client")
    openapi.add_argument("--out", default=str(Path(__file__).resolve().parent.parent / "client" / "openapi" / "auth.json"))

    args = parser.parse_args()
    if args.command == "export-openapi":
        return _export_openapi(args)
    return asyncio.run(_run_create_admin(args))


if __name__ == "__main__":
    sys.exit(main())
