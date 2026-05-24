"""Backfill path_agl_ft for flights ingested before AGL computation was added.

Reads each flight's simplified path and QNH correction series from the database,
runs the same AGL pipeline as batch ingestion, and writes the result back.
Processes one ingest_batch_date at a time so progress is stable.

AGL computation per flight is CPU+I/O bound (numpy densification + np.load tile reads).
A ThreadPoolExecutor runs all flights in a batch concurrently; numpy and file I/O
both release the GIL so threads genuinely overlap.

Usage:
    backfill-agl
    backfill-agl --batch-size 500 --workers 8 --data-dir /data/terrain
"""

from __future__ import annotations

import argparse
import asyncio
import itertools
import logging
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import TYPE_CHECKING

import asyncpg

if TYPE_CHECKING:
    from datetime import date, datetime

from adsb_server.config import get_settings
from adsb_server.geometry.wkt import tfloat_stepwise_seqset
from adsb_server.terrain.agl import compute_agl_series
from adsb_server.terrain.tiles import TileManager

logger = logging.getLogger(__name__)

_DEFAULT_BATCH_SIZE = 500
_DEFAULT_WORKERS = 8

# Fetch one batch of flights with missing AGL for a given ingest_batch_date.
# path_points: 2D float8 array, each row = [seq_n, lon, lat, alt_ft, ts_epoch]
# correction_pairs: 2D float8 array, each row = [ts_epoch, correction_ft], or NULL
# $3/$4: keyset cursor (cursor_ts, cursor_icao) — NULL on first page to fetch from the start.
_FETCH_SQL = """
SELECT
    f.icao24,
    f.start_ts,
    (
        SELECT ARRAY_AGG(
            ARRAY[
                ordinality::float8,
                ST_X(getValue(inst)::geometry)::float8,
                ST_Y(getValue(inst)::geometry)::float8,
                ST_Z(getValue(inst)::geometry)::float8,
                EXTRACT(EPOCH FROM getTimestamp(inst))::float8
            ]
            ORDER BY ordinality, getTimestamp(inst)
        )
        FROM unnest(sequences(f.path)) WITH ORDINALITY AS t(seq, ordinality),
             LATERAL unnest(instants(seq)) AS inst
    ) AS path_points,
    (
        SELECT ARRAY_AGG(
            ARRAY[
                EXTRACT(EPOCH FROM getTimestamp(inst))::float8,
                getValue(inst)::float8
            ]
            ORDER BY getTimestamp(inst)
        )
        FROM unnest(instants(f.alt_correction_ft)) AS inst
    ) AS correction_pairs
FROM flights f
WHERE f.ingest_batch_date = $1
  AND f.path_agl_ft IS NULL
  AND ($3::timestamptz IS NULL OR (f.start_ts, f.icao24) > ($3, $4))
ORDER BY f.start_ts, f.icao24
LIMIT $2
"""

_UPDATE_SQL = """
UPDATE flights
SET path_agl_ft = $3::tfloat
WHERE icao24 = $1 AND start_ts = $2
"""


def _reconstruct_vertex_sequences(
    path_points: list[list[float]],
) -> list[list[tuple[float, float, float, float]]]:
    """Group flat path_points rows (seq_n, lon, lat, alt_ft, ts) into vertex_sequences."""
    vertex_sequences: list[list[tuple[float, float, float, float]]] = []
    for _seq_n, group in itertools.groupby(path_points, key=lambda p: p[0]):
        seq: list[tuple[float, float, float, float]] = [(p[1], p[2], p[3], p[4]) for p in group]
        vertex_sequences.append(seq)
    return vertex_sequences


def _compute_agl_row(
    path_points: list[list[float]] | None,
    correction_pairs: list[list[float]] | None,
    tile_manager: TileManager,
) -> str | None:
    """Compute AGL for one flight and return the tfloat WKT, or None on failure.

    Designed to run in a ThreadPoolExecutor — numpy and np.load both release the GIL.
    TileManager._missing races across threads are benign (worst case: extra stat() calls).
    """
    if not path_points:
        return None
    vertex_sequences = _reconstruct_vertex_sequences(path_points)
    corr_ts = [float(p[0]) for p in correction_pairs] if correction_pairs else None
    corr_vals = [float(p[1]) for p in correction_pairs] if correction_pairs else None
    agl = compute_agl_series(vertex_sequences, corr_ts, corr_vals, tile_manager)
    return tfloat_stepwise_seqset(agl) if agl is not None else None


