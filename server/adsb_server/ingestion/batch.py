"""Batch ingestion: process a single day's tarball and write to the database."""

from __future__ import annotations

import itertools
import logging
import multiprocessing
import os
import pickle
import shutil
import time as _time
import zlib
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path  # noqa: TC003
from typing import TYPE_CHECKING, Any, NamedTuple

if TYPE_CHECKING:
    from collections.abc import Iterator

    import asyncpg

from adsb_server.config import get_settings
from adsb_server.geometry.h3_cells import path_h3_cells
from adsb_server.geometry.wkt import (
    tfloat_stepwise_seqset,
    tgeompoint_seqset,
    tint_seqset,
    ttext_seqset,
)
from adsb_server.ingestion.models import FinalizedFlight, RawFlight, RawPoint, TraceHeader
from adsb_server.ingestion.parser import parse_trace_bytes, stream_tarball_raw
from adsb_server.ingestion.splitter import finalize_segment, split_flights
from adsb_server.pressure.correct import build_correction_interpolator, compute_correction_series
from adsb_server.pressure.fetch import fetch_mslp_for_batch

logger = logging.getLogger(__name__)

# Traces accumulated per DB write.
_FLUSH_THRESHOLD = 256
# Seconds between progress log lines.
_LOG_INTERVAL_SECS = 5.0
# Traces per process-pool chunk.
_POOL_CHUNK_SIZE = 16

_UPSERT_ICAO_TYPE_STATS_SQL = """
INSERT INTO icao_type_stats (day, icao_type, model, flight_count)
SELECT
    $1::date,
    f.icao_type,
    (
        SELECT af.model
        FROM airframes af
        WHERE af.icao_type = f.icao_type
          AND af.model IS NOT NULL
        GROUP BY af.model
        ORDER BY COUNT(*) DESC
        LIMIT 1
    ),
    COUNT(*)
FROM flights f
WHERE f.start_ts >= $1::date::timestamptz
  AND f.start_ts <  ($1::date + 1)::timestamptz
  AND f.icao_type IS NOT NULL
GROUP BY f.icao_type
ON CONFLICT (day, icao_type) DO UPDATE SET
    model        = EXCLUDED.model,
    flight_count = EXCLUDED.flight_count
"""

_UPSERT_FLIGHT_SQL = """
INSERT INTO flights (icao24, callsign, icao_type, emitter_category,
    start_ts, end_ts, path, path_tracks,
    squawk_seq, alt_correction_ft,
    path_gs, path_vr, path_ias,
    raw_point_count, ingest_batch_date, path_h3, squawk_codes)
VALUES ($1,$2,$3,$4,$5,$6,
    $7::tgeompoint, $8::tint,
    $9::ttext, $10::tfloat,
    $11::tint, $12::tint, $13::tint,
    $14, $15, $16::h3index[], $17::text[])
ON CONFLICT (icao24, start_ts) DO UPDATE SET
    callsign=EXCLUDED.callsign, icao_type=EXCLUDED.icao_type,
    emitter_category=EXCLUDED.emitter_category,
    end_ts=EXCLUDED.end_ts,
    path=EXCLUDED.path, path_tracks=EXCLUDED.path_tracks,
    squawk_seq=EXCLUDED.squawk_seq,
    alt_correction_ft=EXCLUDED.alt_correction_ft,
    path_gs=EXCLUDED.path_gs, path_vr=EXCLUDED.path_vr, path_ias=EXCLUDED.path_ias,
    raw_point_count=EXCLUDED.raw_point_count,
    ingest_batch_date=EXCLUDED.ingest_batch_date,
    path_h3=EXCLUDED.path_h3,
    squawk_codes=EXCLUDED.squawk_codes
"""

_FlightParams = tuple[
    str,
    str | None,
    str | None,
    str | None,
    datetime,
    datetime,
    str,
    str | None,
    str | None,
    str | None,
    str | None,
    str | None,
    str | None,
    int,
    date,
    list[str],
    list[str],
]


class _WorkerState(NamedTuple):
    correction_interp: Any  # scipy RegularGridInterpolator
    t_min: float
    t_max: float
    batch_date: date
    cutoff_ts: float
    staging: dict[str, RawFlight]


# Set in run_batch before Pool creation; inherited by forked workers.
_worker_state: _WorkerState | None = None


