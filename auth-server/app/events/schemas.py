from datetime import datetime

from pydantic import BaseModel, Field


class AckRequest(BaseModel):
    instance_id: str = Field(min_length=1, max_length=128)
    seq: int = Field(ge=0)


class DownstreamOut(BaseModel):
    app_key: str
    client_id: str
    instance_id: str
    last_acked_seq: int
    last_seq: int
    lag: int
    last_seen_at: datetime
    status: str
