"""Tests for the OurAirports airports import."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from adsb_server.reference_data.airports import _parse_elevation, _parse_rows, _upsert_batch

if TYPE_CHECKING:
    import asyncpg

FIXTURES = Path(__file__).parent / "fixtures"


def _sample_csv() -> bytes:
    return (FIXTURES / "sample_airports.csv").read_bytes()


def test_parse_elevation_valid() -> None:
    assert _parse_elevation("83") == 83
    assert _parse_elevation("-10") == -10


def test_parse_elevation_empty_or_invalid() -> None:
    assert _parse_elevation("") is None
    assert _parse_elevation("n/a") is None


def test_parse_rows_count() -> None:
    rows = _parse_rows(_sample_csv())
    # BADCOORDS is skipped because latitude_deg and longitude_deg are empty.
    assert len(rows) == 2


def test_parse_rows_egll() -> None:
    rows = _parse_rows(_sample_csv())
    egll = next(r for r in rows if r[0] == "EGLL")
    assert egll[1] == "large_airport"
    assert egll[2] == "London Heathrow Airport"
    assert abs(egll[3] - (-0.461389)) < 1e-6  # lon
    assert abs(egll[4] - 51.4775) < 1e-6  # lat
    assert egll[5] == 83  # elevation_ft
    assert egll[6] == "GB"  # iso_country
    assert egll[7] == "GB-ENG"  # iso_region
    assert egll[8] == "London"  # municipality
    assert egll[9] is True  # scheduled_service
    assert egll[10] == "EGLL"  # icao_code
    assert egll[11] == "LHR"  # iata_code
    assert egll[12] is None  # local_code (empty)
    assert egll[13] == "Heathrow, London"  # keywords


def test_parse_rows_empty_optional_fields() -> None:
    rows = _parse_rows(_sample_csv())
    heliport = next(r for r in rows if r[0] == "00A")
    assert heliport[9] is False  # scheduled_service "no"
    assert heliport[10] is None  # icao_code empty → None
    assert heliport[11] is None  # iata_code empty → None
    assert heliport[13] is None  # keywords empty → None


def test_parse_rows_skips_missing_coords() -> None:
    rows = _parse_rows(_sample_csv())
    idents = {r[0] for r in rows}
    assert "BADCOORDS" not in idents


@pytest.mark.asyncio
async def test_upsert_airports(conn: asyncpg.Connection) -> None:  # type: ignore[type-arg]
    now = datetime.now(UTC)
    batch: list = [
        (
            "EGLL",
            "large_airport",
            "London Heathrow Airport",
            -0.461389,
            51.4775,
            83,
            "GB",
            "GB-ENG",
            "London",
            True,
            "EGLL",
            "LHR",
            None,
            "Heathrow",
            now,
        ),
        (
            "KSFO",
            "large_airport",
            "San Francisco Intl",
            -122.375,
            37.619,
            13,
            "US",
            "US-CA",
            "San Francisco",
            True,
            "KSFO",
            "SFO",
            None,
            None,
            now,
        ),
    ]
    await _upsert_batch(conn, batch)

    rows = await conn.fetch(
        "SELECT ident, icao_code, iata_code FROM airports"
        " WHERE ident IN ('EGLL', 'KSFO') ORDER BY ident"
    )
    assert len(rows) == 2
    assert rows[0]["ident"] == "EGLL"
    assert rows[0]["icao_code"] == "EGLL"
    assert rows[0]["iata_code"] == "LHR"
    assert rows[1]["ident"] == "KSFO"
    assert rows[1]["iata_code"] == "SFO"


@pytest.mark.asyncio
async def test_upsert_airports_location_is_point(
    conn: asyncpg.Connection,  # type: ignore[type-arg]
) -> None:
    now = datetime.now(UTC)
    await _upsert_batch(
        conn,
        [
            (
                "EGLL",
                "large_airport",
                "London Heathrow Airport",
                -0.461389,
                51.4775,
                83,
                "GB",
                "GB-ENG",
                "London",
                True,
                "EGLL",
                "LHR",
                None,
                None,
                now,
            )
        ],
    )
    row = await conn.fetchrow(
        "SELECT ST_X(location) AS lon, ST_Y(location) AS lat FROM airports WHERE ident = 'EGLL'"
    )
    assert row is not None
    assert abs(row["lon"] - (-0.461389)) < 1e-6
    assert abs(row["lat"] - 51.4775) < 1e-6


@pytest.mark.asyncio
async def test_search_vec_generated_column(
    conn: asyncpg.Connection,  # type: ignore[type-arg]
) -> None:
    now = datetime.now(UTC)
    await _upsert_batch(
        conn,
        [
            (
                "EGLL",
                "large_airport",
                "London Heathrow Airport",
                -0.461389,
                51.4775,
                83,
                "GB",
                "GB-ENG",
                "London",
                True,
                "EGLL",
                "LHR",
                None,
                None,
                now,
            ),
            (
                "KSFO",
                "large_airport",
                "San Francisco Intl",
                -122.375,
                37.619,
                13,
                "US",
                "US-CA",
                "San Francisco",
                True,
                "KSFO",
                "SFO",
                None,
                None,
                now,
            ),
        ],
    )
    rows = await conn.fetch(
        "SELECT ident FROM airports WHERE search_vec @@ to_tsquery('simple', 'heath:*')"
    )
    idents = {r["ident"] for r in rows}
    assert "EGLL" in idents
    assert "KSFO" not in idents  # 'heath' does not match San Francisco


@pytest.mark.asyncio
async def test_upsert_airports_on_conflict_updates(
    conn: asyncpg.Connection,  # type: ignore[type-arg]
) -> None:
    now = datetime.now(UTC)
    initial: list = [
        (
            "EGLL",
            "large_airport",
            "Heathrow",
            -0.461389,
            51.4775,
            83,
            "GB",
            "GB-ENG",
            "London",
            True,
            "EGLL",
            "LHR",
            None,
            None,
            now,
        )
    ]
    await _upsert_batch(conn, initial)

    updated: list = [
        (
            "EGLL",
            "large_airport",
            "London Heathrow Airport",
            -0.461389,
            51.4775,
            83,
            "GB",
            "GB-ENG",
            "London",
            True,
            "EGLL",
            "LHR",
            None,
            "Heathrow, LHR",
            now,
        )
    ]
    await _upsert_batch(conn, updated)

    row = await conn.fetchrow("SELECT name, keywords FROM airports WHERE ident = 'EGLL'")
    assert row is not None
    assert row["name"] == "London Heathrow Airport"
    assert row["keywords"] == "Heathrow, LHR"
