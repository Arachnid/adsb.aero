"""Fixtures for API integration tests."""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import TYPE_CHECKING

import pytest_asyncio
from httpx import ASGITransport, AsyncClient

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

    import asyncpg

from adsb_server.api.main import app
from adsb_server.geometry.h3_cells import path_h3_cells
from adsb_server.geometry.wkt import tfloat_seq, tgeompoint_seq, tint_seq, ttext_seq

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
        squawk_seq, raw_point_count, ingest_batch_date,
        path_h3, squawk_codes
    ) VALUES (
        $1, $2, $3, $4,
        $5, $6,
        $7::tgeompoint, $8::tint,
        $9::ttext, $10, $11,
        $12::h3index[], $13::text[]
    )
    ON CONFLICT (icao24, start_ts) DO NOTHING
"""

INSERT_AIRFRAME = """
    INSERT INTO airframes (icao24, registration, icao_type, flags, model, year, operator)
    VALUES ($1, $2, $3, $4, $5, $6, $7)
    ON CONFLICT (icao24) DO NOTHING
"""

# AGL data for integration tests (linear interpolation over baro-altitude waypoints).
# Flight A: London(34800)→midpoint(35700)→Manchester(34900) — min 34800, max 35700 ft AGL
# Flight B: Paris(37300)→Rome(36800) — min 36800, max 37300 ft AGL
FLIGHT_A_AGL = tfloat_seq([34800.0, 35700.0, 34900.0], [v[3] for v in _A_VERTS])
FLIGHT_B_AGL = tfloat_seq([37300.0, 36800.0], [v[3] for v in _B_VERTS])

_AGL_UPDATE = "UPDATE flights SET path_agl_ft = $1::tfloat WHERE icao24 = $2 AND start_ts = $3"

# Flight C: inside UK_CORRIDOR, 13:00-15:00.
# AGL peaks above 35000 ft only around 13:48-14:12 (the high-AGL window).
# Squawk "5555" is active only 13:00-13:30, which is BEFORE the high-AGL window.
# This makes Flight C a "nearly matching" case for squawk+AGL+geometry queries:
# the pre-filters all pass but the correlated EXISTS check fails.
FLIGHT_C_ICAO = "112233"
FLIGHT_C_CALLSIGN = "RYR456"
FLIGHT_C_TYPE = "B738"
FLIGHT_C_EMITTER = "A3"
FLIGHT_C_START_TS = datetime(2025, 4, 1, 13, 0, 0, tzinfo=UTC)
FLIGHT_C_END_TS = datetime(2025, 4, 1, 15, 0, 0, tzinfo=UTC)

_C_VERTS = [
    (-1.0, 51.5, 35000.0, 1743512400.0),  # 13:00
    (-1.5, 52.5, 35000.0, 1743516000.0),  # 14:00 — AGL peak
    (-2.0, 53.5, 35000.0, 1743519600.0),  # 15:00
]
FLIGHT_C_PATH = tgeompoint_seq(_C_VERTS)
FLIGHT_C_TRACKS = tint_seq([315, 315, 315], [v[3] for v in _C_VERTS])

# AGL ≥ 35000 window: ~13:48-14:12 (computed from linear interpolation between 33000→35500→33000)
# Squawk "5555" window: 13:00-13:30 — entirely before the high-AGL window, so never concurrent
FLIGHT_C_AGL = tfloat_seq([33000.0, 35500.0, 33000.0], [v[3] for v in _C_VERTS])
_FLIGHT_C_SQUAWK_END = 1743514200.0  # 13:30

FLIGHT_A_REGISTRATION = "G-TESTA"
FLIGHT_A_MODEL = "BOEING 737-800"
FLIGHT_A_YEAR = 2010
FLIGHT_A_OPERATOR = "Test Airways"


@pytest_asyncio.fixture(scope="session")
async def api_test_data(pool: asyncpg.Pool) -> None:
    """Insert test flights into the DB once per session (no rollback)."""
    await pool.execute(
        INSERT_FLIGHT,
        FLIGHT_A_ICAO,
        FLIGHT_A_CALLSIGN,
        FLIGHT_A_TYPE,
        FLIGHT_A_EMITTER,
        FLIGHT_A_START_TS,
        FLIGHT_A_END_TS,
        FLIGHT_A_PATH,
        FLIGHT_A_TRACKS,
        ttext_seq([(1743501600.0, "1234"), (1743508800.0, "1234")]),
        30,
        date(2025, 4, 1),
        path_h3_cells([_A_VERTS]),
        ["1234"],  # squawk_codes seen on flight A
    )
    await pool.execute(
        INSERT_FLIGHT,
        FLIGHT_B_ICAO,
        FLIGHT_B_CALLSIGN,
        FLIGHT_B_TYPE,
        FLIGHT_B_EMITTER,
        FLIGHT_B_START_TS,
        FLIGHT_B_END_TS,
        FLIGHT_B_PATH,
        FLIGHT_B_TRACKS,
        None,
        50,
        date(2025, 4, 1),
        path_h3_cells([_B_VERTS]),
        [],  # no squawk data for flight B
    )
    await pool.execute(
        INSERT_FLIGHT,
        FLIGHT_C_ICAO,
        FLIGHT_C_CALLSIGN,
        FLIGHT_C_TYPE,
        FLIGHT_C_EMITTER,
        FLIGHT_C_START_TS,
        FLIGHT_C_END_TS,
        FLIGHT_C_PATH,
        FLIGHT_C_TRACKS,
        ttext_seq([(1743512400.0, "5555"), (_FLIGHT_C_SQUAWK_END, "5555")]),
        20,
        date(2025, 4, 1),
        path_h3_cells([_C_VERTS]),
        ["5555"],
    )
    await pool.execute(_AGL_UPDATE, FLIGHT_A_AGL, FLIGHT_A_ICAO, FLIGHT_A_START_TS)
    await pool.execute(_AGL_UPDATE, FLIGHT_B_AGL, FLIGHT_B_ICAO, FLIGHT_B_START_TS)
    await pool.execute(_AGL_UPDATE, FLIGHT_C_AGL, FLIGHT_C_ICAO, FLIGHT_C_START_TS)
    # Airframe data for flight A only; flight B tests the null case.
    await pool.execute(
        INSERT_AIRFRAME,
        FLIGHT_A_ICAO,
        FLIGHT_A_REGISTRATION,
        FLIGHT_A_TYPE,
        0,
        FLIGHT_A_MODEL,
        FLIGHT_A_YEAR,
        FLIGHT_A_OPERATOR,
    )


@pytest_asyncio.fixture(scope="session")
async def api_client(
    pool: asyncpg.Pool,
    api_test_data: None,
) -> AsyncGenerator[AsyncClient]:
    """Session-scoped AsyncClient wired to the app with the test pool."""
    app.state.pool = pool
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client
