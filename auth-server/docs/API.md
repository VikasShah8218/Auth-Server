# API Reference

Every endpoint of the Auth Server. For how the pieces fit together see [ARCHITECTURE.md](ARCHITECTURE.md).
Integrating a downstream server (ANPR, NVR, ...) step by step: [INTEGRATION.md](INTEGRATION.md).
Interactive docs are served at `/docs` outside production.

## Conventions

### Authentication

Each endpoint lists one of these. The rules live in `app/security/policy.py`.

| Label | Meaning |
|---|---|
| **Public** | No credentials |
| **User** | A user access token issued for the AUTH app, as `Authorization: Bearer <token>`, or the console cookie |
| **Admin** | As User, and the token must hold the `Admin` role on AUTH |
| **Client** | OAuth client authentication: HTTP Basic `client_id:client_secret` (`client_secret_basic`), the same in the form (`client_secret_post`), or `client_id` alone for a public client |
| **Service** | A service token (client credentials grant) as `Authorization: Bearer`, with the named scope. The client may only read its own application |
| **SSO cookie** | The `auth_sso` cookie set by a successful login |
| **Console cookie** | The `auth_console` cookie. Writes also need the `X-CSRF-Token` header |

Delegated (exchanged) tokens are refused everywhere on this API.

### Errors

Every endpoint except the OAuth token endpoints answers errors as:

```json
{ "detail": { "code": "invalid_credentials", "message": "Incorrect username or password" } }
```

The token, revoke and authorize endpoints use the OAuth shape (RFC 6749):

```json
{ "error": "invalid_grant", "error_description": "The refresh token is not valid" }
```

Request validation errors (wrong types, patterns) are FastAPI's standard `422` with a list in `detail`.

Common codes:

| Status | Code | When |
|---|---|---|
| 401 | `not_authenticated` | No credentials (carries `WWW-Authenticate: Bearer`) |
| 401 | `invalid_token` | Bad signature, wrong type or issuer, expired, or revoked |
| 403 | `insufficient_role` / `insufficient_permission` | The token lacks the required role or permission |
| 403 | `wrong_application` | The token was issued for another application |
| 403 | `delegated_token` | An exchanged token was used on this API |
| 403 | `policy_unresolved` | The guard couldn't identify the route (fail closed) |
| 403 | `csrf_failed` | A console write without a valid `X-CSRF-Token` |
| 404 | `not_found` | The named resource doesn't exist |
| 409 | `protected` | The change would break a protected object (AUTH app, Admin role, `*` permission) |
| 409 | `last_admin` | The change would leave no active AUTH administrator |
| 429 | `too_many_attempts` | A rate limit was hit. `Retry-After` gives the seconds to wait |
| 503 | `temporarily_unavailable` | Redis is down, so a sign-in step that needs it is refused |
| 500 | `internal_error` | Unexpected error. Details stay in the server log |

### Pagination

List endpoints marked *paged* take `?limit=` (1 to 200, default 50) and `?offset=` (default 0), and answer:

```json
{ "items": [ ... ], "total": 123 }
```

### Identifiers

- Users and sessions are addressed by their UUID `public_id`. Integer keys never leave the server.
- Applications are addressed by `key`: 2 to 32 characters, `A-Z 0-9 _`, starting with a letter. Input is
  upper-cased (`anpr` becomes `ANPR`).
- Permission codes are lower-case dotted names, for example `vehicle.read`.
- Usernames are 3 to 64 characters of `a-z 0-9 . _ -`, stored lower-case.

### Passwords

At least 12 characters, and must not contain the username (`422 weak_password`).

---

## 1. Health

### `GET /health/live`
**Public.** The process is running. Never touches a dependency.

`200` `{"status": "alive"}`

### `GET /health/ready`
**Public.** Whether this replica can serve traffic. Only the database decides; Redis is reported.

`200` `{"status": "ready", "database": "up", "redis": "up"}`
`503` `{"status": "unavailable", "database": "down", "redis": "up"}`

---

## 2. Discovery

