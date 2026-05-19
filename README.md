# adsb.aero

Map-based UI for querying historical ADS-B flight trajectories from the [adsb.lol](https://adsb.lol) archive.

## Architecture

- **Database**: PostgreSQL 17 + PostGIS 3.5 + MobilityDB, partitioned by week
- **Server**: Python — FastAPI (query API) + Dramatiq (ingestion workers)
- **Web**: TypeScript + React + Vite + MapLibre GL JS + deck.gl
- **Deployment**: Docker Compose on a single dedicated server

See [docs/design-spec.md](docs/design-spec.md) for full architectural decisions.

## Quick start

```bash
cp .env.example .env          # add ENVIRONMENT=development for local dev

# Dev stack (Vite dev server + hot reload)
cd infra && docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d
# Browser: http://localhost

# Or prod stack
make build-web && cd infra && docker compose -f docker-compose.yml up -d
```

### Running server or web outside Docker (optional)

```bash
# Server
python -m venv server/.venv && server/.venv/bin/pip install -e "server/.[dev]"
source server/.venv/bin/activate
uvicorn adsb_server.api.main:app --reload

# Web
cd web && pnpm install && pnpm dev
```

## Testing

```bash
# Server (integration tests require Docker running)
cd server && source .venv/bin/activate && pytest --cov

# Web
cd web && pnpm test

# E2E (requires full stack via docker compose up)
cd web && pnpm e2e
```

## Implementation status

- [x] Repo skeleton + tooling
- [x] Schema + Python DB tooling (PostgreSQL + PostGIS + MobilityDB)
- [x] Ingestion pipeline — batch ingest, flight splitting, TD-TR simplification, scalar time series (track/GS/VR/IAS as MobilityDB tfloat)
- [x] API — JSON DSL query endpoint, flight detail, bulk paths, airspace lookup
- [x] GFS altitude correction — per-vertex QNH corrections computed from GFS MSLP (Herbie/cfgrib), stored at ingest, applied at query time; altitude queries accept ft or FL
- [x] Reference data — Doc 8643 emitter-category mapping, OpenAIP airspace overlay and zone selection
- [x] Frontend — full query builder (spatial predicates, altitude/time/squawk/dwell/distance filters), multiple colour modes (alt/cat/VS/GS/IAS/squawk), results panel with sparklines, rich hover infobox
- [ ] OurAirports integration (radius-from-airfield pickers)
- [ ] OpenSky aircraft metadata enrichment
- [ ] Operational stack (Prometheus / Grafana / Loki / alerting)
- [ ] Scale up (whole-world ingest, performance tuning)
