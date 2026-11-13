"""S3, S4 and S5 exit checks."""

import asyncio
import base64
import json
import time
from datetime import datetime, timedelta, timezone

import pytest
from joserfc import jwt as jose_jwt
from joserfc.jwk import ECKey, OctKey

from app.audit.models import AuditLog
from utilities.exceptions import AppError
from utilities.masks import bits_to_mask, decode_mask, has_bit
from app.identity.models import Session
from app.keys import services as keys
from app.tokens import services as jwt
from app.keys.services import ALGORITHM
from app.keys.models import SigningKey
from app.oauth.models import AuthorizationCode, RefreshToken
from app.tokens.services import verify_access_token
from tests.conftest import make_app
from tests.helpers import (
    REDIRECT_URI,
    authorize,
    bearer,
    create_client,
    create_service,
    full_login,
    get_code,
    grant,
    location_query,
    make_user,
    password_login,
    redeem,
    refresh,
    service_token,
)


def payload_of(token: str) -> dict:
    body = token.split(".")[1]
    return json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))


def header_of(token: str) -> dict:
    head = token.split(".")[0]
    return json.loads(base64.urlsafe_b64decode(head + "=" * (-len(head) % 4)))


@pytest.fixture
async def anpr(client, admin):
    """An app, a browser client, and a user with access to it."""
    app = await make_app(client, admin)
    await create_client(client, admin)
    user = await make_user()
    await grant(user, "ANPR")
    return app, user


# Keys and JWT


async def test_jwks_publishes_only_public_material(client):
    published = (await client.get("/.well-known/jwks.json")).json()
    assert len(published["keys"]) == 2
    for key in published["keys"]:
        assert key["kty"] == "EC" and key["alg"] == ALGORITHM
        assert "d" not in key


async def test_private_keys_are_encrypted_at_rest():
    row = await SigningKey.filter(status="active").first()
    assert '"d"' not in row.encrypted_private_key
    assert '"d"' in keys.provider.open(row.kid, row.encrypted_private_key)


async def test_next_key_is_published_before_it_signs(client):
    next_key = await SigningKey.get(status="next")
    kids = {key["kid"] for key in (await client.get("/.well-known/jwks.json")).json()["keys"]}
    assert next_key.kid in kids


async def test_rotation_keeps_old_tokens_valid_until_they_expire(client):
    old = await jwt.sign({"aud": "X"}, jwt.TYP_ACCESS, 60)
    old_kid = header_of(old)["kid"]
    promised = await SigningKey.get(status="next")

    promoted = await keys.rotate_keys()
    assert promoted.kid == promised.kid

    new = await jwt.sign({"aud": "X"}, jwt.TYP_ACCESS, 60)
    assert header_of(new)["kid"] == promoted.kid
    assert (await jwt.decode(old, jwt.TYP_ACCESS))["aud"] == "X"

    retired = await SigningKey.get(kid=old_kid)
    assert retired.status == "retired"
    assert old_kid in {k["kid"] for k in (await client.get("/.well-known/jwks.json")).json()["keys"]}


async def test_expired_key_leaves_jwks_and_stops_verifying(client):
    old = await jwt.sign({"aud": "X"}, jwt.TYP_ACCESS, 60)
    await keys.rotate_keys()
    await SigningKey.filter(status="retired").update(
        not_after=datetime.now(timezone.utc) - timedelta(seconds=1)
    )
    assert await keys.expire_retired_keys() == 1
    keys.clear_key_cache()
    with pytest.raises(AppError):
        await jwt.decode(old, jwt.TYP_ACCESS)


async def test_revoked_key_fails_immediately():
    token = await jwt.sign({"aud": "X"}, jwt.TYP_ACCESS, 60)
    await keys.revoke_key(header_of(token)["kid"])
    with pytest.raises(AppError):
        await jwt.decode(token, jwt.TYP_ACCESS)
    assert await SigningKey.filter(status="active").count() == 1


async def test_alg_none_is_rejected():
    claims = {"iss": "http://localhost:8000", "exp": int(time.time()) + 60, "aud": "X"}
    head = base64.urlsafe_b64encode(
        json.dumps({"alg": "none", "typ": "at+jwt", "kid": (await SigningKey.first()).kid}).encode()
    ).rstrip(b"=").decode()
    body = base64.urlsafe_b64encode(json.dumps(claims).encode()).rstrip(b"=").decode()
    with pytest.raises(AppError):
        await jwt.decode(f"{head}.{body}.", jwt.TYP_ACCESS)


