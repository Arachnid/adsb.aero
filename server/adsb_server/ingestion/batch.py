"""Batch ingestion: process a single day's tarball and write to the database."""

from __future__ import annotations

import dataclasses
import json
import logging
from datetime import UTC, date, datetime, time
from pathlib import Path  # noqa: TC003

import asyncpg  # noqa: TC002

from adsb_server.geometry.wkt import linestring_zm, point_zm
from adsb_server.ingestion.models import FinalizedFlight, RawFlight, RawPoint
from adsb_server.ingestion.parser import stream_tarball
from adsb_server.ingestion.splitter import split_flights

logger = logging.getLogger(__name__)

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


async def _write_flight(
    conn: asyncpg.Connection,    flight: FinalizedFlight,
    batch_date: date,
) -> None:
    """Write a single finalized flight to the database."""
    params = _flight_to_params(flight, batch_date)
    await conn.execute(_UPSERT_FLIGHT_SQL, *params)


async def run_batch(
    conn: asyncpg.Connection,    tarball_path: Path,
    batch_date: date,
    bbox: tuple[float, float, float, float] | None = None,
) -> int:
    """
    Process a single day's tarball and write flights to the database.

    Args:
        conn: asyncpg connection
        tarball_path: path to a .tar.gz file or directory containing .tar.XX parts
        batch_date: the date this batch corresponds to
        bbox: optional (min_lon, min_lat, max_lon, max_lat) filter

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

    # Deserialize staging points: dict keyed by icao24
    staging: dict[str, list[RawPoint]] = {}
    for row in staging_rows:
        icao24: str = row["icao24"]
        raw_points: list[dict[str, object]] = json.loads(row["points"])
        pts = [_raw_point_from_dict(d) for d in raw_points]
        if icao24 in staging:
            staging[icao24].extend(pts)
        else:
            staging[icao24] = pts

    # Compute cutoff_ts: midnight UTC at end of batch_date
    cutoff_dt = datetime.combine(batch_date, time.max, tzinfo=UTC)
    cutoff_ts = cutoff_dt.timestamp()

    flight_count = 0
    new_staging: dict[str, RawFlight] = {}

    # Stream tarball
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
            # Sort by ts and deduplicate
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

        # Split into flights
        finalized_flights, in_progress = split_flights(
            header=trace_header,
            points=all_points,
            cutoff_ts=cutoff_ts,
        )

        # Write finalized flights
        for flight in finalized_flights:
            try:
                await _write_flight(conn, flight, batch_date)
                flight_count += 1
            except Exception:
                logger.exception(
                    "Failed to write flight %s start=%s", flight.icao24, flight.start_ts
                )

        # Track in-progress flight for staging
        if in_progress is not None:
            new_staging[icao24] = in_progress

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
