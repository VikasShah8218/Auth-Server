"""Token signing keys. The private half is encrypted by a KeyProvider (app/keys/services.py)."""

from tortoise import fields, models


class SigningKey(models.Model):
    id = fields.IntField(primary_key=True)
    kid = fields.CharField(max_length=64, unique=True)
    algorithm = fields.CharField(max_length=16)
    encrypted_private_key = fields.TextField()
    public_jwk = fields.JSONField()
    status = fields.CharField(max_length=16, db_index=True)  # next, active, retired, expired, revoked
    activated_at = fields.DatetimeField(null=True)
    # When a retired key leaves JWKS: after every token it signed has expired.
    not_after = fields.DatetimeField(null=True)

    created_at = fields.DatetimeField(auto_now_add=True)

    class Meta:
        table = "signing_keys"
