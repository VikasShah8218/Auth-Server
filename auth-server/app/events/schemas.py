from datetime import datetime
from uuid import UUID

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


# Members and roles for downstream servers (scope users.read). Field names follow OIDC userinfo.


class ServiceRoleRef(BaseModel):
    id: UUID
    name: str


class ServiceMemberOut(BaseModel):
    sub: UUID
    username: str
    given_name: str | None
    family_name: str | None
    email: str | None
    is_active: bool
    roles: list[ServiceRoleRef]


class ServiceMembersPage(BaseModel):
    items: list[ServiceMemberOut]
    next_cursor: str | None


class ServiceRoleOut(BaseModel):
    id: UUID
    name: str
    description: str | None
    permissions: list[str]
