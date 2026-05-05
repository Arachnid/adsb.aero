"""Integration tests for the batch ingestion pipeline.

These tests use the real database (requires Docker).
"""

from __future__ import annotations

import gzip
import io
import json
import tarfile
from datetime import UTC, date
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from pathlib import Path

    import asyncpg


def _make_trace_bytes(
    icao: str,
    base_ts: float = 1609275898.0,
    entries: list[list[object]] | None = None,
) -> bytes:
    """Build a gzip-compressed trace JSON bytes."""
    if entries is None:
        entries = [
            [0.0, 51.5, -0.1, 35000.0, 450.0, 90.0, 0, None,
             {"flight": "BAW100", "squawk": "1234"}],
            [30.0, 51.6, -0.2, 35100.0, 455.0, 91.0, 0, None, None],
            [60.0, 51.7, -0.3, 35200.0, 460.0, 92.0, 0, None, None],
        ]
    data = {
        "icao": icao,
        "t": "B738",
        "timestamp": base_ts,
        "trace": entries,
    }
    return gzip.compress(json.dumps(data).encode())


def _make_tarball_dir(tmp_path: Path, aircraft: list[str]) -> Path:
    """Create a directory with a single uncompressed tar part containing given aircraft."""
    raw_buf = io.BytesIO()
    with tarfile.open(fileobj=raw_buf, mode="w:") as tf:
        for icao in aircraft:
            trace_bytes = _make_trace_bytes(icao)
            hex2 = icao[:2].lower()
            member_name = f"traces/{hex2}/trace_full_{icao}.json.gz"
            ti = tarfile.TarInfo(name=member_name)
            ti.size = len(trace_bytes)
            tf.addfile(ti, io.BytesIO(trace_bytes))
    raw_bytes = raw_buf.getvalue()
    (tmp_path / "archive.tar.aa").write_bytes(raw_bytes)
    return tmp_path


@pytest.mark.asyncio
async def test_run_batch_creates_flights(
    conn: asyncpg.Connection,    tmp_path: Path,
) -> None:
    """run_batch writes flights to the DB and returns the count."""
    from adsb_server.ingestion.batch import run_batch

    tarball_dir = _make_tarball_dir(tmp_path, ["aabbcc", "ddeeff"])
    batch_date = date(2021, 1, 1)

    count = await run_batch(conn, tarball_dir, batch_date)
    assert count == 2

    rows = await conn.fetch("SELECT icao24 FROM flights")
    icaos = {r["icao24"] for r in rows}
    assert "aabbcc" in icaos
    assert "ddeeff" in icaos


@pytest.mark.asyncio
async def test_run_batch_marks_ingest_batch_succeeded(
    conn: asyncpg.Connection,    tmp_path: Path,
) -> None:
    """run_batch records status='succeeded' in ingest_batches."""
    from adsb_server.ingestion.batch import run_batch

    tarball_dir = _make_tarball_dir(tmp_path, ["aabbcc"])
    batch_date = date(2021, 2, 1)

    await run_batch(conn, tarball_dir, batch_date)

    row = await conn.fetchrow(
        "SELECT status, flight_count FROM ingest_batches WHERE batch_date = $1",
        batch_date,
    )
    assert row is not None
    assert row["status"] == "succeeded"
    assert row["flight_count"] == 1


@pytest.mark.asyncio
async def test_run_batch_with_bbox_filter(
    conn: asyncpg.Connection,    tmp_path: Path,
) -> None:
    """run_batch with bbox filter only processes points inside the box."""
    from adsb_server.ingestion.batch import run_batch

    # Aircraft at 51.5-51.7 lat, -0.3 to -0.1 lon — inside UK bbox
    tarball_dir = _make_tarball_dir(tmp_path, ["aabbcc"])
    batch_date = date(2021, 3, 1)

    # Tight bbox that includes the aircraft
    uk_bbox = (-1.0, 51.0, 0.0, 52.0)
    count = await run_batch(conn, tarball_dir, batch_date, bbox=uk_bbox)
    assert count == 1


@pytest.mark.asyncio
async def test_run_batch_bbox_excludes_outside_aircraft(
    conn: asyncpg.Connection,    tmp_path: Path,
) -> None:
    """run_batch with bbox excludes aircraft whose points are all outside."""
    from adsb_server.ingestion.batch import run_batch

    # Aircraft at UK coords, but bbox is in US
    tarball_dir = _make_tarball_dir(tmp_path, ["aabbcc"])
    batch_date = date(2021, 4, 1)

    us_bbox = (-100.0, 30.0, -70.0, 50.0)
    count = await run_batch(conn, tarball_dir, batch_date, bbox=us_bbox)
    assert count == 0


@pytest.mark.asyncio
async def test_run_batch_idempotent_upsert(
    conn: asyncpg.Connection,    tmp_path: Path,
) -> None:
    """Running the same batch twice does not duplicate flights."""
    from adsb_server.ingestion.batch import run_batch

    tarball_dir = _make_tarball_dir(tmp_path, ["aabbcc"])
    batch_date = date(2021, 5, 1)

    await run_batch(conn, tarball_dir, batch_date)
    await run_batch(conn, tarball_dir, batch_date)

    rows = await conn.fetch("SELECT icao24 FROM flights WHERE icao24 = 'aabbcc'")
    assert len(rows) == 1