### `GET /.well-known/openid-configuration`
**Public.** The OpenID Connect discovery document: issuer, endpoint URLs, `grant_types_supported`
(`authorization_code`, `refresh_token`, `client_credentials`, token exchange), `code_challenge_methods_supported`
`["S256"]`, `id_token_signing_alg_values_supported` `["ES256"]`, scopes and claims.

### `GET /.well-known/jwks.json`
**Public.** The public signing keys (`next`, `active` and `retired`). Cached for 60 seconds.

```json
{ "keys": [ { "kty": "EC", "crv": "P-256", "x": "...", "y": "...", "kid": "...", "use": "sig", "alg": "ES256" } ] }
```

---

## 3. Identity (sign-in)

### `POST /v1/identity/login`
**Public.** Password sign-in.

```json
{ "username": "alice", "password": "a-long-enough-pass" }
```

Without MFA: `200` `{"status": "authenticated", "challenge": null, "methods": []}` and the `auth_sso` cookie is set.

With MFA: `200` `{"status": "mfa_required", "challenge": "<opaque>", "methods": ["totp", "webauthn"]}`. The
challenge lasts `MFA_CHALLENGE_SECONDS` (300).

| Error | When |
|---|---|
| `401 invalid_credentials` | Wrong username or password, or a disabled user (one message for all) |
| `429 too_many_attempts` | Too many failures for this IP, this account from this IP, or this account overall |
| `503 temporarily_unavailable` | Redis is down |

### `POST /v1/identity/mfa/verify`
**Public.** Finish sign-in with a TOTP code.

```json
{ "challenge": "<from login>", "code": "123456" }
```

`200` `{"status": "authenticated", ...}` and the `auth_sso` cookie.
Errors: `401 invalid_code`, `401 mfa_challenge_expired` (expired, or destroyed after `MFA_MAX_ATTEMPTS` guesses), `429`.

### `POST /v1/identity/webauthn/options`
**Public.** WebAuthn assertion options for the user behind an MFA challenge.

```json
{ "challenge": "<from login>" }
```

`200` `PublicKeyCredentialRequestOptions` JSON, to pass to `navigator.credentials.get()`.
Errors: `401 invalid_credential` (no security key), `401 mfa_challenge_expired`.

### `POST /v1/identity/webauthn/verify`
**Public.** Finish sign-in with a security key.

```json
{ "challenge": "<from login>", "credential": { "id": "...", "rawId": "...", "response": { ... }, "type": "public-key" } }
```

`200` `{"status": "authenticated", ...}` and the `auth_sso` cookie.
Errors: `401 invalid_credential`, `401 mfa_challenge_expired`, `429`.

---

## 4. OAuth 2.1 / OpenID Connect

### `GET /oauth/authorize`
**SSO cookie.** Starts the authorization code flow.

| Query | Required | Notes |
|---|---|---|
| `response_type` | yes | `code` |
| `client_id` | yes | an active client of an active app |
| `redirect_uri` | yes | exact match with a registered URI |
| `code_challenge`, `code_challenge_method` | yes | PKCE, `S256` only |
| `scope` | no | e.g. `openid profile email` |
| `state`, `nonce` | no | returned / put in the ID token |
| `prompt` | no | `none` (never show login) or `login` (force a new login) |
| `max_age` | no | seconds; an older login must sign in again |

Outcomes:

- Unknown client or unregistered redirect URI: `400` JSON error, **no redirect** (it would be an open redirect).
- No or stale SSO session: `302` to `LOGIN_PAGE_PATH?return_to=/oauth/authorize?...`; with `prompt=none`,
  `302` back with `error=login_required`.
- The user has no role in the client's app: `302` back with `error=access_denied`.
- Success: `302` to `redirect_uri?code=...&state=...&iss=<issuer>`. The code is single-use and lasts
  `AUTH_CODE_SECONDS` (60).

Other errors redirect back with `error=` `unsupported_response_type`, `invalid_request` (no PKCE) or `invalid_scope`.

### `POST /oauth/token`
**Client.** Form-encoded (`application/x-www-form-urlencoded`). Responses carry `Cache-Control: no-store`.

**Authorization code**

```
grant_type=authorization_code&code=...&redirect_uri=...&code_verifier=...&client_id=...
```

