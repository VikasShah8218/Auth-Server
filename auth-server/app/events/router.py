"""Endpoints for downstream servers (service tokens) and the admin's view of them.

router        /v1/events/{key}...            stream, ack, snapshot       (scope events.read)
apps_router   /v1/apps/{key}/permission-map  bit map                     (scope permissions.read)
              /v1/apps/{key}/members         who holds a role            (scope users.read)
              /v1/apps/{key}/roles           roles and their permissions (scope users.read)
admin_router  /v1/admin/downstream           sync status per instance    (Admin)
"""

import base64
import binascii

from fastapi import APIRouter, Depends, Header, Query, Request, Response, status
from fastapi.responses import StreamingResponse

from app.applications import services as app_services
from app.clients.models import OAuthClient
from app.events import services
from app.events.schemas import (
    AckRequest,
    DownstreamOut,
    ServiceMemberOut,
    ServiceMembersPage,
    ServiceRoleOut,
    ServiceRoleRef,
)
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
read_users = require_service_scope("users.read")


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


def _encode_cursor(username: str) -> str:
    return base64.urlsafe_b64encode(username.encode()).rstrip(b"=").decode()


def _decode_cursor(cursor: str) -> str:
    """The cursor is opaque to callers: base64url of the last username on the previous page."""
    try:
        raw = base64.b64decode(cursor.encode("ascii") + b"=" * (-len(cursor) % 4), altchars=b"-_", validate=True)
        username = raw.decode()
    except (binascii.Error, ValueError, UnicodeError):
        username = None
    # Only a cursor this server could have issued: canonical encoding, non-empty.
    if not username or _encode_cursor(username) != cursor:
        raise AppError(422, "invalid_cursor", "The cursor is not valid")
    return username


@apps_router.get("/{key}/members", response_model=ServiceMembersPage,
                 summary="Users holding any role in the app, by username (keyset pages)")
async def app_members(
    key: str,
    limit: int = Query(200, ge=1, le=1000),
    cursor: str | None = Query(None, max_length=512),
    q: str | None = Query(None, max_length=128, description="Matches username, names or email"),
    claims: ServiceClaims = Depends(read_users),
):
    app = await services.bound_app(key, claims)
    after = _decode_cursor(cursor) if cursor else None
    # One extra row tells whether another page exists without a count query.
    rows = await app_services.members_query(app.id, q=q, after=after, limit=limit + 1)
    page = rows[:limit]
    items = [
        ServiceMemberOut(
            sub=user.public_id,
            username=user.username,
            given_name=user.first_name or None,
            family_name=user.last_name or None,
            email=user.email or None,
            is_active=user.is_active,
            roles=[ServiceRoleRef(id=role.public_id, name=role.name) for role in roles],
        )
        for user, roles in page
    ]
    next_cursor = _encode_cursor(page[-1][0].username) if len(rows) > limit else None
    return ServiceMembersPage(items=items, next_cursor=next_cursor)


@apps_router.get("/{key}/roles", response_model=list[ServiceRoleOut],
                 summary="Every role of the app with its active permission codes")
async def app_roles(key: str, claims: ServiceClaims = Depends(read_users)):
    return await app_services.service_roles(await services.bound_app(key, claims))


@admin_router.get("", response_model=list[DownstreamOut], summary="Sync status of every downstream instance")
async def downstream(app: str | None = Query(None, max_length=32)):
    return await services.downstream_status(app, settings.DOWNSTREAM_LAG_SECONDS)
