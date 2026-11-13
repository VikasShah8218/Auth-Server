# Auth Server Client: Implementation Plan

A new React client for the Auth Server, built from scratch in a new folder `auth-client/`, next to `auth-server/`.
The old `client/` stays untouched until the new one replaces it (phase 10).

| Source of truth | Location |
|---|---|
| Visual design (locked) | `ui-design/`: `index.html`, 4 pages, `assets/tokens.css`, `assets/components.css`, `README.md` |
| API | `auth-server/docs/API.md` and the OpenAPI schema from `py cli.py export-openapi` |
| Server behaviour | `auth-server/docs/ARCHITECTURE.md` |

**Rule:** if the React app and `ui-design/` disagree, `ui-design/` wins. A design change is made there first, then
carried into React.

## Status

**P0 to P9 and S are done.** P10 (nginx and removing the old `client/`) waits for the Docker phase.

| Check | Result |
|---|---|
| Server tests (with the phase S additions) | 311 passed |
| Client type check, lint, production build | clean |
| Client unit and component tests | 36 passed |
| End-to-end against the real server | 4 passed: wrong password, open-redirect refusal, admin builds an app and grants access (KeyCut shows the held bit), non-admin limits plus TOTP setup and sign-in |
| Visual review against `ui-design/` | light, dark, phone width |

Where the build differs from this plan, and why:

| Plan said | Built | Why |
|---|---|---|
| TanStack Table | A small typed `DataTable` | Paging and filters are on the server; a table engine would only add weight |
| Separate `keys-admin`, `downstream`, `audit`, `stats` API files | One `api/operations.ts` | Four small read-mostly resources; one file is easier to find |
| Application tabs include Overview | Overview is the page header; Permissions starts with the app's bit map (KeyCut) | Nothing else to show on an Overview tab |
| Login form on React Hook Form + Zod | Plain state for the two login fields | Keeps the form library off the page every app's users load |
| First load ≤ 120 KB gzip | 128 KB measured | React, React DOM and the router alone are about 100 KB; everything optional is already split out |

---

## 1. What the client is

One single-page app with three jobs:

| Job | Who | Pages |
|---|---|---|
| **Sign-in** for every connected app (the hosted login page) | everyone | Login, MFA |
| **Self-service** | every signed-in user | My account: profile, password, sessions, MFA |
| **Administration** | users with the `Admin` role on `AUTH` | Dashboard, Applications, Users, Clients, Signing keys, Downstream sync, Audit log |

A signed-in user without `Admin` sees only **My account**.

---

## 2. Stack

| Need | Choice |
|---|---|
| Core | React 19, TypeScript (strict), Vite |
| Styling | Tailwind CSS v4, tokens from `ui-design/assets/tokens.css` as `@theme` |
| Components | shadcn/ui on Radix primitives, restyled to the locked design |
| Routing | **TanStack Router** (code-based routes, typed search params for filters and paging) |
| Server state | TanStack Query |
| API client | `openapi-typescript` (generated types) + `openapi-fetch` |
| Forms | React Hook Form + Zod |
| Tables | TanStack Table (headless) |
| WebAuthn | `@simplewebauthn/browser` |
| QR code (TOTP setup) | `qrcode.react` |
| Icons | `lucide-react` |
| Toasts | `sonner` |
| Fonts | `@fontsource-variable/*` for Schibsted Grotesk, IBM Plex Sans, IBM Plex Mono (self-hosted) |
| Dates | the browser's `Intl` (no date library) |
| Lint / format | oxlint + Prettier (with the Tailwind class-sorting plugin) |
| Tests | Vitest + Testing Library, Playwright end to end |

Not used: Redux, MUI or Ant Design, moment, lodash, chart libraries.

---

## 3. Folder structure

