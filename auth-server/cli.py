"""Operator commands.

    py cli.py create-admin --username admin --email admin@example.com
    py cli.py export-openapi [--out ../auth-client/openapi/auth.json]
    py cli.py rotate-master-key

rotate-master-key re-encrypts everything sealed with the old MASTER_KEY (signing keys, TOTP secrets, console
tokens) under a new one. It asks for the old and the new key (or reads them from stdin, one per line), checks that
the old key opens every row before changing anything, and does it all in one transaction. Afterwards put the new
key in .env and restart. Use it after copying a database to a machine with a different key, or to replace a key.

create-admin reads the password from a prompt, or from stdin with --password-stdin. It works only once: when
an active AUTH administrator exists it refuses and changes nothing. There is no default admin password.

export-openapi writes the API schema the React client generates its types from.
"""

import argparse
import asyncio
import base64
import binascii
import getpass
import json
import os
import sys
from pathlib import Path

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from tortoise.transactions import in_transaction

from app.applications.models import Application, Role, UserRole
from app.applications.services import ADMIN_ROLE, bump_versions, create_app_records
from app.audit.services import SYSTEM_CLI, record_audit
from app.console.models import BffSession
from app.console.services import ensure_console_client
from app.identity.models import MfaFactor
from app.keys.models import SigningKey
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


def _parse_master_key(value: str) -> bytes:
    raw = base64.urlsafe_b64decode(value.encode() + b"=" * (-len(value) % 4))
    if len(raw) != 32:
        raise ValueError("a MASTER_KEY must decode to exactly 32 bytes")
    return raw


def _reseal(old: AESGCM, new: AESGCM, sealed: str, context: str) -> str:
    raw = base64.urlsafe_b64decode(sealed.encode())
    plain = old.decrypt(raw[:12], raw[12:], context.encode())
    nonce = os.urandom(12)
    return base64.urlsafe_b64encode(nonce + new.encrypt(nonce, plain, context.encode())).decode()


async def rotate_master_key(old_key: bytes, new_key: bytes) -> dict[str, int]:
    """Same AES-GCM format and contexts as utilities.crypto. All or nothing: one row the old key can't open
    aborts the whole run with nothing changed."""
    old, new = AESGCM(old_key), AESGCM(new_key)
    counts = {"signing_keys": 0, "mfa_factors": 0, "bff_sessions": 0}
    async with in_transaction():
        for key in await SigningKey.all().select_for_update():
            key.encrypted_private_key = _reseal(old, new, key.encrypted_private_key, f"signing-key:{key.kid}")
            await key.save(update_fields=["encrypted_private_key"])
            counts["signing_keys"] += 1
        for factor in await MfaFactor.filter(encrypted_secret__isnull=False).select_for_update():
            factor.encrypted_secret = _reseal(old, new, factor.encrypted_secret, f"totp:{factor.user_id}")
            await factor.save(update_fields=["encrypted_secret"])
            counts["mfa_factors"] += 1
        for row in await BffSession.all().select_for_update():
            row.encrypted_access_token = _reseal(old, new, row.encrypted_access_token, f"bff-access:{row.handle_hash}")
            row.encrypted_refresh_token = _reseal(
                old, new, row.encrypted_refresh_token, f"bff-refresh:{row.handle_hash}"
            )
            await row.save(update_fields=["encrypted_access_token", "encrypted_refresh_token"])
            counts["bff_sessions"] += 1
    return counts


async def _run_rotate_master_key() -> int:
    if sys.stdin.isatty():
        old_text, new_text = getpass.getpass("Old MASTER_KEY: "), getpass.getpass("New MASTER_KEY: ")
    else:
        old_text, new_text = sys.stdin.readline().strip(), sys.stdin.readline().strip()
    try:
        old_key, new_key = _parse_master_key(old_text.strip()), _parse_master_key(new_text.strip())
    except (ValueError, binascii.Error) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    if len(set(new_key)) < 16:
        print("Error: the new MASTER_KEY is not random enough", file=sys.stderr)
        return 1
    if old_key == new_key:
        print("Nothing to do: the old and new keys are the same.")
        return 0

    await init_db()
    try:
        counts = await rotate_master_key(old_key, new_key)
    except InvalidTag:
        print("Error: the old MASTER_KEY doesn't open the stored data. Nothing was changed.", file=sys.stderr)
        return 1
    finally:
        await close_db()
    print("Re-encrypted: " + ", ".join(f"{n} {name}" for name, n in counts.items()))
    print("Now set MASTER_KEY to the new key in .env and restart the server.")
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
    openapi.add_argument("--out", default=str(Path(__file__).resolve().parent.parent / "auth-client" / "openapi" / "auth.json"))

    commands.add_parser("rotate-master-key", help="Re-encrypt stored secrets from an old MASTER_KEY to a new one")

    args = parser.parse_args()
    if args.command == "export-openapi":
        return _export_openapi(args)
    if args.command == "rotate-master-key":
        return asyncio.run(_run_rotate_master_key())
    return asyncio.run(_run_create_admin(args))


if __name__ == "__main__":
    sys.exit(main())
