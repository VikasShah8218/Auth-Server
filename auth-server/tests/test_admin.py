"""S1 exit checks: access model rules, permission bits, versions and audit records."""

import asyncio

import pytest
from asyncpg.exceptions import RaiseError
from tortoise import connections
from tortoise.transactions import in_transaction

from app.applications import services as service
from app.audit.services import record_audit
from app.applications.models import Application, Permission, Role, UserAppState, UserRole
from app.audit.models import AuditLog
from app.applications.schemas import PermissionCreate
from cli import create_admin
from utilities.exceptions import AppError
from utilities.masks import MAX_BITS, bits_to_mask, encode_mask
from app.users.models import User
from app.users.utils import verify_password
from tests.conftest import ACTOR, ADMIN_PASSWORD, make_app


async def make_permission(client, admin, code, app="ANPR") -> dict:
    response = await client.post(
        f"/v1/admin/applications/{app}/permissions", headers=admin, json={"code": code}
    )
    assert response.status_code == 201, response.text
    return response.json()


async def make_role(client, admin, name="Operator", app="ANPR") -> dict:
    response = await client.post(
        f"/v1/admin/applications/{app}/roles", headers=admin, json={"name": name}
    )
    assert response.status_code == 201, response.text
    return response.json()


async def make_user(client, admin, username="alice") -> dict:
    response = await client.post(
        "/v1/admin/users",
        headers=admin,
        json={"username": username, "password": "a-long-enough-pass-1"},
    )
    assert response.status_code == 201, response.text
    return response.json()


async def set_role_perms(client, admin, role, permission_ids, app="ANPR"):
    return await client.put(
        f"/v1/admin/applications/{app}/roles/{role['id']}/permissions",
        headers=admin,
        json={"permission_ids": permission_ids},
    )


async def assign(client, admin, user, role_ids, app="ANPR"):
    return await client.put(
        f"/v1/admin/users/{user['public_id']}/roles",
        headers=admin,
        json={"app_key": app, "role_ids": role_ids},
    )


async def version_of(user: dict, app_key="ANPR") -> int:
    state = await UserAppState.get_or_none(user__public_id=user["public_id"], app__key=app_key)
    return state.version if state else 0


# Applications


async def test_new_application_starts_with_full_access_on_bit_zero(client, admin):
    app = await make_app(client, admin)
    permission = await Permission.get(app_id=app.id)
    assert (permission.code, permission.bit) == ("*", 0)
    assert await Role.filter(app_id=app.id, name="Admin").exists()


async def test_key_is_normalised_and_duplicates_conflict(client, admin):
    body = {"key": "anpr", "name": "ANPR"}
    assert (await client.post("/v1/admin/applications", headers=admin, json=body)).json()["key"] == "ANPR"
    again = await client.post("/v1/admin/applications", headers=admin, json=body)
    assert again.status_code == 409
    assert await Application.filter(key="ANPR").count() == 1


async def test_bad_application_key_is_refused(client, admin):
    response = await client.post(
        "/v1/admin/applications", headers=admin, json={"key": "bad key!", "name": "x"}
    )
    assert response.status_code == 422


async def test_auth_application_cannot_be_deactivated(client, admin):
    response = await client.patch(
        "/v1/admin/applications/AUTH", headers=admin, json={"is_active": False}
    )
    assert response.status_code == 409


async def test_list_is_paginated(client, admin):
    for key in ("AAA", "BBB", "CCC"):
        await make_app(client, admin, key)
    page = (await client.get("/v1/admin/applications?limit=2&offset=1", headers=admin)).json()
    assert [a["key"] for a in page["items"]] == ["AUTH", "BBB"]
    assert page["total"] == 4


# Permission bits


async def test_bits_are_assigned_in_order_and_raise_the_map_version(client, admin):
    app = await make_app(client, admin)
    assert (await make_permission(client, admin, "vehicle.read"))["bit"] == 1
    assert (await make_permission(client, admin, "camera.read"))["bit"] == 2
    await app.refresh_from_db()
    assert app.perm_map_version == 3


async def test_retired_bit_is_never_reused(client, admin):
    await make_app(client, admin)
    first = await make_permission(client, admin, "vehicle.read")
    second = await make_permission(client, admin, "camera.read")
    await client.delete(
        f"/v1/admin/applications/ANPR/permissions/{second['id']}", headers=admin
    )
    third = await make_permission(client, admin, "report.export")
    assert first["bit"] == 1
    assert third["bit"] == 3


