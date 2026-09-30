"""Backfill path_length_m for flights ingested before the column existed.

Walks the archive one day of start_ts at a time, newest first, and fills the
column in SQL with the same expression ingest uses.  Each day commits on its
own, and only rows still NULL are touched, so an interrupted run resumes where
it stopped and a re-run over a filled archive does nothing.

Usage:
    backfill-path-length
"""

from __future__ import annotations

import asyncio
import logging
import sys
from datetime import timedelta

import asyncpg

from adsb_server.config import get_settings
from adsb_server.geometry.stitch import stitched_length_m_sql

logger = logging.getLogger(__name__)

_BOUNDS_SQL = """
SELECT min(start_ts)::date AS first_day, max(start_ts)::date AS last_day
FROM flights
WHERE path_length_m IS NULL
"""

# One day is a small slice of one weekly partition, so each UPDATE prunes to a
# single partition and holds its row locks only briefly.
_UPDATE_SQL = f"""
UPDATE flights
SET path_length_m = {stitched_length_m_sql("path")}
WHERE start_ts >= $1::date::timestamptz
  AND start_ts <  ($1::date + 1)::timestamptz
  AND path_length_m IS NULL
"""


async def run_backfill(dsn: str) -> int:
    """Fill path_length_m wherever it is NULL.  Returns the number of flights updated."""
    conn: asyncpg.Connection = await asyncpg.connect(dsn)
    try:
        bounds = await conn.fetchrow(_BOUNDS_SQL)
        assert bounds is not None  # an aggregate always returns one row
        if bounds["first_day"] is None:
            logger.info("Backfill complete: nothing to do")
            return 0

        total = 0
        day = bounds["last_day"]
        while day >= bounds["first_day"]:
            status: str = await conn.execute(_UPDATE_SQL, day)
            updated = int(status.split()[-1])
            total += updated
            if updated:
                logger.info("%s | updated=%d | total=%d", day, updated, total)
            day -= timedelta(days=1)

        logger.info("Backfill complete: %d flights updated", total)
        return total
    finally:
        await conn.close()


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=sys.stderr,
    )
    asyncio.run(run_backfill(get_settings().asyncpg_dsn))


if __name__ == "__main__":
    main()
