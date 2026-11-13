"""Cookie helpers for the SSO session."""

from fastapi import Response

from app.identity.models import Session
from settings.settings import settings
from utilities.common import utcnow

SSO_COOKIE = "auth_sso"


def set_sso_cookie(response: Response, raw: str, session: Session) -> None:
    response.set_cookie(
        SSO_COOKIE,
        raw,
        max_age=int((session.expires_at - utcnow()).total_seconds()),
        httponly=True,
        secure=settings.is_production,
        # Lax, because /oauth/authorize is reached by a redirect from other apps.
        samesite="lax",
        path="/",
    )
