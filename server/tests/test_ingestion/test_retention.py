"""Integration tests for adsb_server.ingestion.retention."""

from __future__ import annotations

from datetime import date, timedelta
from typing import TYPE_CHECKING

from adsb_server.ingestion.retention import (
    flights_retention_interval,
    purge_expired_staging,
)

if TYPE_CHECKING:
    import asyncpg

_OLD = date(2020, 1, 1)
_RECENT = date.today() - timedelta(days=30)


async def _set_retention(conn: asyncpg.Connection, value: str | None) -> None:
    await conn.execute(
        "UPDATE partman.part_config SET retention = $1 WHERE parent_table = 'public.flights'",
        value,
    )


async def _add_staging(conn: asyncpg.Connection, batch_date: date) -> None:
    await conn.execute(
        "INSERT INTO flight_staging (batch_date, staging_data) VALUES ($1, $2)"
        " ON CONFLICT (batch_date) DO NOTHING",
        batch_date,
        b"blob",
    )


async def _staging_dates(conn: asyncpg.Connection) -> set[date]:
    rows = await conn.fetch("SELECT batch_date FROM flight_staging")
    return {r["batch_date"] for r in rows}


async def test_reads_the_window_from_partman(conn: asyncpg.Connection) -> None:
    await _set_retention(conn, "18 months")
    assert await flights_retention_interval(conn) == "18 months"


async def test_no_window_configured_means_no_window_invented(
    conn: asyncpg.Connection,
) -> None:
    await _set_retention(conn, None)
    await _add_staging(conn, _OLD)

    assert await flights_retention_interval(conn) is None
    assert await purge_expired_staging(conn) == 0
    assert _OLD in await _staging_dates(conn), "nothing is deleted without a policy"


async def test_purges_only_rows_outside_the_window(conn: asyncpg.Connection) -> None:
    await _set_retention(conn, "18 months")
    await _add_staging(conn, _OLD)
    await _add_staging(conn, _RECENT)

    deleted = await purge_expired_staging(conn)

    assert deleted >= 1
    dates = await _staging_dates(conn)
    assert _OLD not in dates
    # Inside the window the blob is kept: it is what makes re-importing a day
    # cheap if traces have to be regenerated.
    assert _RECENT in dates


async def test_purge_is_idempotent(conn: asyncpg.Connection) -> None:
    await _set_retention(conn, "18 months")
    await _add_staging(conn, _OLD)

    assert await purge_expired_staging(conn) >= 1
    assert await purge_expired_staging(conn) == 0


async def test_window_spelling_does_not_matter(conn: asyncpg.Connection) -> None:
    """partman stores retention as free text; '1 year 6 mons' is the same window."""
    await _set_retention(conn, "1 year 6 mons")
    await _add_staging(conn, _OLD)
    await _add_staging(conn, _RECENT)

    assert await purge_expired_staging(conn) >= 1
    dates = await _staging_dates(conn)
    assert _OLD not in dates
    assert _RECENT in dates
