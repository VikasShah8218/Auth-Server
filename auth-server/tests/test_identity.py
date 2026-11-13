"""S2 exit checks: each old-server bug is proven gone."""

import time

import httpx
import pyotp
import pytest
from redis.exceptions import ConnectionError as RedisConnectionError

from app.audit.models import AuditLog
from utilities import ratelimit
from utilities.crypto import decrypt, encrypt
from app.identity import mfa
from app.identity.mfa import TOTP_PERIOD
from app.identity.models import MfaFactor, Session
from tests.helpers import PASSWORD, make_user, password_login


def code_for(secret: str, offset: int = 0) -> str:
    step = int(time.time()) // TOTP_PERIOD + offset
    return pyotp.TOTP(secret, interval=TOTP_PERIOD).at(step * TOTP_PERIOD)


@pytest.fixture
def me(tokens):
    def headers(user):
        return tokens(user, roles=())

    return headers


async def enrol(client, headers) -> str:
    started = await client.post("/v1/me/mfa/totp", headers=headers, json={"password": PASSWORD})
    assert started.status_code == 201
    secret = started.json()["secret"]
    confirmed = await client.post(
        "/v1/me/mfa/totp/confirm", headers=headers, json={"code": code_for(secret)}
    )
    assert confirmed.status_code == 204, confirmed.text
    return secret


async def challenge_for(client) -> str:
    response = await password_login(client)
    assert response.json()["status"] == "mfa_required"
    return response.json()["challenge"]


async def test_login_sets_a_protected_session_cookie(client):
    await make_user()
    response = await password_login(client)
    assert response.status_code == 200
    assert response.json()["status"] == "authenticated"
    cookie = response.headers["set-cookie"]
    assert "HttpOnly" in cookie and "SameSite=lax" in cookie
    session = await Session.get()
    assert session.amr == ["pwd"]
    assert session.token_hash not in cookie


@pytest.mark.parametrize("username,password", [("alice", "wrong-password-12"), ("nobody", PASSWORD)])
async def test_bad_login_gives_the_same_answer_either_way(client, username, password):
    await make_user()
    response = await password_login(client, username, password)
    assert response.status_code == 401
    assert response.json()["detail"]["code"] == "invalid_credentials"


async def test_disabled_user_cannot_log_in_and_learns_nothing(client):
    await make_user(is_active=False)
    response = await password_login(client)
    assert response.status_code == 401
    assert response.json()["detail"]["code"] == "invalid_credentials"
    assert not await Session.exists()


async def test_account_lockout_stops_guessing_then_success_resets_it(client, settings):
    await make_user()
    for _ in range(settings.LOGIN_LIMIT_PER_ACCOUNT - 1):
        await password_login(client, password="wrong-password-12")
    assert (await password_login(client)).status_code == 200
    for _ in range(settings.LOGIN_LIMIT_PER_ACCOUNT):
        await password_login(client, password="wrong-password-12")
    blocked = await password_login(client)
    assert blocked.status_code == 429
    assert int(blocked.headers["retry-after"]) > 0


async def test_login_is_refused_when_redis_is_down(client, monkeypatch):
    """With no counter there's no way to stop guessing, so it must fail closed."""
    await make_user()

    def down():
        raise RedisConnectionError("down")

    monkeypatch.setattr(ratelimit, "get_redis", down)
    response = await password_login(client)
    assert response.status_code == 503
    assert not await Session.exists()


async def test_totp_secret_is_encrypted_at_rest(client, me):
    user = await make_user()
    secret = await enrol(client, me(user))
    factor = await MfaFactor.get(user_id=user.id)
    assert secret not in factor.encrypted_secret
    assert decrypt(factor.encrypted_secret, f"totp:{user.id}") == secret


def test_encrypted_value_is_bound_to_its_context():
    sealed = encrypt("secret", "totp:1")
    with pytest.raises(Exception):
        decrypt(sealed, "totp:2")


