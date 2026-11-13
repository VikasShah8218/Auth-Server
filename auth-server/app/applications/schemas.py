from datetime import datetime
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, BeforeValidator, ConfigDict, StringConstraints


def _upper(value: object) -> object:
    return value.strip().upper() if isinstance(value, str) else value


def _lower(value: object) -> object:
    return value.strip().lower() if isinstance(value, str) else value


# Case is normalised first because StringConstraints checks its pattern before applying to_upper or
# to_lower, which would refuse "anpr".
AppKey = Annotated[str, BeforeValidator(_upper), StringConstraints(pattern=r"^[A-Z][A-Z0-9_]{1,31}$")]
PermissionCode = Annotated[
    str,
    BeforeValidator(_lower),
    StringConstraints(max_length=128, pattern=r"^[a-z][a-z0-9_]*(\.[a-z0-9_]+)*$"),
]
RoleName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=64)]
DisplayName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=128)]


class Orm(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# Applications


class ApplicationCreate(BaseModel):
    key: AppKey
    name: DisplayName
    description: str | None = None


class ApplicationUpdate(BaseModel):
    name: DisplayName | None = None
    description: str | None = None
    is_active: bool | None = None


class ApplicationOut(Orm):
    id: int
    key: str
    name: str
    description: str | None
    is_active: bool
    perm_map_version: int
    created_at: datetime
    updated_at: datetime


# Permissions


class PermissionCreate(BaseModel):
    code: PermissionCode
    description: str | None = None


class PermissionUpdate(BaseModel):
    description: str | None = None


class PermissionOut(Orm):
    id: int
    code: str
    description: str | None
    bit: int
    retired_at: datetime | None


# Roles


class RoleCreate(BaseModel):
    name: RoleName
    description: str | None = None


class RoleUpdate(BaseModel):
    name: RoleName | None = None
    description: str | None = None


class RoleOut(Orm):
    id: int
    public_id: UUID
    name: str
    description: str | None


class RoleDetail(RoleOut):
    permissions: list[PermissionOut]


class RolePermissionsSet(BaseModel):
    permission_ids: list[int]


# Members


class MemberOut(BaseModel):
    public_id: UUID
    username: str
    is_active: bool
    roles: list[RoleOut]