```json
{
  "access_token": "<JWT, 10 min>",
  "token_type": "Bearer",
  "expires_in": 600,
  "scope": "openid profile",
  "refresh_token": "<opaque>",
  "id_token": "<JWT, when scope has openid>"
}
```

A second use of a code fails and revokes everything that code issued.

**Refresh**

```
grant_type=refresh_token&refresh_token=...&client_id=...[&scope=<narrower>]
```

Same response with a new refresh token (rotation). Within `REFRESH_GRACE_SECONDS` of a previous use (two tabs),
the response has **no `refresh_token`**: keep the one you hold. A reuse after the window ends the session.
`scope` can narrow, never widen (`invalid_scope`).

**Client credentials** (confidential clients)

```
grant_type=client_credentials[&scope=events.read permissions.read][&audience=ANPR]
```

```json
{ "access_token": "<service JWT, 15 min>", "token_type": "Bearer", "expires_in": 900, "scope": "events.read permissions.read" }
```

`audience` defaults to `AUTH`; another app must be in the client's `audiences` (`invalid_target`).

**Token exchange** (RFC 8693, confidential clients)

```
grant_type=urn:ietf:params:oauth:grant-type:token-exchange
&subject_token=<user access token issued to this client's app>
&subject_token_type=urn:ietf:params:oauth:token-type:access_token
&audience=<target app key, listed in the client's audiences>
[&scope=vehicle.read report.export]
```

```json
{ "access_token": "<JWT with act, 5 min>", "issued_token_type": "urn:ietf:params:oauth:token-type:access_token", "token_type": "Bearer", "expires_in": 300 }
```

`scope` lists permission codes and narrows the token to them; a role stays only if all its permissions remain.

OAuth errors:

| Error | Status | When |
|---|---|---|
| `invalid_client` | 401 | Client authentication failed (also rate limited per IP) |
| `invalid_grant` | 400 | Bad, expired, reused or foreign code / refresh token / subject token |
| `invalid_scope` | 400 | Scope not allowed, widened, or beyond what the user holds |
| `invalid_target` | 400 | Audience not allowed for this client |
| `unauthorized_client` | 400 | A public client used client credentials or exchange |
| `invalid_request` | 400 | Missing or wrong parameters |
| `unsupported_grant_type` | 400 | Any other grant |

### `POST /oauth/revoke`
**Client.** RFC 7009. Form: `token=<refresh token>`. Revokes it and its whole family.
Always `200` for an authenticated client, even for an unknown token.

### `GET /oauth/userinfo`
**Bearer user access token for any application.**

`200` `{"sub": "<uuid>", "preferred_username": "...", "given_name": "...", "family_name": "...", "email": "..."}`
(profile claims with scope `profile`, email with scope `email`).

### `POST /oauth/logout`
**Bearer user access token for any application, or the SSO cookie.** Ends that one login; the user's other
logins are untouched. Without a token the `auth_sso` cookie is cleared. `204`.

---

## 5. Console (backend-for-frontend)

### `GET /bff/login`
**Public.** Starts the console sign-in: `302` to `/oauth/authorize` with PKCE, and a short-lived
`auth_console_state` binding cookie.

### `GET /bff/callback`
**State + PKCE.** The authorize redirect target. On success: `302` to `/` with the `auth_console` cookie
(HttpOnly, SameSite=Strict). On failure: `302` to `LOGIN_PAGE_PATH?error=invalid_state | invalid_code | <oauth error>`.

### `GET /bff/session`
**Console cookie.** What the console needs at startup.

```json
{
  "user": { "public_id": "...", "username": "admin", "email": "...", "first_name": null, "last_name": null },
  "roles": ["Admin"],
  "is_admin": true,
  "csrf_token": "<send as X-CSRF-Token on every write>"
}
```

`401 not_authenticated` without a live console session.

### `POST /bff/logout`
**Console cookie + `X-CSRF-Token`.** Clears the console and SSO cookies and ends the SSO session. `204`.
Without a console session it changes nothing.

---

## 6. My account

All **User**. Operate on the signed-in user.

### `GET /v1/me`
Profile and access in every application.

