"""Batch ingestion: process a single day's tarball and write to the database."""

from __future__ import annotations

import asyncio
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
from adsb_server.ingestion.splitter import build_squawk_runs, split_flights

logger = logging.getLogger(__name__)

# Traces dispatched to the process pool per asyncio gather cycle.
# Large enough to keep all workers busy; small enough that the event loop
# remains responsive and memory stays bounded.
_CHUNK_SIZE = 256

_UPSERT_FLIGHT_SQL = """
INSERT INTO flights (icao24, callsign, icao_type, emitter_category,
    start_ts, end_ts, start_point, end_point, path_geom,
    path_tracks, squawk_runs, raw_point_count, ingest_batch_date,
    completed)
VALUES ($1,$2,$3,$4,$5,$6,
    ST_GeomFromText($7,4326), ST_GeomFromText($8,4326), ST_GeomFromText($9,4326),
    $10, $11::jsonb, $12, $13, $14)
ON CONFLICT (icao24, start_ts) DO UPDATE SET
    callsign=EXCLUDED.callsign, icao_type=EXCLUDED.icao_type,
    emitter_category=EXCLUDED.emitter_category,
    end_ts=EXCLUDED.end_ts, end_point=EXCLUDED.end_point,
    path_geom=EXCLUDED.path_geom, path_tracks=EXCLUDED.path_tracks,
    squawk_runs=EXCLUDED.squawk_runs, raw_point_count=EXCLUDED.raw_point_count,
    ingest_batch_date=EXCLUDED.ingest_batch_date,
    completed=EXCLUDED.completed
"""


def _parse_linestring_zm(wkt: str) -> list[tuple[float, float, float, float]]:
    """Parse a LINESTRING ZM WKT string into (lon, lat, alt, ts) tuples."""
    inner = wkt.split("(", 1)[1].rstrip(")")
    result: list[tuple[float, float, float, float]] = []
    for point_str in inner.split(","):
        x, y, z, m = point_str.split()
        result.append((float(x), float(y), float(z), float(m)))
    return result


def _squawk_at_ts(squawk_runs: list[tuple[float, str]], ts: float) -> str | None:
    """Return the squawk code in effect at ts via forward-fill over sorted squawk_runs."""
    result: str | None = None
    for run_ts, code in squawk_runs:
        if run_ts <= ts:
            result = code
        else:
            break
    return result


_FlightParams = tuple[
    str, str | None, str | None, str | None,
    datetime, datetime,
    str, str, str,
    list[int], str, int, date,
    bool,
]


def _flight_to_params(
    flight: FinalizedFlight,
    batch_date: date,
) -> _FlightParams:
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
        True,
    )


def _raw_flight_to_params(
    flight: RawFlight,
    batch_date: date,
) -> _FlightParams | None:
    """Convert an in-progress RawFlight into the parameter tuple for the UPSERT SQL.

    Returns None if fewer than 2 airborne points (cannot form valid geometry).
    """
    airborne = [p for p in flight.points if p.alt_baro is not None]
    if len(airborne) < 2:
        return None

    vertices: list[tuple[float, float, float, float]] = [
        (p.lon, p.lat, p.alt_baro if p.alt_baro is not None else 0.0, p.ts)
        for p in airborne
    ]

    start_wkt = point_zm(vertices[0][0], vertices[0][1], vertices[0][2], vertices[0][3])
    end_wkt = point_zm(vertices[-1][0], vertices[-1][1], vertices[-1][2], vertices[-1][3])
    path_wkt = linestring_zm(vertices)

    path_tracks: list[int] = [
        round(p.track) % 360 if p.track is not None else 0
        for p in airborne
    ]

    start_ts = datetime.fromtimestamp(vertices[0][3], tz=UTC)
    end_ts = datetime.fromtimestamp(vertices[-1][3], tz=UTC)

    squawk_runs_json = json.dumps(build_squawk_runs(airborne))

    return (
        flight.icao24,
        flight.callsign,
        flight.icao_type,
        flight.emitter_category,
        start_ts,
        end_ts,
        start_wkt,
        end_wkt,
        path_wkt,
        path_tracks,
        squawk_runs_json,
        len(flight.points),
        batch_date,
        False,
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

    # Load all in-progress flights from DB
    staging_rows = await conn.fetch(
        """
        SELECT icao24, callsign, emitter_category, squawk_runs,
               ST_AsText(path_geom) AS path_wkt
        FROM flights WHERE completed = false
        """
    )

    staging: dict[str, list[RawPoint]] = {}
    for row in staging_rows:
        icao24: str = row["icao24"]
        callsign: str | None = row["callsign"]
        emitter_category: str | None = row["emitter_category"]
        runs: list[tuple[float, str]] = [
            (float(r[0]), str(r[1])) for r in json.loads(row["squawk_runs"])
        ]
        pts: list[RawPoint] = [
            RawPoint(
                ts=m, lat=y, lon=x, alt_baro=z,
                track=None, squawk=_squawk_at_ts(runs, m),
                new_leg=False, callsign=callsign,
                emitter_category=emitter_category,
            )
            for x, y, z, m in _parse_linestring_zm(row["path_wkt"])
        ]
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
                    raw_params = _raw_flight_to_params(in_progress, batch_date)
                    if raw_params is not None:
                        params_batch.append(raw_params)

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
