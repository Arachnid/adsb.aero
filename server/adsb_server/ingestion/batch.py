"""Batch ingestion: process a single day's tarball and write to the database."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import pickle
import time as _time
import zlib
from concurrent.futures import ProcessPoolExecutor
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path  # noqa: TC003
from typing import Any

import asyncpg  # noqa: TC002

from adsb_server.geometry.simplify import simplify_flight
from adsb_server.geometry.wkt import tgeompoint_seq, tint_seq
from adsb_server.ingestion.models import FinalizedFlight, RawFlight, RawPoint, TraceHeader
from adsb_server.ingestion.parser import count_traces, stream_tarball
from adsb_server.ingestion.splitter import (
    build_squawk_runs,
    interpolate_missing_values,
    split_flights,
)

logger = logging.getLogger(__name__)

# Traces dispatched to the process pool per asyncio gather cycle.
_CHUNK_SIZE = 256

_UPSERT_FLIGHT_SQL = """
INSERT INTO flights (icao24, callsign, icao_type, emitter_category,
    start_ts, end_ts, path, path_tracks,
    squawk_runs, raw_point_count, ingest_batch_date)
VALUES ($1,$2,$3,$4,$5,$6,
    $7::tgeompoint, $8::tint,
    $9::jsonb, $10, $11)
ON CONFLICT (icao24, start_ts) DO UPDATE SET
    callsign=EXCLUDED.callsign, icao_type=EXCLUDED.icao_type,
    emitter_category=EXCLUDED.emitter_category,
    end_ts=EXCLUDED.end_ts,
    path=EXCLUDED.path, path_tracks=EXCLUDED.path_tracks,
    squawk_runs=EXCLUDED.squawk_runs, raw_point_count=EXCLUDED.raw_point_count,
    ingest_batch_date=EXCLUDED.ingest_batch_date
