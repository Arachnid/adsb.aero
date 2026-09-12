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
- Pre-commit hook blocks commits unless all checks pass: `ruff`, `mypy --strict`, `eslint`, `prettier`, `sqlfluff`, server pytest (with coverage), web tsc, web vitest (with coverage). Hook is in `.git/hooks/pre-commit`; install once after cloning with `server/.venv/bin/pre-commit install` (requires `core.hooksPath` to be unset — see below).
- New code includes its tests in the same change. Coverage drops on changed files block the commit.
- Type hints on every Python function. TypeScript strict mode, no `any` without a comment justifying it.

**Update CLAUDE.md** any time something doesn't work the first time and you learn the correct approach. This file should always reflect what is actually true about working in this repo.

## Test-running

- Server: `cd server && .venv/bin/pytest` — **must run from `server/`** so `pyproject.toml` is picked up (asyncio mode, testpaths, coverage config all live there). Running `server/.venv/bin/pytest` from the repo root silently uses wrong defaults. Integration tests use testcontainers; Docker must be running.
- Web: `pnpm exec vitest run`. **`pnpm test` is `vitest` with no arguments, i.e.
  watch mode** — it never exits, so it hangs any non-interactive run until it is
  killed. Vitest only drops watch on its own when `CI` is set in the environment,
  which is why `pnpm test:coverage` works in GitHub Actions but hangs locally.
  Pass `run` explicitly (or set `CI=true`) whenever you just want the result.
- E2E: `pnpm e2e` (Playwright; requires the dev stack up via `docker compose up`)
- Coverage: `pytest --cov` and `pnpm test --coverage`

## Docker

All `docker` commands (including `docker exec`, `docker ps`, `docker compose`) suppress tabular and interactive output when stdout is not a TTY. Always pipe through `cat`: `docker ps | cat`, `docker exec infra-postgres-1 psql ... | cat`, etc.

**psql errors go to stderr**: always append `2>&1` before `| cat` when running psql so errors are visible: `docker exec infra-postgres-1 psql -U adsb -d postgres -c "..." 2>&1 | cat`. Without `2>&1`, a failed psql command silently produces no output.

**Dropping the adsb database**: connect to the `postgres` database, not `adsb`, otherwise psql fails with "cannot drop the currently open database": `docker exec infra-postgres-1 psql -U adsb -d postgres -c "DROP DATABASE IF EXISTS adsb;" 2>&1 | cat`. Recreate with `CREATE DATABASE adsb TEMPLATE template_mobilitydb;`.

**Postgres auth**: Uses `trust` — no password. Connect with `postgresql://adsb@localhost/adsb` (dev) or `postgresql://adsb@postgres/adsb` (container-to-container). In dev the port is published to `127.0.0.1:5432`; in prod it is not. `POSTGRES_PASSWORD` is not set anywhere.

**Compose setup**: All compose files live in `infra/`. Run all `docker compose` commands from that directory. The `.env` file lives at the repo root; `infra/.env` is a symlink to it (create once with `ln -sf ../.env infra/.env` if missing).

**Dev stack**: `make dev` (or `cd infra && docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d`). Adds the `vite` service and mounts `infra/nginx/dev.conf`. Browser entry point: `http://localhost`.

**Prod stack**: `make build-web && make prod` (or `cd infra && docker compose -f docker-compose.yml up -d`). Nginx serves `web/dist` and proxies `/api/` to the api container.

**Container names**: The compose project is `infra`, so containers are named `infra-<service>-1` (e.g. `infra-postgres-1`, `infra-api-1`, `infra-nginx-1`). Use these names for `docker stop`, `docker logs`, `docker exec`, etc. — `docker compose stop <service>` also works when run from `infra/`.

**Rebuilding a service**: `docker compose -f docker-compose.yml -f docker-compose.dev.yml up --build -d <service>` from `infra/` (include both `-f` flags when in dev).

**Full dev setup guide**: `docs/dev-setup.md`.

## Web / TypeScript types

After any Python API model change, regenerate frontend types with `make gen-types` (runs from repo root). This exports the OpenAPI schema from the live FastAPI app, runs `openapi-typescript` to update `web/src/types/api.ts`, then runs prettier over the result. Do not edit that file by hand.

