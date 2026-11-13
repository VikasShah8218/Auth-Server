# Architecture

How the Auth Server is built and why. For every endpoint see [API.md](API.md).

## 1. Goal

One system decides **who someone is** and **what they may do**. Every downstream server can then:

- trust a token **without calling the auth server** on each request
- learn about revocations **within seconds**
- keep working when the auth server is briefly down

## 2. Principles

| Principle | How it is applied |
|---|---|
| Standards first | OAuth 2.1 and OpenID Connect. All cryptography comes from proven libraries (`joserfc`, `cryptography`, `argon2-cffi`, `webauthn`) |
| Only this server can sign | ES256 key pairs. Downstream servers hold public keys only (JWKS) |
| Verify locally, revoke by push | A signature check needs no network call. Revocations arrive as signed events |
| Short-lived, audience-bound tokens | A token for app A is refused by app B. Access tokens live 10 minutes |
| Postgres is the source of truth | Redis holds only what can be lost: rate-limit counters and login challenges |
| Fail closed | Anything unknown, unverifiable, unlisted or too stale is denied |

## 3. System overview

```
    Browser / mobile apps                     Admin console (React, ../client)
            |                                          |
            | login, refresh                           | /bff cookie session
            v                                          v
+---------------------------------------------------------------------------+
|                   AUTH SERVER  (stateless, N replicas)                    |
|                                                                           |
|  identity        oauth / tokens / keys     applications / users     events|
|  login, MFA,     authorize, token,         clients, audit,          outbox|
|  SSO sessions    JWKS, exchange            policy                   SSE   |
+------+--------------------+----------------------+--------------------+---+
       |                    |                      |                    |
       v                    v                      v                    | signed events,
  PostgreSQL            Redis                MASTER_KEY                 | JWKS
  truth, outbox,        limits,              (encrypts private          |
  audit                 challenges            keys at rest)             v
                                         +-----------------------------------------+
                                         | DOWNSTREAM SERVERS (embed the Auth SDK)  |
                                         | verify JWT locally | follow event stream |
                                         | revocation cache   | ACK each event      |
                                         +-----------------------------------------+
```

It is a **modular monolith**: one deployable, one package per feature under `app/`. Splitting it into
services would add failure modes without adding value.

## 4. Project layout

The project follows the base structure: `main.py` at the root, one package per feature under `app/`, and
cross-cutting infrastructure (`settings/`, `database/`, `utilities/`) beside it.

| Module | Responsibility | Key files |
|---|---|---|
| `app/applications` | Applications, permission bits, roles, role-permission and user-role links, per-user-per-app versions | `services.py` (`bump_versions`, bit assignment, last-admin guard) |
| `app/users` | User admin, password hashing and rules | `utils.py` (Argon2), `services.py` |
| `app/identity` | Password login, TOTP and WebAuthn sign-in, SSO sessions and their revocation | `services.py` (sessions, `cleanup_tick`), `mfa.py`, `webauthn.py` |
| `app/account` | `/v1/me`: profile, password, sessions, MFA factors | `services.py` (step-up checks) |
| `app/oauth` | Authorization code + PKCE, refresh, client credentials, token exchange, revoke, userinfo, logout, discovery | `services.py` (flows) |
| `app/tokens` | Signing and verifying JWTs, user and service claims | `services.py`, `deps.py` |
| `app/keys` | Signing key lifecycle, KeyProvider, JWKS | `services.py` (`rotate_keys`, `key_rotation_tick`) |
| `app/clients` | OAuth client admin and its revocation events | `services.py` |
| `app/console` | Backend-for-frontend for the admin console | `services.py` (`claims_from_cookie`) |
| `app/events` | Outbox publisher, LISTEN/NOTIFY hub, SSE stream, ACK, snapshot, downstream status | `services.py`, `hub.py`, `stream.py` |
| `app/audit` | Insert-only audit trail | `services.py` (`record_audit`) |
| `app/security` | The access rules and the guard that enforces them | `policy.py`, `enforcement.py` |
| `app/dashboard`, `app/health` | Admin counts, probes | `router.py` |

