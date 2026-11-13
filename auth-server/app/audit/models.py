"""The audit trail."""

from tortoise import fields, models


class AuditLog(models.Model):
    """Insert only. A database trigger rejects UPDATE, DELETE and TRUNCATE.

    The fields are plain values rather than foreign keys, so a record can't be altered or lost through a
    change to the row it describes.
    """

    id = fields.BigIntField(primary_key=True)
    actor = fields.CharField(max_length=128)
    action = fields.CharField(max_length=64)
    target = fields.CharField(max_length=128, null=True)
    app = fields.CharField(max_length=32, null=True)
    details = fields.JSONField(null=True)
    ip = fields.CharField(max_length=45, null=True)

    created_at = fields.DatetimeField(auto_now_add=True)

    class Meta:
        table = "audit_logs"
        indexes = (("app", "created_at"), ("actor", "created_at"))
