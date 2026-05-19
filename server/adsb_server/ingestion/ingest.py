"""Entry point for ADS-B batch ingestion.

Normal discovery mode (polls adsb.lol for new releases):
    python -m adsb_server.ingestion.ingest

Reimport specific dates:
    python -m adsb_server.ingestion.ingest --dates 2026-04-28 2026-04-29

Reimport a date range (--to defaults to today):
    python -m adsb_server.ingestion.ingest --from 2026-01-01 --to 2026-01-31
    python -m adsb_server.ingestion.ingest --from 2026-01-01
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from datetime import date, timedelta

import asyncpg
import sentry_sdk

from adsb_server.config import get_settings
from adsb_server.ingestion.scheduler import check_and_run_new_batches, reimport_specific_dates


def _date_range(start: date, end: date) -> list[date]:
    dates: list[date] = []
    d = start
    while d <= end:
        dates.append(d)
        d += timedelta(days=1)
    return dates


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run ADS-B batch ingestion")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--dates",
        metavar="YYYY-MM-DD",
        nargs="+",
        type=date.fromisoformat,
        help="Reimport specific dates.",
    )
    mode.add_argument(
        "--from",
        dest="from_date",
        metavar="YYYY-MM-DD",
        type=date.fromisoformat,
        help="Start of date range to reimport (inclusive).",
    )
    parser.add_argument(
        "--to",
        dest="to_date",
        metavar="YYYY-MM-DD",
        type=date.fromisoformat,
        default=None,
        help="End of date range (inclusive; defaults to today when --from is used).",
    )
    args = parser.parse_args(argv)
    if args.to_date is not None and args.from_date is None:
        parser.error("--to requires --from")
    return args


async def _discover() -> None:
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
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=sys.stderr,
    )
    settings = get_settings()
    settings.init_sentry()

    args = _parse_args()

    if args.dates:
        dates = sorted(set(args.dates))
        with sentry_sdk.start_transaction(op="task", name="reimport-dates"):
            asyncio.run(_reimport(dates))
    elif args.from_date is not None:
        to_date = args.to_date if args.to_date is not None else date.today()
        if args.from_date > to_date:
            sys.exit(f"--from {args.from_date} is after --to {to_date}")
        dates = _date_range(args.from_date, to_date)
        with sentry_sdk.start_transaction(op="task", name="reimport-dates"):
            asyncio.run(_reimport(dates))
    else:
        with sentry_sdk.start_transaction(op="task", name="import-traces"):
            asyncio.run(_discover())


if __name__ == "__main__":
    main()