Import direction stays one way: `router -> services -> models`. Models reference each other by name
(`"models.User"`), so models never import each other.

## 5. Access model

```
Application (key "ANPR")
 ├── Permission  code "vehicle.read"  bit 1     each permission owns a permanent bit
 ├── Permission  code "*"             bit 0     full access, created with every app
 └── Role "Operator" ── RolePermission ──> permissions
                └──── UserRole ──> User
UserAppState(user, app).version = the token's "ver"
```

- **Integer permissions.** A user's access to an app is one integer with their permission bits set. The token
  carries it as little-endian bytes in base64url (`pm`), because JSON numbers above 2^53 lose accuracy in
  JavaScript. Bits {1, 4, 9} → 530 → `"EgI"`. An app may have up to 1,024 bits.
- **Bits are never reused.** A deleted permission is retired and keeps its bit, so an old token can't gain a
  new meaning. Recreating the same code revives the same bit.
- **`pv`** is the app's permission map version. It rises on every map change, so the SDK knows when to refetch
  the code-to-bit map.
- **`ver`** is per user per app. Any change to what a user can do in an app raises it, which makes their tokens
  for that app stale, and only that app.
- Applications and users are **deactivated, never deleted**. Audit history and bits stay intact.
- At least one active AUTH administrator must always remain. The check locks the Admin role row, so two
  simultaneous removals can't both pass.

## 6. Identity and sessions

- **Login** checks the password with Argon2id in a worker thread. Every failure gets one generic message, and
  an unknown username spends the same time as a real check, so accounts can't be discovered.
- **Rate limits** count failures only: per IP, per (account, IP), and a 10x account-wide ceiling. A stranger
  can't lock someone out from another address. With Redis down, login is refused (fail closed).
- **MFA.** A TOTP factor protects nothing until its first valid code confirms it. Secrets are encrypted with
  AES-GCM under `MASTER_KEY`. A code is accepted once (conditional update on the last used step). Guessing is
  capped per challenge (the challenge is destroyed at the limit) and per user. WebAuthn uses a single-use
  challenge and a conditional sign-count update, so a cloned key can't race the real one.
- **SSO session.** A successful login creates a `Session` (its `public_id` is the token `sid`) and sets the
  HttpOnly `auth_sso` cookie (SameSite=Lax, because other apps redirect to `/oauth/authorize`). Only the
  cookie's SHA-256 hash is stored.
- **Revoking a session** revokes its refresh tokens, deletes its console session, and publishes
  `session.revoked` to every app that may hold its tokens. A password change ends the user's other sessions;
  an admin password reset, MFA reset or disable ends all of them.

## 7. Tokens

| Token | Lifetime | Format | Stored by the server |
|---|---|---|---|
| Access (user) | 10 min | ES256 JWT, `typ: at+jwt`, `token_use: user` | No |
| ID token | 10 min | ES256 JWT, `typ: JWT`, `aud` = client_id | No |
| Refresh | Up to the session's end, rotated on every use | Opaque random | Hash only |
| Service | 15 min | ES256 JWT, `token_use: service` | No |
| Exchanged | 5 min | ES256 JWT with `act` | No |
| Event | 5 min | ES256 JWT, `typ: event+jwt` | No |

User access token claims:

```
iss  issuer                     sid        login session (revocable on its own)
aud  the one target app key     ver        version for this user + app
sub  user public_id (UUID)      pm / pv    permission mask / map version
exp  expiry                     roles      role names in this app only
kid  signing key (header)       client_id  issuing client;  act: calling service (exchange only)
```

Rules:

- **Verification is strict.** Only ES256 is accepted whatever the header says, so `alg: none` and HMAC
  downgrades fail. `typ`, `iss`, `exp` and `aud` are checked. On this server, a token is also checked against
  live state: active user, unrevoked session, active app, current `ver`, active client.
- **Authorization code + PKCE (S256 only).** Codes are single-use (conditional update). A second use revokes
  everything the code issued. Redirect URIs must match exactly; before the URI is proven, errors are never
  redirected.
