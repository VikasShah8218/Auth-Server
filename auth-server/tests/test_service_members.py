"""Members and roles for downstream servers: GET /v1/apps/{key}/members and /roles (scope users.read),
and the members.changed event that tells them to refresh."""

import base64
import json

import pytest

from app.applications.models import Role
from app.events.models import OutboxEvent
from app.security.policy_audit import main as policy_audit
from tests.conftest import make_app
from tests.helpers import bearer, create_client, create_service, full_login, grant, make_user, service_token

SCOPES = ["events.read", "permissions.read", "users.read"]


def claims_of(token: str) -> dict:
    payload = token.split(".")[1]
    return json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))


async def add_role(client, admin, name, key="ANPR", permissions=()) -> dict:
    role = (await client.post(f"/v1/admin/applications/{key}/roles", headers=admin, json={"name": name})).json()
    ids = []
    for code in permissions:
        created = await client.post(f"/v1/admin/applications/{key}/permissions", headers=admin, json={"code": code})
        ids.append(created.json()["id"])
    if ids:
        await client.put(
            f"/v1/admin/applications/{key}/roles/{role['id']}/permissions", headers=admin, json={"permission_ids": ids}
        )
    return role


@pytest.fixture
async def reader(client, admin):
    """App ANPR, a service client with users.read, and its bearer header."""
    await make_app(client, admin)
    created = await create_client(
        client, admin, client_id="anpr-api", type="confidential", redirect_uris=[], scopes=SCOPES
    )
    return bearer(await service_token(client, "anpr-api", created["client_secret"]))


async def events_of(key: str, type: str) -> list[OutboxEvent]:
    return await OutboxEvent.filter(app__key=key, type=type).order_by("seq")


# 1. Members


async def test_members_lists_this_apps_members_with_token_sub(client, admin, reader):
    await add_role(client, admin, "Operator")
    await create_client(client, admin)  # public client, to sign alice in for a real token
    alice = await make_user("alice", first_name="Alice", last_name="Smith", email="alice@example.com")
    await grant(alice, "ANPR", "Operator")
    await grant(alice, "ANPR", "Admin")
    bob = await make_user("bob", is_active=False)
    await grant(bob, "ANPR", "Operator")
    await make_user("carol")  # no role in ANPR: not a member

    response = await client.get("/v1/apps/ANPR/members", headers=reader)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["next_cursor"] is None
    assert [m["username"] for m in body["items"]] == ["alice", "bob"]

    first = body["items"][0]
    roles = {role.name: str(role.public_id) for role in await Role.filter(app__key="ANPR")}
    assert first == {
        "sub": str(alice.public_id),
        "username": "alice",
        "given_name": "Alice",
        "family_name": "Smith",
        "email": "alice@example.com",
        "is_active": True,
        "roles": [{"id": roles["Admin"], "name": "Admin"}, {"id": roles["Operator"], "name": "Operator"}],
    }
    tokens = await full_login(client, username="alice")
    assert claims_of(tokens["access_token"])["sub"] == first["sub"]

    second = body["items"][1]
    assert second["is_active"] is False
    assert second["given_name"] is None and second["family_name"] is None and second["email"] is None


async def test_members_never_leak_other_apps_or_private_fields(client, admin, reader):
    await make_app(client, admin, key="SNVR")
    await add_role(client, admin, "Viewer", key="SNVR")
    alice = await make_user("alice")
    await grant(alice, "ANPR")
    await grant(alice, "SNVR", "Viewer")
    await grant(await make_user("dave"), "SNVR", "Viewer")

    items = (await client.get("/v1/apps/ANPR/members", headers=reader)).json()["items"]
    assert [m["username"] for m in items] == ["alice"]
    assert [r["name"] for r in items[0]["roles"]] == ["Admin"]
    assert set(items[0]) == {"sub", "username", "given_name", "family_name", "email", "is_active", "roles"}


# 2 and 3. Who may call


async def test_members_and_roles_need_a_service_token_with_users_read(client, admin, reader):
    plain = await create_service(client, admin, client_id="anpr-plain")
    without_scope = bearer(await service_token(client, "anpr-plain", plain))
    await create_client(client, admin)
    await grant(await make_user("alice"), "ANPR")
    user_token = bearer((await full_login(client, username="alice"))["access_token"])

    for path in ("/v1/apps/ANPR/members", "/v1/apps/ANPR/roles"):
        response = await client.get(path, headers=without_scope)
        assert response.status_code == 403
        assert response.json()["detail"]["code"] == "insufficient_scope"
        assert (await client.get(path, headers=user_token)).status_code == 401
        assert (await client.get(path)).status_code == 401
        assert (await client.get(path, headers=reader)).status_code == 200


async def test_a_client_reads_only_its_own_application(client, admin, reader):
    await make_app(client, admin, key="SNVR")
    for path in ("/v1/apps/SNVR/members", "/v1/apps/SNVR/roles"):
        response = await client.get(path, headers=reader)
        assert response.status_code == 403
        assert response.json()["detail"]["code"] == "wrong_application"

    # A deactivated app's service tokens stop working altogether.
    await client.patch("/v1/admin/applications/ANPR", headers=admin, json={"is_active": False})
    assert (await client.get("/v1/apps/ANPR/members", headers=reader)).status_code == 401


# 4. Paging and search


