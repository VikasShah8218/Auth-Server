from datetime import datetime
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, BeforeValidator, ConfigDict, EmailStr, Field, StringConstraints, field_validator

from app.applications.schemas import AppKey, RoleOut


def _lower(value: object) -> object:
    return value.strip().lower() if isinstance(value, str) else value


Username = Annotated[str, BeforeValidator(_lower), StringConstraints(pattern=r"^[a-z0-9][a-z0-9._-]{2,63}$")]
PersonName = Annotated[str, StringConstraints(strip_whitespace=True, max_length=64)]


class UserCreate(BaseModel):
    username: Username
    password: str = Field(min_length=1, max_length=256)
    email: EmailStr | None = None
    first_name: PersonName | None = None
    last_name: PersonName | None = None
    is_active: bool = True

    @field_validator("email")
    @classmethod
    def _lower_email(cls, value: str | None) -> str | None:
        return value.lower() if value else value


class UserUpdate(BaseModel):
    email: EmailStr | None = None
    first_name: PersonName | None = None
    last_name: PersonName | None = None
    is_active: bool | None = None

    @field_validator("email")
    @classmethod
    def _lower_email(cls, value: str | None) -> str | None:
        return value.lower() if value else value


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    public_id: UUID
    username: str
    email: str | None
    first_name: str | None
    last_name: str | None
    is_active: bool
    created_at: datetime
    updated_at: datetime


class UserListItem(UserOut):
    """A row of the users list: the profile plus what the console shows beside it."""

    app_keys: list[str]
    mfa_enabled: bool


class PermissionBit(BaseModel):
    """One bit of an application's permission map, and whether this user holds it."""

    code: str
    bit: int
    retired: bool
    held: bool


class UserAppAccess(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    app_key: str
    app_name: str
    roles: list[RoleOut]
    permissions: list[str]
    # Every bit of the app's map in bit order, for the console's key-cut strip.
    bits: list[PermissionBit]


class UserDetail(UserOut):
    applications: list[UserAppAccess]


class UserRolesSet(BaseModel):
    app_key: AppKey
    role_ids: list[int]


class PasswordReset(BaseModel):
    new_password: str = Field(min_length=1, max_length=256)
