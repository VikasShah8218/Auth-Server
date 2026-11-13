"""S9: the console BFF, WebAuthn with a software authenticator, and headers."""

import hashlib
import json
import struct
from urllib.parse import urlsplit

import cbor2
import pytest
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from webauthn.helpers import bytes_to_base64url

from app.audit.models import AuditLog
from cli import create_admin
from app.identity.models import MfaFactor, Session
from main import create_app
from app.console.services import CONSOLE_COOKIE, CSRF_HEADER
from app.console.models import BffSession
from app.oauth.models import RefreshToken
from tests.conftest import ADMIN_PASSWORD
from tests.helpers import make_user, password_login

ORIGIN = "http://localhost:8000"
RP_ID = "localhost"


async def console_login(client, username="root.admin", password=ADMIN_PASSWORD) -> dict:
    """The browser's whole trip: login page, /bff/login, authorize, callback."""
    assert (await password_login(client, username, password)).status_code == 200
    start = await client.get("/bff/login")
    assert start.status_code == 302
    location = start.headers["location"]
    authorized = await client.get(location)
    assert authorized.status_code == 302, authorized.text
    target = urlsplit(authorized.headers["location"])
    done = await client.get(f"{target.path}?{target.query}")
    assert done.status_code == 302, done.text
    assert done.headers["location"] == "/"
    return (await client.get("/bff/session")).json()


@pytest.fixture
async def root():
    return await create_admin("root.admin", "root@example.com", ADMIN_PASSWORD)


async def test_console_login_gives_a_cookie_and_no_token_to_the_browser(client, root):
    session = await console_login(client)
    assert session["is_admin"] is True
    assert session["user"]["username"] == "root.admin"
    assert "access_token" not in json.dumps(session)
    assert "refresh_token" not in json.dumps(session)


async def test_console_cookie_is_locked_down(client, root):
    await password_login(client, "root.admin", ADMIN_PASSWORD)
    start = await client.get("/bff/login")
    authorized = await client.get(start.headers["location"])
    target = urlsplit(authorized.headers["location"])
    done = await client.get(f"{target.path}?{target.query}")
    cookie = done.headers["set-cookie"]
    assert "HttpOnly" in cookie and "SameSite=strict" in cookie


async def test_tokens_are_encrypted_on_the_server(client, root):
    await console_login(client)
    row = await BffSession.get()
    assert not row.encrypted_access_token.startswith("eyJ")


async def test_console_reaches_the_admin_api_by_cookie(client, root):
    await console_login(client)
    assert (await client.get("/v1/admin/stats")).status_code == 200


async def test_write_without_csrf_token_is_refused(client, root):
    """A cookie goes along automatically, so it alone proves nothing."""
    session = await console_login(client)
    body = {"key": "ANPR", "name": "ANPR"}
    refused = await client.post("/v1/admin/applications", json=body)
    assert refused.status_code == 403
    assert refused.json()["detail"]["code"] == "csrf_failed"

    wrong = await client.post("/v1/admin/applications", json=body, headers={CSRF_HEADER: "nope"})
    assert wrong.status_code == 403

    allowed = await client.post(
        "/v1/admin/applications", json=body, headers={CSRF_HEADER: session["csrf_token"]}
    )
    assert allowed.status_code == 201


async def test_expired_access_token_renews_silently(client, root):
    await console_login(client)
    from datetime import datetime, timedelta, timezone

    await BffSession.all().update(access_expires_at=datetime.now(timezone.utc) - timedelta(seconds=1))
    assert (await client.get("/v1/admin/stats")).status_code == 200
    assert await RefreshToken.all().count() == 2


async def test_role_change_is_picked_up_without_a_new_login(client, root):
    session = await console_login(client)
    assert session["is_admin"]

    from app.applications.models import Role

    role = await Role.get(app__key="AUTH", name="Admin")
    other = await make_user("second.admin")
    from app.applications.models import UserRole

    await UserRole.create(user=other, role=role)
    from app.applications.services import bump_versions as _bump_versions, get_app
    from tortoise.transactions import in_transaction

    app = await get_app("AUTH")
    await UserRole.filter(user_id=root.id).delete()
    async with in_transaction():
        await _bump_versions(app.id, [root.id])

    assert (await client.get("/v1/admin/stats")).status_code == 403


async def test_ordinary_user_can_sign_in_but_not_administer(client, root):
    await make_user("plain.user")
    from tests.helpers import PASSWORD

    session = await console_login(client, "plain.user", PASSWORD)
    assert session["is_admin"] is False
    assert (await client.get("/v1/me")).status_code == 200
    assert (await client.get("/v1/admin/stats")).status_code == 403


