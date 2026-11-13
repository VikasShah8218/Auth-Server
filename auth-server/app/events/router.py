"""Endpoints for downstream servers (service tokens) and the admin's view of them.

router        /v1/events/{key}...            stream, ack, snapshot       (scope events.read)
apps_router   /v1/apps/{key}/permission-map  bit map                     (scope permissions.read)
admin_router  /v1/admin/downstream           sync status per instance    (Admin)
"""

from fastapi import APIRouter, Depends, Header, Query, Request, Response, status
from fastapi.responses import StreamingResponse

from app.clients.models import OAuthClient
from app.events import services
from app.events.schemas import AckRequest, DownstreamOut
from app.events.stream import event_frames
from app.tokens.deps import require_service_scope
from app.tokens.schemas import ServiceClaims
from settings.settings import settings
from utilities.exceptions import AppError

router = APIRouter(prefix="/v1/events", tags=["Events"])
apps_router = APIRouter(prefix="/v1/apps", tags=["Events"])
admin_router = APIRouter(prefix="/v1/admin/downstream", tags=["Admin: Downstream"])

read_events = require_service_scope("events.read")
read_permissions = require_service_scope("permissions.read")


@router.get("/{key}", summary="SSE stream of signed events after a cursor (after= or Last-Event-ID)")
async def stream_events(
    key: str,
    request: Request,
    after: int | None = Query(None, ge=0),
    instance_id: str | None = Query(None, max_length=128),
    last_event_id: str | None = Header(None),
    claims: ServiceClaims = Depends(read_events),
):
    app = await services.bound_app(key, claims)
    client = await OAuthClient.get(client_id=claims.client_id)
    if last_event_id is not None and last_event_id.isdigit():
        after = int(last_event_id)
    if after is None:
        raise AppError(422, "cursor_required", "Send after= or Last-Event-ID")
    await services.check_cursor(app.id, after)
    if instance_id:
        await services.touch_cursor(client.id, instance_id, None)
    return StreamingResponse(
        event_frames(app, client.id, claims, instance_id, after, request),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache, no-store", "X-Accel-Buffering": "no"},
    )


@router.post("/{key}/ack", status_code=status.HTTP_204_NO_CONTENT, summary="Acknowledge events up to seq")
async def ack(key: str, data: AckRequest, claims: ServiceClaims = Depends(read_events)):
    app = await services.bound_app(key, claims)
    if data.seq > await services.last_seq(app.id):
        raise AppError(422, "invalid_seq", "That sequence number hasn't been published")
    client = await OAuthClient.get(client_id=claims.client_id)
    await services.touch_cursor(client.id, data.instance_id, data.seq)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/{key}/snapshot", summary="Full revocation state, then resume the stream from its seq")
async def snapshot(key: str, claims: ServiceClaims = Depends(read_events)) -> dict:
    return await services.snapshot(await services.bound_app(key, claims))


@apps_router.get("/{key}/permission-map", summary="Permission code to bit map, with its version")
async def permission_map(key: str, claims: ServiceClaims = Depends(read_permissions)) -> dict:
    return await services.permission_map(await services.bound_app(key, claims))


@admin_router.get("", response_model=list[DownstreamOut], summary="Sync status of every downstream instance")
async def downstream(app: str | None = Query(None, max_length=32)):
    return await services.downstream_status(app, settings.DOWNSTREAM_LAG_SECONDS)
