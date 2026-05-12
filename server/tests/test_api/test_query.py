"""Integration tests for POST /api/v1/query."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from httpx import AsyncClient

pytestmark = pytest.mark.asyncio

UK_BBOX = {
    "type": "Polygon",
    "coordinates": [[[-8, 49], [2, 49], [2, 61], [-8, 61], [-8, 49]]],
}

MANCHESTER_CIRCLE = {
    "type": "Circle",
    "coordinates": [-2.2667, 53.4667],
    "radius": 50000,
}


async def test_no_filter_returns_all(api_client: AsyncClient) -> None:
    resp = await api_client.post("/api/v1/query", json={"limit": 100})
    assert resp.status_code == 200
    data = resp.json()
    flight_ids = {f["flight_id"] for f in data["flights"]}
    assert "aabbcc:2025-04-01T10:00:00Z" in flight_ids
    assert "ddeeff:2025-04-01T06:00:00Z" in flight_ids
    # Every result should include the full trace
    for f in data["flights"]:
        assert f["path"]["type"] == "LineString"
        assert len(f["timestamps"]) == len(f["path"]["coordinates"])
        assert len(f["path_tracks"]) == len(f["path"]["coordinates"])


async def test_starts_within_time_filter(api_client: AsyncClient) -> None:
    resp = await api_client.post(
        "/api/v1/query",
        json={
            "match": {
                "starts_within": {
                    "time_from": "2025-04-01T09:00:00Z",
                    "time_to": "2025-04-01T11:00:00Z",
                }
            }
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    flight_ids = {f["flight_id"] for f in data["flights"]}
    assert "aabbcc:2025-04-01T10:00:00Z" in flight_ids
    assert "ddeeff:2025-04-01T06:00:00Z" not in flight_ids


async def test_trajectory_intersects_uk(api_client: AsyncClient) -> None:
    resp = await api_client.post(
        "/api/v1/query",
        json={"match": {"trajectory_intersects": {"geometry": UK_BBOX}}},
    )
    assert resp.status_code == 200
    data = resp.json()
    flight_ids = {f["flight_id"] for f in data["flights"]}
    assert "aabbcc:2025-04-01T10:00:00Z" in flight_ids
    assert "ddeeff:2025-04-01T06:00:00Z" not in flight_ids


async def test_aircraft_filter(api_client: AsyncClient) -> None:
    resp = await api_client.post(
        "/api/v1/query",
        json={"match": {"icao_type": ["B738"]}},
    )
    assert resp.status_code == 200
    data = resp.json()
    flight_ids = {f["flight_id"] for f in data["flights"]}
    assert "aabbcc:2025-04-01T10:00:00Z" in flight_ids
    assert "ddeeff:2025-04-01T06:00:00Z" not in flight_ids


async def test_ends_within_manchester(api_client: AsyncClient) -> None:
    resp = await api_client.post(
        "/api/v1/query",
        json={"match": {"ends_within": {"geometry": MANCHESTER_CIRCLE}}},
    )
    assert resp.status_code == 200
    data = resp.json()
    flight_ids = {f["flight_id"] for f in data["flights"]}
    assert "aabbcc:2025-04-01T10:00:00Z" in flight_ids
    assert "ddeeff:2025-04-01T06:00:00Z" not in flight_ids


async def test_callsign_matches(api_client: AsyncClient) -> None:
    resp = await api_client.post(
        "/api/v1/query",
        json={"match": {"callsign_matches": "^BAW"}},
    )
    assert resp.status_code == 200
    data = resp.json()
    flight_ids = {f["flight_id"] for f in data["flights"]}
    assert "aabbcc:2025-04-01T10:00:00Z" in flight_ids
    assert "ddeeff:2025-04-01T06:00:00Z" not in flight_ids


async def test_and_composition(api_client: AsyncClient) -> None:
    resp = await api_client.post(
        "/api/v1/query",
        json={
            "match": {
                "and": [
                    {"trajectory_intersects": {"geometry": UK_BBOX}},
                    {"icao_type": ["B738"]},
                ]
            }
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["flights"]) >= 1
    flight_ids = {f["flight_id"] for f in data["flights"]}
    assert "aabbcc:2025-04-01T10:00:00Z" in flight_ids


async def test_cursor_pagination(api_client: AsyncClient) -> None:
    resp1 = await api_client.post("/api/v1/query", json={"limit": 1})
    assert resp1.status_code == 200
    data1 = resp1.json()
    assert len(data1["flights"]) == 1
    assert data1["cursor"] is not None

    resp2 = await api_client.post(
        "/api/v1/query", json={"limit": 1, "cursor": data1["cursor"]}
    )
    assert resp2.status_code == 200
    data2 = resp2.json()
    assert len(data2["flights"]) == 1
    assert data1["flights"][0]["flight_id"] != data2["flights"][0]["flight_id"]


async def test_duration_filter(api_client: AsyncClient) -> None:
    # Flight A: 10:00-12:00 = 7200s; Flight B: 06:00-09:00 = 10800s
    # min_s=9000 should return only flight B
    resp = await api_client.post(
        "/api/v1/query",
        json={"match": {"duration": {"min_s": 9000}}},
    )
    assert resp.status_code == 200
    data = resp.json()
    flight_ids = {f["flight_id"] for f in data["flights"]}
    assert "ddeeff:2025-04-01T06:00:00Z" in flight_ids
    assert "aabbcc:2025-04-01T10:00:00Z" not in flight_ids


async def test_trajectory_within_uk(api_client: AsyncClient) -> None:
    # Flight A (London→Manchester) lies entirely within a generous UK bbox.
    # Flight B (Paris→Rome) does not.
    uk_containing = {
        "type": "Polygon",
        "coordinates": [[[-5, 50], [2, 50], [2, 55], [-5, 55], [-5, 50]]],
    }
    resp = await api_client.post(
        "/api/v1/query",
        json={"match": {"trajectory_within": {"geometry": uk_containing}}},
    )
    assert resp.status_code == 200
    data = resp.json()
    flight_ids = {f["flight_id"] for f in data["flights"]}
    assert "aabbcc:2025-04-01T10:00:00Z" in flight_ids
    assert "ddeeff:2025-04-01T06:00:00Z" not in flight_ids


async def test_trajectory_disjoint_uk(api_client: AsyncClient) -> None:
    # Flight B (Paris→Rome) is entirely outside the UK.
    resp = await api_client.post(
        "/api/v1/query",
        json={"match": {"trajectory_disjoint": {"geometry": UK_BBOX}}},
    )
    assert resp.status_code == 200
    data = resp.json()
    flight_ids = {f["flight_id"] for f in data["flights"]}
    assert "ddeeff:2025-04-01T06:00:00Z" in flight_ids
    assert "aabbcc:2025-04-01T10:00:00Z" not in flight_ids


async def test_trajectory_intersects_altitude_band(api_client: AsyncClient) -> None:
    # Flight A cruises at 35000-36000 ft; altitude_min_ft=34000 should match.
    resp = await api_client.post(
        "/api/v1/query",
        json={
            "match": {
                "trajectory_intersects": {
                    "geometry": UK_BBOX,
                    "altitude_min_ft": 34000,
                }
            }
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    flight_ids = {f["flight_id"] for f in data["flights"]}
    assert "aabbcc:2025-04-01T10:00:00Z" in flight_ids


async def test_starts_within_polygon(api_client: AsyncClient) -> None:
    # Flight A departs London; a polygon around London should match it.
    london_box = {
        "type": "Polygon",
        "coordinates": [[[-0.5, 51.3], [0.2, 51.3], [0.2, 51.7], [-0.5, 51.7], [-0.5, 51.3]]],
    }
    resp = await api_client.post(
        "/api/v1/query",
        json={"match": {"starts_within": {"geometry": london_box}}},
    )
    assert resp.status_code == 200
    data = resp.json()
    flight_ids = {f["flight_id"] for f in data["flights"]}
    assert "aabbcc:2025-04-01T10:00:00Z" in flight_ids
    assert "ddeeff:2025-04-01T06:00:00Z" not in flight_ids


async def test_ends_within_time_range(api_client: AsyncClient) -> None:
    # Flight B ends at 09:00; Flight A ends at 12:00.
    resp = await api_client.post(
        "/api/v1/query",
        json={
            "match": {
                "ends_within": {
                    "time_from": "2025-04-01T08:00:00Z",
                    "time_to": "2025-04-01T10:00:00Z",
                }
            }
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    flight_ids = {f["flight_id"] for f in data["flights"]}
    assert "ddeeff:2025-04-01T06:00:00Z" in flight_ids
    assert "aabbcc:2025-04-01T10:00:00Z" not in flight_ids


async def test_emitter_category_filter(api_client: AsyncClient) -> None:
    resp = await api_client.post(
        "/api/v1/query",
        json={"match": {"emitter_category": ["A3"]}},
    )
    assert resp.status_code == 200
    data = resp.json()
    flight_ids = {f["flight_id"] for f in data["flights"]}
    assert "aabbcc:2025-04-01T10:00:00Z" in flight_ids
    assert "ddeeff:2025-04-01T06:00:00Z" in flight_ids


async def test_duration_max_s_filter(api_client: AsyncClient) -> None:
    # Flight A: 7200s; Flight B: 10800s. max_s=8000 → only Flight A.
    resp = await api_client.post(
        "/api/v1/query",
        json={"match": {"duration": {"max_s": 8000}}},
    )
    assert resp.status_code == 200
    data = resp.json()
    flight_ids = {f["flight_id"] for f in data["flights"]}
    assert "aabbcc:2025-04-01T10:00:00Z" in flight_ids
    assert "ddeeff:2025-04-01T06:00:00Z" not in flight_ids


async def test_or_predicate(api_client: AsyncClient) -> None:
    resp = await api_client.post(
        "/api/v1/query",
        json={"match": {"or": [{"icao_type": ["B738"]}, {"icao_type": ["A320"]}]}},
    )
    assert resp.status_code == 200
    data = resp.json()
    flight_ids = {f["flight_id"] for f in data["flights"]}
    assert "aabbcc:2025-04-01T10:00:00Z" in flight_ids
    assert "ddeeff:2025-04-01T06:00:00Z" in flight_ids


async def test_not_predicate(api_client: AsyncClient) -> None:
    resp = await api_client.post(
        "/api/v1/query",
        json={"match": {"not": {"callsign_matches": "^BAW"}}},
    )
    assert resp.status_code == 200
    data = resp.json()
    flight_ids = {f["flight_id"] for f in data["flights"]}
    assert "ddeeff:2025-04-01T06:00:00Z" in flight_ids
    assert "aabbcc:2025-04-01T10:00:00Z" not in flight_ids


async def test_empty_result(api_client: AsyncClient) -> None:
    resp = await api_client.post(
        "/api/v1/query",
        json={"match": {"icao_type": ["NONEXISTENT"]}},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["flights"] == []
    assert data["cursor"] is None
