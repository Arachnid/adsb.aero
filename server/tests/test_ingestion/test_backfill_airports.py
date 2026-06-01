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

_INSERT_AIRPORT = """
    INSERT INTO airports
        (ident, type, name, location, elevation_ft, iso_country, iso_region,
         municipality, scheduled_service, icao_code, iata_code, local_code,
         keywords, fetched_at)
    VALUES
        ($1, $2, $3, ST_SetSRID(ST_MakePoint($4, $5), 4326), $6, $7, $8,
         $9, $10, $11, $12, $13, $14, NOW())
    ON CONFLICT (ident) DO NOTHING
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
_DELETE_AIRPORT = "DELETE FROM airports WHERE ident = ANY($1::text[])"


@pytest_asyncio.fixture
async def backfill_data(
    pool: asyncpg.Pool,  # type: ignore[type-arg]
    migrated_db: dict[str, str],
) -> None:
    """Insert test airports and flights (committed), yield, then clean up."""
    start_ts = datetime(2025, 6, 1, 10, 0, 0, tzinfo=UTC)
    end_ts = datetime(2025, 6, 1, 11, 0, 0, tzinfo=UTC)

    await pool.execute(
        _INSERT_AIRPORT,
        "XTEST1",
        "large_airport",
        "Test Start Airport",
        10.000,
        51.000,
        100,
        "DE",
        "DE-BE",
        "Berlin",
        True,
        "XTEST1",
        None,
        None,
        None,
    )
    await pool.execute(
        _INSERT_AIRPORT,
        "XTEST2",
        "large_airport",
        "Test End Airport",
        10.100,
        51.100,
        100,
        "DE",
        "DE-BE",
        "Berlin",
        True,
        "XTEST2",
        None,
        None,
        None,
    )
    # Start ~300 m from XTEST1, end ~300 m from XTEST2.
    path = (
        "[POINT Z (10.004 51.000 35000)@2025-06-01T10:00:00+00,"
        " POINT Z (10.104 51.100 35000)@2025-06-01T11:00:00+00]"
    )
    await pool.execute(
        _INSERT_FLIGHT,
        "xxtestx",
        "TST1",
        "B738",
        "A3",
        start_ts,
        end_ts,
        path,
        2,
        start_ts.date(),
    )
    yield
    await pool.execute(_DELETE_FLIGHT, "xxtestx")
    await pool.execute(_DELETE_AIRPORT, ["XTEST1", "XTEST2"])


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
    assert row["start_airport_ident"] == "XTEST1"
    assert row["end_airport_ident"] == "XTEST2"