"""

_FlightParams = tuple[
    str, str | None, str | None, str | None,
    datetime, datetime,
    str, str,
    str, int, date,
]


def _serialize_staging(flights: dict[str, RawFlight]) -> bytes:
    """Pickle and zlib-compress a mapping of icao24 → RawFlight."""
    return zlib.compress(pickle.dumps(flights), level=6)


def _deserialize_staging(blob: bytes) -> dict[str, RawFlight]:
    """Decompress and unpickle a staging blob back into a mapping of icao24 → RawFlight."""
    result: dict[str, RawFlight] = pickle.loads(zlib.decompress(blob))
    return result


def _flight_to_params(
    flight: FinalizedFlight,
    batch_date: date,
) -> _FlightParams:
    """Convert a FinalizedFlight into the parameter tuple for the UPSERT SQL."""
    timestamps = [v[3] for v in flight.vertices]
    return (
        flight.icao24,
        flight.callsign,
        flight.icao_type,
        flight.emitter_category,
        flight.start_ts,
        flight.end_ts,
        tgeompoint_seq(flight.vertices),
        tint_seq(flight.path_tracks, timestamps),
        json.dumps(flight.squawk_runs),
        flight.raw_point_count,
        batch_date,
    )


def _in_progress_flight_to_params(
    flight: RawFlight,
    batch_date: date,
) -> _FlightParams | None:
    """
    Build DB params for an in-progress flight using a simplified path.

    Applies interpolation and RDP simplification to the airborne subset so the
    display path stored in flights is always clean.  Raw points are preserved
    separately in the staging blob for idempotent reconstruction next day.
    Returns None if fewer than 2 airborne points (cannot form valid geometry).
    """
    airborne = [p for p in flight.points if p.alt_baro is not None]
    if len(airborne) < 2:
        return None

    interp = interpolate_missing_values(airborne)
    kept = simplify_flight(interp)
    if len(kept) < 2:
        kept = [0, len(interp) - 1]

    vertices: list[tuple[float, float, float, float]] = []
    path_tracks: list[int] = []
    for i in kept:
        p = interp[i]
        vertices.append((p.lon, p.lat, p.alt_baro or 0.0, p.ts))
        path_tracks.append(round(p.track) % 360 if p.track is not None else 0)

    start_ts = datetime.fromtimestamp(vertices[0][3], tz=UTC)
    end_ts = datetime.fromtimestamp(vertices[-1][3], tz=UTC)
    timestamps = [v[3] for v in vertices]

    return (
        flight.icao24,
        flight.callsign,
        flight.icao_type,
        flight.emitter_category,
        start_ts,
        end_ts,
        tgeompoint_seq(vertices),
        tint_seq(path_tracks, timestamps),
        json.dumps(build_squawk_runs([interp[i] for i in kept])),
        len(flight.points),
        batch_date,
    )


def _process_trace(
    header: TraceHeader,
    all_points: list[RawPoint],
    cutoff_ts: float,
) -> tuple[list[FinalizedFlight], RawFlight | None]:
    """CPU-bound per-trace work executed in a worker process."""
    return split_flights(header, all_points, cutoff_ts)


async def run_batch(
    conn: asyncpg.Connection,
    tarball_path: Path,
    batch_date: date,
    bbox: tuple[float, float, float, float] | None = None,
    workers: int | None = None,
) -> int:
    """
    Process a single day's tarball and write flights to the database.

    Staging design for idempotent re-processing
    --------------------------------------------
    At the start, raw in-progress points from the previous day are loaded from
    flight_staging.  At the end, the current day's in-progress points are written
    there.  This lets any day be re-processed without creating duplicate flights:
    the upsert key (icao24, start_ts) stays stable because we reconstruct the
    exact same raw point sequence from the blob.

    Stale flight deletion
    ---------------------
    Flights with ingest_batch_date == batch_date that existed before this run but
    were not touched during it are deleted at the end.  This handles the case where
    re-processing a day produces a different set of flights than the original run.
    """
    await conn.execute(
        """
        INSERT INTO ingest_batches (batch_date, status, started_at, attempts, last_attempt_at)
        VALUES ($1, 'running', NOW(), 1, NOW())
        ON CONFLICT (batch_date) DO UPDATE SET
            status = 'running',
            started_at = COALESCE(ingest_batches.started_at, NOW()),
            attempts = ingest_batches.attempts + 1,
            last_attempt_at = NOW()
        """,
        batch_date,
    )

    # Load in-progress flights from the previous day's staging blob.
    prev_date = batch_date - timedelta(days=1)
    staging_row = await conn.fetchrow(
        "SELECT staging_data FROM flight_staging WHERE batch_date = $1",
        prev_date,
    )
    staging: dict[str, RawFlight] = {}
    if staging_row is not None:
        staging = _deserialize_staging(bytes(staging_row["staging_data"]))
        logger.info(
            "Loaded %d in-progress flights from staging (batch_date=%s)",
            len(staging), prev_date,
        )

    # Record flights already attributed to this batch_date so we can delete
    # any that are not touched (re-run idempotency).
    existing_key_rows = await conn.fetch(
        "SELECT icao24, start_ts FROM flights WHERE ingest_batch_date = $1",
        batch_date,
    )
    existing_keys: set[tuple[str, datetime]] = {
        (r["icao24"], r["start_ts"]) for r in existing_key_rows
    }
    upserted_keys: set[tuple[str, datetime]] = set()

    cutoff_dt = datetime.combine(batch_date, time.max, tzinfo=UTC)
    cutoff_ts = cutoff_dt.timestamp()

    n_workers = workers if workers is not None and workers > 0 else (os.cpu_count() or 1)
    loop = asyncio.get_running_loop()

    total_traces = count_traces(tarball_path)
    if total_traces:
        logger.info("Found %d trace files; using %d workers", total_traces, n_workers)
    else:
        logger.info("Trace count unknown (split archive); using %d workers", n_workers)

    flight_count = 0
    traces_done = 0
    t_start = _time.monotonic()
    pending: list[tuple[TraceHeader, list[RawPoint]]] = []
    in_progress_flights: dict[str, RawFlight] = {}

    with ProcessPoolExecutor(max_workers=n_workers) as pool:

        async def _flush() -> None:
            nonlocal flight_count, traces_done
            if not pending:
                return

            futures = [
                loop.run_in_executor(pool, _process_trace, h, pts, cutoff_ts)
                for h, pts in pending
            ]
            results: list[Any] = list(
                await asyncio.gather(*futures, return_exceptions=True)
            )

            params_batch: list[_FlightParams] = []
            for result, (header, _) in zip(results, pending, strict=True):
                if isinstance(result, BaseException):
                    logger.error(
                        "Failed to process trace %s: %s", header.icao24, result
                    )
                    continue
                finalized: list[FinalizedFlight]
                in_progress: RawFlight | None
                finalized, in_progress = result
                for flight in finalized:
                    params_batch.append(_flight_to_params(flight, batch_date))
                if in_progress is not None:
                    in_progress_flights[in_progress.icao24] = in_progress
                    raw_params = _in_progress_flight_to_params(in_progress, batch_date)
                    if raw_params is not None:
                        params_batch.append(raw_params)

            if params_batch:
                try:
                    await conn.executemany(_UPSERT_FLIGHT_SQL, params_batch)
                    for p in params_batch:
                        upserted_keys.add((p[0], p[4]))  # (icao24, start_ts)
                    flight_count += len(params_batch)
                except Exception:
                    logger.exception(
                        "Failed to write batch of %d flights", len(params_batch)
                    )

            traces_done += len(pending)
            elapsed = _time.monotonic() - t_start
            rate = traces_done / (elapsed / 60.0) if elapsed > 0 else 0.0
            if total_traces:
                pct = 100.0 * traces_done / total_traces
                logger.info(
                    "%d/%d traces (%.0f%%) | %.0f traces/min | %d flights",
                    traces_done, total_traces, pct, rate, flight_count,
                )
            else:
                logger.info(
                    "%d traces | %.0f traces/min | %d flights",
                    traces_done, rate, flight_count,
                )

            pending.clear()

        for trace_header, new_points in stream_tarball(tarball_path):
            icao24 = trace_header.icao24

            if bbox is not None:
                min_lon, min_lat, max_lon, max_lat = bbox
                new_points = [
                    p
                    for p in new_points
                    if min_lon <= p.lon <= max_lon and min_lat <= p.lat <= max_lat
                ]
                if not new_points:
                    continue

            staging_entry = staging.pop(icao24, None)
            base = staging_entry.points if staging_entry is not None else []
            merged = base + new_points
            merged.sort(key=lambda p: p.ts)
            deduped: list[RawPoint] = []
            last_ts: float | None = None
            for p in merged:
                if p.ts != last_ts:
                    deduped.append(p)
                    last_ts = p.ts
            all_points = deduped

            if not all_points:
                continue

            pending.append((trace_header, all_points))
            if len(pending) >= _CHUNK_SIZE:
                await _flush()

        await _flush()

        # Finalize staging entries not seen in this tarball (orphans).
        # Their last point is older than the gap threshold relative to this
        # batch's cutoff, so split_flights will always finalize them.
        for orphan_icao24, orphan_flight in staging.items():
            orphan_pts = sorted(orphan_flight.points, key=lambda p: p.ts)
            header = TraceHeader(icao24=orphan_icao24, icao_type=orphan_flight.icao_type)
            pending.append((header, orphan_pts))
            if len(pending) >= _CHUNK_SIZE:
                await _flush()
        await _flush()

    # Write current in-progress flights to the staging table.
    if in_progress_flights:
        blob = _serialize_staging(in_progress_flights)
        await conn.execute(
            """
            INSERT INTO flight_staging (batch_date, staging_data)
            VALUES ($1, $2)
            ON CONFLICT (batch_date) DO UPDATE SET staging_data = EXCLUDED.staging_data
            """,
            batch_date,
            blob,
        )
        logger.info(
            "Wrote %d in-progress flights to staging for batch_date=%s",
            len(in_progress_flights), batch_date,
        )

    # Delete flights that existed before this run but were not written by it.
    stale = existing_keys - upserted_keys
    if stale:
        await conn.execute(
            """
            DELETE FROM flights f
            USING (
                SELECT unnest($1::text[]) AS icao24,
                       unnest($2::timestamptz[]) AS start_ts
            ) x
            WHERE f.icao24 = x.icao24 AND f.start_ts = x.start_ts
              AND f.ingest_batch_date = $3
            """,
            [k[0] for k in stale],
            [k[1] for k in stale],
            batch_date,
        )
        logger.info("Deleted %d stale flights for batch_date=%s", len(stale), batch_date)

    await conn.execute(
        """
        UPDATE ingest_batches
        SET status='succeeded', finished_at=NOW(), flight_count=$2
        WHERE batch_date=$1
        """,
        batch_date,
        flight_count,
    )

    logger.info("Batch %s complete: %d flights finalized", batch_date, flight_count)
    return flight_count
