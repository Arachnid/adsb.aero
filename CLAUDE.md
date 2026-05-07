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

## Test-running

- Server: `pytest` from an activated venv, or `server/.venv/bin/pytest` (integration tests use testcontainers; Docker must be running)
- Web: `pnpm test` (vitest)
- E2E: `pnpm e2e` (Playwright; requires the dev stack up via `docker compose up`)
- Coverage: `pytest --cov` and `pnpm test --coverage`

## Docker

All `docker` commands (including `docker exec`, `docker ps`, `docker compose`) suppress tabular and interactive output when stdout is not a TTY. Always pipe through `cat`: `docker ps | cat`, `docker exec infra-postgres-1 psql ... | cat`, etc.

**Compose setup**: All compose files live in `infra/`. Run all `docker compose` commands from that directory. The `.env` file lives at the repo root; `infra/.env` is a symlink to it (create once with `ln -sf ../.env infra/.env` if missing).

**Container names**: The compose project is `infra`, so containers are named `infra-<service>-1` (e.g. `infra-postgres-1`, `infra-scheduler-1`). Use these names for `docker stop`, `docker logs`, `docker exec`, etc. — `docker compose stop <service>` also works when run from `infra/`.

**Rebuilding a service**: `docker compose up --build -d <service>` from `infra/`. This rebuilds the image and recreates the container in one step.

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