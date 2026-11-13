"""S6 and S7 exit checks. Live SSE delivery is proven end to end in test_sdk_e2e.py."""

import asyncio
from datetime import datetime, timedelta, timezone

import pytest
from tortoise.transactions import in_transaction

import main
from app.applications.models import Application, UserAppState
from app.events.hub import hub
from app.events.models import DownstreamCursor, OutboxEvent
from app.events.services import publish_event
from app.events.stream import event_frames
from app.events.services import prune_outbox_tick
from app.identity.models import Session
from app.identity.services import cleanup_tick
from app.keys.services import key_rotation_tick
from app.keys import services as keys
from app.tokens import services as jwt
from app.keys.models import SigningKey
from app.oauth.models import AuthorizationCode, RefreshToken
from app.tokens.schemas import ServiceClaims
from tests.conftest import make_app
from utilities.common import run_exclusive, run_periodic
from tests.helpers import (
    bearer,
    create_client,
    create_service,
    full_login,
    get_code,
    grant,
    make_user,
    password_login,
    service_token,
)


@pytest.fixture
async def service(client, admin):
    app = await make_app(client, admin)
    secret = await create_service(client, admin)
    token = await service_token(client, "anpr-api", secret)
    return app, bearer(token)


async def events_of(app) -> list[OutboxEvent]:
    return await OutboxEvent.filter(app_id=app.id).order_by("seq")


async def test_publish_outside_a_transaction_is_refused(client, admin):
    app = await make_app(client, admin)
    with pytest.raises(RuntimeError, match="inside a transaction"):
        await publish_event([app.id], "x", {})


async def test_rolled_back_change_publishes_nothing(client, admin):
    """Plan exit check."""
    app = await make_app(client, admin)
    before = len(await events_of(app))
    with pytest.raises(RuntimeError):
        async with in_transaction():
            await publish_event([app.id], "x", {})
            raise RuntimeError("abort")
    assert len(await events_of(app)) == before


async def test_a_rollback_leaves_no_gap_in_the_sequence(client, admin):
    app = await make_app(client, admin)
    with pytest.raises(RuntimeError):
        async with in_transaction():
            await publish_event([app.id], "lost", {})
            raise RuntimeError("abort")
    async with in_transaction():
        await publish_event([app.id], "kept", {})
    seqs = [event.seq for event in await events_of(app)]
    assert seqs == list(range(1, len(seqs) + 1))


async def test_concurrent_events_get_gapless_numbers(client, admin):
    app = await make_app(client, admin)

    async def publish(index):
        async with in_transaction():
            await publish_event([app.id], "x", {"index": index})

    await asyncio.gather(*(publish(i) for i in range(20)))
    assert [e.seq for e in await events_of(app)] == list(range(1, 21))


async def test_access_change_reaches_the_outbox_with_the_new_version(client, admin):
    app = await make_app(client, admin)
    user = await make_user()
    role = (await client.get("/v1/admin/applications/ANPR/roles", headers=admin)).json()[0]
    await client.put(
        f"/v1/admin/users/{user.public_id}/roles",
        headers=admin,
        json={"app_key": "ANPR", "role_ids": [role["id"]]},
    )
    event = (await events_of(app))[-1]
    assert event.type == "user.access_changed"
    assert event.payload == {"users": [{"sub": str(user.public_id), "ver": 1}]}


async def test_every_event_type_is_published(client, admin):
    app = await make_app(client, admin)
    await create_client(client, admin)
    secret = await create_service(client, admin)
    user = await make_user()
    await grant(user, "ANPR")
    tokens = await full_login(client)

    await client.post(
        "/v1/admin/applications/ANPR/permissions", headers=admin, json={"code": "door.read"}
    )
    await client.post("/oauth/logout", headers=bearer(tokens["access_token"]))
    await client.patch(f"/v1/admin/users/{user.public_id}", headers=admin, json={"is_active": False})
    await client.post("/v1/admin/clients/anpr-api/rotate-secret", headers=admin)
    await keys.rotate_keys()
    assert secret

    types = {event.type for event in await events_of(app)}
    assert types >= {
        "session.revoked",
        "user.disabled",
        "client.revoked",
        "key.rotated",
        "permissions.changed",
    }


