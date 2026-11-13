"""The SSE stream itself: signed event frames, keep-alives, and closing when the service token ends."""

import time
from collections.abc import AsyncIterator

from fastapi import Request

from app.applications.models import Application
from app.events.hub import hub
from app.events.models import OutboxEvent
from app.events.services import touch_cursor
from app.tokens import services as token_services
from app.tokens.schemas import ServiceClaims

BATCH = 200
POLL_SECONDS = 5
KEEP_ALIVE_SECONDS = 15
EVENT_TOKEN_SECONDS = 300


async def frame(app: Application, event: OutboxEvent) -> str:
    """One SSE frame. The data is a signed JWT, so a consumer can trust it came from this server."""
    signed = await token_services.sign(
        {"aud": app.key, "seq": event.seq, "type": event.type, "payload": event.payload},
        token_services.TYP_EVENT,
        EVENT_TOKEN_SECONDS,
    )
    return f"id: {event.seq}\nevent: {event.type}\ndata: {signed}\n\n"


async def event_frames(
    app: Application,
    client_id: int,
    claims: ServiceClaims,
    instance_id: str | None,
    after: int,
    request: Request,
) -> AsyncIterator[str]:
    last_keep_alive = time.monotonic()
    while True:
        if await request.is_disconnected():
            return

        remaining = claims.exp - time.time()
        if remaining <= 0:
            yield 'event: token.expired\ndata: {"detail":"reconnect"}\n\n'
            return

        rows = await OutboxEvent.filter(app_id=app.id, seq__gt=after).order_by("seq").limit(BATCH)
        for row in rows:
            yield await frame(app, row)
            after = row.seq
        if len(rows) == BATCH:
            continue

        if time.monotonic() - last_keep_alive >= KEEP_ALIVE_SECONDS:
            last_keep_alive = time.monotonic()
            # A client revoked mid-stream must not keep receiving events.
            if not await token_services.verify_service_scope_alive(claims):
                yield 'event: token.expired\ndata: {"detail":"revoked"}\n\n'
                return
            if instance_id:
                await touch_cursor(client_id, instance_id, None)
            yield ": keep-alive\n\n"

        await hub.wait(app.id, min(POLL_SECONDS, remaining))