async def test_hmac_token_signed_with_the_public_key_is_rejected():
    """The classic algorithm-confusion attack: the public key is public."""
    row = await SigningKey.get(status="active")
    fake = OctKey.import_key(json.dumps(row.public_jwk).encode())
    forged = jose_jwt.encode(
        {"alg": "HS256", "typ": "at+jwt", "kid": row.kid},
        {"iss": "http://localhost:8000", "exp": int(time.time()) + 60},
        fake,
        algorithms=["HS256"],
    )
    with pytest.raises(AppError):
        await jwt.decode(forged, jwt.TYP_ACCESS)


async def test_token_signed_by_an_unknown_key_is_rejected():
    stranger = ECKey.generate_key("P-256", parameters={"kid": "attacker"}, private=True)
    forged = jose_jwt.encode(
        {"alg": ALGORITHM, "typ": "at+jwt", "kid": "attacker"},
        {"iss": "http://localhost:8000", "exp": int(time.time()) + 60},
        stranger,
        algorithms=[ALGORITHM],
    )
    with pytest.raises(AppError):
        await jwt.decode(forged, jwt.TYP_ACCESS)


async def test_expired_and_wrong_issuer_and_wrong_type_are_rejected():
    expired = await jwt.sign({}, jwt.TYP_ACCESS, -1)
    wrong_issuer = await jwt.sign({"iss": "https://evil.example"}, jwt.TYP_ACCESS, 60)
    id_token = await jwt.sign({}, jwt.TYP_ID, 60)
    for token in (expired, wrong_issuer):
        with pytest.raises(AppError):
            await jwt.decode(token, jwt.TYP_ACCESS)
    with pytest.raises(AppError):
        await jwt.decode(id_token, jwt.TYP_ACCESS)


# Authorization code


async def test_discovery_matches_what_the_server_does(client):
    config = (await client.get("/.well-known/openid-configuration")).json()
    assert config["issuer"] == "http://localhost:8000"
    assert config["id_token_signing_alg_values_supported"] == ["ES256"]
    assert config["code_challenge_methods_supported"] == ["S256"]


async def test_full_flow_issues_audience_bound_tokens(client, anpr):
    app, user = anpr
    tokens = await full_login(client)
    claims = payload_of(tokens["access_token"])
    assert header_of(tokens["access_token"])["typ"] == "at+jwt"
    assert claims["aud"] == "ANPR"
    assert claims["sub"] == str(user.public_id)
    assert claims["roles"] == ["Admin"]
    assert has_bit(decode_mask(claims["pm"]), 0)
    assert claims["pv"] == app.perm_map_version
    verified = await verify_access_token(tokens["access_token"])
    assert verified.aud == "ANPR"


async def test_id_token_has_the_oidc_claims(client, anpr):
    _, user = anpr
    await password_login(client)
    code, verifier = await get_code(client, nonce="nonce-1")
    tokens = (await redeem(client, code, verifier)).json()
    claims = payload_of(tokens["id_token"])
    assert claims["aud"] == "anpr-web"
    assert claims["nonce"] == "nonce-1"
    assert claims["preferred_username"] == user.username
    assert claims["amr"] == ["pwd"]
    assert claims["at_hash"] == jwt.at_hash(tokens["access_token"])


async def test_refresh_token_is_stored_hashed(client, anpr):
    tokens = await full_login(client)
    row = await RefreshToken.first()
    assert tokens["refresh_token"] not in row.token_hash


async def test_no_session_redirects_to_the_login_page(client, anpr):
    response, _ = await authorize(client)
    assert response.status_code == 302
    assert response.headers["location"].startswith("/login?return_to=%2Foauth%2Fauthorize")


async def test_prompt_none_without_a_session_returns_an_error(client, anpr):
    response, _ = await authorize(client, prompt="none")
    query = location_query(response)
    assert query["error"] == "login_required"
    assert query["state"] == "state-1"
    assert query["iss"] == "http://localhost:8000"


async def test_prompt_login_forces_a_new_login(client, anpr):
    await password_login(client)
    response, _ = await authorize(client, prompt="login")
    assert response.headers["location"].startswith("/login")


