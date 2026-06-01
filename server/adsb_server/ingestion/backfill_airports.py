"""Backfill start_airport_ident and end_airport_ident for existing flights.

Loads the full airports table into an in-memory KD-tree index, then streams
all flights with NULL airport columns via a server-side cursor, resolves the
nearest airport within 5 km for each start/end point, and writes results back
in batches.

Two connections are used: a read connection holds the cursor inside a read
transaction; a write connection commits each batch independently so a crash
loses at most one batch.

Usage:
    backfill-airports
    backfill-airports --batch-size 2000
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys

import asyncpg

from adsb_server.config import get_settings
from adsb_server.ingestion.airport_index import AGL_MATCH_MAX_FT, AirportIndex

logger = logging.getLogger(__name__)

_DEFAULT_BATCH_SIZE = 2_000

_FETCH_SQL = """
SELECT
    icao24,
    start_ts,
    emitter_category,
    ST_X(startValue(path)::geometry)  AS start_lon,
    ST_Y(startValue(path)::geometry)  AS start_lat,
    ST_X(endValue(path)::geometry)    AS end_lon,
    ST_Y(endValue(path)::geometry)    AS end_lat,
    startValue(path_agl_ft)           AS start_agl_ft,
    endValue(path_agl_ft)             AS end_agl_ft
FROM flights
ORDER BY start_ts DESC, icao24 DESC
"""

_UPDATE_SQL = """
UPDATE flights
SET start_airport_ident = $3, end_airport_ident = $4
WHERE icao24 = $1 AND start_ts = $2
"""


async def _load_airport_index(conn: asyncpg.Connection) -> AirportIndex:
    rows = await conn.fetch(
        "SELECT ident, ST_X(location) AS lon, ST_Y(location) AS lat, type"
        " FROM airports WHERE type NOT IN ('closed', 'balloonport')"
    )
    logger.info("Loaded %d airports into index", len(rows))
    return AirportIndex.from_rows([(r["ident"], r["lon"], r["lat"], r["type"]) for r in rows])


async def run_backfill(dsn: str, batch_size: int = _DEFAULT_BATCH_SIZE) -> None:
    read_conn: asyncpg.Connection = await asyncpg.connect(dsn)
    write_conn: asyncpg.Connection = await asyncpg.connect(dsn)
    try:
        index = await _load_airport_index(read_conn)

        total = 0
        pending: list[tuple[str, object, str | None, str | None]] = []

        async with read_conn.transaction():
            async for row in read_conn.cursor(_FETCH_SQL, prefetch=batch_size):
                start_agl: float | None = row["start_agl_ft"]
                end_agl: float | None = row["end_agl_ft"]
                start = (
                    index.nearest(row["start_lon"], row["start_lat"], row["emitter_category"])
                    if start_agl is None or start_agl <= AGL_MATCH_MAX_FT
                    else None
                )
                end = (
                    index.nearest(row["end_lon"], row["end_lat"], row["emitter_category"])
                    if end_agl is None or end_agl <= AGL_MATCH_MAX_FT
                    else None
                )
                pending.append((row["icao24"], row["start_ts"], start, end))

                if len(pending) >= batch_size:
                    await write_conn.executemany(_UPDATE_SQL, pending)
                    total += len(pending)
                    logger.info(
                        "back to %s | batch=%d | total=%d",
                        pending[-1][1],
                        len(pending),
                        total,
                    )
                    pending = []

        if pending:
            await write_conn.executemany(_UPDATE_SQL, pending)
            total += len(pending)
            logger.info(
                "back to %s | batch=%d | total=%d",
                pending[-1][1],
                len(pending),
                total,
            )

        logger.info("Backfill complete: %d flights updated", total)
    finally:
        await read_conn.close()
        await write_conn.close()


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=sys.stderr,
    )
    settings = get_settings()
    parser = argparse.ArgumentParser(
        description="Backfill start/end airport idents for existing flights"
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=_DEFAULT_BATCH_SIZE,
        metavar="N",
        help=f"Flights per DB commit (default: {_DEFAULT_BATCH_SIZE})",
    )
    args = parser.parse_args()
    asyncio.run(run_backfill(settings.asyncpg_dsn, batch_size=args.batch_size))


if __name__ == "__main__":
    main()
