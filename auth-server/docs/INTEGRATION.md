# Downstream Integration Guide

How a downstream server (for example ANPR or NVR) trusts the Auth Server: signing users in, verifying their
tokens, enforcing permissions, staying in sync with revocations, and calling other servers.

- Every Auth Server endpoint: [API.md](API.md)
- Why it works this way: [ARCHITECTURE.md](ARCHITECTURE.md)

The examples use an application with key `ANPR`. Replace it with your own.

---

## 1. The model in one picture

```
 Browser app ──(1) /oauth/authorize + PKCE──> Auth Server ──> login page ──> code
      │       ──(2) /oauth/token ───────────> access token (10 min) + refresh token
      │
      └──(3) GET /vehicles  Authorization: Bearer <access token> ──> ANPR server
                                                                     │ verifies LOCALLY:
                                                                     │  signature (cached JWKS)
                                                                     │  iss / aud / exp / typ
                                                                     │  revocation state (cache)
                                                                     │  permission bits (cached map)
 ANPR server ──(4) GET /v1/events/ANPR (SSE, outbound) ─────────────> Auth Server
             <── signed events: session.revoked, user.access_changed, ...
             ──(5) POST /v1/events/ANPR/ack {seq}
```

- A request to your server **never calls the Auth Server**. Verification uses cached public keys and a cached
  revocation state.
- Revocations arrive over **SSE**: your server opens the connection, outbound, so no inbound port is needed.
- If the Auth Server is down, valid tokens keep working until they expire (10 minutes at most).

---

## 2. One-time setup in the Auth Server console

1. **Create the application**, e.g. key `ANPR`. It starts with the `*` permission (full access, bit 0) and an
   `Admin` role.
2. **Create its permissions**, e.g. `vehicle.read`, `vehicle.write`, `report.export`. Each gets a permanent bit.
3. **Create roles** (e.g. `Operator`, `Viewer`) and give them permissions.
4. **Assign users** to roles. A user with no role in `ANPR` can't sign in to ANPR (`access_denied`).
5. **Create a confidential client for the server**, e.g. `anpr-api`:

   | Field | Value |
   |---|---|
   | type | `confidential` |
   | scopes | `events.read`, `permissions.read`, plus `users.read` if your server lists its members and roles (section 10) |
   | audiences | apps this server may call or exchange tokens for (e.g. `NVR`), or none |

   Save the **client secret**: it's shown once. Rotate it later with *Rotate secret*.
6. **If ANPR has a browser app, create a public client**, e.g. `anpr-web`, with its exact redirect URI
   (`https://anpr.example.com/callback`, or `http://localhost:<port>/callback` in development) and scopes
   `openid profile email`.

---

## 3. Configuration for your server

```env
AUTH_ISSUER=https://auth.example.com        # must equal the Auth Server's ISSUER exactly
AUTH_APP_KEY=ANPR
AUTH_CLIENT_ID=anpr-api
AUTH_CLIENT_SECRET=<from step 5, never commit it>
AUTH_STATE_PATH=/var/lib/anpr/auth-state.json   # recommended
AUTH_INSTANCE_ID=anpr-1                          # stable name per process
```

---

## 4. Python servers: use the Auth SDK

The SDK (`../sdk`, package `auth_sdk`) implements everything in sections 6 to 9 for you.

```bash
pip install -e path/to/sdk
```

```python
import os
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from auth_sdk import AuthSDK, Principal

auth = AuthSDK(
    issuer=os.environ["AUTH_ISSUER"],
    app_key=os.environ["AUTH_APP_KEY"],
    client_id=os.environ["AUTH_CLIENT_ID"],
    client_secret=os.environ["AUTH_CLIENT_SECRET"],
    instance_id=os.environ.get("AUTH_INSTANCE_ID"),
    state_path=os.environ.get("AUTH_STATE_PATH"),
    max_staleness_seconds=None,          # set e.g. 60 on high-risk servers
    api_url=os.environ.get("AUTH_API_URL"),  # optional: internal address when it differs from the issuer
)


@asynccontextmanager
async def lifespan(_: FastAPI):
    await auth.start()                   # keys, permission map, snapshot, then the event stream
    yield
    await auth.stop()


app = FastAPI(lifespan=lifespan)


@app.get("/health")
async def health():
    return auth.health()


@app.get("/whoami")
async def whoami(user: Principal = Depends(auth.current_user)):
    return {"sub": user.sub, "roles": user.roles}


@app.get("/vehicles")
async def vehicles(user: Principal = Depends(auth.require_perm("vehicle.read"))):
    ...


@app.delete("/vehicles/{plate}")
async def delete_vehicle(plate: str, user: Principal = Depends(auth.require_role("Admin", "Operator"))):
    ...
```