async def test_max_age_forces_a_new_login_for_an_old_session(client, anpr):
    await password_login(client)
    await Session.all().update(auth_time=datetime.now(timezone.utc) - timedelta(hours=1))
    response, _ = await authorize(client, max_age="60")
    assert response.headers["location"].startswith("/login")


async def test_unknown_redirect_uri_is_never_followed(client, anpr):
    """Redirecting here would hand the code to an attacker."""
    await password_login(client)
    response, _ = await authorize(client, redirect_uri="https://evil.example/callback")
    assert response.status_code == 400
    assert "location" not in response.headers


async def test_unknown_client_is_not_redirected(client, anpr):
    response, _ = await authorize(client, client_id="nobody")
    assert response.status_code == 400


async def test_pkce_is_mandatory(client, anpr):
    await password_login(client)
    response = await client.get(
        "/oauth/authorize",
        params={
            "response_type": "code",
            "client_id": "anpr-web",
            "redirect_uri": REDIRECT_URI,
            "scope": "openid",
        },
    )
    assert location_query(response)["error"] == "invalid_request"


async def test_plain_pkce_is_refused(client, anpr):
    await password_login(client)
    response, _ = await authorize(client, code_challenge_method="plain")
    assert location_query(response)["error"] == "invalid_request"


async def test_user_without_a_role_is_denied(client, admin):
    await make_app(client, admin)
    await create_client(client, admin)
    await make_user()
    await password_login(client)
    response, _ = await authorize(client)
    assert location_query(response)["error"] == "access_denied"


async def test_scope_outside_the_client_is_refused(client, anpr):
    await password_login(client)
    response, _ = await authorize(client, scope="openid events.read")
    assert location_query(response)["error"] == "invalid_scope"


async def test_wrong_pkce_verifier_is_refused(client, anpr):
    await password_login(client)
    code, _ = await get_code(client)
    response = await redeem(client, code, "w" * 60)
    assert response.status_code == 400
    assert response.json()["error"] == "invalid_grant"


async def test_code_cannot_be_used_twice_and_replay_cancels_its_tokens(client, anpr):
    await password_login(client)
    code, verifier = await get_code(client)
    first = (await redeem(client, code, verifier)).json()

    replay = await redeem(client, code, verifier)
    assert replay.status_code == 400

    stolen = await refresh(client, first["refresh_token"])
    assert stolen.status_code == 400


async def test_simultaneous_code_redemption_has_one_winner(client, anpr):
    await password_login(client)
    code, verifier = await get_code(client)
    results = await asyncio.gather(*(redeem(client, code, verifier) for _ in range(5)))
    assert sorted(r.status_code for r in results) == [200, 400, 400, 400, 400]


async def test_expired_code_is_refused(client, anpr):
    await password_login(client)
    code, verifier = await get_code(client)
    await AuthorizationCode.all().update(expires_at=datetime.now(timezone.utc) - timedelta(seconds=1))
    assert (await redeem(client, code, verifier)).status_code == 400


async def test_code_is_bound_to_its_client(client, admin, anpr):
    await create_client(client, admin, client_id="other-web")
    await password_login(client)
    code, verifier = await get_code(client)
    assert (await redeem(client, code, verifier, client_id="other-web")).status_code == 400


async def test_redirect_uri_must_match_at_redemption(client, anpr):
    await password_login(client)
    code, verifier = await get_code(client)
    response = await redeem(client, code, verifier, redirect_uri="https://app.example.com/other")
    assert response.status_code == 400


async def test_token_responses_are_not_cached(client, anpr):
    await password_login(client)
    code, verifier = await get_code(client)
    response = await redeem(client, code, verifier)
    assert response.headers["cache-control"] == "no-store"


# Refresh


async def test_refresh_rotates_and_reflects_current_access(client, admin, anpr):
    tokens = await full_login(client)
    response = await refresh(client, tokens["refresh_token"])
    assert response.status_code == 200
    renewed = response.json()
    assert renewed["refresh_token"] != tokens["refresh_token"]
    assert (await verify_access_token(renewed["access_token"])).aud == "ANPR"


