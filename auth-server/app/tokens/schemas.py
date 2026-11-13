"""The verified contents of tokens issued by this server."""

from pydantic import BaseModel


class Claims(BaseModel):
    """A user's access token (token_use = "user")."""

    sub: str
    sid: str
    aud: str
    ver: int
    pm: str = ""
    pv: int = 0
    roles: list[str] = []
    client_id: str = ""
    scope: str = ""
    act: dict | None = None


class ServiceClaims(BaseModel):
    """A service token (token_use = "service"), from the client credentials grant."""

    sub: str
    client_id: str
    app: str
    aud: str
    scope: str = ""
    ver: int
    exp: int

    @property
    def scopes(self) -> set[str]:
        return set(self.scope.split())