- **Refresh rotation.** The claim on a refresh token is one conditional update. A second use within
  `REFRESH_GRACE_SECONDS` (two open tabs) gets an access token only, with no new refresh token, so no hidden
  branch can start. A reuse after the window is treated as theft: the session ends and the event is audited.
- **Token exchange (RFC 8693)** needs an authenticated confidential client, a subject token issued to that
  client's own app, and a target app listed in the client's `audiences`. The AUTH app is never a target.
  Requested scope narrows permissions (requested AND held) and keeps a role only if all its permissions remain.
  It can never widen. An exchanged token can't be exchanged again.
- **Browsers hold no tokens.** The console uses a backend-for-frontend (section 10).

## 8. Signing keys

```
next ──rotate──> active ──rotate──> retired ──(longest token lifetime + 5 min)──> expired
                    └──────── revoke (leak) ────────> revoked   (out of JWKS at once)
```

- JWKS publishes `next`, `active` and `retired` keys. A `next` key is published before it signs anything, so
  downstream servers already hold it when it becomes active.
- Private keys sit behind a `KeyProvider`. `LocalKeyProvider` encrypts them with AES-GCM under `MASTER_KEY`,
  bound to their `kid`. A Vault provider can replace it.
- Rotation and revocation take a Postgres advisory lock, publish `key.rotated`, and `NOTIFY auth_keys` so every
  replica drops its key cache immediately.
- `key_rotation_tick` keeps an active and a next key, expires retired keys, and rotates every
  `KEY_ROTATION_DAYS`.

## 9. Revocation and downstream sync

This is the core of the system: how every downstream server stays in step.

```
 Admin / logout action
        |
        v
 Postgres transaction: change the data + audit record + OUTBOX row     (atomic)
        |                       per-app counter row gives a gapless seq
        v
 NOTIFY auth_events  (held by Postgres until commit)
        |
        v
 every replica's EventHub wakes its SSE streams
        |
        v
 SSE frame: id=seq, event=type, data=signed event JWT ──> downstream applies it ──> POST ack(seq)
        ^                                                                               |
        |                                                                               v
 reconnect with Last-Event-ID / after=  (replay what was missed)       cursor per client + instance;
 cursor older than retention -> 409 snapshot_required -> snapshot      lag shown in the console
```

- **Why an outbox:** a change can never be saved without its event, or the reverse. A rolled-back change
  wakes nobody.
- **Gapless order:** the per-app counter row is updated in the publishing transaction. When one change
  affects several apps, counters are locked in `app_id` order, so two changes can't deadlock.
- **Why SSE:** the downstream server connects outward, so it works through firewalls and needs no broker.
- **Delivery can't be lost:** NOTIFY is only a wake-up. Streams read the outbox themselves and also poll every
  5 seconds.
- **Stream lifetime:** a stream ends when its service token expires or its client is revoked, with a
  `token.expired` event telling the consumer to reconnect.
- **Snapshot:** users' current versions and status, revoked sessions, and revoked clients, plus the `seq` to
  resume from. Its `seq` is read first, so anything landing during the read is replayed again, harmlessly.
- A revocation doesn't wait for ACKs. The stream makes it fast; the short access token lifetime is the
  guaranteed upper limit.

Event types:

| Type | Payload | Published when |
|---|---|---|
| `user.access_changed` | `{users: [{sub, ver}]}` | roles or role permissions change, a role is renamed or deleted, a permission is retired, a user is re-enabled |
| `user.disabled` | `{users: [{sub, ver}]}` | a user is disabled |
| `session.revoked` | `{sid, sub}` | logout, session end, password change or reset, MFA reset, refresh token reuse |
| `client.revoked` | `{client_id, version, revoked_at}` | a client is disabled, its scopes or audiences change, or its secret rotates |
| `key.rotated` | `{kid}` or `{kid, revoked: true}` | key rotation or revocation (sent to every app) |
| `permissions.changed` | `{version}` | a permission is created, revived or retired |

## 10. Admin console (backend-for-frontend)

The console is an ordinary PKCE client (`auth-console`) of this server's own OAuth flow, but the browser never
sees a token:

