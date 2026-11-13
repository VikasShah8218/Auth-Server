"""OAuth client administration.

Anything that reduces a client's access (disable, scope or audience change, secret rotation) raises its
version, which ends its service tokens here, and publishes client.revoked so downstream servers drop the
tokens it issued.
"""

from tortoise.exceptions import IntegrityError
from tortoise.transactions import in_transaction

from app.applications.models import Application
from app.applications.services import get_app
from app.audit.services import Actor, record_audit
from app.clients.models import OAuthClient
from app.clients.schemas import ClientCreate, ClientOut, ClientUpdate
from app.clients.utils import OIDC_SCOPES, SERVICE_SCOPES
from app.events.services import publish_event
from settings.settings import settings
from utilities.common import utcnow
from utilities.crypto import hash_token, new_opaque_token
from utilities.exceptions import AppError, conflict, not_found


def client_view(client: OAuthClient) -> ClientOut:
    return ClientOut(
        client_id=client.client_id,
        name=client.name,
        app_key=client.app.key,
        type=client.type,
        redirect_uris=client.redirect_uris,
        scopes=client.scopes,
        audiences=client.audiences,
        is_active=client.is_active,
        created_at=client.created_at,
    )


def _check_rules(type: str, redirect_uris: list[str], scopes: list[str], audiences: list[str]) -> None:
    if not set(scopes) <= OIDC_SCOPES | SERVICE_SCOPES:
        raise AppError(422, "invalid_scope", "Unknown scope")
    if settings.AUTH_APP_KEY in audiences:
        raise AppError(422, "invalid_audience", "The AUTH application can't be an audience")
    if type == "public":
        if not redirect_uris:
            raise AppError(422, "invalid_client", "A public client needs a redirect URI")
        if audiences or set(scopes) & SERVICE_SCOPES:
            raise AppError(422, "invalid_client", "A public client can't hold service access")


async def _check_audiences(audiences: list[str]) -> None:
    known = await Application.filter(key__in=audiences).count()
    if known != len(set(audiences)):
        raise AppError(422, "invalid_audience", "Unknown application in audiences")


async def get_client(client_id: str) -> OAuthClient:
    client = await OAuthClient.get_or_none(client_id=client_id).select_related("app")
    if client is None:
        raise not_found("Client")
    return client


async def _notify_revoked(client: OAuthClient, audiences: list[str]) -> None:
    apps = await Application.filter(key__in=audiences).values_list("id", flat=True)
    await publish_event(
        {client.app_id, *apps},
        "client.revoked",
        {"client_id": client.client_id, "version": client.version, "revoked_at": int(utcnow().timestamp())},
    )


async def create_client(data: ClientCreate, actor: Actor) -> tuple[OAuthClient, str | None]:
    app = await get_app(data.app_key)
    _check_rules(data.type, data.redirect_uris, data.scopes, data.audiences)
    await _check_audiences(data.audiences)
    secret = new_opaque_token() if data.type == "confidential" else None
    try:
        async with in_transaction():
            client = await OAuthClient.create(
                client_id=data.client_id,
                name=data.name,
                app=app,
                type=data.type,
                secret_hash=hash_token(secret) if secret else None,
                redirect_uris=data.redirect_uris,
                scopes=sorted(set(data.scopes)),
                audiences=sorted(set(data.audiences)),
            )
            await record_audit(actor, "client.create", target=client.client_id, app=app.key)
    except IntegrityError:
        raise conflict("client_exists", "This client_id already exists") from None
    client.app = app
    return client, secret


async def update_client(client_id: str, data: ClientUpdate, actor: Actor) -> OAuthClient:
    client = await get_client(client_id)
    changes = {k: v for k, v in data.model_dump(exclude_unset=True).items() if v is not None}
    _check_rules(
        client.type,
        changes.get("redirect_uris", client.redirect_uris),
        changes.get("scopes", client.scopes),
        changes.get("audiences", client.audiences),
    )
    await _check_audiences(changes.get("audiences", []))

    reduces_access = changes.get("is_active") is False or "scopes" in changes or "audiences" in changes
    # An app losing this client must hear about it, so the old list counts too.
    previous_audiences = list(client.audiences)
    async with in_transaction():
        await client.update_from_dict(changes).save()
        if reduces_access:
            client.version += 1
            await client.save(update_fields=["version"])
            await _notify_revoked(client, sorted({*previous_audiences, *client.audiences}))
        await record_audit(
            actor, "client.update", target=client.client_id, app=client.app.key, details={"fields": sorted(changes)}
        )
    return client


async def rotate_secret(client_id: str, actor: Actor) -> tuple[OAuthClient, str]:
    client = await get_client(client_id)
    if client.type != "confidential":
        raise conflict("not_confidential", "A public client has no secret")
    secret = new_opaque_token()
    async with in_transaction():
        client.secret_hash = hash_token(secret)
        client.version += 1
        await client.save(update_fields=["secret_hash", "version"])
        await _notify_revoked(client, client.audiences)
        await record_audit(actor, "client.rotate_secret", target=client.client_id, app=client.app.key)
    return client, secret