def _cleanup_old_herbie_cache(cache_dir: Path, batch_date: date) -> None:
    """Delete herbie GFS cache directories for dates strictly before batch_date."""
    if not cache_dir.exists():
        return
    try:
        for entry in cache_dir.iterdir():
            if not entry.is_dir():
                continue
            # Herbie names dirs like "gfs.YYYYMMDD"
            dot = entry.name.rfind(".")
            date_part = entry.name[dot + 1 :] if dot != -1 else ""
            if len(date_part) != 8 or not date_part.isdigit():
                continue
            try:
                entry_date = date(int(date_part[:4]), int(date_part[4:6]), int(date_part[6:]))
            except ValueError:
                continue
            if entry_date < batch_date:
                shutil.rmtree(entry, ignore_errors=True)
                logger.info("Deleted old herbie cache: %s", entry.name)
    except OSError:
        logger.warning("Failed to scan herbie cache dir %s", cache_dir, exc_info=True)


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
    alt_correction_ft: str | None,
) -> _FlightParams:
    """Convert a FinalizedFlight into the parameter tuple for the UPSERT SQL."""
    return (
        flight.icao24,
        flight.callsign,
        flight.icao_type,
        flight.emitter_category,
        flight.start_ts,
        flight.end_ts,
        tgeompoint_seqset(flight.vertex_sequences),
        tint_seqset(flight.path_tracks_series),
        ttext_seqset(flight.squawk_runs),
        alt_correction_ft,
        tint_seqset(flight.path_gs_series),
        tint_seqset(flight.path_vr_series),
        tint_seqset(flight.path_ias_series),
        flight.raw_point_count,
        batch_date,
        path_h3_cells(flight.vertex_sequences),
        list({code for seq in flight.squawk_runs for _, code in seq}),
    )


def _log_progress(
    traces_done: int,
    flight_count: int,
    t_start: float,
    last_log_time: float,
) -> float:
    """Log throughput if enough time has passed; return updated last_log_time."""
    now = _time.monotonic()
    if now - last_log_time < _LOG_INTERVAL_SECS:
        return last_log_time
    elapsed = now - t_start
    rate = traces_done / (elapsed / 60.0) if elapsed > 0 else 0.0
    logger.info("%d traces | %.0f traces/min | %d flights", traces_done, rate, flight_count)
    return now


def _process_and_correct(
    args: tuple[str, bytes | None],
) -> tuple[list[_FlightParams], RawFlight | None, int, str | None]:
    """
    Worker function: parse trace bytes, merge staging points, split into discrete
    flights, apply altitude correction, return (db_params_list, in_progress).

    Runs in a forked worker; state (including staging dict) is inherited from parent.
    For tarball entries args=(member_name, raw_bytes); for orphan staging entries
    args=(icao24, None) — the worker determines icao24 from the JSON when raw_bytes
    is present, or uses the first arg directly for orphans.
    """
    assert _worker_state is not None
    state = _worker_state
    name, trace_bytes = args

    icao24: str | None = None
    icao_type: str | None = None
    new_points: list[RawPoint] = []

    if trace_bytes is not None:
        try:
            header, new_points = parse_trace_bytes(trace_bytes)
            icao24 = header.icao24
            icao_type = header.icao_type
        except Exception:
            logger.warning("Failed to parse trace %s", name, exc_info=True)
    else:
        icao24 = name  # orphan: name is the icao24

    base_points: list[RawPoint] = []
    if icao24 is not None:
        staging_flight = state.staging.get(icao24)
        if staging_flight is not None:
            base_points = staging_flight.points
            if icao_type is None:
                icao_type = staging_flight.icao_type

    if icao24 is None or not (base_points or new_points):
        return [], None, 0, icao24

    all_points = base_points + new_points
    all_points.sort(key=lambda p: p.ts)
    deduped: list[RawPoint] = []
    last_ts: float | None = None
    for p in all_points:
        if p.ts != last_ts:
            deduped.append(p)
            last_ts = p.ts

    trace_header = TraceHeader(icao24=icao24, icao_type=icao_type)
    finalized, in_progress, total_dropped = split_flights(trace_header, deduped, state.cutoff_ts)
    if in_progress is not None:
        ip_finalized, ip_dropped = finalize_segment(
            in_progress.icao24, in_progress.points, in_progress.icao_type
        )
        total_dropped += ip_dropped
        if ip_finalized is not None:
            finalized.append(ip_finalized)

    params_list: list[_FlightParams] = []
    for flight in finalized:
        flat_verts = [v for seq in flight.vertex_sequences for v in seq]
        series = compute_correction_series(
            flat_verts, state.correction_interp, state.t_min, state.t_max
        )
        wkt: str | None = None
        if series is not None:
            corr_ts, corr_vals = series
            # Split the flat correction arrays back into per-sub-sequence pairs.
            per_seq: list[tuple[list[float], list[float]]] = []
            offset = 0
            for seq in flight.vertex_sequences:
                n = len(seq)
                per_seq.append(
                    (
                        list(corr_vals[offset : offset + n]),
                        list(corr_ts[offset : offset + n]),
                    )
                )
                offset += n
            wkt = tfloat_stepwise_seqset(per_seq)
        params_list.append(_flight_to_params(flight, state.batch_date, wkt))

    return params_list, in_progress, total_dropped, icao24


