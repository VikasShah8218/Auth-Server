# How It Works: Flow Diagrams

This document shows each moving part of the Auth Server as a step-by-step flow. The diagrams use Mermaid,
which GitHub, GitLab and VS Code (with a Mermaid extension) draw automatically.

| # | Flow | Who is involved |
|---|---|---|
| 1 | [The big picture](#1-the-big-picture) | Everything |
| 2 | [Sign-in page (password, TOTP, passkey)](#2-sign-in-page-password-totp-passkey) | User, login page, Auth Server |
| 3 | [Admin console (auth-client) login](#3-admin-console-auth-client-login) | Admin, console, BFF |
| 4 | [Downstream web or desktop app login](#4-downstream-web-or-desktop-app-login-pkce) | User, your app, Auth Server |
| 5 | [Refresh and logout](#5-refresh-token-rotation-and-logout) | Your app, Auth Server |
| 6 | [Downstream server: SDK startup and sync](#6-downstream-server-sdk-startup-and-sync) | SDK, Auth Server |
| 7 | [Downstream server: checking a request](#7-downstream-server-checking-a-request) | User's app, your server, SDK |
| 8 | [A change reaching every server](#8-a-change-reaching-every-downstream-server) | Admin, Auth Server, SDKs |
| 9 | [Server to server](#9-server-to-server-service-tokens-and-token-exchange) | Two downstream servers |
| 10 | [Members and roles API](#10-members-and-roles-api) | Downstream server, SDK |
| 11 | [Signing key rotation](#11-signing-key-rotation-and-revocation) | Auth Server, SDKs |
| 12 | [Running several replicas](#12-running-several-replicas) | Load balancer, replicas, Postgres |

---

## 1. The big picture

```mermaid
flowchart LR
    subgraph Users
        U[User's browser or desktop app]
        A[Admin's browser]
    end

    subgraph AuthServer["Auth Server (FastAPI, any number of replicas)"]
        LP["/login page<br/>(auth-client)"]
        OA["/oauth/*<br/>authorize, token, revoke, logout"]
        ID["/v1/identity/*<br/>password, TOTP, passkey"]
        BFF["/bff/*<br/>console backend"]
        ADM["/v1/admin/*<br/>users, apps, roles, keys"]
        EV["/v1/events/*<br/>SSE, ack, snapshot"]
        SVC["/v1/apps/{key}/*<br/>permission-map, members, roles"]
        JW["/.well-known/jwks.json"]
    end

    PG[(PostgreSQL<br/>source of truth + outbox)]
    RD[(Redis<br/>rate limits + challenges)]

    subgraph Downstream["Downstream server (e.g. Shah-NVR)"]
        SDK[auth_sdk]
        API[Your API]
    end

    U -- "1. sign in" --> LP --> ID
    U -- "2. code + PKCE" --> OA
    A --> BFF --> ADM
    U -- "3. Bearer access token" --> API
    API -- "verify locally" --> SDK
    SDK -- "keys" --> JW
    SDK -- "events (SSE)" --> EV
    SDK -- "maps, members" --> SVC
    AuthServer --- PG
    AuthServer --- RD
```

**The core idea:**
- The Auth Server issues short-lived signed tokens (10 minutes).
- Downstream servers verify them **locally** with the public keys; there is no call per request.
- Changes such as a lost role, a disabled user or a logout are **pushed** to every downstream server over SSE
  within about a second.

---

## 2. Sign-in page (password, TOTP, passkey)

Every login (the console, a downstream web app, a desktop app) ends up on this one page. The result is always
the same: an `auth_sso` cookie, then a redirect back to `/oauth/authorize`.

```mermaid
sequenceDiagram
    autonumber
    actor User
    participant Page as /login page (browser)
    participant ID as /v1/identity/*
    participant R as Redis
    participant DB as PostgreSQL

    Note over Page: Opened by /oauth/authorize with ?return_to=...

    alt Password
        User->>Page: username + password
        Page->>ID: POST /v1/identity/login
        ID->>R: check failure counters (per IP, per account+IP, account ceiling)
        ID->>DB: load user, verify Argon2id hash (worker thread)
        alt Wrong password or unknown user
            ID->>R: count the failure
            ID-->>Page: 401 one generic message (same timing either way)
        else MFA is on
            ID->>R: store MFA challenge (short-lived, attempt-capped)
            ID-->>Page: {mfa_required, challenge}
            User->>Page: 6-digit TOTP code
            Page->>ID: POST /v1/identity/mfa/verify
            ID->>DB: accept code once (conditional update on last step)
            ID->>R: delete challenge
        end
    else Passkey
        Page->>ID: POST /v1/identity/webauthn/options
        ID->>R: store single-use challenge
        ID-->>Page: WebAuthn options
        User->>Page: touch the key / Windows Hello
        Page->>ID: POST /v1/identity/webauthn/verify
        ID->>R: consume challenge
        ID->>DB: check signature, conditional sign-count update
    end

    ID->>DB: create Session (sid), audit record
    ID-->>Page: Set-Cookie auth_sso (HttpOnly, SameSite=Lax, only its hash stored)
    Page->>Page: go to return_to (back to /oauth/authorize)
```

**Notes:**
- **Redis down:** login and MFA return 503. This is deliberate, because without the counters it can't stop guessing.
- **Lockouts:** only failures count, and a stranger can't lock someone out from a different address.

---

## 3. Admin console (auth-client) login

The console is a normal OAuth client called `auth-console`, but **the browser never sees a token**. The BFF
(backend-for-frontend) keeps the tokens on the server.

```mermaid
sequenceDiagram
    autonumber
    actor Admin
    participant SPA as Console SPA (auth-client)
    participant BFF as /bff/*
    participant OA as /oauth/*
    participant R as Redis
    participant DB as PostgreSQL

    Admin->>SPA: open the console
    SPA->>BFF: GET /bff/session
    BFF-->>SPA: 401 (no console cookie)
    SPA->>BFF: GET /bff/login
    BFF->>R: store state + PKCE verifier
    BFF-->>SPA: 302 to /oauth/authorize + short-lived binding cookie
    SPA->>OA: GET /oauth/authorize?client_id=auth-console&code_challenge=...
    alt No auth_sso cookie yet
        OA-->>Admin: 302 to /login?return_to=... (see flow 2)
        Admin->>OA: back to /oauth/authorize with auth_sso
    end
    OA->>DB: store single-use authorization code
    OA-->>BFF: 302 /bff/callback?code=...&state=...
    BFF->>R: take state + verifier (checked against binding cookie)
    BFF->>OA: POST /oauth/token (code + verifier), server side
    OA-->>BFF: access + refresh + id tokens
    BFF->>DB: store tokens AES-GCM encrypted in bff_sessions
    BFF-->>SPA: Set-Cookie auth_console (HttpOnly, SameSite=Strict)

    SPA->>BFF: GET /bff/session
    BFF-->>SPA: user, roles, CSRF token

    loop Every console action
        SPA->>DB: /v1/admin/... with cookie + X-CSRF-Token (writes)
        Note over BFF,DB: policy guard resolves the cookie to claims,<br/>renewing the token when expired or stale
    end
```

**Notes:**
- **Role changes apply immediately:** if an admin loses the Admin role, the next call sees the new token
  version and is refused.
- **Logout:** `POST /bff/logout` ends the console session and the SSO session behind it.

---

## 4. Downstream web or desktop app login (PKCE)

This applies to a **Browser app** client (public, no secret), for example SNVR-web, or the desktop app with a
loopback redirect `http://127.0.0.1:<port>/callback`.

```mermaid
sequenceDiagram
    autonumber
    actor User
    participant App as Your app (SNVR-web / desktop)
    participant OA as Auth Server /oauth/*
    participant Login as /login page
    participant API as Your server (SDK)

    App->>App: make code_verifier + code_challenge (S256), state
    App->>OA: open GET /oauth/authorize?client_id&redirect_uri&code_challenge&state
    OA->>OA: redirect_uri must match exactly
    alt No SSO session
        OA-->>Login: 302 /login?return_to=...
        User->>Login: sign in (flow 2)
        Login-->>OA: back with auth_sso cookie
    else Already signed in (SSO)
        Note over OA: no prompt, straight through
    end
    OA-->>App: 302 redirect_uri?code=...&state=...
    App->>App: check state
    App->>OA: POST /oauth/token grant_type=authorization_code + code_verifier
    OA-->>App: access_token (10 min, aud=your app key) + refresh_token + id_token
    App->>API: GET /cameras  Authorization: Bearer access_token
    API->>API: auth.verify() locally (flow 7)
    API-->>App: 200 data
```

**Notes:**
- **Single sign-on:** once the user is signed in to one app, other apps get through without a password, because they share
  the `auth_sso` cookie.
- **Codes:** a code is single-use. If it's used twice, everything the code issued is revoked.
- **Public clients have no secret:** PKCE proves that the app redeeming the code is the one that started the
  login.
- **User details:** get the signed-in user's name and email from `GET /oauth/userinfo`, not from the token.

---

## 5. Refresh token rotation and logout

```mermaid
sequenceDiagram
    autonumber
    participant App as Your app
    participant OA as /oauth/*
    participant DB as PostgreSQL
    participant SDK as Downstream SDKs

    Note over App: access token expires after 10 min
    App->>OA: POST /oauth/token grant_type=refresh_token
    OA->>DB: claim refresh token (one conditional update)
    alt First use
        OA-->>App: new access token + NEW refresh token (old one dead)
    else Second use within the grace window (two tabs)
        OA-->>App: access token only, no new refresh token
    else Reuse after the window (stolen token)
        OA->>DB: end the whole session, audit "refresh reuse"
        OA->>SDK: session.revoked event
        OA-->>App: 400 invalid_grant, so sign in again
    end

    Note over App: user clicks Logout
    App->>OA: POST /oauth/logout (Bearer token or SSO cookie)
    OA->>DB: revoke session + its refresh tokens
    OA->>SDK: session.revoked {sid, sub} to every app
    Note over SDK: tokens with that sid are rejected at once,<br/>even though they haven't expired
```

---

## 6. Downstream server: SDK startup and sync

This is what `auth_sdk` does in the background after `await auth.start()`.

```mermaid
sequenceDiagram
    autonumber
    participant SDK as auth_sdk (in your server)
    participant File as state file (optional)
    participant AS as Auth Server

    SDK->>File: load cursor + instance_id (ignored if wrong issuer/app)
    SDK->>AS: POST /oauth/token grant_type=client_credentials (client_id + secret)
    AS-->>SDK: service token (15 min, scopes: events.read, permissions.read, users.read)
    SDK->>AS: GET /.well-known/jwks.json
    AS-->>SDK: public keys (next, active, retired)
    SDK->>AS: GET /v1/apps/{key}/permission-map
    AS-->>SDK: code → bit map + version (pv)

    alt No saved cursor, or cursor too old
        SDK->>AS: GET /v1/events/{key}/snapshot
        AS-->>SDK: user versions, disabled users, revoked sessions/clients, seq
        Note over SDK: now ready, verify() stops failing closed
    end

    SDK->>AS: GET /v1/events/{key}?after=seq&instance_id=... (SSE)
    loop Stream open
        AS-->>SDK: event: id=seq, data=signed event JWT
        SDK->>SDK: verify event signature, apply to memory
        SDK->>AS: POST /v1/events/{key}/ack {seq}
        SDK->>File: save cursor
        AS-->>SDK: ": keep-alive" every 15 s
    end

    alt token.expired (service token ended or client revoked)
        SDK->>AS: new service token, reconnect with after=seq
    else Connection lost
        SDK->>SDK: back off (exponential + jitter), reconnect with after=seq
    else 409 snapshot_required (offline longer than retention)
        SDK->>AS: snapshot again, then stream
    end
```

**What each event does in the SDK's memory:**

| Event | SDK reaction |
|---|---|
| `user.access_changed` / `user.disabled` | Raise the minimum token `ver` for that user / mark them disabled |
| `session.revoked` | Add the `sid` to the revoked set |
| `client.revoked` | Reject tokens that client issued before `revoked_at` |
| `key.rotated` | Reload JWKS; drop the key at once if `revoked` |
| `permissions.changed` | Reload the permission map |
| `members.changed` | Fire `on_change` callbacks (refresh your members/roles cache) |

The console's **Downstream sync** page shows each instance's cursor and lag, using the ack position.

---

## 7. Downstream server: checking a request

`auth.verify(token)` or `Depends(auth.require_perm("camera.view"))`. **No network call per request.**

```mermaid
flowchart TD
    A[Request with Bearer token] --> B{SDK synced and<br/>not stale?}
    B -- no --> X1[503 StaleAuthState<br/>fail closed]
    B -- yes --> C{Header alg = ES256<br/>and kid known?}
    C -- unknown kid --> C2[Reload JWKS once] --> C
    C -- revoked kid / bad alg --> X2[401 Invalid token]
    C -- ok --> D{Signature valid?<br/>typ = at+jwt<br/>iss, aud = my app<br/>not expired}
    D -- no --> X2
    D -- yes --> E{sub disabled?<br/>sid revoked?<br/>ver below minimum?<br/>client revoked?}
    E -- yes --> X3[401 Token has been revoked]
    E -- no --> F[Decode pm mask with permission map<br/>reload map if pv is newer]
    F --> G{require_perm / require_role<br/>satisfied?}
    G -- no --> X4[403 Forbidden]
    G -- yes --> H[Principal: sub, sid, roles, has_perm]
    H --> I[Your handler runs]
```

---

## 8. A change reaching every downstream server

Example: an admin removes the *Operator* role from Vikas in SNVR.

```mermaid
sequenceDiagram
    autonumber
    actor Admin
    participant Con as Console
    participant AS as Auth Server (replica A)
    participant DB as PostgreSQL
    participant B as Replica B
    participant SDK as NVR SDK (connected to B)
    participant NVR as NVR API

    Admin->>Con: remove role
    Con->>AS: PUT /v1/admin/users/{id}/roles
    rect rgb(235, 245, 255)
    Note over AS,DB: one transaction
    AS->>DB: update user_roles
    AS->>DB: bump ver for (Vikas, SNVR)
    AS->>DB: audit record
    AS->>DB: outbox row user.access_changed (gapless seq)
    AS->>DB: pg_notify('auth_events')
    end
    DB-->>B: NOTIFY (delivered only after commit)
    B->>DB: read outbox after the stream's cursor
    B-->>SDK: SSE user.access_changed {sub, ver}
    SDK->>SDK: min ver for Vikas = new ver
    SDK->>B: ack(seq)
    Note over NVR: Vikas's old token (old ver) is now refused.<br/>His app refreshes and gets a token without Operator.
```

**Guarantees:**
- **Never out of step:** the change and its event are committed together, so neither can exist without the other.
- **Never lost:** a downstream server that was offline replays from its cursor on reconnect.
- **Worst case:** if the stream is down, old tokens still die within 10 minutes when they expire.

---

## 9. Server to server: service tokens and token exchange

```mermaid
sequenceDiagram
    autonumber
    actor User
    participant A as Server A (e.g. NVR)
    participant AS as Auth Server
    participant B as Server B (e.g. analytics)

    rect rgb(240, 248, 240)
    Note over A,B: Option 1: A calls B as itself
    A->>AS: POST /oauth/token client_credentials, audience=B
    AS-->>A: service token (aud=B, 15 min)
    A->>B: call with Bearer service token
    B->>B: auth.verify_service() / Depends(auth.current_service)
    end

    rect rgb(248, 240, 240)
    Note over A,B: Option 2: A calls B on behalf of the user
    User->>A: request with user token (aud=A)
    A->>AS: POST /oauth/token grant_type=token-exchange<br/>subject_token=user token, audience=B
    AS->>AS: B must be in A's client audiences,<br/>permissions can only narrow
    AS-->>A: exchanged token (aud=B, act=A, 5 min)
    A->>B: call with exchanged token
    B->>B: auth.verify() → Principal for the user, actor = A
    end
```

---

## 10. Members and roles API

This flow is for pages like NVR's Access page: "give these cameras to this user or this role". The client needs the
`users.read` scope.

```mermaid
sequenceDiagram
    autonumber
    participant NVR as NVR server
    participant SDK as auth_sdk
    participant AS as Auth Server

    NVR->>SDK: await auth.list_all_members()
    loop until next_cursor is null
        SDK->>AS: GET /v1/apps/SNVR/members?limit=1000&cursor=...
        AS-->>SDK: {items: [{sub, username, names, email, is_active, roles}], next_cursor}
    end
    NVR->>SDK: await auth.roles()
    SDK->>AS: GET /v1/apps/SNVR/roles
    AS-->>SDK: [{id, name, description, permissions}]
    SDK-->>NVR: cache members + roles

    Note over AS,SDK: later, something changes
    AS-->>SDK: SSE members.changed / user.access_changed / user.disabled
    SDK->>NVR: on_change(event_type, payload), in the background
    NVR->>NVR: debounce ~1 s, then refetch members + roles
```

**Rules:**
- **User grants:** store them by `sub`.
- **Role grants:** store them by role `id`, never the name.
- **On a request:** map `principal.roles` names to ids through the cached roles list.

---

## 11. Signing key rotation and revocation

```mermaid
stateDiagram-v2
    [*] --> next: created (published in JWKS before signing)
    next --> active: rotate
    active --> retired: rotate (still verifies old tokens)
    retired --> expired: longest token lifetime + 5 min
    active --> revoked: DELETE /v1/admin/keys/{kid} (leak)
    retired --> revoked: DELETE (leak)
    expired --> [*]
    revoked --> [*]
```

```mermaid
sequenceDiagram
    autonumber
    participant Job as key_rotation_tick (one replica, advisory lock)
    participant DB as PostgreSQL
    participant Reps as All replicas
    participant SDK as Every downstream SDK

    Job->>DB: next → active, active → retired, create new next
    Job->>DB: outbox key.rotated (every app) + NOTIFY auth_keys
    DB-->>Reps: drop key cache
    DB-->>SDK: SSE key.rotated {kid}
    SDK->>SDK: reload JWKS (already had the new key as "next")
    Note over SDK: on revoke: key.rotated {kid, revoked: true},<br/>tokens signed with it are refused at once
```

---

## 12. Running several replicas

```mermaid
flowchart TB
    LB[Load balancer / nginx<br/>proxy_buffering off for SSE]
    LB --> R1[Replica 1]
    LB --> R2[Replica 2]
    LB --> R3[Replica N]

    subgraph Shared
        PG[(PostgreSQL<br/>data, sessions, outbox,<br/>advisory locks, LISTEN/NOTIFY)]
        RD[(Redis<br/>counters, challenges)]
    end

    R1 & R2 & R3 --> PG
    R1 & R2 & R3 --> RD
    PG -. "NOTIFY auth_events / auth_keys" .-> R1 & R2 & R3
```

| Concern | How it's handled |
|---|---|
| A change made on replica 1, a stream open on replica 3 | Every replica LISTENs; NOTIFY wakes all of them, and streams read the outbox |
| A missed NOTIFY | Streams also poll the outbox every 5 s |
| Background jobs | Postgres advisory lock, so only one replica runs each job per tick |
| Signing key cache | `NOTIFY auth_keys` clears it on every replica |
| Sessions and login state | Postgres and Redis, so no sticky sessions are needed |
| A downstream server reconnects to another replica | Its cursor is in Postgres, so it resumes from the same seq |

---

## Related documents

| Document | What it covers |
|---|---|
| `auth-server/docs/ARCHITECTURE.md` | Design decisions and failure behaviour |
| `auth-server/docs/API.md` | Every endpoint |
| `auth-server/docs/INTEGRATION.md` | Step-by-step guide to connecting a downstream app |
| `sdk/README.md` | SDK reference |
| `docs/FEATURES.md` | Full feature list |
