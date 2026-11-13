# Members and Roles API for Downstream Servers: Implementation Plan

Lets a downstream server (first user: Shah-NVR, app `SNVR`, client `snvr-a`) list **who holds a role in its own
application and which roles exist**, using its service token. NVR needs it for its Access page, where an NVR
admin gives cameras to a user or a role, including people who have never signed in to NVR.

| Source | Location |
|---|---|
| Request | `Shah-NVR/docs/AUTH_V2_MEMBERS_ENDPOINT_PROMPT.md` |
| Existing pattern to copy | `GET /v1/apps/{key}/permission-map` in `auth-server/app/events/router.py` |
| API and events reference | `auth-server/docs/API.md`, `auth-server/docs/ARCHITECTURE.md` section 9 |

## Status

**M1 to M6 are done.**

| Check | Result |
|---|---|
| Server tests | 319 passed (11 new in `tests/test_service_members.py`). 3 fail only because of the temporary password rules in `app/users/utils.py` (minimum 4, username check off) |
| `policy_audit` | 71 routes, 0 on the default rule |
| Migration 4 | Tried on a scratch database with existing roles: backfilled, unique, not null, downgrade clean |
| SDK tests | 24 passed (3 new) |
| Client | lint clean, build OK, 36 tests passed |
| Live run (real server, throwaway database) | members paged and complete, roles with codes, rename keeps the role id, `on_change` fires on rename and profile change, a client without `users.read` still syncs and gets a clear error |

Where the build differs from this plan:

| Plan said | Built | Why |
|---|---|---|
| Missing scope raises `AuthError` | Raises a new `MissingScope` | `AuthError` means "reject this caller with 401"; a missing scope is this server's own setup problem |
| Inactive app → 404 | 401 | The service token of a deactivated app is already refused when it's checked, before the route runs |
| `gen:api` unchanged | `gen:api` now also runs Prettier on `schema.d.ts` | Regenerating produced a whole-file diff of indentation only |

---

## 1. Decisions

The request doc was checked against the code. These points differ from it or settle what it left open.

| # | Topic | Decision | Why |
|---|---|---|---|
| D1 | **Role identity** | Add a stable `public_id` (UUID) to roles. Both endpoints return roles as `{id, name}`, where `id` is that UUID | NVR stores camera grants per role. A grant keyed by name breaks silently when an admin renames the role. Internal integer ids stay hidden, as the request asks |
| D2 | **Refresh event** | Add `members.changed`. Existing events don't fire for: role created, role description changed, role renamed or deleted when it has no members, user's name or email changed | Checked in `applications/services.py` and `users/services.py`. `bump_versions` returns early on an empty user list, so a memberless role change publishes nothing |
| D3 | **Paging** | Keyset paging on username: `?limit=` (default 200, max 1000), `?cursor=`, answer `{items, next_cursor}` | Stable under concurrent changes and fast on large lists. It differs from the admin lists (`limit`/`offset` + `total`); `API.md` says so |
| D4 | **Scope in the SDK** | No scope logic in `start()` | The server already gives a service token every scope its client holds (`oauth/services.py`, client credentials). A client without `users.read` keeps working; `members()` turns the 403 into a clear error |
| D5 | **Email** | Included | All clients are first-party (version 1). Noted in `API.md` as personal data downstream servers must protect |
| D6 | **Permission codes in `/roles`** | Active permissions only; retired ones are left out | Retired bits grant nothing |
| D7 | **Snapshot** | The SDK treats taking a snapshot as "refresh everything" too | After a long disconnect, missed `members.changed` events are gone; the snapshot is the moment to reload |

Out of scope, as requested: write endpoints, changes to admin endpoints or schemas, names in tokens, changes to
the token format, `pm`, or existing event payloads.

---

## 2. API

### `GET /v1/apps/{key}/members`

**Service token with scope `users.read`**, for the client's own application only.

