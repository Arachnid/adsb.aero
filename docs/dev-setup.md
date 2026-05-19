# Dev setup

The full stack runs in Docker Compose. In dev, nginx proxies HMR-aware to a Vite dev server; in prod, nginx serves the pre-built `web/dist` bundle. Both environments share the same entry point: `http://localhost:80`.

## Prerequisites

- Docker (with Compose v2 — `docker compose` not `docker-compose`)
- Node 22+ and pnpm (`npm i -g pnpm` or via corepack)
- Python 3.14 and a virtualenv for running server tests locally

## First-time setup

```bash
# 1. Copy the env template (non-secret config only)
cp .env.example .env

# 2. Create the infra .env symlink (once per clone)
ln -sf ../.env infra/.env

# 3. Create secrets files (see "Secrets" section below)
mkdir -p infra/secrets
echo "your-openaip-api-key" > infra/secrets/openaip_api_key
echo "your-sentry-dsn"      > infra/secrets/sentry_dsn       # optional: leave blank to disable
# TLS certs for prod only (not needed for local dev):
# cp /path/to/origin.crt infra/secrets/origin.crt
# cp /path/to/origin.key infra/secrets/origin.key

# 4. Set up the Python virtualenv (for local test runs only — not needed for Docker)
python -m venv server/.venv
server/.venv/bin/pip install -e "server/[dev]"

# 5. Start the dev stack
make dev

# 6. Apply the database schema (once per fresh database)
make migrate

# 7. Seed airframe reference data (registration, model, operator, etc.)
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
| `api`      | FastAPI with `--reload` (restarts on Python source saves) |
| `vite`     | Vite dev server with HMR                                  |
| `nginx`    | Entry point at `:80` — proxies `/api/` → api, `/` → vite |
| `scheduler`| Ingestion scheduler (background, not needed for UI work)  |

Open `http://localhost` in the browser. HMR is active — saving a `.tsx` file updates the page without a full reload.

## Secrets

Sensitive values are kept in `infra/secrets/` as plain text files (gitignored). Docker Compose mounts them into containers at `/run/secrets/<name>`.

| File                          | Used by                          | What it is                                  |
| ----------------------------- | -------------------------------- | ------------------------------------------- |
| `infra/secrets/openaip_api_key` | `nginx`                        | OpenAIP API key for tile and airspace proxy |
| `infra/secrets/sentry_dsn`    | `api`, `scheduler`               | Sentry DSN for error reporting (optional)   |
| `infra/secrets/origin.crt`    | `nginx` (prod only)              | TLS origin certificate                      |
| `infra/secrets/origin.key`    | `nginx` (prod only)              | TLS origin private key                      |

`openaip_api_key` is required for the airspace overlay to work. The OpenAIP key is available from [account.openaip.net](https://account.openaip.net).

`sentry_dsn` is optional — leave the file empty or omit it to disable error reporting.

`origin.crt` and `origin.key` are only needed in production (HTTPS). The dev stack uses plain HTTP on port 80 and does not require these.

## Importing airframe reference data

The `airframes` table holds registration, model, operator, and flag data sourced from [tar1090-db](https://github.com/wiedehopf/tar1090-db). It is required for the API to return aircraft metadata alongside trajectories.

```bash
make import-airframes
# or directly:
cd server && .venv/bin/python -m adsb_server.reference_data.airframes
```

This downloads `aircraft.csv.gz` from the tar1090-db GitHub release, upserts ~600k rows into `airframes`, and exits. It takes about 2 minutes. The dev stack must be up (`make dev`) so that postgres is reachable at `localhost:5432`.

Re-run any time to pull the latest snapshot from upstream.

## Accessing postgres from the host

In dev, postgres is published to `127.0.0.1:5432`. It uses trust auth — no password required:

```bash
# via psql in the container (no port needed)
docker exec infra-postgres-1 psql -U adsb -d adsb

# from a local Python script
# postgresql://adsb@localhost/adsb  (no password)
```

In prod the port is not published; postgres is only reachable by the `api` and `scheduler` containers.

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