async def test_recreating_a_retired_code_restores_its_own_bit(client, admin):
    await make_app(client, admin)
    original = await make_permission(client, admin, "vehicle.read")
    await make_permission(client, admin, "camera.read")
    await client.delete(
        f"/v1/admin/applications/ANPR/permissions/{original['id']}", headers=admin
    )
    revived = await make_permission(client, admin, "vehicle.read")
    assert revived["bit"] == original["bit"]
    assert revived["retired_at"] is None


async def test_concurrent_creates_get_different_bits(client, admin):
    await make_app(client, admin)
    results = await asyncio.gather(
        *(make_permission(client, admin, f"perm.p{i}") for i in range(12))
    )
    assert sorted(r["bit"] for r in results) == list(range(1, 13))


async def test_bit_limit_is_enforced(client, admin):
    app = await make_app(client, admin)
    await Permission.bulk_create(
        [Permission(app_id=app.id, code=f"p{bit}", bit=bit) for bit in range(1, MAX_BITS)]
    )
    response = await client.post(
        "/v1/admin/applications/ANPR/permissions", headers=admin, json={"code": "too.many"}
    )
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "permission_limit"


async def test_wildcard_cannot_be_retired(client, admin):
    app = await make_app(client, admin)
    wildcard = await Permission.get(app_id=app.id, bit=0)
    response = await client.delete(
        f"/v1/admin/applications/ANPR/permissions/{wildcard.id}", headers=admin
    )
    assert response.status_code == 409


async def test_permission_from_another_app_is_not_found(client, admin):
    await make_app(client, admin)
    await make_app(client, admin, "HID")
    other = await make_permission(client, admin, "door.open", app="HID")
    response = await client.delete(
        f"/v1/admin/applications/ANPR/permissions/{other['id']}", headers=admin
    )
    assert response.status_code == 404


async def test_retired_permission_is_hidden_unless_asked_for(client, admin):
    await make_app(client, admin)
    permission = await make_permission(client, admin, "vehicle.read")
    await client.delete(
        f"/v1/admin/applications/ANPR/permissions/{permission['id']}", headers=admin
    )
    active = (await client.get("/v1/admin/applications/ANPR/permissions", headers=admin)).json()
    everything = (
        await client.get(
            "/v1/admin/applications/ANPR/permissions?include_retired=true", headers=admin
        )
    ).json()
    assert [p["code"] for p in active] == ["*"]
    assert [p["code"] for p in everything] == ["*", "vehicle.read"]


# Roles


async def test_role_cannot_take_a_permission_from_another_app(client, admin):
    await make_app(client, admin)
    await make_app(client, admin, "HID")
    role = await make_role(client, admin)
    other = await make_permission(client, admin, "door.open", app="HID")
    response = await set_role_perms(client, admin, role, [other["id"]])
    assert response.status_code == 422


async def test_role_cannot_take_a_retired_permission(client, admin):
    await make_app(client, admin)
    role = await make_role(client, admin)
    permission = await make_permission(client, admin, "vehicle.read")
    await client.delete(
        f"/v1/admin/applications/ANPR/permissions/{permission['id']}", headers=admin
    )
    response = await set_role_perms(client, admin, role, [permission["id"]])
    assert response.status_code == 422


async def test_role_names_are_unique_per_application(client, admin):
    await make_app(client, admin)
    await make_app(client, admin, "HID")
    await make_role(client, admin)
    await make_role(client, admin, app="HID")
    duplicate = await client.post(
        "/v1/admin/applications/ANPR/roles", headers=admin, json={"name": "Operator"}
    )
    assert duplicate.status_code == 409


async def test_admin_role_is_protected(client, admin):
    app = await make_app(client, admin)
    role = await Role.get(app_id=app.id, name="Admin")
    url = f"/v1/admin/applications/ANPR/roles/{role.id}"
    assert (await client.delete(url, headers=admin)).status_code == 409
    assert (await client.patch(url, headers=admin, json={"name": "Boss"})).status_code == 409


async def test_auth_admin_role_must_keep_full_access(client, admin):
    role = await Role.get(app__key="AUTH", name="Admin")
    response = await set_role_perms(client, admin, {"id": role.id}, [], app="AUTH")
    assert response.status_code == 409


