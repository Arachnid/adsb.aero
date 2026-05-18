"""Entry point for the scheduler process.

Run with:
    python -m adsb_server.ingestion.scheduler_main
"""

from __future__ import annotations

import asyncio
import logging
import sys

import asyncpg

from adsb_server.config import get_settings
from adsb_server.ingestion.scheduler import check_and_run_new_batches


async def _main() -> None:
    settings = get_settings()
    conn: asyncpg.Connection[asyncpg.Record] = await asyncpg.connect(settings.asyncpg_dsn)
    try:
        await check_and_run_new_batches(
            conn,
            settings.scheduler_cache_dir,
            lookback_days=settings.scheduler_lookback_days,
            keep_traces=settings.scheduler_keep_traces,
        )
    finally:
        await conn.close()


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=sys.stderr,
    )
    asyncio.run(_main())


if __name__ == "__main__":
    main()