```
auth-client/
├── index.html
├── package.json
├── vite.config.ts            dev server 5181, proxy to the API on 8000
├── tsconfig.json
├── openapi/auth.json         written by: py cli.py export-openapi --out ../auth-client/openapi/auth.json
├── public/
├── tests/e2e/                Playwright
└── src/
    ├── main.tsx              providers: QueryClient, Router, Theme, Toaster
    ├── router.tsx            all routes, guards, lazy pages
    │
    ├── pages/
    │   ├── auth/             Login.tsx, MfaVerify.tsx, components/ (OtpInput, SecurityKeyButton)
    │   ├── dashboard/        Dashboard.tsx, components/ (SyncTable, KeyCard, ActivityList)
    │   ├── applications/     ApplicationsList.tsx, ApplicationDetail.tsx, components/ (tabs, dialogs)
    │   ├── users/            UsersList.tsx, UserDetail.tsx, components/ (AccessTab, SessionsTab, MfaTab, ProfileTab)
    │   ├── clients/          ClientsList.tsx, ClientDetail.tsx, components/ (SecretOnceDialog)
    │   ├── keys/             SigningKeys.tsx
    │   ├── downstream/       DownstreamSync.tsx
    │   ├── audit/            AuditLog.tsx
    │   ├── account/          MyAccount.tsx, components/ (TotpSetup, SecurityKeys, MySessions, ChangePassword)
    │   └── errors/           NotFound.tsx, Forbidden.tsx
    │
    ├── components/
    │   ├── ui/               Button, Input, Select, Badge, Chip, Card, Tabs, DropdownMenu, Dialog, Alert,
    │   │                     Avatar, Tooltip, Skeleton, Switch, Textarea
    │   ├── common/           PageHeader, StatStrip, DataTable, TableToolbar, Pagination, FormField,
    │   │                     ConfirmDialog, EmptyState, ErrorState, ListRow, KeyCut, CopyButton, StatusBadge
    │   └── layout/           AppShell, Sidebar, Topbar, AuthLayout, ThemeToggle, UserMenu
    │
    ├── api/
    │   ├── schema.d.ts       generated, never edited
    │   ├── client.ts         openapi-fetch instance + middleware (cookies, CSRF, 401, errors)
    │   ├── keys.ts           query key factory
    │   ├── session.ts        useSession, useLogout
    │   ├── identity.ts       login, MFA, WebAuthn sign-in
    │   ├── account.ts        /v1/me hooks
    │   ├── applications.ts   applications, permissions, roles, members
    │   ├── users.ts          users, roles, sessions, password, MFA reset
    │   ├── clients.ts
    │   ├── keys-admin.ts     signing keys
    │   ├── downstream.ts
    │   ├── audit.ts
    │   └── stats.ts
    │
    ├── hooks/                useDebounce, useMediaQuery, useCopy, useDocumentTitle
    ├── lib/                  cn, format (dates, numbers, user agent), returnTo, errors, masks, constants
    └── styles/index.css      @theme tokens, light and dark, base styles
```

Rules:
- A component used by one page area lives in that area's `components/`. It moves to `src/components/common/`
  when a second area needs it.
- `components/` never imports from `pages/`. Pages never import from another area's folder.
- Pages never call `fetch`. They use hooks from `api/`.
- Absolute imports through the `@/` alias.

---

## 4. How the client talks to the server

### 4.1 Same origin

In development Vite serves the client on **5181** and proxies these paths to the API on **8000**:
`/v1`, `/oauth`, `/bff`, `/.well-known`, `/health`.

The server's `ISSUER` is `http://localhost:5181`, so every redirect, cookie and WebAuthn origin is on the client's
origin. In production nginx does the same (phase 10).

### 4.2 The console session (backend-for-frontend)

The browser never holds a token. It holds the HttpOnly `auth_console` cookie, set by the server.

```
App start
  └─ GET /bff/session
       ├─ 200 → user, roles, is_admin, csrf_token  → render the app
       └─ 401 → window.location = /bff/login
                  └─ server → /oauth/authorize (PKCE)
                       ├─ SSO cookie valid → /bff/callback → sets auth_console → /
                       └─ no SSO cookie → /login?return_to=/oauth/authorize?...   (our Login page)
```

