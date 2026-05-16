"""Integration tests for the batch ingestion pipeline.

These tests use the real database (requires Docker).
"""

from __future__ import annotations

import gzip
import io
import json
import re
import tarfile
from datetime import UTC, date, datetime
from datetime import time as dt_time
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from pathlib import Path

    import asyncpg


_TTEXT_RE = re.compile(r"([^@,\[\]]+)@([^,\[\]]+)")


def _parse_squawk_seq(text: str | None) -> list[tuple[float, str]]:
    """Parse a MobilityDB ttext WKT string into (unix_ts, squawk_code) pairs."""
    if not text:
        return []
    runs: list[tuple[float, str]] = []
    for m in _TTEXT_RE.finditer(text):
        code = m.group(1).strip().strip('"')
        ts_str = m.group(2).strip()
        if ts_str.endswith("+00"):
            ts_str += ":00"
        runs.append((datetime.fromisoformat(ts_str).replace(tzinfo=UTC).timestamp(), code))
    return runs


def _make_trace_bytes(
    icao: str,
    base_ts: float = 1609275898.0,
    entries: list[list[object]] | None = None,
) -> bytes:
    """Build a gzip-compressed trace JSON bytes."""
    if entries is None:
        entries = [
            [
                0.0,
                51.5,
                -0.1,
                35000.0,
                450.0,
                90.0,
                0,
                None,
                {"flight": "BAW100", "squawk": "1234"},
            ],
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
        RawPoint(
            ts=1000.0,
            lat=51.5,
            lon=-0.1,
            alt_baro=35000.0,
            track=90.0,
            squawk=None,
            new_leg=False,
            callsign=None,
            emitter_category=None,
        ),
        RawPoint(
            ts=1030.0,
            lat=51.6,
            lon=-0.2,
            alt_baro=35100.0,
            track=91.0,
            squawk=None,
            new_leg=False,
            callsign=None,
            emitter_category=None,
        ),
    ]
    staging_flight = RawFlight(
        icao24="cc1122",
        callsign=None,
        icao_type="B738",
        emitter_category=None,
        points=prev_pts,
    )
    blob = _serialize_staging({"cc1122": staging_flight})
    await conn.execute(
        "INSERT INTO flight_staging (batch_date, staging_data) VALUES ($1, $2)",
        batch_date_1,
        blob,
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
    """Batch writes correct tgeompoint path and tint path_tracks to DB."""
    from adsb_server.ingestion.batch import run_batch

    tarball_dir = _make_tarball_dir(tmp_path, ["ff1122"])
    batch_date = date(2021, 8, 1)

    count = await run_batch(conn, tarball_dir, batch_date)
    assert count == 1

    row = await conn.fetchrow(
        "SELECT asText(path_tracks) AS pt, asText(squawk_seq) AS squawk_seq_text"
        " FROM flights WHERE icao24 = 'ff1122'"
    )
    assert row is not None
    # tint text is a seqset: starts with '{['
    assert row["pt"].startswith("{[")
    runs = _parse_squawk_seq(row["squawk_seq_text"])
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
        [0.0, 51.5, -0.1, 35000.0, 90.0, 0.0, 0, None, None],
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
        [0.0, 51.7, -0.3, 35200.0, 92.0, 0.0, 0, None, None],
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
        [0.0, 51.5, -0.1, 35000.0, 90.0, 0.0, 0, None, {"squawk": "7700"}],
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
        [0.0, 51.7, -0.3, 35200.0, 92.0, 0.0, 0, None, {"squawk": "2000"}],
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
        "SELECT asText(squawk_seq) AS squawk_seq_text FROM flights WHERE icao24 = 'cc0001'"
    )
    assert row is not None
    runs_2 = _parse_squawk_seq(row["squawk_seq_text"])
    squawk_codes = {r[1] for r in runs_2}
    assert "7700" in squawk_codes, "7700 from batch 1 should survive into finalised squawk_seq"
    assert "2000" in squawk_codes, "2000 from batch 2 should appear in finalised squawk_seq"


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
        [0.0, 51.5, -0.1, 35000.0, 90.0, 0.0, 0, None, None],
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
        [0.0, 51.5, -0.1, 35000.0, 450.0, 90.0, 0, None, None],  # airborne
        [30.0, 51.6, -0.2, 35100.0, 455.0, 91.0, 0, None, None],  # airborne
        [60.0, 51.6, -0.2, "ground", None, None, 0, None, None],  # on ground
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

    rows = await conn.fetch("SELECT icao24 FROM flights WHERE icao24 = 'ff0001'")
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

    rows = await conn.fetch("SELECT icao24 FROM flights WHERE ingest_batch_date = $1", batch_date)
    assert {r["icao24"] for r in rows} == {"aa1111", "bb2222"}

    # Second run: only one aircraft (simulate the tarball changing)
    tmp2 = tmp_path / "rerun"
    tmp2.mkdir()
    tarball_dir2 = _make_tarball_dir(tmp2, ["aa1111"])
    await run_batch(conn, tarball_dir2, batch_date)

    rows = await conn.fetch("SELECT icao24 FROM flights WHERE ingest_batch_date = $1", batch_date)
    assert {r["icao24"] for r in rows} == {"aa1111"}, "bb2222 should have been deleted as stale"


