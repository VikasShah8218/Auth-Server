"""OAuth 2.1 / OpenID Connect endpoints. They authenticate themselves (see app/security/policy.py), and the
token endpoints answer errors in the RFC 6749 shape."""

import time
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Request, Response, status
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.security import HTTPAuthorizationCredentials
from tortoise.transactions import in_transaction

from app.clients.models import OAuthClient
from app.clients.utils import OIDC_SCOPES
from app.identity.models import Session
from app.identity.services import is_session_live, revoke_session, session_from_cookie
from app.identity.utils import SSO_COOKIE
from app.keys.services import ALGORITHM, public_jwks
from app.oauth import services
from app.oauth.utils import GRANT_EXCHANGE, OAuthError, profile_claims
from app.tokens.deps import service_bearer
from app.tokens.services import verify_access_token
from app.users.models import User
from settings.settings import settings
from utilities.exceptions import AppError

router = APIRouter(tags=["OAuth / OIDC"])

_NO_STORE = {"Cache-Control": "no-store", "Pragma": "no-cache"}


def _json_error(exc: OAuthError) -> JSONResponse:
    headers = dict(_NO_STORE)
    if exc.status_code == 401:
        headers["WWW-Authenticate"] = "Basic"
    return JSONResponse(
        {"error": exc.error, "error_description": exc.description}, status_code=exc.status_code, headers=headers
    )


async def _form(request: Request) -> dict[str, str]:
    return {key: str(value) for key, value in (await request.form()).items()}


# Discovery


@router.get("/.well-known/openid-configuration", summary="OpenID Connect discovery document")
async def discovery() -> dict:
    issuer = settings.ISSUER
    return {
        "issuer": issuer,
        "authorization_endpoint": f"{issuer}/oauth/authorize",
        "token_endpoint": f"{issuer}/oauth/token",
        "userinfo_endpoint": f"{issuer}/oauth/userinfo",
        "revocation_endpoint": f"{issuer}/oauth/revoke",
        "end_session_endpoint": f"{issuer}/oauth/logout",
        "jwks_uri": f"{issuer}/.well-known/jwks.json",
        "response_types_supported": ["code"],
        "response_modes_supported": ["query"],
        "grant_types_supported": ["authorization_code", "refresh_token", "client_credentials", GRANT_EXCHANGE],
        "subject_types_supported": ["public"],
        "id_token_signing_alg_values_supported": [ALGORITHM],
        "token_endpoint_auth_methods_supported": ["client_secret_basic", "client_secret_post", "none"],
        "code_challenge_methods_supported": ["S256"],
        "scopes_supported": sorted(OIDC_SCOPES),
        "authorization_response_iss_parameter_supported": True,
        "claims_supported": [
            "sub", "iss", "aud", "exp", "iat", "auth_time", "nonce", "sid", "amr",
            "preferred_username", "given_name", "family_name", "email",
        ],
    }


@router.get("/.well-known/jwks.json", summary="Public signing keys (next, active and retired)")
async def jwks() -> JSONResponse:
    return JSONResponse(await public_jwks(), headers={"Cache-Control": "public, max-age=60"})


# Authorization code + PKCE


def _login_redirect(request: Request, reauthenticate: bool) -> RedirectResponse:
    params = dict(request.query_params)
    params.pop("prompt", None)
    params.pop("max_age", None)
    if reauthenticate:
        params["login_after"] = str(int(time.time()))
    return_to = f"/oauth/authorize?{urlencode(params)}"
    return RedirectResponse(f"{settings.LOGIN_PAGE_PATH}?{urlencode({'return_to': return_to})}", status_code=302)


def _client_error(message: str) -> JSONResponse:
    """Before the redirect URI is proven, redirecting would be an open redirect."""
    return JSONResponse({"error": "invalid_request", "error_description": message}, status_code=400)


