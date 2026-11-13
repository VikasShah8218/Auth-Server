"""The transactional outbox, its per-app sequence counters, and what each downstream instance has applied."""

from tortoise import fields, models


class AppEventCounter(models.Model):
    """The last sequence number per app. Updating this row inside the publishing transaction gives gapless
    numbers in commit order."""

    id = fields.IntField(primary_key=True)
    app = fields.OneToOneField("models.Application", related_name="event_counter")
    last_seq = fields.BigIntField(default=0)

    class Meta:
        table = "app_event_counters"


class OutboxEvent(models.Model):
    id = fields.BigIntField(primary_key=True)
    app = fields.ForeignKeyField("models.Application", related_name="outbox_events")
    seq = fields.BigIntField()
    type = fields.CharField(max_length=64)
    payload = fields.JSONField()
    created_at = fields.DatetimeField(auto_now_add=True, db_index=True)

    class Meta:
        table = "outbox_events"
        unique_together = (("app_id", "seq"),)


class DownstreamCursor(models.Model):
    """What one running instance of a downstream server has applied."""

    id = fields.IntField(primary_key=True)
    client = fields.ForeignKeyField("models.OAuthClient", related_name="cursors")
    instance_id = fields.CharField(max_length=128)
    last_acked_seq = fields.BigIntField(default=0)
    last_seen_at = fields.DatetimeField()

    class Meta:
        table = "downstream_cursors"
        unique_together = (("client_id", "instance_id"),)
