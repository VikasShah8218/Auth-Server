"""Fields the console needs: users list extras, a user's factors, permission bits, stats, key rotation date,
audit actor names."""

from datetime import datetime, timedelta, timezone

from app.applications.models import Permission
from app.identity.models import MfaFactor, Session
from app.keys.models import SigningKey
from tests.conftest import make_app
from tests.helpers import grant, make_user


async def _confirmed_totp(user) -> None:
    await MfaFactor.create(user=user, type="totp", encrypted_secret="x", confirmed_at=datetime.now(timezone.utc))


async def test_users_list_shows_applications_and_mfa(client, admin):
    await make_app(client, admin, "ANPR")
    await make_app(client, admin, "SNVR")
    alice = await make_user("alice")
    await grant(alice, "ANPR")
    await grant(alice, "SNVR")
    await _confirmed_totp(alice)
    await make_user("bob")

    response = await client.get("/v1/admin/users", headers=admin)
    assert response.status_code == 200
    rows = {row["username"]: row for row in response.json()["items"]}
    assert rows["alice"]["app_keys"] == ["ANPR", "SNVR"]
    assert rows["alice"]["mfa_enabled"] is True
    assert rows["bob"]["app_keys"] == []
    assert rows["bob"]["mfa_enabled"] is False


async def test_users_list_filters_by_application(client, admin):
    await make_app(client, admin, "ANPR")
    alice = await make_user("alice")
    await grant(alice, "ANPR")
    await make_user("bob")

    response = await client.get("/v1/admin/users", params={"app": "anpr"}, headers=admin)
    body = response.json()
    assert [row["username"] for row in body["items"]] == ["alice"]
    assert body["total"] == 1


async def test_admin_sees_a_users_factors(client, admin):
    alice = await make_user("alice")
    await _confirmed_totp(alice)
    await MfaFactor.create(user=alice, type="totp", encrypted_secret="y")  # unconfirmed: not listed

    response = await client.get(f"/v1/admin/users/{alice.public_id}/mfa", headers=admin)
    assert response.status_code == 200
    assert [factor["type"] for factor in response.json()] == ["totp"]


async def test_user_detail_carries_the_apps_bit_map(client, admin):
    app = await make_app(client, admin, "ANPR")
    await client.post("/v1/admin/applications/ANPR/permissions", headers=admin, json={"code": "vehicle.read"})
    old = await client.post("/v1/admin/applications/ANPR/permissions", headers=admin, json={"code": "old.thing"})
    await client.delete(f"/v1/admin/applications/ANPR/permissions/{old.json()['id']}", headers=admin)
    role = await client.post("/v1/admin/applications/ANPR/roles", headers=admin, json={"name": "Viewer"})
    read = await Permission.get(app_id=app.id, code="vehicle.read")
    await client.put(
        f"/v1/admin/applications/ANPR/roles/{role.json()['id']}/permissions",
        headers=admin,
        json={"permission_ids": [read.id]},
    )
    alice = await make_user("alice")
    await grant(alice, "ANPR", "Viewer")

    response = await client.get(f"/v1/admin/users/{alice.public_id}", headers=admin)
    anpr = response.json()["applications"][0]
    assert anpr["bits"] == [
        {"code": "*", "bit": 0, "retired": False, "held": False},
        {"code": "vehicle.read", "bit": 1, "retired": False, "held": True},
        {"code": "old.thing", "bit": 2, "retired": True, "held": False},
    ]


async def test_stats_include_the_dashboard_details(client, admin, admin_user):
    await make_app(client, admin, "ANPR")
    await make_user("gone", is_active=False)
    now = datetime.now(timezone.utc)
    for n in range(2):
        await Session.create(
            user=admin_user, token_hash=f"h{n}", auth_time=now, expires_at=now + timedelta(days=1)
        )

    body = (await client.get("/v1/admin/stats", headers=admin)).json()
    assert body["disabled_users"] == 1
    assert body["application_keys"] == ["ANPR", "AUTH"]
    assert body["active_sessions"] == 2
    assert body["session_users"] == 1


async def test_active_key_has_a_rotation_date(client, admin, settings):
    keys = (await client.get("/v1/admin/keys", headers=admin)).json()
    active = next(key for key in keys if key["status"] == "active")
    nxt = next(key for key in keys if key["status"] == "next")
    row = await SigningKey.get(kid=active["kid"])
    expected = row.activated_at + timedelta(days=settings.KEY_ROTATION_DAYS)
    assert datetime.fromisoformat(active["rotates_at"]) == expected
    assert nxt["rotates_at"] is None


async def test_audit_shows_usernames(client, admin, admin_user):
    await make_app(client, admin, "ANPR")
    items = (await client.get("/v1/admin/audit", headers=admin)).json()["items"]
    by_admin = next(item for item in items if item["action"] == "application.create" and item["app"] == "ANPR")
    assert by_admin["actor"] == str(admin_user.public_id)
    assert by_admin["actor_name"] == admin_user.username
    cli = next(item for item in items if item["actor"] == "system:cli")
    assert cli["actor_name"] == "system:cli"
