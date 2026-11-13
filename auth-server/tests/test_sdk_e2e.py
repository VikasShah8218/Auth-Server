"""S8 exit checks, with real processes.

A real auth server runs under uvicorn. The SDK connects to it over HTTP and SSE.
Changes are made from this test process, which is a separate Postgres client, so
each one also proves that an event crosses replicas by way of NOTIFY.
"""

import asyncio
import os
import socket
import subprocess
import sys
import time

import httpx
import pytest
from tortoise.transactions import in_transaction

from app.applications import services as service
from app.users import services as user_service
from app.applications.models import Application
from app.applications.schemas import ApplicationCreate, PermissionCreate, RoleCreate
from app.events.models import DownstreamCursor, OutboxEvent
from app.events.services import publish_event
from utilities.crypto import hash_token
from app.clients.models import OAuthClient
from auth_sdk import AuthError, AuthSDK, StaleAuthState
from tests.conftest import ACTOR
from tests.helpers import REDIRECT_URI, grant, location_query, make_user, pkce, PASSWORD

SECRET = "service-client-secret-for-tests"


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class AuthProcess:
    def __init__(self):
        self.port = free_port()
        self.url = f"http://127.0.0.1:{self.port}"
        self.process = None

    def start(self):
        env = {**os.environ, "ISSUER": self.url}
        self.process = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "main:app", "--port", str(self.port), "--log-level", "warning"],
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

    async def wait_ready(self):
        async with httpx.AsyncClient() as http:
            for _ in range(100):
                try:
                    if (await http.get(f"{self.url}/health/ready", timeout=1)).status_code == 200:
                        return
                except httpx.TransportError:
                    pass
                await asyncio.sleep(0.1)
        pytest.fail("Auth server did not start")

    def stop(self):
        if self.process is not None:
            self.process.terminate()
            self.process.wait(timeout=10)
            self.process = None


@pytest.fixture
async def world():
    """An app, permissions, a role, two users, and a service client."""
    app = await service.create_application(ApplicationCreate(key="ANPR", name="ANPR"), ACTOR)
    read = await service.create_permission("ANPR", PermissionCreate(code="vehicle.read"), ACTOR)
    await service.create_permission("ANPR", PermissionCreate(code="vehicle.write"), ACTOR)
    role = await service.create_role("ANPR", RoleCreate(name="Viewer"), ACTOR)
    await service.set_role_permissions("ANPR", role.id, [read.id], ACTOR)

    alice = await make_user("alice")
    bob = await make_user("bob")
    await grant(alice, "ANPR", "Viewer")
    await grant(bob, "ANPR", "Viewer")

    await OAuthClient.create(
        client_id="anpr-web",
        name="web",
        app=app,
        type="public",
        redirect_uris=[REDIRECT_URI],
        scopes=["openid", "profile"],
    )
    await OAuthClient.create(
        client_id="anpr-api",
        name="api",
        app=app,
        type="confidential",
        secret_hash=hash_token(SECRET),
        scopes=["events.read", "permissions.read"],
    )
    return app, alice, bob, role


@pytest.fixture
async def auth_server(world):
    server = AuthProcess()
    server.start()
    await server.wait_ready()
    yield server
    server.stop()


def new_sdk(server, **options) -> AuthSDK:
    return AuthSDK(server.url, "ANPR", "anpr-api", SECRET, **options)


@pytest.fixture
async def sdk(auth_server):
    client = new_sdk(auth_server)
    await client.start()
    yield client
    await client.stop()


async def wait_until(condition, timeout=5.0) -> float:
    started = time.monotonic()
    while time.monotonic() - started < timeout:
        if await condition() if asyncio.iscoroutinefunction(condition) else condition():
            return time.monotonic() - started
        await asyncio.sleep(0.02)
    pytest.fail("Condition not met in time")


async def wait_connected(client) -> None:
    await wait_until(lambda: client.health()["connected"])


async def real_login(server, username="alice") -> dict:
    async with httpx.AsyncClient(base_url=server.url) as http:
        login = await http.post(
            "/v1/identity/login", json={"username": username, "password": PASSWORD}
        )
        assert login.status_code == 200, login.text
        verifier, challenge = pkce()
        authorized = await http.get(
            "/oauth/authorize",
            params={
                "response_type": "code",
                "client_id": "anpr-web",
                "redirect_uri": REDIRECT_URI,
                "scope": "openid",
                "code_challenge": challenge,
                "code_challenge_method": "S256",
            },
        )
        tokens = await http.post(
            "/oauth/token",
            data={
                "grant_type": "authorization_code",
                "client_id": "anpr-web",
                "code": location_query(authorized)["code"],
                "redirect_uri": REDIRECT_URI,
                "code_verifier": verifier,
            },
        )
        assert tokens.status_code == 200, tokens.text
        return tokens.json()


