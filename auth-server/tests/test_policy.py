"""The API policy layer: the resolver, the guard, and the FastAPI behaviour it relies on."""

import httpx
import pytest
from fastapi import APIRouter, Depends, FastAPI

from utilities.exceptions import register_error_handlers
from utilities.masks import bits_to_mask, encode_mask
from main import create_app
from app.security import policy as api_policy
from app.security.deps import current_claims
from app.tokens.schemas import Claims
from app.security.enforcement import (
    AUTH,
    FREE,
    CompiledPolicy,
    Rule,
    SelfGuarded,
    apply_security_policy,
    policy_guard,
)
from tests.conftest import make_app

ADMIN = Rule(roles=("Admin",))


def compile_policy(policy, default=AUTH):
    return CompiledPolicy.build(policy, default, "AUTH")


def test_exact_beats_star_method_beats_prefix():
    policy = compile_policy({"GET /a/b": FREE, "* /a/b": ADMIN, "* /a/*": AUTH})
    assert policy.resolve("GET", "/a/b")[0] == FREE
    assert policy.resolve("POST", "/a/b")[0] == ADMIN
    assert policy.resolve("GET", "/a/c")[0] == AUTH


def test_longest_prefix_wins_and_default_applies():
    policy = compile_policy({"* /a/*": FREE, "* /a/b/*": ADMIN})
    assert policy.resolve("GET", "/a/b/c")[0] == ADMIN
    assert policy.resolve("GET", "/a/x")[0] == FREE
    assert policy.resolve("GET", "/other") == (AUTH, "default")


def test_method_prefix_beats_star_prefix_at_same_length():
    policy = compile_policy({"* /a/*": FREE, "GET /a/*": ADMIN})
    assert policy.resolve("GET", "/a/x")[0] == ADMIN
    assert policy.resolve("POST", "/a/x")[0] == FREE


def test_trailing_slash_is_normalised():
    assert compile_policy({"POST /login": FREE}).resolve("POST", "/login/")[0] == FREE
    assert compile_policy({"POST /login/": FREE}).resolve("POST", "/login")[0] == FREE


def test_duplicate_keys_are_refused():
    with pytest.raises(ValueError, match="Duplicate"):
        compile_policy({"POST /login": FREE, "POST /login/": AUTH})


def test_bad_key_is_refused():
    with pytest.raises(ValueError):
        compile_policy({"GET/a": FREE})


def small_app(policy, default=ADMIN, required_free=frozenset()):
    app = FastAPI(dependencies=[Depends(policy_guard)])
    register_error_handlers(app)
    router = APIRouter(prefix="/r")

    @router.get("/open")
    async def open_route():
        return {"ok": True}

    @router.get("/token")
    async def token_route(claims: Claims = Depends(current_claims)):
        return {"sub": claims.sub}

    @router.get("/admin")
    async def admin_route():
        return {"ok": True}

    @router.get("/unlisted")
    async def unlisted_route():
        return {"ok": True}

    @router.get("/self")
    async def self_route():
        return {"ok": True}

    app.include_router(router)
    apply_security_policy(
        app,
        policy=policy,
        default=default,
        default_app_key="AUTH",
        required_free=set(required_free),
    )
    return app


POLICY = {
    "GET /r/open": FREE,
    "GET /r/token": AUTH,
    "GET /r/admin": ADMIN,
    "GET /r/self": SelfGuarded("own guard"),
}


def http(app):
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    return httpx.AsyncClient(transport=transport, base_url="http://test")


async def test_included_router_routes_are_really_guarded():
    """Canary for FastAPI upgrades. The old post-startup injection reported
    success here on FastAPI 0.162 while these routes stayed open."""
    async with http(small_app(POLICY)) as client:
        assert (await client.get("/r/open")).status_code == 200
        assert (await client.get("/r/self")).status_code == 200
        assert (await client.get("/r/token")).status_code == 401
        assert (await client.get("/r/admin")).status_code == 401
        assert (await client.get("/r/unlisted")).status_code == 401


async def test_every_real_admin_route_needs_a_token(app, client):
    schema = app.openapi()
    app.openapi_schema = None
    checked = 0
    for path, operations in schema["paths"].items():
        if not path.startswith("/v1/admin"):
            continue
        url = (
            path.replace("{key}", "ANPR")
            .replace("{public_id}", "00000000-0000-0000-0000-000000000000")
            .replace("{role_id}", "1")
            .replace("{permission_id}", "1")
        )
        for method in operations:
            response = await client.request(method.upper(), url, json={})
            assert response.status_code == 401, f"{method} {path}"
            checked += 1
    assert checked > 30


async def test_invalid_token_is_refused(client):
    response = await client.get(
        "/v1/admin/applications", headers={"Authorization": "Bearer forged"}
    )
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"


