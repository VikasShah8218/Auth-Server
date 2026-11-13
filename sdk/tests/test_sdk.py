"""SDK tests against a fake Auth Server (httpx.MockTransport) that signs with real ES256 keys.

    python -m unittest discover -s tests        (or: pytest)
"""

import asyncio
import json
import os
import tempfile
import time
import unittest

import httpx
from joserfc import jwt
from joserfc.jwk import ECKey, OctKey

from auth_sdk import AuthError, AuthSDK, MissingScope, StaleAuthState, decode_mask

ISSUER = "http://auth.test"
APP = "ANPR"


def encode_mask(bits: set[int]) -> str:
    import base64

    mask = sum(1 << bit for bit in bits)
    return base64.urlsafe_b64encode(mask.to_bytes((mask.bit_length() + 7) // 8, "little")).rstrip(b"=").decode()


class FakeAuthServer:
    """Just enough of the Auth Server for the SDK: JWKS, client credentials, permission map,
    snapshot, ACK and an SSE stream that sends whatever is queued."""

    def __init__(self) -> None:
        self.key = ECKey.generate_key("P-256", parameters={"kid": "k1"}, private=True)
        self.keys = [self.key]
        self.seq = 0
        self.queued: list[str] = []
        self.acks: list[tuple[str, int]] = []
        self.stream_status = 200
        self.map_version = 1
        self.permissions = [
            {"code": "*", "bit": 0, "retired": False},
            {"code": "vehicle.read", "bit": 1, "retired": False},
            {"code": "report.export", "bit": 2, "retired": False},
        ]
        self.snapshot = {"users": [], "revoked_sessions": [], "revoked_clients": []}
        self.calls: list[str] = []
        self.users_read = True
        self.members = [
            {"sub": f"sub-{i}", "username": f"user{i:02d}", "given_name": None, "family_name": None,
             "email": None, "is_active": True, "roles": [{"id": "r-op", "name": "Operator"}]}
            for i in range(5)
        ]
        self.roles = [{"id": "r-op", "name": "Operator", "description": None, "permissions": ["vehicle.read"]}]

    def sign(self, claims: dict, typ: str = "at+jwt", key: ECKey | None = None, lifetime: int = 600) -> str:
        key = key or self.key
        now = int(time.time())
        payload = {"iss": ISSUER, "iat": now, "exp": now + lifetime, **claims}
        return jwt.encode({"alg": "ES256", "typ": typ, "kid": key.kid}, payload, key, algorithms=["ES256"])

    def user_token(self, **overrides) -> str:
        claims = {
            "aud": APP, "sub": "user-1", "sid": "sid-1", "ver": 1, "token_use": "user",
            "pm": encode_mask({1}), "pv": 1, "roles": ["Operator"], "client_id": "anpr-web",
        }
        claims.update(overrides)
        return self.sign(claims)

    def publish(self, type: str, payload: dict) -> None:
        self.seq += 1
        signed = self.sign(
            {"aud": APP, "seq": self.seq, "type": type, "payload": payload}, typ="event+jwt", lifetime=300
        )
        self.queued.append(f"id: {self.seq}\nevent: {type}\ndata: {signed}\n\n")

    async def handle(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        self.calls.append(f"{request.method} {path}")
        if path == "/.well-known/jwks.json":
            return httpx.Response(200, json={"keys": [k.as_dict(private=False) for k in self.keys]})
        if path == "/oauth/token":
            return httpx.Response(200, json={"access_token": "svc", "token_type": "Bearer", "expires_in": 900})
        if path == f"/v1/apps/{APP}/permission-map":
            return httpx.Response(200, json={"version": self.map_version, "permissions": self.permissions})
        if path in (f"/v1/apps/{APP}/members", f"/v1/apps/{APP}/roles"):
            if not self.users_read:
                return httpx.Response(403, json={"detail": {"code": "insufficient_scope", "message": "x"}})
            if path.endswith("/roles"):
                return httpx.Response(200, json=self.roles)
            limit = int(request.url.params.get("limit", 200))
            after = request.url.params.get("cursor")
            rows = [m for m in self.members if after is None or m["username"] > after]
            page = rows[:limit]
            more = len(rows) > limit
            return httpx.Response(200, json={"items": page, "next_cursor": page[-1]["username"] if more else None})
        if path == f"/v1/events/{APP}/snapshot":
            return httpx.Response(200, json={"seq": self.seq, "perm_map_version": self.map_version, **self.snapshot})
        if path == f"/v1/events/{APP}/ack":
            body = json.loads(request.content)
            self.acks.append((body["instance_id"], body["seq"]))
            return httpx.Response(204)
        if path == f"/v1/events/{APP}":
            if self.stream_status != 200:
                return httpx.Response(self.stream_status, json={"detail": {"code": "snapshot_required"}})
            after = int(request.url.params["after"])
            frames = [f for f in self.queued if int(f.split("\n")[0][4:]) > after]
            body = "".join(frames) + ": keep-alive\n\n"
            return httpx.Response(200, content=body.encode(), headers={"content-type": "text/event-stream"})
        return httpx.Response(404)


class SDKTestCase(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.server = FakeAuthServer()

    def make_sdk(self, **options) -> AuthSDK:
        options.setdefault("transport", httpx.MockTransport(self.server.handle))
        return AuthSDK(ISSUER, APP, "anpr-api", "secret", **options)

    async def synced_sdk(self, **options) -> AuthSDK:
        sdk = self.make_sdk(**options)
        await sdk._follow_events()
        self.addAsyncCleanup(sdk._http.aclose)
        return sdk


class MaskTests(unittest.TestCase):
    def test_decodes_little_endian_base64url(self):
        self.assertEqual(decode_mask("EgI"), 530)  # bits 1, 4 and 9
        self.assertEqual(decode_mask(""), 0)

    def test_rejects_non_canonical_and_wrong_types(self):
        for bad in ("EgIA", "E g", "!!", 530, None, "A" * 200):
            with self.assertRaises(AuthError, msg=repr(bad)):
                decode_mask(bad)


class VerifyTests(SDKTestCase):
    async def test_unsynced_server_fails_closed(self):
        sdk = self.make_sdk()
        self.addAsyncCleanup(sdk._http.aclose)
        with self.assertRaises(StaleAuthState):
            await sdk.verify(self.server.user_token())

    async def test_valid_token_and_permissions(self):
        sdk = await self.synced_sdk()
        user = await sdk.verify(self.server.user_token())
        self.assertEqual((user.sub, user.sid, user.roles), ("user-1", "sid-1", ["Operator"]))
        self.assertTrue(user.has_perm("vehicle.read"))
        self.assertFalse(user.has_perm("report.export"))
        self.assertFalse(user.has_perm("never.defined"))
        self.assertTrue(user.has_role("Admin", "Operator"))

    async def test_wildcard_grants_everything(self):
        sdk = await self.synced_sdk()
        user = await sdk.verify(self.server.user_token(pm=encode_mask({0})))
        self.assertTrue(user.has_perm("report.export"))

    async def test_rejects_wrong_audience_type_issuer_and_use(self):
        sdk = await self.synced_sdk()
        bad = [
            self.server.user_token(aud="SNVR"),
            self.server.user_token(iss="http://evil.test"),
            self.server.user_token(token_use="service"),
            self.server.user_token(ver="1"),
            self.server.user_token(roles="Admin"),
            self.server.sign({"aud": APP, "sub": "u", "sid": "s", "ver": 1, "token_use": "user"}, typ="JWT"),
            "not-a-token",
        ]
        for token in bad:
            with self.assertRaises(AuthError, msg=token[:40]):
                await sdk.verify(token)

    async def test_rejects_forged_algorithms_and_unknown_keys(self):
        sdk = await self.synced_sdk()
        hmac = OctKey.import_key(b"x" * 32)
        forged = jwt.encode(
            {"alg": "HS256", "typ": "at+jwt", "kid": "k1"},
            {"iss": ISSUER, "aud": APP, "exp": int(time.time()) + 60, "sub": "u", "sid": "s", "ver": 9},
            hmac,
            algorithms=["HS256"],
        )
        stranger = ECKey.generate_key("P-256", parameters={"kid": "k9"}, private=True)
        for token in (forged, self.server.sign({"aud": APP}, key=stranger)):
            with self.assertRaises(AuthError):
                await sdk.verify(token)

    async def test_expiry_with_leeway(self):
        sdk = await self.synced_sdk(leeway_seconds=30)
        now = int(time.time())
        await sdk.verify(self.server.user_token(exp=now - 10))  # within the leeway
        with self.assertRaises(AuthError):
            await sdk.verify(self.server.user_token(exp=now - 60))

    async def test_max_staleness(self):
        sdk = await self.synced_sdk(max_staleness_seconds=60)
        await sdk.verify(self.server.user_token())
        sdk._last_contact = time.time() - 120
        with self.assertRaises(StaleAuthState):
            await sdk.verify(self.server.user_token())


class EventTests(SDKTestCase):
    async def test_snapshot_then_events_revoke_tokens(self):
        self.server.publish("user.access_changed", {"users": [{"sub": "user-0", "ver": 1}]})
        self.server.snapshot["users"] = [{"sub": "user-1", "ver": 1, "is_active": True}]
        sdk = await self.synced_sdk()
        self.assertEqual(sdk._cursor, 1)
        token = self.server.user_token()
        await sdk.verify(token)

        self.server.publish("user.access_changed", {"users": [{"sub": "user-1", "ver": 2}]})
        await sdk._follow_events()
        with self.assertRaises(AuthError):
            await sdk.verify(token)
        await sdk.verify(self.server.user_token(ver=2))

        self.server.publish("session.revoked", {"sid": "sid-1", "sub": "user-1"})
        await sdk._follow_events()
        with self.assertRaises(AuthError):
            await sdk.verify(self.server.user_token(ver=2))
        await sdk.verify(self.server.user_token(ver=2, sid="sid-2"))

    async def test_disable_and_enable(self):
        sdk = await self.synced_sdk()
        self.server.publish("user.disabled", {"users": [{"sub": "user-1", "ver": 2}]})
        await sdk._follow_events()
        with self.assertRaises(AuthError):
            await sdk.verify(self.server.user_token(ver=2))
        self.server.publish("user.access_changed", {"users": [{"sub": "user-1", "ver": 3}]})
        await sdk._follow_events()
        await sdk.verify(self.server.user_token(ver=3))

    async def test_client_revoked_covers_earlier_tokens(self):
        sdk = await self.synced_sdk()
        old = self.server.user_token(iat=int(time.time()) - 5)
        self.server.publish(
            "client.revoked", {"client_id": "anpr-web", "version": 2, "revoked_at": int(time.time()) - 1}
        )
        await sdk._follow_events()
        with self.assertRaises(AuthError):
            await sdk.verify(old)
        await sdk.verify(self.server.user_token(iat=int(time.time()) + 1))

    async def test_revoked_signing_key(self):
        sdk = await self.synced_sdk()
        token = self.server.user_token()
        second = ECKey.generate_key("P-256", parameters={"kid": "k2"}, private=True)
        self.server.keys = [second]
        old_key, self.server.key = self.server.key, second
        self.server.publish("key.rotated", {"kid": old_key.kid, "revoked": True})
        await sdk._follow_events()
        with self.assertRaises(AuthError):
            await sdk.verify(token)
        await sdk.verify(self.server.user_token())

    async def test_new_permission_needs_no_restart(self):
        sdk = await self.synced_sdk()
        self.server.permissions.append({"code": "watchlist.edit", "bit": 3, "retired": False})
        self.server.map_version = 2
        self.server.publish("permissions.changed", {"version": 2})
        await sdk._follow_events()
        user = await sdk.verify(self.server.user_token(pm=encode_mask({3}), pv=2))
        self.assertTrue(user.has_perm("watchlist.edit"))

    async def test_events_are_acknowledged_and_not_applied_twice(self):
        sdk = await self.synced_sdk(instance_id="anpr-1")
        self.server.publish("session.revoked", {"sid": "sid-9", "sub": "user-1"})
        await sdk._follow_events()
        await sdk._follow_events()
        self.assertIn(("anpr-1", 1), self.server.acks)
        self.assertEqual(sdk._cursor, 1)

    async def test_unresumable_cursor_takes_a_snapshot(self):
        sdk = await self.synced_sdk()
        sdk._cursor = 500  # e.g. the auth database was reset
        self.server.stream_status = 409
        await sdk._follow_events()
        self.assertIsNone(sdk._cursor)
        self.server.stream_status = 200
        await sdk._follow_events()
        self.assertEqual(sdk._cursor, 0)

    async def test_forged_event_is_refused(self):
        sdk = await self.synced_sdk()
        stranger = ECKey.generate_key("P-256", parameters={"kid": "evil"}, private=True)
        signed = self.server.sign(
            {"aud": APP, "seq": 1, "type": "user.disabled", "payload": {"users": []}}, typ="event+jwt", key=stranger
        )
        self.server.queued.append(f"id: 1\nevent: user.disabled\ndata: {signed}\n\n")
        with self.assertRaises(RuntimeError):
            await sdk._follow_events()
        self.assertEqual(sdk._cursor, 0)


class StateTests(SDKTestCase):
    def state_file(self) -> str:
        directory = tempfile.mkdtemp()
        return os.path.join(directory, "auth-state.json")

    async def test_restart_verifies_while_auth_server_is_down(self):
        path = self.state_file()
        sdk = await self.synced_sdk(state_path=path)
        self.server.publish("session.revoked", {"sid": "sid-gone", "sub": "user-1"})
        await sdk._follow_events()

        def down(_: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("down")

        restarted = self.make_sdk(state_path=path, transport=httpx.MockTransport(down))
        self.addAsyncCleanup(restarted._http.aclose)
        self.assertEqual(restarted.instance_id, sdk.instance_id)
        await restarted.verify(self.server.user_token())
        with self.assertRaises(AuthError):
            await restarted.verify(self.server.user_token(sid="sid-gone"))

    async def test_foreign_or_corrupt_state_is_ignored(self):
        path = self.state_file()
        await self.synced_sdk(state_path=path)
        other = AuthSDK("http://other.test", APP, "c", "s", state_path=path)
        self.addAsyncCleanup(other._http.aclose)
        self.assertIsNone(other._cursor)

        with open(path, "w", encoding="utf-8") as file:
            file.write("{ not json")
        broken = self.make_sdk(state_path=path)
        self.addAsyncCleanup(broken._http.aclose)
        self.assertIsNone(broken._cursor)


class ServiceTokenTests(SDKTestCase):
    async def test_service_token_and_client_version(self):
        sdk = await self.synced_sdk()
        token = self.server.sign({"aud": APP, "token_use": "service", "client_id": "nvr-api", "ver": 1})
        claims = await sdk.verify_service(token)
        self.assertEqual(claims["client_id"], "nvr-api")
        with self.assertRaises(AuthError):
            await sdk.verify_service(self.server.user_token())

        self.server.publish("client.revoked", {"client_id": "nvr-api", "version": 2, "revoked_at": int(time.time())})
        await sdk._follow_events()
        with self.assertRaises(AuthError):
            await sdk.verify_service(token)


class MembersTests(SDKTestCase):
    async def test_members_page_all_pages_and_roles(self):
        sdk = await self.synced_sdk()
        page = await sdk.members(limit=2)
        self.assertEqual([m["username"] for m in page["items"]], ["user00", "user01"])
        self.assertEqual(page["next_cursor"], "user01")

        self.server.members += [
            {**self.server.members[0], "sub": f"x-{i}", "username": f"z{i:04d}"} for i in range(1500)
        ]
        everyone = await sdk.list_all_members()
        self.assertEqual(len(everyone), 1505)
        self.assertEqual(len({m["sub"] for m in everyone}), 1505)
        self.assertEqual(await sdk.roles(), self.server.roles)

    async def test_missing_scope_is_a_clear_error_and_sync_still_works(self):
        self.server.users_read = False
        sdk = await self.synced_sdk()
        await sdk.verify(self.server.user_token())
        with self.assertRaisesRegex(MissingScope, "users.read"):
            await sdk.members()
        with self.assertRaises(MissingScope):
            await sdk.roles()

    async def test_on_change_fires_for_member_events_and_snapshots(self):
        sdk = self.make_sdk()
        self.addAsyncCleanup(sdk._http.aclose)
        seen: list[tuple[str, dict]] = []

        @sdk.on_change
        async def refresh(type, payload):
            seen.append((type, payload))

        def broken(type, payload):
            raise ValueError("callback bug")

        sdk.on_change(broken)
        await sdk._follow_events()  # first sync takes a snapshot
        self.server.publish("members.changed", {"sub": "sub-1"})
        self.server.publish("user.disabled", {"users": [{"sub": "sub-2", "ver": 2}]})
        self.server.publish("session.revoked", {"sid": "s", "sub": "sub-2"})  # not a member change
        self.server.publish("user.access_changed", {"users": [{"sub": "sub-3", "ver": 2}]})
        with self.assertLogs("auth_sdk", "ERROR"):
            await sdk._follow_events()
            await asyncio.sleep(0)
        await asyncio.gather(*sdk._callback_tasks)

        self.assertEqual(
            [type for type, _ in seen], ["snapshot", "members.changed", "user.disabled", "user.access_changed"]
        )
        self.assertEqual(seen[1][1], {"sub": "sub-1"})
        self.assertEqual(sdk.members_version, 4)
        self.assertEqual(sdk._cursor, 4)  # the failing callback didn't stop the sync


class FastAPITests(SDKTestCase):
    async def test_dependencies(self):
        from fastapi import Depends, FastAPI

        sdk = await self.synced_sdk()
        app = FastAPI()

        @app.get("/vehicles")
        async def vehicles(_=Depends(sdk.require_perm("vehicle.read"))):
            return ["JK01AB1234"]

        @app.get("/reports")
        async def reports(_=Depends(sdk.require_perm("report.export"))):
            return []

        @app.get("/internal")
        async def internal(claims=Depends(sdk.current_service)):
            return {"caller": claims["client_id"]}

        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://downstream") as client:
            bearer = {"Authorization": f"Bearer {self.server.user_token()}"}
            self.assertEqual((await client.get("/vehicles")).status_code, 401)
            self.assertEqual((await client.get("/vehicles", headers=bearer)).status_code, 200)
            self.assertEqual((await client.get("/reports", headers=bearer)).status_code, 403)
            self.assertEqual((await client.get("/internal", headers=bearer)).status_code, 401)
            service = self.server.sign({"aud": APP, "token_use": "service", "client_id": "nvr-api", "ver": 1})
            response = await client.get("/internal", headers={"Authorization": f"Bearer {service}"})
            self.assertEqual(response.json(), {"caller": "nvr-api"})

            sdk._cursor = None
            self.assertEqual((await client.get("/vehicles", headers=bearer)).status_code, 503)


if __name__ == "__main__":
    unittest.main()
