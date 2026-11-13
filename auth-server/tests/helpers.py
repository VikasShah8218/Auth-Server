import base64
import hashlib
import secrets
from urllib.parse import parse_qs, urlsplit

from app.applications.models import Role, UserRole
from app.users.models import User
from app.users.utils import hash_password

PASSWORD = "a-long-enough-pass-1"
REDIRECT_URI = "https://app.example.com/callback"


def pkce() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(48)
    digest = hashlib.sha256(verifier.encode()).digest()
    return verifier, base64.urlsafe_b64encode(digest).rstrip(b"=").decode()


async def make_user(username="alice", **fields) -> User:
    return await User.create(username=username, password_hash=hash_password(PASSWORD), **fields)


async def grant(user: User, app_key: str, role_name: str = "Admin") -> None:
    role = await Role.get(app__key=app_key, name=role_name)
    await UserRole.create(user=user, role=role)


async def create_client(client, admin, client_id="anpr-web", **fields) -> dict:
    body = {
        "client_id": client_id,
        "name": client_id,
        "app_key": "ANPR",
        "type": "public",
        "redirect_uris": [REDIRECT_URI],
        "scopes": ["openid", "profile", "email"],
        **fields,
    }
    response = await client.post("/v1/admin/clients", headers=admin, json=body)
    assert response.status_code == 201, response.text
    return response.json()


async def create_service(client, admin, client_id="anpr-api", **fields) -> str:
    created = await create_client(
        client,
        admin,
        client_id=client_id,
        type="confidential",
        redirect_uris=[],
        scopes=["events.read", "permissions.read"],
        **fields,
    )
    return created["client_secret"]


async def password_login(client, username="alice", password=PASSWORD):
    return await client.post(
        "/v1/identity/login", json={"username": username, "password": password}
    )


def location_query(response) -> dict:
    return {k: v[0] for k, v in parse_qs(urlsplit(response.headers["location"]).query).items()}


async def authorize(client, client_id="anpr-web", **overrides):
    verifier, challenge = pkce()
    params = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": REDIRECT_URI,
        "scope": "openid profile",
        "state": "state-1",
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        **overrides,
    }
    response = await client.get("/oauth/authorize", params=params)
    return response, verifier


async def get_code(client, client_id="anpr-web", **overrides) -> tuple[str, str]:
    response, verifier = await authorize(client, client_id, **overrides)
    assert response.status_code == 302, response.text
    query = location_query(response)
    assert "code" in query, query
    return query["code"], verifier


async def redeem(client, code, verifier, client_id="anpr-web", **overrides):
    return await client.post(
        "/oauth/token",
        data={
            "grant_type": "authorization_code",
            "client_id": client_id,
            "code": code,
            "redirect_uri": REDIRECT_URI,
            "code_verifier": verifier,
            **overrides,
        },
    )


async def refresh(client, token, client_id="anpr-web", **overrides):
    return await client.post(
        "/oauth/token",
        data={"grant_type": "refresh_token", "client_id": client_id, "refresh_token": token, **overrides},
    )


async def full_login(client, client_id="anpr-web", username="alice") -> dict:
    """Password, SSO cookie, code and PKCE: the whole browser flow."""
    assert (await password_login(client, username)).status_code == 200
    code, verifier = await get_code(client, client_id)
    response = await redeem(client, code, verifier, client_id)
    assert response.status_code == 200, response.text
    return response.json()


async def service_token(client, client_id, secret, **form) -> str:
    response = await client.post(
        "/oauth/token",
        data={"grant_type": "client_credentials", **form},
        auth=(client_id, secret),
    )
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


def bearer(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}