```json
{
  "public_id": "...", "username": "alice", "email": "...", "first_name": "...", "last_name": "...",
  "is_active": true, "created_at": "...", "updated_at": "...",
  "applications": [
    { "app_key": "ANPR", "app_name": "Anpr", "roles": [{ "id": 3, "name": "Operator", "description": null }],
      "permissions": ["vehicle.read"],
      "bits": [ { "code": "*", "bit": 0, "retired": false, "held": false },
                { "code": "vehicle.read", "bit": 1, "retired": false, "held": true } ] }
  ]
}
```

### `POST /v1/me/password`
`{"current_password": "...", "new_password": "..."}` → `204`. The user's other sessions end.
Errors: `401 invalid_credentials`, `422 weak_password`, `429`.

### `GET /v1/me/sessions`
Live sessions, newest first.

```json
[ { "id": "<uuid>", "ip": "...", "user_agent": "...", "amr": ["pwd", "otp"], "auth_time": "...", "expires_at": "...", "current": true } ]
```

### `DELETE /v1/me/sessions/{session_id}`
End one of my sessions. `204`, `404`.

### `GET /v1/me/mfa`
Confirmed factors: `[{"id": "<uuid>", "type": "totp" | "webauthn", "name": "...", "confirmed_at": "..."}]`

### `POST /v1/me/mfa/totp`
Start TOTP setup. `{"password": "..."}` → `201` `{"secret": "BASE32...", "otpauth_uri": "otpauth://totp/..."}`.
The factor is inactive until confirmed. Errors: `401 invalid_credentials`, `409 mfa_already_enabled`.

### `POST /v1/me/mfa/totp/confirm`
`{"code": "123456"}` → `204`. Errors: `401 invalid_code`, `409 no_enrolment`, `429`.

### `POST /v1/me/mfa/totp/remove`
`{"code": "123456"}` → `204`. A valid code is required. Errors: `401 invalid_code`, `404`, `429`.

### `POST /v1/me/mfa/webauthn/options`
`{"password": "..."}` → `200` `PublicKeyCredentialCreationOptions` JSON for `navigator.credentials.create()`.

### `POST /v1/me/mfa/webauthn/register`
`{"credential": { ... }, "name": "YubiKey"}` → `204`. Error: `401 invalid_credential`.

### `POST /v1/me/mfa/webauthn/{factor_id}/remove`
`{"password": "..."}` → `204`. Errors: `401 invalid_credentials`, `404`.

---

## 7. Admin: applications, permissions, roles

All **Admin**.

### `GET /v1/admin/applications`
*Paged*, by key. Item:

```json
{ "id": 2, "key": "ANPR", "name": "Anpr", "description": null, "is_active": true, "perm_map_version": 4, "created_at": "...", "updated_at": "..." }
```

### `POST /v1/admin/applications`
`{"key": "ANPR", "name": "Anpr", "description": "..."}` → `201` application. Created with the `*` permission on
bit 0 and an `Admin` role holding it. Error: `409 application_exists`.

### `GET /v1/admin/applications/{key}`
One application. `404`.

### `PATCH /v1/admin/applications/{key}`
`{"name"?, "description"?, "is_active"?}` → application. The AUTH app can't be deactivated (`409 protected`).

### `GET /v1/admin/applications/{key}/members`
Users holding any role in the app: `[{"public_id", "username", "is_active", "roles": [role]}]`.

### `GET /v1/admin/applications/{key}/permissions`
By bit. `?include_retired=true` adds retired ones. Item:
`{"id": 5, "code": "vehicle.read", "description": null, "bit": 1, "retired_at": null}`

### `POST /v1/admin/applications/{key}/permissions`
`{"code": "vehicle.read", "description": "..."}` → `201` permission on the next free bit. Recreating a retired
code revives its original bit. Publishes `permissions.changed`.
Errors: `409 permission_exists`, `409 permission_limit` (1,024 bits).

### `PATCH /v1/admin/applications/{key}/permissions/{permission_id}`
`{"description": "..."}` → permission.

### `DELETE /v1/admin/applications/{key}/permissions/{permission_id}`
Retires the permission (its bit stays reserved) and removes it from roles → the retired permission. Affected
users' tokens become stale. The `*` permission can't be retired (`409 protected`).