async def test_console_logout_ends_the_session_and_cookies(client, root):
    session = await console_login(client)
    refused = await client.post("/bff/logout")
    assert refused.status_code == 403

    done = await client.post("/bff/logout", headers={CSRF_HEADER: session["csrf_token"]})
    assert done.status_code == 204
    assert (await client.get("/bff/session")).status_code == 401
    assert await BffSession.all().count() == 0
    assert (await Session.get()).revoked_at is not None


async def test_cross_site_logout_changes_nothing(client, root):
    """SameSite=Strict keeps the console cookie off a cross-site POST, so the request
    arrives with only the SSO cookie. It must not clear anything."""
    await console_login(client)
    console = client.cookies[CONSOLE_COOKIE]
    client.cookies.delete(CONSOLE_COOKIE)
    response = await client.post("/bff/logout")
    assert response.status_code == 204
    assert "set-cookie" not in response.headers
    client.cookies.set(CONSOLE_COOKIE, console)
    assert (await Session.get()).revoked_at is None
    assert (await client.get("/bff/session")).status_code == 200


async def test_parallel_console_requests_keep_the_session(client, root):
    """Each one may need a refresh, and only one gets a new refresh token."""
    import asyncio
    from datetime import datetime, timedelta, timezone

    await console_login(client)
    await BffSession.all().update(access_expires_at=datetime.now(timezone.utc) - timedelta(seconds=1))
    results = await asyncio.gather(*(client.get("/v1/admin/stats") for _ in range(4)))
    assert [r.status_code for r in results] == [200, 200, 200, 200]

    await BffSession.all().update(access_expires_at=datetime.now(timezone.utc) - timedelta(seconds=1))
    assert (await client.get("/v1/admin/stats")).status_code == 200
    assert (await Session.get()).revoked_at is None


async def test_callback_rejects_a_forged_state(client, root):
    response = await client.get("/bff/callback?state=forged&code=x")
    assert response.status_code == 302
    assert "invalid_state" in response.headers["location"]


async def test_callback_from_another_browser_is_refused(app, client, root):
    """Login CSRF: an attacker's finished login must not land in a victim's browser."""
    from httpx import ASGITransport, AsyncClient

    await password_login(client, "root.admin", ADMIN_PASSWORD)
    start = await client.get("/bff/login")
    authorized = await client.get(start.headers["location"])
    target = urlsplit(authorized.headers["location"])

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as victim:
        response = await victim.get(f"{target.path}?{target.query}")
        assert "invalid_state" in response.headers["location"]
        assert CONSOLE_COOKIE not in response.headers.get("set-cookie", "")


async def test_callback_state_works_only_once(client, root):
    await password_login(client, "root.admin", ADMIN_PASSWORD)
    start = await client.get("/bff/login")
    authorized = await client.get(start.headers["location"])
    target = urlsplit(authorized.headers["location"])
    url = f"{target.path}?{target.query}"
    assert (await client.get(url)).headers["location"] == "/"
    assert "invalid_state" in (await client.get(url)).headers["location"]


async def test_session_without_a_cookie_is_401(client):
    assert (await client.get("/bff/session")).status_code == 401


async def test_a_stale_cookie_value_is_useless(client, root):
    client.cookies.set(CONSOLE_COOKIE, "forged")
    assert (await client.get("/bff/session")).status_code == 401
    assert (await client.get("/v1/admin/stats")).status_code == 401


# Real tokens through the self-service API


async def test_password_change_keeps_this_login_and_ends_others(client, root):
    from httpx import ASGITransport, AsyncClient

    session = await console_login(client)
    transport = ASGITransport(app=client._transport.app)
    async with AsyncClient(transport=transport, base_url="http://test") as other:
        await console_login(other)
        response = await client.post(
            "/v1/me/password",
            headers={CSRF_HEADER: session["csrf_token"]},
            json={"current_password": ADMIN_PASSWORD, "new_password": "a-brand-new-password"},
        )
        assert response.status_code == 204
        assert (await other.get("/bff/session")).status_code == 401
    assert (await client.get("/bff/session")).status_code == 200


async def test_wrong_current_password_changes_nothing(client, root):
    session = await console_login(client)
    response = await client.post(
        "/v1/me/password",
        headers={CSRF_HEADER: session["csrf_token"]},
        json={"current_password": "wrong-password", "new_password": "a-brand-new-password"},
    )
    assert response.status_code == 401
    assert not await AuditLog.filter(action="user.password_change").exists()


