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

The client needs the scopes `events.read` and `permissions.read`.

| Dependency | Requires |
|---|---|
| `auth.current_user` | Any valid token for this application |
| `auth.require_perm("a.read", "b.write")` | Every listed permission |
| `auth.require_role("Admin", "Operator")` | At least one listed role |
| `auth.current_service` | A service token for this application (server-to-server); returns its claims |

Outside FastAPI, call `await auth.verify(token)`. It returns a `Principal` with `has_perm()` and `has_role()`, or raises `AuthError` (answer 401) or `StaleAuthState` (answer 503).

For a call from another server, use `await auth.verify_service(token)`.

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