The prettier step is part of the target because `openapi-typescript` emits 4-space indent while the pre-commit prettier hook reformats to 2; without it a handful of real changes arrive buried under ~1500 lines of whitespace churn. If you see a diff that size on `api.ts`, that's what happened.

Do not run `prettier --write` over hand-written web sources: `web/.prettierrc` sets `printWidth: 100` but the committed code is wrapped at prettier's default 80, so a write pass reformats entire files. Match the surrounding wrapping instead. (`src/types/api.ts` is exempt — it's generated, so prettier owns its formatting outright.)

Also watch for schemas splitting into `-Input`/`-Output` pairs. Pydantic emits those when one model is reachable from both a request and a response and the two serialise differently — usually a sign that a response field is typed more broadly than what it can actually contain. Narrowing the response field (e.g. to `GeoJSONPolygon | GeoJSONMultiPolygon` rather than the whole `Geometry` union) is normally the right fix, and it keeps the generated types stable.

`pnpm tsc --noEmit` for a type-check without building. The `dist/` directory may be owned by root (written by Docker); if `pnpm build` fails with EACCES on `dist/`, that's a permissions issue unrelated to the code — use `sudo -A rm -rf web/dist` to clear it.

## Python environment

On a machine with no Python 3.14 and no Node — the `adsb` host itself, for
instance — both suites still run in containers, provided the repo is mounted at
the *same absolute path* it has on the host. `tests/conftest.py` shells out to
`docker build` for the postgres image, and the daemon resolves that build
context on the host, so a differing path inside the container fails the build.
Mount the docker socket, add the host's `docker` group with `--group-add` (a
plain `-u $(id -u)` cannot open the socket), and use `--network host` so
testcontainers' published ports are reachable:

```bash
docker run --rm --network host -v "$PWD:$PWD" -w "$PWD/server" \
    -v /var/run/docker.sock:/var/run/docker.sock -v /usr/bin/docker:/usr/bin/docker:ro \
    -u "$(id -u):$(id -g)" --group-add "$(stat -c %g /var/run/docker.sock)" \
    -e HOME="$PWD/.container-home" python:3.14-slim \
    bash -c '.venv/bin/pytest -q'
```

`tests/test_terrain/test_dem_downloader.py::test_tif_to_npy_from_bytes` fails
under `python:3.14-slim` because rasterio cannot import there; it passes in CI.

Use `python -m venv server/.venv && server/.venv/bin/pip install -e ".[dev]"` to set up the server virtualenv. `server/pyproject.toml` requires Python >= 3.14; with an older interpreter pip fails with "Package 'adsb-server' requires a different Python", so create the venv against 3.14 explicitly (`python3.14 -m venv server/.venv`, or `uv venv --python 3.14 server/.venv`) rather than relying on whatever `python` is on PATH. Activate with `source server/.venv/bin/activate` before running Python tools.

## Agent-facing docs

`web/public/llms.txt` is the API guide agents read, and for most of them it is
the *only* thing they read — the OpenAPI schema is ~100 KB. Treat it as part of
the API surface, not as prose:

- **Any DSL or endpoint change must update it in the same commit.**
  `server/tests/test_llms_txt.py` fails the commit if a predicate or route is
  missing from it, or if it names a predicate that doesn't exist. That guard
  exists because `docs/design-spec.md` documented `callsign_matches` for months
  after the code shipped `callsign_prefix`.
- It is hand-written on purpose. The judgement in it — which of two valid
  queries is the right one, which defaults silently give wrong answers — can't
  be generated from a schema.
- Static files under `web/public/` are served at the site root in both dev
  (Vite) and prod (copied into `dist/`, served by nginx). No nginx change needed
  to add one.

## Things to surface rather than guess

- Schema or query DSL changes: discuss before implementing — they're expensive to undo.
- New top-level dependencies: justify, since this is a single-operator project and every dependency is a maintenance cost.
- Anything contradicting `docs/design-spec.md`: flag the contradiction; don't pick one silently.

## Things not to do

- Don't add new microservices. Server, web, and Postgres is the topology.
- Don't bypass the query DSL with bespoke endpoints for specific query shapes.
- Don't introduce ORM-level abstractions over PostGIS — the SQL is the interface.
