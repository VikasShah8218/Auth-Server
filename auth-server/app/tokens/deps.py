"""FastAPI dependencies for routes that take service tokens (downstream servers)."""

from collections.abc import Callable

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.tokens.schemas import ServiceClaims
from app.tokens.services import revoked_error, verify_service_token
from utilities.exceptions import AppError

service_bearer = HTTPBearer(auto_error=False)


def require_service_scope(scope: str) -> Callable:
    async def checker(
        credentials: HTTPAuthorizationCredentials | None = Depends(service_bearer),
    ) -> ServiceClaims:
        if credentials is None:
            raise revoked_error()
        claims = await verify_service_token(credentials.credentials)
        if scope not in claims.scopes:
            raise AppError(403, "insufficient_scope", f"Requires scope {scope}")
        return claims

    return checker
