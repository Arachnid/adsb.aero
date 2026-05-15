"""Backfill icao_type_stats from all succeeded ingest batches.

Iterates every date in ingest_batches where status='succeeded' and runs the
same aggregation query that run_batch executes after each live ingestion.
Each date only touches its own monthly flights partition (partition pruning),
so the total work is proportional to the number of flights, not a full scan.

Usage:
    python -m adsb_server.reference_data.icao_type_stats
"""

from __future__ import annotations

import asyncio
import logging
import sys
from typing import TYPE_CHECKING

import asyncpg

if TYPE_CHECKING:
    from datetime import date

from adsb_server.config import get_settings
from adsb_server.ingestion.batch import _UPSERT_ICAO_TYPE_STATS_SQL

logger = logging.getLogger(__name__)


async def _main() -> int:
    settings = get_settings()
    conn: asyncpg.Connection[asyncpg.Record] = await asyncpg.connect(settings.asyncpg_dsn)
    try:
        rows = await conn.fetch(
            "SELECT batch_date FROM ingest_batches WHERE status = 'succeeded' ORDER BY batch_date"
        )
        dates: list[date] = [r["batch_date"] for r in rows]
        print(f"Backfilling {len(dates)} batch dates…", file=sys.stderr)

        for i, batch_date in enumerate(dates, 1):
            await conn.execute(_UPSERT_ICAO_TYPE_STATS_SQL, batch_date)
            print(f"  [{i}/{len(dates)}] {batch_date}", file=sys.stderr)

        total: int = await conn.fetchval("SELECT COUNT(*) FROM icao_type_stats")
        print(f"Done. {total:,} rows in icao_type_stats.", file=sys.stderr)
        return 0
    except Exception:
        logger.exception("Backfill failed")
        return 1
    finally:
        await conn.close()


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=sys.stderr,
    )
    sys.exit(asyncio.run(_main()))


if __name__ == "__main__":
    main()