@pytest.mark.asyncio
async def test_staging_serialization_roundtrip() -> None:
    """_serialize_staging / _deserialize_staging are inverses."""
    from adsb_server.ingestion.batch import _deserialize_staging, _serialize_staging
    from adsb_server.ingestion.models import RawFlight, RawPoint

    pts = [
        RawPoint(
            ts=1000.0,
            lat=51.5,
            lon=-0.1,
            alt_baro=35000.0,
            track=90.0,
            squawk="7700",
            new_leg=False,
            callsign="BAW1",
            emitter_category="A3",
        ),
        RawPoint(
            ts=1060.0,
            lat=51.6,
            lon=-0.2,
            alt_baro=None,
            track=None,
            squawk=None,
            new_leg=False,
            callsign="BAW1",
            emitter_category="A3",
        ),
    ]
    flight = RawFlight(
        icao24="aabbcc",
        callsign="BAW1",
        icao_type="B738",
        emitter_category="A3",
        points=pts,
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


@pytest.mark.asyncio
async def test_cleanup_old_herbie_cache(tmp_path: Path) -> None:
    """
    _cleanup_old_herbie_cache deletes GFS directories older than batch_date
    and leaves the current day's directory intact.
    """
    from adsb_server.ingestion.batch import _cleanup_old_herbie_cache

    batch_date = date(2024, 3, 15)

    old1 = tmp_path / "gfs.20240313"
    old2 = tmp_path / "gfs.20240314"
    current = tmp_path / "gfs.20240315"
    future = tmp_path / "gfs.20240316"
    unrelated = tmp_path / "something_else"

    for d in (old1, old2, current, future, unrelated):
        d.mkdir()
        (d / "data.grib2").write_bytes(b"x")

    _cleanup_old_herbie_cache(tmp_path, batch_date)

    assert not old1.exists(), "gfs.20240313 should be deleted"
    assert not old2.exists(), "gfs.20240314 should be deleted"
    assert current.exists(), "gfs.20240315 (current day) should be kept"
    assert future.exists(), "gfs.20240316 (future) should be kept"
    assert unrelated.exists(), "non-GFS directory should be kept"


@pytest.mark.asyncio
async def test_run_batch_cleans_old_herbie_cache(
    conn: asyncpg.Connection,
    tmp_path: Path,
) -> None:
    """After a successful run_batch, old herbie cache directories are deleted."""
    from adsb_server.ingestion.batch import run_batch

    herbie_dir = tmp_path / "herbie"
    herbie_dir.mkdir()
    old_cache = herbie_dir / "gfs.20210101"
    old_cache.mkdir()
    (old_cache / "data.grib2").write_bytes(b"x")

    batch_date = date(2021, 3, 1)
    tarball_dir = _make_tarball_dir(tmp_path, ["aabbcc"])

    await run_batch(
        conn, tarball_dir, batch_date, herbie_cache_dir=herbie_dir, keep_herbie_cache=False
    )

    assert not old_cache.exists(), "old herbie cache dir should be deleted after successful batch"


@pytest.mark.asyncio
async def test_run_batch_keeps_herbie_cache_when_flag_set(
    conn: asyncpg.Connection,
    tmp_path: Path,
) -> None:
    """When keep_herbie_cache=True, old herbie cache directories are preserved."""
    from adsb_server.ingestion.batch import run_batch

    herbie_dir = tmp_path / "herbie"
    herbie_dir.mkdir()
    old_cache = herbie_dir / "gfs.20210101"
    old_cache.mkdir()
    (old_cache / "data.grib2").write_bytes(b"x")

    batch_date = date(2021, 3, 1)
    tarball_dir = _make_tarball_dir(tmp_path, ["aabbcc"])

    await run_batch(
        conn, tarball_dir, batch_date, herbie_cache_dir=herbie_dir, keep_herbie_cache=True
    )

    assert old_cache.exists(), "old herbie cache dir should be kept when flag is set"


# ---------------------------------------------------------------------------
# Unit tests: _process_and_correct (called directly, not via process pool)
# ---------------------------------------------------------------------------


class TestProcessAndCorrect:
    """Call _process_and_correct in the main process so coverage can track it."""

    def _make_state(
        self,
        staging: dict | None = None,
        cutoff_ts: float | None = None,
    ):
        from unittest.mock import MagicMock

        import adsb_server.ingestion.batch as batch_mod

        batch_date = date(2021, 1, 1)
        ct = (
            cutoff_ts
            if cutoff_ts is not None
            else datetime.combine(batch_date, dt_time.max, tzinfo=UTC).timestamp()
        )
        return batch_mod._WorkerState(
            correction_interp=MagicMock(),
            t_min=0.0,
            t_max=1e12,
            batch_date=batch_date,
            cutoff_ts=ct,
            staging=staging or {},
        )

    def test_valid_trace_produces_finalized_flight(self, monkeypatch):
        import adsb_server.ingestion.batch as batch_mod

        monkeypatch.setattr(batch_mod, "_worker_state", self._make_state())
        monkeypatch.setattr(batch_mod, "compute_correction_series", lambda *a, **kw: None)

        raw = _make_trace_bytes("aabbcc")  # Dec 2020 timestamps, well before Jan 2021 cutoff
        params_list, in_progress = batch_mod._process_and_correct(
            ("traces/aa/trace_full_aabbcc.json.gz", raw)
        )
        assert len(params_list) == 1
        assert params_list[0][0] == "aabbcc"  # icao24
        assert in_progress is None

    def test_in_progress_returned_when_points_near_cutoff(self, monkeypatch):
        import adsb_server.ingestion.batch as batch_mod

        cutoff_ts = datetime(2021, 1, 1, 23, 59, 59, tzinfo=UTC).timestamp()
        monkeypatch.setattr(batch_mod, "_worker_state", self._make_state(cutoff_ts=cutoff_ts))
        monkeypatch.setattr(batch_mod, "compute_correction_series", lambda *a, **kw: None)

        raw = _make_trace_bytes(
            "aabbcc",
            base_ts=cutoff_ts - 30,
            entries=[
                [0.0, 51.5, -0.1, 35000.0, 450.0, 90.0, 0, None, None],
                [30.0, 51.6, -0.2, 35100.0, 455.0, 91.0, 0, None, None],
            ],
        )
        _params_list, in_progress = batch_mod._process_and_correct(
            ("traces/aa/trace_full_aabbcc.json.gz", raw)
        )
        assert in_progress is not None
        assert in_progress.icao24 == "aabbcc"

    def test_orphan_with_staging_produces_flight(self, monkeypatch):
        import adsb_server.ingestion.batch as batch_mod
        from adsb_server.ingestion.models import RawFlight, RawPoint

        pts = [
            RawPoint(
                ts=1000.0,
                lat=51.5,
                lon=-0.1,
                alt_baro=35000.0,
                track=90.0,
                squawk=None,
                new_leg=False,
                callsign=None,
                emitter_category=None,
            ),
            RawPoint(
                ts=1060.0,
                lat=51.6,
                lon=-0.2,
                alt_baro=35100.0,
                track=91.0,
                squawk=None,
                new_leg=False,
                callsign=None,
                emitter_category=None,
            ),
        ]
        staging_flight = RawFlight(
            icao24="aabbcc",
            callsign=None,
            icao_type="B738",
            emitter_category=None,
            points=pts,
        )
        monkeypatch.setattr(
            batch_mod, "_worker_state", self._make_state(staging={"aabbcc": staging_flight})
        )
        monkeypatch.setattr(batch_mod, "compute_correction_series", lambda *a, **kw: None)

        params_list, _in_progress = batch_mod._process_and_correct(("aabbcc", None))
        assert isinstance(params_list, list)
        assert len(params_list) >= 1

    def test_icao_type_inherited_from_staging_for_orphan(self, monkeypatch):
        """Orphan with no trace bytes gets icao_type from its staging entry."""
        import adsb_server.ingestion.batch as batch_mod
        from adsb_server.ingestion.models import RawFlight, RawPoint

        pts = [
            RawPoint(
                ts=1000.0,
                lat=51.5,
                lon=-0.1,
                alt_baro=35000.0,
                track=90.0,
                squawk=None,
                new_leg=False,
                callsign=None,
                emitter_category=None,
            ),
            RawPoint(
                ts=1060.0,
                lat=51.6,
                lon=-0.2,
                alt_baro=35100.0,
                track=91.0,
                squawk=None,
                new_leg=False,
                callsign=None,
                emitter_category=None,
            ),
        ]
        staging_flight = RawFlight(
            icao24="aabbcc",
            callsign=None,
            icao_type="A320",
            emitter_category=None,
            points=pts,
        )
        monkeypatch.setattr(
            batch_mod, "_worker_state", self._make_state(staging={"aabbcc": staging_flight})
        )
        monkeypatch.setattr(batch_mod, "compute_correction_series", lambda *a, **kw: None)

        params_list, _ = batch_mod._process_and_correct(("aabbcc", None))
        assert params_list
        assert params_list[0][2] == "A320"  # icao_type at index 2

    def test_parse_failure_returns_empty(self, monkeypatch):
        import adsb_server.ingestion.batch as batch_mod

        monkeypatch.setattr(batch_mod, "_worker_state", self._make_state())

        params_list, in_progress = batch_mod._process_and_correct(
            ("traces/aa/trace_full_aabbcc.json.gz", b"not valid gzip or json")
        )
        assert params_list == []
        assert in_progress is None

    def test_orphan_not_in_staging_returns_empty(self, monkeypatch):
        import adsb_server.ingestion.batch as batch_mod

        monkeypatch.setattr(batch_mod, "_worker_state", self._make_state(staging={}))

        params_list, in_progress = batch_mod._process_and_correct(("unknown_icao24", None))
        assert params_list == []
        assert in_progress is None

    def test_correction_series_wkt_included_in_params(self, monkeypatch):
        """When compute_correction_series returns data, alt_correction_ft is a WKT string."""
        import adsb_server.ingestion.batch as batch_mod

        monkeypatch.setattr(batch_mod, "_worker_state", self._make_state())
        # Return a real (corr_ts, corr_vals) tuple instead of None
        monkeypatch.setattr(
            batch_mod,
            "compute_correction_series",
            lambda *a, **kw: ([1609275898.0, 1609275928.0], [100.0, 102.0]),
        )

        raw = _make_trace_bytes("aabbcc")
        params_list, _ = batch_mod._process_and_correct(
            ("traces/aa/trace_full_aabbcc.json.gz", raw)
        )
        assert params_list
        assert params_list[0][9] is not None  # alt_correction_ft at index 9


# ---------------------------------------------------------------------------
# Unit tests: _log_progress
# ---------------------------------------------------------------------------


class TestLogProgress:
    def test_emits_when_interval_exceeded(self, monkeypatch):
        import adsb_server.ingestion.batch as batch_mod

        monkeypatch.setattr(batch_mod, "_LOG_INTERVAL_SECS", 0.0)
        last = 0.0
        result = batch_mod._log_progress(500, 100, 0.0, last)
        assert result > last  # last_log_time was updated

    def test_suppressed_when_too_soon(self):
        import time

        import adsb_server.ingestion.batch as batch_mod

        now = time.monotonic()
        result = batch_mod._log_progress(500, 100, now - 10, now)
        assert result == now  # unchanged — not enough time has passed


# ---------------------------------------------------------------------------
# Additional _cleanup_old_herbie_cache edge cases
# ---------------------------------------------------------------------------


class TestCleanupHerbieCacheEdgeCases:
    def test_skips_non_directory_entries(self, tmp_path):
        from adsb_server.ingestion.batch import _cleanup_old_herbie_cache

        (tmp_path / "loose_file.bin").write_bytes(b"data")
        old_dir = tmp_path / "gfs.20240101"
        old_dir.mkdir()

        _cleanup_old_herbie_cache(tmp_path, date(2024, 3, 15))

        assert (tmp_path / "loose_file.bin").exists()
        assert not old_dir.exists()

    def test_skips_dir_with_impossible_date(self, tmp_path):
        from adsb_server.ingestion.batch import _cleanup_old_herbie_cache

        invalid = tmp_path / "gfs.20241399"  # month 13 → ValueError
        invalid.mkdir()

        _cleanup_old_herbie_cache(tmp_path, date(2024, 3, 15))

        assert invalid.exists()

    def test_handles_os_error_on_iterdir(self, tmp_path, monkeypatch):
        from pathlib import Path

        from adsb_server.ingestion.batch import _cleanup_old_herbie_cache

        def _raise(self):
            raise OSError("Permission denied")

        monkeypatch.setattr(Path, "iterdir", _raise)
        _cleanup_old_herbie_cache(tmp_path, date(2024, 3, 15))  # must not raise


# ---------------------------------------------------------------------------
# Integration test: MSLP unavailable
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_batch_raises_when_mslp_unavailable(
    conn: asyncpg.Connection,
    tmp_path: Path,
) -> None:
    """run_batch raises RuntimeError when fetch_mslp_for_batch returns None."""
    from unittest.mock import AsyncMock, patch

    from adsb_server.ingestion.batch import run_batch

    tarball_dir = _make_tarball_dir(tmp_path, ["aabbcc"])
    batch_date = date(2021, 4, 1)

    with (
        patch(
            "adsb_server.ingestion.batch.fetch_mslp_for_batch",
            new_callable=AsyncMock,
            return_value=None,
        ),
        pytest.raises(RuntimeError, match="MSLP data unavailable"),
    ):
        await run_batch(conn, tarball_dir, batch_date)