async def test_one_change_affecting_two_apps_reaches_both(client, admin):
    first = await make_app(client, admin)
    second = await make_app(client, admin, "HID")
    await create_client(client, admin)
    user = await make_user()
    await grant(user, "ANPR")
    await grant(user, "HID")
    tokens = await full_login(client)
    await client.post("/oauth/logout", headers=bearer(tokens["access_token"]))
    for app in (first, second):
        assert (await events_of(app))[-1].type == "session.revoked"


async def test_stream_needs_the_right_scope_and_application(client, admin, service):
    await make_app(client, admin, "HID")
    _, headers = service
    assert (await client.get("/v1/events/ANPR?after=0")).status_code == 401
    wrong_app = await client.get("/v1/events/HID?after=0", headers=headers)
    assert wrong_app.status_code == 403

    secret = await create_service(client, admin, client_id="no-events")
    limited = await service_token(client, "no-events", secret, scope="permissions.read")
    denied = await client.get("/v1/events/ANPR?after=0", headers=bearer(limited))
    assert denied.status_code == 403


async def test_stream_needs_a_cursor(client, service):
    _, headers = service
    assert (await client.get("/v1/events/ANPR", headers=headers)).status_code == 422


async def test_pruned_cursor_is_told_to_fetch_a_snapshot(client, service):
    app, headers = service
    async with in_transaction():
        for _ in range(3):
            await publish_event([app.id], "x", {})
    await OutboxEvent.filter(app_id=app.id, seq__lte=2).delete()

    response = await client.get("/v1/events/ANPR?after=0", headers=headers)
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "snapshot_required"


async def test_cursor_from_the_future_is_refused(client, service):
    _, headers = service
    assert (await client.get("/v1/events/ANPR?after=999", headers=headers)).status_code == 409


class FakeRequest:
    def __init__(self, stop_after):
        self.stop_after = stop_after
        self.calls = 0

    async def is_disconnected(self):
        self.calls += 1
        return self.calls > self.stop_after


def service_claims(exp=None) -> ServiceClaims:
    return ServiceClaims(
        sub="anpr-api",
        client_id="anpr-api",
        app="ANPR",
        aud="AUTH",
        ver=0,
        exp=exp or int(datetime.now(timezone.utc).timestamp()) + 600,
    )


async def collect(app, after, stop_after=1, claims=None) -> list[str]:
    frames = []
    async for frame in event_frames(app, 1, claims or service_claims(), None, after, FakeRequest(stop_after)):
        frames.append(frame)
    return frames


async def test_replay_delivers_each_missed_event_once_in_order(client, service):
    app, _ = service
    async with in_transaction():
        for index in range(5):
            await publish_event([app.id], "x", {"index": index})
    frames = await collect(app, after=2)
    ids = [int(f.split("\n")[0].removeprefix("id: ")) for f in frames]
    assert ids == [3, 4, 5]


async def test_events_are_signed(client, service):
    app, _ = service
    async with in_transaction():
        await publish_event([app.id], "user.disabled", {"users": []})
    frame = (await collect(app, after=0))[0]
    signed = frame.split("data: ")[1].strip()
    claims = await jwt.decode(signed, jwt.TYP_EVENT)
    assert claims["type"] == "user.disabled"
    assert claims["aud"] == "ANPR"
    assert claims["seq"] == 1


async def test_large_backlog_is_delivered_in_batches(client, service):
    app, _ = service
    async with in_transaction():
        for _ in range(450):
            await publish_event([app.id], "x", {})
    assert len(await collect(app, after=0, stop_after=3)) == 450


async def test_stream_closes_when_the_service_token_expires(client, service):
    app, _ = service
    past = int(datetime.now(timezone.utc).timestamp()) - 1
    frames = await collect(app, after=0, stop_after=5, claims=service_claims(exp=past))
    assert frames[-1].startswith("event: token.expired")


async def test_hub_wakes_a_waiter_on_notify(client, service):
    """A real LISTEN connection and a real commit."""
    app, _ = service
    hub.start()
    await asyncio.sleep(0.3)
    waiter = asyncio.create_task(hub.wait(app.id, 5))
    await asyncio.sleep(0.05)
    started = asyncio.get_running_loop().time()
    async with in_transaction():
        await publish_event([app.id], "x", {})
    await waiter
    assert asyncio.get_running_loop().time() - started < 2