async def backfill_date(
    conn: asyncpg.Connection,
    tile_manager: TileManager,
    batch_date: date,
    batch_size: int,
    executor: ThreadPoolExecutor,
) -> int:
    """Backfill path_agl_ft for all flights on batch_date. Returns count of updated flights."""
    loop = asyncio.get_running_loop()
    total = 0
    cursor_ts: datetime | None = None
    cursor_icao: str = ""

    while True:
        rows = await conn.fetch(_FETCH_SQL, batch_date, batch_size, cursor_ts, cursor_icao)
        if not rows:
            break

        # Dispatch all flights in the batch to the thread pool concurrently.
        # return_exceptions=True ensures one failed flight doesn't abort the batch.
        raw_results: list[str | None | BaseException] = list(
            await asyncio.gather(
                *[
                    loop.run_in_executor(
                        executor,
                        _compute_agl_row,
                        row["path_points"],
                        row["correction_pairs"],
                        tile_manager,
                    )
                    for row in rows
                ],
                return_exceptions=True,
            )
        )

        updates: list[tuple[str, datetime, str]] = []
        skipped = 0
        for row, result in zip(rows, raw_results, strict=True):
            if isinstance(result, BaseException):
                logger.warning(
                    "AGL computation raised for %s %s: %s",
                    row["icao24"],
                    row["start_ts"],
                    result,
                )
                skipped += 1
            elif not row["path_points"]:
                logger.warning(
                    "Flight %s %s has no path points; skipping", row["icao24"], row["start_ts"]
                )
                skipped += 1
            elif result is None:
                logger.warning(
                    "AGL computation produced no data for %s %s; skipping",
                    row["icao24"],
                    row["start_ts"],
                )
                skipped += 1
            else:
                updates.append((row["icao24"], row["start_ts"], result))

        if updates:
            await conn.executemany(_UPDATE_SQL, updates)
        total += len(updates)

        logger.info(
            "date=%s  batch=%d  updated=%d  skipped=%d  date_total=%d",
            batch_date,
            len(rows),
            len(updates),
            skipped,
            total,
        )

        # Advance the keyset cursor past all rows we just fetched, whether they
        # succeeded or failed.  This prevents failed (still-NULL) flights from
        # being re-fetched in subsequent iterations of the same run.
        cursor_ts = rows[-1]["start_ts"]
        cursor_icao = rows[-1]["icao24"]

        if len(rows) < batch_size:
            break

    return total


async def run_backfill(
    dsn: str,
    data_dir: Path,
    batch_size: int = _DEFAULT_BATCH_SIZE,
    workers: int = _DEFAULT_WORKERS,
) -> None:
    """Connect to DB and backfill all dates with missing AGL data."""
    tile_manager = TileManager(data_dir)
    conn: asyncpg.Connection = await asyncpg.connect(dsn)
    with ThreadPoolExecutor(max_workers=workers) as executor:
        try:
            dates = await conn.fetch(
                "SELECT DISTINCT ingest_batch_date FROM flights "
                "WHERE path_agl_ft IS NULL ORDER BY ingest_batch_date"
            )
            if not dates:
                logger.info("No flights missing AGL data.")
                return

            logger.info("Backfilling %d dates with missing AGL data", len(dates))
            grand_total = 0
            for date_row in dates:
                batch_date: date = date_row["ingest_batch_date"]
                count = await backfill_date(conn, tile_manager, batch_date, batch_size, executor)
                grand_total += count
                logger.info(
                    "date=%s  completed  updated=%d  running_total=%d",
                    batch_date,
                    count,
                    grand_total,
                )

            logger.info("Backfill complete: %d flights updated", grand_total)
        finally:
            await conn.close()


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=sys.stderr,
    )
    settings = get_settings()
    parser = argparse.ArgumentParser(
        description="Backfill path_agl_ft for flights missing AGL data"
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=_DEFAULT_BATCH_SIZE,
        metavar="N",
        help=f"Flights per DB fetch/update batch (default: {_DEFAULT_BATCH_SIZE})",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=_DEFAULT_WORKERS,
        metavar="N",
        help=f"Thread-pool size for AGL computation (default: {_DEFAULT_WORKERS})",
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=settings.terrain_data_dir,
        metavar="DIR",
        help=f"Terrain .npy tiles directory (default: {settings.terrain_data_dir})",
    )
    args = parser.parse_args()
    asyncio.run(
        run_backfill(
            settings.asyncpg_dsn,
            args.data_dir,
            batch_size=args.batch_size,
            workers=args.workers,
        )
    )


if __name__ == "__main__":
    main()
