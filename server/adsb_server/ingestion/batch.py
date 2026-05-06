"""Batch ingestion: process a single day's tarball and write to the database."""

from __future__ import annotations

import asyncio
import dataclasses
import json
import logging
import os
import time as _time
from concurrent.futures import ProcessPoolExecutor
from datetime import UTC, date, datetime, time
from pathlib import Path  # noqa: TC003
from typing import Any

import asyncpg  # noqa: TC002

from adsb_server.geometry.wkt import linestring_zm, point_zm
from adsb_server.ingestion.models import FinalizedFlight, RawFlight, RawPoint, TraceHeader
from adsb_server.ingestion.parser import count_traces, stream_tarball
from adsb_server.ingestion.splitter import split_flights

logger = logging.getLogger(__name__)

# Traces dispatched to the process pool per asyncio gather cycle.
# Large enough to keep all workers busy; small enough that the event loop
# remains responsive and memory stays bounded.
_CHUNK_SIZE = 256

_UPSERT_FLIGHT_SQL = """
INSERT INTO flights (icao24, callsign, icao_type, emitter_category,
    start_ts, end_ts, start_point, end_point, path_geom,
    path_tracks, squawk_runs, raw_point_count, ingest_batch_date)
VALUES ($1,$2,$3,$4,$5,$6,
    ST_GeomFromText($7,4326), ST_GeomFromText($8,4326), ST_GeomFromText($9,4326),
    $10, $11::jsonb, $12, $13)
ON CONFLICT (icao24, start_ts) DO UPDATE SET
    callsign=EXCLUDED.callsign, icao_type=EXCLUDED.icao_type,
    emitter_category=EXCLUDED.emitter_category,
    end_ts=EXCLUDED.end_ts, end_point=EXCLUDED.end_point,
    path_geom=EXCLUDED.path_geom, path_tracks=EXCLUDED.path_tracks,
    squawk_runs=EXCLUDED.squawk_runs, raw_point_count=EXCLUDED.raw_point_count,
    ingest_batch_date=EXCLUDED.ingest_batch_date
"""


def _raw_point_to_dict(p: RawPoint) -> dict[str, object]:
    """Serialize a RawPoint to a JSON-compatible dict."""
    return dataclasses.asdict(p)


def _raw_point_from_dict(d: dict[str, object]) -> RawPoint:
    """Deserialize a RawPoint from a dict."""
    # d values are `object`; we cast to the expected concrete types via str() / float().
    return RawPoint(
        ts=float(str(d["ts"])),
        lat=float(str(d["lat"])),
        lon=float(str(d["lon"])),
        alt_baro=float(str(d["alt_baro"])) if d.get("alt_baro") is not None else None,
        track=float(str(d["track"])) if d.get("track") is not None else None,
        squawk=str(d["squawk"]) if d.get("squawk") is not None else None,
        new_leg=bool(d.get("new_leg", False)),
        callsign=str(d["callsign"]) if d.get("callsign") is not None else None,
        emitter_category=(
            str(d["emitter_category"]) if d.get("emitter_category") is not None else None
        ),
    )