@router.get("/oauth/authorize", summary="Start sign-in: redirects back with a code, or to the login page")
async def authorize(request: Request):
    params = request.query_params
    client = await OAuthClient.get_or_none(client_id=params.get("client_id", ""), is_active=True).select_related("app")
    redirect_uri = params.get("redirect_uri", "")
    if client is None or not client.app.is_active:
        return _client_error("Unknown client")
    if redirect_uri not in client.redirect_uris:
        return _client_error("redirect_uri is not registered for this client")

    def back(**result: str) -> RedirectResponse:
        query = {**result, "iss": settings.ISSUER}
        if params.get("state"):
            query["state"] = params["state"]
        separator = "&" if "?" in redirect_uri else "?"
        return RedirectResponse(f"{redirect_uri}{separator}{urlencode(query)}", status_code=302)

    if params.get("response_type") != "code":
        return back(error="unsupported_response_type")
    challenge = params.get("code_challenge")
    if not challenge or params.get("code_challenge_method") != "S256":
        return back(error="invalid_request", error_description="PKCE with S256 is required")
    try:
        scope = services.validate_scope(client, params.get("scope"))
    except OAuthError as exc:
        return back(error=exc.error, error_description=exc.description)

    prompt = params.get("prompt", "")
    session = await session_from_cookie(request.cookies.get(SSO_COOKIE))

    stale = False
    if session is not None:
        age = time.time() - session.auth_time.timestamp()
        max_age = params.get("max_age", "")
        login_after = params.get("login_after", "")
        stale = (
            prompt == "login"
            or (max_age.isdigit() and age > int(max_age))
            or (login_after.isdigit() and session.auth_time.timestamp() < int(login_after))
        )

    if session is None or stale:
        if prompt == "none":
            return back(error="login_required")
        return _login_redirect(request, reauthenticate=stale)

    if not await services.user_may_use_app(session.user, client.app):
        return back(error="access_denied", error_description="You have no access to this application")

    code = await services.create_authorization_code(
        client, session, redirect_uri, scope, challenge, params.get("nonce")
    )
    return back(code=code)


# Token endpoint


@router.post("/oauth/token", summary="Token endpoint: code, refresh, client credentials, token exchange")
async def token(request: Request) -> JSONResponse:
    form = await _form(request)
    grant = form.get("grant_type", "")
    try:
        client = await services.authenticate_client(request, form)
        if grant == "authorization_code":
            result = await services.exchange_code(client, form)
        elif grant == "refresh_token":
            result = await services.refresh(client, form)
        elif grant == "client_credentials":
            result = await services.client_credentials(client, form)
        elif grant == GRANT_EXCHANGE:
            result = await services.token_exchange(client, form)
        else:
            raise OAuthError("unsupported_grant_type", "This grant type is not supported")
    except OAuthError as exc:
        return _json_error(exc)
    return JSONResponse(result, headers=_NO_STORE)


@router.post("/oauth/revoke", summary="Revoke a refresh token and its whole family (RFC 7009)")
async def revoke(request: Request) -> Response:
    form = await _form(request)
    try:
        client = await services.authenticate_client(request, form)
    except OAuthError as exc:
        return _json_error(exc)
    await services.revoke_token(client, form.get("token", ""))
    return Response(status_code=status.HTTP_200_OK, headers=_NO_STORE)


@router.get("/oauth/userinfo", summary="OIDC userinfo for an access token of any application")
async def userinfo(credentials: HTTPAuthorizationCredentials | None = Depends(service_bearer)) -> dict:
    if credentials is None:
        raise AppError(401, "not_authenticated", "Authentication required", {"WWW-Authenticate": "Bearer"})
    claims = await verify_access_token(credentials.credentials)
    user = await User.get(public_id=claims.sub)
    return {"sub": str(user.public_id), **profile_claims(user, claims.scope)}


@router.post("/oauth/logout", status_code=status.HTTP_204_NO_CONTENT,
             summary="End one login, named by a bearer token or the SSO cookie")
async def logout(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(service_bearer),
) -> Response:
    """Other logins of the same user are untouched. A token for any app is accepted on purpose, because each
    app needs a way to sign its user out."""
    # A token names one login exactly, so it wins over whatever cookie came along.
    if credentials is not None:
        claims = await verify_access_token(credentials.credentials)
        session = await Session.get_or_none(public_id=claims.sid).select_related("user")
    else:
        session = await session_from_cookie(request.cookies.get(SSO_COOKIE))

    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    if credentials is None:
        response.delete_cookie(SSO_COOKIE, path="/")
    if session is not None and await is_session_live(session):
        async with in_transaction():
            await revoke_session(session)
    return response