async def test_valid_token_verifies_locally_with_permissions(auth_server, sdk):
    await wait_connected(sdk)
    tokens = await real_login(auth_server)
    principal = await sdk.verify(tokens["access_token"])
    assert principal.roles == ["Viewer"]
    assert principal.has_perm("vehicle.read")
    assert not principal.has_perm("vehicle.write")
    assert not principal.has_perm("no.such.permission")


async def test_revocation_takes_effect_within_two_seconds_and_is_acked(auth_server, sdk):
    """Plan exit check."""
    app = await Application.get(key="ANPR")
    await wait_connected(sdk)
    tokens = await real_login(auth_server)
    principal = await sdk.verify(tokens["access_token"])
    assert principal

    async with httpx.AsyncClient(base_url=auth_server.url) as http:
        assert (
            await http.post(
                "/oauth/logout", headers={"Authorization": f"Bearer {tokens['access_token']}"}
            )
        ).status_code == 204

    async def rejected():
        try:
            await sdk.verify(tokens["access_token"])
            return False
        except AuthError:
            return True

    assert await wait_until(rejected, timeout=2.0) < 2.0

    last = (await OutboxEvent.filter(app_id=app.id).order_by("-seq").first()).seq

    async def acknowledged():
        cursor = await DownstreamCursor.get_or_none(instance_id=sdk.instance_id)
        return cursor is not None and cursor.last_acked_seq == last

    for _ in range(100):
        if await acknowledged():
            break
        await asyncio.sleep(0.02)
    assert await acknowledged()


async def test_access_change_from_another_process_reaches_the_stream(auth_server, sdk, world):
    """This process stands in for a second replica, so the event has to cross
    processes through Postgres NOTIFY."""
    _, alice, _, _ = world
    await wait_connected(sdk)
    tokens = await real_login(auth_server)

    await user_service.set_user_roles(alice.public_id, "ANPR", [], ACTOR)

    async def rejected():
        try:
            await sdk.verify(tokens["access_token"])
            return False
        except AuthError:
            return True

    assert await wait_until(rejected, timeout=2.0) < 2.0


async def test_revoking_one_user_leaves_others_working(auth_server, sdk, world):
    _, alice, bob, _ = world
    await wait_connected(sdk)
    alice_tokens = await real_login(auth_server, "alice")
    bob_tokens = await real_login(auth_server, "bob")

    await user_service.set_user_roles(alice.public_id, "ANPR", [], ACTOR)
    await wait_until(lambda: str(alice.public_id) in sdk._min_versions and sdk._min_versions[str(alice.public_id)] > 0)

    assert await sdk.verify(bob_tokens["access_token"])
    with pytest.raises(AuthError):
        await sdk.verify(alice_tokens["access_token"])


async def test_valid_tokens_keep_working_with_the_auth_server_stopped(auth_server, sdk):
    """Plan exit check."""
    await wait_connected(sdk)
    tokens = await real_login(auth_server)
    auth_server.stop()
    await asyncio.sleep(0.3)

    principal = await sdk.verify(tokens["access_token"])
    assert principal.has_perm("vehicle.read")
    assert sdk.health()["connected"] is False


async def test_new_permission_is_learned_without_a_restart(auth_server, sdk):
    await wait_connected(sdk)
    await service.create_permission("ANPR", PermissionCreate(code="report.export"), ACTOR)
    await wait_until(lambda: "report.export" in sdk._bits, timeout=2.0)


async def test_consumer_catches_up_after_being_down(auth_server, world):
    """Events made during an outage arrive once, in order, after reconnecting."""
    app, alice, _, _ = world
    client = new_sdk(auth_server)
    await client.start()
    await wait_connected(client)
    await client.stop()
    cursor = client._cursor

    await user_service.set_user_roles(alice.public_id, "ANPR", [], ACTOR)
    last = (await OutboxEvent.filter(app_id=app.id).order_by("-seq").first()).seq
    assert last > cursor

    resumed = new_sdk(auth_server)
    resumed._cursor = cursor
    await resumed.start()
    await wait_until(lambda: resumed._cursor == last)
    assert resumed._min_versions[str(alice.public_id)] >= 1
    await resumed.stop()


async def test_cursor_past_retention_recovers_through_a_snapshot(auth_server, world):
    app, alice, _, _ = world
    await user_service.set_user_roles(alice.public_id, "ANPR", [], ACTOR)
    async with in_transaction():
        await publish_event([app.id], "x", {})
    await OutboxEvent.filter(app_id=app.id).delete()
    async with in_transaction():
        await publish_event([app.id], "y", {})

    client = new_sdk(auth_server)
    client._cursor = 1
    await client.start()
    await wait_connected(client)
    assert client._cursor == (await OutboxEvent.filter(app_id=app.id).order_by("-seq").first()).seq
    assert str(alice.public_id) in client._min_versions
    await client.stop()


async def test_state_file_lets_a_server_start_during_an_outage(auth_server, tmp_path):
    state = str(tmp_path / "auth-state.json")
    client = new_sdk(auth_server, state_path=state)
    await client.start()
    await wait_connected(client)
    tokens = await real_login(auth_server)
    await client.stop()
    auth_server.stop()

    restarted = new_sdk(auth_server, state_path=state)
    principal = await restarted.verify(tokens["access_token"])
    assert principal.has_perm("vehicle.read")
    await restarted._http.aclose()


