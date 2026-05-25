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


# ---------------------------------------------------------------------------
# AGL height filter integration tests
#
# Flight A (London→Manchester): path_agl_ft min=34800, max=35700 ft AGL
# Flight B (Paris→Rome):        path_agl_ft min=36800, max=37300 ft AGL
# ---------------------------------------------------------------------------


async def test_agl_intersects_min_no_geometry(api_client: AsyncClient) -> None:
    # ever: agl_min_ft=36000 → only Flight B qualifies (maxvalue 37300 ≥ 36000).
    # Flight A maxvalue is 35700 < 36000 so it is excluded.
    resp = await api_client.post(
        "/api/v1/query",
        json=qbody(match={"trajectory_intersects": {"agl_min_ft": 36000}}),
    )
    assert resp.status_code == 200
    ids = {f["flight_id"] for f in resp.json()["flights"]}
    assert "ddeeff:2025-04-01T06:00:00Z" in ids
    assert "aabbcc:2025-04-01T10:00:00Z" not in ids


async def test_agl_intersects_min_no_match(api_client: AsyncClient) -> None:
    # ever: agl_min_ft=38000 → no flight ever reaches this AGL.
    resp = await api_client.post(
        "/api/v1/query",
        json=qbody(match={"trajectory_intersects": {"agl_min_ft": 38000}}),
    )
    assert resp.status_code == 200
    assert resp.json()["flights"] == []


async def test_agl_within_min_no_geometry(api_client: AsyncClient) -> None:
    # always: agl_min_ft=34000 → both flights qualify (A min 34800, B min 36800, both ≥ 34000).
    # always: agl_min_ft=35000 → only Flight B (A min 34800 < 35000).
    resp_34k = await api_client.post(
        "/api/v1/query",
        json=qbody(match={"trajectory_within": {"agl_min_ft": 34000}}),
    )
    assert resp_34k.status_code == 200
    ids_34k = {f["flight_id"] for f in resp_34k.json()["flights"]}
    assert "aabbcc:2025-04-01T10:00:00Z" in ids_34k
    assert "ddeeff:2025-04-01T06:00:00Z" in ids_34k

    resp_35k = await api_client.post(
        "/api/v1/query",
        json=qbody(match={"trajectory_within": {"agl_min_ft": 35000}}),
    )
    assert resp_35k.status_code == 200
    ids_35k = {f["flight_id"] for f in resp_35k.json()["flights"]}
    assert "aabbcc:2025-04-01T10:00:00Z" not in ids_35k
    assert "ddeeff:2025-04-01T06:00:00Z" in ids_35k


async def test_agl_within_max_no_geometry(api_client: AsyncClient) -> None:
    # always: agl_max_ft=36000 → only Flight A (max 35700 ≤ 36000; B max 37300 > 36000).
    # always: agl_max_ft=34000 → no flight qualifies (A max 35700 > 34000).
    resp_36k = await api_client.post(
        "/api/v1/query",
        json=qbody(match={"trajectory_within": {"agl_max_ft": 36000}}),
    )
    assert resp_36k.status_code == 200
    ids_36k = {f["flight_id"] for f in resp_36k.json()["flights"]}
    assert "aabbcc:2025-04-01T10:00:00Z" in ids_36k
    assert "ddeeff:2025-04-01T06:00:00Z" not in ids_36k

    resp_34k = await api_client.post(
        "/api/v1/query",
        json=qbody(match={"trajectory_within": {"agl_max_ft": 34000}}),
    )
    assert resp_34k.status_code == 200
    assert resp_34k.json()["flights"] == []


async def test_agl_with_geometry_intersects(api_client: AsyncClient) -> None:
    # ever + UK_CORRIDOR: Flight A path is entirely inside the corridor.
    # agl_min_ft=35000: Flight A has instants ≥ 35000 ft AGL inside the corridor → matches.
    # agl_min_ft=36000: Flight A max AGL is 35700 < 36000 → no qualifying instant → excluded.
    resp_match = await api_client.post(
        "/api/v1/query",
        json=qbody(match={"trajectory_intersects": {"geometry": UK_CORRIDOR, "agl_min_ft": 35000}}),
    )
    assert resp_match.status_code == 200
    ids_match = {f["flight_id"] for f in resp_match.json()["flights"]}
    assert "aabbcc:2025-04-01T10:00:00Z" in ids_match

    resp_excl = await api_client.post(
        "/api/v1/query",
        json=qbody(match={"trajectory_intersects": {"geometry": UK_CORRIDOR, "agl_min_ft": 36000}}),
    )
    assert resp_excl.status_code == 200
    ids_excl = {f["flight_id"] for f in resp_excl.json()["flights"]}
    assert "aabbcc:2025-04-01T10:00:00Z" not in ids_excl


# ---------------------------------------------------------------------------
# AGL + geometry + dwell/distance/squawk combined tests
#
# "Nearly matching" means the flight satisfies the dwell/distance/squawk bound
# globally AND satisfies the AGL bound somewhere inside the geometry, but the
# two conditions do not overlap at the same instants — so the combined query
# must NOT return the flight.
#
# Flight A (London→Manchester, 10:00-12:00, UK_CORRIDOR):
#   path_agl_ft min=34800 max=35700 ft AGL; AGL ≥ 35000 for ~5950 s (10:13-11:49)
#   total dwell in corridor = 7200 s; AGL-clipped dwell = 5950 s
#   total distance in corridor ≈ 261 km; AGL-clipped distance ≈ 216 km
#   squawk "1234" active throughout — concurrent with AGL ≥ 35000 window
#
# Flight C (inside UK_CORRIDOR, 13:00-15:00):
#   path_agl_ft peaks at 35500 ft AGL only around 13:48-14:12
#   squawk "5555" active only 13:00-13:30 (entirely before the high-AGL window)
# ---------------------------------------------------------------------------