async def test_cursor_walk_returns_every_member_once(client, admin, reader):
    names = [f"user{i:02d}" for i in range(7)]
    for name in reversed(names):
        await grant(await make_user(name), "ANPR")

    seen, cursor, pages = [], None, 0
    while True:
        params = {"limit": 3} | ({"cursor": cursor} if cursor else {})
        body = (await client.get("/v1/apps/ANPR/members", headers=reader, params=params)).json()
        seen += [m["username"] for m in body["items"]]
        pages += 1
        cursor = body["next_cursor"]
        if cursor is None:
            break
    assert seen == names
    assert pages == 3

    exact = (await client.get("/v1/apps/ANPR/members", headers=reader, params={"limit": 7})).json()
    assert exact["next_cursor"] is None and len(exact["items"]) == 7


async def test_search_and_bad_input(client, admin, reader):
    await grant(await make_user("alice", first_name="Alice", email="a@corp.example"), "ANPR")
    await grant(await make_user("bob", last_name="Builder"), "ANPR")

    def names(response):
        return [m["username"] for m in response.json()["items"]]

    assert names(await client.get("/v1/apps/ANPR/members", headers=reader, params={"q": "BUILD"})) == ["bob"]
    assert names(await client.get("/v1/apps/ANPR/members", headers=reader, params={"q": "corp"})) == ["alice"]
    assert names(await client.get("/v1/apps/ANPR/members", headers=reader, params={"q": "ali"})) == ["alice"]

    for cursor in ("%%%", "YWxpY2U=", "YWxpY2", "", "4oCm"[:-1]):
        bad = await client.get("/v1/apps/ANPR/members", headers=reader, params={"cursor": cursor})
        if cursor == "":
            assert bad.status_code == 200  # an empty cursor is the first page
            continue
        assert bad.status_code == 422, cursor
        assert bad.json()["detail"]["code"] == "invalid_cursor"
    for limit in (0, 1001):
        assert (await client.get("/v1/apps/ANPR/members", headers=reader, params={"limit": limit})).status_code == 422


# 5. Roles


async def test_roles_list_names_ids_and_active_permission_codes(client, admin, reader):
    operator = await add_role(client, admin, "Operator", permissions=("live.view", "camera.manage", "old.thing"))
    old = next(
        p for p in (await client.get("/v1/admin/applications/ANPR/permissions", headers=admin)).json()
        if p["code"] == "old.thing"
    )
    await client.delete(f"/v1/admin/applications/ANPR/permissions/{old['id']}", headers=admin)
    await make_app(client, admin, key="SNVR")
    await add_role(client, admin, "Elsewhere", key="SNVR")

    response = await client.get("/v1/apps/ANPR/roles", headers=reader)
    assert response.status_code == 200
    roles = response.json()
    assert [r["name"] for r in roles] == ["Admin", "Operator"]
    by_name = {r["name"]: r for r in roles}
    assert by_name["Admin"]["permissions"] == ["*"]
    assert by_name["Operator"] == {
        "id": operator["public_id"],
        "name": "Operator",
        "description": None,
        "permissions": ["camera.manage", "live.view"],
    }


async def test_role_id_survives_a_rename(client, admin, reader):
    role = await add_role(client, admin, "Operator")
    await client.patch(f"/v1/admin/applications/ANPR/roles/{role['id']}", headers=admin, json={"name": "Guard"})
    roles = {r["name"]: r["id"] for r in (await client.get("/v1/apps/ANPR/roles", headers=reader)).json()}
    assert roles["Guard"] == role["public_id"]


# 6. members.changed


async def test_role_changes_announce_members_changed_for_that_app_only(client, admin):
    await make_app(client, admin)
    await make_app(client, admin, key="SNVR")
    before = len(await events_of("ANPR", "members.changed"))

    role = await add_role(client, admin, "Operator")  # created, no members
    path = f"/v1/admin/applications/ANPR/roles/{role['id']}"
    await client.patch(path, headers=admin, json={"description": "Gate staff"})
    await client.patch(path, headers=admin, json={"name": "Guard"})  # renamed, no members
    await client.delete(path, headers=admin)  # deleted, no members

    with_member = await add_role(client, admin, "Viewer")
    await grant(await make_user("alice"), "ANPR", "Viewer")
    await client.delete(f"/v1/admin/applications/ANPR/roles/{with_member['id']}", headers=admin)

    events = await events_of("ANPR", "members.changed")
    assert len(events) - before == 6
    assert all(event.payload == {} for event in events[before:])
    assert await events_of("SNVR", "members.changed") == []


async def test_profile_change_announces_to_each_of_the_users_apps(client, admin):
    await make_app(client, admin)
    await make_app(client, admin, key="SNVR")
    await make_app(client, admin, key="OTHR")
    alice = await make_user("alice", first_name="Alice")
    await grant(alice, "ANPR")
    await grant(alice, "SNVR")
    path = f"/v1/admin/users/{alice.public_id}"

    await client.patch(path, headers=admin, json={"first_name": "Alicia", "email": "alicia@example.com"})
    for key in ("ANPR", "SNVR"):
        events = await events_of(key, "members.changed")
        assert [event.payload for event in events] == [{"sub": str(alice.public_id)}]
    assert await events_of("OTHR", "members.changed") == []

    await client.patch(path, headers=admin, json={"first_name": "Alicia"})  # no real change
    assert len(await events_of("ANPR", "members.changed")) == 1

    # Disable and rename together: both events, one transaction.
    response = await client.patch(path, headers=admin, json={"is_active": False, "last_name": "Smith"})
    assert response.status_code == 200
    assert len(await events_of("ANPR", "members.changed")) == 2
    assert len(await events_of("ANPR", "user.disabled")) == 1


# 7. Policy


def test_policy_audit_covers_the_new_routes(capsys):
    assert policy_audit() == 0
    out = capsys.readouterr().out
    assert "/v1/apps/{key}/members" in out and "/v1/apps/{key}/roles" in out
