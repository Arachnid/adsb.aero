# Dev setup

The full stack runs in Docker Compose. In dev, nginx proxies HMR-aware to a Vite dev server; in prod, nginx serves the pre-built `web/dist` bundle. Both environments share the same entry point: `http://localhost:80`.

## Prerequisites

- Docker (with Compose v2 — `docker compose` not `docker-compose`)
- Node 22+ and pnpm (`npm i -g pnpm` or via corepack)
- Python 3.14 and a virtualenv for running server tests locally

## First-time setup

```bash
# 1. Copy the env template and fill in passwords
cp .env.example .env
$EDITOR .env

# 2. Create the infra .env symlink (once per clone)
ln -sf ../.env infra/.env

# 3. Set up the Python virtualenv (for local test runs only — not needed for Docker)
python -m venv server/.venv
server/.venv/bin/pip install -e "server/[dev]"

# 4. Start the dev stack
make dev

# 5. Apply the database schema (once per fresh database)
#    Postgres uses trust auth for localhost — no password env var needed.
make migrate

# 6. Seed airframe reference data (registration, model, operator, etc.)
#    Takes ~2 min; re-run any time to pull the latest tar1090-db snapshot.
make import-airframes
```

## Starting the dev stack

```bash
make dev
# or explicitly:
# cd infra && docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d
```

This brings up:

| Service    | What it does                                              |
| ---------- | --------------------------------------------------------- |
| `postgres` | PostgreSQL 17 + PostGIS                                   |
| `redis`    | Redis 7 (Dramatiq broker)                                 |
| `api`      | FastAPI with `--reload` (restarts on Python source saves) |
| `vite`     | Vite dev server with HMR                                  |
| `nginx`    | Entry point at `:80` — proxies `/api/` → api, `/` → vite |
| `scheduler`| Ingestion scheduler (background, not needed for UI work)  |

Open `http://localhost` in the browser. HMR is active — saving a `.tsx` file updates the page without a full reload.

## Daily use

```bash
make logs               # tail all service logs
make dev-down           # stop and remove containers (volumes are preserved)

# Rebuild the API image after adding a Python dependency:
cd infra && docker compose -f docker-compose.yml -f docker-compose.dev.yml up --build -d api

# Force-reinstall node_modules (e.g. after adding a package):
cd infra && docker compose -f docker-compose.yml -f docker-compose.dev.yml down -v
make dev
```

## Running tests

```bash
# Server (uses testcontainers — Docker must be running)
server/.venv/bin/pytest

# Web unit tests
cd web && pnpm test

# E2E (requires the dev stack to be up)
cd web && pnpm e2e
```

## Production build

```bash
# Build the frontend bundle into web/dist
make build-web

# Start the prod stack (nginx serves web/dist directly — no Vite)
make prod
```

The prod stack uses the same `docker-compose.yml` without the dev overrides. Nginx serves `web/dist` as static files and proxies `/api/` to the API container.

## Architecture

```
Browser ──► nginx :80
              ├── /api/* ──► api :8000 (FastAPI)
              └── /*
                    dev:  ──► vite :5173 (Vite dev server + HMR)
                    prod: ──► web/dist (static files)
```

The nginx config for dev is at `infra/nginx/dev.conf`; for prod, `infra/nginx/prod.conf`. The dev override (`infra/docker-compose.dev.yml`) mounts `dev.conf` over `prod.conf` in the nginx container and adds the Vite service.