async def test_two_tabs_refreshing_at_once_keep_the_session(client, anpr):
    """Plan exit check: neither request may end the session."""
    tokens = await full_login(client)
    results = await asyncio.gather(
        refresh(client, tokens["refresh_token"]), refresh(client, tokens["refresh_token"])
    )
    assert [r.status_code for r in results] == [200, 200]
    session = await Session.get()
    assert session.revoked_at is None
    assert all(r.json()["access_token"] for r in results)

    # Exactly one branch continues, so reuse detection still sees a thief.
    fresh = [r.json()["refresh_token"] for r in results if "refresh_token" in r.json()]
    assert len(fresh) == 1
    assert (await refresh(client, fresh[0])).status_code == 200


async def test_replay_inside_the_grace_window_gets_no_refresh_token(client, anpr):
    tokens = await full_login(client)
    assert (await refresh(client, tokens["refresh_token"])).status_code == 200
    replay = await refresh(client, tokens["refresh_token"])
    assert replay.status_code == 200
    assert "refresh_token" not in replay.json()


async def test_replay_after_the_grace_window_ends_the_session(client, anpr):
    tokens = await full_login(client)
    renewed = (await refresh(client, tokens["refresh_token"])).json()
    await RefreshToken.filter(used_at__isnull=False).update(
        used_at=datetime.now(timezone.utc) - timedelta(minutes=5)
    )

    replay = await refresh(client, tokens["refresh_token"])
    assert replay.status_code == 400

    assert (await Session.get()).revoked_at is not None
    assert (await refresh(client, renewed["refresh_token"])).status_code == 400
    with pytest.raises(AppError):
        await verify_access_token(renewed["access_token"])
    assert await AuditLog.filter(action="token.reuse_detected").exists()


async def test_refresh_is_bound_to_its_client(client, admin, anpr):
    await create_client(client, admin, client_id="other-web")
    tokens = await full_login(client)
    assert (await refresh(client, tokens["refresh_token"], client_id="other-web")).status_code == 400


async def test_refresh_cannot_outlive_its_session(client, anpr):
    tokens = await full_login(client)
    await Session.all().update(expires_at=datetime.now(timezone.utc) - timedelta(seconds=1))
    assert (await refresh(client, tokens["refresh_token"])).status_code == 400


async def test_refresh_stops_when_access_is_removed(client, admin, anpr):
    _, user = anpr
    tokens = await full_login(client)
    await client.put(
        f"/v1/admin/users/{user.public_id}/roles",
        headers=admin,
        json={"app_key": "ANPR", "role_ids": []},
    )
    assert (await refresh(client, tokens["refresh_token"])).status_code == 400


async def test_refresh_cannot_widen_scope(client, anpr):
    tokens = await full_login(client)
    assert (await refresh(client, tokens["refresh_token"], scope="openid email")).status_code == 400


# Revocation scope


async def test_access_change_makes_the_old_token_stale_only_in_that_app(client, admin, anpr):
    _, user = anpr
    await make_app(client, admin, "HID")
    await create_client(client, admin, client_id="hid-web", app_key="HID")
    await grant(user, "HID")

    anpr_tokens = await full_login(client)
    code, verifier = await get_code(client, "hid-web")
    hid_tokens = (await redeem(client, code, verifier, "hid-web")).json()

    role_change = await client.put(
        f"/v1/admin/users/{user.public_id}/roles",
        headers=admin,
        json={"app_key": "ANPR", "role_ids": []},
    )
    assert role_change.status_code == 204

    with pytest.raises(AppError):
        await verify_access_token(anpr_tokens["access_token"])
    assert (await verify_access_token(hid_tokens["access_token"])).aud == "HID"


async def test_logout_ends_only_that_login(client, anpr):
    first = await full_login(client)
    client.cookies.clear()
    second = await full_login(client)

    response = await client.post("/oauth/logout", headers=bearer(first["access_token"]))
    assert response.status_code == 204

    with pytest.raises(AppError):
        await verify_access_token(first["access_token"])
    assert (await refresh(client, first["refresh_token"])).status_code == 400
    assert (await verify_access_token(second["access_token"])).aud == "ANPR"


async def test_logout_by_cookie_clears_it(client, anpr):
    tokens = await full_login(client)
    response = await client.post("/oauth/logout")
    assert response.status_code == 204
    assert 'auth_sso=""' in response.headers["set-cookie"]
    with pytest.raises(AppError):
        await verify_access_token(tokens["access_token"])