async def test_user_can_list_and_end_their_own_sessions(client, root):
    session = await console_login(client)
    listed = (await client.get("/v1/me/sessions")).json()
    assert len(listed) == 1 and listed[0]["current"] is True
    ended = await client.delete(
        f"/v1/me/sessions/{listed[0]['id']}", headers={CSRF_HEADER: session["csrf_token"]}
    )
    assert ended.status_code == 204


async def test_user_cannot_end_someone_elses_session(client, root):
    session = await console_login(client)
    other = await make_user("someone.else")
    from app.identity.services import create_session

    theirs, _ = await create_session(other, ["pwd"], None, None)
    response = await client.delete(
        f"/v1/me/sessions/{theirs.public_id}", headers={CSRF_HEADER: session["csrf_token"]}
    )
    assert response.status_code == 404
    await theirs.refresh_from_db()
    assert theirs.revoked_at is None


async def test_admin_password_reset_ends_the_users_sessions(client, admin):
    user = await make_user()
    await password_login(client)
    response = await client.post(
        f"/v1/admin/users/{user.public_id}/password",
        headers=admin,
        json={"new_password": "reset-by-the-admin-1"},
    )
    assert response.status_code == 204
    assert (await Session.get()).revoked_at is not None


async def test_admin_mfa_reset_clears_factors(client, admin):
    user = await make_user()
    await MfaFactor.create(user=user, type="totp", encrypted_secret="x")
    response = await client.delete(f"/v1/admin/users/{user.public_id}/mfa", headers=admin)
    assert response.status_code == 204
    assert not await MfaFactor.exists()


async def test_admin_key_endpoints(client, admin):
    keys = (await client.get("/v1/admin/keys", headers=admin)).json()
    assert {key["status"] for key in keys} == {"active", "next"}
    assert "encrypted_private_key" not in str(keys)
    rotated = await client.post("/v1/admin/keys/rotate", headers=admin)
    assert rotated.status_code == 200
    assert rotated.json()["status"] == "active"


async def test_stats(client, admin):
    stats = (await client.get("/v1/admin/stats", headers=admin)).json()
    assert stats["users"] == 1 and stats["applications"] == 1


# WebAuthn


class SoftAuthenticator:
    """A real ES256 authenticator in software, so these tests run the same
    signature checks a hardware key would face."""

    def __init__(self):
        self.key = ec.generate_private_key(ec.SECP256R1())
        self.credential_id = b"soft-credential-" + bytes(16)
        self.counter = 0

    def _cose(self) -> bytes:
        numbers = self.key.public_key().public_numbers()
        return cbor2.dumps(
            {
                1: 2,
                3: -7,
                -1: 1,
                -2: numbers.x.to_bytes(32, "big"),
                -3: numbers.y.to_bytes(32, "big"),
            }
        )

    def _client_data(self, kind, challenge, origin) -> bytes:
        return json.dumps(
            {"type": kind, "challenge": challenge, "origin": origin, "crossOrigin": False},
            separators=(",", ":"),
        ).encode()

    def _auth_data(self, attested: bool, rp_id: str = RP_ID) -> bytes:
        flags = 0x01 | 0x04 | (0x40 if attested else 0)
        data = hashlib.sha256(rp_id.encode()).digest() + bytes([flags])
        data += struct.pack(">I", self.counter)
        if attested:
            data += bytes(16)
            data += struct.pack(">H", len(self.credential_id)) + self.credential_id
            data += self._cose()
        return data

    def register(self, challenge: str, origin: str = ORIGIN) -> dict:
        client_data = self._client_data("webauthn.create", challenge, origin)
        attestation = cbor2.dumps(
            {"fmt": "none", "attStmt": {}, "authData": self._auth_data(True)}
        )
        encoded = bytes_to_base64url(self.credential_id)
        return {
            "id": encoded,
            "rawId": encoded,
            "type": "public-key",
            "response": {
                "clientDataJSON": bytes_to_base64url(client_data),
                "attestationObject": bytes_to_base64url(attestation),
            },
        }

    def authenticate(self, challenge: str, origin: str = ORIGIN) -> dict:
        self.counter += 1
        client_data = self._client_data("webauthn.get", challenge, origin)
        auth_data = self._auth_data(False)
        signature = self.key.sign(
            auth_data + hashlib.sha256(client_data).digest(), ec.ECDSA(hashes.SHA256())
        )
        encoded = bytes_to_base64url(self.credential_id)
        return {
            "id": encoded,
            "rawId": encoded,
            "type": "public-key",
            "response": {
                "clientDataJSON": bytes_to_base64url(client_data),
                "authenticatorData": bytes_to_base64url(auth_data),
                "signature": bytes_to_base64url(signature),
            },
        }


