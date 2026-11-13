"""People who sign in. Deactivated, never deleted, so audit history stays intact."""

from uuid import uuid4

from tortoise import fields, models


class User(models.Model):
    id = fields.IntField(primary_key=True)
    # The token "sub" claim and the id used in URLs. The integer key stays private.
    public_id = fields.UUIDField(default=uuid4, unique=True)
    username = fields.CharField(max_length=64, unique=True)
    email = fields.CharField(max_length=254, unique=True, null=True)
    first_name = fields.CharField(max_length=64, null=True)
    last_name = fields.CharField(max_length=64, null=True)
    password_hash = fields.TextField()
    is_active = fields.BooleanField(default=True)
    is_superuser = fields.BooleanField(default=False)

    created_at = fields.DatetimeField(auto_now_add=True)
    updated_at = fields.DatetimeField(auto_now=True)

    class Meta:
        table = "users"
