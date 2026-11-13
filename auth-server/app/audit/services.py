"""Writing audit records. Every change to access is recorded in the same transaction as the change."""

from dataclasses import dataclass
from typing import Any

from app.audit.models import AuditLog


@dataclass(frozen=True)
class Actor:
    """Who made a change: a user's public id, a client_id, or "system:<name>"."""

    id: str
    ip: str | None = None


SYSTEM_CLI = Actor(id="system:cli")


async def record_audit(
    actor: Actor,
    action: str,
    target: str | None = None,
    app: str | None = None,
    details: dict[str, Any] | None = None,
) -> None:
    """Add an audit record. Call it inside the transaction making the change, so the change and its record
    are saved together or not at all."""
    await AuditLog.create(
        actor=actor.id,
        action=action,
        target=target,
        app=app,
        details=details,
        ip=actor.ip,
    )
