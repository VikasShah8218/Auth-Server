"""OAuth clients: browser apps (public) and downstream servers (confidential)."""

from tortoise import fields, models


class OAuthClient(models.Model):
    id = fields.IntField(primary_key=True)
    client_id = fields.CharField(max_length=128, unique=True)
    name = fields.CharField(max_length=128)
    app = fields.ForeignKeyField("models.Application", related_name="clients")
    type = fields.CharField(max_length=16)  # public or confidential
    secret_hash = fields.TextField(null=True)
    redirect_uris = fields.JSONField(default=list)
    scopes = fields.JSONField(default=list)
    # Applications this client may get a service or exchanged token for.
    audiences = fields.JSONField(default=list)
    is_active = fields.BooleanField(default=True)
    # The service token "ver" claim. Goes up to end a client's existing tokens.
    version = fields.IntField(default=0)

    created_at = fields.DatetimeField(auto_now_add=True)
    updated_at = fields.DatetimeField(auto_now=True)

    class Meta:
        table = "oauth_clients"
