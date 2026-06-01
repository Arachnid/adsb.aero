"""Integration tests for GET /airports/search and GET /airports/{ident}."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest
import pytest_asyncio

if TYPE_CHECKING:
    import asyncpg
    from httpx import AsyncClient

pytestmark = pytest.mark.asyncio

_INSERT_AIRPORT = """
    INSERT INTO airports
        (ident, type, name, location, elevation_ft, iso_country, iso_region,
         municipality, scheduled_service, icao_code, iata_code, local_code,
         keywords, fetched_at)
    VALUES
        ($1, $2, $3, ST_SetSRID(ST_MakePoint($4, $5), 4326), $6, $7, $8,
         $9, $10, $11, $12, $13, $14, $15)
    ON CONFLICT (ident) DO NOTHING
"""

_NOW = datetime.now(UTC)

_AIRPORTS = [
    (
        "EGLL",
        "large_airport",
        "London Heathrow Airport",
        -0.461389,
        51.4775,
        83,
        "GB",
        "GB-ENG",
        "London",
        True,
        "EGLL",
        "LHR",
        None,
        None,
        _NOW,
    ),
    (
        "KSFO",
        "large_airport",
        "San Francisco Intl Airport",
        -122.375,
        37.619,
        13,
        "US",
        "US-CA",
        "San Francisco",
        True,
        "KSFO",
        "SFO",
        None,
        None,
        _NOW,
    ),
    (
        "EGLT",
        "heliport",
        "Ascot Racecourse Heliport",
        -0.668,
        51.409,
        50,
        "GB",
        "GB-ENG",
        "Ascot Heath",
        False,
        "EGLT",
        None,
        None,
        None,
        _NOW,
    ),
    (
        "GB-CLOSED",
        "closed",
        "Old Heath Airfield",
        -0.5,
        51.5,
        None,
        "GB",
        "GB-ENG",
        "Heath",
        False,
        None,
        None,
        None,
        None,
        _NOW,
    ),
]


@pytest_asyncio.fixture(scope="session")
async def airport_data(pool: asyncpg.Pool) -> None:  # type: ignore[type-arg]
    for row in _AIRPORTS:
        await pool.execute(_INSERT_AIRPORT, *row)


@pytest_asyncio.fixture(scope="session")
async def airport_client(
    pool: asyncpg.Pool,
    airport_data: None,
) -> AsyncClient:
    from httpx import ASGITransport, AsyncClient

    from adsb_server.api.main import app

    app.state.pool = pool
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client  # type: ignore[misc]


async def test_search_returns_matching_airports(airport_client: AsyncClient) -> None:
    resp = await airport_client.get("/api/v1/airports/search", params={"q": "heathrow"})
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["ident"] == "EGLL"
    assert data[0]["icao_code"] == "EGLL"
    assert data[0]["iata_code"] == "LHR"
    assert data[0]["lon"] == pytest.approx(-0.461389, abs=1e-4)
    assert data[0]["lat"] == pytest.approx(51.4775, abs=1e-4)


async def test_search_prefix_match(airport_client: AsyncClient) -> None:
    resp = await airport_client.get("/api/v1/airports/search", params={"q": "heath"})
    assert resp.status_code == 200
    idents = {r["ident"] for r in resp.json()}
    assert "EGLL" in idents
    assert "EGLT" in idents
    # Closed airport must be excluded
    assert "GB-CLOSED" not in idents


async def test_search_excludes_closed(airport_client: AsyncClient) -> None:
    resp = await airport_client.get("/api/v1/airports/search", params={"q": "old heath"})
    assert resp.status_code == 200
    assert resp.json() == []


async def test_search_scheduled_service_first(airport_client: AsyncClient) -> None:
    resp = await airport_client.get("/api/v1/airports/search", params={"q": "heath"})
    results = resp.json()
    # EGLL (scheduled=True) must appear before EGLT (scheduled=False)
    idents = [r["ident"] for r in results]
    assert idents.index("EGLL") < idents.index("EGLT")


async def test_search_limit(airport_client: AsyncClient) -> None:
    resp = await airport_client.get("/api/v1/airports/search", params={"q": "airport", "limit": 1})
    assert resp.status_code == 200
    assert len(resp.json()) == 1


async def test_search_empty_after_strip(airport_client: AsyncClient) -> None:
    resp = await airport_client.get("/api/v1/airports/search", params={"q": "!!!"})
    assert resp.status_code == 200
    assert resp.json() == []


async def test_search_missing_q(airport_client: AsyncClient) -> None:
    resp = await airport_client.get("/api/v1/airports/search")
    assert resp.status_code == 422


async def test_get_airport_happy_path(airport_client: AsyncClient) -> None:
    resp = await airport_client.get("/api/v1/airports/EGLL")
    assert resp.status_code == 200
    data = resp.json()
    assert data["ident"] == "EGLL"
    assert data["name"] == "London Heathrow Airport"
    assert data["type"] == "large_airport"
    assert data["iso_country"] == "GB"
    assert data["scheduled_service"] is True


async def test_get_airport_case_insensitive(airport_client: AsyncClient) -> None:
    resp = await airport_client.get("/api/v1/airports/egll")
    assert resp.status_code == 200
    assert resp.json()["ident"] == "EGLL"


async def test_get_airport_not_found(airport_client: AsyncClient) -> None:
    resp = await airport_client.get("/api/v1/airports/ZZZZ")
    assert resp.status_code == 404
