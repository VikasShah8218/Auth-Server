# Deploying with Docker Compose

One command runs the whole Auth Server: the API, the web console, PostgreSQL and Redis, behind Caddy with
automatic HTTPS.

```
Internet ──443/80──> caddy ──> api (uvicorn, N workers) ──> postgres (volume)
                       │                                └─> redis (memory only)
                       └─ serves the console (built SPA)
                     migrate: runs `aerich upgrade` once before api starts
```

| Service | Image | Measured RAM (idle) |
|---|---|---|
| caddy | `auth-server-web` (Caddy + console, ~67 MB image) | ~18 MB |
| api | `auth-server-api` (python:3.13-slim, ~220 MB image), 2 workers | ~165 MB |
| postgres | `postgres:17-alpine` | ~45 MB |
| redis | `redis:7-alpine` | ~8 MB |
| **Total** | | **~240 MB** |

Only Caddy publishes ports. The API, PostgreSQL and Redis are reachable only on the private Compose network.

## 1. Install

**Requirements:**
- Docker with Compose v2. On a Linux server, Docker Engine is enough; Docker Desktop isn't needed.
- For a real certificate: a domain whose DNS points at this host, with ports 80 and 443 open.

```bash
cd Auth-Server/deploy
cp .env.example .env
```

Edit `.env`:

| Setting | Value |
|---|---|
| `DOMAIN` | `auth.example.com` (or `localhost` / an IP for a LAN test) |
| `ISSUER` | `https://auth.example.com`, exactly what browsers use. Add the port if it isn't 443 |
| `MASTER_KEY` | `openssl rand -base64 32 \| tr '+/' '-_' \| tr -d '='` |
| `DB_PASSWORD` | `openssl rand -hex 24` |

```bash
docker compose up -d --build
docker compose ps            # every service healthy, migrate "Exited (0)"
```

## 2. First administrator

```bash
docker compose run --rm api python cli.py create-admin --username admin --email you@example.com
```

It prompts for the password. Then open `https://<DOMAIN>` and sign in.

To pass the password without a prompt, for example in a script:

```bash
echo 'the-password' | docker compose run --rm -T api python cli.py create-admin --username admin --email you@example.com --password-stdin
```

## 3. Everyday commands

| Task | Command |
|---|---|
| Status | `docker compose ps` |
| Logs | `docker compose logs -f api` (or `caddy`, `postgres`) |
| Restart the API | `docker compose restart api` |
| Upgrade | `git pull && docker compose up -d --build` (migrations run automatically first) |
| Stop | `docker compose down` (data is kept in volumes) |
| More workers | set `WORKERS=4` in `.env`, then `docker compose up -d` |
| Readiness | `curl https://<DOMAIN>/health/ready` |

## 4. Backup and restore

```bash
./backup.sh                                 # writes backups/auth-YYYYMMDD-HHMMSS.sql.gz, keeps the newest 14
KEEP=30 ./backup.sh                         # keep more

# restore into the running stack
gunzip -c backups/auth-20261114-030000.sql.gz | docker compose exec -T postgres psql -U auth -d auth
```

Schedule backups with cron: `0 3 * * * /opt/Auth-Server/deploy/backup.sh`.

> ⚠️ **Back up `.env` as well, especially `MASTER_KEY`.** The database dump contains encrypted signing keys and
> TOTP secrets, and they can only be decrypted with that key. A dump without the key can't be fully restored.

## 5. Important notes

- **`ISSUER` is permanent in practice.** Tokens, cookies and passkeys are tied to it. Changing the domain later
  signs everyone out and makes existing passkeys stop working.
- **Production checks:** the API refuses to start with a non-https `ISSUER`, a weak `MASTER_KEY`, or a known
  default database password.
- **Redis has no persistence on purpose.** It holds only rate-limit counters and login challenges. If it
  restarts, in-progress sign-ins start over; nothing else is lost.
- **Real client IPs:**
  - Caddy sets `X-Forwarded-For`, and the API trusts it because only Caddy can reach it. Rate limits then
    see the real address.
  - On Docker Desktop (Windows or Mac), every request appears to come from the Docker gateway. On a Linux
    host it's the real IP.
- **Non-standard ports** (`HTTPS_PORT=8443`): put the port in `ISSUER`. Caddy's http→https redirect assumes
  443, so open the `https://` URL directly.
- **Downstream servers** (SDK) connect to `https://<DOMAIN>` like any client. The event stream passes through
  Caddy unbuffered (`flush_interval -1`).

## 6. Development: only PostgreSQL and Redis in Docker

```bash
docker compose -f docker-compose.dev.yml up -d
```

PostgreSQL is published on `127.0.0.1:5433` and Redis on `127.0.0.1:6380`. Point `auth-server/.env` at them as
the comments in `docker-compose.dev.yml` show, then run the API and `npm run dev` natively.

## 7. Already running nginx instead of Caddy?

Serve `auth-client/dist` and proxy the API paths. Keep the event stream unbuffered:

```nginx
location ~ ^/(v1|oauth|bff|\.well-known|health)/ {
    proxy_pass http://127.0.0.1:8000;
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
}
location /v1/events/ {
    proxy_pass http://127.0.0.1:8000;
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_buffering off;
    proxy_read_timeout 1h;
}
location / {
    root /opt/Auth-Server/auth-client/dist;
    try_files $uri /index.html;
}
```

## Files

| File | Purpose |
|---|---|
| `docker-compose.yml` | Production stack |
| `docker-compose.dev.yml` | PostgreSQL + Redis only, for local development |
| `Caddyfile` | TLS, console, API proxy (mounted, so edits need only `docker compose restart caddy`) |
| `.env.example` | Every setting an operator changes |
| `backup.sh` | Database backups with rotation |
| `../auth-server/Dockerfile` | API image (multi-stage, non-root) |
| `../auth-client/Dockerfile` | Console build + Caddy image |
