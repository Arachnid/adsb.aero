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

    # Tracks
    assert data["path_tracks"] == [90, 315, 315]

    # Squawk runs
    assert data["squawk_runs"] == [[1743501600.0, "1234"]]

    assert data["raw_point_count"] == 30
    assert data["ingest_batch_date"] == "2025-04-01"


async def test_get_flight_not_found(api_client: AsyncClient) -> None:
    resp = await api_client.get("/api/v1/flights/zzzzzz:2000-01-01T00:00:00Z")
    assert resp.status_code == 404


async def test_get_flight_malformed_id(api_client: AsyncClient) -> None:
    resp = await api_client.get("/api/v1/flights/notavalidid")
    assert resp.status_code == 422
