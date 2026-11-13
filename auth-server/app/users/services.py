"""User accounts and their roles. A user is deactivated, never deleted."""

import asyncio
from uuid import UUID

from tortoise.exceptions import IntegrityError
from tortoise.transactions import in_transaction

from app.applications import services as app_services
from app.applications.models import Application, Permission, Role, UserRole
from app.audit.services import Actor, record_audit
from app.events.services import lock_event_counters
from app.identity.models import MfaFactor
from app.identity.services import revoke_user_sessions
from app.users.models import User
from app.users.schemas import UserAppAccess, UserCreate, UserDetail, UserListItem, UserOut, UserUpdate
from app.users.utils import hash_password, validate_password
from settings.settings import settings
from utilities.exceptions import AppError, conflict, not_found

# Fields downstream servers cache through the members endpoint.
PROFILE_FIELDS = ("first_name", "last_name", "email")


async def get_user(public_id: UUID) -> User:
    user = await User.get_or_none(public_id=public_id)
    if user is None:
        raise not_found("User")
    return user


async def create_user(data: UserCreate, actor: Actor) -> User:
    validate_password(data.password, data.username)
    password_hash = await asyncio.to_thread(hash_password, data.password)
    try:
        async with in_transaction():
            user = await User.create(
                username=data.username,
                email=data.email,
                first_name=data.first_name,
                last_name=data.last_name,
                is_active=data.is_active,
                password_hash=password_hash,
            )
            await record_audit(actor, "user.create", target=str(user.public_id))
    except IntegrityError:
        raise conflict("user_exists", "This username or email is already in use") from None
    return user


async def update_user(public_id: UUID, data: UserUpdate, actor: Actor) -> User:
    user = await get_user(public_id)
    changes = data.model_dump(exclude_unset=True)
    if changes.get("is_active") is None:
        changes.pop("is_active", None)
    if not changes:
        return user

    disabling = changes.get("is_active") is False and user.is_active
    enabling = changes.get("is_active") is True and not user.is_active
    # Downstream servers cache names and email (GET /v1/apps/{key}/members), so a real change is announced.
    profile_changed = any(
        field in changes and (changes[field] or None) != (getattr(user, field) or None) for field in PROFILE_FIELDS
    )
    try:
        async with in_transaction():
            if disabling and await app_services.is_auth_admin(user.id):
                await app_services.ensure_other_admin_remains(user.id)
            app_ids: list[int] = []
            if disabling or enabling or profile_changed:
                app_ids = sorted(
                    await Application.filter(roles__users__user_id=user.id).distinct().values_list("id", flat=True)
                )
            if (disabling or enabling) and profile_changed:
                # Several events in one change: take every counter first, in order, so it can't deadlock.
                await lock_event_counters(app_ids)
            await user.update_from_dict(changes).save()
            if disabling:
                await revoke_user_sessions(user.id)
            if disabling or enabling:
                event = "user.disabled" if disabling else "user.access_changed"
                for app_id in app_ids:
                    await app_services.bump_versions(app_id, [user.id], event)
            if profile_changed and app_ids:
                await app_services.publish_members_changed(app_ids, {"sub": str(user.public_id)})
            await record_audit(actor, "user.update", target=str(user.public_id), details={"fields": sorted(changes)})
    except IntegrityError:
        raise conflict("user_exists", "This email is already in use") from None
    return user


