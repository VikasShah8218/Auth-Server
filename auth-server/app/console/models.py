"""The admin console's server-side session (backend-for-frontend)."""

from tortoise import fields, models


class BffSession(models.Model):
    """The browser holds only an opaque cookie. The tokens stay here, encrypted."""

    id = fields.IntField(primary_key=True)
    handle_hash = fields.CharField(max_length=64, unique=True)
    session = fields.ForeignKeyField("models.Session", related_name="bff_sessions")
    encrypted_access_token = fields.TextField()
    encrypted_refresh_token = fields.TextField()
    access_expires_at = fields.DatetimeField()
    csrf_token = fields.CharField(max_length=64)
    expires_at = fields.DatetimeField()

    class Meta:
        table = "bff_sessions"