async def test_route_with_prefix_on_include_is_denied_not_misjudged(tokens):
    """scope["route"].path omits an include prefix, so a wrong rule could match.
    Such a route must be refused until its router carries the full prefix."""
    app = FastAPI(dependencies=[Depends(policy_guard)])
    register_error_handlers(app)
    router = APIRouter(prefix="/open")

    @router.get("/thing")
    async def thing():
        return {"ok": True}

    app.include_router(router, prefix="/v1/admin")
    apply_security_policy(
        app,
        policy={"GET /v1/admin/open/thing": FREE},
        default=ADMIN,
        default_app_key="AUTH",
        required_free=set(),
    )
    async with http(app) as client:
        response = await client.get("/v1/admin/open/thing")
    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "policy_unresolved"


def test_app_without_the_guard_refuses_to_start():
    app = FastAPI()

    @app.get("/x")
    async def x():
        return {}

    with pytest.raises(RuntimeError, match="not installed"):
        apply_security_policy(
            app, policy={"GET /x": FREE}, default=ADMIN, default_app_key="AUTH", required_free=set()
        )


def test_dead_policy_key_stops_startup():
    with pytest.raises(RuntimeError, match="match no route"):
        small_app({**POLICY, "GET /r/typo": FREE})


def test_dead_prefix_key_stops_startup():
    with pytest.raises(RuntimeError, match="match no route"):
        small_app({**POLICY, "* /nothing/*": ADMIN})


def test_required_free_endpoint_cannot_be_guarded():
    with pytest.raises(RuntimeError, match="must resolve to FREE"):
        small_app(POLICY, required_free={"GET /r/admin"})


def test_required_free_endpoint_must_exist():
    with pytest.raises(RuntimeError, match="must resolve to FREE"):
        small_app(POLICY, required_free={"GET /r/renamed"})


def test_real_policy_covers_every_route_explicitly():
    rows = apply_security_policy(create_app())
    assert [row for row in rows if row[3] == "default"] == []


def test_default_rule_is_closed():
    assert api_policy.DEFAULT_RULE == api_policy.ADMIN


async def test_admin_of_another_app_is_refused(client, tokens):
    """Every app has an "Admin" role, so the role name alone proves nothing."""
    response = await client.get("/v1/admin/applications", headers=tokens(aud="ANPR"))
    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "wrong_application"


async def test_ordinary_auth_user_is_refused(client, tokens):
    response = await client.get("/v1/admin/applications", headers=tokens(roles=("Viewer",)))
    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "insufficient_role"


async def test_admin_token_passes(client, admin):
    assert (await client.get("/v1/admin/applications", headers=admin)).status_code == 200


def perm_app(rule):
    return small_app({**POLICY, "GET /r/admin": rule})


async def seed_permission(client, admin, code="report.export"):
    response = await client.post(
        "/v1/admin/applications/AUTH/permissions", headers=admin, json={"code": code}
    )
    assert response.status_code == 201
    return response.json()["bit"]


async def test_permission_rule_uses_the_token_mask(client, admin, tokens):
    bit = await seed_permission(client, admin)
    app = perm_app(Rule(perms=("report.export",)))

    async with http(app) as guarded:
        allowed = tokens(roles=(), pm=encode_mask(bits_to_mask({bit})))
        assert (await guarded.get("/r/admin", headers=allowed)).status_code == 200

        other_bit = tokens(roles=(), pm=encode_mask(bits_to_mask({bit + 1})))
        assert (await guarded.get("/r/admin", headers=other_bit)).status_code == 403

        wildcard = tokens(roles=(), pm=encode_mask(bits_to_mask({0})))
        assert (await guarded.get("/r/admin", headers=wildcard)).status_code == 200


async def test_malformed_mask_is_refused_not_treated_as_empty(client, admin, tokens):
    await seed_permission(client, admin)
    async with http(perm_app(Rule(perms=("report.export",)))) as guarded:
        response = await guarded.get("/r/admin", headers=tokens(roles=(), pm="EgI="))
    assert response.status_code == 401


async def test_all_of_rule_fails_when_a_code_does_not_exist(client, admin, tokens):
    bit = await seed_permission(client, admin)
    rule = Rule(perms=("report.export", "does.not.exist"), any_perm=False)
    async with http(perm_app(rule)) as guarded:
        token = tokens(roles=(), pm=encode_mask(bits_to_mask({0, bit})))
        assert (await guarded.get("/r/admin", headers=token)).status_code == 403


async def test_retired_permission_no_longer_passes(client, admin, tokens):
    bit = await seed_permission(client, admin)
    permissions = await client.get("/v1/admin/applications/AUTH/permissions", headers=admin)
    permission_id = next(p["id"] for p in permissions.json() if p["bit"] == bit)
    await client.delete(f"/v1/admin/applications/AUTH/permissions/{permission_id}", headers=admin)

    async with http(perm_app(Rule(perms=("report.export",)))) as guarded:
        token = tokens(roles=(), pm=encode_mask(bits_to_mask({bit})))
        assert (await guarded.get("/r/admin", headers=token)).status_code == 403


async def test_make_app_helper_gives_a_working_application(client, admin):
    app = await make_app(client, admin)
    assert app.key == "ANPR"
