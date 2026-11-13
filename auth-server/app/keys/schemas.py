from datetime import datetime

from pydantic import BaseModel


class SigningKeyOut(BaseModel):
    kid: str
    algorithm: str
    status: str
    activated_at: datetime | None
    not_after: datetime | None
    created_at: datetime
    # The active key only: when the scheduled rotation replaces it.
    rotates_at: datetime | None = None
