"""Integration tests for GET /flights/{flight_id}."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from httpx import AsyncClient

pytestmark = pytest.mark.asyncio

FLIGHT_A_ID = "aabbcc:2025-04-01T10:00:00Z"


async def test_get_flight_happy_path(api_client: AsyncClient) -> None:
    resp = await api_client.get(f"/api/v1/flights/{FLIGHT_A_ID}")
    assert resp.status_code == 200
    data = resp.json()

    assert data["flight_id"] == FLIGHT_A_ID
    assert data["icao24"] == "aabbcc"
    assert data["callsign"] == "BAW123"
    assert data["icao_type"] == "B738"
    assert data["emitter_category"] == "A3"
    assert data["registration"] == "G-TESTA"
    assert data["model"] == "BOEING 737-800"
    assert data["year"] == 2010
    assert data["operator"] == "Test Airways"

    # Path shape
    path = data["path"]
    assert path["type"] == "LineString"
    assert len(path["coordinates"]) == 3
    # Each coordinate should have 3 elements (lon, lat, alt — M stripped)
    for coord in path["coordinates"]:
        assert len(coord) == 3

    # Timestamps
    timestamps = data["timestamps"]
    assert len(timestamps) == 3
    assert timestamps[0] == pytest.approx(1743501600.0)

    # path_tracks: [[ts, degrees], ...] timeseries (independent of path vertices)
    pt = data["path_tracks"]
    assert pt is not None
    assert len(pt) == 3
    assert pt[0] == [pytest.approx(1743501600.0), 90]
    assert pt[1] == [pytest.approx(1743505200.0), 315]
    assert pt[2] == [pytest.approx(1743508800.0), 315]

    # New series: null in test data (not inserted)
    assert data["path_gs"] is None
    assert data["path_vr"] is None
    assert data["path_ias"] is None

    # Squawk runs: two instants with the same code define the temporal extent
    assert data["squawk_runs"] == [[1743501600.0, "1234"], [1743508800.0, "1234"]]

    assert data["raw_point_count"] == 30
    assert data["ingest_batch_date"] == "2025-04-01"


async def test_get_flight_not_found(api_client: AsyncClient) -> None:
    resp = await api_client.get("/api/v1/flights/zzzzzz:2000-01-01T00:00:00Z")
    assert resp.status_code == 404


async def test_get_flight_malformed_id(api_client: AsyncClient) -> None:
    resp = await api_client.get("/api/v1/flights/notavalidid")
    assert resp.status_code == 422


async def test_get_data_range(api_client: AsyncClient) -> None:
    resp = await api_client.get("/api/v1/data-range")
    assert resp.status_code == 200
    data = resp.json()
    assert data["first_date"] == "2025-04-01"
    assert data["last_date"] == "2025-04-01"
