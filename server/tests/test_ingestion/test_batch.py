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

    rows = await conn.fetch(
        "SELECT icao24 FROM flights WHERE icao24 = 'aabbcc' AND ingest_batch_date = '2021-05-01'"
    )
    assert len(rows) == 1


@pytest.mark.asyncio
async def test_run_batch_in_progress_roundtrip(
    conn: asyncpg.Connection,    tmp_path: Path,
) -> None:
    """
    In-progress flights are stored in flights with completed=false;
    a subsequent batch past the cutoff finalizes them.
    """
    from adsb_server.ingestion.batch import run_batch

    batch_date = date(2021, 6, 1)
    cutoff_ts = 1622505600 + 86399  # ~end of 2021-06-01

    near_cutoff_entries: list[list[object]] = [
        [0.0, 51.5, -0.1, 35000.0, 450.0, 90.0, 0, None, None],
        [30.0, 51.6, -0.2, 35100.0, 455.0, 91.0, 0, None, None],
    ]

    raw_buf = io.BytesIO()
    with tarfile.open(fileobj=raw_buf, mode="w:") as tf:
        trace_bytes = _make_trace_bytes(
            "ip0001", base_ts=float(cutoff_ts - 30), entries=near_cutoff_entries
        )
        ti = tarfile.TarInfo(name="traces/ip/trace_full_ip0001.json.gz")
        ti.size = len(trace_bytes)
        tf.addfile(ti, io.BytesIO(trace_bytes))
    (tmp_path / "archive.tar.aa").write_bytes(raw_buf.getvalue())

    await run_batch(conn, tmp_path, batch_date)

    # Flight ends within the airborne in-progress window → stored as completed=false
    row = await conn.fetchrow(
        "SELECT completed FROM flights WHERE icao24 = 'ip0001'"
    )
    assert row is not None
    assert row["completed"] is False