async def test_high_risk_server_denies_when_stale(auth_server):
    client = new_sdk(auth_server, max_staleness_seconds=1)
    await client.start()
    await wait_connected(client)
    tokens = await real_login(auth_server)
    assert await client.verify(tokens["access_token"])

    auth_server.stop()
    await asyncio.sleep(1.2)
    with pytest.raises(StaleAuthState):
        await client.verify(tokens["access_token"])
    await client.stop()


async def test_token_for_another_app_is_refused(auth_server):
    other = AuthSDK(auth_server.url, "HID", "anpr-api", SECRET)
    await other.refresh_keys()
    other._cursor = 0
    tokens = await real_login(auth_server)
    with pytest.raises(AuthError):
        await other.verify(tokens["access_token"])
    await other._http.aclose()


async def test_tokens_are_refused_before_the_first_sync(auth_server):
    """It can't tell a revoked token from a good one until it has the state."""
    client = new_sdk(auth_server)
    await client.refresh_keys()
    tokens = await real_login(auth_server)
    with pytest.raises(StaleAuthState):
        await client.verify(tokens["access_token"])
    await client._http.aclose()


async def test_sync_survives_a_client_version_bump(auth_server, sdk, world):
    """A routine admin edit kills the cached service token. The SDK must replace it
    at once, not stay blind until that token would have expired."""
    _, alice, _, _ = world
    await wait_connected(sdk)
    tokens = await real_login(auth_server)
    from app.events.services import publish_event

    client_row = await OAuthClient.get(client_id="anpr-api")
    async with in_transaction():
        client_row.version += 1
        await client_row.save(update_fields=["version"])
        await publish_event(
            [client_row.app_id],
            "client.revoked",
            {"client_id": "anpr-api", "version": client_row.version, "revoked_at": 0},
        )

    async def still_syncing():
        cursor = await DownstreamCursor.get_or_none(instance_id=sdk.instance_id)
        last = (await OutboxEvent.all().order_by("-seq").first()).seq
        return cursor is not None and sdk._cursor == last and cursor.last_acked_seq == last

    for _ in range(150):
        if await still_syncing():
            break
        await asyncio.sleep(0.02)
    assert await still_syncing()

    await user_service.set_user_roles(alice.public_id, "ANPR", [], ACTOR)

    async def rejected():
        try:
            await sdk.verify(tokens["access_token"])
            return False
        except AuthError:
            return True

    assert await wait_until(rejected, timeout=20) < 20


async def test_revoked_key_reaches_a_running_server_process(auth_server, sdk):
    """The key is revoked from this process. The running server must drop it at once."""
    from app.keys import services as keys
    from app.keys.models import SigningKey

    await wait_connected(sdk)
    tokens = await real_login(auth_server)
    active = await SigningKey.get(status="active")
    headers = {"Authorization": f"Bearer {tokens['access_token']}"}
    async with httpx.AsyncClient(base_url=auth_server.url) as http:
        assert (await http.get("/oauth/userinfo", headers=headers)).status_code == 200
        await keys.revoke_key(active.kid)
        await asyncio.sleep(0.5)
        assert (await http.get("/oauth/userinfo", headers=headers)).status_code == 401


async def test_forged_events_are_ignored(auth_server, sdk):
    await wait_connected(sdk)
    cursor = sdk._cursor
    with pytest.raises(Exception):
        await sdk._handle_event("eyJhbGciOiJub25lIn0.eyJzZXEiOjk5OX0.")
    assert sdk._cursor == cursor


async def test_sync_survives_a_restart_of_the_auth_server(auth_server, sdk, world):
    _, alice, _, _ = world
    await wait_connected(sdk)
    auth_server.stop()
    await wait_until(lambda: not sdk.health()["connected"])
    await user_service.set_user_roles(alice.public_id, "ANPR", [], ACTOR)

    auth_server.start()
    await auth_server.wait_ready()
    await wait_until(lambda: sdk._min_versions.get(str(alice.public_id), 0) >= 1, timeout=10)


async def test_example_service_guards_a_route_with_the_sdk(auth_server, tmp_path):
    from fastapi import Depends, FastAPI

    client = new_sdk(auth_server)
    await client.start()
    await wait_connected(client)
    app = FastAPI()

    @app.get("/vehicles")
    async def vehicles(_=Depends(client.require_perm("vehicle.read"))):
        return ["ok"]

    @app.get("/edit")
    async def edit(_=Depends(client.require_perm("vehicle.write"))):
        return ["ok"]

    tokens = await real_login(auth_server)
    headers = {"Authorization": f"Bearer {tokens['access_token']}"}
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
        assert (await http.get("/vehicles")).status_code == 401
        assert (await http.get("/vehicles", headers=headers)).status_code == 200
        assert (await http.get("/edit", headers=headers)).status_code == 403
    await client.stop()