- `csrf_token` from `/bff/session` is kept in memory and sent as `X-CSRF-Token` on every non-GET request.
- Any `401` from the API clears the cached session and goes to `/bff/login`.
- `403` shows the Forbidden page or an inline message, never a redirect loop.
- **Sign out:** `POST /bff/logout` (ends the console session and the SSO session), then go to `/login`.

### 4.3 The hosted login page

`/login` is also the login page for **every other app** (ANPR, NVR...). It doesn't need a console session.

1. `POST /v1/identity/login` with username and password.
2. `status: "authenticated"` → go to `return_to`.
   `status: "mfa_required"` → show the MFA step with `challenge` and `methods`.
3. MFA: `POST /v1/identity/mfa/verify` (TOTP), or `POST /v1/identity/webauthn/options` then
   `POST /v1/identity/webauthn/verify` (security key).
4. On success, `window.location = return_to`.

**`return_to` safety (required):** accept it only when it is a same-origin path starting with
`/oauth/authorize?`. Anything else (absolute URLs, `//host`, `javascript:`, other paths) falls back to
`/bff/login`. This is the open-redirect rule from the server's security review; it gets its own unit tests.

Error codes to show: `invalid_credentials`, `too_many_attempts` (use `Retry-After`), `temporarily_unavailable`,
`invalid_code`, `mfa_challenge_expired` (back to the password step), `invalid_credential`. Also the
`?error=` value that `/bff/callback` sends back.

### 4.4 API client

- Types come from `openapi/auth.json` via `npm run gen:api`. Regenerate after every server API change. CI fails
  when the generated file is out of date.
