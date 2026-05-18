.PHONY: dev dev-down prod prod-down logs build-web migrate import-airframes import-traces

# ── Dev stack ────────────────────────────────────────────────────────────────
# Brings up postgres, redis, api (--reload), vite dev server, and nginx.
# The browser entry point is http://localhost:80.
dev:
	cd infra && docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d

dev-down:
	cd infra && docker compose -f docker-compose.yml -f docker-compose.dev.yml down

# ── Production stack ─────────────────────────────────────────────────────────
# Requires a prior `make build-web` to populate web/dist.
build-web:
	cd web && pnpm build

prod:
	cd infra && docker compose -f docker-compose.yml up -d

prod-down:
	cd infra && docker compose -f docker-compose.yml down

# ── Database setup ────────────────────────────────────────────────────────────
# Run once after `make dev` on a fresh database (postgres uses trust auth for localhost).
migrate:
	cd server && .venv/bin/alembic upgrade head

import-airframes:
	cd server && .venv/bin/python -m adsb_server.reference_data.airframes

import-traces:
	cd infra && docker compose -f docker-compose.yml -f docker-compose.dev.yml run --rm import-traces

# ── Code generation ───────────────────────────────────────────────────────────
# Export the OpenAPI spec from the server and regenerate web TypeScript types.
# Run this after any change to server/adsb_server/query/models.py or the API routes.
gen-types:
	server/.venv/bin/python -c \
	  "from adsb_server.api.main import app; import json; print(json.dumps(app.openapi(), indent=2))" \
	  > server/openapi.json
	cd web && pnpm gen-types

# ── Helpers ───────────────────────────────────────────────────────────────────
logs:
	cd infra && docker compose logs -f
