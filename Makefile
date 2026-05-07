.PHONY: dev dev-down prod prod-down logs build-web

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

# ── Helpers ───────────────────────────────────────────────────────────────────
logs:
	cd infra && docker compose logs -f
