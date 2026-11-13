"""Business rules for the access model.

Every write runs in one transaction with its audit record and its downstream event. Anything that changes
what a user can do raises that user's per-app version, which makes their existing tokens stale.
"""

from collections.abc import Iterable

from tortoise import connections
from tortoise.exceptions import IntegrityError
from tortoise.expressions import Q, Subquery
from tortoise.functions import Max
from tortoise.transactions import in_transaction

from app.applications.models import Application, Permission, Role, RolePermission, UserAppState, UserRole
from app.applications.schemas import (
    ApplicationCreate,
    ApplicationUpdate,
    PermissionCreate,
    PermissionUpdate,
    RoleCreate,
    RoleUpdate,
)
from app.audit.services import Actor, record_audit
from app.events.services import publish_event
from app.users.models import User
from settings.settings import settings
from utilities.common import utcnow
from utilities.exceptions import AppError, conflict, not_found
from utilities.masks import MAX_BITS, WILDCARD_BIT, WILDCARD_CODE

ADMIN_ROLE = "Admin"


async def get_app(key: str) -> Application:
    app = await Application.get_or_none(key=key.upper())
    if app is None:
        raise not_found("Application")
    return app


async def _lock_app(key: str) -> Application:
    app = await Application.filter(key=key.upper()).select_for_update().first()
    if app is None:
        raise not_found("Application")
    return app


# Versions and events


async def bump_versions(app_id: int, user_ids: Iterable[int], event: str = "user.access_changed") -> None:
    """Raise the users' per-app versions and tell downstream, in the caller's transaction."""
    ids = sorted(set(user_ids))
    if not ids:
        return
    # Sorted ids and a single statement keep two concurrent changes from deadlocking.
    rows = await connections.get("default").execute_query_dict(
        """
        WITH changed AS (
            INSERT INTO user_app_states (user_id, app_id, version)
            SELECT id, $1, 1 FROM users WHERE id = ANY($2::int[]) ORDER BY id
            ON CONFLICT (user_id, app_id)
            DO UPDATE SET version = user_app_states.version + 1
            RETURNING user_id, version
        )
        SELECT users.public_id::text AS sub, changed.version AS ver
        FROM changed JOIN users ON users.id = changed.user_id
        ORDER BY users.id
        """,
        [app_id, ids],
    )
    await publish_event([app_id], event, {"users": rows})


MEMBERS_CHANGED = "members.changed"


async def publish_members_changed(app_ids: Iterable[int], payload: dict | None = None) -> None:
    """Tell downstream servers their cached members or roles list is out of date. Covers what the access
    events don't: roles created, described, renamed or deleted (members or not), and profile changes."""
    await publish_event(app_ids, MEMBERS_CHANGED, payload or {})


async def _publish_map_change(app: Application) -> None:
    await publish_event([app.id], "permissions.changed", {"version": app.perm_map_version})


async def _role_user_ids(role_id: int) -> list[int]:
    return await UserRole.filter(role_id=role_id).values_list("user_id", flat=True)


# The AUTH administrator guard


async def _is_auth_admin_role(role: Role) -> bool:
    if role.name != ADMIN_ROLE:
        return False
    return await Application.filter(id=role.app_id, key=settings.AUTH_APP_KEY).exists()


async def is_auth_admin(user_id: int) -> bool:
    return await UserRole.filter(
        user_id=user_id, role__name=ADMIN_ROLE, role__app__key=settings.AUTH_APP_KEY
    ).exists()


async def ensure_other_admin_remains(user_id: int) -> None:
    """Refuse a change that would leave nobody able to administer the system.

    Locking the role row makes two simultaneous removals run one after the other, so they can't each see
    the other as the admin who remains.
    """
    role = await Role.filter(app__key=settings.AUTH_APP_KEY, name=ADMIN_ROLE).select_for_update().first()
    if role is None:
        return
    remaining = await UserRole.filter(role_id=role.id, user__is_active=True).exclude(user_id=user_id).exists()
    if not remaining:
        raise conflict("last_admin", "At least one active administrator must remain")


# Applications


async def create_app_records(key: str, name: str, description: str | None) -> Application:
    """An app starts with its full-access permission on bit 0 and an Admin role holding it."""
    app = await Application.create(key=key, name=name, description=description)
    wildcard = await Permission.create(app=app, code=WILDCARD_CODE, bit=WILDCARD_BIT, description="Full access")
    role = await Role.create(app=app, name=ADMIN_ROLE, description="Full access")
    await RolePermission.create(role=role, permission=wildcard)
    return app


