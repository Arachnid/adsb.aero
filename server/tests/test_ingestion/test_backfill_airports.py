"""Integration tests for backfill_airports."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest
import pytest_asyncio

from adsb_server.ingestion.backfill_airports import run_backfill

if TYPE_CHECKING:
    import asyncpg

pytestmark = pytest.mark.asyncio

_INSERT_WAYPOINT = """
    INSERT INTO waypoints
        (id, kind, name, ident, type_code, country,
         location, fetched_at)
    VALUES ($1, 'airport', $2, $3, $4, $5,
            ST_SetSRID(ST_MakePoint($6, $7), 4326), NOW())
    ON CONFLICT (id) DO NOTHING
"""

_INSERT_FLIGHT = """
    INSERT INTO flights (
        icao24, callsign, icao_type, emitter_category,
        start_ts, end_ts, path, raw_point_count, ingest_batch_date,
        path_h3, squawk_codes
    ) VALUES (
        $1, $2, $3, $4, $5, $6,
        $7::tgeompoint, $8, $9, '{}'::h3index[], '{}'::text[]
    )
    ON CONFLICT (icao24, start_ts) DO NOTHING
"""

_DELETE_FLIGHT = "DELETE FROM flights WHERE icao24 = $1"
_DELETE_WAYPOINT = "DELETE FROM waypoints WHERE id = ANY($1::text[])"


@pytest_asyncio.fixture
async def backfill_data(
    pool: asyncpg.Pool,  # type: ignore[type-arg]
    migrated_db: dict[str, str],
) -> None:
    start_ts = datetime(2025, 6, 1, 10, 0, 0, tzinfo=UTC)
    end_ts = datetime(2025, 6, 1, 11, 0, 0, tzinfo=UTC)

    # Waypoint ~300 m from start, another ~300 m from end.
    await pool.execute(_INSERT_WAYPOINT, "xtest-1", "Test Start", "XTEST1", 3, "DE", 10.000, 51.000)
    await pool.execute(_INSERT_WAYPOINT, "xtest-2", "Test End", "XTEST2", 3, "DE", 10.100, 51.100)
    path = (
        "[POINT Z (10.004 51.000 35000)@2025-06-01T10:00:00+00,"
        " POINT Z (10.104 51.100 35000)@2025-06-01T11:00:00+00]"
    )
    await pool.execute(
        _INSERT_FLIGHT, "xxtestx", "TST1", "B738", "A3", start_ts, end_ts, path, 2, start_ts.date()
    )
    yield
    await pool.execute(_DELETE_FLIGHT, "xxtestx")
    await pool.execute(_DELETE_WAYPOINT, ["xtest-1", "xtest-2"])


async def test_backfill_assigns_start_and_end_airports(
    pool: asyncpg.Pool,  # type: ignore[type-arg]
    migrated_db: dict[str, str],
    backfill_data: None,
) -> None:
    dsn = (
        f"postgresql://{migrated_db['POSTGRES_USER']}:{migrated_db['POSTGRES_PASSWORD']}"
        f"@{migrated_db['POSTGRES_HOST']}:{migrated_db['POSTGRES_PORT']}"
        f"/{migrated_db['POSTGRES_DB']}"
    )
    start_ts = datetime(2025, 6, 1, 10, 0, 0, tzinfo=UTC)
    await run_backfill(dsn)

    row = await pool.fetchrow(
        "SELECT start_airport_ident, end_airport_ident FROM flights"
        " WHERE icao24 = 'xxtestx' AND start_ts = $1",
        start_ts,
    )
    assert row is not None
    # start_airport_ident stores the waypoints.id (OpenAIP _id), not the ident.
    assert row["start_airport_ident"] == "xtest-1"
    assert row["end_airport_ident"] == "xtest-2"
