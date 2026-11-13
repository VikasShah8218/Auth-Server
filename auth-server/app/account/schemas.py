from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class PasswordChange(BaseModel):
    current_password: str = Field(min_length=1, max_length=256)
    new_password: str = Field(min_length=1, max_length=256)


class PasswordConfirm(BaseModel):
    """Step-up: the current password, required before adding or removing a factor."""

    password: str = Field(min_length=1, max_length=256)


class CodeRequest(BaseModel):
    code: str = Field(pattern=r"^\d{6}$")


class SessionOut(BaseModel):
    id: UUID
    ip: str | None
    user_agent: str | None
    amr: list[str]
    auth_time: datetime
    expires_at: datetime
    current: bool


class FactorOut(BaseModel):
    id: UUID
    type: str
    name: str | None
    confirmed_at: datetime


class TotpEnrolment(BaseModel):
    secret: str
    otpauth_uri: str


class WebAuthnRegistration(BaseModel):
    credential: dict
    name: str = Field(default="Security key", min_length=1, max_length=64)
