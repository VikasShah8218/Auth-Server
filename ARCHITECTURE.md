# Centralized Auth Server: Architecture

The high-level design only. Implementation detail belongs in separate specs.

## 1. Goal

One system decides **who someone is** and **what they may do**. Every downstream server can then:

- trust a token **without calling the auth server** on each request
- learn about revocations **within seconds**
- keep working when the auth server is briefly down

## 2. Core principles

| Principle | Decision |
|---|---|
| Standards first | OAuth 2.1 and OpenID Connect, on proven libraries for all cryptography and JWT handling |
| Only the auth server can sign | Asymmetric keys (ES256). Downstream servers hold public keys only |
| Verify locally, revoke by push | JWT signature checks need no network call, and revocations arrive as events |
| Tokens are short-lived and audience-bound | A token for service A is rejected by service B |
| Postgres is the source of truth | Redis holds only data that can be lost or rebuilt |
| Fail closed | Anything unknown, unverifiable or too stale is denied |

## 3. System overview

```
    Browser / Mobile apps                      Admin console
            |                                       |
            | login, refresh                        | manage users, roles, clients
            v                                       v
+------------------------------------------------------------------------+
|                         AUTH SERVER (stateless, N replicas)            |
|                                                                        |
|  +----------------+  +----------------+  +---------------+  +--------+ |
|  | Identity plane |  | Token plane    |  | Admin plane   |  | Event  | |
|  | login, MFA,    |  | OAuth/OIDC,    |  | users, roles, |  | plane  | |
|  | SSO sessions   |  | exchange, JWKS |  | apps, clients |  | stream | |
|  +----------------+  +----------------+  +---------------+  +--------+ |
+-----+------------------+------------------+-------------------+--------+
      |                  |                  |                   |
      v                  v                  v                   | signed
+------------+     +-----------+     +--------------+           | events,
| Postgres   |     | Redis     |     | KMS / Vault  |           | JWKS
| truth,     |     | cache,    |     | private      |           |
| outbox,    |     | limits,   |     | signing keys |           |
| audit      |     | challenges|     |              |           |
+------------+     +-----------+     +--------------+           |
                                                                v
     +----------------------------------------------------------------+
     |  DOWNSTREAM SERVERS (each one embeds the Auth SDK)             |
     |  verify JWT | cached JWKS | revocation cache | policy check    |
     |  service token worker | event consumer | ack sender            |
     +----------------------------------------------------------------+
            ^                                     |
            |  request with access token          |  service-to-service call
         Clients                                  |  with exchanged token
                                                  v
                                         Other downstream servers
```

Build it as a **modular monolith**: one deployable with four internal planes. Splitting into microservices would add failure modes without adding value here. The planes can still be scaled or exposed separately, for example by keeping the admin plane on an internal network.

## 4. The four planes

**Identity plane: proves who the user is.** It hosts the single login page, passwords (Argon2id), MFA (TOTP and WebAuthn), and the SSO session. Apps never see a password, so logging in once covers every app.

Permissions are stored as integer bits rather than strings, which keeps tokens short. Each permission owns a permanent bit in its application, and a token carries the combined integer in the `pm` claim, encoded as base64url.

**Token plane: issues and exchanges tokens.**

| Flow | Used by | Standard |
|---|---|---|
| Authorization Code + PKCE | Browser and mobile apps | OAuth 2.1 |
| Client Credentials | Server acting as itself | OAuth 2.1 |
| Token Exchange | Server acting for a user | RFC 8693 |
| Refresh rotation | Clients renewing a session | OAuth 2.1 |
| JWKS endpoint | Downstream servers fetching public keys | RFC 7517 |

**Admin plane: manages access.** It covers applications, users, roles, permissions and service clients. All endpoint rules live in one fail-closed policy file, and every change writes an audit record.

**Event plane: tells downstream servers what changed.** See section 6.

## 5. Tokens

| Token | Lifetime | Format | Stored by the server |
|---|---|---|---|
| Access | 5 to 10 min | Signed JWT | No |
| Refresh | Days to weeks, rotated on each use | Opaque random value | Hash only |
| Service | 5 to 15 min | Signed JWT | No |
| Exchanged | 5 min at most | Signed JWT | No |

Key claims:

```
iss  who issued it          sid  login session id
aud  the one target app     ver  version for user + app
sub  stable user id         act  calling service (exchange only)
exp  expiry                 kid  signing key id (JWT header)
pm   permission mask        pv   permission map version
roles                       for this audience only
```

Rules:

