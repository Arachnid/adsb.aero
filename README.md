# adsb.aero

Map-based UI for querying historical ADS-B flight trajectories from the [adsb.lol](https://adsb.lol) archive.

## Architecture

- **Database**: PostgreSQL 17 + PostGIS 3.5 + MobilityDB, partitioned by week
- **Server**: Python — FastAPI (query API) + ingestion workers
- **Web**: TypeScript + React + Vite + MapLibre GL JS + deck.gl
- **Deployment**: Docker Compose on a single dedicated server

See [docs/design-spec.md](docs/design-spec.md) for full architectural decisions and [docs/dev-setup.md](docs/dev-setup.md) for environment setup.

## Quick start

```bash
cp .env.example .env          # add ENVIRONMENT=development for local dev

# Dev stack (Vite dev server + hot reload)
make dev
# Browser: http://localhost

# Or prod stack
make build-web && make prod
```

Full setup including terrain data and initial data import: see [docs/dev-setup.md](docs/dev-setup.md).

### Running server or web outside Docker (optional)

```bash
# Server
python -m venv server/.venv && server/.venv/bin/pip install -e "server/.[dev]"
cd server && .venv/bin/uvicorn adsb_server.api.main:app --reload

# Web
cd web && pnpm install && pnpm dev
```

## Testing

```bash
# Server (integration tests require Docker running)
cd server && .venv/bin/pytest --cov

# Web
cd web && pnpm test

# E2E (requires full stack via docker compose up)
cd web && pnpm e2e
```

## Implementation status

- [x] Repo skeleton + tooling
- [x] Schema + Python DB tooling (PostgreSQL + PostGIS + MobilityDB)
- [x] Ingestion pipeline — batch ingest, flight splitting, TD-TR simplification, scalar time series (track/GS/VR/IAS as MobilityDB tint)
- [x] API — JSON DSL query endpoint, flight detail, bulk paths, airspace lookup
- [x] GFS altitude correction — per-vertex QNH corrections from GFS MSLP (Herbie/cfgrib), stored as `alt_correction_ft` at ingest; altitude queries accept ft or FL
- [x] AGL height — per-vertex above-ground-level height from Copernicus GLO-90 DEM, stored as `path_agl_ft` at ingest; `download-terrain` downloads tiles, `backfill-agl` fills historical data
- [ ] Frontend — map UI with query builder, results panel, flight detail
- [ ] Reference data — Doc 8643 emitter-category mapping, OpenAIP airspace, OurAirports airports
- [ ] OurAirports integration (radius-from-airfield pickers)
- [ ] OpenSky aircraft metadata enrichment
- [ ] Scale up (whole-world ingest, performance tuning)