- `openapi-fetch` middleware: `credentials: "same-origin"`, the CSRF header, 401 handling, and turning
  `{"detail": {"code", "message"}}` into a typed `ApiError` (also FastAPI's 422 lists).
- One query key factory (`api/keys.ts`), for example `keys.users.list(filters)` and `keys.users.detail(id)`.
- Every mutation invalidates exactly the queries it changes, and shows a toast that uses the button's own verb
  ("Disable user" → "User disabled").

---

## 5. Design system

1. **Tokens:** copy `ui-design/assets/tokens.css` into `src/styles/index.css` as Tailwind v4 `@theme` variables.
   Rename `--brass*` to `--accent*`. Dark mode uses the `data-theme` attribute (system by default, user choice
   remembered), exactly like the static pages.
2. **Fonts:** self-hosted through `@fontsource-variable`. No Google Fonts request.
3. **Components:** one React component per block in `components.css`, using the mapping table in
   `ui-design/README.md`. Variants are made with `class-variance-authority`.
4. **KeyCut:** `<KeyCut permissions={map} mask={pm} />` decodes the mask (little-endian base64url, as `BigInt`),
   draws one tooth per bit, hatches retired bits, shows codes on hover and focus, and gives screen readers a list
   of held permissions.
5. **A `/dev/components` page** (development builds only) shows every component in every state, next to the
   static page, for side-by-side review.

---

## 6. Pages and their endpoints

| Page | Route | Endpoints |
|---|---|---|
| Login | `/login` | `POST /v1/identity/login` |
| MFA | `/login` (step 2) | `POST /v1/identity/mfa/verify`, `POST /v1/identity/webauthn/options`, `.../verify` |
| Dashboard | `/` | `GET /v1/admin/stats`, `GET /v1/admin/downstream`, `GET /v1/admin/keys`, `GET /v1/admin/audit?limit=5` |
| Applications | `/applications` | `GET/POST /v1/admin/applications` |
| Application detail | `/applications/$key` | tabs: Overview (`GET/PATCH`), Permissions (list, create, edit, retire), Roles (CRUD + `PUT .../permissions`), Members (`GET .../members`), Clients (`GET /v1/admin/clients?app=`) |
| Users | `/users?q=&status=&app=&page=` | `GET/POST /v1/admin/users` |
| User detail | `/users/$id` | `GET/PATCH /v1/admin/users/{id}`, `PUT .../roles`, `GET/DELETE .../sessions`, `POST .../password`, `DELETE .../mfa`, `DELETE /v1/admin/sessions/{id}` |
| Clients | `/clients` | `GET/POST /v1/admin/clients` (secret shown once, with copy button and warning) |
| Client detail | `/clients/$clientId` | `GET/PATCH`, `POST .../rotate-secret` |
| Signing keys | `/keys` | `GET /v1/admin/keys`, `POST .../rotate`, `DELETE .../{kid}` (typed confirmation) |
| Downstream sync | `/downstream` | `GET /v1/admin/downstream`, refreshed every 10 s |
| Audit log | `/audit?actor=&action=&app=&since=&until=&page=` | `GET /v1/admin/audit` |
| My account | `/account` | `GET /v1/me`, `POST /v1/me/password`, sessions, TOTP (QR from `otpauth_uri`), WebAuthn register / remove |
| Not found / Forbidden | `*` | none |

All admin routes are guarded by `is_admin`; a non-admin is sent to `/account`.

---

## 7. Server additions needed

The locked design shows some data the API doesn't return yet. These are small, backward-compatible server
changes, done in phase S before the pages that need them:

| Design shows | Missing from the API | Server change |
|---|---|---|
| Users list: application chips and MFA badge | `UserOut` has neither | add `app_keys: list[str]` and `mfa_enabled: bool` to the list response |
| Users list: filter by application | no `app` filter | `GET /v1/admin/users?app=ANPR` |
| User detail: MFA tab (factors) | no admin endpoint for a user's factors | `GET /v1/admin/users/{id}/mfa` |
| User detail: KeyCut strip per app | permission bits per app not in `UserDetail` | add `bits: [{code, bit, held, retired}]` (or the app's mask + map) to each `applications[]` entry |
| Dashboard: "6 disabled", "across 29 people", app keys | `StatsOut` has 4 counts | add `disabled_users`, `session_users`, `application_keys` |
| Signing key card: next rotation date | client doesn't know `KEY_ROTATION_DAYS` | add `rotates_at` to the active key in `GET /v1/admin/keys` |
| Activity list: usernames, not UUIDs | `AuditOut.actor` is a public id | add `actor_name` (username or client id) |
| Sidebar counts | none | reuse the stats endpoint |

Each change gets a server test, a line in `auth-server/docs/API.md`, and a regenerated `openapi/auth.json`.

---

## 8. Phases

Each phase ends with its exit check passing. Nothing starts before the previous phase's check passes.

### P0. Project setup
Vite + React + TS strict, Tailwind v4, oxlint, Prettier, Vitest, Playwright, `@/` alias, the proxy, `gen:api`
script, and the folder structure from section 3.
**Exit:** `npm run dev`, `build`, `lint`, `test` all pass on an empty app served on 5181.

### P1. Design system
Tokens and fonts, light and dark, then every component in section 5 including `KeyCut`, plus the
`/dev/components` page.
**Exit:** `/dev/components` matches `ui-design/` side by side in both themes and at phone width.

### S. Server additions
The changes in section 7, with tests.
**Exit:** server tests pass and the regenerated schema has the new fields.

### P2. API layer and session
`api/client.ts` with its middleware, the key factory, `useSession`, route guards, the 401 and 403 behaviour, the
AppShell (sidebar, topbar, theme toggle, user menu, mobile drawer), Not found and Forbidden.
**Exit:** an unauthenticated visit to `/` goes through `/bff/login` to `/login`; with a session the shell renders
the user's name; a non-admin is sent to `/account`.

### P3. Login and MFA
Login, the MFA step (OTP input with paste, security key), all error states, and `return_to` validation.
**Exit:** a full PKCE login reaches the dashboard; TOTP and a virtual WebAuthn key both work; a bad `return_to`
is ignored (unit tests); lockout shows the wait time.

### P4. Dashboard
Stat strip, downstream sync table, signing key card, recent activity, loading skeletons and empty states.
**Exit:** matches `ui-design/dashboard.html`; stopping a downstream server marks it Offline within a minute.

### P5. Users
List with search, filters and paging kept in the URL; create user; detail with Access (KeyCut), Sessions, MFA,
Profile; edit roles; set password; reset MFA; disable and enable with confirm dialogs.
**Exit:** matches `ui-design/users.html` and `user-detail.html`; an admin can create a user, give roles in two
apps and disable the user without touching the API directly.

### P6. Applications
List and create; detail tabs for Overview, Permissions (create, describe, retire with warning), Roles (create,
rename, delete, set permissions), Members, Clients.
**Exit:** an admin creates an app, its permissions and a role, and assigns it to a user from the console.

### P7. Clients, signing keys, downstream sync, audit log
Clients list, create (secret shown once), edit, rotate secret, disable; signing keys with rotate and revoke;
downstream page with auto refresh; audit log with filters in the URL.
**Exit:** a service client is created and its secret copied once; rotating a key shows the new active key; audit
filters survive a page reload.

### P8. My account
Profile, change password (other sessions end), my sessions, TOTP setup with QR code and confirm, remove TOTP,
add and remove security keys (password step-up).
**Exit:** a user enables TOTP by scanning the QR code, signs out, and signs in with a code.

### P9. Quality pass
- Every page: loading, empty, error and success states.
- Keyboard: every action reachable, focus visible, dialogs trap focus, tabs use arrow keys.
- Phone width: tables become cards, the sidebar becomes a drawer.
- Performance budget (section 10) checked with the bundle visualiser.
- Playwright suite (section 9) green against a real server.
**Exit:** all of the above pass and the production build has no warnings.

### P10. Ship and replace
- nginx config: serve `dist/` with a fallback to `index.html`; proxy `/v1`, `/oauth`, `/bff`, `/.well-known`,
  `/health` to the API with SSE buffering off.
- Point the Docker phase at `auth-client/`.
- Remove the old `client/` folder.
**Exit:** a production build behind nginx passes the Playwright suite.

---

## 9. Testing

| Level | Tool | Covers |
|---|---|---|
| Unit | Vitest | `returnTo` validation, mask decoding, error mapping, formatters, user-agent labels |
| Component | Vitest + Testing Library | forms and their validation, ConfirmDialog, DataTable states, KeyCut, OtpInput |
| End to end | Playwright against a real server (test database, `create-admin` fixture) | login with and without MFA (TOTP from the secret, WebAuthn virtual authenticator), the admin flows from each exit check, non-admin limits, logout, phone layout |

---

## 10. Performance budget

| Item | Budget |
|---|---|
| First load (login page) JS | ≤ 130 KB gzip (measured: 128 KB) |
| Shell + dashboard JS | ≤ 180 KB gzip |
| Each other page chunk | ≤ 40 KB gzip |
| Fonts | 3 variable files, Latin subset, `font-display: swap` |

How: every page is a lazy route, Radix parts are imported per component, icons are imported one by one,
`qrcode.react` and `@simplewebauthn/browser` load only on the pages that use them, and queries use sensible
`staleTime` so revisits are instant.

---

## 11. Conventions

| Thing | Convention | Example |
|---|---|---|
| Page file | PascalCase, in `pages/<area>/` | `pages/users/UserDetail.tsx` |
| Component file | PascalCase, one component per file | `components/common/KeyCut.tsx` |
| Hook | `useX`, in `api/` or `hooks/` | `useUsers`, `useDisableUser` |
| API module | named after the server resource | `api/applications.ts` |
| Route path | lower-case, plural resources | `/users/$id` |
| URL state | filters and paging in search params | `/users?q=ana&status=active&page=2` |
| Copy | sentence case, button says what happens | "Disable user", toast "User disabled" |
| Errors | from the server's `code`, mapped in `lib/errors.ts` | `last_admin` → "At least one active administrator must remain." |
