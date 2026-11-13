from datetime import datetime

from pydantic import BaseModel, Field, field_validator

from app.applications.schemas import AppKey
from app.clients.utils import check_redirect_uri


class ClientCreate(BaseModel):
    client_id: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]{2,127}$")
    name: str = Field(min_length=1, max_length=128)
    app_key: AppKey
    type: str = Field(pattern=r"^(public|confidential)$")
    redirect_uris: list[str] = []
    scopes: list[str] = []
    audiences: list[AppKey] = []

    @field_validator("redirect_uris")
    @classmethod
    def _uris(cls, value: list[str]) -> list[str]:
        return [check_redirect_uri(uri) for uri in value]


class ClientUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=128)
    redirect_uris: list[str] | None = None
    scopes: list[str] | None = None
    audiences: list[AppKey] | None = None
    is_active: bool | None = None

    @field_validator("redirect_uris")
    @classmethod
    def _uris(cls, value: list[str] | None) -> list[str] | None:
        return None if value is None else [check_redirect_uri(uri) for uri in value]


class ClientOut(BaseModel):
    client_id: str
    name: str
    app_key: str
    type: str
    redirect_uris: list[str]
    scopes: list[str]
    audiences: list[str]
    is_active: bool
    created_at: datetime


class ClientWithSecret(BaseModel):
    """The secret is returned once, at creation or rotation, and never stored in clear."""

    client: ClientOut
    client_secret: str | None
