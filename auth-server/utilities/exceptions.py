"""One error format for the whole API: `{"detail": {"code", "message"}}`.

OAuth endpoints are the exception: they answer in the RFC 6749 shape (see app/oauth/services.py).
"""

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from utilities.common import logger


class AppError(Exception):
    """An expected failure, returned as {"detail": {"code", "message"}}."""

    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.headers = headers


def not_found(what: str) -> AppError:
    return AppError(404, "not_found", f"{what} not found")


def conflict(code: str, message: str) -> AppError:
    return AppError(409, code, message)


def unavailable() -> AppError:
    """Redis is down: sign-in steps that need it fail closed."""
    return AppError(503, "temporarily_unavailable", "Sign-in is temporarily unavailable")


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error(_: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(
            {"detail": {"code": exc.code, "message": exc.message}},
            status_code=exc.status_code,
            headers=exc.headers,
        )

    @app.exception_handler(Exception)
    async def _unexpected(request: Request, exc: Exception) -> JSONResponse:
        # The real error stays in the log. Its text could expose SQL or secrets.
        logger.exception("Unhandled error on %s %s", request.method, request.url.path)
        return JSONResponse(
            {"detail": {"code": "internal_error", "message": "Internal server error"}},
            status_code=500,
        )
