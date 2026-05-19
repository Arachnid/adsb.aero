.PHONY: dev dev-down prod prod-down logs build-web migrate import-airframes import-traces gen-cert

# ── Dev stack ────────────────────────────────────────────────────────────────
# Brings up postgres, redis, api (--reload), vite dev server, and nginx.
# The browser entry point is http://localhost:80.
dev:
	cd infra && docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d

dev-down:
	cd infra && docker compose -f docker-compose.yml -f docker-compose.dev.yml down

# ── Production stack ─────────────────────────────────────────────────────────
# Pull the latest images from GHCR, then start the stack.
# Static assets are baked into the web image — no local build step needed.
prod:
	cd infra && docker compose -f docker-compose.yml pull && docker compose -f docker-compose.yml up -d

# Build the web bundle locally (useful for testing the build outside Docker).
build-web:
	cd web && pnpm build

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

# ── TLS ───────────────────────────────────────────────────────────────────────
# Generate a self-signed origin certificate for use behind Cloudflare (Full SSL mode).
# Run once; the files land in infra/secrets/ which is gitignored.
gen-cert:
	openssl req -x509 -nodes -days 3650 -newkey rsa:2048 \
	    -keyout infra/secrets/origin.key \
	    -out infra/secrets/origin.crt \
	    -subj "/CN=adsb.aero"

# ── Helpers ───────────────────────────────────────────────────────────────────
logs:
	cd infra && docker compose logs -f