async def test_replacing_role_permissions_replaces_them(client, admin):
    await make_app(client, admin)
    role = await make_role(client, admin)
    one = await make_permission(client, admin, "vehicle.read")
    two = await make_permission(client, admin, "camera.read")
    await set_role_perms(client, admin, role, [one["id"]])
    await set_role_perms(client, admin, role, [two["id"]])
    detail = await client.get(f"/v1/admin/applications/ANPR/roles/{role['id']}", headers=admin)
    assert [p["code"] for p in detail.json()["permissions"]] == ["camera.read"]


# Users


async def test_password_is_hashed_and_never_returned(client, admin):
    created = await make_user(client, admin)
    assert "password" not in str(created).lower()
    user = await User.get(public_id=created["public_id"])
    assert user.password_hash.startswith("$argon2id$")
    assert verify_password("a-long-enough-pass-1", user.password_hash)
    assert not verify_password("wrong", user.password_hash)


@pytest.mark.parametrize("password", ["short", "dave-is-the-best-user"])
async def test_weak_password_is_refused(client, admin, password):
    response = await client.post(
        "/v1/admin/users", headers=admin, json={"username": "dave", "password": password}
    )
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "weak_password"


async def test_duplicate_username_and_email_conflict(client, admin):
    body = {"username": "alice", "email": "a@example.com", "password": "a-long-enough-pass-1"}
    assert (await client.post("/v1/admin/users", headers=admin, json=body)).status_code == 201
    same_name = await client.post("/v1/admin/users", headers=admin, json={**body, "email": "b@example.com"})
    same_email = await client.post("/v1/admin/users", headers=admin, json={**body, "username": "bob"})
    assert same_name.status_code == 409
    assert same_email.status_code == 409


async def test_search_finds_by_username_and_email(client, admin):
    await make_user(client, admin, "alice")
    await make_user(client, admin, "bob")
    found = (await client.get("/v1/admin/users?q=ali", headers=admin)).json()
    assert [u["username"] for u in found["items"]] == ["alice"]
    assert found["total"] == 1


async def test_user_detail_shows_access_per_application(client, admin):
    await make_app(client, admin)
    role = await make_role(client, admin)
    permission = await make_permission(client, admin, "vehicle.read")
    await set_role_perms(client, admin, role, [permission["id"]])
    user = await make_user(client, admin)
    await assign(client, admin, user, [role["id"]])

    detail = (await client.get(f"/v1/admin/users/{user['public_id']}", headers=admin)).json()
    assert detail["applications"][0]["app_key"] == "ANPR"
    assert detail["applications"][0]["permissions"] == ["vehicle.read"]
    assert detail["applications"][0]["roles"][0]["name"] == "Operator"


async def test_user_role_must_belong_to_the_application(client, admin):
    await make_app(client, admin)
    await make_app(client, admin, "HID")
    role = await make_role(client, admin, app="HID")
    user = await make_user(client, admin)
    response = await assign(client, admin, user, [role["id"]])
    assert response.status_code == 422


async def test_setting_roles_for_one_app_leaves_other_apps_alone(client, admin):
    await make_app(client, admin)
    await make_app(client, admin, "HID")
    anpr_role = await make_role(client, admin)
    hid_role = await make_role(client, admin, app="HID")
    user = await make_user(client, admin)
    await assign(client, admin, user, [hid_role["id"]], app="HID")
    await assign(client, admin, user, [anpr_role["id"]])
    await assign(client, admin, user, [])
    assert await UserRole.filter(user__public_id=user["public_id"], role_id=hid_role["id"]).exists()


async def test_members_lists_each_user_once_with_their_roles(client, admin):
    await make_app(client, admin)
    operator = await make_role(client, admin)
    viewer = await make_role(client, admin, name="Viewer")
    user = await make_user(client, admin)
    await assign(client, admin, user, [operator["id"], viewer["id"]])

    members = (await client.get("/v1/admin/applications/ANPR/members", headers=admin)).json()
    assert len(members) == 1
    assert members[0]["username"] == "alice"
    assert sorted(role["name"] for role in members[0]["roles"]) == ["Operator", "Viewer"]


# Token mask inputs and versions