async def run_batch(
    conn: asyncpg.Connection,
    tarball_path: Path,
    batch_date: date,
    workers: int | None = None,
    herbie_cache_dir: Path | None = None,
    keep_herbie_cache: bool | None = None,
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
    global _worker_state

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
            len(staging),
            prev_date,
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

    settings = get_settings()
    effective_cache_dir = (
        herbie_cache_dir if herbie_cache_dir is not None else settings.herbie_cache_dir
    )
    effective_keep_herbie_cache = (
        keep_herbie_cache if keep_herbie_cache is not None else settings.herbie_keep_cache
    )

    mslp = await fetch_mslp_for_batch(batch_date, effective_cache_dir)
    if mslp is None:
        raise RuntimeError(
            f"MSLP data unavailable for {batch_date} — cannot compute altitude corrections"
        )
    correction_interp, t_min, t_max = build_correction_interpolator(mslp)
    del mslp  # release the raw DataArray; the interpolator holds sorted copies

    n_workers = workers if workers is not None and workers > 0 else (os.cpu_count() or 1)
    logger.info("Starting batch %s with %d workers", batch_date, n_workers)

    # Set worker state before fork so all worker processes inherit it.
    _worker_state = _WorkerState(correction_interp, t_min, t_max, batch_date, cutoff_ts, staging)

    flight_count = 0
    t_start = _time.monotonic()
    last_log_time = t_start
    in_progress_flights: dict[str, RawFlight] = {}
    total_dropped_points = 0
    icaos_with_drops: set[str] = set()

    def _iter_trace_args() -> Iterator[tuple[str, bytes | None]]:
        seen: set[str] = set()
        for name, raw_bytes in stream_tarball_raw(tarball_path):
            icao24 = name.rsplit("/", 1)[-1].split(".")[0].removeprefix("trace_full_")
            seen.add(icao24)
            yield name, raw_bytes
        for icao24 in staging:
            if icao24 not in seen:
                yield icao24, None

    mp_ctx = multiprocessing.get_context("fork")
    with mp_ctx.Pool(n_workers) as pool:
        traces_done = 0
        for batch in itertools.batched(
            pool.imap_unordered(
                _process_and_correct,
                _iter_trace_args(),
                chunksize=_POOL_CHUNK_SIZE,
            ),
            _FLUSH_THRESHOLD,
            strict=False,
        ):
            db_params: list[_FlightParams] = []
            for result in batch:
                params_list, ip_raw, dropped, result_icao24 = result
                if ip_raw is not None:
                    in_progress_flights[ip_raw.icao24] = ip_raw
                if dropped and result_icao24 is not None:
                    total_dropped_points += dropped
                    icaos_with_drops.add(result_icao24)
                db_params.extend(params_list)
                traces_done += 1
                last_log_time = _log_progress(traces_done, flight_count, t_start, last_log_time)
            if db_params:
                try:
                    await conn.executemany(_UPSERT_FLIGHT_SQL, db_params)
                    for p in db_params:
                        upserted_keys.add((p[0], p[4]))  # (icao24, start_ts)
                    flight_count += len(db_params)
                except Exception:
                    logger.exception("Failed to write batch of %d flights", len(db_params))

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
            len(in_progress_flights),
            batch_date,
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

    await conn.execute(_UPSERT_ICAO_TYPE_STATS_SQL, batch_date)
    logger.info("Updated icao_type_stats for batch_date=%s", batch_date)

    await conn.execute(
        """
        UPDATE ingest_batches
        SET status='succeeded', finished_at=NOW(), flight_count=$2
        WHERE batch_date=$1
        """,
        batch_date,
        flight_count,
    )

    if not effective_keep_herbie_cache:
        _cleanup_old_herbie_cache(effective_cache_dir, batch_date)

    if total_dropped_points:
        logger.info(
            "Batch %s complete: %d flights finalized; "
            "%d implausible points dropped across %d ICAO(s)",
            batch_date,
            flight_count,
            total_dropped_points,
            len(icaos_with_drops),
        )
    else:
        logger.info("Batch %s complete: %d flights finalized", batch_date, flight_count)
    return flight_count
