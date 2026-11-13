from pydantic import BaseModel


class SessionUser(BaseModel):
    public_id: str
    username: str
    email: str | None
    first_name: str | None
    last_name: str | None


class ConsoleSession(BaseModel):
    """What the console needs at startup. The CSRF token is the only secret in it."""

    user: SessionUser
    roles: list[str]
    is_admin: bool
    csrf_token: str
