# Auth Server: Features

Everything the Auth Server and its web app can do, from the big capabilities down to the small details.

| Detail | Where |
|---|---|
| Every endpoint, request and response | [`auth-server/docs/API.md`](../auth-server/docs/API.md) |
| How it is built and why | [`auth-server/docs/ARCHITECTURE.md`](../auth-server/docs/ARCHITECTURE.md) |
| Connecting a downstream server (ANPR, NVR, ...) | [`auth-server/docs/INTEGRATION.md`](../auth-server/docs/INTEGRATION.md) |
| The web app | [`auth-client/README.md`](../auth-client/README.md) |

---

## Contents

1. [At a glance](#1-at-a-glance)
2. [Single sign-on](#2-single-sign-on)
3. [Sign-in and the login page](#3-sign-in-and-the-login-page)
4. [Two-step sign-in (MFA)](#4-two-step-sign-in-mfa)
5. [Sessions](#5-sessions)
6. [Passwords](#6-passwords)
7. [Applications, permissions and roles](#7-applications-permissions-and-roles)
8. [Users](#8-users)
9. [Tokens](#9-tokens)
10. [OAuth 2.1 and OpenID Connect](#10-oauth-21-and-openid-connect)
11. [Clients (connected apps and services)](#11-clients-connected-apps-and-services)
12. [Service-to-service access and token exchange](#12-service-to-service-access-and-token-exchange)
13. [Instant revocation and downstream sync](#13-instant-revocation-and-downstream-sync)
14. [Signing keys](#14-signing-keys)
15. [Audit log](#15-audit-log)
16. [Admin console](#16-admin-console)
17. [My account (self-service)](#17-my-account-self-service)
18. [Access policy](#18-access-policy)
19. [Security protections](#19-security-protections)
20. [Rate limits and lockout](#20-rate-limits-and-lockout)
21. [Reliability and failure behaviour](#21-reliability-and-failure-behaviour)
22. [Background jobs](#22-background-jobs)
23. [Health checks and monitoring](#23-health-checks-and-monitoring)
24. [Configuration](#24-configuration)
25. [Command-line tools](#25-command-line-tools)
26. [Web app: design and experience](#26-web-app-design-and-experience)
27. [Web app: performance](#27-web-app-performance)
28. [Developer experience and testing](#28-developer-experience-and-testing)
29. [Known limits of version 1](#29-known-limits-of-version-1)

---

## 1. At a glance

The Auth Server is one central system that decides **who someone is** and **what they may do** in every
connected application (ANPR, NVR and any future app).

| Capability | In one line |
|---|---|
| Single sign-on | Sign in once, use every connected app |
| Central access control | Every app's permissions and roles are managed in one console |
| Two-step sign-in | Authenticator app codes (with QR setup) and security keys (WebAuthn) |
| Local token checks | Downstream servers verify tokens themselves, with no call to the Auth Server per request |
| Instant revocation | Disabling a user, changing roles or signing out reaches every app within seconds |
| Service accounts | Backend services get their own credentials and short-lived tokens |
| Full audit trail | Every change is recorded and can never be edited or deleted |
| Admin console and self-service | One web app for administrators and for every user |
| Standards based | OAuth 2.1, OpenID Connect, PKCE, JWT (ES256), JWKS, RFC 7009, RFC 8693, TOTP, WebAuthn |

**Stack.** Server: Python, FastAPI, Tortoise ORM, Aerich migrations, PostgreSQL, Redis. Web app: React 19,
TypeScript, Vite, Tailwind CSS v4, TanStack Router and Query, Radix primitives.

---

## 2. Single sign-on

- **One login for all apps.** After signing in once, opening another connected app signs the user in without
  asking again.
- **SSO session.** A successful sign-in creates a server-side session and sets the `auth_sso` cookie
  (HttpOnly, SameSite=Lax so other apps can redirect back).
- **The cookie is never stored in readable form.** The server keeps only its SHA-256 hash.
- **Each app gets its own tokens.** A token issued for ANPR is refused by NVR.
- **Logins in different apps and on different devices are independent.** Signing in to app 2 on another
  computer doesn't sign the user out of app 1.
- **Several tabs of the same app work together.** Two tabs refreshing at the same moment don't sign each other
  out (see the refresh grace window in [section 9](#9-tokens)).
- **Silent sign-in.** An app can ask with `prompt=none` whether the user is already signed in, without ever
  showing the login page.
- **Forced re-login.** An app can demand a fresh sign-in with `prompt=login`, or require one newer than
  `max_age` seconds.
- **Ending one login.** Logging out of one app ends that login only; the user's other logins stay.
- **Ending everything.** An administrator, a password change or a disabled account can end every session at
  once.

---

## 3. Sign-in and the login page

- **One hosted login page for every app** at `/login`. Apps redirect there; after sign-in the user goes back
  to the app.
- **Username or password errors share one message**, so the page never reveals whether an account exists.
- **Disabled accounts get the same message** as a wrong password.
- **Equal timing.** An unknown username takes as long to reject as a real one, so accounts can't be discovered
  by measuring response time.
- **Passwords are checked in a worker thread**, so slow hashing never blocks other requests.
- **Safe return address.** The page returns only to a same-origin `/oauth/authorize` address. Anything else
  (other sites, `//host`, `javascript:`) is ignored, so the page can't be used as an open redirect.
- **Long return addresses are kept whole** (up to 4,000 characters), so the PKCE challenge in them is never
  cut off.
- **Clear error messages** for wrong password, too many attempts (with the wait time), service temporarily
  unavailable, wrong code, expired code step, and errors sent back from the console sign-in.
- **Lockout shows how long to wait**, from the server's `Retry-After`.
- **Second step on the same page.** When MFA is on, the page switches to the code or security-key step without
  a reload.
- **Small and fast.** The login page loads only what it needs (about 128 KB gzipped), because users of every
  app load it.
- **Light and dark themes** follow the system setting.

---

## 4. Two-step sign-in (MFA)

### Authenticator app (TOTP)

- **QR code setup.** Scan the QR code with any authenticator app (Google Authenticator, Microsoft
  Authenticator, Authy, 1Password, ...).
- **Manual setup.** The secret is also shown as text for apps that can't scan.
- **Nothing changes until it's confirmed.** A new authenticator protects the account only after its first
  correct code.
- **Password required to start setup**, so someone at an unlocked computer can't add their own authenticator.
- **Code required to remove it.**
- **Each code works once.** A code that has been used can't be replayed, even within its 30 seconds.
- **Secrets are encrypted** in the database (AES-GCM under `MASTER_KEY`).
- **Six-digit code input** with paste support: pasting a full code fills every box.

### Security keys (WebAuthn)

- **Hardware keys and passkeys**: YubiKey, Windows Hello, Touch ID, phone passkeys.
- **Several keys per user**, each with its own name (for example "YubiKey" or "Laptop").
- **Password required to add or remove a key.**
- **Each challenge works once.**
- **Cloned-key detection.** The key's signature counter is updated with a conditional write, so a copied key
  can't race the real one.

### Protections

- **The code step expires** after `MFA_CHALLENGE_SECONDS` (300 s).
- **Guessing is capped per challenge.** After `MFA_MAX_ATTEMPTS` (5) wrong codes the step is destroyed and
  the user starts again.
- **Guessing is capped per user** across all challenges (10 in the window).
- **The session remembers how the user signed in** (`amr`: `pwd`, `otp`, `hwk`), shown in session lists.

### Administrator help

- **See a user's factors** (type, name, date added).
- **Reset MFA** for a user who lost their phone or key. This removes every factor and ends every session.

---

## 5. Sessions

- **Every sign-in is a session** with its own id (`sid`), IP address, device (user agent), sign-in method and
  expiry.
- **Session lifetime** is `SESSION_DAYS` (14 days), absolute: refreshing can never extend it.
- **Users see their own sessions**, newest first, with "this device" marked.
- **Users can end any of their other sessions.**
- **Administrators see and end any user's sessions**, one or all.
- **Readable device names** in the web app (browser and operating system from the user agent).
- **Ending a session reaches every app.** Its refresh tokens are revoked, its console session is removed, and
  a `session.revoked` event goes to every app that may hold its tokens.
- **Automatic endings:**

| Event | Sessions ended |
|---|---|
| User changes their own password | All except the current one |
| Administrator sets a new password | All |
| Administrator resets MFA | All |
| Administrator disables the user | All |
| A refresh token is reused after the grace window (theft) | That session |

---

## 6. Passwords

- **Argon2id hashing**, the current recommended algorithm.
- **Automatic rehash.** When hashing settings are strengthened, old hashes are upgraded at the next sign-in.
- **Minimum length** (`MIN_PASSWORD_LENGTH` in `auth-server/app/users/utils.py`, default 12; the web app's
  matching value is `MIN_PASSWORD` in `auth-client/src/lib/validation.ts`).
- **Must not contain the username** (same file).
- **Change password** (self-service): needs the current password, ends the other sessions.
- **Set password** (administrator): for a user who forgot theirs; ends every session.
- **Password confirmations are rate limited** (5 wrong in the window).
- **No default password anywhere.** The first administrator's password is typed at setup.
- **Long-password limit** of 256 characters, so huge inputs can't be used to slow the server.

> Note: in the current development copy the minimum is lowered to 4 and the username rule is commented out.
> Put both back before going live.

---

## 7. Applications, permissions and roles

### Applications

- **One entry per connected system**: ANPR, SNVR, and the Auth Server itself (`AUTH`).
- **Application key**: 2 to 32 characters, `A-Z 0-9 _`, starting with a letter. Typed lower-case, stored
  upper-case.
- **Name and description** can be edited.
- **Deactivate, never delete.** A deactivated app stops issuing tokens; its history and bits stay.
- **The AUTH app is protected** and can't be deactivated.
- **Every new app starts with** a `*` permission (bit 0, full access) and an `Admin` role holding it.
- **Members view**: everyone who holds any role in the app, with their roles.
- **Clients view**: every client that belongs to the app.

### Permissions

- **Named permission codes** like `vehicle.read` or `report.export` (lower-case dotted names).
- **Each permission owns a permanent bit number.** A user's access is one integer with their bits set.
- **Up to 1,024 permissions per app.**
- **Bits are never reused.** Deleting a permission retires it and keeps its bit, so an old token can never gain
  a new meaning.
- **Recreating a retired code revives its original bit.**
- **Descriptions** explain each permission in the console.
- **Retired permissions** can be listed (`include_retired=true`) and are hatched in the key-cut strip.
- **The `*` permission can't be retired.**
- **Permission map version (`pv`).** Every change to an app's map raises its version, so downstream servers
  know when to refetch the code-to-bit map.
- **Warning before retiring**: the console explains that holders lose the permission at once.

### Roles

- **Roles group permissions** inside one app (for example "Operator" holds `vehicle.read` and
  `camera.read`).
- **Create, rename, describe, delete** roles.
- **Set a role's permissions** with checkboxes.
- **The `Admin` role is protected**: it can't be renamed or deleted, and AUTH's Admin must keep `*`.
- **Every role change reaches holders at once.** Renaming, deleting or changing a role's permissions makes its
  members' tokens for that app stale.

### Access versions

- **Per-user, per-app version (`ver`).** Any change to what a user can do in an app raises it. Their tokens for
  that app become stale; their tokens for other apps are untouched.
- **At least one administrator always remains.** Removing, disabling or demoting the last active AUTH
  administrator is refused (`last_admin`). The check locks the Admin role, so two simultaneous removals can't
  both succeed.

---

## 8. Users

- **Create users** with username, password, email, first and last name, and active or disabled.
- **Usernames**: 3 to 64 characters of `a-z 0-9 . _ -`, stored lower-case and unique.
- **Email** is optional and unique.
- **Edit profile**: email, first name, last name.
- **Disable and enable.** Disabling ends every session and tells every app at once (`user.disabled`).
  Enabling tells every app too (`user.access_changed`). Users are never deleted, so their audit history stays.
- **Assign roles per app.** Pick an app, tick roles. Replacing roles in one app never touches the user's roles
  in other apps.
- **Access view per app.** The user's roles, the permissions they add up to, and the key-cut strip showing
  exactly which bits they hold.
- **Search** by username, email or name.
- **Filter** by status (active or disabled) and by application.
- **Paging** with a total count.
- **Badges** for MFA on or off and for every app the user can reach.
- **Initials avatar**, falling back to the username when no name is set.
- **Public id.** Users are addressed by a UUID (`sub` in tokens); internal database ids never leave the
  server.

---

## 9. Tokens

| Token | Lifetime | Format | Stored by the server |
|---|---|---|---|
| Access token (user) | 10 min | ES256 JWT | No |
| ID token | 10 min | ES256 JWT | No |
| Refresh token | until the session ends, new one on every use | random, opaque | hash only |
| Service token | 15 min | ES256 JWT | No |
| Exchanged token | 5 min | ES256 JWT with `act` | No |
| Event token | 5 min | ES256 JWT | No |

- **Signed with ES256** (elliptic curve P-256). Only the Auth Server holds private keys; apps hold public keys.
- **Audience-bound.** Each token names exactly one app (`aud`).
- **Compact permissions.** The permission bits travel as `pm`, little-endian bytes in base64url, so they stay
  exact in JavaScript (no 2^53 limit). Example: bits {1, 4, 9} = 530 = `"EgI"`.
- **Roles in the token** are the role names for that app only.
- **Claims:** `iss`, `aud`, `sub`, `exp`, `sid`, `ver`, `pm`, `pv`, `roles`, `client_id`, `kid` in the header,
  and `act` on exchanged tokens.
- **Strict checking.** Only ES256 is accepted whatever the header says (`alg: none` and HMAC tricks fail).
  `typ`, `iss`, `exp` and `aud` are all checked.
- **Live checks on the Auth Server itself.** Its own API also checks that the user is active, the session is
  live, the app is active, `ver` is current and the client is active.
- **Refresh rotation.** Every refresh returns a new refresh token; the old one is used up.
- **Two-tab grace window.** A second refresh with the same token within `REFRESH_GRACE_SECONDS` (10 s) gets
  an access token but no new refresh token, so two tabs don't sign each other out and no hidden branch can
  start.
- **Theft detection.** Reusing a refresh token after the window ends the session and is audited
  (`token.reuse_detected`).
- **Refresh can narrow scope, never widen it.**
- **Refresh tokens are stored only as hashes.**

---

## 10. OAuth 2.1 and OpenID Connect

- **Authorization code flow with PKCE** (S256 only; `plain` is refused).
- **Single-use codes** valid for `AUTH_CODE_SECONDS` (60 s). A second use revokes everything that code issued.
- **Exact redirect URI matching.**
- **No redirect before the redirect URI is proven.** An unknown client or unregistered URI gets a plain error
  page, never a redirect.
- **`state`, `nonce` and `iss`** in the response (RFC 9207 issuer identification).
- **Access denied for users without a role** in the client's app (`error=access_denied`).
- **Scopes:** `openid`, `profile`, `email` for browser apps; `events.read`, `permissions.read`, `users.read`
  for services.
- **ID tokens** with `sub`, `sid`, `auth_time`, `amr`, `at_hash`, `nonce`, and profile and email claims when
  asked for.
- **UserInfo endpoint** (`/oauth/userinfo`).
- **Token revocation** (RFC 7009): revokes a refresh token and its whole family. Always answers 200, so it
  reveals nothing.
- **Logout endpoint** for one login, by token or SSO cookie.
- **Discovery document** (`/.well-known/openid-configuration`) and **JWKS** (`/.well-known/jwks.json`, cached
  60 s), so standard OAuth libraries configure themselves.
- **Client authentication** by HTTP Basic (`client_secret_basic`), form fields (`client_secret_post`), or
  `client_id` alone for public clients.
- **`Cache-Control: no-store`** on every token response.
- **Standard OAuth error shapes** (`invalid_grant`, `invalid_client`, `invalid_scope`, ...).

---

## 11. Clients (connected apps and services)

- **Two kinds:**
  - **Public** clients: browser and mobile apps with redirect URIs and no secret (PKCE protects them).
  - **Confidential** clients: backend services with a secret.
- **Belongs to one app.**
- **Client secret shown once** at creation, with a copy button and a warning. Only its SHA-256 hash is
  stored.
- **Rotate secret.** A new secret is shown once; the old secret and every token the client holds stop working.
- **Redirect URIs** must be https, or http on localhost, with no fragment.
- **Scopes** from the allowed list; public clients can't hold service scopes.
- **Audiences**: other apps a confidential client may get tokens for. The AUTH app can never be one.
- **Edit name, redirect URIs, scopes, audiences.**
- **Disable a client.** Disabling, or changing its scopes or audiences, ends its tokens everywhere at once
  (`client.revoked`).
- **Client version.** Each revoking change raises it, so downstream servers can reject tokens issued before
  the change.
- **The console's own client** (`auth-console`) is created automatically.

---

## 12. Service-to-service access and token exchange

- **Client credentials grant.** A backend service trades its id and secret for a 15-minute service token.
- **Service tokens are scoped** (`events.read`, `permissions.read`, `users.read`) and target AUTH by default,
  or another app listed in the client's audiences.
- **A service may only read its own app's** events, permission map, members and roles.
- **Token exchange (RFC 8693).** One service calls another on a user's behalf:
  - needs a confidential client, a user token issued for that client's own app, and a target app in the
    client's audiences;
  - the new token carries `act` (who is acting) and lives 5 minutes;
  - requested scope **narrows** permissions (requested AND held) and keeps a role only if all its permissions
    remain; it can never widen;
  - an exchanged token can't be exchanged again;
  - the AUTH app is never a target, and exchanged tokens are refused on the Auth Server's own API;
  - every exchange is audited (`token.exchange`).

---

## 13. Instant revocation and downstream sync

The heart of the system: how every downstream server learns about changes within seconds.

- **Events over Server-Sent Events (SSE).** The downstream server connects out to the Auth Server, so it works
  through firewalls and needs no message broker.
- **Signed events.** Each event is an ES256 JWT (`typ: event+jwt`), verified with the same public keys as
  tokens.
- **Transactional outbox.** A change and its event are saved in one database transaction: a change can never
  be saved without its event, and a rolled-back change sends nothing.
- **Gapless numbering per app** (`seq`), so a downstream server can tell if it missed something.
- **No deadlocks** when one change touches several apps (counters locked in a fixed order).
- **Instant wake-up** with Postgres `LISTEN/NOTIFY`, plus polling every 5 s, so delivery never depends on the
  wake-up alone.
- **Resume after disconnect** with `Last-Event-ID` or `after=`; missed events are replayed.
- **Acknowledgements.** Each downstream instance confirms what it has applied (`ack`); the console shows how
  far behind each one is.
- **Snapshot.** When a server was away longer than the retention period, it downloads the current state
  (user versions and status, revoked sessions, revoked clients) and continues from there.
- **Keep-alives** every 15 s.
- **Stream ends cleanly** when the service token expires or the client is revoked (`token.expired`), telling
  the consumer to reconnect.
- **Instance names** (`instance_id`) identify each running process on the Downstream page.
- **Event retention** of `EVENT_RETENTION_DAYS` (7 days).
- **Guaranteed upper limit.** Even if the stream is down, a revoked token stops working when it expires
  (10 minutes).

| Event | Sent when |
|---|---|
| `user.access_changed` | roles or role permissions change, a role is renamed or deleted, a permission is retired, a user is enabled |
| `user.disabled` | a user is disabled |
| `session.revoked` | logout, session ended, password change or reset, MFA reset, refresh-token theft |
| `client.revoked` | a client is disabled, its scopes or audiences change, or its secret rotates |
| `key.rotated` | a signing key rotates or is revoked (sent to every app) |
| `permissions.changed` | a permission is created, revived or retired |
| `members.changed` | a role is created, described, renamed or deleted, or a user's name or email changes |

**Permission map endpoint.** Downstream servers fetch the code-to-bit map (`/v1/apps/{key}/permission-map`)
and refetch when a token's `pv` is newer.

**Members and roles endpoints** (scope `users.read`). A downstream server lists everyone who holds a role in
its own app (`/v1/apps/{key}/members`), including people who never signed in to it, and every role with its
permission codes (`/v1/apps/{key}/roles`). Built for screens like "give this camera to a user or a role":

- Members carry `sub` (the same as in their tokens), username, names, email, active flag and roles.
- Keyset paging (`limit`, `cursor`) and search (`q`).
- **Roles have a stable id** that survives renames, so downstream grants never break when a role is renamed.
- Read-only, own app only, and nothing private (no password hashes, MFA state or internal ids).

---

## 14. Signing keys

- **Automatic lifecycle:** `next` → `active` → `retired` → `expired`, or `revoked` on a leak.
- **Published before use.** The `next` key is in JWKS before it signs anything, so every downstream server
  already has it when it becomes active.
- **Scheduled rotation** every `KEY_ROTATION_DAYS` (30 days).
- **Rotate now** from the console.
- **Revoke a leaked key** with typed confirmation: it leaves JWKS at once and every token it signed stops
  working.
- **Retired keys stay published** long enough for tokens they signed to expire.
- **Private keys are encrypted** (AES-GCM under `MASTER_KEY`, bound to their `kid`), behind a `KeyProvider` so
  a vault can replace local storage.
- **Every replica updates at once** (`NOTIFY auth_keys` clears key caches).
- **Next rotation date** is shown on the dashboard's key card with a progress bar.

---

## 15. Audit log

- **Every change is recorded**: who, what, which target, which app, details, IP address and time.
- **Written in the same transaction** as the change, so the log can't miss anything.
- **Can never be edited or deleted.** A database trigger rejects UPDATE, DELETE and TRUNCATE.
- **Readable names.** Actors show as usernames or client ids, not raw ids.
- **Filters:** actor, action, app, date from, date to. Filters stay in the URL and survive a reload.
- **Paging**, newest first.
- **Recent activity** on the dashboard.
- **Recorded actions:** application create and update; permission create, update and retire; role create,
  update, delete and set permissions; user create, update, set roles, login, password change and password
  reset; session revoke and revoke all; MFA enable, disable and reset; client create, update and rotate
  secret; key rotate and revoke; token exchange; token reuse detected; admin bootstrap.

---

## 16. Admin console

Available to users with the `Admin` role on the AUTH app.

| Page | What it does |
|---|---|
| **Dashboard** | Counts (users, disabled users, applications, active sessions and how many people, service clients), downstream sync table, signing key card with next rotation, recent activity |
| **Applications** | List and create apps; detail with Permissions (bit map, create, describe, retire), Roles (create, rename, delete, set permissions), Members, Clients |
| **Users** | Search, filter by status and app, paging, create user; detail with Access (key-cut strip per app, edit roles), Sessions, MFA, Profile (edit, set password, disable or enable) |
| **Clients** | List, create (secret shown once), edit, rotate secret, disable |
| **Signing keys** | Status of every key, rotate now, revoke with typed confirmation |
| **Downstream sync** | Every downstream instance: last applied event, lag, last seen, OK / lagging / offline; refreshes every 10 s |
| **Audit log** | Filterable, paged history of every change |

Console behaviour:

- **No tokens in the browser** (backend-for-frontend). The browser holds only an HttpOnly, SameSite=Strict
  cookie; tokens stay encrypted on the server.
- **CSRF protection.** Every write sends the `X-CSRF-Token` header.
- **Login binding.** The console sign-in uses a short-lived binding cookie, so an attacker can't hand a victim
  the attacker's own login.
- **Role changes apply without signing in again.** The server renews the console's token when it becomes
  stale.
- **Session expiry handled.** A `401` sends the user through sign-in again and back.
- **Non-admins are redirected** to My account.
- **Confirmation dialogs** for every destructive action (disable, revoke, retire, delete, reset MFA).
- **Success toasts** that repeat the button's own words ("Disable user" → "User disabled").
- **Quick search** in the top bar.
- **Sidebar counts** from the dashboard numbers.

---

## 17. My account (self-service)

Every signed-in user, admin or not.

- **Profile**: name, username, email.
- **My access**: every app, its roles, its permissions and the key-cut strip.
- **Change password** (other sessions end).
- **My sessions**: devices, IP, sign-in method, this device marked; end any other session.
- **Authenticator app**: set up with a QR code, confirm with a code, remove with a code.
- **Security keys**: add (named), list, remove.
- **Sign out** from the user menu ends the console session and the SSO session.

---

## 18. Access policy

- **Every endpoint's rule is in one file**: `auth-server/app/security/policy.py`.
- **Rule types:** free (no token), self-guarded (the route checks its own credentials), any signed-in user
  (AUTH token), administrator.
- **Default is administrator.** Anything not listed needs the Admin role.
- **One guard for every route**, including routes added later.
- **Fail closed.** A route the guard can't identify is denied.
- **Startup checks.** The server refuses to start if the guard is missing, a rule matches no route, or a
  required public endpoint isn't public.
- **Policy audit command** (`python -m app.security.policy_audit`) prints every route's rule and fails if any
  route falls back to the default, for use in CI.

---

## 19. Security protections

- **Startup refuses unsafe settings:** missing or weak `MASTER_KEY`, `CORS_ORIGINS: ["*"]`, and in production
  a default database password or a non-https `ISSUER`.
- **Production is the default environment**, so a forgotten setting gets the strict rules.
- **Secrets are never printed**, even in validation errors.
- **Encryption at rest** (AES-GCM, per-purpose context so a value copied to another row won't decrypt):
  signing keys, TOTP secrets, console tokens.
- **Hashes only** for session cookies, refresh tokens, authorization codes and client secrets (SHA-256), and
  passwords (Argon2id).
- **Security headers** on every response: `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`,
  `Referrer-Policy: no-referrer`, HSTS in production. Set without buffering, so SSE still streams.
- **API docs hidden in production** (`/docs` and `/openapi.json`).
- **Exact CORS origins only.**
- **Trusted proxies** (`FORWARDED_ALLOW_IPS`), so rate limits and audit see the real client IP.
- **Generic server errors.** A crash returns `internal_error`; details stay in the server log.
- **Open-redirect protection** on the login page and the authorize endpoint.
- **Account discovery protection**: one error message and equal timing.
- **No integer ids in URLs or tokens.**

---

## 20. Rate limits and lockout

Counted in Redis over `RATE_WINDOW_SECONDS` (15 minutes). Only failures count, so normal use is never slowed.

| Limit | Default |
|---|---|
| Login failures per IP | 30 |
| Login failures per account from one IP | 5 |
| Login failures per account overall | 50 |
| MFA failures per user | 10 |
| MFA failures per code step | 5 (the step is then destroyed) |
| Password confirmations per user | 5 |
| Client authentication failures per IP | 120 |

- **Strangers can't lock someone out** from another address: the per-account limit is per IP, with a much
  higher account-wide ceiling.
- **`Retry-After`** tells the client how long to wait; the login page shows it.

---

## 21. Reliability and failure behaviour

| Failure | What happens |
|---|---|
| Auth Server down | Existing tokens keep working in every app until they expire. New sign-ins and refreshes wait |
| Event stream down | Apps run on slightly old data for at most one token lifetime (10 min). Strict apps can refuse after a set staleness |
| Redis down | Tokens still verify. Sign-in and MFA are refused (fail closed). Readiness stays up |
| PostgreSQL down | Readiness reports 503. Token issuing stops; apps keep verifying |
| Signing key leaked | Revoke it: every replica and app drops it at once |

- **Stateless servers.** Run as many replicas as needed; all state is in PostgreSQL and Redis.
- **PostgreSQL is the source of truth.** Redis holds only what can be lost (rate counters, login challenges).
- **Safe on several replicas.** Background jobs take a Postgres advisory lock, so only one replica runs each.

---

## 22. Background jobs

Run every `JOB_INTERVAL_SECONDS` (60 s); switch off with `RUN_JOBS=false`.

| Job | Does |
|---|---|
| Cleanup | Deletes expired codes, console sessions, refresh tokens and sessions (revoked sessions are kept until they would have expired, because snapshots list them) |
| Outbox pruning | Deletes events older than `EVENT_RETENTION_DAYS` |
| Key rotation | Keeps an active and a next key, expires retired keys, rotates on schedule |
| Downstream report | Logs downstream instances that are lagging or offline |

---

## 23. Health checks and monitoring

- **Liveness** (`/health/live`): the process is running; touches nothing else.
- **Readiness** (`/health/ready`): the database decides; Redis status is reported.
- **Downstream status** in the console and in the logs.
- **Dashboard counts** for a quick health view.

---

## 24. Configuration

All settings come from `auth-server/.env`, validated at startup.

| Group | Settings (defaults) |
|---|---|
| Server | `ENVIRONMENT` (production), `HOST`, `PORT` (8000), `LOG_LEVEL`, `CORS_ORIGINS`, `FORWARDED_ALLOW_IPS` |
| Database | `DB_HOST`, `DB_PORT`, `DB_USER`, `DB_PASSWORD`, `DB_NAME` (auth), or `DATABASE_URL` |
| Redis | `REDIS_URL` (required) |
| Secret | `MASTER_KEY` (required, 32 random bytes, base64url) |
| Issuer | `ISSUER`, `AUTH_APP_KEY` (AUTH), `LOGIN_PAGE_PATH` (/login) |
| Lifetimes | `ACCESS_TOKEN_MINUTES` 10, `SERVICE_TOKEN_MINUTES` 15, `EXCHANGE_TOKEN_MINUTES` 5, `AUTH_CODE_SECONDS` 60, `REFRESH_GRACE_SECONDS` 10, `SESSION_DAYS` 14 |
| Keys and events | `KEY_ROTATION_DAYS` 30, `EVENT_RETENTION_DAYS` 7, `DOWNSTREAM_LAG_SECONDS` 60 |
| Limits | `LOGIN_LIMIT_PER_ACCOUNT` 5, `LOGIN_LIMIT_PER_IP` 30, `TOKEN_LIMIT_PER_IP` 120, `RATE_WINDOW_SECONDS` 900, `MFA_MAX_ATTEMPTS` 5, `MFA_CHALLENGE_SECONDS` 300 |
| Jobs | `RUN_JOBS` true, `JOB_INTERVAL_SECONDS` 60 |

Web app: `PORT` (5181) and `API_TARGET` (`http://127.0.0.1:8000`) for the dev server.

---

## 25. Command-line tools

| Command | Does |
|---|---|
| `py cli.py create-admin --username <name> [--email <email>]` | Creates the AUTH app and its first administrator. Works only once; asks for the password (or `--password-stdin`) |
| `py cli.py export-openapi --out <file>` | Writes the API schema the web app generates its types from |
| `python -m app.security.policy_audit` | Prints every route's access rule; fails if any falls back to the default |
| `aerich upgrade` / `aerich migrate --name <change>` | Applies / creates database migrations |

---

## 26. Web app: design and experience

- **Locked design** in `ui-design/` is the source of truth; the React app follows it.
- **Light and dark themes**, system by default, with a toggle that remembers the choice.
- **Cyan accent** and a soft, readable dark theme.
- **Key-cut strip.** The signature component: each permission bit drawn as a key tooth, cut when held,
  hatched when retired. Hovering or focusing a tooth shows its code; screen readers get the list of held
  permissions.
- **Responsive.** On a phone, tables become cards and the sidebar becomes a drawer.
- **Keyboard friendly.** Every action reachable, visible focus, dialogs trap focus, tabs use arrow keys.
- **Accessible.** Real buttons, labels on every field, native progress bars, alerts announced to screen
  readers.
- **Loading, empty and error states** on every page, with skeletons while loading.
- **URL state.** Filters, paging and tabs live in the URL, so they survive reloads and can be shared.
- **Page titles** per screen.
- **Copy buttons** for ids and secrets.
- **Plain, consistent wording.** Buttons say what happens; toasts repeat the same verb.
- **Self-hosted fonts** (Schibsted Grotesk, IBM Plex Sans, IBM Plex Mono); no Google Fonts request.

---

## 27. Web app: performance

- **Every page is its own chunk**, loaded when visited.
- **Login page about 128 KB gzipped**: no shell, menus, dialogs, form library or toasts.
- **Heavy parts load only where needed**: QR code library, WebAuthn library, form library.
- **Radix components imported one by one**, icons one by one.
- **Cached queries** with sensible stale times, so going back to a page is instant.
- **Bundle report** with `npm run analyze`.

---

## 28. Developer experience and testing

- **Typed API client** generated from the server's OpenAPI schema (`npm run gen:api`), so a server change that
  breaks the web app fails the type check.
- **One hooks file per resource** in `auth-client/src/api/`; pages never call `fetch` themselves.
- **Clear folder structure**: `pages/<area>/` for screens, `components/` for shared pieces (see
  [PROJECT_STRUCTURE.md](PROJECT_STRUCTURE.md)).
- **Component gallery** at `/dev/components` (development only) showing every component in every state.
- **Server tests**: 311 pytest tests against a real PostgreSQL test database (`auth_test`).
- **Web app tests**: 36 unit and component tests (Vitest), and end-to-end tests (Playwright in Edge) against a
  real server on a throwaway database (`auth_e2e`), covering sign-in errors, open-redirect refusal, an admin
  building an app and granting access, and a non-admin setting up TOTP and signing in with a code.
- **Screenshot run** for design review (`SCREENS_DIR=./screens npm run e2e -- screens`).
- **Linting and formatting**: oxlint (React, accessibility, imports) and Prettier with Tailwind class sorting.
- **Interactive API docs** at `/docs` outside production.

---

## 29. Known limits of version 1

- All clients are first-party: there is no consent screen.
- Redirect URIs must be https, or http on localhost.
- Logout with a bearer token accepts a token for any app, so any app holding a user's token can end that
  login.
- Token exchange has no per-client ceiling beyond the client's audiences.
- Deployment (nginx and Docker) and removal of the old `client/` folder are still to do.
