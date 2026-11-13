# Auth Client

The Auth Server's web app: the hosted sign-in page for every connected app, self-service for every user, and
the admin console. React 19, TypeScript, Vite, Tailwind CSS v4, TanStack Router and Query, Radix primitives.

- Design (locked source of truth): [`../ui-design/`](../ui-design/README.md)
- Plan and decisions: [`../docs/CLIENT_IMPLEMENTATION_PLAN.md`](../docs/CLIENT_IMPLEMENTATION_PLAN.md)
- API it talks to: [`../auth-server/docs/API.md`](../auth-server/docs/API.md)

## Run

Start the API first (`py main.py` in `../auth-server`, port 8000), then:

```bash
npm install
npm run dev          # http://localhost:5181
```

The dev server proxies `/v1`, `/oauth`, `/bff`, `/.well-known` and `/health` to the API, so the browser sees
one origin. The server's `ISSUER` must be `http://localhost:5181`.

| Setting | Default | Meaning |
|---|---|---|
| `PORT` | `5181` | Dev server port |
| `API_TARGET` | `http://127.0.0.1:8000` | Where API paths are proxied |

## Commands

| Command | What it does |
|---|---|
| `npm run dev` | Dev server with hot reload |
| `npm run build` | Type check, then production build into `dist/` |
| `npm run lint` | oxlint (React, a11y, imports) |
| `npm run format` | Prettier, including Tailwind class order |
| `npm test` | Unit and component tests (Vitest) |
| `npm run e2e` | End-to-end tests against a real server (below) |
| `npm run gen:api` | Regenerate `src/api/schema.d.ts` from `openapi/auth.json` |
| `npm run analyze` | Build with a bundle report in `dist/stats.html` |

After any server API change:

```bash
cd ../auth-server && py cli.py export-openapi --out ../auth-client/openapi/auth.json
cd ../auth-client && npm run gen:api
```

## End-to-end tests

They start their own API on port 8010 with a throwaway database `auth_e2e` (next to the server's test
database) and their own client on port 5182, then drive Microsoft Edge. Your development data is never touched.

```bash
AUTH_PYTHON=../server/.venv/Scripts/python.exe npm run e2e
```

`AUTH_PYTHON` is a Python with the server's requirements. `PW_CHANNEL=chrome` uses Chrome instead of Edge.
`SCREENS_DIR=./screens npm run e2e -- screens` saves screenshots of the main screens for design review.

## How it works

- **No tokens in the browser.** The console holds only the HttpOnly `auth_console` cookie (backend-for-frontend).
  Writes send `X-CSRF-Token` from `GET /bff/session`. A `401` on the console API restarts sign-in.
- **The login page serves every app.** `/login?return_to=/oauth/authorize?...` returns there after sign-in.
  `return_to` is accepted only as a same-origin `/oauth/authorize` path (`src/lib/returnTo.ts`), so the page
  can't be used as an open redirect.
- **Admins and everyone else.** A user without the `Admin` role on `AUTH` sees only My account; admin routes
  redirect there.
- **URL state.** Filters, paging and tabs live in the URL, so they survive reloads and can be shared.
- **Small first load.** Every page is its own chunk. The login page (what every app's users load) skips the
  shell, menus, dialogs, form library and toasts: about 128 KB gzipped, most of it React and the router.

## Layout

```
src/
├── main.tsx, router.tsx     providers; routes, guards, lazy pages
├── pages/<area>/            screens; components/ for pieces used by that area only
├── components/ui/           base pieces (Button, Input, Dialog, Tabs, DropdownMenu, ...)
├── components/common/       shared app pieces (PageHeader, DataTable, KeyCut, ConfirmDialog, ...)
├── components/layout/       AppShell, Sidebar, Topbar, AuthLayout, ThemeToggle, UserMenu
├── api/                     typed client and one hooks file per resource
├── hooks/, lib/             shared hooks; helpers (errors, format, returnTo, search, validation)
└── styles/index.css         design tokens as Tailwind theme, light and dark
```

Rules: `components/` never imports from `pages/`; a page area never imports another area's files; pages call
the API only through `src/api/`.
