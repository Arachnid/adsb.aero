"""Tests for the agent-facing surface: CORS, and self-documenting 422s.

None of these touch the database, so they run without a container.
The static landing-page discovery assets are covered by test_discovery_assets.py.
"""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from adsb_server.api.main import DOCS_URL, app

pytestmark = pytest.mark.asyncio


async def _client() -> AsyncClient:
    app.state.pool = None  # these routes never reach the pool
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def test_cors_preflight_allows_any_origin() -> None:
    async with await _client() as client:
        resp = await client.options(
            "/api/v1/query",
            headers={
                "Origin": "https://example.com",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "content-type",
            },
        )
    assert resp.status_code == 200
    assert resp.headers["access-control-allow-origin"] == "*"
    assert "POST" in resp.headers["access-control-allow-methods"]


async def test_cors_header_on_simple_request() -> None:
    async with await _client() as client:
        resp = await client.get("/api/v1/health", headers={"Origin": "https://example.com"})
    assert resp.status_code == 200
    assert resp.headers["access-control-allow-origin"] == "*"


async def test_validation_error_points_at_the_docs() -> None:
    """A caller that guessed the request shape is told where the real one is."""
    async with await _client() as client:
        resp = await client.post("/api/v1/query", json={"match": {"departs_from": "EGHP"}})
    assert resp.status_code == 422
    body = resp.json()
    assert body["documentation"] == DOCS_URL
    assert DOCS_URL in body["hint"]
    assert "/api/openapi.json" in body["hint"]


async def test_validation_error_keeps_fastapi_detail_shape() -> None:
    """`detail` stays exactly as FastAPI emits it; the docs pointer is additive."""
    async with await _client() as client:
        resp = await client.post("/api/v1/query", json={"limit": "not-a-number"})
    assert resp.status_code == 422
    detail = resp.json()["detail"]
    assert isinstance(detail, list)
    assert detail and all("loc" in item and "msg" in item for item in detail)


async def test_validation_error_is_json_serialisable() -> None:
    """Regression guard: ValueError from a model validator must not 500.

    `model_validator` raises plain ValueError, which lands in the error list as
    a `ctx.error` exception object — not JSON-serialisable without encoding.
    """
    async with await _client() as client:
        resp = await client.post(
            "/api/v1/query",
            json={
                "end_date": "2025-01-01T00:00:00Z",
                "start_from": "2025-06-01T00:00:00Z",  # after end_date → invalid
            },
        )
    assert resp.status_code == 422
    assert "start_from" in resp.text
