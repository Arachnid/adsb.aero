# CLAUDE.md

ADS-B historical query platform at adsb.aero. Map-based UI for querying flight trajectories from the adsb.lol archive.

**Read `docs/design-spec.md` first** — it contains all architectural decisions. This file lists only what's universally true across every task.

## Stack

- Database: PostgreSQL 17 + PostGIS 3.5+
- Server: Python (FastAPI + asyncpg + Dramatiq), in `server/`
- Web: TypeScript + React + Vite + MapLibre + deck.gl, in `web/`
- Deployment: Docker Compose

## Working in this repo

- Conventional Commits for messages
- Pre-commit must pass before any commit (`ruff`, `mypy --strict`, `eslint`, `prettier`, `sqlfluff`, tests with coverage)
- New code includes its tests in the same change. Coverage drops on changed files block the commit.
- Type hints on every Python function. TypeScript strict mode, no `any` without a comment justifying it.

**Update CLAUDE.md** any time something doesn't work the first time and you learn the correct approach. This file should always reflect what is actually true about working in this repo.

## Test-running

- Server: `cd server && .venv/bin/pytest` — **must run from `server/`** so `pyproject.toml` is picked up (asyncio mode, testpaths, coverage config all live there). Running `server/.venv/bin/pytest` from the repo root silently uses wrong defaults. Integration tests use testcontainers; Docker must be running.
- Web: `pnpm test` (vitest)
- E2E: `pnpm e2e` (Playwright; requires the dev stack up via `docker compose up`)
- Coverage: `pytest --cov` and `pnpm test --coverage`

## Docker

All `docker` commands (including `docker exec`, `docker ps`, `docker compose`) suppress tabular and interactive output when stdout is not a TTY. Always pipe through `cat`: `docker ps | cat`, `docker exec infra-postgres-1 psql ... | cat`, etc.

**psql errors go to stderr**: always append `2>&1` before `| cat` when running psql so errors are visible: `docker exec infra-postgres-1 psql -U adsb -d postgres -c "..." 2>&1 | cat`. Without `2>&1`, a failed psql command silently produces no output.

**Dropping the adsb database**: connect to the `postgres` database, not `adsb`, otherwise psql fails with "cannot drop the currently open database": `docker exec infra-postgres-1 psql -U adsb -d postgres -c "DROP DATABASE IF EXISTS adsb;" 2>&1 | cat`. Recreate with `CREATE DATABASE adsb TEMPLATE template_mobilitydb;`.

**Compose setup**: All compose files live in `infra/`. Run all `docker compose` commands from that directory. The `.env` file lives at the repo root; `infra/.env` is a symlink to it (create once with `ln -sf ../.env infra/.env` if missing).

**Dev stack**: `make dev` (or `cd infra && docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d`). Adds the `vite` service and mounts `infra/nginx/dev.conf`. Browser entry point: `http://localhost`.

**Prod stack**: `make build-web && make prod` (or `cd infra && docker compose -f docker-compose.yml up -d`). Nginx serves `web/dist` and proxies `/api/` to the api container.

**Container names**: The compose project is `infra`, so containers are named `infra-<service>-1` (e.g. `infra-postgres-1`, `infra-api-1`, `infra-nginx-1`). Use these names for `docker stop`, `docker logs`, `docker exec`, etc. — `docker compose stop <service>` also works when run from `infra/`.

**Rebuilding a service**: `docker compose -f docker-compose.yml -f docker-compose.dev.yml up --build -d <service>` from `infra/` (include both `-f` flags when in dev).

**Full dev setup guide**: `docs/dev-setup.md`.

## Web / TypeScript types

After any Python API model change, regenerate frontend types with `make gen-types` (runs from repo root). This exports the OpenAPI schema from the live FastAPI app and runs `openapi-typescript` to update `web/src/types/api.ts`. Do not edit that file by hand.

`pnpm tsc --noEmit` for a type-check without building. The `dist/` directory may be owned by root (written by Docker); if `pnpm build` fails with EACCES on `dist/`, that's a permissions issue unrelated to the code — use `sudo -A rm -rf web/dist` to clear it.

## Python environment

Use `python -m venv server/.venv && server/.venv/bin/pip install -e ".[dev]"` to set up the server virtualenv. Activate with `source server/.venv/bin/activate` before running Python tools.

## Things to surface rather than guess

- Schema or query DSL changes: discuss before implementing — they're expensive to undo.
- New top-level dependencies: justify, since this is a single-operator project and every dependency is a maintenance cost.
- Anything contradicting `docs/design-spec.md`: flag the contradiction; don't pick one silently.

## Things not to do

- Don't add new microservices. Server, web, and the Postgres+Redis pair is the topology.
- Don't bypass the query DSL with bespoke endpoints for specific query shapes.
- Don't introduce ORM-level abstractions over PostGIS — the SQL is the interface.