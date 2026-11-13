from datetime import datetime
from typing import Any

from pydantic import BaseModel


class AuditOut(BaseModel):
    id: int
    actor: str
    # The actor's username when the actor is a user; otherwise the actor itself (client_id, system:cli).
    actor_name: str
    action: str
    target: str | None
    app: str | None
    details: dict[str, Any] | None
    ip: str | None
    created_at: datetime