async def test_disabling_a_user_ends_everything(client, admin, anpr):
    _, user = anpr
    tokens = await full_login(client)
    await client.patch(
        f"/v1/admin/users/{user.public_id}", headers=admin, json={"is_active": False}
    )
    with pytest.raises(AppError):
        await verify_access_token(tokens["access_token"])
    assert (await refresh(client, tokens["refresh_token"])).status_code == 400


async def test_revoke_endpoint_cancels_the_family(client, anpr):
    tokens = await full_login(client)
    response = await client.post(
        "/oauth/revoke", data={"client_id": "anpr-web", "token": tokens["refresh_token"]}
    )
    assert response.status_code == 200
    assert (await refresh(client, tokens["refresh_token"])).status_code == 400


async def test_revoking_an_unknown_token_reveals_nothing(client, anpr):
    response = await client.post("/oauth/revoke", data={"client_id": "anpr-web", "token": "nope"})
    assert response.status_code == 200


async def test_userinfo_returns_the_profile(client, anpr):
    _, user = anpr
    tokens = await full_login(client)
    response = await client.get("/oauth/userinfo", headers=bearer(tokens["access_token"]))
    assert response.status_code == 200
    assert response.json()["preferred_username"] == user.username


# Client credentials


async def test_service_token_is_scoped_and_bound(client, admin):
    await make_app(client, admin)
    secret = await create_service(client, admin)
    token = await service_token(client, "anpr-api", secret, scope="events.read")
    claims = payload_of(token)
    assert claims["token_use"] == "service"
    assert claims["app"] == "ANPR" and claims["aud"] == "AUTH"
    assert claims["scope"] == "events.read"


async def test_wrong_secret_is_refused(client, admin):
    await make_app(client, admin)
    await create_service(client, admin)
    response = await client.post(
        "/oauth/token", data={"grant_type": "client_credentials"}, auth=("anpr-api", "wrong")
    )
    assert response.status_code == 401
    assert response.json()["error"] == "invalid_client"


async def test_client_guessing_is_limited(client, admin, settings):
    await make_app(client, admin)
    await create_service(client, admin)
    settings_limit = settings.TOKEN_LIMIT_PER_IP
    statuses = []
    for _ in range(settings_limit + 1):
        response = await client.post(
            "/oauth/token", data={"grant_type": "client_credentials"}, auth=("nobody", "wrong")
        )
        statuses.append(response.status_code)
    assert statuses[-1] == 429


async def test_public_client_cannot_use_client_credentials(client, anpr):
    response = await client.post(
        "/oauth/token", data={"grant_type": "client_credentials", "client_id": "anpr-web"}
    )
    assert response.status_code == 400


async def test_service_cannot_request_a_scope_it_lacks(client, admin):
    await make_app(client, admin)
    secret = await create_service(client, admin)
    response = await client.post(
        "/oauth/token",
        data={"grant_type": "client_credentials", "scope": "users.read"},
        auth=("anpr-api", secret),
    )
    assert response.json()["error"] == "invalid_scope"


async def test_service_token_for_another_audience_needs_permission(client, admin):
    await make_app(client, admin)
    await make_app(client, admin, "HID")
    secret = await create_service(client, admin)
    response = await client.post(
        "/oauth/token",
        data={"grant_type": "client_credentials", "audience": "HID"},
        auth=("anpr-api", secret),
    )
    assert response.json()["error"] == "invalid_target"


async def test_service_token_is_not_a_user_token(client, admin):
    await make_app(client, admin)
    secret = await create_service(client, admin)
    token = await service_token(client, "anpr-api", secret)
    with pytest.raises(AppError):
        await verify_access_token(token)
    assert (await client.get("/v1/me", headers=bearer(token))).status_code == 401


async def test_user_token_is_not_a_service_token(client, admin, anpr):
    tokens = await full_login(client)
    response = await client.get("/v1/apps/ANPR/permission-map", headers=bearer(tokens["access_token"]))
    assert response.status_code == 401


# Token exchange


@pytest.fixture
async def exchange_setup(client, admin, anpr):
    _, user = anpr
    target = await make_app(client, admin, "HID")
    await create_client(client, admin, client_id="hid-web", app_key="HID")
    secret = await create_service(client, admin, audiences=["HID"])
    await grant(user, "HID")
    return user, target, secret


