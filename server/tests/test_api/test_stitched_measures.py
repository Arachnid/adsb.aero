"""Integration tests for dwell/distance measured across coverage gaps.

Flight G has two observed stretches with a 20-minute coverage gap between them,
so every measure here has a distinct stitched and unstitched answer, and each
test picks a threshold that only the stitched one satisfies (or fails).

    11:00 (10.0°E, 5000 ft) → 11:05 (10.1°E, 5000 ft)     observed
    11:05 ──────────────── gap ───────────────── 11:25     bridged, climbing
    11:25 (10.5°E, 15000 ft) → 11:30 (10.6°E, 15000 ft)   observed

All along 60°N, where one degree of longitude is ~55.8 km.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import TYPE_CHECKING, Any

import pytest
import pytest_asyncio

from adsb_server.geometry.h3_cells import path_h3_cells
from adsb_server.geometry.wkt import tgeompoint_seqset
from tests.test_api.conftest import FILL_PATH_LENGTH, INSERT_FLIGHT

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

    import asyncpg
    from httpx import AsyncClient

pytestmark = pytest.mark.asyncio

_ICAO = "0a0b0c"
_START = datetime(2025, 4, 1, 11, 0, tzinfo=UTC)
_END = datetime(2025, 4, 1, 11, 30, tzinfo=UTC)
_FLIGHT_ID = "0a0b0c:2025-04-01T11:00:00Z"
_T0 = _START.timestamp()

_SEQS = [
    [(10.0, 60.0, 5000.0, _T0), (10.1, 60.0, 5000.0, _T0 + 300)],
    [(10.5, 60.0, 15000.0, _T0 + 1500), (10.6, 60.0, 15000.0, _T0 + 1800)],
]

# Only covers the first observed stretch and the start of the gap: the bridge
# leaves it at 10.2°E, which it reaches at 11:10.
_WEST_BOX = {
    "type": "Polygon",
    "coordinates": [[[9.9, 59.9], [10.2, 59.9], [10.2, 60.1], [9.9, 60.1], [9.9, 59.9]]],
}

_RANGE = {"end_date": "2025-04-02T00:00:00Z", "window_days": 2}


@pytest_asyncio.fixture
async def gap_flight(pool: asyncpg.Pool, api_client: AsyncClient) -> AsyncGenerator[None]:
    """Insert Flight G for one test; its date sits inside the session data's range."""
    await pool.execute(
        INSERT_FLIGHT,
        _ICAO,
        "GAP001",
        "C172",
        "A1",
        _START,
        _END,
        tgeompoint_seqset(_SEQS),
        None,
        None,
        10,
        date(2025, 4, 1),
        path_h3_cells(_SEQS),
        [],
    )
    await pool.execute(FILL_PATH_LENGTH)
    try:
        yield
    finally:
        await pool.execute("DELETE FROM flights WHERE icao24 = $1 AND start_ts = $2", _ICAO, _START)


async def _matches(api_client: AsyncClient, match: dict[str, Any]) -> bool:
    resp = await api_client.post(
        "/api/v1/query", json={**_RANGE, "match": match, "include_path": False}
    )
    assert resp.status_code == 200, resp.text
    return _FLIGHT_ID in {f["flight_id"] for f in resp.json()["flights"]}


@pytest.mark.usefixtures("gap_flight")
@pytest.mark.parametrize(
    ("value", "expected"),
    [
        # Whole flight: 1800 s stitched (only 600 s observed).
        ({"dwell_min_s": 1700}, True),
        ({"dwell_max_s": 1000}, False),
        # Whole flight: ~33.5 km stitched (only ~11.2 km observed).
        ({"distance_min_m": 30000}, True),
        ({"distance_min_m": 36000}, False),
    ],
)
async def test_always_without_region_measures_whole_flight(
    api_client: AsyncClient, value: dict[str, float], expected: bool
) -> None:
    assert await _matches(api_client, {"trajectory_within": value}) is expected


@pytest.mark.usefixtures("gap_flight")
async def test_whole_flight_dwell_agrees_with_duration(api_client: AsyncClient) -> None:
    assert await _matches(api_client, {"duration": {"min_s": 1800, "max_s": 1800}})
    assert await _matches(api_client, {"trajectory_within": {"dwell_min_s": 1800}})


@pytest.mark.usefixtures("gap_flight")
@pytest.mark.parametrize(("dwell_min_s", "expected"), [(550, True), (650, False)])
async def test_geometry_dwell_bridges_gap_but_not_exit(
    api_client: AsyncClient, dwell_min_s: int, expected: bool
) -> None:
    # Inside the box 11:00-11:10 on the stitched path = 600 s.  Observed only 300 s,
    # so 550 proves the gap is bridged; 650 proves the bridge is still clipped where
    # it leaves the box rather than counted to the far side of the gap.
    match = {"trajectory_intersects": {"geometry": _WEST_BOX, "dwell_min_s": dwell_min_s}}
    assert await _matches(api_client, match) is expected


@pytest.mark.usefixtures("gap_flight")
@pytest.mark.parametrize(("dwell_min_s", "expected"), [(850, True), (950, False)])
async def test_ever_altitude_without_region_measures_time_in_band(
    api_client: AsyncClient, dwell_min_s: int, expected: bool
) -> None:
    # The bridge climbs 5000 → 15000 ft over 11:05-11:25, crossing FL100 at 11:15:
    # 900 s at or above it.  Observed alone it would be 300 s.
    match = {
        "trajectory_intersects": {
            "altitude_min": 100,
            "altitude_min_ref": "fl",
            "dwell_min_s": dwell_min_s,
        }
    }
    assert await _matches(api_client, match) is expected


@pytest.mark.usefixtures("gap_flight")
@pytest.mark.parametrize(("distance_min_m", "expected"), [(10000, True), (12000, False)])
async def test_time_window_clips_distance(
    api_client: AsyncClient, distance_min_m: int, expected: bool
) -> None:
    # From 11:20 the stitched path runs 10.4°E → 10.6°E ≈ 11.2 km; observed only
    # the last 0.1° ≈ 5.6 km.
    match = {
        "trajectory_intersects": {
            "time_from": "2025-04-01T11:20:00Z",
            "distance_min_m": distance_min_m,
        }
    }
    assert await _matches(api_client, match) is expected


@pytest.mark.usefixtures("gap_flight")
async def test_ft_altitude_clip_with_agl_runs(api_client: AsyncClient) -> None:
    # Flight G has no QNH correction or AGL series; the stitched-correction CASE
    # falls back to pressure altitude, and the AGL bound excludes it outright.
    assert await _matches(
        api_client,
        {"trajectory_intersects": {"altitude_min": 10000, "dwell_min_s": 850}},
    )
    assert not await _matches(
        api_client,
        {"trajectory_intersects": {"agl_min_ft": 0, "dwell_min_s": 60}},
    )