### SDK reference

| API | Does |
|---|---|
| `AuthSDK(issuer, app_key, client_id, client_secret, instance_id=None, state_path=None, max_staleness_seconds=None, api_url=None, leeway_seconds=30)` | Creates the client. `issuer` must equal the Auth Server's `ISSUER` exactly. `api_url` is where to reach it when that differs (private network). `instance_id` defaults to the one saved in `state_path`, else a random value; set a stable one. `leeway_seconds` tolerates clock drift on expiry checks |
| `await auth.start()` / `await auth.stop()` | Starts / stops the background sync (call from the app lifespan) |
| `auth.current_user` | FastAPI dependency: any valid user token for this app. Returns a `Principal` |
| `auth.require_perm("a.read", "b.write")` | Dependency: the caller holds **every** listed permission (403 otherwise) |
| `auth.require_role("Admin", "Operator")` | Dependency: the caller holds **at least one** listed role (403 otherwise) |
| `await auth.verify(token)` | Outside FastAPI: returns a `Principal`, or raises `AuthError` (answer 401) or `StaleAuthState` (answer 503) |
| `auth.current_service` | FastAPI dependency: a valid **service** token for this app (server-to-server). Returns its claims; `client_id` names the caller |
| `await auth.verify_service(token)` | Verifies another server's service token sent to this app. Returns its claims |
| `auth.health()` | `{"instance_id", "connected", "synced", "cursor", "seconds_since_contact", "keys", "stale"}`. Put it in your health check |
| `await auth.members(q=None, limit=200, cursor=None)` | One page of your app's members (scope `users.read`, section 10) |
| `await auth.list_all_members(q=None)` | Every member, following the cursor |
| `await auth.roles()` | Every role with its permission codes |
| `auth.on_change(callback)` | `callback(event_type, payload)`, sync or async, runs in the background whenever members or roles may have changed (also after a snapshot). Usable as a decorator |
| `auth.members_version` | Integer that rises at the same moments, for servers that poll |

`Principal` fields: `sub` (user UUID), `sid`, `roles`, `mask`, `client_id`, `actor` (set on exchanged tokens),
`claims` (all claims). Methods: `has_perm(code)`, `has_role(*roles)`.

### SDK behaviour you should know

- **Until the first sync completes**, every request gets `503` (`StaleAuthState`): with no revocation state, a
  revoked token can't be told from a good one. With `state_path`, a restart loads the saved state and verifies
  immediately, even while the Auth Server is unreachable.
- **With `max_staleness_seconds` set**, requests get `503` after that long without contact. Unset (default), the
  server keeps working through an outage, and the 10-minute token lifetime is the limit on staleness.
- **A permission code the server can't map is denied**, never assumed. New permissions need no restart: the
  SDK refetches the map on `permissions.changed`, or when a token's `pv` is newer than its map.
