"""SSO sessions and MFA factors."""

from uuid import uuid4

from tortoise import fields, models


class MfaFactor(models.Model):
    id = fields.IntField(primary_key=True)
    public_id = fields.UUIDField(default=uuid4, unique=True)
    user = fields.ForeignKeyField("models.User", related_name="mfa_factors")
    type = fields.CharField(max_length=16)  # totp or webauthn
    name = fields.CharField(max_length=64, null=True)
    # An unconfirmed factor never protects or unlocks anything.
    confirmed_at = fields.DatetimeField(null=True)

    # TOTP: the secret, and the last accepted time step so a code works only once.
    encrypted_secret = fields.TextField(null=True)
    last_used_step = fields.BigIntField(null=True)

    # WebAuthn
    credential_id = fields.CharField(max_length=512, null=True, unique=True)
    public_key = fields.TextField(null=True)
    sign_count = fields.BigIntField(default=0)

    created_at = fields.DatetimeField(auto_now_add=True)

    class Meta:
        table = "mfa_factors"


class Session(models.Model):
    """One SSO login. Its public_id is the token "sid" claim."""

    id = fields.IntField(primary_key=True)
    public_id = fields.UUIDField(default=uuid4, unique=True)
    user = fields.ForeignKeyField("models.User", related_name="sessions")
    token_hash = fields.CharField(max_length=64, unique=True)
    auth_time = fields.DatetimeField()
    amr = fields.JSONField(default=list)
    ip = fields.CharField(max_length=45, null=True)
    user_agent = fields.CharField(max_length=256, null=True)
    expires_at = fields.DatetimeField()
    revoked_at = fields.DatetimeField(null=True)

    created_at = fields.DatetimeField(auto_now_add=True)

    class Meta:
        table = "sessions"
