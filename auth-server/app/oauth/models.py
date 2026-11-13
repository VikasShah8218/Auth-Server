"""Authorization codes and refresh tokens. Only hashes are stored, never the raw values."""

from tortoise import fields, models


class AuthorizationCode(models.Model):
    id = fields.IntField(primary_key=True)
    code_hash = fields.CharField(max_length=64, unique=True)
    client = fields.ForeignKeyField("models.OAuthClient", related_name="codes")
    session = fields.ForeignKeyField("models.Session", related_name="codes")
    family_id = fields.UUIDField()
    pkce_challenge = fields.CharField(max_length=128)
    redirect_uri = fields.TextField()
    scope = fields.TextField()
    nonce = fields.CharField(max_length=256, null=True)
    expires_at = fields.DatetimeField()
    used_at = fields.DatetimeField(null=True)

    class Meta:
        table = "authorization_codes"


class RefreshToken(models.Model):
    """Rotated on every use. All tokens descended from one code share a family_id, so reuse ends them all."""

    id = fields.IntField(primary_key=True)
    token_hash = fields.CharField(max_length=64, unique=True)
    family_id = fields.UUIDField(db_index=True)
    session = fields.ForeignKeyField("models.Session", related_name="refresh_tokens")
    client = fields.ForeignKeyField("models.OAuthClient", related_name="refresh_tokens")
    scope = fields.TextField()
    expires_at = fields.DatetimeField()
    used_at = fields.DatetimeField(null=True)
    revoked_at = fields.DatetimeField(null=True)

    created_at = fields.DatetimeField(auto_now_add=True)

    class Meta:
        table = "refresh_tokens"
