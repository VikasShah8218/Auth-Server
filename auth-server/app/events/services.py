"""The event plane: how every downstream server stays in step.

    change + outbox row commit together -> NOTIFY wakes streams -> SSE -> downstream applies -> ACK(seq)

A change can never be saved without its event, or the reverse. Each app has a gapless sequence, so a
consumer resumes exactly where it stopped, or fetches a snapshot when replay is no longer possible.
"""

from collections.abc import Iterable
from datetime import timedelta
from typing import Any

from tortoise import connections
from tortoise.backends.base.client import TransactionalDBClient
from tortoise.expressions import Q

from app.applications.models import Application, Permission, UserAppState
from app.clients.models import OAuthClient
from app.events.models import AppEventCounter, DownstreamCursor, OutboxEvent
from app.identity.models import Session
from app.tokens.schemas import ServiceClaims
from settings.settings import settings
from utilities.common import logger, utcnow
from utilities.exceptions import AppError, not_found

NOTIFY_CHANNEL = "auth_events"
KEYS_CHANNEL = "auth_keys"


# Publishing


async def lock_event_counters(app_ids: Iterable[int]) -> None:
    """Take every counter a multi-step change will need, in one sorted pass. Separate publish_event calls
    each sort only their own apps, so two such changes could still lock in opposite orders and deadlock."""
    connection = connections.get("default")
    for app_id in sorted(set(app_ids)):
        await connection.execute_query(
            """
            INSERT INTO app_event_counters (app_id, last_seq) VALUES ($1, 0)
            ON CONFLICT (app_id) DO UPDATE SET last_seq = app_event_counters.last_seq
            """,
            [app_id],
        )


async def publish_event(app_ids: Iterable[int], type: str, payload: dict[str, Any]) -> None:
    """Write an event to each app's outbox, inside the caller's transaction.

    Counters are always locked in app_id order, which stops two changes touching the same apps from
    deadlocking. NOTIFY is held back by Postgres until commit, so a rolled-back change wakes nobody.
    """
    connection = connections.get("default")
    if not isinstance(connection, TransactionalDBClient):
        raise RuntimeError("publish_event must run inside a transaction")

    for app_id in sorted(set(app_ids)):
        row = await connection.execute_query_dict(
            """
            INSERT INTO app_event_counters (app_id, last_seq) VALUES ($1, 1)
            ON CONFLICT (app_id)
            DO UPDATE SET last_seq = app_event_counters.last_seq + 1
            RETURNING last_seq
            """,
            [app_id],
        )
        await OutboxEvent.create(app_id=app_id, seq=row[0]["last_seq"], type=type, payload=payload)
        await connection.execute_query("SELECT pg_notify($1, $2)", [NOTIFY_CHANNEL, str(app_id)])


# Consuming


async def bound_app(key: str, claims: ServiceClaims) -> Application:
    """A service can only follow its own application."""
    if claims.app != key.upper():
        raise AppError(403, "wrong_application", "This client belongs to another application")
    app = await Application.get_or_none(key=key.upper(), is_active=True)
    if app is None:
        raise not_found("Application")
    return app


async def last_seq(app_id: int) -> int:
    counter = await AppEventCounter.get_or_none(app_id=app_id)
    return counter.last_seq if counter else 0


async def check_cursor(app_id: int, after: int) -> None:
    """Refuse a cursor the outbox can no longer satisfy, so that no consumer ever skips events without
    knowing. It must fetch a snapshot and resume from there."""
    last = await last_seq(app_id)
    oldest = await OutboxEvent.filter(app_id=app_id).order_by("seq").first()
    first_available = oldest.seq if oldest else last + 1
    if after > last or after + 1 < first_available:
        raise AppError(409, "snapshot_required", "Fetch a snapshot, then resume from its seq")


async def touch_cursor(client_id: int, instance_id: str, seq: int | None) -> None:
    """Record that an instance is alive, and the highest seq it has acknowledged."""
    await connections.get("default").execute_query(
        """
        INSERT INTO downstream_cursors (client_id, instance_id, last_acked_seq, last_seen_at)
        VALUES ($1, $2, COALESCE($3::bigint, 0), now())
        ON CONFLICT (client_id, instance_id) DO UPDATE SET
            last_acked_seq = GREATEST(downstream_cursors.last_acked_seq, COALESCE($3::bigint, 0)),
            last_seen_at = now()
        """,
        [client_id, instance_id, seq],
    )


async def snapshot(app: Application) -> dict:
    """Current state, for a new consumer or one past the retention window.

    seq is read first. A change landing during the read then appears in the snapshot and again in replay,
    and applying an event twice is harmless.
    """
    seq = await last_seq(app.id)
    states = await UserAppState.filter(app_id=app.id).select_related("user")
    # By role as well, because a session can reach an app through exchange alone.
    sessions = await Session.filter(
        Q(refresh_tokens__client__app_id=app.id) | Q(user__roles__role__app_id=app.id),
        revoked_at__isnull=False,
        expires_at__gt=utcnow(),
    ).distinct()
    clients = await OAuthClient.filter(Q(version__gt=0) | Q(is_active=False))
    return {
        "seq": seq,
        "perm_map_version": app.perm_map_version,
        "users": [
            {"sub": str(s.user.public_id), "ver": s.version, "is_active": s.user.is_active} for s in states
        ],
        "revoked_sessions": [str(s.public_id) for s in sessions],
        "revoked_clients": [
            {"client_id": c.client_id, "version": c.version, "revoked_at": int(c.updated_at.timestamp())}
            for c in clients
            if c.app_id == app.id or app.key in c.audiences
        ],
    }


async def permission_map(app: Application) -> dict:
    rows = await Permission.filter(app_id=app.id).order_by("bit")
    return {
        "version": app.perm_map_version,
        "permissions": [
            {"code": row.code, "bit": row.bit, "retired": row.retired_at is not None} for row in rows
        ],
    }


async def downstream_status(app_key: str | None, lag_seconds: int) -> list[dict]:
    """Each downstream instance: last ACK, lag behind the app's sequence, and ok / lagging / offline."""
    query = DownstreamCursor.all().select_related("client__app").order_by("client__client_id", "instance_id")
    if app_key:
        query = query.filter(client__app__key=app_key.upper())
    result = []
    now = utcnow()
    for cursor in await query:
        latest = await last_seq(cursor.client.app_id)
        lag = max(0, latest - cursor.last_acked_seq)
        silent = (now - cursor.last_seen_at).total_seconds()
        state = "offline" if silent > lag_seconds else "lagging" if lag > 0 else "ok"
        result.append(
            {
                "app_key": cursor.client.app.key,
                "client_id": cursor.client.client_id,
                "instance_id": cursor.instance_id,
                "last_acked_seq": cursor.last_acked_seq,
                "last_seq": latest,
                "lag": lag,
                "last_seen_at": cursor.last_seen_at,
                "status": state,
            }
        )
    return result


# Background jobs


async def prune_outbox_tick() -> None:
    """Drop events past retention. A consumer older than that gets 409 snapshot_required."""
    cutoff = utcnow() - timedelta(days=settings.EVENT_RETENTION_DAYS)
    await OutboxEvent.filter(created_at__lt=cutoff).delete()


async def downstream_report_tick() -> None:
    for entry in await downstream_status(None, settings.DOWNSTREAM_LAG_SECONDS):
        if entry["status"] != "ok":
            logger.warning(
                "Downstream %s/%s is %s, %s events behind",
                entry["client_id"],
                entry["instance_id"],
                entry["status"],
                entry["lag"],
            )
