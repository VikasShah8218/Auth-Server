# Handoff: Members and Roles API (Auth Server → Shah-NVR)

For the agent building Shah-NVR's Access page (give cameras to a user or a role). This is what the Auth
Server now provides, and how NVR should use it. Everything below is built, tested, and live.

## 1. Setup (one time)

1. **Auth Server:** run `aerich upgrade` in `auth-server`, then restart it. Migration 4 adds role ids.
2. **Console:** open client `snvr-a` and tick the scope **`users.read`**. It keeps `events.read` and
   `permissions.read`.
3. **NVR:** install SDK **0.3.0**: `pip install -e D:\Drive-1\Shah-Secret-Project\Auth-Server\sdk`.

No new credentials are needed. The SDK reuses `snvr-a`'s service token.

## 2. Endpoints

Both need a **service token** with `users.read` (client credentials). They are read-only and return the
client's own app only.

### `GET /v1/apps/SNVR/members`

| Query | Default | Notes |
|---|---|---|
| `limit` | 200 | 1 to 1000 |
| `cursor` | none | Copy `next_cursor` from the previous page. Opaque |
| `q` | none | Case-insensitive match on username, first name, last name, email |

```json
{
  "items": [
    {
      "sub": "8f0c2a4e-1d3b-4c5e-9f00-123456789abc",
      "username": "vikas",
      "given_name": "Vikas",
      "family_name": "Shah",
      "email": "vikas@example.com",
      "is_active": true,
      "roles": [
        { "id": "1b7e0c2d-...", "name": "Admin" },
        { "id": "93d0aa41-...", "name": "Operator" }
      ]
    }
  ],
  "next_cursor": null
}
```

- **Who is listed:** every user holding at least one SNVR role, sorted by username. This includes people who
  never signed in to NVR.
- **Disabled users** are included with `is_active: false`.
- **`sub`** equals the `sub` claim in that user's access tokens, which is `principal.sub` in the SDK.
- **`given_name`, `family_name`, `email`** are `null` when not set.
- **`roles`** are SNVR roles only, sorted by name.
- **`next_cursor`** is `null` on the last page.

### `GET /v1/apps/SNVR/roles`

```json
[
  { "id": "1b7e0c2d-...", "name": "Admin", "description": "Full access", "permissions": ["*"] },
  { "id": "93d0aa41-...", "name": "Operator", "description": null, "permissions": ["camera.view", "live.view"] }
]
```

- **Every SNVR role**, sorted by name.
- **`id`** is a UUID that never changes, even when the role is renamed.
- **`name`** is exactly what appears in the token's `roles` claim.
- **`permissions`** lists active permission codes only; retired ones are left out.

### Errors

| Status | Code | Meaning |
|---|---|---|
| 401 | `not_authenticated` / `invalid_token` | No token, a user token, or SNVR is deactivated |
| 403 | `insufficient_scope` | `snvr-a` lacks `users.read` |
| 403 | `wrong_application` | The client belongs to another app |
| 422 | `invalid_cursor` | The cursor wasn't one the server issued |

## 3. New event: `members.changed`

It arrives on the existing event stream, signed and in order like the other events.

| Payload | When |
|---|---|
| `{}` | An SNVR role is created, renamed, has its description changed, or is deleted |
| `{"sub": "<uuid>"}` | A user's first name, last name or email changed (sent to every app where they hold a role) |

Your cached members or roles may be out of date after any of these:

| Signal | Cause |
|---|---|
| `user.access_changed` | Someone gained or lost a role, or was re-enabled |
| `user.disabled` | Someone was disabled |
| `members.changed` | Roles or profiles changed |
| `"snapshot"` | The SDK resynced after a long disconnect; events may have been missed |

The SDK ignores unknown event types, so nothing breaks for old consumers.

## 4. SDK 0.3.0

```python
from auth_sdk import AuthSDK, MissingScope

auth = AuthSDK(issuer=..., app_key="SNVR", client_id="snvr-a", client_secret=..., api_url=...)

members = await auth.list_all_members()          # every member, follows the cursor
page    = await auth.members(q="vik", limit=200)  # one page: {"items", "next_cursor"}
roles   = await auth.roles()                      # every role with permission codes

@auth.on_change                                   # runs in the background, never blocks the sync
async def refresh(event_type: str, payload: dict):
    cache.members = await auth.list_all_members()
    cache.roles = await auth.roles()
```

| API | Notes |
|---|---|
| `members(q=None, limit=200, cursor=None)` | One page |
| `list_all_members(q=None)` | All pages |
| `roles()` | All roles |
| `on_change(callback)` | Sync or async callback, called with `(event_type, payload)` on the four signals above. Also usable as a decorator. A failing callback is logged and never stops the sync |
| `members_version` | Integer that rises on the same signals, for code that polls |
| `MissingScope` | Raised by the three calls when `snvr-a` lacks `users.read`. Token verification keeps working without the scope |

Signals can arrive several at a time, so debounce the refresh (for example, wait 1 second and coalesce).

## 5. Rules for NVR's grants

1. **Store user grants by `sub`.** On a request, match `principal.sub`.
2. **Store role grants by role `id`, never the name,** because names can be renamed. On a request, map the
   token's `principal.roles` names to ids through the cached `roles()` list, then match grants.
3. **Show disabled members greyed out** (`is_active: false`). Don't delete their grants; they may be
   re-enabled.
4. **A deleted role disappears from `roles()`** (you'll get `members.changed`). Its grants then match no one.
   Show them as "role removed", or clean them up.
5. **Names and email are personal data.** Cache only what the Access page shows.
6. **Read-only.** NVR can't create users or change roles; that happens in the Auth Server console.

## 6. Not changed

- Token format, the `pm` permission mask, the `roles` claim, and every existing event payload are unchanged.
- No names or emails were added to access tokens. Use these endpoints, or `/oauth/userinfo` for the
  signed-in user.

## 7. References (in the Auth Server repo)

| Document | Section |
|---|---|
| `auth-server/docs/API.md` | Section 11: full endpoint reference |
| `auth-server/docs/INTEGRATION.md` | Section 10: "Listing your app's users and roles" |
| `sdk/README.md` | "Members and roles" |
| `docs/MEMBERS_API_IMPLEMENTATION_PLAN.md` | Decisions and test results |
