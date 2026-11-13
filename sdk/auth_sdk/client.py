"""The downstream side of the Auth Server.

Verification is local: a signature check against cached public keys, plus an
in-memory revocation state that the event stream keeps current. No request made
to this server ever calls the auth server, so a brief outage changes nothing.
"""

import asyncio
import base64
import binascii
import contextlib
import json
import logging
import os
import random
import tempfile
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

import httpx
from joserfc import jws, jwt
from joserfc.errors import JoseError
from joserfc.jwk import ECKey

logger = logging.getLogger("auth_sdk")

ALGORITHM = "ES256"
WILDCARD_BIT = 0
MAX_BITS = 1024
STATE_FORMAT = 2

_RETRY_MIN_SECONDS = 1
_RETRY_MAX_SECONDS = 60
_JWKS_RELOAD_SECONDS = 30
_MAP_RELOAD_SECONDS = 10
_READ_TIMEOUT_SECONDS = 45
_TOKEN_MARGIN_SECONDS = 30
_MEMBERS_PAGE = 1000

# Events after which a cached members or roles list may be out of date.
MEMBER_EVENTS = frozenset({"user.access_changed", "user.disabled", "members.changed"})


class AuthError(Exception):
    """The token is not acceptable. Answer 401."""


class StaleAuthState(Exception):
    """This server has lost sync for longer than it allows. Answer 503."""


class MissingScope(Exception):
    """This server's client lacks a scope the call needs (give it to the client in the console)."""


ChangeCallback = Callable[[str, dict], Awaitable[None] | None]


