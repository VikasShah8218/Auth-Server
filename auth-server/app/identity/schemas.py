from typing import Literal

from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=254)
    password: str = Field(min_length=1, max_length=256)


class MfaVerifyRequest(BaseModel):
    challenge: str = Field(min_length=1, max_length=128)
    code: str = Field(pattern=r"^\d{6}$")


class LoginResponse(BaseModel):
    status: Literal["authenticated", "mfa_required"]
    challenge: str | None = None
    methods: list[str] = []


class WebAuthnLoginOptions(BaseModel):
    challenge: str = Field(min_length=1, max_length=128)


class WebAuthnLoginVerify(WebAuthnLoginOptions):
    credential: dict