- **Revocation is scoped.** `sid` ends one session, and `ver` is per user per app, so leaving one app doesn't log the user out of the others.
- **Exchange authenticates the calling service.** Requested scope narrows both permissions and roles, and can never widen them.
- **Browsers don't hold tokens in `localStorage`.** A backend-for-frontend keeps them behind `HttpOnly` cookies.
- **Signing keys rotate on a schedule.** Old public keys stay in JWKS until every token signed with them has expired.
- **Refresh tolerates honest races.** A short grace window stops two open tabs from looking like token theft.

## 6. Revocation and downstream sync

This is the core of the system: how every server stays in step.

```
 Admin / logout action
        |
        v
 Postgres transaction: change the data + write event to OUTBOX   (atomic)
        |
        v
 Publisher assigns a per-app sequence number
        |
        v
 SSE stream to downstream ----> apply to revocation cache ----> send ACK(seq)
        ^                                                             |
        |                                                             v
        +--- reconnect with Last-Event-ID                  Auth server records
             (replay what was missed)                      last-acked seq per
                                                           server and alerts on lag
```

- **Why an outbox:** a change can never be saved without its event, or the reverse. Plain Redis pub/sub loses any message sent while a server is disconnected.
- **Why SSE:** downstream servers make an outbound connection, so it works through firewalls and needs no broker. Move to NATS JetStream or Kafka only if scale demands it.
- **Why a sequence number and ACK:** every server can resume exactly where it stopped, and the console shows which servers are behind.
- **If replay is no longer possible:** the server fetches a full snapshot, then continues from that sequence.

Event types: `session.revoked`, `user.access_changed`, `user.disabled`, `client.revoked`, `key.rotated`, `permissions.changed`.

A revocation doesn't wait for ACKs. The stream makes it fast, and the short access token lifetime is the guaranteed upper limit.

## 7. Downstream Auth SDK

Ship one versioned package instead of copy-pasted handover code. Each server gets the same behaviour:

- JWT verification (`iss`, `aud`, `exp`, signature) using cached JWKS
- revocation cache and event consumer, with ACK and replay
- service token worker with retries that survive Redis and network failures
- local policy enforcement, using the same single-file rule model
- a health signal reporting how stale the server's auth state is

## 8. Failure behaviour

| Failure | Result |
|---|---|
| Auth server down | Existing tokens keep working until expiry. New logins and refreshes fail |
| Event stream down | Servers run stale, for at most one access token lifetime. High-risk servers can deny after 60 seconds of staleness |
| Redis down | Tokens still verify. Login degrades, and rate limiting must fail closed |
| Postgres primary down | Failover to a standby. Token issuing pauses, while local verification continues |
| Signing key leaked | Rotate the key, remove it from JWKS, and publish `key.rotated`. Every downstream server rejects the old `kid` at once |

## 9. Deployment

```
            Load balancer / TLS
                    |
        +-----------+-----------+
        |           |           |
     Auth #1     Auth #2     Auth #3      stateless
        |           |           |
        +-----+-----+-----+-----+
              |           |
      Postgres HA      Redis HA           + KMS / Vault
      (primary +       (cache only)
       standby)
```

- All traffic uses TLS. Internal service traffic uses mTLS where possible.
- Startup fails if any secret is missing or still set to a default.
- Secrets come from Docker secrets, Vault or KMS, never from committed files. Private signing keys sit behind a `KeyProvider` interface: version 1 encrypts them in Postgres under a master key, and a Vault provider can replace it.
- The public edge has rate limiting, with restricted CORS origins.
- Audit logs are append-only and shipped off the server.
- For on-premises or edge sites, a remote server needs only cached JWKS and its event cursor to keep verifying during a network cut.

## 10. Build or adopt

| Option | Choose it when |
|---|---|
| **Keycloak, Zitadel or Ory** | Standard SSO and RBAC are enough, and you'd rather not own security-critical code |
| **Custom server on a proven OAuth/OIDC library** | You need custom downstream sync, ACK tracking or air-gapped operation |

**Recommendation:** build custom, because acknowledged downstream sync is your real differentiator. Never hand-write cryptography. No async OAuth server library fits this model, so the flows are thin endpoints on `joserfc`, which makes passing the OpenID conformance suite essential.

## 11. What changes from the current server

| Today | Target |
|---|---|
| Shared HS256 secret across every server | Asymmetric keys, with JWKS |
| Apps collect passwords and call `/login` | Hosted login, with SSO and PKCE |
| One `token_version` per user | `sid` plus a per-user, per-app `ver` |
| Redis pub/sub, with snapshot on connect | Postgres outbox, sequence numbers, replay and ACK |
| `/token-exchange` with no caller authentication | Authenticated client, with narrowing of roles and permissions |
| Handover code copied into each server | Versioned Auth SDK |
| Tokens in `localStorage` | `HttpOnly` cookies through a backend-for-frontend |

**Keep as they are:** the application, role and permission data model, the single-file API policy, refresh rotation with reuse detection, and the separate service client model.