def decode_mask(value: str) -> int:
    """The `pm` claim: little-endian bytes in base64url, without padding."""
    if not isinstance(value, str):
        raise AuthError("Permission mask is not a string")
    if len(value) > (MAX_BITS // 8 * 4 + 2) // 3:
        raise AuthError("Permission mask too long")
    try:
        raw = base64.urlsafe_b64decode(value.encode("ascii") + b"=" * (-len(value) % 4))
    except (binascii.Error, ValueError, UnicodeEncodeError):
        raise AuthError("Permission mask is not base64url") from None
    mask = int.from_bytes(raw, "little")
    canonical = base64.urlsafe_b64encode(
        mask.to_bytes((mask.bit_length() + 7) // 8, "little")
    ).rstrip(b"=").decode("ascii")
    if canonical != value:
        raise AuthError("Permission mask is not canonical")
    return mask


@dataclass
class Principal:
    """A verified caller."""

    sub: str
    sid: str
    roles: list[str]
    mask: int
    client_id: str
    actor: dict | None
    claims: dict[str, Any]
    _bits: dict[str, int] = field(repr=False, default_factory=dict)

    def has_perm(self, code: str) -> bool:
        if self.mask >> WILDCARD_BIT & 1:
            return True
        # A code this server can't name is denied, never assumed.
        bit = self._bits.get(code)
        return bit is not None and bool(self.mask >> bit & 1)

    def has_role(self, *roles: str) -> bool:
        return bool(set(roles) & set(self.roles))


class AuthSDK:
    def __init__(
        self,
        issuer: str,
        app_key: str,
        client_id: str,
        client_secret: str,
        instance_id: str | None = None,
        state_path: str | None = None,
        max_staleness_seconds: int | None = None,
        api_url: str | None = None,
        leeway_seconds: int = 30,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        """issuer: exactly the Auth Server's ISSUER setting; tokens must carry it as `iss`.

        api_url: where this server reaches the Auth Server, when that differs from the
        public issuer (for example http://auth:8000 inside a private network).

        max_staleness_seconds: deny requests after this long without contact.
        Leave it unset to keep serving during an outage, where the short access
        token lifetime remains the limit on staleness.

        state_path: keeps keys and revocations across restarts, so a server can
        start and verify while the auth server is unreachable. One file per process.

        leeway_seconds: tolerated clock difference when checking expiry.
        """
        self.issuer = issuer.rstrip("/")
        self.app_key = app_key.upper()
        self.client_id = client_id
        self.client_secret = client_secret
        self.state_path = state_path
        self.max_staleness_seconds = max_staleness_seconds
        self.leeway_seconds = max(0, leeway_seconds)

        self._http = httpx.AsyncClient(
            base_url=(api_url or self.issuer).rstrip("/"),
            timeout=httpx.Timeout(10, read=_READ_TIMEOUT_SECONDS),
            transport=transport,
        )
        self._tasks: list[asyncio.Task] = []
        self._service_token: str | None = None
        self._service_token_expiry = 0.0
        self._failures = 0

        self._keys: dict[str, ECKey] = {}
        self._jwks_raw: list[dict] = []
        self._revoked_kids: set[str] = set()
        self._jwks_loaded = 0.0

        self._bits: dict[str, int] = {}
        self._map_version = 0
        self._map_loaded = 0.0

        self._cursor: int | None = None
        self._min_versions: dict[str, int] = {}
        self._disabled: set[str] = set()
        self._revoked_sids: set[str] = set()
        self._revoked_clients: dict[str, dict] = {}
        self._last_contact = 0.0
        self._connected = False

        self.members_version = 0
        self._change_callbacks: list[ChangeCallback] = []
        self._callback_tasks: set[asyncio.Task] = set()

        saved_instance = self._load_state()
        # A stable name keeps one row per process on the Downstream Sync page across restarts.
        self.instance_id = instance_id or saved_instance or uuid.uuid4().hex

    # Lifecycle

    async def start(self) -> None:
        self._tasks = [asyncio.create_task(self._run_forever(self._follow_events))]

    async def stop(self) -> None:
        tasks = self._tasks + list(self._callback_tasks)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        self._tasks = []
        self._callback_tasks.clear()
        await self._http.aclose()

    async def _run_forever(self, loop) -> None:
        """Nothing that fails here may stop the loop for good: revocations would stop
        arriving silently. Failures back off exponentially (with jitter, so a fleet
        doesn't reconnect in step) and reset once a stream opens."""
        while True:
            try:
                await loop()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self._connected = False
                self._failures += 1
                delay = min(_RETRY_MAX_SECONDS, _RETRY_MIN_SECONDS * 2 ** min(self._failures - 1, 6))
                logger.warning("Auth sync interrupted (retry in %.0fs): %s", delay, exc)
                await asyncio.sleep(delay * random.uniform(0.5, 1.0))

    def health(self) -> dict[str, Any]:
        age = time.time() - self._last_contact if self._last_contact else None
        return {
            "instance_id": self.instance_id,
            "connected": self._connected,
            "synced": self._cursor is not None,
            "cursor": self._cursor,
            "seconds_since_contact": age,
            "keys": len(self._keys),
            "stale": self._is_stale(),
        }

    def _is_stale(self) -> bool:
        if self.max_staleness_seconds is None:
            return False
        return time.time() - self._last_contact > self.max_staleness_seconds

    # Persistence

    def _load_state(self) -> str | None:
        """Returns the saved instance id. A missing, unreadable or foreign file is ignored:
        the server then starts unsynced and fails closed until the first snapshot."""
        if not self.state_path or not os.path.exists(self.state_path):
            return None
        try:
            with open(self.state_path, encoding="utf-8") as file:
                state = json.load(file)
            if state.get("issuer") != self.issuer or state.get("app_key") != self.app_key:
                logger.warning("Ignoring auth state saved for another issuer or application")
                return None
            self._revoked_kids = set(state.get("revoked_kids", []))
            self._set_keys(state.get("jwks", []))
            self._bits = dict(state.get("bits", {}))
            self._map_version = int(state.get("map_version", 0))
            self._cursor = state.get("cursor")
            self._min_versions = dict(state.get("min_versions", {}))
            self._disabled = set(state.get("disabled", []))
            self._revoked_sids = set(state.get("revoked_sids", []))
            self._revoked_clients = dict(state.get("revoked_clients", {}))
            return state.get("instance_id")
        except (OSError, ValueError, TypeError, KeyError, JoseError) as exc:
            logger.warning("Ignoring unreadable auth state %s: %s", self.state_path, exc)
            self._reset_state()
            return None

    def _reset_state(self) -> None:
        self._keys, self._jwks_raw, self._revoked_kids = {}, [], set()
        self._bits, self._map_version = {}, 0
        self._cursor = None
        self._min_versions, self._disabled = {}, set()
        self._revoked_sids, self._revoked_clients = set(), {}

    def _save_state(self) -> None:
        if not self.state_path:
            return
        state = {
            "format": STATE_FORMAT,
            "issuer": self.issuer,
            "app_key": self.app_key,
            "instance_id": self.instance_id,
            "jwks": self._jwks_raw,
            "bits": self._bits,
            "map_version": self._map_version,
            "cursor": self._cursor,
            "min_versions": self._min_versions,
            "disabled": sorted(self._disabled),
            "revoked_sids": sorted(self._revoked_sids),
            "revoked_kids": sorted(self._revoked_kids),
            "revoked_clients": self._revoked_clients,
        }
        directory = os.path.dirname(os.path.abspath(self.state_path))
        descriptor, temporary = tempfile.mkstemp(dir=directory, suffix=".tmp")
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as file:
                json.dump(state, file)
            os.replace(temporary, self.state_path)
        except BaseException:
            with contextlib.suppress(OSError):
                os.remove(temporary)
            raise

    # Keys and permission map

    def _set_keys(self, jwks: list[dict]) -> None:
        self._jwks_raw = jwks
        self._keys = {
            key["kid"]: ECKey.import_key(key)
            for key in jwks
            if key["kid"] not in self._revoked_kids
        }

    async def refresh_keys(self) -> None:
        # Set before the call, so that an outage can't turn every token carrying a
        # random kid into an outbound request.
        self._jwks_loaded = time.monotonic()
        response = await self._http.get("/.well-known/jwks.json")
        response.raise_for_status()
        self._set_keys(response.json()["keys"])

    async def _service_auth(self) -> dict[str, str]:
        if self._service_token is None or time.time() >= self._service_token_expiry:
            response = await self._http.post(
                "/oauth/token",
                data={"grant_type": "client_credentials"},
                auth=(self.client_id, self.client_secret),
            )
            if response.status_code in (400, 401):
                raise RuntimeError(
                    f"Client credentials refused ({response.status_code}): check client_id, "
                    "client_secret and that the client is active and confidential"
                )
            response.raise_for_status()
            body = response.json()
            self._service_token = body["access_token"]
            self._service_token_expiry = time.time() + body["expires_in"] - _TOKEN_MARGIN_SECONDS
        return {"Authorization": f"Bearer {self._service_token}"}

    async def _service_call(self, method: str, url: str, **options) -> httpx.Response:
        """Any 401 means the cached token is dead: its client changed, or its signing
        key was revoked. Drop it and retry once, or sync stays blind until it expires."""
        for attempt in range(2):
            response = await self._http.request(
                method, url, headers=await self._service_auth(), **options
            )
            if response.status_code != 401 or attempt == 1:
                break
            self._service_token = None
        response.raise_for_status()
        return response

    async def refresh_permission_map(self) -> None:
        self._map_loaded = time.monotonic()
        response = await self._service_call("GET", f"/v1/apps/{self.app_key}/permission-map")
        body = response.json()
        self._bits = {p["code"]: p["bit"] for p in body["permissions"] if not p["retired"]}
        self._map_version = body["version"]

    # Events

    async def _snapshot(self) -> None:
        response = await self._service_call("GET", f"/v1/events/{self.app_key}/snapshot")
        snapshot = response.json()
        self._min_versions = {user["sub"]: user["ver"] for user in snapshot["users"]}
        self._disabled = {u["sub"] for u in snapshot["users"] if not u["is_active"]}
        self._revoked_sids = set(snapshot["revoked_sessions"])
        self._revoked_clients = {c["client_id"]: c for c in snapshot["revoked_clients"]}
        self._cursor = snapshot["seq"]
        self._save_state()
        await self._ack(snapshot["seq"])
        # Events missed while away are gone: anything cached from the auth server must be reloaded.
        self._members_changed("snapshot", {})

    async def _ack(self, seq: int) -> None:
        await self._service_call(
            "POST",
            f"/v1/events/{self.app_key}/ack",
            json={"instance_id": self.instance_id, "seq": seq},
        )

    async def _follow_events(self) -> None:
        await self.refresh_keys()
        await self.refresh_permission_map()
        if self._cursor is None:
            await self._snapshot()

        async with self._http.stream(
            "GET",
            f"/v1/events/{self.app_key}",
            params={"after": self._cursor, "instance_id": self.instance_id},
            headers=await self._service_auth(),
        ) as stream:
            if stream.status_code == 409:
                # Too far behind, or ahead of the stream (the auth database was reset).
                await stream.aread()
                logger.info("Auth event cursor %s is not resumable; taking a snapshot", self._cursor)
                self._cursor = None
                return
            if stream.status_code == 401:
                await stream.aread()
                self._service_token = None
                raise RuntimeError("Service token refused")
            if stream.status_code == 403:
                await stream.aread()
                raise RuntimeError(
                    f"Event stream refused (403): the client needs scope events.read on {self.app_key}"
                )
            stream.raise_for_status()

            self._connected = True
            self._failures = 0
            self._last_contact = time.time()
            # Report the position at once, so a restarted process shows its real lag.
            await self._ack(self._cursor)
            event_type = None
            async for line in stream.aiter_lines():
                self._last_contact = time.time()
                if line.startswith("event: "):
                    event_type = line[len("event: "):]
                elif line.startswith("data: "):
                    if event_type == "token.expired":
                        self._service_token = None
                        self._connected = False
                        return
                    await self._handle_event(line[len("data: "):])
                    event_type = None
                elif line == "":
                    event_type = None
        self._connected = False

    async def _verify_event(self, signed: str) -> dict:
        header = jws.extract_compact(signed.encode()).headers()
        kid = str(header.get("kid", ""))
        if kid not in self._keys:
            await self.refresh_keys()
        key = None if kid in self._revoked_kids else self._keys.get(kid)
        if key is None or header.get("typ") != "event+jwt" or header.get("alg") != ALGORITHM:
            raise RuntimeError("Unverifiable event")
        claims = jwt.decode(signed, key, algorithms=[ALGORITHM]).claims
        if (
            claims.get("iss") != self.issuer
            or claims.get("aud") != self.app_key
            or not isinstance(claims.get("exp"), int)
            or claims["exp"] + self.leeway_seconds <= time.time()
        ):
            raise RuntimeError("Event rejected")
        return claims

    async def _handle_event(self, signed: str) -> None:
        event = await self._verify_event(signed)
        seq = event["seq"]
        if self._cursor is not None and seq <= self._cursor:
            return
        await self._apply(event["type"], event["payload"])
        self._cursor = seq
        self._save_state()
        await self._ack(seq)
        if event["type"] in MEMBER_EVENTS:
            self._members_changed(event["type"], event["payload"])

    async def _apply(self, type: str, payload: dict) -> None:
        if type in ("user.access_changed", "user.disabled"):
            for user in payload["users"]:
                current = self._min_versions.get(user["sub"], 0)
                self._min_versions[user["sub"]] = max(current, user["ver"])
                if type == "user.disabled":
                    self._disabled.add(user["sub"])
                else:
                    self._disabled.discard(user["sub"])
        elif type == "session.revoked":
            self._revoked_sids.add(payload["sid"])
        elif type == "client.revoked":
            self._revoked_clients[payload["client_id"]] = payload
        elif type == "key.rotated":
            if payload.get("revoked"):
                self._revoked_kids.add(payload["kid"])
                self._keys.pop(payload["kid"], None)
            await self.refresh_keys()
        elif type == "permissions.changed":
            await self.refresh_permission_map()
        elif type == "members.changed":
            pass  # nothing to verify differently; on_change callbacks run after the ACK
        else:
            logger.info("Ignoring unknown auth event type %s", type)

    # Members and roles (scope users.read)

    def on_change(self, callback: ChangeCallback) -> ChangeCallback:
        """Call `callback(event_type, payload)` whenever a cached members or roles list may be out of date:
        after user.access_changed, user.disabled, members.changed, and after a snapshot ("snapshot").

        It may be async. It runs in the background, so a slow refresh never holds up revocations, and an
        error in it is logged and never stops the sync. Usable as a decorator."""
        self._change_callbacks.append(callback)
        return callback

    def _members_changed(self, type: str, payload: dict) -> None:
        self.members_version += 1
        for callback in self._change_callbacks:
            task = asyncio.create_task(self._run_callback(callback, type, payload))
            self._callback_tasks.add(task)
            task.add_done_callback(self._callback_tasks.discard)

    @staticmethod
    async def _run_callback(callback: ChangeCallback, type: str, payload: dict) -> None:
        try:
            result = callback(type, payload)
            if asyncio.iscoroutine(result):
                await result
        except Exception:
            logger.exception("Auth on_change callback failed for %s", type)

    async def _users_call(self, path: str, params: dict | None = None) -> Any:
        """GET under /v1/apps/{key}/, turning a missing users.read scope into a clear error."""
        url = f"/v1/apps/{self.app_key}/{path}"
        try:
            response = await self._service_call("GET", url, params=params)
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 403 and "insufficient_scope" in exc.response.text:
                raise MissingScope(
                    f"Client {self.client_id} needs scope users.read: tick it on the client in the console"
                ) from None
            raise
        return response.json()

    async def members(self, q: str | None = None, limit: int = 200, cursor: str | None = None) -> dict:
        """One page of this application's members: {"items": [...], "next_cursor": str | None}.

        Each item: sub (equals the token "sub"), username, given_name, family_name, email, is_active, and
        roles as [{"id", "name"}]. Store role ids, not names: ids survive renames."""
        params: dict[str, Any] = {"limit": limit}
        if q:
            params["q"] = q
        if cursor:
            params["cursor"] = cursor
        return await self._users_call("members", params)

    async def list_all_members(self, q: str | None = None) -> list[dict]:
        """Every member, following next_cursor to the end."""
        items: list[dict] = []
        cursor = None
        while True:
            page = await self.members(q=q, limit=_MEMBERS_PAGE, cursor=cursor)
            items.extend(page["items"])
            cursor = page["next_cursor"]
            if not cursor:
                return items

    async def roles(self) -> list[dict]:
        """Every role of this application: [{"id", "name", "description", "permissions": [codes]}]."""
        return await self._users_call("roles")

    # Verification

    async def _key_for(self, kid: str) -> ECKey:
        if kid in self._revoked_kids:
            raise AuthError("Signing key was revoked")
        if kid not in self._keys and time.monotonic() - self._jwks_loaded > _JWKS_RELOAD_SECONDS:
            try:
                await self.refresh_keys()
            except (httpx.HTTPError, ValueError, KeyError):
                logger.warning("Could not reload signing keys")
        key = self._keys.get(kid)
        if key is None:
            raise AuthError("Unknown signing key")
        return key

    async def _refresh_map_if_behind(self, version: Any) -> None:
        if not isinstance(version, int) or version <= self._map_version:
            return
        if time.monotonic() - self._map_loaded > _MAP_RELOAD_SECONDS:
            try:
                await self.refresh_permission_map()
            except (httpx.HTTPError, RuntimeError, ValueError, KeyError):
                logger.warning("Could not reload the permission map")

    async def _decode(self, token: str) -> dict:
        try:
            header = jws.extract_compact(token.encode()).headers()
            if header.get("alg") != ALGORITHM:
                raise AuthError("Invalid token")
            key = await self._key_for(str(header.get("kid", "")))
            claims = jwt.decode(token, key, algorithms=[ALGORITHM]).claims
        except (JoseError, ValueError, UnicodeError, TypeError):
            raise AuthError("Invalid token") from None
        exp = claims.get("exp")
        if (
            header.get("typ") != "at+jwt"
            or claims.get("iss") != self.issuer
            or claims.get("aud") != self.app_key
            or not isinstance(exp, int)
            or isinstance(exp, bool)
            or exp + self.leeway_seconds <= time.time()
        ):
            raise AuthError("Invalid token")
        return claims

    def _check_ready(self) -> None:
        # With no cursor this server has never seen the revocation state, so it can't
        # tell a good token from a revoked one. Fails closed until the first sync.
        if self._cursor is None:
            raise StaleAuthState("Auth state has not synced yet")
        if self._is_stale():
            raise StaleAuthState("Lost contact with the auth server")

    def _issued_by_revoked_client(self, claims: dict) -> bool:
        actor = claims.get("act") or {}
        if not isinstance(actor, dict):
            return True
        revoked = self._revoked_clients.get(actor.get("sub") or claims.get("client_id"))
        return revoked is not None and claims.get("iat", 0) <= revoked["revoked_at"]

    async def verify(self, token: str) -> Principal:
        """Verify a user's access token. Raises AuthError or StaleAuthState."""
        self._check_ready()
        claims = await self._decode(token)
        sub, sid, ver = claims.get("sub"), claims.get("sid"), claims.get("ver")
        roles = claims.get("roles", [])
        if (
            claims.get("token_use") != "user"
            or not isinstance(sub, str) or not sub
            or not isinstance(sid, str) or not sid
            or not isinstance(ver, int)
            or not isinstance(roles, list)
        ):
            raise AuthError("Invalid token")
        if sub in self._disabled or sid in self._revoked_sids:
            raise AuthError("Token has been revoked")
        if ver < self._min_versions.get(sub, 0) or self._issued_by_revoked_client(claims):
            raise AuthError("Token has been revoked")

        mask = decode_mask(claims.get("pm", ""))
        await self._refresh_map_if_behind(claims.get("pv", 0))
        return Principal(
            sub=sub,
            sid=sid,
            roles=[str(role) for role in roles],
            mask=mask,
            client_id=str(claims.get("client_id", "")),
            actor=claims.get("act"),
            claims=claims,
            _bits=self._bits,
        )

    async def verify_service(self, token: str) -> dict:
        """Verify another server's service token, sent with audience=this app."""
        self._check_ready()
        claims = await self._decode(token)
        client_id = claims.get("client_id")
        if claims.get("token_use") != "service" or not isinstance(client_id, str) or not client_id:
            raise AuthError("Invalid token")
        revoked = self._revoked_clients.get(client_id)
        if revoked is not None and claims.get("ver", 0) < revoked["version"]:
            raise AuthError("Token has been revoked")
        return claims

    # FastAPI

    def _bearer_dependency(self, verify):
        from fastapi import Depends, HTTPException
        from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

        bearer = HTTPBearer(auto_error=False)

        async def dependency(
            credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
        ):
            if credentials is None:
                raise HTTPException(401, "Authentication required", {"WWW-Authenticate": "Bearer"})
            try:
                return await verify(credentials.credentials)
            except AuthError:
                raise HTTPException(
                    401, "Invalid or revoked token", {"WWW-Authenticate": "Bearer"}
                ) from None
            except StaleAuthState:
                raise HTTPException(
                    503, "Authorization is temporarily unavailable", {"Retry-After": "5"}
                ) from None

        return dependency

    @property
    def current_user(self):
        """FastAPI dependency: any valid user token for this application."""
        if not hasattr(self, "_principal_dependency"):
            self._principal_dependency = self._bearer_dependency(self.verify)
        return self._principal_dependency

    @property
    def current_service(self):
        """FastAPI dependency: a valid service token for this application (server-to-server).
        Returns the token's claims; `client_id` names the calling service."""
        if not hasattr(self, "_service_dependency"):
            self._service_dependency = self._bearer_dependency(self.verify_service)
        return self._service_dependency

    def require_perm(self, *codes: str):
        """FastAPI dependency: the caller must hold every listed permission."""
        from fastapi import Depends, HTTPException

        async def checker(principal: Principal = Depends(self.current_user)) -> Principal:
            if not all(principal.has_perm(code) for code in codes):
                raise HTTPException(403, "Insufficient permission")
            return principal

        return checker

    def require_role(self, *roles: str):
        """FastAPI dependency: the caller must hold at least one listed role."""
        from fastapi import Depends, HTTPException

        async def checker(principal: Principal = Depends(self.current_user)) -> Principal:
            if not principal.has_role(*roles):
                raise HTTPException(403, "Insufficient role")
            return principal

        return checker