### `GET /v1/admin/applications/{key}/roles`
By name: `[{"id", "public_id", "name", "description"}]`. `public_id` is the role's stable UUID, the `id`
downstream servers see; it survives renames.

### `POST /v1/admin/applications/{key}/roles`
`{"name": "Operator", "description": "..."}` → `201` role. Error: `409 role_exists`.

### `GET /v1/admin/applications/{key}/roles/{role_id}`
Role with its permissions: `{"id", "name", "description", "permissions": [permission]}`.

### `PATCH /v1/admin/applications/{key}/roles/{role_id}`
`{"name"?, "description"?}` → role. Renaming makes members' tokens stale. `Admin` can't be renamed (`409 protected`).

### `DELETE /v1/admin/applications/{key}/roles/{role_id}`
`204`. Members' tokens become stale. `Admin` can't be deleted (`409 protected`).

### `PUT /v1/admin/applications/{key}/roles/{role_id}/permissions`
Replace the role's permissions. `{"permission_ids": [5, 6]}` → `[permission]`. Members' tokens become stale.
Errors: `422 invalid_permissions` (unknown, retired or other app), `409 protected` (AUTH Admin must keep `*`).

---

## 8. Admin: users

All **Admin**.

### `GET /v1/admin/users`
*Paged*, by username. `?q=` matches username, email or name; `?active=true|false`; `?app=ANPR` keeps users
holding a role in that application. Item:

```json
{ "public_id": "...", "username": "alice", "email": "...", "first_name": "...", "last_name": "...", "is_active": true, "created_at": "...", "updated_at": "...",
  "app_keys": ["ANPR", "SNVR"], "mfa_enabled": true }
```

### `POST /v1/admin/users`
```json
{ "username": "alice", "password": "a-long-enough-pass", "email": "a@example.com", "first_name": "Alice", "last_name": "Smith", "is_active": true }
```
→ `201` user. Errors: `409 user_exists`, `422 weak_password`.

### `GET /v1/admin/users/{public_id}`
User with access per application (same shape as `GET /v1/me`).

### `PATCH /v1/admin/users/{public_id}`
`{"email"?, "first_name"?, "last_name"?, "is_active"?}` → user. Disabling ends every session and publishes
`user.disabled`; enabling publishes `user.access_changed`. Errors: `409 last_admin`, `409 user_exists` (email).

### `PUT /v1/admin/users/{public_id}/roles`
Replace the user's roles in one application. `{"app_key": "ANPR", "role_ids": [3]}` → `204`. The user's tokens
for that app become stale. Errors: `422 invalid_roles`, `409 last_admin`.

### `GET /v1/admin/users/{public_id}/sessions`
The user's live sessions (same shape as `GET /v1/me/sessions`, `current` always false).

### `DELETE /v1/admin/users/{public_id}/sessions`
End every session of the user. `204`.

### `POST /v1/admin/users/{public_id}/password`
`{"new_password": "..."}` → `204`. Ends every session. Error: `422 weak_password`.

### `GET /v1/admin/users/{public_id}/mfa`
The user's confirmed factors (same shape as `GET /v1/me/mfa`).

### `DELETE /v1/admin/users/{public_id}/mfa`
Remove every MFA factor (lost device) and end every session. `204`.

### `DELETE /v1/admin/sessions/{session_id}`
End any one session. `204`, `404`.

---

## 9. Admin: clients

All **Admin**.

Client shape:

```json
{
  "client_id": "anpr-api", "name": "ANPR API", "app_key": "ANPR", "type": "confidential",
  "redirect_uris": [], "scopes": ["events.read", "permissions.read"], "audiences": [],
  "is_active": true, "created_at": "..."
}
```

Rules: scopes come from `openid profile email` (browser) and `events.read permissions.read users.read`
(service). `users.read` lets a downstream server list its own app's members and roles (section 11). A public client needs a redirect URI and can't hold service scopes or audiences. Redirect URIs
must be https, or http on localhost, without a fragment. The AUTH app can't be an audience.

### `GET /v1/admin/clients`
All clients by `client_id`; `?app=ANPR` filters.

