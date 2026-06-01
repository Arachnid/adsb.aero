"""Fetch OurAirports airports.csv and upsert into the airports table.

Source: https://davidmegginson.github.io/ourairports-data/airports.csv

Columns (comma-delimited, with header):
  id, ident, type, name, latitude_deg, longitude_deg, elevation_ft,
  continent, iso_country, iso_region, municipality, scheduled_service,
  icao_code, iata_code, gps_code, local_code, home_link,
  wikipedia_link, keywords

Usage:
    python -m adsb_server.reference_data.airports
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

CSV_URL = "https://davidmegginson.github.io/ourairports-data/airports.csv"
BATCH_SIZE = 5_000

logger = logging.getLogger(__name__)

# (ident, type, name, lon, lat, elevation_ft, iso_country, iso_region,
#  municipality, scheduled_service, icao_code, iata_code, local_code,
#  keywords, fetched_at)
# lon/lat are passed separately for use in ST_MakePoint($lon, $lat).
Row = tuple[
    str,
    str,
    str,
    float,
    float,
    int | None,
    str,
    str,
    str | None,
    bool,
    str | None,
    str | None,
    str | None,
    str | None,
    datetime,
]


def _parse_elevation(raw: str) -> int | None:
    try:
        return int(raw) if raw else None
    except ValueError:
        return None


async def _fetch_csv() -> bytes:
    async with httpx.AsyncClient(timeout=60, follow_redirects=True) as client:
        resp = await client.get(CSV_URL)
        resp.raise_for_status()
        return resp.content


def _parse_rows(data: bytes) -> list[Row]:
    now = datetime.now(UTC)
    rows = []
    reader = csv.DictReader(io.TextIOWrapper(io.BytesIO(data), encoding="utf-8", errors="replace"))
    for row in reader:
        ident = row["ident"].strip()
        if not ident:
            continue
        try:
            lat = float(row["latitude_deg"])
            lon = float(row["longitude_deg"])
        except ValueError, KeyError:
            continue
        rows.append(
            (
                ident,
                row["type"].strip(),
                row["name"].strip(),
                lon,
                lat,
                _parse_elevation(row["elevation_ft"].strip()),
                row["iso_country"].strip(),
                row["iso_region"].strip(),
                row["municipality"].strip() or None,
                row["scheduled_service"].strip() == "yes",
                row["icao_code"].strip() or None,
                row["iata_code"].strip() or None,
                row["local_code"].strip() or None,
                row["keywords"].strip() or None,
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
        INSERT INTO airports
            (ident, type, name, location, elevation_ft, iso_country, iso_region,
             municipality, scheduled_service, icao_code, iata_code, local_code,
             keywords, fetched_at)
        VALUES
            ($1, $2, $3, ST_SetSRID(ST_MakePoint($4, $5), 4326), $6, $7, $8,
             $9, $10, $11, $12, $13, $14, $15)
        ON CONFLICT (ident) DO UPDATE SET
            type              = EXCLUDED.type,
            name              = EXCLUDED.name,
            location          = EXCLUDED.location,
            elevation_ft      = EXCLUDED.elevation_ft,
            iso_country       = EXCLUDED.iso_country,
            iso_region        = EXCLUDED.iso_region,
            municipality      = EXCLUDED.municipality,
            scheduled_service = EXCLUDED.scheduled_service,
            icao_code         = EXCLUDED.icao_code,
            iata_code         = EXCLUDED.iata_code,
            local_code        = EXCLUDED.local_code,
            keywords          = EXCLUDED.keywords,
            fetched_at        = EXCLUDED.fetched_at
        """,
        batch,
    )


@sentry_sdk.monitor(
    monitor_slug="import-airports",
    monitor_config={
        "schedule": {"type": "crontab", "value": "10 3 * * 0"},
        "timezone": "UTC",
        "checkin_margin": 60,
        "max_runtime": 30,
    },
)
async def _main() -> None:
    settings = get_settings()
    print(f"Fetching {CSV_URL} ...", file=sys.stderr)
    data = await _fetch_csv()
    print(f"Downloaded {len(data):,} bytes. Parsing...", file=sys.stderr)

    rows = _parse_rows(data)
    print(f"Parsed {len(rows):,} airport records. Upserting...", file=sys.stderr)

    conn: asyncpg.Connection[asyncpg.Record] = await asyncpg.connect(settings.asyncpg_dsn)
    try:
        for i in range(0, len(rows), BATCH_SIZE):
            await _upsert_batch(conn, rows[i : i + BATCH_SIZE])
            print(f"  {min(i + BATCH_SIZE, len(rows)):,} / {len(rows):,}", file=sys.stderr)

        count: int = await conn.fetchval("SELECT COUNT(*) FROM airports")
        print(f"Done. {count:,} rows in airports table.", file=sys.stderr)
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
        asyncio.run(_main())  # type: ignore[arg-type]  # sentry decorator loses Coroutine type
    except Exception:
        sys.exit(1)


if __name__ == "__main__":
    main()