def _flight_to_params(
    flight: FinalizedFlight,
    batch_date: date,
) -> tuple[
    str,
    str | None,
    str | None,
    str | None,
    datetime,
    datetime,
    str,
    str,
    str,
    list[int],
    str,
    int,
    date,
]:
    """Convert a FinalizedFlight into the parameter tuple for the UPSERT SQL."""
    start_v = flight.vertices[0]
    end_v = flight.vertices[-1]

    start_wkt = point_zm(start_v[0], start_v[1], start_v[2], start_v[3])
    end_wkt = point_zm(end_v[0], end_v[1], end_v[2], end_v[3])
    path_wkt = linestring_zm(flight.vertices)

    squawk_runs_json = json.dumps(flight.squawk_runs)

    return (
        flight.icao24,
        flight.callsign,
        flight.icao_type,
        flight.emitter_category,
        flight.start_ts,
        flight.end_ts,
        start_wkt,
        end_wkt,
        path_wkt,
        flight.path_tracks,
        squawk_runs_json,
        flight.raw_point_count,
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

    Trace processing (split + simplify) is parallelised across a
    ProcessPoolExecutor; DB writes are batched with executemany.

    Args:
        conn: asyncpg connection
        tarball_path: path to a .tar.gz file or directory containing .tar.XX parts
        batch_date: the date this batch corresponds to
        bbox: optional (min_lon, min_lat, max_lon, max_lat) filter
        workers: worker processes for CPU work (default: os.cpu_count())

    Returns:
        Number of flights finalized.
    """
    # Mark ingest_batches row as 'running'
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

    # Load all staging flights from DB
    staging_rows = await conn.fetch(
        "SELECT icao24, start_ts, last_ts, points FROM staging_flights"
    )

    staging: dict[str, list[RawPoint]] = {}
    for row in staging_rows:
        icao24: str = row["icao24"]
        raw_points: list[dict[str, object]] = json.loads(row["points"])
        pts = [_raw_point_from_dict(d) for d in raw_points]
        if icao24 in staging:
            staging[icao24].extend(pts)
        else:
            staging[icao24] = pts

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
    new_staging: dict[str, RawFlight] = {}
    pending: list[tuple[TraceHeader, list[RawPoint]]] = []

    with ProcessPoolExecutor(max_workers=n_workers) as pool:

        async def _flush() -> None:
            nonlocal flight_count, traces_done
            if not pending:
                return

            futures = [
                loop.run_in_executor(pool, _process_trace, h, pts, cutoff_ts)
                for h, pts in pending
            ]
            # return_exceptions=True keeps one bad trace from aborting the chunk
            results: list[Any] = list(
                await asyncio.gather(*futures, return_exceptions=True)
            )

            params_batch: list[
                tuple[
                    str,
                    str | None,
                    str | None,
                    str | None,
                    datetime,
                    datetime,
                    str,
                    str,
                    str,
                    list[int],
                    str,
                    int,
                    date,
                ]
            ] = []
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
                    new_staging[in_progress.icao24] = in_progress

            if params_batch:
                try:
                    await conn.executemany(_UPSERT_FLIGHT_SQL, params_batch)
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

            # Apply bbox filter
            if bbox is not None:
                min_lon, min_lat, max_lon, max_lat = bbox
                new_points = [
                    p
                    for p in new_points
                    if min_lon <= p.lon <= max_lon and min_lat <= p.lat <= max_lat
                ]
                if not new_points:
                    continue

            # Merge with staging points
            existing_pts = staging.get(icao24, [])
            if existing_pts:
                merged = existing_pts + new_points
                merged.sort(key=lambda p: p.ts)
                deduped: list[RawPoint] = []
                last_ts: float | None = None
                for p in merged:
                    if p.ts != last_ts:
                        deduped.append(p)
                        last_ts = p.ts
                all_points = deduped
            else:
                all_points = sorted(new_points, key=lambda p: p.ts)

            if not all_points:
                continue

            pending.append((trace_header, all_points))
            if len(pending) >= _CHUNK_SIZE:
                await _flush()

        await _flush()  # drain remaining

    # Update staging table in a transaction
    async with conn.transaction():
        await conn.execute("DELETE FROM staging_flights")
        for icao24, raw_flight in new_staging.items():
            points_json = json.dumps([_raw_point_to_dict(p) for p in raw_flight.points])
            start_ts_dt = datetime.fromtimestamp(raw_flight.points[0].ts, tz=UTC)
            last_ts_dt = datetime.fromtimestamp(raw_flight.points[-1].ts, tz=UTC)
            await conn.execute(
                """
                INSERT INTO staging_flights (icao24, start_ts, last_ts, points, source)
                VALUES ($1, $2, $3, $4::jsonb, 'batch')
                """,
                icao24,
                start_ts_dt,
                last_ts_dt,
                points_json,
            )

    # Mark batch as succeeded
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