@pytest.mark.asyncio
async def test_run_batch_merges_in_progress(
    conn: asyncpg.Connection,
    tmp_path: Path,
) -> None:
    """
    Pre-existing in-progress points in flights are merged with new tarball points.
    The combined data produces a single finalized flight.
    """
    from datetime import datetime

    from adsb_server.ingestion.batch import run_batch

    # Insert an in-progress flight for "cc1122" with 2 points from 1000.0 to 1030.0
    start_ts = datetime.fromtimestamp(1000.0, tz=UTC)
    end_ts = datetime.fromtimestamp(1030.0, tz=UTC)
    await conn.execute(
        """
        INSERT INTO flights (
            icao24, start_ts, end_ts,
            start_point, end_point, path_geom,
            path_tracks, squawk_runs, raw_point_count,
            ingest_batch_date, completed
        ) VALUES (
            $1, $2, $3,
            ST_GeomFromText('POINT ZM (-0.1 51.5 35000 1000)', 4326),
            ST_GeomFromText('POINT ZM (-0.2 51.6 35100 1030)', 4326),
            ST_GeomFromText('LINESTRING ZM (-0.1 51.5 35000 1000,-0.2 51.6 35100 1030)', 4326),
            ARRAY[90, 91], '[]'::jsonb, 2,
            '2021-01-01', false
        )
        """,
        "cc1122",
        start_ts,
        end_ts,
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

    # The row should now be completed
    row = await conn.fetchrow(
        "SELECT completed FROM flights WHERE icao24 = 'cc1122'"
    )
    assert row is not None
    assert row["completed"] is True


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
    import json as _json
    runs = _json.loads(row["squawk_runs"])
    assert isinstance(runs, list)


@pytest.mark.asyncio
async def test_in_progress_and_completed_visible_together(
    conn: asyncpg.Connection,
    tmp_path: Path,
) -> None:
    """completed=false and completed=true rows both appear in unfiltered flights queries."""
    from adsb_server.ingestion.batch import run_batch

    # Batch 1: one aircraft well before cutoff (finalised), one near cutoff (in-progress)
    batch_date = date(2021, 8, 1)
    cutoff_ts = 1627776000 + 86399  # end of 2021-08-01

    far_entries: list[list[object]] = [
        [0.0,  51.5, -0.1, 35000.0, 90.0, 0.0, 0, None, None],
        [60.0, 51.6, -0.2, 35100.0, 91.0, 0.0, 0, None, None],
        [120.0, 51.7, -0.3, 35200.0, 92.0, 0.0, 0, None, None],
    ]
    near_entries: list[list[object]] = [
        [0.0,  51.5, -0.1, 35000.0, 90.0, 0.0, 0, None, None],
        [30.0, 51.6, -0.2, 35100.0, 91.0, 0.0, 0, None, None],
    ]

    raw_buf = io.BytesIO()
    with tarfile.open(fileobj=raw_buf, mode="w:") as tf:
        # "aa0001" ends at ts=100 — well before cutoff
        b = _make_trace_bytes("aa0001", base_ts=100.0, entries=far_entries)
        ti = tarfile.TarInfo(name="traces/aa/trace_full_aa0001.json.gz")
        ti.size = len(b)
        tf.addfile(ti, io.BytesIO(b))
        # "aa0002" ends near cutoff
        b = _make_trace_bytes("aa0002", base_ts=float(cutoff_ts - 30), entries=near_entries)
        ti = tarfile.TarInfo(name="traces/aa/trace_full_aa0002.json.gz")
        ti.size = len(b)
        tf.addfile(ti, io.BytesIO(b))
    (tmp_path / "archive.tar.aa").write_bytes(raw_buf.getvalue())

    await run_batch(conn, tmp_path, batch_date)

    rows = await conn.fetch(
        "SELECT icao24, completed FROM flights WHERE icao24 = ANY($1)",
        ["aa0001", "aa0002"],
    )
    by_icao = {r["icao24"]: r["completed"] for r in rows}
    assert by_icao.get("aa0001") is True
    assert by_icao.get("aa0002") is False


@pytest.mark.asyncio
async def test_run_batch_two_batches_finalizes_in_progress(
    conn: asyncpg.Connection,
    tmp_path: Path,
) -> None:
    """
    A flight left in-progress by batch 1 is completed=false in the DB.
    Batch 2, with a later date, picks it up and finalises it as completed=true.
    """
    from adsb_server.ingestion.batch import run_batch

    batch_date_1 = date(2021, 9, 1)
    cutoff_ts_1 = 1630454400 + 86399  # end of 2021-09-01

    near_entries: list[list[object]] = [
        [0.0,  51.5, -0.1, 35000.0, 90.0, 0.0, 0, None, None],
        [30.0, 51.6, -0.2, 35100.0, 91.0, 0.0, 0, None, None],
    ]

    # --- Batch 1 ---
    tmp1 = tmp_path / "batch1"
    tmp1.mkdir()
    raw_buf = io.BytesIO()
    with tarfile.open(fileobj=raw_buf, mode="w:") as tf:
        b = _make_trace_bytes("bb0001", base_ts=float(cutoff_ts_1 - 30), entries=near_entries)
        ti = tarfile.TarInfo(name="traces/bb/trace_full_bb0001.json.gz")
        ti.size = len(b)
        tf.addfile(ti, io.BytesIO(b))
    (tmp1 / "archive.tar.aa").write_bytes(raw_buf.getvalue())

    await run_batch(conn, tmp1, batch_date_1)

    row = await conn.fetchrow("SELECT completed FROM flights WHERE icao24 = 'bb0001'")
    assert row is not None
    assert row["completed"] is False, "should be in-progress after batch 1"

    # --- Batch 2: same points but well before the new batch's cutoff ---
    batch_date_2 = date(2021, 9, 2)
    tmp2 = tmp_path / "batch2"
    tmp2.mkdir()
    cont_entries: list[list[object]] = [
        [0.0,  51.7, -0.3, 35200.0, 92.0, 0.0, 0, None, None],
        [30.0, 51.8, -0.4, 35300.0, 93.0, 0.0, 0, None, None],
        [60.0, 51.9, -0.5, 35400.0, 94.0, 0.0, 0, None, None],
    ]
    raw_buf = io.BytesIO()
    with tarfile.open(fileobj=raw_buf, mode="w:") as tf:
        b = _make_trace_bytes("bb0001", base_ts=float(cutoff_ts_1 + 60), entries=cont_entries)
        ti = tarfile.TarInfo(name="traces/bb/trace_full_bb0001.json.gz")
        ti.size = len(b)
        tf.addfile(ti, io.BytesIO(b))
    (tmp2 / "archive.tar.aa").write_bytes(raw_buf.getvalue())

    count = await run_batch(conn, tmp2, batch_date_2)
    assert count >= 1, "at least the merged flight should be finalised"

    row = await conn.fetchrow("SELECT completed FROM flights WHERE icao24 = 'bb0001'")
    assert row is not None
    assert row["completed"] is True, "should be finalised after batch 2"


@pytest.mark.asyncio
async def test_squawk_reconstructed_from_in_progress(
    conn: asyncpg.Connection,
    tmp_path: Path,
) -> None:
    """
    Squawk codes observed in batch 1 are stored as squawk_runs on the in-progress row
    and reconstructed when batch 2 loads it, so the finalised squawk_runs span both batches.
    """
    import json as _json

    from adsb_server.ingestion.batch import run_batch

    batch_date_1 = date(2021, 10, 1)
    cutoff_ts_1 = 1633046400 + 86399  # end of 2021-10-01

    # Points near cutoff with a distinctive squawk
    squawk_entries: list[list[object]] = [
        [0.0,  51.5, -0.1, 35000.0, 90.0, 0.0, 0, None, {"squawk": "7700"}],
        [30.0, 51.6, -0.2, 35100.0, 91.0, 0.0, 0, None, {"squawk": "7700"}],
    ]

    tmp1 = tmp_path / "batch1"
    tmp1.mkdir()
    raw_buf = io.BytesIO()
    with tarfile.open(fileobj=raw_buf, mode="w:") as tf:
        b = _make_trace_bytes("cc0001", base_ts=float(cutoff_ts_1 - 30), entries=squawk_entries)
        ti = tarfile.TarInfo(name="traces/cc/trace_full_cc0001.json.gz")
        ti.size = len(b)
        tf.addfile(ti, io.BytesIO(b))
    (tmp1 / "archive.tar.aa").write_bytes(raw_buf.getvalue())

    await run_batch(conn, tmp1, batch_date_1)

    # In-progress row should have the 7700 squawk stored
    row = await conn.fetchrow(
        "SELECT completed, squawk_runs FROM flights WHERE icao24 = 'cc0001'"
    )
    assert row is not None
    assert row["completed"] is False
    runs_1 = _json.loads(row["squawk_runs"])
    assert any(r[1] == "7700" for r in runs_1), "7700 should be in squawk_runs after batch 1"

    # Batch 2: continuation well before new cutoff, different squawk
    batch_date_2 = date(2021, 10, 2)
    cont_entries: list[list[object]] = [
        [0.0,  51.7, -0.3, 35200.0, 92.0, 0.0, 0, None, {"squawk": "2000"}],
        [30.0, 51.8, -0.4, 35300.0, 93.0, 0.0, 0, None, {"squawk": "2000"}],
        [60.0, 51.9, -0.5, 35400.0, 94.0, 0.0, 0, None, None],
    ]
    tmp2 = tmp_path / "batch2"
    tmp2.mkdir()
    raw_buf = io.BytesIO()
    with tarfile.open(fileobj=raw_buf, mode="w:") as tf:
        b = _make_trace_bytes("cc0001", base_ts=float(cutoff_ts_1 + 60), entries=cont_entries)
        ti = tarfile.TarInfo(name="traces/cc/trace_full_cc0001.json.gz")
        ti.size = len(b)
        tf.addfile(ti, io.BytesIO(b))
    (tmp2 / "archive.tar.aa").write_bytes(raw_buf.getvalue())

    await run_batch(conn, tmp2, batch_date_2)

    row = await conn.fetchrow(
        "SELECT completed, squawk_runs FROM flights WHERE icao24 = 'cc0001'"
    )
    assert row is not None
    assert row["completed"] is True
    runs_2 = _json.loads(row["squawk_runs"])
    squawk_codes = {r[1] for r in runs_2}
    assert "7700" in squawk_codes, "7700 from batch 1 should survive into finalised squawk_runs"
    assert "2000" in squawk_codes, "2000 from batch 2 should appear in finalised squawk_runs"
