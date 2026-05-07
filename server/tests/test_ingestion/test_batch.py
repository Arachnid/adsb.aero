"""Integration tests for the batch ingestion pipeline.

These tests use the real database (requires Docker).
"""

from __future__ import annotations

import gzip
import io
import json
import tarfile
from datetime import UTC, date, datetime
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
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
    conn: asyncpg.Connection,
    tmp_path: Path,
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
    conn: asyncpg.Connection,
    tmp_path: Path,
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
    conn: asyncpg.Connection,
    tmp_path: Path,
) -> None:
    """run_batch with bbox filter only processes points inside the box."""
    from adsb_server.ingestion.batch import run_batch

    tarball_dir = _make_tarball_dir(tmp_path, ["aabbcc"])
    batch_date = date(2021, 3, 1)

    uk_bbox = (-1.0, 51.0, 0.0, 52.0)
    count = await run_batch(conn, tarball_dir, batch_date, bbox=uk_bbox)
    assert count == 1


@pytest.mark.asyncio
async def test_run_batch_bbox_excludes_outside_aircraft(
    conn: asyncpg.Connection,
    tmp_path: Path,
) -> None:
    """run_batch with bbox excludes aircraft whose points are all outside."""
    from adsb_server.ingestion.batch import run_batch

    tarball_dir = _make_tarball_dir(tmp_path, ["aabbcc"])
    batch_date = date(2021, 4, 1)

    us_bbox = (-100.0, 30.0, -70.0, 50.0)
    count = await run_batch(conn, tarball_dir, batch_date, bbox=us_bbox)
    assert count == 0