### `POST /v1/admin/clients`
```json
{ "client_id": "anpr-api", "name": "ANPR API", "app_key": "ANPR", "type": "confidential",
  "redirect_uris": [], "scopes": ["events.read", "permissions.read"], "audiences": [] }
```
→ `201` `{"client": client, "client_secret": "<shown once>" | null}`.
Errors: `409 client_exists`, `422 invalid_scope | invalid_audience | invalid_client`.

### `GET /v1/admin/clients/{client_id}`
One client. `404`.

### `PATCH /v1/admin/clients/{client_id}`
`{"name"?, "redirect_uris"?, "scopes"?, "audiences"?, "is_active"?}` → client. Disabling or changing scopes or
audiences ends the client's tokens and publishes `client.revoked`.

### `POST /v1/admin/clients/{client_id}/rotate-secret`
→ `{"client": client, "client_secret": "<shown once>"}`. The old secret and the client's tokens stop working.
Error: `409 not_confidential`.

---

## 10. Admin: signing keys, audit, downstream, stats

All **Admin**.

### `GET /v1/admin/keys`
Keys except expired ones, newest first:
`[{"kid", "algorithm": "ES256", "status": "next|active|retired|revoked", "activated_at", "not_after", "created_at", "rotates_at"}]`.
`rotates_at` is set on the active key only: when the scheduled rotation replaces it.

### `POST /v1/admin/keys/rotate`
Rotate now: `next` becomes active, active retires, a new `next` is made → the new active key. Publishes `key.rotated`.

### `DELETE /v1/admin/keys/{kid}`
Revoke a leaked key: out of JWKS at once, every token it signed stops working. `204`, `404`.

### `GET /v1/admin/audit`
*Paged*, newest first. Filters: `?actor=`, `?action=`, `?app=`, `?since=`, `?until=` (ISO 8601). Item:

```json
{ "id": 42, "actor": "<user uuid | client_id | system:cli>", "actor_name": "<username, or the actor itself>", "action": "user.set_roles", "target": "<uuid>", "app": "ANPR", "details": { "roles": ["Operator"] }, "ip": "10.0.0.5", "created_at": "..." }
```

Actions: `application.create|update`, `permission.create|update|retire`, `role.create|update|delete|set_permissions`,
`user.create|update|set_roles|login|password_change|password_reset`, `session.revoke|revoke_all`,
`mfa.enable|disable|reset`, `client.create|update|rotate_secret`, `key.rotate|revoke`, `token.exchange`,
`token.reuse_detected`, `admin.bootstrap`.

### `GET /v1/admin/downstream`
Sync status of every downstream instance; `?app=` filters.

```json
[ { "app_key": "ANPR", "client_id": "anpr-api", "instance_id": "anpr-1", "last_acked_seq": 120, "last_seq": 122, "lag": 2, "last_seen_at": "...", "status": "ok | lagging | offline" } ]
```

`offline` means no contact for `DOWNSTREAM_LAG_SECONDS`; `lagging` means behind on ACKs.

### `GET /v1/admin/stats`
`{"users": 12, "disabled_users": 1, "applications": 3, "application_keys": ["ANPR", "AUTH", "SNVR"], "active_sessions": 7, "session_users": 5, "service_clients": 2}`

---

## 11. Downstream servers (events)

All **Service**, and the client may only use its own application's `key`. The Auth SDK (`../sdk`) implements
this protocol. The full integration walkthrough, including how to apply each event, is in
[INTEGRATION.md](INTEGRATION.md).

### `GET /v1/events/{key}`
Scope `events.read`. A Server-Sent Events stream.

| Parameter | Notes |
|---|---|
| `after` (query) or `Last-Event-ID` (header) | Required. The last seq applied; events after it are sent |
| `instance_id` (query) | Names this process on the Downstream page |

Frames:

```
id: 121
event: user.access_changed
data: <event JWT>

: keep-alive
```

The `data` is an ES256 JWT (`typ: event+jwt`, `aud` = app key, 5 min) with claims `seq`, `type` and `payload`.
Verify it against JWKS. Keep-alives come every 15 seconds. When the service token expires or the client is
revoked, the stream sends `event: token.expired` and closes: get a new token and reconnect.