- The sync loop never dies: network or Auth Server errors are logged and retried with exponential backoff
  (1 s doubling to 60 s, with jitter so a fleet doesn't reconnect in step), reset once the stream opens.
- On every (re)connect the SDK acknowledges its position, so a restarted process shows its true lag on the
  Downstream Sync page at once.
- **State file:** one per process. It records the issuer and app key, and a file saved for another issuer or app,
  or an unreadable one, is ignored (the process starts unsynced and takes a snapshot). If the Auth Server's
  database is reset, the server answers `409` to the old cursor and the SDK takes a fresh snapshot by itself.

---

## 5. Signing users in (browser apps)

Your browser app is a **public client** using Authorization Code + PKCE. It never sees a password: the Auth
Server hosts the login page, so one login covers every app (SSO).

### 5.1 Start the login

Create a PKCE pair and redirect the browser:

```
code_verifier  = 43–128 random characters [A-Za-z0-9-._~]
code_challenge = base64url(sha256(code_verifier)), no padding

GET https://auth.example.com/oauth/authorize
    ?response_type=code
    &client_id=anpr-web
    &redirect_uri=https://anpr.example.com/callback
    &scope=openid profile email
    &state=<random, check on return>
    &nonce=<random, check in the id_token>
    &code_challenge=<code_challenge>
    &code_challenge_method=S256
```

If the user already has an SSO session, the Auth Server redirects straight back. Otherwise it shows its login
page (password, then TOTP or security key if enabled) and then redirects back.

Optional: `prompt=none` (never show the login page; returns `error=login_required` instead), `prompt=login`
(force a fresh login), `max_age=<seconds>`.

### 5.2 Handle the callback

```
https://anpr.example.com/callback?code=...&state=...&iss=https://auth.example.com
```

Check `state` and `iss`. On `error=access_denied` the user has no role in your app.

### 5.3 Redeem the code

```http
POST /oauth/token
Content-Type: application/x-www-form-urlencoded

grant_type=authorization_code&client_id=anpr-web&code=...&redirect_uri=https://anpr.example.com/callback&code_verifier=...
```

```json
{
  "access_token": "<JWT, 10 min>",
  "token_type": "Bearer",
  "expires_in": 600,
  "scope": "email openid profile",
  "refresh_token": "<opaque>",
  "id_token": "<JWT>"
}
```

The code is single-use and expires in 60 seconds.

### 5.4 Call your API

```http
GET /vehicles
Authorization: Bearer <access_token>
```

### 5.5 Refresh before expiry

```http
POST /oauth/token
Content-Type: application/x-www-form-urlencoded

grant_type=refresh_token&client_id=anpr-web&refresh_token=<current>
```

- Refresh tokens **rotate**: store the new one each time.
- If the response has **no `refresh_token`**, another tab refreshed at the same moment. Keep the one you have.
- Reusing an old refresh token after a 10-second grace window is treated as theft and **ends the login**.
- A refresh token never outlives its login session (`SESSION_DAYS`, 14 by default).
- `invalid_grant` means the login has ended: send the user to 5.1 again.

### 5.6 Sign out

```http
POST /oauth/logout
Authorization: Bearer <access_token>
```

Ends this login everywhere (the user's other logins stay). Then drop your tokens. To end only the refresh token
family: `POST /oauth/revoke` with `client_id=anpr-web&token=<refresh_token>`.

### 5.7 Where to keep tokens

Don't put tokens in `localStorage`, where any injected script can read them. Prefer, in order:

1. **A backend-for-frontend**: your server runs the flow above and keeps the tokens, and the browser holds only
   an HttpOnly, SameSite cookie (this is how the Auth Server's own console works).
2. Keep them in memory only, and use `prompt=none` to get a new session silently after a page reload.

### 5.8 User profile

The `id_token` (and `GET /oauth/userinfo` with the access token) carry `sub`, and with the scopes:
`preferred_username`, `given_name`, `family_name` (`profile`) and `email` (`email`). Use `sub` as the stable
user id; usernames and emails can change.

---

## 6. Verifying an access token (any language)

Do this on every request. All of it is local; nothing calls the Auth Server.

### 6.1 Signature and standard claims

| Check | Rule |
|---|---|
| Algorithm | `ES256` only. Never take the algorithm from the token header |
| Key | `kid` from the header, looked up in the cached JWKS (`GET /.well-known/jwks.json`). Unknown `kid`: reload JWKS at most every 30 s, then reject |
| `typ` (header) | `at+jwt` |
| `iss` | equals your configured issuer exactly |
| `aud` | equals **your** app key (`ANPR`). A token for another app must be rejected |
| `exp` | integer, in the future |
| `token_use` | `user` (a user token) or `service` (see section 9) |
| `sub`, `sid`, `ver` | present; `ver` is an integer |

### 6.2 Claims of a user access token

```json
{
  "iss": "https://auth.example.com",
  "aud": "ANPR",
  "sub": "7f1c…-uuid",          // stable user id
  "sid": "c2a9…-uuid",          // login session
  "ver": 4,                      // this user's access version for ANPR
  "pm": "EgI",                   // permission mask
  "pv": 7,                       // permission map version
  "roles": ["Operator"],         // roles in ANPR only
  "client_id": "anpr-web",       // client that obtained the token
  "token_use": "user",
  "scope": "openid profile",
  "act": {"sub": "nvr-api", "app": "NVR"},   // only on exchanged tokens: the calling service
  "iat": 1762990000, "exp": 1762990600, "jti": "…"
}
```

### 6.3 Revocation checks (against your synced state)

Reject the token (401) when any of these is true:

| Condition | Comes from |
|---|---|
| `sid` is in the revoked sessions | `session.revoked` events, snapshot `revoked_sessions` |
| `sub` is disabled | `user.disabled` events, snapshot `users[].is_active` |
| `ver` < the user's minimum `ver` | `user.access_changed` / `user.disabled` events, snapshot `users[].ver` |
| the issuing client is revoked and `iat` ≤ its `revoked_at` (issuing client = `act.sub` if present, else `client_id`) | `client.revoked` events, snapshot `revoked_clients` |
| `kid` was revoked | `key.rotated` with `revoked: true` |

And refuse every request (503) until your first sync has completed.

### 6.4 Permissions

`pm` is an integer with one bit per permission, sent as **little-endian bytes in base64url without padding**.
JSON numbers above 2^53 would lose accuracy in JavaScript, so never decode it into a float.

```
"EgI"  ->  bytes 12 02  ->  0x0212 = 530  ->  bits 1, 4, 9
```

```python
import base64

def decode_mask(value: str) -> int:
    raw = base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
    return int.from_bytes(raw, "little")

def has_perm(mask: int, code: str, bits: dict[str, int]) -> bool:
    if mask & 1:                 # bit 0 is "*": full access
        return True
    bit = bits.get(code)
    return bit is not None and bool(mask >> bit & 1)   # unknown code: denied
```

```javascript
function decodeMask(value) {                     // BigInt, never Number
  const bin = atob(value.replace(/-/g, '+').replace(/_/g, '/'));
  let mask = 0n;
  for (let i = bin.length - 1; i >= 0; i--) mask = (mask << 8n) | BigInt(bin.charCodeAt(i));
  return mask;
}
```

Get the code-to-bit map with your service token, and refetch it when a token's `pv` is newer than the map's
`version` (at most every 10 s) or on `permissions.changed`:

```http
GET /v1/apps/ANPR/permission-map
Authorization: Bearer <service token with permissions.read>
```

```json
{ "version": 7, "permissions": [ {"code": "*", "bit": 0, "retired": false}, {"code": "vehicle.read", "bit": 1, "retired": false} ] }
```

Ignore retired permissions when building the map. Bits are never reused, so a cached map can't grant the wrong
permission.

---

## 7. Your service token

Your server authenticates as itself with the client credentials grant, to read events and the permission map:

```http
POST /oauth/token
Authorization: Basic base64(anpr-api:<client secret>)
Content-Type: application/x-www-form-urlencoded

grant_type=client_credentials
```

```json
{ "access_token": "<service JWT>", "token_type": "Bearer", "expires_in": 900, "scope": "events.read permissions.read" }
```

- Cache it and renew about 30 seconds before `expires_in` runs out.
- **Any 401** with it means the token is dead (its client changed, or its signing key was revoked): drop it, get
  a new one, retry once.
- The client may only read its own application's events and map (`403 wrong_application` otherwise).

---

## 8. Staying in sync: the event stream

### 8.1 Startup sequence

```
1. GET /.well-known/jwks.json                  cache the keys
2. GET /v1/apps/ANPR/permission-map            cache the bit map
3. if you have no saved cursor:
       GET /v1/events/ANPR/snapshot            replace the revocation state, cursor = snapshot.seq
       POST /v1/events/ANPR/ack {seq}
4. GET /v1/events/ANPR?after=<cursor>&instance_id=anpr-1     open the stream (loop forever)
```

### 8.2 Snapshot

```http
GET /v1/events/ANPR/snapshot
Authorization: Bearer <service token with events.read>
```

```json
{
  "seq": 121,
  "perm_map_version": 7,
  "users": [ {"sub": "7f1c…", "ver": 4, "is_active": true} ],
  "revoked_sessions": [ "c2a9…" ],
  "revoked_clients": [ {"client_id": "old-api", "version": 2, "revoked_at": 1762990000} ]
}
```

Replace your whole state with it: minimum `ver` per user, disabled users, revoked sessions, revoked clients.

### 8.3 The stream

```http
GET /v1/events/ANPR?after=121&instance_id=anpr-1
Authorization: Bearer <service token with events.read>
Accept: text/event-stream
```

`Last-Event-ID: 121` works instead of `after`. Frames:

```
id: 122
event: session.revoked
data: eyJhbGciOiJFUzI1NiIsInR5cCI6ImV2ZW50K2p3dCIs...

: keep-alive
```

Keep-alives arrive every 15 seconds; treat 45 seconds of silence as a dead connection and reconnect.

### 8.4 Handling one event

1. **Verify the `data` JWT**: ES256, header `typ` = `event+jwt`, `kid` in your JWKS (reload once if unknown),
   `iss` = issuer, `aud` = your app key, `exp` in the future. If it fails, drop the connection and reconnect.
2. Read `seq`, `type`, `payload` from its claims.
3. If `seq` ≤ your cursor, skip it (already applied).
4. Apply it (table below).
5. Set cursor = `seq`, persist your state, then acknowledge:

```http
POST /v1/events/ANPR/ack
Authorization: Bearer <service token>
Content-Type: application/json

{"instance_id": "anpr-1", "seq": 122}
```

| Event | Payload | Apply |
|---|---|---|
| `session.revoked` | `{"sid", "sub"}` | add `sid` to revoked sessions |
| `user.access_changed` | `{"users": [{"sub", "ver"}]}` | for each: min `ver` = max(current, `ver`); mark the user active |
| `user.disabled` | `{"users": [{"sub", "ver"}]}` | for each: min `ver` = max(current, `ver`); mark the user disabled |
| `client.revoked` | `{"client_id", "version", "revoked_at"}` | store it under `client_id` |
| `key.rotated` | `{"kid"}` or `{"kid", "revoked": true}` | reload JWKS; if `revoked`, also drop and blocklist the `kid` |
| `permissions.changed` | `{"version"}` | refetch the permission map |
| `members.changed` | `{}` or `{"sub"}` | nothing for verification; refresh a cached members or roles list (section 10) |

Unknown event types must be ignored (acknowledge them like any other), so new ones never break you.

Applying an event twice is harmless, so at-least-once delivery is safe.

### 8.5 Special answers

| You get | Do |
|---|---|
| `event: token.expired` (then the stream closes) | get a new service token, reconnect with your cursor |
| `409 snapshot_required` | your cursor is older than the event retention (7 days) or invalid: clear it, go to step 3 |
| `401` | get a new service token, reconnect |
| network error | wait about 2 seconds, reconnect with your cursor |

### 8.6 Persist your state

Save JWKS, the permission map, the cursor and the revocation state to disk after each event (write a temp file,
then rename). A server restarted during an Auth Server outage can then still verify tokens.

### 8.7 Monitoring

Your instance appears on the console's **Downstream Sync** page by `instance_id`: last ACK, lag behind the
latest event, and `ok`, `lagging` or `offline` (no contact for 60 seconds). Use a stable `instance_id` per
process, for example `anpr-1`, `anpr-2`.

---

## 9. Server-to-server calls

### 9.1 Acting as yourself (service token for another app)

NVR calls ANPR as NVR. In the console, add `ANPR` to the `nvr-api` client's **audiences**. Then:

```http
POST /oauth/token
Authorization: Basic base64(nvr-api:<secret>)

grant_type=client_credentials&audience=ANPR
```

NVR sends that token to ANPR, and ANPR verifies it:

```python
claims = await auth.verify_service(token)     # aud must be ANPR, token_use "service"
caller = claims["client_id"]                  # "nvr-api"
```

Without the SDK: the same signature and claim checks as section 6.1 with `token_use` = `service`, then reject it
if its `client_id` is in your revoked clients with `version` greater than the token's `ver`.

### 9.2 Acting for a user (token exchange)

ANPR holds Alice's ANPR token and needs to call NVR as Alice. In the console, add `NVR` to `anpr-api`'s
**audiences**. Then:

```http
POST /oauth/token
Authorization: Basic base64(anpr-api:<secret>)
Content-Type: application/x-www-form-urlencoded

grant_type=urn:ietf:params:oauth:grant-type:token-exchange
&subject_token=<Alice's ANPR access token>
&subject_token_type=urn:ietf:params:oauth:token-type:access_token
&audience=NVR
&scope=camera.read
```

```json
{ "access_token": "<JWT for NVR, 5 min>", "issued_token_type": "urn:ietf:params:oauth:token-type:access_token", "token_type": "Bearer", "expires_in": 300 }
```

- The subject token must have been issued **to your app** (`aud` = `ANPR`), and Alice must have a role in NVR.
- `scope` (permission codes of the target app) **narrows** the token: its permissions are the requested ones
  AND what Alice holds, and a role stays only if all its permissions remain. It can never widen. Without
  `scope`, the token carries everything Alice holds in NVR.
- The result carries `act: {"sub": "anpr-api", "app": "ANPR"}`. NVR verifies it like any user token (the SDK
  exposes it as `Principal.actor`). It can't be exchanged again.
- Exchange is audited as `token.exchange`.

---

## 10. Listing your app's users and roles

For screens like "give this camera to a user or a role", your server needs everyone who holds a role in your
app, including people who have never signed in to it. Give your server's client the **`users.read`** scope,
then:

```http
GET /v1/apps/SNVR/members?limit=200[&cursor=...][&q=...]     ->  {"items": [...], "next_cursor": ...}
GET /v1/apps/SNVR/roles                                        ->  [{"id", "name", "description", "permissions"}]
Authorization: Bearer <service token>
```

Full shapes are in [API.md, section 11](API.md#11-downstream-servers-events). With the SDK:

```python
members = await auth.list_all_members()
roles = await auth.roles()

@auth.on_change
async def refresh(event_type, payload):
    cache.members = await auth.list_all_members()
    cache.roles = await auth.roles()
```

Rules that keep your data right:

- **Key user grants by `sub`.** It's the `sub` claim in that user's tokens, so `principal.sub` matches it.
- **Key role grants by the role `id`, never its name.** An admin can rename a role; the id stays. Compare with
  the token's `roles` names through the cached roles list (`name` → `id`).
- **Refresh on `user.access_changed`, `user.disabled`, `members.changed`, and after a snapshot.** The SDK's
  `on_change` covers all four. Several events can arrive together, so debounce the refresh.
- **Show disabled members** (`is_active: false`) greyed out instead of dropping their grants.
- **Treat names and email as personal data**: cache only what your screens need.
- Your client sees only its own app (`403 wrong_application` otherwise) and can't change anything.

---

## 11. Failure behaviour

| Situation | Your server |
|---|---|
| Auth Server down | Keeps verifying with cached keys and state. Valid tokens work until they expire. New logins and refreshes fail |
| Event stream down | Runs on its last state, at most one access token lifetime (10 min) out of date. With `max_staleness_seconds`, refuses requests (503) after that limit |
| Restart during an outage | With saved state: verifies immediately. Without: 503 until the Auth Server is reachable |
| Signing key leaked | `key.rotated` with `revoked` arrives; tokens signed by that key are rejected at once |
| User's password changed | `session.revoked` for their other sessions (all sessions on an admin reset) within a second or two |
| User's roles changed in your app | `user.access_changed` with a higher `ver`; their older tokens for your app are rejected; other apps are unaffected |
| User disabled | `user.disabled`; every token of theirs is rejected |

---

## 12. Integration checklist

- [ ] Application, permissions, roles and user assignments created in the console
- [ ] Confidential client with `events.read` and `permissions.read`; secret stored in your secrets store
- [ ] Public client with the exact redirect URI (if there's a browser app)
- [ ] `AUTH_ISSUER` equals the Auth Server's `ISSUER` exactly
- [ ] SDK started in the app lifespan, or sections 6 to 8 implemented
- [ ] Every route protected by `current_user`, `require_perm` or `require_role` (deny by default)
- [ ] Permission checks use codes, never raw bit numbers
- [ ] `state_path` set and on persistent storage
- [ ] Stable `instance_id` per process
- [ ] `auth.health()` included in your health check
- [ ] Browser tokens kept out of `localStorage`
- [ ] The instance shows `ok` on the Downstream Sync page
- [ ] If you list members: `users.read` on the client, grants keyed by `sub` and role `id`, cache refreshed on `on_change`
