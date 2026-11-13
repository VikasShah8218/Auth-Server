from urllib.parse import urlsplit

OIDC_SCOPES = {"openid", "profile", "email"}
SERVICE_SCOPES = {"events.read", "permissions.read", "users.read"}


def check_redirect_uri(uri: str) -> str:
    """https, or http on localhost. No fragment. Custom mobile schemes aren't supported yet."""
    parts = urlsplit(uri)
    local = parts.hostname in ("localhost", "127.0.0.1")
    if parts.scheme != "https" and not (parts.scheme == "http" and local):
        raise ValueError("redirect URIs must use https, or http on localhost")
    if parts.fragment or not parts.hostname:
        raise ValueError("redirect URIs need a host and can't have a fragment")
    return uri
