"""Entry point for the scheduler process.

Run with:
    python -m adsb_server.ingestion.scheduler_main

To reimport specific dates:
    python -m adsb_server.ingestion.scheduler_main --dates 2026-04-28 2026-04-29
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from datetime import date

import asyncpg
import sentry_sdk

from adsb_server.config import get_settings
from adsb_server.ingestion.scheduler import check_and_run_new_batches, reimport_specific_dates


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


async def _reimport(dates: list[date]) -> None:
    settings = get_settings()
    conn: asyncpg.Connection[asyncpg.Record] = await asyncpg.connect(settings.asyncpg_dsn)
    try:
        await reimport_specific_dates(
            conn,
            dates,
            settings.scheduler_cache_dir,
            keep_traces=settings.scheduler_keep_traces,
        )
    finally:
        await conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Run ingestion scheduler")
    parser.add_argument(
        "--dates",
        metavar="YYYY-MM-DD",
        nargs="+",
        help="Reimport specific dates instead of running normal discovery.",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=sys.stderr,
    )
    settings = get_settings()
    settings.init_sentry()

    if args.dates:
        dates = [date.fromisoformat(d) for d in args.dates]
        with sentry_sdk.start_transaction(op="task", name="reimport-dates"):
            asyncio.run(_reimport(dates))
    else:
        with sentry_sdk.start_transaction(op="task", name="import-traces"):
            asyncio.run(_main())


if __name__ == "__main__":
    main()