Errors: `409 snapshot_required` (the cursor is older than retention, or ahead of the stream),
`422 cursor_required`, `403 wrong_application`.

### `POST /v1/events/{key}/ack`
Scope `events.read`. `{"instance_id": "anpr-1", "seq": 121}` → `204`. Error: `422 invalid_seq` (not yet published).

### `GET /v1/events/{key}/snapshot`
Scope `events.read`. Current revocation state; then stream with `after=seq`.

```json
{
  "seq": 121,
  "perm_map_version": 4,
  "users": [ { "sub": "<uuid>", "ver": 3, "is_active": true } ],
  "revoked_sessions": [ "<sid>" ],
  "revoked_clients": [ { "client_id": "old-api", "version": 2, "revoked_at": 1762990000 } ]
}
```

A token is revoked when its `ver` is below the user's `ver`, the user is inactive, its `sid` is listed, or it
was issued by a listed client at or before `revoked_at`.

### `GET /v1/apps/{key}/permission-map`
Scope `permissions.read`. The code-to-bit map. Refetch when a token's `pv` is newer than `version`.

```json
{ "version": 4, "permissions": [ { "code": "*", "bit": 0, "retired": false }, { "code": "vehicle.read", "bit": 1, "retired": false } ] }
```

### `GET /v1/apps/{key}/members`
Scope `users.read`. Users holding at least one role in the app, by username, including disabled users.

| Query | Default | Notes |
|---|---|---|
| `limit` | 200 | 1 to 1000 |
| `cursor` | none | The previous page's `next_cursor`. Opaque |
| `q` | none | Case-insensitive match on username, first or last name, email |

```json
{
  "items": [
    {
      "sub": "8f0c2a4e-...",
      "username": "vikas",
      "given_name": "Vikas",
      "family_name": "Shah",
      "email": "vikas@example.com",
      "is_active": true,
      "roles": [ { "id": "1b7e...", "name": "Admin" }, { "id": "93d0...", "name": "Operator" } ]
    }
  ],
  "next_cursor": "dmlrYXM"
}
```

- `sub` is the user's public id: the same value as the `sub` claim in their access tokens.
- `given_name`, `family_name`, `email` are `null` when not set. The names match `/oauth/userinfo`.
- `roles` are this app's roles only, by name. A role's `id` is stable across renames; store it, not the name.
- `next_cursor` is `null` on the last page. Unlike the admin lists (`limit`/`offset` with `total`), this list
  pages by key, so it never skips or repeats a member while the list changes.
- Never returned: password hashes, MFA state, superuser flag, sessions, internal ids. Names and email are
  personal data: only clients given `users.read` can read them, and only for their own app.

Errors: `403 insufficient_scope`, `403 wrong_application`, `422 invalid_cursor`, `401` for a user token or a
token of a deactivated app.

### `GET /v1/apps/{key}/roles`
Scope `users.read`. Every role of the app, by name, with its active permission codes (retired ones left out).

```json
[
  { "id": "1b7e...", "name": "Admin", "description": "Full access", "permissions": ["*"] },
  { "id": "93d0...", "name": "Operator", "description": null, "permissions": ["camera.view", "live.view"] }
]
```

`name` is exactly what appears in the token's `roles` claim. Errors as for members.

**When to refresh a cached copy:** on `user.access_changed`, `user.disabled` and `members.changed`, and after
taking a snapshot. The SDK's `on_change` hook does this.

Event types and payloads are listed in [ARCHITECTURE.md, section 9](ARCHITECTURE.md#9-revocation-and-downstream-sync).

---

## 12. Rate limits

Counted in Redis over `RATE_WINDOW_SECONDS` (900). Only failures count.

| Limit | Default | Key |
|---|---|---|
| Login per IP | 30 | client IP |
| Login per account from one IP | 5 | username + IP |
| Login per account overall | 50 | username |
| MFA per user | 10 | user (TOTP, WebAuthn and step-up codes) |
| MFA per challenge | 5 | the challenge; it's destroyed at the limit |
| Step-up password | 5 | user (`/v1/me` password confirmations) |
| Client authentication failures | 120 | client IP |
