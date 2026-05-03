# adsb.aero

Map-based UI for querying historical ADS-B flight trajectories from the [adsb.lol](https://adsb.lol) archive.

## Architecture

- **Database**: PostgreSQL 17 + PostGIS 3.5, partitioned by month
- **Server**: Python — FastAPI (query API) + Dramatiq (ingestion workers)
- **Web**: TypeScript + React + Vite + MapLibre GL JS + deck.gl
- **Deployment**: Docker Compose on a single dedicated server

See [docs/design-spec.md](docs/design-spec.md) for full architectural decisions.

## Quick start

```bash
cp .env.example .env          # fill in POSTGRES_PASSWORD
docker compose -f infra/docker-compose.yml up -d

# Server (dev)
cd server
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
uvicorn adsb_server.api.main:app --reload

# Web (dev)
cd web
pnpm install
pnpm dev
```

## Testing

```bash
# Server (integration tests require Docker)
cd server && source .venv/bin/activate && pytest --cov

# Web
cd web && pnpm test

# E2E (requires full stack via docker compose up)
cd web && pnpm e2e
```

## Implementation status

- [x] Step 1: Repo skeleton + tooling
- [ ] Step 2: Schema + reference data
- [ ] Step 3: Ingestion pipeline (batch, no staging)
- [ ] Step 4: Staging flights
- [ ] Step 5: API v1
- [ ] Step 6: Frontend v1
- [ ] Step 7: Frontend v2
- [ ] Step 8: ERA5 + QNH correction
- [ ] Step 9: Operational stack
- [ ] Step 10: Scale up
