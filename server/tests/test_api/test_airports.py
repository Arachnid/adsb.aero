"""Integration tests for GET /waypoints/search and GET /waypoints/{id}."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest
import pytest_asyncio

if TYPE_CHECKING:
    import asyncpg
    from httpx import AsyncClient

pytestmark = pytest.mark.asyncio

_INSERT_WAYPOINT = """
    INSERT INTO waypoints
        (id, kind, name, ident, iata_code, type_code, country,
         location, elevation_ft, fetched_at)
    VALUES ($1, $2, $3, $4, $5, $6, $7,
            ST_SetSRID(ST_MakePoint($8, $9), 4326), $10, NOW())
    ON CONFLICT (id) DO NOTHING
"""

_NOW = datetime.now(UTC)

_WAYPOINTS = [
    ("wp-egll", "airport", "LONDON HEATHROW", "EGLL", "LHR", 3, "GB", -0.461389, 51.4775, 83),
    ("wp-ksfo", "airport", "SAN FRANCISCO INTL", "KSFO", "SFO", 3, "US", -122.375, 37.619, 13),
    ("wp-eglt", "airport", "ASCOT RACECOURSE HELIPORT", "EGLT", None, 7, "GB", -0.668, 51.409, 50),
    ("wp-bnn", "navaid", "BOVINGDON", "BNN", None, 3, "GB", -0.549, 51.726, 488),
    ("wp-divis", "reporting_point", "DIVIS", None, None, None, "GB", -6.030, 54.590, 365),
]


@pytest_asyncio.fixture(scope="session")
async def waypoint_data(pool: asyncpg.Pool) -> None:  # type: ignore[type-arg]
    for row in _WAYPOINTS:
        await pool.execute(_INSERT_WAYPOINT, *row)


@pytest_asyncio.fixture(scope="session")
async def wp_client(
    pool: asyncpg.Pool,
    waypoint_data: None,
) -> AsyncClient:
    from httpx import ASGITransport, AsyncClient

    from adsb_server.api.main import app

    app.state.pool = pool
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client  # type: ignore[misc]


async def test_search_returns_matching_waypoints(wp_client: AsyncClient) -> None:
    resp = await wp_client.get("/api/v1/waypoints/search", params={"q": "heathrow"})
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["ident"] == "EGLL"
    assert data[0]["iata_code"] == "LHR"
    assert data[0]["kind"] == "airport"
    assert data[0]["lon"] == pytest.approx(-0.461389, abs=1e-4)


async def test_search_prefix_match(wp_client: AsyncClient) -> None:
    resp = await wp_client.get("/api/v1/waypoints/search", params={"q": "egll"})
    assert resp.status_code == 200
    idents = {r["ident"] for r in resp.json()}
    assert "EGLL" in idents


async def test_search_navaid(wp_client: AsyncClient) -> None:
    resp = await wp_client.get("/api/v1/waypoints/search", params={"q": "BNN"})
    assert resp.status_code == 200
    hits = resp.json()
    bnn = next((r for r in hits if r["ident"] == "BNN"), None)
    assert bnn is not None
    assert bnn["kind"] == "navaid"


async def test_search_kind_filter(wp_client: AsyncClient) -> None:
    resp = await wp_client.get("/api/v1/waypoints/search", params={"q": "bov", "kinds": "navaid"})
    assert resp.status_code == 200
    assert all(r["kind"] == "navaid" for r in resp.json())


async def test_search_limit(wp_client: AsyncClient) -> None:
    resp = await wp_client.get("/api/v1/waypoints/search", params={"q": "london", "limit": 1})
    assert resp.status_code == 200
    assert len(resp.json()) == 1


async def test_search_empty_after_strip(wp_client: AsyncClient) -> None:
    resp = await wp_client.get("/api/v1/waypoints/search", params={"q": "!!!"})
    assert resp.status_code == 200
    assert resp.json() == []


async def test_search_missing_q(wp_client: AsyncClient) -> None:
    resp = await wp_client.get("/api/v1/waypoints/search")
    assert resp.status_code == 422


async def test_get_waypoint_happy_path(wp_client: AsyncClient) -> None:
    resp = await wp_client.get("/api/v1/waypoints/wp-egll")
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == "wp-egll"
    assert data["ident"] == "EGLL"
    assert data["kind"] == "airport"
    assert data["country"] == "GB"


async def test_get_waypoint_not_found(wp_client: AsyncClient) -> None:
    resp = await wp_client.get("/api/v1/waypoints/does-not-exist")
    assert resp.status_code == 404
