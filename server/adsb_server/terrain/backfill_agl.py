"""Backfill path_agl_ft for flights ingested before AGL computation was added.

Reads each flight's simplified path and QNH correction series from the database,
runs the same AGL pipeline as batch ingestion, and writes the result back.

Streams all NULL-AGL flights in reverse chronological order via a single
PostgreSQL server-side cursor (no keyset pagination).  A dedicated read
connection holds the cursor open inside a read transaction; a separate write
connection commits each batch independently so a crash loses at most one batch.

Each row is submitted to a thread pool as it arrives; when batch_size futures
have accumulated they are awaited together and committed.

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
    from datetime import datetime

from adsb_server.config import get_settings
from adsb_server.geometry.wkt import tfloat_stepwise_seqset
from adsb_server.terrain.agl import compute_agl_series
from adsb_server.terrain.tiles import TileManager

logger = logging.getLogger(__name__)

_DEFAULT_BATCH_SIZE = 500
_DEFAULT_WORKERS = 8

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
WHERE f.path_agl_ft IS NULL
ORDER BY f.start_ts DESC, f.icao24 DESC
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


async def _flush(
    conn: asyncpg.Connection,
    pending: list[tuple[asyncpg.Record, asyncio.Future[str | None]]],
) -> int:
    """Await pending AGL futures, write results to the DB, return updated flight count."""
    raw: list[str | None | BaseException] = list(
        await asyncio.gather(*[f for _, f in pending], return_exceptions=True)
    )
    updates: list[tuple[str, datetime, str]] = []
    for (row, _), result in zip(pending, raw, strict=True):
        if isinstance(result, BaseException):
            logger.warning(
                "AGL computation raised for %s %s: %s",
                row["icao24"],
                row["start_ts"],
                result,
            )
        elif result is not None:
            updates.append((row["icao24"], row["start_ts"], result))
    if updates:
        await conn.executemany(_UPDATE_SQL, updates)
    return len(updates)


async def run_backfill(
    dsn: str,
    data_dir: Path,
    batch_size: int = _DEFAULT_BATCH_SIZE,
    workers: int = _DEFAULT_WORKERS,
) -> None:
    """Connect to the DB and backfill all flights with missing AGL data."""
    tile_manager = TileManager(data_dir)
    # Two connections: read_conn holds the server-side cursor in a read transaction;
    # write_conn commits each batch independently so crashes lose at most one batch.
    read_conn: asyncpg.Connection = await asyncpg.connect(dsn)
    write_conn: asyncpg.Connection = await asyncpg.connect(dsn)
    loop = asyncio.get_running_loop()

    with ThreadPoolExecutor(max_workers=workers) as executor:
        try:
            total = 0
            pending: list[tuple[asyncpg.Record, asyncio.Future[str | None]]] = []

            async with read_conn.transaction():
                async for row in read_conn.cursor(_FETCH_SQL, prefetch=batch_size):
                    fut: asyncio.Future[str | None] = loop.run_in_executor(
                        executor,
                        _compute_agl_row,
                        row["path_points"],
                        row["correction_pairs"],
                        tile_manager,
                    )
                    pending.append((row, fut))

                    if len(pending) >= batch_size:
                        n = await _flush(write_conn, pending)
                        total += n
                        logger.info(
                            "back to %s | batch=%d | updated=%d | total=%d",
                            pending[-1][0]["start_ts"].date(),
                            len(pending),
                            n,
                            total,
                        )
                        pending = []

            if pending:
                n = await _flush(write_conn, pending)
                total += n
                logger.info(
                    "back to %s | batch=%d | updated=%d | total=%d",
                    pending[-1][0]["start_ts"].date(),
                    len(pending),
                    n,
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
        description="Backfill path_agl_ft for flights missing AGL data"
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=_DEFAULT_BATCH_SIZE,
        metavar="N",
        help=f"Flights per thread-pool flush and DB commit (default: {_DEFAULT_BATCH_SIZE})",
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
