"""The access model: applications, their permission bits and roles, and who holds which role."""

from uuid import uuid4

from tortoise import fields, models


class Application(models.Model):
    """A system that trusts this server (e.g. ANPR). Deactivated, never deleted."""

    id = fields.IntField(primary_key=True)
    key = fields.CharField(max_length=32, unique=True)
    name = fields.CharField(max_length=128)
    description = fields.TextField(null=True)
    is_active = fields.BooleanField(default=True)
    # The token "pv" claim. Goes up whenever the app's bit map changes.
    perm_map_version = fields.IntField(default=1)

    created_at = fields.DatetimeField(auto_now_add=True)
    updated_at = fields.DatetimeField(auto_now=True)

    class Meta:
        table = "applications"


class Role(models.Model):
    id = fields.IntField(primary_key=True)
    # Stable id for downstream servers: survives renames, unlike the name in the token "roles" claim.
    public_id = fields.UUIDField(default=uuid4, unique=True)
    app = fields.ForeignKeyField("models.Application", related_name="roles")
    name = fields.CharField(max_length=64)
    description = fields.TextField(null=True)

    created_at = fields.DatetimeField(auto_now_add=True)
    updated_at = fields.DatetimeField(auto_now=True)

    class Meta:
        table = "roles"
        unique_together = (("app_id", "name"),)


class Permission(models.Model):
    id = fields.IntField(primary_key=True)
    app = fields.ForeignKeyField("models.Application", related_name="permissions")
    code = fields.CharField(max_length=128)
    description = fields.TextField(null=True)
    # Permanent. A retired row keeps its bit so a live token can't change meaning.
    bit = fields.SmallIntField()
    retired_at = fields.DatetimeField(null=True)

    created_at = fields.DatetimeField(auto_now_add=True)
    updated_at = fields.DatetimeField(auto_now=True)

    class Meta:
        table = "permissions"
        unique_together = (("app_id", "code"), ("app_id", "bit"))


class RolePermission(models.Model):
    id = fields.IntField(primary_key=True)
    role = fields.ForeignKeyField("models.Role", related_name="permissions")
    permission = fields.ForeignKeyField("models.Permission", related_name="roles")

    created_at = fields.DatetimeField(auto_now_add=True)

    class Meta:
        table = "role_permissions"
        unique_together = (("role_id", "permission_id"),)


class UserRole(models.Model):
    id = fields.IntField(primary_key=True)
    user = fields.ForeignKeyField("models.User", related_name="roles")
    role = fields.ForeignKeyField("models.Role", related_name="users")

    created_at = fields.DatetimeField(auto_now_add=True)

    class Meta:
        table = "user_roles"
        unique_together = (("user_id", "role_id"),)


class UserAppState(models.Model):
    """The token "ver" claim. Scoped per app, so one app's change leaves the rest alone."""

    id = fields.IntField(primary_key=True)
    user = fields.ForeignKeyField("models.User", related_name="app_states")
    app = fields.ForeignKeyField("models.Application", related_name="user_states")
    version = fields.IntField(default=0)

    class Meta:
        table = "user_app_states"
        unique_together = (("user_id", "app_id"),)