async def test_mfa_is_not_active_until_a_code_confirms_it(client, me):
    """The old server enabled MFA first, so a lost QR code meant a lockout."""
    user = await make_user()
    await client.post("/v1/me/mfa/totp", headers=me(user), json={"password": PASSWORD})
    response = await password_login(client)
    assert response.json()["status"] == "authenticated"


async def test_enrolment_rejects_a_wrong_code(client, me):
    user = await make_user()
    headers = me(user)
    await client.post("/v1/me/mfa/totp", headers=headers, json={"password": PASSWORD})
    response = await client.post("/v1/me/mfa/totp/confirm", headers=headers, json={"code": "000000"})
    assert response.status_code == 401
    assert await MfaFactor.filter(confirmed_at__isnull=False).count() == 0


async def test_mfa_login_flow(client, me):
    user = await make_user()
    secret = await enrol(client, me(user))
    challenge = await challenge_for(client)
    assert not await Session.exists()

    response = await client.post(
        "/v1/identity/mfa/verify", json={"challenge": challenge, "code": code_for(secret, 1)}
    )
    assert response.status_code == 200
    assert (await Session.get()).amr == ["pwd", "otp"]


async def test_mfa_guessing_is_cut_off(client, me, settings):
    """The old server let a challenge be guessed for its whole 5 minutes."""
    user = await make_user()
    secret = await enrol(client, me(user))
    challenge = await challenge_for(client)

    for _ in range(settings.MFA_MAX_ATTEMPTS):
        wrong = await client.post(
            "/v1/identity/mfa/verify", json={"challenge": challenge, "code": "000000"}
        )
        assert wrong.status_code == 401

    # The right code no longer helps, because the challenge is gone.
    final = await client.post(
        "/v1/identity/mfa/verify", json={"challenge": challenge, "code": code_for(secret, 1)}
    )
    assert final.status_code == 401
    assert not await Session.exists()


async def test_new_challenges_do_not_reset_the_guess_limit(client, me, settings):
    """A correct password clears the login counter, so fetching fresh challenges
    would otherwise allow endless guessing."""
    user = await make_user()
    secret = await enrol(client, me(user))
    allowed = settings.MFA_MAX_ATTEMPTS * 2

    used = 0
    while used < allowed:
        challenge = await challenge_for(client)
        for _ in range(min(settings.MFA_MAX_ATTEMPTS - 1, allowed - used)):
            await client.post(
                "/v1/identity/mfa/verify", json={"challenge": challenge, "code": "000000"}
            )
            used += 1

    challenge = await challenge_for(client)
    blocked = await client.post(
        "/v1/identity/mfa/verify", json={"challenge": challenge, "code": code_for(secret, 1)}
    )
    assert blocked.status_code == 429


async def test_a_totp_code_works_only_once(client, me):
    user = await make_user()
    secret = await enrol(client, me(user))
    code = code_for(secret, 1)

    first = await client.post(
        "/v1/identity/mfa/verify", json={"challenge": await challenge_for(client), "code": code}
    )
    assert first.status_code == 200

    replay = await client.post(
        "/v1/identity/mfa/verify", json={"challenge": await challenge_for(client), "code": code}
    )
    assert replay.status_code == 401


async def test_disabled_user_cannot_finish_mfa(client, me):
    """The old /verify-2fa/ never rechecked is_active."""
    user = await make_user()
    secret = await enrol(client, me(user))
    challenge = await challenge_for(client)
    user.is_active = False
    await user.save()

    response = await client.post(
        "/v1/identity/mfa/verify", json={"challenge": challenge, "code": code_for(secret, 1)}
    )
    assert response.status_code == 401
    assert not await Session.exists()


