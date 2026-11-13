"""The admin console's sign-in, session and sign-out (backend-for-frontend)."""

import secrets
from urllib.parse import urlencode

from fastapi import APIRouter, Request, Response, status
from fastapi.responses import RedirectResponse
from tortoise.transactions import in_transaction

from app.console import services
from app.console.schemas import ConsoleSession
from app.identity.models import Session
from app.identity.services import revoke_session
from app.identity.utils import SSO_COOKIE
from app.oauth import services as oauth_services
from app.oauth.utils import OAuthError
from app.tokens.services import verify_access_token
from app.users.models import User
from settings.settings import settings
from utilities.common import utcnow
from utilities.crypto import hash_token, new_opaque_token, pkce_challenge
from utilities.exceptions import AppError

router = APIRouter(prefix="/bff", tags=["Console"])


def _login_failed(reason: str) -> RedirectResponse:
    return RedirectResponse(f"{settings.LOGIN_PAGE_PATH}?{urlencode({'error': reason})}", status_code=302)


@router.get("/login", summary="Begin the console sign-in (PKCE against this server)")
async def bff_login() -> RedirectResponse:
    await services.ensure_console_client()
    state = secrets.token_urlsafe(24)
    binding = secrets.token_urlsafe(24)
    verifier = secrets.token_urlsafe(48)
    await services.save_state(state, verifier, binding)
    query = urlencode(
        {
            "response_type": "code",
            "client_id": services.CONSOLE_CLIENT_ID,
            "redirect_uri": services.redirect_uri(),
            "scope": "openid profile email",
            "state": state,
            "code_challenge": pkce_challenge(verifier),
            "code_challenge_method": "S256",
        }
    )
    response = RedirectResponse(f"/oauth/authorize?{query}", status_code=302)
    # Ties the callback to the browser that began the login. Without it, an attacker could finish a login as
    # themselves and send the victim the callback link, leaving the victim working inside the attacker's
    # account.
    response.set_cookie(
        services.STATE_COOKIE,
        binding,
        max_age=services.STATE_SECONDS,
        httponly=True,
        secure=settings.is_production,
        samesite="lax",
        path="/bff",
    )
    return response


@router.get("/callback", summary="Finish the console sign-in and set the console cookie")
async def bff_callback(request: Request) -> RedirectResponse:
    params = request.query_params
    stored = await services.take_state(params.get("state", ""))
    if stored is None or not secrets.compare_digest(
        hash_token(request.cookies.get(services.STATE_COOKIE, "")), stored["binding"]
    ):
        return _login_failed("invalid_state")
    if "error" in params:
        return _login_failed(params["error"])

    try:
        tokens = await oauth_services.exchange_code(
            await services.console_client(),
            {"code": params.get("code", ""), "redirect_uri": services.redirect_uri(), "code_verifier": stored["verifier"]},
        )
    except OAuthError:
        return _login_failed("invalid_code")

    claims = await verify_access_token(tokens["access_token"])
    session = await Session.get(public_id=claims.sid)
    handle = new_opaque_token()
    await services.create_bff_session(handle, session, tokens)

    response = RedirectResponse("/", status_code=302)
    response.delete_cookie(services.STATE_COOKIE, path="/bff")
    response.set_cookie(
        services.CONSOLE_COOKIE,
        handle,
        max_age=int((session.expires_at - utcnow()).total_seconds()),
        httponly=True,
        secure=settings.is_production,
        samesite="strict",
        path="/",
    )
    return response


@router.get("/session", response_model=ConsoleSession, summary="The signed-in user, roles and CSRF token")
async def bff_session(request: Request):
    row = await services.load(request)
    claims = await services.claims_from_cookie(request) if row else None
    if row is None or claims is None:
        raise AppError(401, "not_authenticated", "Authentication required")
    user: User = row.session.user
    return {
        "user": {
            "public_id": str(user.public_id),
            "username": user.username,
            "email": user.email,
            "first_name": user.first_name,
            "last_name": user.last_name,
        },
        "roles": claims.roles,
        "is_admin": "Admin" in claims.roles,
        "csrf_token": row.csrf_token,
    }


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT, summary="Sign out of the console and its SSO session")
async def bff_logout(request: Request) -> Response:
    row = await services.load(request)
    # Without a session there's no CSRF token to check, so nothing may change here. Otherwise a cross-site
    # form could clear cookies while the session stays live.
    if row is None:
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    services.check_csrf(request, row)
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    response.delete_cookie(services.CONSOLE_COOKIE, path="/")
    response.delete_cookie(SSO_COOKIE, path="/")
    async with in_transaction():
        await revoke_session(row.session)
    return response
