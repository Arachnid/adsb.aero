"""
Command-line interface for running a single ADS-B ingestion batch.

Usage:
    python -m adsb_server.ingestion.cli <tarball_path> \
        [--batch-date YYYY-MM-DD] \
        [--workers N]

Arguments:
    tarball_path: path to a .tar.gz file or directory containing .tar.XX parts

Options:
    --batch-date: defaults to today
    --workers: worker processes for CPU-bound trace processing (default: os.cpu_count())
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from datetime import date
from pathlib import Path

import asyncpg

from adsb_server.config import get_settings
from adsb_server.ingestion.batch import run_batch

logger = logging.getLogger(__name__)


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m adsb_server.ingestion.cli",
        description="Run a single ADS-B ingestion batch.",
    )
    parser.add_argument(
        "tarball_path",
        type=Path,
        help="Path to a .tar.gz file or directory containing .tar.XX parts",
    )
    parser.add_argument(
        "--batch-date",
        type=date.fromisoformat,
        default=date.today(),
        metavar="YYYY-MM-DD",
        help="Batch date (default: today)",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=None,
        metavar="N",
        help="Worker processes for CPU-bound trace processing (default: os.cpu_count())",
    )
    return parser.parse_args(argv)


async def _main(args: argparse.Namespace) -> int:
    settings = get_settings()
    print(
        f"Connecting to {settings.postgres_host}:{settings.postgres_port}/{settings.postgres_db}",
        file=sys.stderr,
    )

    conn: asyncpg.Connection[asyncpg.Record] = await asyncpg.connect(settings.asyncpg_dsn)
    try:
        print(f"Processing batch for {args.batch_date} from {args.tarball_path}", file=sys.stderr)

        count = await run_batch(
            conn=conn,
            tarball_path=args.tarball_path,
            batch_date=args.batch_date,
            workers=args.workers,
        )
        print(f"Done: {count} flights finalized.", file=sys.stderr)
        return 0
    except Exception:
        logger.exception("Batch failed")
        return 1
    finally:
        await conn.close()


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=sys.stderr,
    )
    args = _parse_args()
    sys.exit(asyncio.run(_main(args)))


if __name__ == "__main__":
    main()