async def exchange(client, secret, subject, **overrides):
    return await client.post(
        "/oauth/token",
        data={
            "grant_type": "urn:ietf:params:oauth:grant-type:token-exchange",
            "subject_token": subject,
            "subject_token_type": "urn:ietf:params:oauth:token-type:access_token",
            "audience": "HID",
            **overrides,
        },
        auth=("anpr-api", secret),
    )


async def add_permission(client, admin, code, app="HID") -> dict:
    response = await client.post(
        f"/v1/admin/applications/{app}/permissions", headers=admin, json={"code": code}
    )
    return response.json()


async def test_exchange_issues_a_short_token_for_the_target(client, exchange_setup):
    tokens = await full_login(client)
    response = await exchange(client, exchange_setup[2], tokens["access_token"])
    assert response.status_code == 200, response.text
    body = response.json()
    claims = payload_of(body["access_token"])
    assert claims["aud"] == "HID"
    assert claims["act"] == {"sub": "anpr-api", "app": "ANPR"}
    assert body["expires_in"] <= 300
    assert (await verify_access_token(body["access_token"])).aud == "HID"
    assert await AuditLog.filter(action="token.exchange").exists()


async def test_exchange_needs_an_authenticated_caller(client, exchange_setup):
    """The old /token-exchange took a key name as a plain string."""
    tokens = await full_login(client)
    response = await client.post(
        "/oauth/token",
        data={
            "grant_type": "urn:ietf:params:oauth:grant-type:token-exchange",
            "subject_token": tokens["access_token"],
            "subject_token_type": "urn:ietf:params:oauth:token-type:access_token",
            "audience": "HID",
            "client_id": "anpr-api",
        },
    )
    assert response.status_code == 401


async def test_public_client_cannot_exchange(client, exchange_setup):
    tokens = await full_login(client)
    response = await client.post(
        "/oauth/token",
        data={
            "grant_type": "urn:ietf:params:oauth:grant-type:token-exchange",
            "subject_token": tokens["access_token"],
            "subject_token_type": "urn:ietf:params:oauth:token-type:access_token",
            "audience": "HID",
            "client_id": "anpr-web",
        },
    )
    assert response.json()["error"] == "unauthorized_client"


async def test_exchange_only_reaches_allowed_audiences(client, admin, exchange_setup):
    await make_app(client, admin, "OTHER")
    tokens = await full_login(client)
    response = await exchange(client, exchange_setup[2], tokens["access_token"], audience="OTHER")
    assert response.json()["error"] == "invalid_target"


async def test_subject_token_must_belong_to_the_caller(client, admin, exchange_setup):
    """A service can't spend a token that was never sent to it."""
    tokens = await full_login(client)
    code, verifier = await get_code(client, "hid-web")
    hid = (await redeem(client, code, verifier, "hid-web")).json()
    response = await exchange(client, exchange_setup[2], hid["access_token"])
    assert response.json()["error"] == "invalid_grant"
    assert tokens


async def test_narrowing_removes_admin_from_the_token(client, admin, exchange_setup):
    """The old exchange narrowed perms but kept full roles, so Admin still passed."""
    await add_permission(client, admin, "door.read")
    tokens = await full_login(client)
    response = await exchange(client, exchange_setup[2], tokens["access_token"], scope="door.read")
    assert response.status_code == 200, response.text
    claims = payload_of(response.json()["access_token"])
    assert claims["roles"] == []
    assert decode_mask(claims["pm"]) == bits_to_mask({1})


async def test_scope_cannot_widen_access(client, admin, exchange_setup):
    user = exchange_setup[0]
    held = await add_permission(client, admin, "door.read")
    await add_permission(client, admin, "door.open")
    role = (
        await client.post(
            "/v1/admin/applications/HID/roles", headers=admin, json={"name": "Viewer"}
        )
    ).json()
    await client.put(
        f"/v1/admin/applications/HID/roles/{role['id']}/permissions",
        headers=admin,
        json={"permission_ids": [held["id"]]},
    )
    await client.put(
        f"/v1/admin/users/{user.public_id}/roles",
        headers=admin,
        json={"app_key": "HID", "role_ids": [role["id"]]},
    )
    tokens = await full_login(client)

    widened = await exchange(client, exchange_setup[2], tokens["access_token"], scope="door.open")
    assert widened.json()["error"] == "invalid_scope"

    fine = await exchange(client, exchange_setup[2], tokens["access_token"], scope="door.read")
    assert payload_of(fine.json()["access_token"])["roles"] == ["Viewer"]