async def set_user_roles(public_id: UUID, app_key: str, role_ids: list[int], actor: Actor) -> None:
    """Replace the user's roles in one application."""
    user = await get_user(public_id)
    app = await app_services.get_app(app_key)
    wanted = set(role_ids)
    roles = await Role.filter(id__in=wanted, app_id=app.id)
    if len(roles) != len(wanted):
        raise AppError(422, "invalid_roles", "Unknown role for this application")

    async with in_transaction():
        losing_admin = (
            app.key == settings.AUTH_APP_KEY
            and await app_services.is_auth_admin(user.id)
            and not any(role.name == app_services.ADMIN_ROLE for role in roles)
        )
        if losing_admin:
            await app_services.ensure_other_admin_remains(user.id)

        # Filter on role ids, not role__app_id: a DELETE with a join renders invalid SQL on Postgres.
        app_role_ids = await Role.filter(app_id=app.id).values_list("id", flat=True)
        await UserRole.filter(user_id=user.id, role_id__in=list(app_role_ids)).delete()
        await UserRole.bulk_create([UserRole(user_id=user.id, role_id=role.id) for role in roles])
        await app_services.bump_versions(app.id, [user.id])
        await record_audit(
            actor,
            "user.set_roles",
            target=str(user.public_id),
            app=app.key,
            details={"roles": sorted(role.name for role in roles)},
        )


async def user_access(user: User) -> list[dict]:
    """Per application: the user's roles, the permission codes they add up to, and the app's whole bit map
    marked with what the user holds."""
    links = await UserRole.filter(user_id=user.id).prefetch_related("role__app", "role__permissions__permission")
    apps: dict[int, dict] = {}
    for link in links:
        role = link.role
        entry = apps.setdefault(
            role.app_id,
            {"app_key": role.app.key, "app_name": role.app.name, "roles": [], "permissions": set()},
        )
        entry["roles"].append(role)
        for role_permission in role.permissions:
            permission = role_permission.permission
            if permission.retired_at is None:
                entry["permissions"].add(permission.code)

    maps: dict[int, list[Permission]] = {}
    for permission in await Permission.filter(app_id__in=list(apps)).order_by("bit"):
        maps.setdefault(permission.app_id, []).append(permission)

    result = []
    for app_id, entry in sorted(apps.items(), key=lambda item: item[1]["app_key"]):
        held = entry["permissions"]
        bits = [
            {"code": p.code, "bit": p.bit, "retired": p.retired_at is not None, "held": p.code in held}
            for p in maps.get(app_id, [])
        ]
        result.append({**entry, "permissions": sorted(held), "bits": bits})
    return result


async def list_items(users: list[User]) -> list[UserListItem]:
    """Users list rows with their applications and MFA status, in two queries for the whole page."""
    ids = [user.id for user in users]
    app_keys: dict[int, set[str]] = {}
    for user_id, key in await UserRole.filter(user_id__in=ids).values_list("user_id", "role__app__key"):
        app_keys.setdefault(user_id, set()).add(key)
    with_mfa = set(
        await MfaFactor.filter(user_id__in=ids, confirmed_at__isnull=False).values_list("user_id", flat=True)
    )
    return [
        UserListItem(
            **UserOut.model_validate(user).model_dump(),
            app_keys=sorted(app_keys.get(user.id, ())),
            mfa_enabled=user.id in with_mfa,
        )
        for user in users
    ]


async def user_factors(user: User) -> list[MfaFactor]:
    return await MfaFactor.filter(user_id=user.id, confirmed_at__isnull=False).order_by("id")


async def user_detail(user: User) -> UserDetail:
    access = await user_access(user)
    return UserDetail(
        **UserOut.model_validate(user).model_dump(),
        applications=[UserAppAccess.model_validate(entry, from_attributes=True) for entry in access],
    )


async def reset_password(user: User, new_password: str, actor: Actor) -> None:
    """An admin sets a new password. Every login of the user ends."""
    validate_password(new_password, user.username)
    password_hash = await asyncio.to_thread(hash_password, new_password)
    async with in_transaction():
        user.password_hash = password_hash
        await user.save(update_fields=["password_hash", "updated_at"])
        await revoke_user_sessions(user.id)
        await record_audit(actor, "user.password_reset", target=str(user.public_id))


async def reset_mfa(user: User, actor: Actor) -> None:
    """For a user who lost their device. Ends their logins so the change takes effect at once."""
    async with in_transaction():
        await MfaFactor.filter(user_id=user.id).delete()
        await revoke_user_sessions(user.id)
        await record_audit(actor, "mfa.reset", target=str(user.public_id))