1. `GET /bff/login` stores state and the PKCE verifier in Redis, sets a short-lived binding cookie, and
   redirects to `/oauth/authorize`.
2. `GET /bff/callback` checks state against the binding cookie (so an attacker can't hand a victim their own
   login), redeems the code server-side, and stores the access and refresh tokens encrypted in `bff_sessions`.
   The browser gets one opaque `auth_console` cookie (HttpOnly, SameSite=Strict).
3. Every API call with that cookie is resolved by the policy guard through `claims_from_cookie`, which renews
   the token when it expires or turns stale (a role change takes effect without a new login).
4. Every write must carry the `X-CSRF-Token` header from `GET /bff/session`.

## 11. Access policy

All endpoint rules live in one file, `app/security/policy.py`:

```
"GET /health/live":       FREE                  no token
"POST /oauth/token":      SelfGuarded("...")    the route authenticates itself
"* /v1/me*":              AUTH                  any valid token issued for AUTH
"* /v1/admin/*":          ADMIN                 Admin role on AUTH
anything unlisted:        DEFAULT_RULE = ADMIN
```

One guard (`policy_guard`) is installed as an app-level FastAPI dependency, so it runs for every route,
including routes added later. It is fail-closed:

- A route it can't identify is denied. Routers must carry their full prefix, because a `prefix=` given to
  `include_router()` is invisible to the guard.
- Startup fails if the guard isn't installed, if a policy key matches no route, or if a required public
  endpoint resolves to anything but FREE or SelfGuarded.
- Delegated (exchanged) tokens are refused: this API manages access itself.
- `python -m app.security.policy_audit` prints the effective rule of every route and exits 1 if any route is on
  the default rule, so it works as a CI gate.

## 12. Background jobs

Run from `main.py`'s lifespan with `run_periodic`, every `JOB_INTERVAL_SECONDS`. Each job runs inside
`run_exclusive`, which takes a Postgres advisory lock for its transaction, so on several replicas only one
runs it at a time and the others skip.

| Job | Lock | Does |
|---|---|---|
| `cleanup_tick` | 725101 | Deletes expired authorization codes, console sessions, refresh tokens and sessions. Revoked sessions stay until they would have expired, because snapshots must list them |
| `prune_outbox_tick` | 725102 | Deletes events older than `EVENT_RETENTION_DAYS` |
| `key_rotation_tick` | 725103 | Key upkeep and scheduled rotation (section 8) |
| `downstream_report_tick` | 725104 | Logs downstream instances that are lagging or offline |

## 13. Failure behaviour

| Failure | Result |
|---|---|
| Auth server down | Existing tokens keep working downstream until expiry. New logins and refreshes fail |
| Event stream down | Downstream runs stale for at most one access token lifetime. High-risk servers can deny after a set staleness (SDK `max_staleness_seconds`) |
| Redis down | Tokens still verify. Login, MFA and console sign-in refuse (fail closed). Readiness stays up |
| Postgres down | Readiness reports 503. Token issuing stops; downstream verification continues |
| Signing key leaked | `DELETE /v1/admin/keys/{kid}`: out of JWKS, `key.rotated` with `revoked`, every replica and downstream server drops the kid at once |
| Unhandled error | 500 with a generic `internal_error`. The real error stays in the log only |

## 14. Security measures

- Startup fails on a missing or weak `MASTER_KEY`, `CORS_ORIGINS: ["*"]`, and, in production, a default
  database password or a non-https `ISSUER`. Validation errors never print the rejected secret.
- Secrets at rest: signing keys, TOTP secrets and console tokens are AES-GCM encrypted with a per-purpose
  context, so a ciphertext copied to another row won't decrypt. Passwords use Argon2id; long random values
  (session cookies, refresh tokens, codes, client secrets) are stored as SHA-256 hashes.
- The audit table is insert only: a database trigger rejects UPDATE, DELETE and TRUNCATE. Every change writes
  its audit record in the same transaction.