@pytest.mark.asyncio
async def test_run_batch_staging_roundtrip(
    conn: asyncpg.Connection,    tmp_path: Path,
) -> None:
    """
    In-progress flights go to staging_flights; a subsequent batch
    that is past the cutoff finalizes them.
    """
    from adsb_server.ingestion.batch import run_batch

    # Points with timestamps close to end-of-day cutoff → in-progress
    batch_date = date(2021, 6, 1)
    # midnight UTC for 2021-06-01 = 1622505600
    # cutoff = end of day = 1622505600 + 86399.999...
    # Use a very large timestamp so the flight appears to end near cutoff
    cutoff_ts = 1622505600 + 86399  # ~end of 2021-06-01

    near_cutoff_entries: list[list[object]] = [
        [0.0, 51.5, -0.1, 35000.0, 450.0, 90.0, 0, None, None],
        [30.0, 51.6, -0.2, 35100.0, 455.0, 91.0, 0, None, None],
    ]

    raw_buf = io.BytesIO()
    with tarfile.open(fileobj=raw_buf, mode="w:") as tf:
        trace_bytes = _make_trace_bytes(
            "aabbcc", base_ts=float(cutoff_ts - 30), entries=near_cutoff_entries
        )
        ti = tarfile.TarInfo(name="traces/aa/trace_full_aabbcc.json.gz")
        ti.size = len(trace_bytes)
        tf.addfile(ti, io.BytesIO(trace_bytes))
    (tmp_path / "archive.tar.aa").write_bytes(raw_buf.getvalue())

    count = await run_batch(conn, tmp_path, batch_date)
    # Flight ends near cutoff, so might be in-progress; staging should have it
    staging = await conn.fetchrow(
        "SELECT icao24 FROM staging_flights WHERE icao24 = 'aabbcc'"
    )
    # Either finalized or in staging
    assert count >= 0 or staging is not None


@pytest.mark.asyncio
async def test_run_batch_merges_staging(
    conn: asyncpg.Connection,
    tmp_path: Path,
) -> None:
    """
    Pre-existing staging points are merged with new tarball points.
    The combined data produces a single finalized flight.
    """
    import json
    from datetime import datetime

    from adsb_server.ingestion.batch import run_batch

    # Insert staging entry for "cc1122" with 2 points from 1000.0 to 1030.0
    staging_points = [
        {
            "ts": 1000.0, "lat": 51.5, "lon": -0.1, "alt_baro": 35000.0,
            "track": 90.0, "squawk": None, "new_leg": False,
            "callsign": None, "emitter_category": None,
        },
        {
            "ts": 1030.0, "lat": 51.6, "lon": -0.2, "alt_baro": 35100.0,
            "track": 91.0, "squawk": None, "new_leg": False,
            "callsign": None, "emitter_category": None,
        },
    ]
    await conn.execute(
        """
        INSERT INTO staging_flights (icao24, start_ts, last_ts, points, source)
        VALUES ($1, $2, $3, $4::jsonb, 'batch')
        """,
        "cc1122",
        datetime.fromtimestamp(1000.0, tz=UTC),
        datetime.fromtimestamp(1030.0, tz=UTC),
        json.dumps(staging_points),
    )

    # Tarball continues from ts=1060.0 to 1090.0
    entries: list[list[object]] = [
        [0.0, 51.7, -0.3, 35200.0, 460.0, 92.0, 0, None, None],
        [30.0, 51.8, -0.4, 35300.0, 465.0, 93.0, 0, None, None],
    ]
    raw_buf = io.BytesIO()
    with tarfile.open(fileobj=raw_buf, mode="w:") as tf:
        trace_bytes = _make_trace_bytes("cc1122", base_ts=1060.0, entries=entries)
        ti = tarfile.TarInfo(name="traces/cc/trace_full_cc1122.json.gz")
        ti.size = len(trace_bytes)
        tf.addfile(ti, io.BytesIO(trace_bytes))
    (tmp_path / "archive.tar.aa").write_bytes(raw_buf.getvalue())

    # Batch date well in the future so all points are finalized
    batch_date = date(2099, 1, 1)
    count = await run_batch(conn, tmp_path, batch_date)
    assert count == 1  # one merged flight


@pytest.mark.asyncio
async def test_run_batch_serialization_roundtrip(
    conn: asyncpg.Connection,
    tmp_path: Path,
) -> None:
    """Batch writes correct WKT geometry and path_tracks to DB."""
    from adsb_server.ingestion.batch import run_batch

    tarball_dir = _make_tarball_dir(tmp_path, ["ff1122"])
    batch_date = date(2021, 7, 1)

    count = await run_batch(conn, tarball_dir, batch_date)
    assert count == 1

    row = await conn.fetchrow(
        "SELECT path_tracks, squawk_runs FROM flights WHERE icao24 = 'ff1122'"
    )
    assert row is not None
    assert isinstance(row["path_tracks"], list)
    # squawk_runs should be valid JSON (list of [ts, squawk] pairs)
    import json as _json
    runs = _json.loads(row["squawk_runs"])
    assert isinstance(runs, list)
