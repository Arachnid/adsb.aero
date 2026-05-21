"""Fetch tar1090-db aircraft.csv.gz and upsert into the airframes table.

Columns (semicolon-delimited, no header):
  icao24 ; registration ; icao_type ; flags ; model ; year ; operator ; <trailing null>

flags is a bit string (e.g. "0010"): bit 0 = military, bit 3 = FAA LADD.
Parsed to SMALLINT by treating each character as a bit (char 0 → LSB).

Usage:
    python -m adsb_server.reference_data.airframes
"""

from __future__ import annotations

import asyncio
import csv
import io
import logging
import sys
from datetime import UTC, datetime

import asyncpg
import httpx
import sentry_sdk

from adsb_server.config import get_settings

CSV_URL = "https://github.com/wiedehopf/tar1090-db/raw/refs/heads/csv/aircraft.csv.gz"
BATCH_SIZE = 10_000

logger = logging.getLogger(__name__)


def _parse_flags(raw: str) -> int:
    """Parse a bit-string flag field (e.g. '0010') to an integer.

    Each character is a bit: char 0 is the LSB (bit 0 = military).
    """
    result = 0
    for i, ch in enumerate(raw):
        if ch == "1":
            result |= 1 << i
    return result


def _parse_year(raw: str) -> int | None:
    try:
        return int(raw) if raw else None
    except ValueError:
        return None


async def _fetch_csv() -> bytes:
    async with httpx.AsyncClient(timeout=60, follow_redirects=True) as client:
        resp = await client.get(CSV_URL)
        resp.raise_for_status()
        return resp.content


Row = tuple[str, str | None, str | None, int, str | None, int | None, str | None, datetime]


def _parse_rows(data: bytes) -> list[Row]:
    import gzip

    now = datetime.now(UTC)
    rows = []
    with gzip.open(io.BytesIO(data)) as f:
        reader = csv.reader(
            io.TextIOWrapper(f, encoding="utf-8", errors="replace"),
            delimiter=";",
            escapechar="\\",
            quoting=csv.QUOTE_NONE,
            quotechar=None,
        )
        for row in reader:
            if len(row) < 4:
                continue
            icao24 = row[0].strip().lower()
            if len(icao24) != 6:
                continue
            rows.append(
                (
                    icao24,
                    row[1].strip() or None,
                    row[2].strip() or None,
                    _parse_flags(row[3].strip()),
                    row[4].strip() or None if len(row) > 4 else None,
                    _parse_year(row[5].strip()) if len(row) > 5 else None,
                    row[6].strip() or None if len(row) > 6 else None,
                    now,
                )
            )
    return rows


async def _upsert_batch(
    conn: asyncpg.Connection[asyncpg.Record],
    batch: list[Row],
) -> None:
    await conn.executemany(
        """
        INSERT INTO airframes
            (icao24, registration, icao_type, flags, model, year, operator, fetched_at)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
        ON CONFLICT (icao24) DO UPDATE SET
            registration = EXCLUDED.registration,
            icao_type    = EXCLUDED.icao_type,
            flags        = EXCLUDED.flags,
            model        = EXCLUDED.model,
            year         = EXCLUDED.year,
            operator     = EXCLUDED.operator,
            fetched_at   = EXCLUDED.fetched_at
        """,
        batch,
    )


@sentry_sdk.monitor(  # type: ignore[misc]
    monitor_slug="import-airframes",
    monitor_config={
        "schedule": {"type": "crontab", "value": "0 3 * * 0"},
        "timezone": "UTC",
        "checkin_margin": 60,
        "max_runtime": 60,
    },
)
async def _main() -> None:
    settings = get_settings()
    print(f"Fetching {CSV_URL} ...", file=sys.stderr)
    data = await _fetch_csv()
    print(f"Downloaded {len(data):,} bytes. Parsing...", file=sys.stderr)

    rows = _parse_rows(data)
    print(f"Parsed {len(rows):,} airframe records. Upserting...", file=sys.stderr)

    conn: asyncpg.Connection[asyncpg.Record] = await asyncpg.connect(settings.asyncpg_dsn)
    try:
        for i in range(0, len(rows), BATCH_SIZE):
            await _upsert_batch(conn, rows[i : i + BATCH_SIZE])
            print(f"  {min(i + BATCH_SIZE, len(rows)):,} / {len(rows):,}", file=sys.stderr)

        count: int = await conn.fetchval("SELECT COUNT(*) FROM airframes")
        print(f"Done. {count:,} rows in airframes table.", file=sys.stderr)
    except Exception:
        logger.exception("Import failed")
        raise
    finally:
        await conn.close()


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=sys.stderr,
    )
    settings = get_settings()
    settings.init_sentry()
    try:
        asyncio.run(_main())
    except Exception:
        sys.exit(1)


if __name__ == "__main__":
    main()