- Security headers on every response (`nosniff`, `DENY` framing, `no-referrer`, HSTS in production), set by a
  pure ASGI middleware so the SSE stream isn't buffered. `/docs` and `/openapi.json` are off in production.
- Version 1 limits: all clients are first-party (no consent screen); redirect URIs must be https or http on
  localhost; bearer logout accepts a token for any app, so any app holding a user's token can end that login;
  exchange has no per-client ceiling beyond `audiences`.

## 15. Configuration

All settings come from `.env` through `settings/settings.py` (see `.env.example`).

| Group | Settings |
|---|---|
| Server | `ENVIRONMENT` (default `production`), `HOST`, `PORT`, `LOG_LEVEL`, `CORS_ORIGINS`, `FORWARDED_ALLOW_IPS` |
| Database | `DB_HOST`, `DB_PORT`, `DB_USER`, `DB_PASSWORD`, `DB_NAME`, or `DATABASE_URL` |
| Redis | `REDIS_URL` (required) |
| Secrets | `MASTER_KEY` (required, 32 random bytes, base64url) |
| Issuer | `ISSUER`, `AUTH_APP_KEY`, `LOGIN_PAGE_PATH` |
| Lifetimes | `ACCESS_TOKEN_MINUTES` 10, `SERVICE_TOKEN_MINUTES` 15, `EXCHANGE_TOKEN_MINUTES` 5, `AUTH_CODE_SECONDS` 60, `REFRESH_GRACE_SECONDS` 10, `SESSION_DAYS` 14 |
| Keys and events | `KEY_ROTATION_DAYS` 30, `EVENT_RETENTION_DAYS` 7, `DOWNSTREAM_LAG_SECONDS` 60 |
| Limits | `LOGIN_LIMIT_PER_ACCOUNT` 5, `LOGIN_LIMIT_PER_IP` 30, `TOKEN_LIMIT_PER_IP` 120, `RATE_WINDOW_SECONDS` 900, `MFA_MAX_ATTEMPTS` 5, `MFA_CHALLENGE_SECONDS` 300 |
| Jobs | `RUN_JOBS` true, `JOB_INTERVAL_SECONDS` 60 |

## 16. Data model

| Table | Module | Key fields |
|---|---|---|
| `applications` | applications | `key`, `name`, `is_active`, `perm_map_version` |
| `permissions` | applications | `app`, `code`, `bit`, `retired_at`. Unique (`app`, `code`) and (`app`, `bit`) |
| `roles`, `role_permissions`, `user_roles` | applications | join tables, unique pairs |
| `user_app_states` | applications | `user`, `app`, `version` (the `ver` claim) |
| `users` | users | `public_id` (the `sub`), `username`, `email`, `password_hash`, `is_active`, `is_superuser` |
| `mfa_factors` | identity | `user`, `type` (totp / webauthn), `encrypted_secret`, `last_used_step`, `credential_id`, `sign_count`, `confirmed_at` |
| `sessions` | identity | `public_id` (the `sid`), `token_hash`, `auth_time`, `amr`, `ip`, `expires_at`, `revoked_at` |
| `oauth_clients` | clients | `client_id`, `app`, `type`, `secret_hash`, `redirect_uris`, `scopes`, `audiences`, `version` |
| `authorization_codes` | oauth | `code_hash`, `client`, `session`, `family_id`, `pkce_challenge`, `redirect_uri`, `expires_at`, `used_at` |
| `refresh_tokens` | oauth | `token_hash`, `family_id`, `session`, `client`, `expires_at`, `used_at`, `revoked_at` |
| `signing_keys` | keys | `kid`, `encrypted_private_key`, `public_jwk`, `status`, `activated_at`, `not_after` |
| `bff_sessions` | console | `handle_hash`, `session`, encrypted tokens, `csrf_token`, `expires_at` |
| `app_event_counters`, `outbox_events` | events | per-app `last_seq`; (`app`, `seq`) unique |
| `downstream_cursors` | events | `client`, `instance_id`, `last_acked_seq`, `last_seen_at` |
| `audit_logs` | audit | `actor`, `action`, `target`, `app`, `details`, `ip`, `created_at`. Insert only |