async def test_user_bits_ignore_other_apps_and_retired_permissions(client, admin):
    app = await make_app(client, admin)
    await make_app(client, admin, "HID")
    role = await make_role(client, admin)
    keep = await make_permission(client, admin, "vehicle.read")
    drop = await make_permission(client, admin, "camera.read")
    await set_role_perms(client, admin, role, [keep["id"], drop["id"]])
    other_role = await make_role(client, admin, app="HID")
    other = await make_permission(client, admin, "door.open", app="HID")
    await set_role_perms(client, admin, other_role, [other["id"]], app="HID")

    created = await make_user(client, admin)
    await assign(client, admin, created, [role["id"]])
    await assign(client, admin, created, [other_role["id"]], app="HID")
    await client.delete(f"/v1/admin/applications/ANPR/permissions/{drop['id']}", headers=admin)

    user = await User.get(public_id=created["public_id"])
    bits = await service.permission_bits_for_user(user.id, app.id)
    assert bits == {keep["bit"]}
    assert encode_mask(bits_to_mask(bits)) == "Ag"


async def test_every_access_change_raises_only_that_apps_version(client, admin):
    await make_app(client, admin)
    await make_app(client, admin, "HID")
    role = await make_role(client, admin)
    hid_role = await make_role(client, admin, app="HID")
    permission = await make_permission(client, admin, "vehicle.read")
    user = await make_user(client, admin)

    await assign(client, admin, user, [hid_role["id"]], app="HID")
    hid_version = await version_of(user, "HID")

    await assign(client, admin, user, [role["id"]])
    assert await version_of(user) == 1

    await set_role_perms(client, admin, role, [permission["id"]])
    assert await version_of(user) == 2

    await client.delete(
        f"/v1/admin/applications/ANPR/permissions/{permission['id']}", headers=admin
    )
    assert await version_of(user) == 3

    await client.patch(
        f"/v1/admin/applications/ANPR/roles/{role['id']}", headers=admin, json={"name": "Viewer"}
    )
    assert await version_of(user) == 4

    await client.delete(f"/v1/admin/applications/ANPR/roles/{role['id']}", headers=admin)
    assert await version_of(user) == 5

    assert await version_of(user, "HID") == hid_version


async def test_disabling_a_user_raises_the_version_in_every_app(client, admin):
    await make_app(client, admin)
    await make_app(client, admin, "HID")
    user = await make_user(client, admin)
    await assign(client, admin, user, [(await make_role(client, admin))["id"]])
    await assign(client, admin, user, [(await make_role(client, admin, app="HID"))["id"]], app="HID")

    await client.patch(f"/v1/admin/users/{user['public_id']}", headers=admin, json={"is_active": False})
    assert await version_of(user) == 2
    assert await version_of(user, "HID") == 2


async def test_profile_edit_does_not_end_sessions(client, admin):
    await make_app(client, admin)
    user = await make_user(client, admin)
    await assign(client, admin, user, [(await make_role(client, admin))["id"]])
    await client.patch(f"/v1/admin/users/{user['public_id']}", headers=admin, json={"first_name": "Al"})
    assert await version_of(user) == 1


# Last administrator


async def test_last_admin_cannot_be_disabled(client, admin, admin_user):
    response = await client.patch(
        f"/v1/admin/users/{admin_user.public_id}", headers=admin, json={"is_active": False}
    )
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "last_admin"


async def test_last_admin_cannot_lose_the_role(client, admin, admin_user):
    response = await assign(client, admin, {"public_id": str(admin_user.public_id)}, [], app="AUTH")
    assert response.status_code == 409
    assert await UserRole.filter(user_id=admin_user.id).exists()


async def test_admin_can_step_down_once_another_exists(client, admin, admin_user):
    role = await Role.get(app__key="AUTH", name="Admin")
    other = await make_user(client, admin)
    await assign(client, admin, other, [role.id], app="AUTH")
    response = await assign(client, admin, {"public_id": str(admin_user.public_id)}, [], app="AUTH")
    assert response.status_code == 204


async def test_a_disabled_admin_does_not_count_as_remaining(client, admin, admin_user):
    role = await Role.get(app__key="AUTH", name="Admin")
    other = await make_user(client, admin)
    await assign(client, admin, other, [role.id], app="AUTH")
    await client.patch(f"/v1/admin/users/{other['public_id']}", headers=admin, json={"is_active": False})
    response = await client.patch(
        f"/v1/admin/users/{admin_user.public_id}", headers=admin, json={"is_active": False}
    )
    assert response.status_code == 409