async def test_removing_mfa_needs_a_code(client, me):
    """The old /disable-2fa needed nothing but a token."""
    user = await make_user()
    headers = me(user)
    secret = await enrol(client, headers)

    wrong = await client.post("/v1/me/mfa/totp/remove", headers=headers, json={"code": "000000"})
    assert wrong.status_code == 401
    assert await MfaFactor.filter(user_id=user.id).exists()

    right = await client.post(
        "/v1/me/mfa/totp/remove", headers=headers, json={"code": code_for(secret, 1)}
    )
    assert right.status_code == 204
    assert not await MfaFactor.filter(user_id=user.id).exists()


async def test_mfa_cannot_be_enrolled_twice(client, me):
    user = await make_user()
    headers = me(user)
    await enrol(client, headers)
    second = await client.post("/v1/me/mfa/totp", headers=headers, json={"password": PASSWORD})
    assert second.status_code == 409


async def test_adding_a_factor_needs_the_password(client, me):
    """A hijacked session must not be able to add its own second factor."""
    user = await make_user()
    response = await client.post(
        "/v1/me/mfa/totp", headers=me(user), json={"password": "wrong-password-12"}
    )
    assert response.status_code == 401
    assert not await MfaFactor.filter(user_id=user.id).exists()


async def test_step_up_password_guessing_is_limited(client, me, settings):
    user = await make_user()
    headers = me(user)
    for _ in range(settings.LOGIN_LIMIT_PER_ACCOUNT):
        await client.post("/v1/me/mfa/totp", headers=headers, json={"password": "wrong-password-12"})
    blocked = await client.post("/v1/me/mfa/totp", headers=headers, json={"password": PASSWORD})
    assert blocked.status_code == 429


async def test_removing_mfa_code_guessing_is_limited(client, me, settings):
    user = await make_user()
    headers = me(user)
    secret = await enrol(client, headers)
    for _ in range(settings.MFA_MAX_ATTEMPTS * 2):
        await client.post("/v1/me/mfa/totp/remove", headers=headers, json={"code": "000000"})
    blocked = await client.post(
        "/v1/me/mfa/totp/remove", headers=headers, json={"code": code_for(secret, 1)}
    )
    assert blocked.status_code == 429
    assert await MfaFactor.filter(user_id=user.id).exists()


async def login_from(app, ip, username="alice", password=PASSWORD):
    transport = httpx.ASGITransport(app=app, client=(ip, 1234), raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
        return await http.post(
            "/v1/identity/login", json={"username": username, "password": password}
        )


async def test_a_stranger_cannot_lock_someone_out(app, settings):
    """Failed logins from one address must not block the owner on another."""
    await make_user()
    for _ in range(settings.LOGIN_LIMIT_PER_ACCOUNT + 1):
        await login_from(app, "10.0.0.66", password="wrong-password-12")
    assert (await login_from(app, "10.0.0.66")).status_code == 429
    assert (await login_from(app, "10.0.0.7")).status_code == 200


async def test_guessing_across_many_addresses_hits_the_account_ceiling(app, settings):
    await make_user()
    for index in range(settings.LOGIN_LIMIT_PER_ACCOUNT * 10):
        await login_from(app, f"10.1.{index // 200}.{index % 200}", password="wrong-password-12")
    assert (await login_from(app, "10.9.9.9")).status_code == 429


async def test_successful_logins_do_not_count_against_a_shared_address(app, settings):
    """Everyone behind one proxy shares an address, so success must not use it up."""
    await make_user()
    for _ in range(settings.LOGIN_LIMIT_PER_IP + 1):
        assert (await login_from(app, "10.0.0.8")).status_code == 200


async def test_expired_challenge_is_refused(client):
    response = await client.post(
        "/v1/identity/mfa/verify", json={"challenge": "not-a-real-one", "code": "123456"}
    )
    assert response.status_code == 401


async def test_login_writes_an_audit_record(client):
    user = await make_user()
    await password_login(client)
    record = await AuditLog.get(action="user.login")
    assert record.actor == str(user.public_id)
    assert PASSWORD not in str(record.details)


async def test_mfa_helper_loads_nothing_for_an_unknown_challenge():
    with pytest.raises(Exception):
        await mfa.load_challenge("nope")
