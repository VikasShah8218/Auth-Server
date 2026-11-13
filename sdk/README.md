# Auth SDK

Everything a downstream server needs to trust the Auth Server. Verification is local, so a request to your server never calls the auth server.

## Use it

```bash
pip install -e path/to/sdk
```

```python
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from auth_sdk import AuthSDK, Principal

auth = AuthSDK(
    issuer="https://auth.example.com",
    app_key="ANPR",
    client_id="anpr-api",
    client_secret="...",
    state_path="/var/lib/anpr/auth-state.json",
)


@asynccontextmanager
async def lifespan(_: FastAPI):
    await auth.start()
    yield
    await auth.stop()


app = FastAPI(lifespan=lifespan)


@app.get("/vehicles")
async def vehicles(user: Principal = Depends(auth.require_perm("vehicle.read"))):
    return {"sub": user.sub}
```

The client needs the scopes `events.read` and `permissions.read`. Add `users.read` to list your app's members
and roles (below); without it everything else works as before.

| Dependency | Requires |
|---|---|
| `auth.current_user` | Any valid token for this application |
| `auth.require_perm("a.read", "b.write")` | Every listed permission |
| `auth.require_role("Admin", "Operator")` | At least one listed role |
| `auth.current_service` | A service token for this application (server-to-server); returns its claims |

Outside FastAPI, call `await auth.verify(token)`. It returns a `Principal` with `has_perm()` and `has_role()`, or raises `AuthError` (answer 401) or `StaleAuthState` (answer 503).

For a call from another server, use `await auth.verify_service(token)`.

## Members and roles

For screens like "give this camera to a user or a role" (scope `users.read`):

| Method | Returns |
|---|---|
| `await auth.members(q=None, limit=200, cursor=None)` | One page: `{"items": [...], "next_cursor"}`. Each item has `sub`, `username`, `given_name`, `family_name`, `email`, `is_active`, `roles: [{"id", "name"}]` |
| `await auth.list_all_members(q=None)` | Every member, following the cursor |
| `await auth.roles()` | `[{"id", "name", "description", "permissions": [codes]}]` |
| `auth.on_change(callback)` | Calls `callback(event_type, payload)` (sync or async, in the background) after `user.access_changed`, `user.disabled`, `members.changed` and a snapshot. Usable as a decorator |
| `auth.members_version` | Rises at the same moments, for code that polls |

```python
@auth.on_change
async def refresh(event_type, payload):
    cache.members = await auth.list_all_members()
    cache.roles = await auth.roles()
```

Key grants by the member's `sub` (it equals `principal.sub`) and by the role's `id`, never its name: a role
can be renamed, its id stays. Without `users.read` these calls raise `MissingScope`.

## What it does for you

- Verifies tokens with cached public keys: signature, issuer, audience, expiry and type.
- Follows the event stream, applies revocations within seconds, and acknowledges each event.
- Resumes where it stopped after a disconnect, and falls back to a snapshot if it's too far behind.
- Keeps the permission map current, so new permissions need no restart.
- Keeps running through Redis and network failures.

## Options

| Option | Default | Effect |
|---|---|---|
| `state_path` | None | Saves keys and revocations to a file. Without it, a server restarted during an outage can't verify anything until the auth server returns |
| `max_staleness_seconds` | None | Denies requests after this long without contact. Use it on high-risk servers. When unset, a server keeps working during an outage, and access tokens expiring is the limit on staleness |
| `instance_id` | Saved in `state_path`, else random | Names this process on the Downstream Sync page. Set it to something stable |
| `api_url` | `issuer` | Where to reach the Auth Server when that differs from its public `ISSUER` (for example `http://auth:8000` on a private network). `issuer` itself must equal the server's `ISSUER` exactly |
| `leeway_seconds` | 30 | Clock drift tolerated when checking expiry |

`auth.health()` reports the connection state, the cursor and the seconds since last contact. Include it in your health check.

`state_path` is one file per process. A file saved for another issuer or application, or an unreadable one, is
ignored and the SDK resyncs from a snapshot.

## Test

```bash
python -m unittest discover -s tests      # or: pytest
```

The tests run against a fake Auth Server that signs with real ES256 keys: verification, every event type,
forged tokens and events, clock leeway, staleness, state files, service tokens and the FastAPI dependencies.