async def test_unknown_scope_is_refused_not_ignored(client, exchange_setup):
    tokens = await full_login(client)
    response = await exchange(client, exchange_setup[2], tokens["access_token"], scope="no.such")
    assert response.json()["error"] == "invalid_scope"


async def test_exchange_needs_access_to_the_target(client, admin, exchange_setup):
    user = exchange_setup[0]
    await client.put(
        f"/v1/admin/users/{user.public_id}/roles",
        headers=admin,
        json={"app_key": "HID", "role_ids": []},
    )
    tokens = await full_login(client)
    response = await exchange(client, exchange_setup[2], tokens["access_token"])
    assert response.json()["error"] == "invalid_grant"


async def test_auth_app_cannot_be_an_audience(client, admin, exchange_setup):
    """A service holding an admin's token could otherwise mint itself admin access."""
    response = await client.patch(
        "/v1/admin/clients/anpr-api", headers=admin, json={"audiences": ["AUTH"]}
    )
    assert response.status_code == 422


async def test_exchange_into_auth_is_refused_even_if_listed(client, exchange_setup):
    from app.clients.models import OAuthClient

    await OAuthClient.filter(client_id="anpr-api").update(audiences=["HID", "AUTH"])
    tokens = await full_login(client)
    response = await exchange(client, exchange_setup[2], tokens["access_token"], audience="AUTH")
    assert response.json()["error"] == "invalid_target"


async def test_delegated_token_cannot_use_this_server(client, tokens):
    from app.tokens.schemas import Claims
    from app.tokens import services as verifier

    headers = tokens(aud="AUTH")
    token = headers["Authorization"].removeprefix("Bearer ")
    original = verifier.verify_access_token

    async def delegated(value):
        claims: Claims = await original(value)
        return claims.model_copy(update={"act": {"sub": "svc", "app": "ANPR"}})

    with pytest.MonkeyPatch.context() as patcher:
        patcher.setattr(verifier, "verify_access_token", delegated)
        response = await client.get("/v1/admin/stats", headers=bearer(token))
    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "delegated_token"


async def test_token_reads_version_before_access(client, anpr, monkeypatch):
    """A demotion landing mid-build must leave a token that fails, never old access
    under the new version. The access read here happens after the version read."""
    from app.applications.models import UserAppState
    from app.oauth import services as token_service

    app, user = anpr
    await UserAppState.create(user=user, app=app, version=1)
    original = token_service.permission_bits_for_user

    async def demoted_during_build(user_id, app_id):
        await UserAppState.filter(user_id=user_id, app_id=app_id).update(version=99)
        return await original(user_id, app_id)

    monkeypatch.setattr(token_service, "permission_bits_for_user", demoted_during_build)
    tokens = await full_login(client)
    with pytest.raises(AppError):
        await verify_access_token(tokens["access_token"])


async def test_disabling_a_browser_client_ends_its_user_tokens(client, admin, anpr):
    tokens = await full_login(client)
    await client.patch("/v1/admin/clients/anpr-web", headers=admin, json={"is_active": False})
    with pytest.raises(AppError):
        await verify_access_token(tokens["access_token"])


async def test_removing_an_audience_notifies_that_app(client, admin, exchange_setup):
    from app.events.models import OutboxEvent

    target = exchange_setup[1]
    await client.patch("/v1/admin/clients/anpr-api", headers=admin, json={"audiences": []})
    event = await OutboxEvent.filter(app_id=target.id, type="client.revoked").first()
    assert event.payload["client_id"] == "anpr-api"
    assert event.payload["version"] == 1


async def test_userinfo_returns_only_what_the_scope_allows(client, anpr):
    await password_login(client)
    code, verifier = await get_code(client, scope="openid")
    tokens = (await redeem(client, code, verifier)).json()
    body = (await client.get("/oauth/userinfo", headers=bearer(tokens["access_token"]))).json()
    assert set(body) == {"sub"}


async def test_redirect_uri_with_a_query_keeps_it_valid(client, admin, anpr):
    uri = "https://app.example.com/callback?tenant=7"
    await create_client(client, admin, client_id="query-web", redirect_uris=[uri])
    await password_login(client)
    response, _ = await authorize(client, "query-web", redirect_uri=uri)
    assert response.headers["location"].count("?") == 1
    assert location_query(response)["tenant"] == "7"
    assert "code" in location_query(response)


