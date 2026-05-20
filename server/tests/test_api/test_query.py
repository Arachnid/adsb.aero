"""Integration tests for POST /api/v1/query."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest

if TYPE_CHECKING:
    from httpx import AsyncClient

pytestmark = pytest.mark.asyncio

# Polygon covering the London→Manchester corridor (115 H3 cells, well under MAX_QUERY_H3_CELLS).
# Contains Flight A (London→Manchester); excludes Flight B (Paris→Rome).
UK_CORRIDOR = {
    "type": "Polygon",
    "coordinates": [[[-3, 50.5], [0.5, 50.5], [0.5, 54], [-3, 54], [-3, 50.5]]],
}

MANCHESTER_CIRCLE = {
    "type": "Circle",
    "coordinates": [-2.2667, 53.4667],
    "radius": 50000,
}

# Both test flights start on 2025-04-01.  end_date=Apr-02, window_days=2 covers both.
_START_RANGE = {
    "end_date": "2025-04-02T00:00:00Z",
    "window_days": 2,
}


def qbody(**kwargs: Any) -> dict[str, Any]:
    """Build a query request body with the required date bounds."""
    return {**_START_RANGE, **kwargs}


async def test_no_filter_returns_all(api_client: AsyncClient) -> None:
    resp = await api_client.post("/api/v1/query", json=qbody(limit=100))
    assert resp.status_code == 200
    data = resp.json()
    flight_ids = {f["flight_id"] for f in data["flights"]}
    assert "aabbcc:2025-04-01T10:00:00Z" in flight_ids
    assert "ddeeff:2025-04-01T06:00:00Z" in flight_ids
    # Every result should include the full trace (MultiLineString: list of sub-sequences)
    for f in data["flights"]:
        assert f["path"]["type"] == "MultiLineString"
        assert len(f["timestamps"]) == len(f["path"]["coordinates"])
        assert len(f["path_tracks"]) > 0


async def test_endpoint_within_start_time_filter(api_client: AsyncClient) -> None:
    resp = await api_client.post(
        "/api/v1/query",
        json=qbody(
            match={
                "endpoint_within": {
                    "mode": "start",
                    "start_time_from": "2025-04-01T09:00:00Z",
                    "start_time_to": "2025-04-01T11:00:00Z",
                }
            }
        ),
    )
    assert resp.status_code == 200
    data = resp.json()
    flight_ids = {f["flight_id"] for f in data["flights"]}
    assert "aabbcc:2025-04-01T10:00:00Z" in flight_ids
    assert "ddeeff:2025-04-01T06:00:00Z" not in flight_ids


async def test_trajectory_intersects_uk(api_client: AsyncClient) -> None:
    resp = await api_client.post(
        "/api/v1/query",
        json=qbody(match={"trajectory_intersects": {"geometry": UK_CORRIDOR}}),
    )
    assert resp.status_code == 200
    data = resp.json()
    flight_ids = {f["flight_id"] for f in data["flights"]}
    assert "aabbcc:2025-04-01T10:00:00Z" in flight_ids
    assert "ddeeff:2025-04-01T06:00:00Z" not in flight_ids


async def test_aircraft_filter(api_client: AsyncClient) -> None:
    resp = await api_client.post(
        "/api/v1/query",
        json=qbody(match={"icao_type": ["B738"]}),
    )
    assert resp.status_code == 200
    data = resp.json()
    flight_ids = {f["flight_id"] for f in data["flights"]}
    assert "aabbcc:2025-04-01T10:00:00Z" in flight_ids
    assert "ddeeff:2025-04-01T06:00:00Z" not in flight_ids


async def test_endpoint_within_end_geometry(api_client: AsyncClient) -> None:
    resp = await api_client.post(
        "/api/v1/query",
        json=qbody(match={"endpoint_within": {"mode": "end", "geometry": MANCHESTER_CIRCLE}}),
    )
    assert resp.status_code == 200
    data = resp.json()
    flight_ids = {f["flight_id"] for f in data["flights"]}
    assert "aabbcc:2025-04-01T10:00:00Z" in flight_ids
    assert "ddeeff:2025-04-01T06:00:00Z" not in flight_ids


async def test_callsign_prefix(api_client: AsyncClient) -> None:
    resp = await api_client.post(
        "/api/v1/query",
        json=qbody(match={"callsign_prefix": "BAW"}),
    )
    assert resp.status_code == 200
    data = resp.json()
    flight_ids = {f["flight_id"] for f in data["flights"]}
    assert "aabbcc:2025-04-01T10:00:00Z" in flight_ids
    assert "ddeeff:2025-04-01T06:00:00Z" not in flight_ids


async def test_and_composition(api_client: AsyncClient) -> None:
    resp = await api_client.post(
        "/api/v1/query",
        json=qbody(
            match={
                "and": [
                    {"trajectory_intersects": {"geometry": UK_CORRIDOR}},
                    {"icao_type": ["B738"]},
                ]
            }
        ),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["flights"]) >= 1
    flight_ids = {f["flight_id"] for f in data["flights"]}
    assert "aabbcc:2025-04-01T10:00:00Z" in flight_ids


async def test_cursor_pagination(api_client: AsyncClient) -> None:
    resp1 = await api_client.post("/api/v1/query", json=qbody(limit=1))
    assert resp1.status_code == 200
    data1 = resp1.json()
    assert len(data1["flights"]) == 1
    assert data1["cursor"] is not None
    assert data1["window_from"] is not None

    resp2 = await api_client.post("/api/v1/query", json=qbody(limit=1, cursor=data1["cursor"]))
    assert resp2.status_code == 200
    data2 = resp2.json()
    assert len(data2["flights"]) == 1
    assert data1["flights"][0]["flight_id"] != data2["flights"][0]["flight_id"]
    # Second page window slides back from cursor position
    assert data2["window_from"] is not None


async def test_duration_filter(api_client: AsyncClient) -> None:
    # Flight A: 10:00-12:00 = 7200s; Flight B: 06:00-09:00 = 10800s
    # min_s=9000 should return only flight B
    resp = await api_client.post(
        "/api/v1/query",
        json=qbody(match={"duration": {"min_s": 9000}}),
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
        "coordinates": [[[-3, 50.5], [0.5, 50.5], [0.5, 54], [-3, 54], [-3, 50.5]]],
    }
    resp = await api_client.post(
        "/api/v1/query",
        json=qbody(match={"trajectory_within": {"geometry": uk_containing}}),
    )
    assert resp.status_code == 200
    data = resp.json()
    flight_ids = {f["flight_id"] for f in data["flights"]}
    assert "aabbcc:2025-04-01T10:00:00Z" in flight_ids
    assert "ddeeff:2025-04-01T06:00:00Z" not in flight_ids


async def test_not_trajectory_intersects_as_disjoint(api_client: AsyncClient) -> None:
    # Equivalent to the removed trajectory_disjoint: NOT intersects(UK) → Flight B only.
    resp = await api_client.post(
        "/api/v1/query",
        json=qbody(match={"not": {"trajectory_intersects": {"geometry": UK_CORRIDOR}}}),
    )
    assert resp.status_code == 200
    data = resp.json()
    flight_ids = {f["flight_id"] for f in data["flights"]}
    assert "ddeeff:2025-04-01T06:00:00Z" in flight_ids
    assert "aabbcc:2025-04-01T10:00:00Z" not in flight_ids


async def test_squawk_filter_matches_flight_with_code(api_client: AsyncClient) -> None:
    # Flight A has squawk "1234"; Flight B has no squawk.
    resp = await api_client.post(
        "/api/v1/query",
        json=qbody(match={"trajectory_intersects": {"squawk_codes": ["1234"]}}),
    )
    assert resp.status_code == 200
    data = resp.json()
    flight_ids = {f["flight_id"] for f in data["flights"]}
    assert "aabbcc:2025-04-01T10:00:00Z" in flight_ids
    assert "ddeeff:2025-04-01T06:00:00Z" not in flight_ids


async def test_squawk_filter_no_match_returns_empty(api_client: AsyncClient) -> None:
    resp = await api_client.post(
        "/api/v1/query",
        json=qbody(match={"trajectory_intersects": {"squawk_codes": ["7700"]}}),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["flights"] == []


async def test_squawk_filter_with_geometry_correlated(api_client: AsyncClient) -> None:
    # Flight A flies London→Manchester with squawk "1234" throughout.
    # A polygon around Manchester contains the end of the flight.
    # squawk "1234" applies when the path is in Manchester → should match.
    manchester_box = {
        "type": "Polygon",
        "coordinates": [[[-3, 53], [-1.5, 53], [-1.5, 54], [-3, 54], [-3, 53]]],
    }
    resp = await api_client.post(
        "/api/v1/query",
        json=qbody(
            match={"trajectory_intersects": {"geometry": manchester_box, "squawk_codes": ["1234"]}}
        ),
    )
    assert resp.status_code == 200
    data = resp.json()
    flight_ids = {f["flight_id"] for f in data["flights"]}
    assert "aabbcc:2025-04-01T10:00:00Z" in flight_ids
    assert "ddeeff:2025-04-01T06:00:00Z" not in flight_ids


async def test_squawk_filter_geometry_no_squawk_match_at_location(
    api_client: AsyncClient,
) -> None:
    # Same Manchester polygon, but squawk "7700" — Flight A never had this code.
    # Verifies the correlated SQL correctly returns no results.
    manchester_box = {
        "type": "Polygon",
        "coordinates": [[[-3, 53], [-1.5, 53], [-1.5, 54], [-3, 54], [-3, 53]]],
    }
    resp = await api_client.post(
        "/api/v1/query",
        json=qbody(
            match={"trajectory_intersects": {"geometry": manchester_box, "squawk_codes": ["7700"]}}
        ),
    )
    assert resp.status_code == 200
    assert resp.json()["flights"] == []


async def test_trajectory_intersects_altitude_band_fl(api_client: AsyncClient) -> None:
    # altitude_min_ref=fl, altitude_min=340 → FL340 = 34000 ft pressure altitude.
    # Flight A at 35000-36000 ft; should match.
    resp = await api_client.post(
        "/api/v1/query",
        json=qbody(
            match={
                "trajectory_intersects": {
                    "geometry": UK_CORRIDOR,
                    "altitude_min": 340,
                    "altitude_min_ref": "fl",
                }
            }
        ),
    )
    assert resp.status_code == 200
    data = resp.json()
    flight_ids = {f["flight_id"] for f in data["flights"]}
    assert "aabbcc:2025-04-01T10:00:00Z" in flight_ids


async def test_trajectory_intersects_altitude_band_ft(api_client: AsyncClient) -> None:
    # altitude_min_ref=ft (default): corrected alt falls back to getZ when correction is NULL.
    # Flight A at 35000-36000 ft; altitude_min=34000 ft should match.
    resp = await api_client.post(
        "/api/v1/query",
        json=qbody(
            match={
                "trajectory_intersects": {
                    "geometry": UK_CORRIDOR,
                    "altitude_min": 34000,
                }
            }
        ),
    )
    assert resp.status_code == 200
    data = resp.json()
    flight_ids = {f["flight_id"] for f in data["flights"]}
    assert "aabbcc:2025-04-01T10:00:00Z" in flight_ids


async def test_trajectory_intersects_altitude_band_ft_excludes_below(
    api_client: AsyncClient,
) -> None:
    # altitude_max=30000 ft (default ref): Flight A (35000-36000 ft) should not match.
    resp = await api_client.post(
        "/api/v1/query",
        json=qbody(
            match={
                "trajectory_intersects": {
                    "geometry": UK_CORRIDOR,
                    "altitude_max": 30000,
                }
            }
        ),
    )
    assert resp.status_code == 200
    data = resp.json()
    flight_ids = {f["flight_id"] for f in data["flights"]}
    assert "aabbcc:2025-04-01T10:00:00Z" not in flight_ids


async def test_trajectory_intersects_altitude_mixed_refs(api_client: AsyncClient) -> None:
    # ft floor + FL ceiling: 1500 ft MSL floor, FL400 ceiling.
    # Flight A at 35000-36000 ft; should match (above floor, below ceiling).
    resp = await api_client.post(
        "/api/v1/query",
        json=qbody(
            match={
                "trajectory_intersects": {
                    "geometry": UK_CORRIDOR,
                    "altitude_min": 1500,
                    "altitude_min_ref": "ft",
                    "altitude_max": 400,
                    "altitude_max_ref": "fl",  # FL400 = 40000 ft pressure
                }
            }
        ),
    )
    assert resp.status_code == 200
    data = resp.json()
    flight_ids = {f["flight_id"] for f in data["flights"]}
    assert "aabbcc:2025-04-01T10:00:00Z" in flight_ids


async def test_endpoint_within_start_polygon(api_client: AsyncClient) -> None:
    # Flight A departs London; a polygon around London should match it.
    london_box = {
        "type": "Polygon",
        "coordinates": [[[-0.5, 51.3], [0.2, 51.3], [0.2, 51.7], [-0.5, 51.7], [-0.5, 51.3]]],
    }
    resp = await api_client.post(
        "/api/v1/query",
        json=qbody(match={"endpoint_within": {"mode": "start", "geometry": london_box}}),
    )
    assert resp.status_code == 200
    data = resp.json()
    flight_ids = {f["flight_id"] for f in data["flights"]}
    assert "aabbcc:2025-04-01T10:00:00Z" in flight_ids
    assert "ddeeff:2025-04-01T06:00:00Z" not in flight_ids


async def test_endpoint_within_end_time_range(api_client: AsyncClient) -> None:
    # Flight B ends at 09:00; Flight A ends at 12:00.
    resp = await api_client.post(
        "/api/v1/query",
        json=qbody(
            match={
                "endpoint_within": {
                    "mode": "end",
                    "end_time_from": "2025-04-01T08:00:00Z",
                    "end_time_to": "2025-04-01T10:00:00Z",
                }
            }
        ),
    )
    assert resp.status_code == 200
    data = resp.json()
    flight_ids = {f["flight_id"] for f in data["flights"]}
    assert "ddeeff:2025-04-01T06:00:00Z" in flight_ids
    assert "aabbcc:2025-04-01T10:00:00Z" not in flight_ids


async def test_endpoint_within_both_same_polygon(api_client: AsyncClient) -> None:
    # Flight A departs London and arrives Manchester — a UK-wide box covers both endpoints.
    uk_box = {
        "type": "Polygon",
        "coordinates": [[[-6, 49], [2, 49], [2, 59], [-6, 59], [-6, 49]]],
    }
    resp = await api_client.post(
        "/api/v1/query",
        json=qbody(match={"endpoint_within": {"mode": "both", "geometry": uk_box}}),
    )
    assert resp.status_code == 200
    data = resp.json()
    flight_ids = {f["flight_id"] for f in data["flights"]}
    assert "aabbcc:2025-04-01T10:00:00Z" in flight_ids


async def test_endpoint_within_either_mode(api_client: AsyncClient) -> None:
    # Flight A departs London (within UK box) — either mode should match it even though
    # arrival (Manchester) is also within the box.
    # Use a small box that covers only the London start point to confirm OR semantics.
    london_box = {
        "type": "Polygon",
        "coordinates": [[[-1, 51], [1, 51], [1, 52], [-1, 52], [-1, 51]]],
    }
    resp = await api_client.post(
        "/api/v1/query",
        json=qbody(match={"endpoint_within": {"mode": "either", "geometry": london_box}}),
    )
    assert resp.status_code == 200
    data = resp.json()
    flight_ids = {f["flight_id"] for f in data["flights"]}
    # Flight A starts near London → matches via start endpoint
    assert "aabbcc:2025-04-01T10:00:00Z" in flight_ids


async def test_emitter_category_filter(api_client: AsyncClient) -> None:
    resp = await api_client.post(
        "/api/v1/query",
        json=qbody(match={"emitter_category": ["A3"]}),
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
        json=qbody(match={"duration": {"max_s": 8000}}),
    )
    assert resp.status_code == 200
    data = resp.json()
    flight_ids = {f["flight_id"] for f in data["flights"]}
    assert "aabbcc:2025-04-01T10:00:00Z" in flight_ids
    assert "ddeeff:2025-04-01T06:00:00Z" not in flight_ids


async def test_or_predicate(api_client: AsyncClient) -> None:
    resp = await api_client.post(
        "/api/v1/query",
        json=qbody(match={"or": [{"icao_type": ["B738"]}, {"icao_type": ["A320"]}]}),
    )
    assert resp.status_code == 200
    data = resp.json()
    flight_ids = {f["flight_id"] for f in data["flights"]}
    assert "aabbcc:2025-04-01T10:00:00Z" in flight_ids
    assert "ddeeff:2025-04-01T06:00:00Z" in flight_ids


async def test_not_predicate(api_client: AsyncClient) -> None:
    resp = await api_client.post(
        "/api/v1/query",
        json=qbody(match={"not": {"callsign_prefix": "BAW"}}),
    )
    assert resp.status_code == 200
    data = resp.json()
    flight_ids = {f["flight_id"] for f in data["flights"]}
    assert "ddeeff:2025-04-01T06:00:00Z" in flight_ids
    assert "aabbcc:2025-04-01T10:00:00Z" not in flight_ids


async def test_empty_result(api_client: AsyncClient) -> None:
    # No start_from: server emits a sentinel cursor so callers can page further back.
    resp = await api_client.post(
        "/api/v1/query",
        json=qbody(match={"icao_type": ["NONEXISTENT"]}),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["flights"] == []
    assert data["cursor"] is not None
    assert "window_from" in data


async def test_empty_result_with_start_from_yields_null_cursor(api_client: AsyncClient) -> None:
    # With start_from equal to the window floor, the explicit floor is exhausted → null cursor.
    resp = await api_client.post(
        "/api/v1/query",
        json={
            "end_date": "2025-04-02T00:00:00Z",
            "start_from": "2025-04-01T00:00:00Z",
            "window_days": 1,
            "match": {"icao_type": ["NONEXISTENT"]},
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["flights"] == []
    assert data["cursor"] is None


async def test_start_range_filters_by_start_time(api_client: AsyncClient) -> None:
    # start_from as optional floor: covers only Flight A (starts 10:00), not Flight B (06:00).
    resp = await api_client.post(
        "/api/v1/query",
        json={
            "end_date": "2025-04-01T11:00:00Z",
            "start_from": "2025-04-01T09:00:00Z",
        },
    )
    assert resp.status_code == 200
    flight_ids = {f["flight_id"] for f in resp.json()["flights"]}
    assert "aabbcc:2025-04-01T10:00:00Z" in flight_ids
    assert "ddeeff:2025-04-01T06:00:00Z" not in flight_ids


async def test_window_days_limits_results(api_client: AsyncClient) -> None:
    # window_days=0.001 would be invalid; use window_days=1 anchored after Flight B starts.
    # end_date=2025-04-01T12:00:00Z, window_days=1 → floor=2025-03-31T12:00:00Z, covers both.
    # Narrow via start_from instead to exclude Flight B.
    resp = await api_client.post(
        "/api/v1/query",
        json={
            "end_date": "2025-04-02T00:00:00Z",
            "start_from": "2025-04-01T09:00:00Z",  # excludes Flight B (starts 06:00)
            "window_days": 7,
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    flight_ids = {f["flight_id"] for f in data["flights"]}
    assert "aabbcc:2025-04-01T10:00:00Z" in flight_ids
    assert "ddeeff:2025-04-01T06:00:00Z" not in flight_ids
    assert data["window_from"] is not None


async def test_start_from_after_end_date_rejected(api_client: AsyncClient) -> None:
    resp = await api_client.post(
        "/api/v1/query",
        json={
            "end_date": "2025-04-01T00:00:00Z",
            "start_from": "2025-04-02T00:00:00Z",  # after end_date
        },
    )
    assert resp.status_code == 422


async def test_start_from_equal_end_date_rejected(api_client: AsyncClient) -> None:
    resp = await api_client.post(
        "/api/v1/query",
        json={
            "end_date": "2025-04-01T00:00:00Z",
            "start_from": "2025-04-01T00:00:00Z",  # equal — not strictly before
        },
    )
    assert resp.status_code == 422


async def test_dwell_min_s_includes_flight_with_long_dwell(api_client: AsyncClient) -> None:
    # Flight A flies entirely within UK_CORRIDOR for 7200 s (10:00-12:00).
    # dwell_min_s=3600 should include it; verifies the two-level outer_parts SQL executes.
    resp = await api_client.post(
        "/api/v1/query",
        json=qbody(
            match={
                "trajectory_intersects": {
                    "geometry": UK_CORRIDOR,
                    "dwell_min_s": 3600,
                }
            }
        ),
    )
    assert resp.status_code == 200
    data = resp.json()
    flight_ids = {f["flight_id"] for f in data["flights"]}
    assert "aabbcc:2025-04-01T10:00:00Z" in flight_ids
    assert "ddeeff:2025-04-01T06:00:00Z" not in flight_ids


async def test_dwell_min_s_excludes_flight_below_threshold(api_client: AsyncClient) -> None:
    # Flight A dwells in UK_CORRIDOR for exactly 7200 s; requiring 7201 s should exclude it.
    resp = await api_client.post(
        "/api/v1/query",
        json=qbody(
            match={
                "trajectory_intersects": {
                    "geometry": UK_CORRIDOR,
                    "dwell_min_s": 7201,
                }
            }
        ),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["flights"] == []