@pytest.mark.asyncio
async def test_run_batch_idempotent_upsert(
    conn: asyncpg.Connection,
    tmp_path: Path,
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
async def test_run_batch_in_progress_written_to_staging(
    conn: asyncpg.Connection,
    tmp_path: Path,
) -> None:
    """
    In-progress flights are written to flight_staging and visible in the flights
    table with a simplified path (no ground points).
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

    # Flight is visible in the flights table with a simplified path
    row = await conn.fetchrow("SELECT icao24 FROM flights WHERE icao24 = 'ip0001'")
    assert row is not None

    # Raw points written to staging for next day's use
    staging_row = await conn.fetchrow(
        "SELECT staging_data FROM flight_staging WHERE batch_date = $1", batch_date
    )
    assert staging_row is not None

    from adsb_server.ingestion.batch import _deserialize_staging
    staging = _deserialize_staging(bytes(staging_row["staging_data"]))
    assert "ip0001" in staging


@pytest.mark.asyncio
async def test_run_batch_merges_in_progress_from_staging(
    conn: asyncpg.Connection,
    tmp_path: Path,
) -> None:
    """
    In-progress points from the previous day's staging blob are merged with new
    tarball points.  The combined data produces a single finalized flight.
    """
    from adsb_server.ingestion.batch import _serialize_staging, run_batch
    from adsb_server.ingestion.models import RawFlight, RawPoint

    batch_date_1 = date(2021, 7, 1)
    batch_date_2 = date(2021, 7, 2)

    # Build a staging blob as if batch_date_1 produced an in-progress flight
    prev_pts = [
        RawPoint(ts=1000.0, lat=51.5, lon=-0.1, alt_baro=35000.0,
                 track=90.0, squawk=None, new_leg=False,
                 callsign=None, emitter_category=None),
        RawPoint(ts=1030.0, lat=51.6, lon=-0.2, alt_baro=35100.0,
                 track=91.0, squawk=None, new_leg=False,
                 callsign=None, emitter_category=None),
    ]
    staging_flight = RawFlight(
        icao24="cc1122", callsign=None, icao_type="B738",
        emitter_category=None, points=prev_pts,
    )
    blob = _serialize_staging({"cc1122": staging_flight})
    await conn.execute(
        "INSERT INTO flight_staging (batch_date, staging_data) VALUES ($1, $2)",
        batch_date_1, blob,
    )

    # Tarball for batch_date_2 continues the flight, placed well before the cutoff
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

    count = await run_batch(conn, tmp_path, batch_date_2)
    assert count == 1

    row = await conn.fetchrow("SELECT icao24 FROM flights WHERE icao24 = 'cc1122'")
    assert row is not None


@pytest.mark.asyncio
async def test_run_batch_serialization_roundtrip(
    conn: asyncpg.Connection,
    tmp_path: Path,
) -> None:
    """Batch writes correct WKT geometry and path_tracks to DB."""
    from adsb_server.ingestion.batch import run_batch

    tarball_dir = _make_tarball_dir(tmp_path, ["ff1122"])
    batch_date = date(2021, 8, 1)

    count = await run_batch(conn, tarball_dir, batch_date)
    assert count == 1

    row = await conn.fetchrow(
        "SELECT path_tracks, squawk_runs FROM flights WHERE icao24 = 'ff1122'"
    )
    assert row is not None
    assert isinstance(row["path_tracks"], list)
    runs = json.loads(row["squawk_runs"])
    assert isinstance(runs, list)


@pytest.mark.asyncio
async def test_run_batch_two_batches_finalizes_in_progress(
    conn: asyncpg.Connection,
    tmp_path: Path,
) -> None:
    """
    A flight left in-progress by batch 1 is in staging.
    Batch 2, with a later date, picks it up from staging and finalises it.
    """
    from adsb_server.ingestion.batch import run_batch

    batch_date_1 = date(2021, 9, 1)
    cutoff_ts_1 = 1630454400 + 86399  # end of 2021-09-01

    near_entries: list[list[object]] = [
        [0.0,  51.5, -0.1, 35000.0, 90.0, 0.0, 0, None, None],
        [30.0, 51.6, -0.2, 35100.0, 91.0, 0.0, 0, None, None],
    ]

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

    # Should be in staging after batch 1
    staging_row = await conn.fetchrow(
        "SELECT staging_data FROM flight_staging WHERE batch_date = $1", batch_date_1
    )
    assert staging_row is not None, "in-progress flight should be in staging after batch 1"

    # Batch 2: continuation well before the new cutoff
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
    assert count >= 1

    # The merged flight exists in flights
    row = await conn.fetchrow("SELECT icao24 FROM flights WHERE icao24 = 'bb0001'")
    assert row is not None


@pytest.mark.asyncio
async def test_squawk_reconstructed_from_staging(
    conn: asyncpg.Connection,
    tmp_path: Path,
) -> None:
    """
    Squawk codes from batch 1 are preserved in the staging blob and reconstructed
    when batch 2 loads it, so the finalised squawk_runs span both batches.
    """
    from adsb_server.ingestion.batch import run_batch

    batch_date_1 = date(2021, 10, 1)
    cutoff_ts_1 = 1633046400 + 86399  # end of 2021-10-01

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

    # Staging should contain the squawk
    from adsb_server.ingestion.batch import _deserialize_staging
    staging_row = await conn.fetchrow(
        "SELECT staging_data FROM flight_staging WHERE batch_date = $1", batch_date_1
    )
    assert staging_row is not None
    staging = _deserialize_staging(bytes(staging_row["staging_data"]))
    assert "cc0001" in staging
    squawks_in_staging = [p.squawk for p in staging["cc0001"].points if p.squawk is not None]
    assert "7700" in squawks_in_staging, "7700 squawk should be in staging after batch 1"

    # Batch 2: continuation with different squawk
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
        "SELECT squawk_runs FROM flights WHERE icao24 = 'cc0001'"
    )
    assert row is not None
    runs_2 = json.loads(row["squawk_runs"])
    squawk_codes = {r[1] for r in runs_2}
    assert "7700" in squawk_codes, "7700 from batch 1 should survive into finalised squawk_runs"
    assert "2000" in squawk_codes, "2000 from batch 2 should appear in finalised squawk_runs"


@pytest.mark.asyncio
async def test_orphaned_in_progress_finalized_by_next_batch(
    conn: asyncpg.Connection,
    tmp_path: Path,
) -> None:
    """
    A flight left in staging by batch 1 that does NOT appear in batch 2's tarball
    is finalized as an orphan (gap exceeds threshold relative to batch 2's cutoff).
    """
    from adsb_server.ingestion.batch import run_batch

    batch_date_1 = date(2021, 11, 1)
    cutoff_ts_1 = 1635724800 + 86399  # end of 2021-11-01

    near_entries: list[list[object]] = [
        [0.0,  51.5, -0.1, 35000.0, 90.0, 0.0, 0, None, None],
        [30.0, 51.6, -0.2, 35100.0, 91.0, 0.0, 0, None, None],
    ]

    tmp1 = tmp_path / "batch1"
    tmp1.mkdir()
    raw_buf = io.BytesIO()
    with tarfile.open(fileobj=raw_buf, mode="w:") as tf:
        b = _make_trace_bytes("dd0001", base_ts=float(cutoff_ts_1 - 30), entries=near_entries)
        ti = tarfile.TarInfo(name="traces/dd/trace_full_dd0001.json.gz")
        ti.size = len(b)
        tf.addfile(ti, io.BytesIO(b))
    (tmp1 / "archive.tar.aa").write_bytes(raw_buf.getvalue())

    await run_batch(conn, tmp1, batch_date_1)

    staging_row = await conn.fetchrow(
        "SELECT staging_data FROM flight_staging WHERE batch_date = $1", batch_date_1
    )
    assert staging_row is not None, "dd0001 should be in staging after batch 1"

    # Batch 2: dd0001 absent from tarball
    batch_date_2 = date(2021, 11, 2)
    tmp2 = tmp_path / "batch2"
    tmp2.mkdir()
    tarball_dir = _make_tarball_dir(tmp2, ["ee0002"])

    await run_batch(conn, tarball_dir, batch_date_2)

    row = await conn.fetchrow("SELECT icao24 FROM flights WHERE icao24 = 'dd0001'")
    assert row is not None, "orphaned in-progress should be finalized by next batch"


@pytest.mark.asyncio
async def test_ground_points_preserved_across_batch_boundary(
    conn: asyncpg.Connection,
    tmp_path: Path,
) -> None:
    """
    An in-progress flight with a ground phase stores the ground points in the staging
    blob.  The next batch reconstructs them correctly so the ground gap does not appear
    as a spurious >1h air gap that would wrongly split the flight.
    """
    from adsb_server.ingestion.batch import run_batch

    batch_date_1 = date(2021, 12, 1)
    cutoff_ts_1 = 1638316800 + 86399  # end of 2021-12-01

    # Airborne → ground → airborne; gap between last airborne and re-takeoff is 4000 s
    # (> AIR_GAP_THRESHOLD of 3600 s).  The ground point bridges the gap so split must
    # not fire.
    base = float(cutoff_ts_1 - 4060)
    entries: list[list[object]] = [
        [0.0,    51.5, -0.1, 35000.0, 450.0, 90.0, 0, None, None],  # airborne
        [30.0,   51.6, -0.2, 35100.0, 455.0, 91.0, 0, None, None],  # airborne
        [60.0,   51.6, -0.2, "ground", None,  None, 0, None, None],  # on ground
        [4060.0, 51.7, -0.3, 35200.0, 460.0, 92.0, 0, None, None],  # airborne after takeoff
    ]

    tmp1 = tmp_path / "batch1"
    tmp1.mkdir()
    raw_buf = io.BytesIO()
    with tarfile.open(fileobj=raw_buf, mode="w:") as tf:
        b = _make_trace_bytes("ff0001", base_ts=base, entries=entries)
        ti = tarfile.TarInfo(name="traces/ff/trace_full_ff0001.json.gz")
        ti.size = len(b)
        tf.addfile(ti, io.BytesIO(b))
    (tmp1 / "archive.tar.aa").write_bytes(raw_buf.getvalue())

    await run_batch(conn, tmp1, batch_date_1)

    staging_row = await conn.fetchrow(
        "SELECT staging_data FROM flight_staging WHERE batch_date = $1", batch_date_1
    )
    assert staging_row is not None, "ff0001 should be in staging after batch 1"

    # Verify ground point is in the blob (alt_baro=None)
    from adsb_server.ingestion.batch import _deserialize_staging
    staging = _deserialize_staging(bytes(staging_row["staging_data"]))
    assert "ff0001" in staging
    ground_count = sum(1 for p in staging["ff0001"].points if p.alt_baro is None)
    assert ground_count == 1, "ground point should be preserved in staging blob"

    # Batch 2: ff0001 absent — processed as orphan.  Must produce ONE finalized
    # flight, not two (which would happen if the ground gap were misread as air gap).
    batch_date_2 = date(2021, 12, 2)
    tmp2 = tmp_path / "batch2"
    tmp2.mkdir()
    tarball_dir = _make_tarball_dir(tmp2, ["gg0002"])

    await run_batch(conn, tarball_dir, batch_date_2)

    rows = await conn.fetch(
        "SELECT icao24 FROM flights WHERE icao24 = 'ff0001'"
    )
    assert len(rows) == 1, "ground gap must not produce a spurious split"


@pytest.mark.asyncio
async def test_stale_flights_deleted_on_rerun(
    conn: asyncpg.Connection,
    tmp_path: Path,
) -> None:
    """
    Re-running a batch deletes flights from ingest_batch_date=N that were not
    touched by the re-run, so the resulting DB state matches a fresh run.
    """
    from adsb_server.ingestion.batch import run_batch

    batch_date = date(2021, 1, 15)

    # First run: two aircraft
    tarball_dir = _make_tarball_dir(tmp_path, ["aa1111", "bb2222"])
    await run_batch(conn, tarball_dir, batch_date)

    rows = await conn.fetch(
        "SELECT icao24 FROM flights WHERE ingest_batch_date = $1", batch_date
    )
    assert {r["icao24"] for r in rows} == {"aa1111", "bb2222"}

    # Second run: only one aircraft (simulate the tarball changing)
    tmp2 = tmp_path / "rerun"
    tmp2.mkdir()
    tarball_dir2 = _make_tarball_dir(tmp2, ["aa1111"])
    await run_batch(conn, tarball_dir2, batch_date)

    rows = await conn.fetch(
        "SELECT icao24 FROM flights WHERE ingest_batch_date = $1", batch_date
    )
    assert {r["icao24"] for r in rows} == {"aa1111"}, "bb2222 should have been deleted as stale"


@pytest.mark.asyncio
async def test_staging_serialization_roundtrip() -> None:
    """_serialize_staging / _deserialize_staging are inverses."""
    from adsb_server.ingestion.batch import _deserialize_staging, _serialize_staging
    from adsb_server.ingestion.models import RawFlight, RawPoint

    pts = [
        RawPoint(ts=1000.0, lat=51.5, lon=-0.1, alt_baro=35000.0,
                 track=90.0, squawk="7700", new_leg=False,
                 callsign="BAW1", emitter_category="A3"),
        RawPoint(ts=1060.0, lat=51.6, lon=-0.2, alt_baro=None,
                 track=None, squawk=None, new_leg=False,
                 callsign="BAW1", emitter_category="A3"),
    ]
    flight = RawFlight(
        icao24="aabbcc", callsign="BAW1", icao_type="B738",
        emitter_category="A3", points=pts,
    )
    blob = _serialize_staging({"aabbcc": flight})
    result = _deserialize_staging(blob)

    assert "aabbcc" in result
    rf = result["aabbcc"]
    assert rf.icao24 == "aabbcc"
    assert rf.icao_type == "B738"
    assert len(rf.points) == 2
    assert rf.points[0].ts == 1000.0
    assert rf.points[0].alt_baro == 35000.0
    assert rf.points[0].squawk == "7700"
    assert rf.points[1].alt_baro is None
    assert rf.points[1].squawk is None