@pytest.fixture
async def enrolled(client, tokens):
    user = await make_user()
    headers = tokens(user, roles=())
    key = SoftAuthenticator()
    from tests.helpers import PASSWORD

    options = (
        await client.post(
            "/v1/me/mfa/webauthn/options", headers=headers, json={"password": PASSWORD}
        )
    ).json()
    response = await client.post(
        "/v1/me/mfa/webauthn/register",
        headers=headers,
        json={"credential": key.register(options["challenge"]), "name": "Test key"},
    )
    assert response.status_code == 204, response.text
    return user, key, headers


async def begin_key_login(client) -> tuple[str, str]:
    login = (await password_login(client)).json()
    assert login["status"] == "mfa_required" and login["methods"] == ["webauthn"]
    options = await client.post(
        "/v1/identity/webauthn/options", json={"challenge": login["challenge"]}
    )
    assert options.status_code == 200, options.text
    return login["challenge"], options.json()["challenge"]


async def test_key_login_end_to_end(client, enrolled):
    _, key, _ = enrolled
    challenge, webauthn_challenge = await begin_key_login(client)
    response = await client.post(
        "/v1/identity/webauthn/verify",
        json={"challenge": challenge, "credential": key.authenticate(webauthn_challenge)},
    )
    assert response.status_code == 200, response.text
    assert (await Session.get()).amr == ["pwd", "hwk"]
    assert (await MfaFactor.get()).sign_count == 1


async def test_a_different_key_is_refused(client, enrolled):
    _, key, _ = enrolled
    challenge, webauthn_challenge = await begin_key_login(client)
    impostor = SoftAuthenticator()
    response = await client.post(
        "/v1/identity/webauthn/verify",
        json={"challenge": challenge, "credential": impostor.authenticate(webauthn_challenge)},
    )
    assert response.status_code == 401
    assert not await Session.exists()


async def test_phishing_site_origin_is_refused(client, enrolled):
    """The reason WebAuthn beats TOTP: a signature made on a fake site is useless."""
    _, key, _ = enrolled
    challenge, webauthn_challenge = await begin_key_login(client)
    response = await client.post(
        "/v1/identity/webauthn/verify",
        json={
            "challenge": challenge,
            "credential": key.authenticate(webauthn_challenge, origin="https://evil.example"),
        },
    )
    assert response.status_code == 401


async def test_replayed_assertion_is_refused(client, enrolled):
    _, key, _ = enrolled
    challenge, webauthn_challenge = await begin_key_login(client)
    credential = key.authenticate(webauthn_challenge)
    first = await client.post(
        "/v1/identity/webauthn/verify", json={"challenge": challenge, "credential": credential}
    )
    assert first.status_code == 200

    challenge, _ = await begin_key_login(client)
    replay = await client.post(
        "/v1/identity/webauthn/verify", json={"challenge": challenge, "credential": credential}
    )
    assert replay.status_code == 401


async def test_cloned_key_with_an_old_counter_is_refused(client, enrolled):
    _, key, _ = enrolled
    challenge, webauthn_challenge = await begin_key_login(client)
    await client.post(
        "/v1/identity/webauthn/verify",
        json={"challenge": challenge, "credential": key.authenticate(webauthn_challenge)},
    )
    key.counter = 0
    challenge, webauthn_challenge = await begin_key_login(client)
    response = await client.post(
        "/v1/identity/webauthn/verify",
        json={"challenge": challenge, "credential": key.authenticate(webauthn_challenge)},
    )
    assert response.status_code == 401


async def test_removing_a_key_needs_the_password(client, enrolled):
    _, _, headers = enrolled
    factor = await MfaFactor.get()
    url = f"/v1/me/mfa/webauthn/{factor.public_id}/remove"
    wrong = await client.post(url, headers=headers, json={"password": "wrong-password"})
    assert wrong.status_code == 401
    from tests.helpers import PASSWORD

    right = await client.post(url, headers=headers, json={"password": PASSWORD})
    assert right.status_code == 204


async def test_factor_list_hides_key_material(client, enrolled):
    _, _, headers = enrolled
    body = (await client.get("/v1/me/mfa", headers=headers)).text
    assert "public_key" not in body and "credential_id" not in body


# Headers and production settings


async def test_security_headers_are_on_every_response(client):
    response = await client.get("/health/live")
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
    assert response.headers["referrer-policy"] == "no-referrer"


def test_docs_are_off_in_production(monkeypatch):
    from settings.settings import get_settings

    settings = get_settings()
    monkeypatch.setattr(type(settings), "is_production", property(lambda _: True))
    app = create_app()
    paths = {getattr(route, "path", None) for route in app.routes}
    assert "/docs" not in paths and "/openapi.json" not in paths
