"""OAuth client administration. No auth code here: access is declared in app/security/policy.py."""

from fastapi import APIRouter, Depends, Query, status

from app.audit.services import Actor
from app.clients import services
from app.clients.models import OAuthClient
from app.clients.schemas import ClientCreate, ClientOut, ClientUpdate, ClientWithSecret
from app.security.deps import current_actor

router = APIRouter(prefix="/v1/admin/clients", tags=["Admin: Clients"])


@router.get("", response_model=list[ClientOut], summary="All clients, optionally for one application")
async def list_clients(app: str | None = Query(None, max_length=32)):
    qs = OAuthClient.all().select_related("app").order_by("client_id")
    if app:
        qs = qs.filter(app__key=app.upper())
    return [services.client_view(client) for client in await qs]


@router.post("", response_model=ClientWithSecret, status_code=status.HTTP_201_CREATED,
             summary="Create a client. A confidential client's secret is shown once")
async def create_client(data: ClientCreate, actor: Actor = Depends(current_actor)):
    client, secret = await services.create_client(data, actor)
    return ClientWithSecret(client=services.client_view(client), client_secret=secret)


@router.get("/{client_id}", response_model=ClientOut)
async def get_client(client_id: str):
    return services.client_view(await services.get_client(client_id))


@router.patch("/{client_id}", response_model=ClientOut,
              summary="Edit a client. Reducing access ends its tokens everywhere")
async def update_client(client_id: str, data: ClientUpdate, actor: Actor = Depends(current_actor)):
    return services.client_view(await services.update_client(client_id, data, actor))


@router.post("/{client_id}/rotate-secret", response_model=ClientWithSecret,
             summary="New secret, shown once. The old one stops working")
async def rotate_client_secret(client_id: str, actor: Actor = Depends(current_actor)):
    client, secret = await services.rotate_secret(client_id, actor)
    return ClientWithSecret(client=services.client_view(client), client_secret=secret)