async def test_two_admins_disabled_at_once_leaves_one(client, admin, admin_user):
    """Without the row lock, each would see the other as the one who remains."""
    role = await Role.get(app__key="AUTH", name="Admin")
    other = await make_user(client, admin)
    await assign(client, admin, other, [role.id], app="AUTH")

    responses = await asyncio.gather(
        client.patch(f"/v1/admin/users/{other['public_id']}", headers=admin, json={"is_active": False}),
        client.patch(f"/v1/admin/users/{admin_user.public_id}", headers=admin, json={"is_active": False}),
    )
    assert sorted(r.status_code for r in responses) == [200, 409]
    assert await UserRole.filter(role_id=role.id, user__is_active=True).count() == 1


# Audit


async def test_each_write_leaves_an_audit_record(client, admin, admin_user):
    await make_app(client, admin)
    role = await make_role(client, admin)
    permission = await make_permission(client, admin, "vehicle.read")
    await set_role_perms(client, admin, role, [permission["id"]])
    user = await make_user(client, admin)
    await assign(client, admin, user, [role["id"]])

    actions = await AuditLog.filter(actor=str(admin_user.public_id)).order_by("id").values_list("action", flat=True)
    assert actions == [
        "application.create",
        "role.create",
        "permission.create",
        "role.set_permissions",
        "user.create",
        "user.set_roles",
    ]


async def test_audit_never_stores_a_password(client, admin):
    await make_user(client, admin)
    records = await AuditLog.all()
    assert "a-long-enough-pass" not in str([(r.action, r.details) for r in records])


async def test_audit_list_filters(client, admin):
    await make_app(client, admin)
    await make_app(client, admin, "HID")
    page = (await client.get("/v1/admin/audit?app=hid", headers=admin)).json()
    assert page["total"] == 1
    assert page["items"][0]["action"] == "application.create"
    assert page["items"][0]["ip"]


async def test_failed_change_saves_neither_data_nor_audit(client, admin):
    await make_app(client, admin)
    before = await AuditLog.all().count()

    async def fail(*_args, **_kwargs):
        raise RuntimeError("audit write failed")

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(service, "record_audit", fail)
        response = await client.post(
            "/v1/admin/applications/ANPR/permissions", headers=admin, json={"code": "lost.write"}
        )

    assert response.status_code == 500
    assert not await Permission.filter(code="lost.write").exists()
    assert (await Application.get(key="ANPR")).perm_map_version == 1
    assert await AuditLog.all().count() == before


async def test_audit_rows_reject_update_and_delete(admin):
    await record_audit(ACTOR, "test.action")
    connection = connections.get("default")
    with pytest.raises(RaiseError, match="insert only"):
        await connection.execute_query("UPDATE audit_logs SET actor = 'someone-else'")
    with pytest.raises(RaiseError, match="insert only"):
        await connection.execute_query("DELETE FROM audit_logs")
    with pytest.raises(RaiseError, match="insert only"):
        await connection.execute_script("TRUNCATE audit_logs")
    assert await AuditLog.filter(action="test.action").exists()


async def test_rollback_covers_service_writes_and_raw_version_updates(client, admin):
    await make_app(client, admin)
    role = await make_role(client, admin)
    user = await make_user(client, admin)
    await assign(client, admin, user, [role["id"]])
    db_user = await User.get(public_id=user["public_id"])
    app = await Application.get(key="ANPR")

    with pytest.raises(RuntimeError):
        async with in_transaction():
            await service.bump_versions(app.id, [db_user.id])
            await service.create_permission("ANPR", PermissionCreate(code="in.rollback"), ACTOR)
            raise RuntimeError("abort")

    assert await version_of(user) == 1
    assert not await Permission.filter(code="in.rollback").exists()


# create-admin


async def test_create_admin_bootstraps_the_system():
    user = await create_admin("first.admin", "first@example.com", ADMIN_PASSWORD)
    assert user.is_superuser
    assert await Application.filter(key="AUTH").exists()
    assert await UserRole.filter(user_id=user.id, role__name="Admin", role__app__key="AUTH").exists()
    record = await AuditLog.get(action="admin.bootstrap")
    assert record.actor == "system:cli"


async def test_create_admin_works_only_once(admin_user):
    with pytest.raises(AppError) as caught:
        await create_admin("second.admin", None, ADMIN_PASSWORD)
    assert caught.value.code == "admin_exists"
    assert not await User.filter(username="second.admin").exists()


async def test_create_admin_refuses_a_weak_password():
    with pytest.raises(AppError) as caught:
        await create_admin("first.admin", None, "Admin@123")
    assert caught.value.code == "weak_password"
    assert not await Application.filter(key="AUTH").exists()