| Query | Default | Notes |
|---|---|---|
| `limit` | 200 | 1 to 1000 |
| `cursor` | none | Opaque, from `next_cursor` |
| `q` | none | Case-insensitive contains on username, first name, last name, email |

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
  "next_cursor": null
}
```

- Users holding at least one role in this app, sorted by username. Disabled users are included with
  `is_active: false`.
- `sub` is the user's `public_id`, the same value as the `sub` claim in their access tokens.
- `given_name`, `family_name`, `email` are `null` when empty (OIDC userinfo names, so the data merges with
  `/oauth/userinfo` without mapping).
- `roles` are this app's roles only, sorted by name.
- Never returned: password hash, MFA state, superuser flag, sessions, integer ids.
- `cursor` is base64url of the last username on the page. It's opaque to callers and validated on input
  (`422 invalid_cursor` when malformed).

### `GET /v1/apps/{key}/roles`

Same authentication.

```json
[
  { "id": "1b7e...", "name": "Admin", "description": "Full access", "permissions": ["*"] },
  { "id": "93d0...", "name": "Operator", "description": null, "permissions": ["camera.view", "live.view"] }
]
```

- Every role of the app, sorted by name. `name` is exactly what appears in the token's `roles` claim.
- `permissions` are active permission codes, sorted.

### Errors (both)

| Status | Code | When |
|---|---|---|
| 401 | `not_authenticated` / `invalid_token` | No token, a bad one, or a **user** token |
| 403 | `insufficient_scope` | The service token lacks `users.read` |
| 403 | `wrong_application` | The client belongs to another application |
| 404 | `not_found` | The application is missing or inactive |
| 422 | `invalid_cursor` | Malformed cursor (members only) |

### Event `members.changed`

| Payload | Sent to | When |
|---|---|---|
| `{}` | the role's app | role created, description changed, or renamed or deleted (always, members or not) |
| `{"sub": "<uuid>"}` | every app where the user holds a role | the user's first name, last name or email changed |

Signed and delivered through the transactional outbox like every other event. The existing events keep their
meaning, and downstream servers refresh on any of `user.access_changed`, `user.disabled` and `members.changed`.

---

## 3. Changes by file

### Server (`auth-server/`)

| File | Change |
|---|---|
| `app/applications/models.py` | `Role.public_id = fields.UUIDField(default=uuid4, unique=True)` |
| `migrations/models/4_<timestamp>_role_public_id.py` | Add the column, fill existing rows with `gen_random_uuid()`, then make it `NOT NULL UNIQUE`. Generated with `aerich migrate --name role_public_id`, then checked by hand for the backfill |
| `app/applications/services.py` | Split `application_members()` into a query helper `members_query(app_id, q, after, limit)` used by the admin endpoint (no limit) and the new service endpoint (keyset page). Admin output unchanged. Add `service_roles(app)` (roles plus active permission codes). Publish `members.changed` in `create_role`, `update_role` (any change) and `delete_role` |
| `app/users/services.py` | `update_user`: when `first_name`, `last_name` or `email` change, publish `members.changed` with `{"sub"}` to each app where the user holds a role, in the same transaction |
| `app/events/schemas.py` | `ServiceRoleRef {id, name}`, `ServiceMemberOut`, `ServiceMembersPage {items, next_cursor}`, `ServiceRoleOut` |
| `app/events/router.py` | `read_users = require_service_scope("users.read")`; `GET /{key}/members` and `GET /{key}/roles` on `apps_router`, both through `services.bound_app(key, claims)` |
| `app/security/policy.py` | `"GET /v1/apps/{key}/members"` and `"GET /v1/apps/{key}/roles"` as `SelfGuarded("service token, scope users.read")` |
| `app/applications/schemas.py` | Admin `RoleOut` gains `public_id` (additive only, so the console can show it later; no existing field changes) |

### SDK (`sdk/`)

| Item | Change |
|---|---|
| `auth.members(q=None, limit=200, cursor=None) -> dict` | One page: `{items, next_cursor}` |
| `auth.list_all_members() -> list[dict]` | Follows `next_cursor` to the end |
| `auth.roles() -> list[dict]` | All roles |
| Missing scope | A 403 `insufficient_scope` raises `AuthError("Client needs scope users.read ...")` |
| `auth.on_change(callback)` | Registers an async callback, called after `user.access_changed`, `user.disabled`, `members.changed` and after a snapshot. Errors in a callback are logged and never stop the sync loop |
| `auth.members_version` | Integer that rises on the same moments, for servers that poll instead |
| Version | `0.3.0`; README gains rows for the new methods and the scope note |

All calls reuse the cached service token, the 401 retry, and `api_url`.

### Console (`auth-client/`)

| File | Change |
|---|---|
| `src/pages/clients/components/ClientDialog.tsx` | `users.read` help text: "List this app's members and roles (downstream servers)" |
| `openapi/auth.json`, `src/api/schema.d.ts` | Regenerated (`py cli.py export-openapi --out ...`, `npm run gen:api`) |

### Docs

| File | Change |
|---|---|
| `auth-server/docs/API.md` | Section 11 gains both endpoints with shapes and errors; scope table describes `users.read`; event list gains `members.changed` |
| `auth-server/docs/ARCHITECTURE.md` | Event table gains `members.changed`; data model notes `roles.public_id` |
| `auth-server/docs/INTEGRATION.md` | New section "Listing your app's users": scope, endpoints, caching, refresh events, keying grants by `sub` and role `id` |
| `docs/FEATURES.md` | `users.read` described; members and roles endpoints listed under downstream sync |
| `sdk/README.md` | New methods, `on_change`, scope note |

---

## 4. Phases

Each phase ends with its check passing before the next starts.

### M1. Role public id
Model field, migration with backfill, admin `RoleOut.public_id`.
**Check:** `aerich upgrade` on a copy of the dev database fills every existing role; full `pytest` passes.

### M2. Endpoints
Schemas, `members_query` refactor, `service_roles`, the two routes, policy entries.
**Check:** new tests 1 to 5 (section 5) pass; `python -m app.security.policy_audit` passes; admin members
endpoint output is unchanged (existing tests).

### M3. `members.changed`
Publishing in role create, update, delete and in profile changes.
**Check:** test 6 passes; existing event tests still pass.

### M4. SDK 0.3.0
Methods, scope error, `on_change`, `members_version`, version bump.
**Check:** SDK tests pass, including the existing 21; `tests/test_sdk_e2e.py` in the server still passes.

### M5. Console and docs
Help text, regenerated schema, all doc updates.
**Check:** `npm run lint` and `npm run build` pass in `auth-client`.

### M6. Live check
Throwaway database (as in the client's e2e setup): create app `SNVR`, client with `users.read`, roles and
users, then drive the SDK: list members and roles, rename a role and change a profile, and see `on_change` fire
and the new data arrive.
**Check:** the run passes end to end, and the report for the NVR side (section 7) is written.

---

## 5. Tests

### Server (`auth-server/tests/test_service_members.py`, real Postgres)

1. With `users.read`: `sub` equals the user's `public_id` and their token's `sub`; names, email, roles of this
   app only; disabled users flagged; no forbidden fields in the response.
2. Without `users.read` → 403 `insufficient_scope`. User access token → 401. No token → 401.
3. Client of app A asking for app B → 403 `wrong_application`; inactive app → 404.
4. Paging: a limit/cursor walk returns every member exactly once, in username order; `q` filters on username,
   names and email; a malformed cursor → 422.
5. Roles: names, ids, active permission codes (a retired one is absent); another app's users and roles never
   appear.
6. `members.changed`: role create, description change, rename and delete (with and without members) emit it
   for that app only; a profile change emits it with `sub` for each of the user's apps and none other; a
   change that touches no name or email emits nothing new.
7. `policy_audit` passes (existing policy test).

### SDK (`sdk/tests/test_sdk.py`, fake server)

- `members()` one page; `list_all_members()` follows the cursor across pages.
- `roles()`.
- Missing scope → clear `AuthError`.
- `start()` and verification still work for a client without `users.read`.
- `on_change` fires on `members.changed`, `user.access_changed`, `user.disabled` and after a snapshot; a
  failing callback doesn't stop the sync; `members_version` rises.

---

## 6. Risks

| Risk | Handling |
|---|---|
| Migration on existing data | Backfill in the migration itself; tried on a copy of the dev database first (M1) |
| Admin members output changes by accident | Refactor keeps the admin call path and shape; existing admin tests guard it |
| Event noise | `members.changed` carries no user list and is cheap; downstream servers debounce refreshes (documented) |
| Personal data spreading | Only clients explicitly given `users.read` can read it, only for their own app; documented in `API.md` |

---

## 7. Report for the NVR side

**Setup:** in the console, tick `users.read` on client `snvr-a`. Install SDK 0.3.0 (`pip install -e path/to/sdk`).

**Endpoints** (service token, own app only):

| Call | Answer |
|---|---|
| `GET /v1/apps/SNVR/members?limit=200&cursor=&q=` | `{"items": [{"sub", "username", "given_name", "family_name", "email", "is_active", "roles": [{"id", "name"}]}], "next_cursor"}` |
| `GET /v1/apps/SNVR/roles` | `[{"id", "name", "description", "permissions": ["live.view", ...]}]` |

Errors: `403 insufficient_scope` (no `users.read`), `403 wrong_application`, `422 invalid_cursor`, `401` (user
token, or the app is deactivated).

**SDK:**

| Use | Code |
|---|---|
| All members | `await auth.list_all_members()` |
| One page / search | `await auth.members(q="vik", limit=200, cursor=None)` |
| Roles | `await auth.roles()` |
| Refresh hook | `@auth.on_change` on `async def refresh(event_type, payload)` |
| Polling alternative | `auth.members_version` |
| Missing scope | raises `auth_sdk.MissingScope` |

**Refresh signals:** `user.access_changed`, `user.disabled`, `members.changed` (new), and `"snapshot"`, all
delivered through `on_change`. Debounce: several can arrive together.

**Keys to store in NVR grants:** the member's `sub` (equals `principal.sub` on requests) and the role's `id`
(a UUID that survives renames). Never the role name. To check a request against role grants, map the token's
`roles` names to ids through the cached `roles()` list.

**Before the dev server can serve this:** run `aerich upgrade` in `auth-server` (migration 4 adds role ids).