async def test_ack_is_recorded_and_never_goes_backwards(client, service):
    app, headers = service
    async with in_transaction():
        for _ in range(5):
            await publish_event([app.id], "x", {})
    url = "/v1/events/ANPR/ack"
    assert (await client.post(url, headers=headers, json={"instance_id": "a", "seq": 4})).status_code == 204
    assert (await client.post(url, headers=headers, json={"instance_id": "a", "seq": 2})).status_code == 204
    assert (await DownstreamCursor.get(instance_id="a")).last_acked_seq == 4


async def test_ack_past_the_last_event_is_refused(client, service):
    _, headers = service
    response = await client.post(
        "/v1/events/ANPR/ack", headers=headers, json={"instance_id": "a", "seq": 99}
    )
    assert response.status_code == 422


async def test_downstream_status_shows_lag_per_instance(client, admin, service):
    app, headers = service
    async with in_transaction():
        for _ in range(3):
            await publish_event([app.id], "x", {})
    await client.post("/v1/events/ANPR/ack", headers=headers, json={"instance_id": "a", "seq": 3})
    await client.post("/v1/events/ANPR/ack", headers=headers, json={"instance_id": "b", "seq": 1})
    await DownstreamCursor.filter(instance_id="b").update(
        last_seen_at=datetime.now(timezone.utc) - timedelta(minutes=5)
    )
    entries = {
        e["instance_id"]: e
        for e in (await client.get("/v1/admin/downstream?app=anpr", headers=admin)).json()
    }
    assert entries["a"]["status"] == "ok" and entries["a"]["lag"] == 0
    assert entries["b"]["status"] == "offline" and entries["b"]["lag"] == 2


async def test_snapshot_gives_a_resume_point_and_current_state(client, admin, service):
    app, headers = service
    await create_client(client, admin)
    user = await make_user()
    await grant(user, "ANPR")
    await UserAppState.create(user=user, app=app, version=7)
    tokens = await full_login(client)
    await client.post("/oauth/logout", headers=bearer(tokens["access_token"]))

    snapshot = (await client.get("/v1/events/ANPR/snapshot", headers=headers)).json()
    assert snapshot["seq"] == (await events_of(app))[-1].seq
    assert snapshot["users"] == [{"sub": str(user.public_id), "ver": 7, "is_active": True}]
    assert len(snapshot["revoked_sessions"]) == 1


async def test_snapshot_lists_sessions_reached_only_by_role(client, admin, service):
    """A session can reach an app through exchange, with no refresh token there."""
    _, headers = service
    await make_app(client, admin, "HID")
    await create_client(client, admin, client_id="hid-web", app_key="HID")
    user = await make_user()
    await grant(user, "HID")
    await grant(user, "ANPR")
    tokens = await full_login(client, "hid-web")
    await client.post("/oauth/logout", headers=bearer(tokens["access_token"]))
    snapshot = (await client.get("/v1/events/ANPR/snapshot", headers=headers)).json()
    assert len(snapshot["revoked_sessions"]) == 1


async def test_snapshot_lists_revoked_clients(client, admin, service):
    _, headers = service
    await create_service(client, admin, client_id="gone-api")
    await client.patch("/v1/admin/clients/gone-api", headers=admin, json={"is_active": False})
    snapshot = (await client.get("/v1/events/ANPR/snapshot", headers=headers)).json()
    entry = next(c for c in snapshot["revoked_clients"] if c["client_id"] == "gone-api")
    assert entry["version"] == 1


async def test_revoking_all_sessions_with_mixed_apps_cannot_deadlock(client, admin):
    from app.identity.services import revoke_user_sessions

    for key in ("AAA", "BBB", "CCC"):
        await make_app(client, admin, key)
    users = [await make_user(f"user{i}") for i in range(4)]
    for user in users:
        for key in ("AAA", "BBB", "CCC"):
            await grant(user, key)
        for _ in range(3):
            await Session.create(
                user=user,
                token_hash=f"{user.id}-{_}",
                auth_time=datetime.now(timezone.utc),
                expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
            )

    async def revoke(user):
        async with in_transaction():
            await revoke_user_sessions(user.id)

    await asyncio.wait_for(asyncio.gather(*(revoke(u) for u in users)), 20)
    assert not await Session.filter(revoked_at__isnull=True).exists()