async def test_agl_dwell_geometry_match(api_client: AsyncClient) -> None:
    # AGL-clipped dwell ~5950 s > 5000 s → Flight A matches.
    resp = await api_client.post(
        "/api/v1/query",
        json=qbody(
            match={
                "trajectory_intersects": {
                    "geometry": UK_CORRIDOR,
                    "agl_min_ft": 35000,
                    "dwell_min_s": 5000,
                }
            }
        ),
    )
    assert resp.status_code == 200
    assert "aabbcc:2025-04-01T10:00:00Z" in {f["flight_id"] for f in resp.json()["flights"]}


async def test_agl_dwell_geometry_near_miss(api_client: AsyncClient) -> None:
    # Flight A's total dwell in the corridor is 7200 s (would pass a plain dwell_min_s=6500
    # check).  Its AGL-clipped dwell is only ~5950 s, which is below 6500 s → must not match.
    resp = await api_client.post(
        "/api/v1/query",
        json=qbody(
            match={
                "trajectory_intersects": {
                    "geometry": UK_CORRIDOR,
                    "agl_min_ft": 35000,
                    "dwell_min_s": 6500,
                }
            }
        ),
    )
    assert resp.status_code == 200
    assert "aabbcc:2025-04-01T10:00:00Z" not in {f["flight_id"] for f in resp.json()["flights"]}


async def test_agl_distance_geometry_match(api_client: AsyncClient) -> None:
    # AGL-clipped distance ≈ 216 km > 180 km → Flight A matches.
    resp = await api_client.post(
        "/api/v1/query",
        json=qbody(
            match={
                "trajectory_intersects": {
                    "geometry": UK_CORRIDOR,
                    "agl_min_ft": 35000,
                    "distance_min_m": 180000,
                }
            }
        ),
    )
    assert resp.status_code == 200
    assert "aabbcc:2025-04-01T10:00:00Z" in {f["flight_id"] for f in resp.json()["flights"]}


async def test_agl_distance_geometry_near_miss(api_client: AsyncClient) -> None:
    # Flight A's total corridor distance ≈ 261 km (would pass a plain distance_min_m=230000
    # check).  Its AGL-clipped distance ≈ 216 km, which is below 230 km → must not match.
    resp = await api_client.post(
        "/api/v1/query",
        json=qbody(
            match={
                "trajectory_intersects": {
                    "geometry": UK_CORRIDOR,
                    "agl_min_ft": 35000,
                    "distance_min_m": 230000,
                }
            }
        ),
    )
    assert resp.status_code == 200
    assert "aabbcc:2025-04-01T10:00:00Z" not in {f["flight_id"] for f in resp.json()["flights"]}


async def test_agl_squawk_geometry_match(api_client: AsyncClient) -> None:
    # Flight A: squawk "1234" active throughout, AGL ≥ 35000 during 10:13-11:49 → concurrent.
    resp = await api_client.post(
        "/api/v1/query",
        json=qbody(
            match={
                "trajectory_intersects": {
                    "geometry": UK_CORRIDOR,
                    "agl_min_ft": 35000,
                    "squawk_codes": ["1234"],
                }
            }
        ),
    )
    assert resp.status_code == 200
    assert "aabbcc:2025-04-01T10:00:00Z" in {f["flight_id"] for f in resp.json()["flights"]}


async def test_agl_squawk_geometry_near_miss(api_client: AsyncClient) -> None:
    # Flight C: inside the corridor, AGL ≥ 35000 during 13:48-14:12, squawk "5555" only
    # during 13:00-13:30.  Pre-filters all pass (maxvalue ≥ 35000, squawk_codes GIN matches)
    # but the correlated EXISTS check finds no squawk instants during the AGL window → no match.
    resp = await api_client.post(
        "/api/v1/query",
        json=qbody(
            match={
                "trajectory_intersects": {
                    "geometry": UK_CORRIDOR,
                    "agl_min_ft": 35000,
                    "squawk_codes": ["5555"],
                }
            }
        ),
    )
    assert resp.status_code == 200
    assert "112233:2025-04-01T13:00:00Z" not in {f["flight_id"] for f in resp.json()["flights"]}


async def test_agl_with_geometry_within(api_client: AsyncClient) -> None:
    # always + UK_CORRIDOR: the entire Flight A path lies inside the corridor.
    # agl_min_ft=34000: min AGL inside corridor = 34800 ≥ 34000 → matches.
    # agl_min_ft=35000: min AGL = 34800 < 35000 → excluded.
    resp_match = await api_client.post(
        "/api/v1/query",
        json=qbody(match={"trajectory_within": {"geometry": UK_CORRIDOR, "agl_min_ft": 34000}}),
    )
    assert resp_match.status_code == 200
    ids_match = {f["flight_id"] for f in resp_match.json()["flights"]}
    assert "aabbcc:2025-04-01T10:00:00Z" in ids_match

    resp_excl = await api_client.post(
        "/api/v1/query",
        json=qbody(match={"trajectory_within": {"geometry": UK_CORRIDOR, "agl_min_ft": 35000}}),
    )
    assert resp_excl.status_code == 200
    ids_excl = {f["flight_id"] for f in resp_excl.json()["flights"]}
    assert "aabbcc:2025-04-01T10:00:00Z" not in ids_excl
