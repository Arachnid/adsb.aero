"""Fixtures for API integration tests."""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import TYPE_CHECKING

import pytest
from httpx import ASGITransport, AsyncClient

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

    import asyncpg

from adsb_server.api.main import app
from adsb_server.geometry.wkt import tgeompoint_seq, tint_seq

# ---------------------------------------------------------------------------
# Test flight data
# ---------------------------------------------------------------------------

FLIGHT_A_ICAO = "aabbcc"
FLIGHT_A_CALLSIGN = "BAW123"
FLIGHT_A_TYPE = "B738"
FLIGHT_A_EMITTER = "A3"
FLIGHT_A_START_TS = datetime(2025, 4, 1, 10, 0, 0, tzinfo=UTC)
FLIGHT_A_END_TS = datetime(2025, 4, 1, 12, 0, 0, tzinfo=UTC)

FLIGHT_B_ICAO = "ddeeff"
FLIGHT_B_CALLSIGN = "AFR999"
FLIGHT_B_TYPE = "A320"
FLIGHT_B_EMITTER = "A3"
FLIGHT_B_START_TS = datetime(2025, 4, 1, 6, 0, 0, tzinfo=UTC)
FLIGHT_B_END_TS = datetime(2025, 4, 1, 9, 0, 0, tzinfo=UTC)

# Flight A path: London → midpoint → Manchester
_A_VERTS = [
    (-0.1275, 51.5072, 35000.0, 1743501600.0),
    (-1.2, 52.5, 36000.0, 1743505200.0),
    (-2.2667, 53.4667, 35000.0, 1743508800.0),
]
FLIGHT_A_PATH = tgeompoint_seq(_A_VERTS)
FLIGHT_A_TRACKS = tint_seq([90, 315, 315], [v[3] for v in _A_VERTS])

# Flight B path: Paris → Rome
_B_VERTS = [
    (2.3490, 48.8600, 38000.0, 1743487200.0),
    (12.4964, 41.9028, 38000.0, 1743498000.0),
]
FLIGHT_B_PATH = tgeompoint_seq(_B_VERTS)
FLIGHT_B_TRACKS = tint_seq([135, 135], [v[3] for v in _B_VERTS])

INSERT_FLIGHT = """
    INSERT INTO flights (
        icao24, callsign, icao_type, emitter_category,
        start_ts, end_ts,
        path, path_tracks,
        squawk_runs, raw_point_count, ingest_batch_date
    ) VALUES (
        $1, $2, $3, $4,
        $5, $6,
        $7::tgeompoint, $8::tint,
        $9::jsonb, $10, $11
    )
    ON CONFLICT (icao24, start_ts) DO NOTHING
"""


@pytest.fixture(scope="session")
async def api_test_data(pool: asyncpg.Pool) -> None:
    """Insert test flights into the DB once per session (no rollback)."""
    await pool.execute(
        INSERT_FLIGHT,
        FLIGHT_A_ICAO, FLIGHT_A_CALLSIGN, FLIGHT_A_TYPE, FLIGHT_A_EMITTER,
        FLIGHT_A_START_TS, FLIGHT_A_END_TS,
        FLIGHT_A_PATH, FLIGHT_A_TRACKS,
        "[[1743501600.0,\"1234\"]]", 30, date(2025, 4, 1),
    )
    await pool.execute(
        INSERT_FLIGHT,
        FLIGHT_B_ICAO, FLIGHT_B_CALLSIGN, FLIGHT_B_TYPE, FLIGHT_B_EMITTER,
        FLIGHT_B_START_TS, FLIGHT_B_END_TS,
        FLIGHT_B_PATH, FLIGHT_B_TRACKS,
        "[]", 50, date(2025, 4, 1),
    )


@pytest.fixture(scope="session")
async def api_client(
    pool: asyncpg.Pool,
    api_test_data: None,
) -> AsyncGenerator[AsyncClient, None]:
    """Session-scoped AsyncClient wired to the app with the test pool."""
    app.state.pool = pool
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        yield client