async def create_application(data: ApplicationCreate, actor: Actor) -> Application:
    try:
        async with in_transaction():
            app = await create_app_records(data.key, data.name, data.description)
            await record_audit(actor, "application.create", target=app.key, app=app.key)
    except IntegrityError:
        raise conflict("application_exists", "An application with this key exists") from None
    return app


async def update_application(key: str, data: ApplicationUpdate, actor: Actor) -> Application:
    changes = data.model_dump(exclude_unset=True)
    async with in_transaction():
        app = await _lock_app(key)
        if changes.get("is_active") is False and app.key == settings.AUTH_APP_KEY:
            raise conflict("protected", "The AUTH application can't be deactivated")
        if not changes:
            return app
        await app.update_from_dict(changes).save()
        await record_audit(actor, "application.update", target=app.key, app=app.key, details=changes)
    return app


async def members_query(
    app_id: int, q: str | None = None, after: str | None = None, limit: int | None = None
) -> list[tuple[User, list[Role]]]:
    """Users holding any role in the app, by username, each with their roles in this app (by name).

    `after` and `limit` give a keyset page: usernames are unique, so "username > after" never skips or
    repeats anyone, even while members change between pages.
    """
    users = User.filter(id__in=Subquery(UserRole.filter(role__app_id=app_id).values("user_id")))
    if q:
        users = users.filter(
            Q(username__icontains=q) | Q(email__icontains=q) | Q(first_name__icontains=q) | Q(last_name__icontains=q)
        )
    if after is not None:
        users = users.filter(username__gt=after)
    users = users.order_by("username")
    if limit is not None:
        users = users.limit(limit)
    page = await users

    roles: dict[int, list[Role]] = {user.id: [] for user in page}
    if page:
        links = await UserRole.filter(role__app_id=app_id, user_id__in=list(roles)).select_related("role")
        for link in links:
            roles[link.user_id].append(link.role)
    return [(user, sorted(roles[user.id], key=lambda role: role.name)) for user in page]


async def application_members(app: Application) -> list[dict]:
    return [
        {"public_id": user.public_id, "username": user.username, "is_active": user.is_active, "roles": roles}
        for user, roles in await members_query(app.id)
    ]


async def service_roles(app: Application) -> list[dict]:
    """Every role of the app with its active permission codes, for downstream servers."""
    roles = await Role.filter(app_id=app.id).order_by("name").prefetch_related("permissions__permission")
    return [
        {
            "id": role.public_id,
            "name": role.name,
            "description": role.description,
            "permissions": sorted(
                link.permission.code for link in role.permissions if link.permission.retired_at is None
            ),
        }
        for role in roles
    ]


# Permissions


async def create_permission(key: str, data: PermissionCreate, actor: Actor) -> Permission:
    async with in_transaction():
        # The row lock makes bit assignment safe against concurrent creates.
        app = await _lock_app(key)
        existing = await Permission.get_or_none(app_id=app.id, code=data.code)

        if existing is not None and existing.retired_at is None:
            raise conflict("permission_exists", "This permission already exists")

        if existing is not None:
            # Same code, same bit: reviving it can't change the meaning of a token.
            existing.retired_at = None
            existing.description = data.description
            await existing.save()
            permission = existing
        else:
            row = await Permission.filter(app_id=app.id).annotate(top=Max("bit")).group_by("app_id").values("top")
            bit = row[0]["top"] + 1 if row else WILDCARD_BIT + 1
            if bit >= MAX_BITS:
                raise conflict("permission_limit", f"An application can't exceed {MAX_BITS} permissions")
            permission = await Permission.create(app=app, code=data.code, bit=bit, description=data.description)

        app.perm_map_version += 1
        await app.save(update_fields=["perm_map_version", "updated_at"])
        await _publish_map_change(app)
        await record_audit(
            actor, "permission.create", target=permission.code, app=app.key, details={"bit": permission.bit}
        )
    return permission


async def _get_permission(app: Application, permission_id: int) -> Permission:
    permission = await Permission.get_or_none(id=permission_id, app_id=app.id)
    if permission is None:
        raise not_found("Permission")
    return permission


async def update_permission(key: str, permission_id: int, data: PermissionUpdate, actor: Actor) -> Permission:
    app = await get_app(key)
    permission = await _get_permission(app, permission_id)
    changes = data.model_dump(exclude_unset=True)
    if not changes:
        return permission
    async with in_transaction():
        await permission.update_from_dict(changes).save()
        await record_audit(actor, "permission.update", target=permission.code, app=app.key)
    return permission