async def test_long_client_id_can_exchange(client, admin, exchange_setup):
    long_id = "s" + "e" * 100
    secret = await create_service(client, admin, client_id=long_id, audiences=["HID"])
    tokens = await full_login(client)
    from app.clients.models import OAuthClient

    await OAuthClient.filter(client_id=long_id).update(
        app_id=(await OAuthClient.get(client_id="anpr-api")).app_id
    )
    response = await client.post(
        "/oauth/token",
        data={
            "grant_type": "urn:ietf:params:oauth:grant-type:token-exchange",
            "subject_token": tokens["access_token"],
            "subject_token_type": "urn:ietf:params:oauth:token-type:access_token",
            "audience": "HID",
        },
        auth=(long_id, secret),
    )
    assert response.status_code == 200, response.text


async def test_exchanged_token_cannot_be_exchanged_again(client, admin, exchange_setup):
    await client.patch(
        "/v1/admin/clients/anpr-api", headers=admin, json={"audiences": ["HID", "ANPR"]}
    )
    secret = exchange_setup[2]
    tokens = await full_login(client)
    first = await exchange(client, secret, tokens["access_token"], audience="ANPR")
    second = await exchange(client, secret, first.json()["access_token"], audience="HID")
    assert second.json()["error"] == "invalid_grant"


async def test_exchange_refuses_a_revoked_subject(client, exchange_setup):
    tokens = await full_login(client)
    await client.post("/oauth/logout", headers=bearer(tokens["access_token"]))
    response = await exchange(client, exchange_setup[2], tokens["access_token"])
    assert response.json()["error"] == "invalid_grant"


# Service clients


async def test_public_client_needs_a_redirect_uri(client, admin):
    await make_app(client, admin)
    response = await client.post(
        "/v1/admin/clients",
        headers=admin,
        json={"client_id": "web-app", "name": "x", "app_key": "ANPR", "type": "public"},
    )
    assert response.status_code == 422


@pytest.mark.parametrize(
    "uri", ["http://app.example.com/cb", "https://app.example.com/cb#frag", "ftp://x/cb", "nothing"]
)
async def test_bad_redirect_uris_are_refused(client, admin, uri):
    await make_app(client, admin)
    response = await client.post(
        "/v1/admin/clients",
        headers=admin,
        json={
            "client_id": "web-app",
            "name": "x",
            "app_key": "ANPR",
            "type": "public",
            "redirect_uris": [uri],
        },
    )
    assert response.status_code == 422


async def test_secret_is_shown_once_and_stored_hashed(client, admin):
    from app.clients.models import OAuthClient

    await make_app(client, admin)
    secret = await create_service(client, admin)
    row = await OAuthClient.get(client_id="anpr-api")
    assert secret not in row.secret_hash
    listed = (await client.get("/v1/admin/clients", headers=admin)).text
    assert secret not in listed and "secret" not in listed


async def test_rotating_a_secret_ends_the_old_token(client, admin):
    await make_app(client, admin)
    secret = await create_service(client, admin)
    token = await service_token(client, "anpr-api", secret)
    rotated = await client.post("/v1/admin/clients/anpr-api/rotate-secret", headers=admin)
    assert rotated.status_code == 200

    url = "/v1/apps/ANPR/permission-map"
    assert (await client.get(url, headers=bearer(token))).status_code == 401
    old = await client.post(
        "/oauth/token", data={"grant_type": "client_credentials"}, auth=("anpr-api", secret)
    )
    assert old.status_code == 401
    assert await service_token(client, "anpr-api", rotated.json()["client_secret"])


async def test_disabling_a_client_ends_its_token(client, admin):
    await make_app(client, admin)
    secret = await create_service(client, admin)
    token = await service_token(client, "anpr-api", secret)
    await client.patch("/v1/admin/clients/anpr-api", headers=admin, json={"is_active": False})
    assert (await client.get("/v1/apps/ANPR/permission-map", headers=bearer(token))).status_code == 401


# Self-service with real tokens


async def test_token_for_another_app_cannot_use_this_server(client, anpr):
    tokens = await full_login(client)
    response = await client.get("/v1/me", headers=bearer(tokens["access_token"]))
    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "wrong_application"
