"""Small pure helpers for the OAuth flows."""

import base64
import hmac
import re
from urllib.parse import unquote

from fastapi import Request

from app.users.models import User
from utilities.crypto import pkce_challenge

TOKEN_TYPE_ACCESS = "urn:ietf:params:oauth:token-type:access_token"
GRANT_EXCHANGE = "urn:ietf:params:oauth:grant-type:token-exchange"

_VERIFIER = re.compile(r"^[A-Za-z0-9\-._~]{43,128}$")


class OAuthError(Exception):
    """Reported in the RFC 6749 shape {"error", "error_description"}, not the API's usual one."""

    def __init__(self, error: str, description: str, status_code: int = 400) -> None:
        super().__init__(description)
        self.error = error
        self.description = description
        self.status_code = status_code


def basic_credentials(request: Request) -> tuple[str, str] | None:
    """client_secret_basic. None when the header is absent."""
    header = request.headers.get("authorization", "")
    if not header.lower().startswith("basic "):
        return None
    try:
        decoded = base64.b64decode(header[6:], validate=True).decode()
        client_id, secret = decoded.split(":", 1)
    except (ValueError, UnicodeDecodeError):
        raise OAuthError("invalid_client", "Malformed client credentials", 401) from None
    return unquote(client_id), unquote(secret)


def pkce_matches(verifier: str, challenge: str) -> bool:
    if not _VERIFIER.match(verifier):
        return False
    return hmac.compare_digest(pkce_challenge(verifier), challenge)


def profile_claims(user: User, scope: str) -> dict:
    """The OIDC claims a scope allows, for the ID token and userinfo."""
    scopes = scope.split()
    claims: dict = {}
    if "profile" in scopes:
        claims.update(preferred_username=user.username, given_name=user.first_name, family_name=user.last_name)
    if "email" in scopes:
        claims.update(email=user.email)
    return {key: value for key, value in claims.items() if value is not None}
