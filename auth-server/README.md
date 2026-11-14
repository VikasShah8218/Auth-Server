# Auth Server

Central authentication and authorization for every downstream server: one login (OAuth 2.1 / OpenID Connect),
one place that decides what each user may do, and revocations pushed to downstream servers within seconds.

**Stack:** Python 3.13, FastAPI, Tortoise ORM + Aerich, PostgreSQL, Redis, joserfc (ES256), Argon2, TOTP, WebAuthn.

- How it works: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)
- Every endpoint: [docs/API.md](docs/API.md)
- Integrating a downstream server (ANPR, NVR, ...): [docs/INTEGRATION.md](docs/INTEGRATION.md)

## Run locally

You need PostgreSQL and Redis running.

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements-dev.txt

copy .env.example .env          # then set DB_PASSWORD and MASTER_KEY
createdb auth
createdb auth_test

aerich upgrade                  # apply migrations
py cli.py create-admin --username admin --email you@example.com
py main.py                      # http://localhost:8000/docs
```

The React console (`../client`, `npm run dev`) runs on port 5181 and proxies the API to port 8000.

## Commands

| Command | What it does |
|---|---|
| `py main.py` | Runs the server, including the background jobs (`RUN_JOBS`) |
| `py cli.py create-admin --username <name>` | Creates the first administrator. Works only once |
| `py cli.py export-openapi` | Writes `../client/openapi/auth.json` for the client's generated types |
| `python -m app.security.policy_audit` | Prints the access rule of every route. Exits 1 if any is on the default rule |
| `pytest` | Runs the tests against `TEST_DATABASE_URL`, whose name must end in `_test` |
| `aerich migrate --name <change>` | Generates a migration after a model change |
| `aerich upgrade` | Applies migrations |

## Project layout

```
auth-server/
├── main.py            app factory, lifespan (DB, keys, event hub, background jobs), routers
├── cli.py             create-admin, export-openapi
├── app/               one package per feature: models / schemas / router / services / utils
│   ├── applications/  apps, permission bits, roles, members
│   ├── users/         user admin, passwords
│   ├── identity/      login, MFA, WebAuthn sign-in, SSO sessions
│   ├── account/       /v1/me self-service
│   ├── oauth/         authorize, token, revoke, userinfo, logout, discovery
│   ├── tokens/        JWT signing and verification
│   ├── keys/          signing key lifecycle and admin
│   ├── clients/       OAuth client admin
│   ├── console/       admin console backend-for-frontend (/bff)
│   ├── events/        outbox, SSE stream, ACK, snapshot, downstream status
│   ├── audit/         insert-only audit trail
│   ├── dashboard/     admin stats
│   ├── health/        liveness and readiness
│   └── security/      policy.py (the access rules), enforcement.py (the guard)
├── settings/          settings.py: validated config from .env
├── database/          config.py: TORTOISE_ORM for the app and Aerich
├── utilities/         crypto, redis, rate limits, masks, errors, pagination, middleware
├── migrations/        Aerich migrations
├── tests/             pytest suite (real Postgres and Redis)
└── docs/
```

## Adding a downstream server

1. In the console, create an application and its permissions.
2. Create a confidential client for the server with the scopes `events.read` and `permissions.read`. Save the
   secret: it's shown only once.
3. If the server has a browser app, create a public client with its redirect URI.
4. Add the Auth SDK (`../sdk`).

## Operations

- **Signing keys** rotate every `KEY_ROTATION_DAYS` (background job). Rotate early with
  `POST /v1/admin/keys/rotate`. For a leaked key, `DELETE /v1/admin/keys/{kid}`: its tokens stop working at once.
- **MASTER_KEY** encrypts signing keys, TOTP secrets and console tokens. Back it up separately from the
  database: replacing it makes them unreadable.
- **Several replicas** need nothing extra. Each listens to Postgres for events, and each background job takes
  an advisory lock, so it runs on one replica at a time. Set `RUN_JOBS=false` to keep jobs off a replica.
- **Behind a proxy**, set `FORWARDED_ALLOW_IPS` to the proxy's address, or rate limits and audit records see
  the proxy instead of the client.
- **Access rules** live in `app/security/policy.py`. A new route is admin-only until it has its own line.
  Routers carry their full prefix (`APIRouter(prefix="/v1/x")`); never pass `prefix=` to `include_router()`.
