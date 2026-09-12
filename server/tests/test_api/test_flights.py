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

    # Path shape (MultiLineString: list of sub-sequences)
    path = data["path"]
    assert path["type"] == "MultiLineString"
    assert sum(len(s) for s in path["coordinates"]) == 3
    # Each coordinate should have 3 elements (lon, lat, alt — M stripped)
    for seq in path["coordinates"]:
        for coord in seq:
            assert len(coord) == 3

    # Timestamps (list[list[float]]: per-sequence structure)
    timestamps = data["timestamps"]
    assert sum(len(s) for s in timestamps) == 3
    assert timestamps[0][0] == pytest.approx(1743501600.0)

    # path_tracks: per-sub-sequence [[[ts, degrees], ...], ...] timeseries
    pt = data["path_tracks"]
    assert pt is not None
    assert len(pt) == 1  # one sub-sequence (no coverage gaps in test data)
    assert len(pt[0]) == 3
    assert pt[0][0] == [pytest.approx(1743501600.0), 90]
    assert pt[0][1] == [pytest.approx(1743505200.0), 315]
    assert pt[0][2] == [pytest.approx(1743508800.0), 315]

    # New series: null in test data (not inserted)
    assert data["path_gs"] is None
    assert data["path_vr"] is None
    assert data["path_ias"] is None

    # Squawk runs: per-sub-sequence [[[ts, code], ...], ...]
    assert data["squawk_runs"] == [[[1743501600.0, "1234"], [1743508800.0, "1234"]]]

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