async def test_permission_map_lists_retired_bits_too(client, admin, service):
    _, headers = service
    created = await client.post(
        "/v1/admin/applications/ANPR/permissions", headers=admin, json={"code": "door.read"}
    )
    await client.delete(
        f"/v1/admin/applications/ANPR/permissions/{created.json()['id']}", headers=admin
    )
    body = (await client.get("/v1/apps/ANPR/permission-map", headers=headers)).json()
    assert body["version"] == 3
    assert {"code": "door.read", "bit": 1, "retired": True} in body["permissions"]


# Worker


async def test_cleanup_removes_only_what_has_expired(client, admin):
    await make_app(client, admin)
    await create_client(client, admin)
    user = await make_user()
    await grant(user, "ANPR")
    await full_login(client)
    await get_code(client)
    await password_login(client)

    assert await RefreshToken.all().count() == 1
    await cleanup_tick()
    assert await RefreshToken.all().count() == 1

    past = datetime.now(timezone.utc) - timedelta(seconds=1)
    await AuthorizationCode.all().update(expires_at=past)
    await RefreshToken.all().update(expires_at=past)
    await Session.all().update(expires_at=past)
    await cleanup_tick()
    assert await AuthorizationCode.all().count() == 0
    assert await RefreshToken.all().count() == 0
    assert await Session.all().count() == 0


async def test_prune_keeps_events_inside_retention(client, admin):
    app = await make_app(client, admin)
    async with in_transaction():
        await publish_event([app.id], "old", {})
        await publish_event([app.id], "new", {})
    await OutboxEvent.filter(type="old").update(
        created_at=datetime.now(timezone.utc) - timedelta(days=8)
    )
    await prune_outbox_tick()
    assert [e.type for e in await events_of(app)] == ["new"]


async def test_key_rotates_when_due_and_not_before(client):
    active = await SigningKey.get(status="active")
    await key_rotation_tick()
    assert (await SigningKey.get(status="active")).kid == active.kid

    await SigningKey.filter(id=active.id).update(
        activated_at=datetime.now(timezone.utc) - timedelta(days=31)
    )
    await key_rotation_tick()
    assert (await SigningKey.get(status="active")).kid != active.kid


async def test_two_workers_do_not_double_rotate(client):
    """Plan exit check: the lock makes the second worker skip."""
    await SigningKey.filter(status="active").update(
        activated_at=datetime.now(timezone.utc) - timedelta(days=31)
    )
    results = await asyncio.gather(*(run_exclusive(725103, key_rotation_tick) for _ in range(4)))
    assert results.count(True) >= 1
    assert await SigningKey.filter(status="active").count() == 1
    assert await SigningKey.filter(status="retired").count() == 1
    assert await SigningKey.filter(status="next").count() == 1


async def run_jobs_once() -> None:
    """One pass of every scheduled job, the way main.py's lifespan runs them."""
    for _, lock_id, tick in main.JOBS:
        await run_exclusive(lock_id, tick)


def test_every_job_has_its_own_lock():
    locks = [lock_id for _, lock_id, _ in main.JOBS]
    assert len(locks) == len(set(locks))


async def test_a_failing_job_keeps_its_loop_running():
    calls = []
    done = asyncio.Event()

    async def flaky():
        calls.append(True)
        if len(calls) == 1:
            raise RuntimeError("job failed")
        done.set()

    loop = asyncio.create_task(run_periodic("flaky", 0, flaky))
    await asyncio.wait_for(done.wait(), 5)
    loop.cancel()
    await asyncio.gather(loop, return_exceptions=True)
    assert len(calls) >= 2


async def test_application_table_is_untouched_by_the_worker(client, admin):
    await make_app(client, admin)
    before = await Application.all().count()
    await run_jobs_once()
    assert await Application.all().count() == before