async def retire_permission(key: str, permission_id: int, actor: Actor) -> Permission:
    async with in_transaction():
        app = await _lock_app(key)
        permission = await _get_permission(app, permission_id)
        if permission.bit == WILDCARD_BIT:
            raise conflict("protected", "The full-access permission can't be retired")
        if permission.retired_at is not None:
            return permission

        role_ids = await RolePermission.filter(permission_id=permission.id).values_list("role_id", flat=True)
        user_ids = await UserRole.filter(role_id__in=role_ids).values_list("user_id", flat=True)

        await RolePermission.filter(permission_id=permission.id).delete()
        permission.retired_at = utcnow()
        await permission.save()

        app.perm_map_version += 1
        await app.save(update_fields=["perm_map_version", "updated_at"])
        await _publish_map_change(app)
        await bump_versions(app.id, user_ids)
        await record_audit(
            actor, "permission.retire", target=permission.code, app=app.key, details={"bit": permission.bit}
        )
    return permission


async def permission_bits_for_user(user_id: int, app_id: int) -> set[int]:
    """The bits that go into a token's mask for this user on this application."""
    bits = await Permission.filter(
        app_id=app_id, retired_at__isnull=True, roles__role__users__user_id=user_id
    ).distinct().values_list("bit", flat=True)
    return set(bits)


async def access_version(user_id: int, app_id: int) -> int:
    state = await UserAppState.get_or_none(user_id=user_id, app_id=app_id)
    return state.version if state else 0


# Roles


async def get_role(app: Application, role_id: int) -> Role:
    role = await Role.get_or_none(id=role_id, app_id=app.id)
    if role is None:
        raise not_found("Role")
    return role


async def role_permissions(role: Role) -> list[Permission]:
    return await Permission.filter(roles__role_id=role.id).order_by("bit")


async def create_role(key: str, data: RoleCreate, actor: Actor) -> Role:
    app = await get_app(key)
    try:
        async with in_transaction():
            role = await Role.create(app=app, name=data.name, description=data.description)
            await publish_members_changed([app.id])
            await record_audit(actor, "role.create", target=role.name, app=app.key)
    except IntegrityError:
        raise conflict("role_exists", "A role with this name exists") from None
    return role


async def update_role(key: str, role_id: int, data: RoleUpdate, actor: Actor) -> Role:
    app = await get_app(key)
    role = await get_role(app, role_id)
    changes = data.model_dump(exclude_unset=True)
    if not changes:
        return role
    if "name" in changes and role.name == ADMIN_ROLE:
        raise conflict("protected", "The Admin role can't be renamed")
    try:
        async with in_transaction():
            await role.update_from_dict(changes).save()
            if "name" in changes:
                # Role names are in the token, so existing tokens are now out of date.
                await bump_versions(app.id, await _role_user_ids(role.id))
            await publish_members_changed([app.id])
            await record_audit(actor, "role.update", target=role.name, app=app.key, details=changes)
    except IntegrityError:
        raise conflict("role_exists", "A role with this name exists") from None
    return role


async def delete_role(key: str, role_id: int, actor: Actor) -> None:
    app = await get_app(key)
    role = await get_role(app, role_id)
    if role.name == ADMIN_ROLE:
        raise conflict("protected", "The Admin role can't be deleted")
    async with in_transaction():
        await bump_versions(app.id, await _role_user_ids(role.id))
        await publish_members_changed([app.id])
        await record_audit(actor, "role.delete", target=role.name, app=app.key)
        await role.delete()


async def set_role_permissions(key: str, role_id: int, permission_ids: list[int], actor: Actor) -> list[Permission]:
    app = await get_app(key)
    role = await get_role(app, role_id)
    wanted = set(permission_ids)
    permissions = await Permission.filter(id__in=wanted, app_id=app.id, retired_at__isnull=True).order_by("bit")
    if len(permissions) != len(wanted):
        raise AppError(422, "invalid_permissions", "Unknown or retired permission for this application")
    if await _is_auth_admin_role(role) and not any(p.bit == WILDCARD_BIT for p in permissions):
        raise conflict("protected", "The AUTH Admin role must keep full access")

    async with in_transaction():
        await RolePermission.filter(role_id=role.id).delete()
        await RolePermission.bulk_create([RolePermission(role_id=role.id, permission_id=p.id) for p in permissions])
        await bump_versions(app.id, await _role_user_ids(role.id))
        await record_audit(
            actor,
            "role.set_permissions",
            target=role.name,
            app=app.key,
            details={"permissions": [p.code for p in permissions]},
        )
    return permissions
