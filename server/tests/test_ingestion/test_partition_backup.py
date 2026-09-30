"""Integration tests for adsb_server.ingestion.partition_backup."""

from __future__ import annotations

import io
import json
from compression import zstd
from datetime import UTC, date, datetime, timedelta
from typing import TYPE_CHECKING

from adsb_server.geometry.wkt import tgeompoint_seqset
from adsb_server.ingestion.partition_backup import (
    DUMP_FORMAT,
    SETTLE_DAYS,
    Partition,
    backup_due_partitions,
    dump_partition,
    dumpable_columns,
    is_settled,
    latest_succeeded_batch,
    list_partitions,
    partitions_due,
    read_manifest,
)

if TYPE_CHECKING:
    from pathlib import Path

    import asyncpg

# 2024-06-03 is a Monday, so it starts a weekly partition: the parent is created
# with p_start_partition 2022-01-03, also a Monday.
_WEEK_START = date(2024, 6, 3)
_PARTITION = "flights_p20240603"
_SETTLE_DATE = _WEEK_START + timedelta(days=7 + SETTLE_DAYS)
_ICAO = "c0ffee"
_START = datetime(2024, 6, 4, 10, 0, tzinfo=UTC)
_END = datetime(2024, 6, 4, 11, 0, tzinfo=UTC)
_T0 = _START.timestamp()
_PATH = tgeompoint_seqset([[(1.0, 51.0, 3000.0, _T0), (1.1, 51.1, 3500.0, _T0 + 3600)]])

_FLIGHT_COLUMNS = "callsign, start_ts, end_ts, asText(path) AS path, alt_max_pressure_ft"


async def _insert_flight(conn: asyncpg.Connection) -> None:
    await conn.execute(
        "INSERT INTO flights (icao24, callsign, start_ts, end_ts, path, ingest_batch_date)"
        " VALUES ($1, $2, $3, $4, $5::tgeompoint, $6)",
        _ICAO,
        "TEST123",
        _START,
        _END,
        _PATH,
        _WEEK_START,
    )


async def _delete_flight(conn: asyncpg.Connection) -> None:
    await conn.execute("DELETE FROM flights WHERE icao24 = $1 AND start_ts = $2", _ICAO, _START)


async def _mark_batch(conn: asyncpg.Connection, batch_date: date, finished_at: datetime) -> None:
    await conn.execute(
        """
        INSERT INTO ingest_batches (batch_date, status, finished_at, attempts)
        VALUES ($1, 'succeeded', $2, 1)
        ON CONFLICT (batch_date) DO UPDATE
            SET status = 'succeeded', finished_at = EXCLUDED.finished_at
        """,
        batch_date,
        finished_at,
    )


async def _clear_batches(conn: asyncpg.Connection, *batch_dates: date) -> None:
    await conn.execute("DELETE FROM ingest_batches WHERE batch_date = ANY($1::date[])", batch_dates)


async def _the_partition(conn: asyncpg.Connection) -> Partition:
    return next(p for p in await list_partitions(conn) if p.name == _PARTITION)


async def test_list_partitions_reports_weekly_bounds(conn: asyncpg.Connection) -> None:
    parts = await list_partitions(conn)
    assert parts, "migrations should have created partitions"
    part = next(p for p in parts if p.name == _PARTITION)
    assert part.start.date() == _WEEK_START
    assert part.end.date() == _WEEK_START + timedelta(days=7)
    assert parts == sorted(parts, key=lambda p: p.start), "oldest first"
    assert all(p.end - p.start == timedelta(days=7) for p in parts)


async def test_dumpable_columns_excludes_generated(conn: asyncpg.Connection) -> None:
    columns = await dumpable_columns(conn)
    assert "icao24" in columns
    assert "path" in columns
    # Generated columns cannot be COPY'd into, so they must not be dumped.
    assert "alt_min_pressure_ft" not in columns
    assert "alt_max_qnh_ft" not in columns


def test_is_settled_waits_for_the_cross_midnight_tail() -> None:
    part = Partition(
        name=_PARTITION,
        start=datetime(2024, 6, 3, tzinfo=UTC),
        end=datetime(2024, 6, 10, tzinfo=UTC),
    )
    assert not is_settled(part, None)
    # The last day inside the partition is 2024-06-09, but a flight crossing
    # into it can still be finalised by a batch a couple of days later.
    assert not is_settled(part, date(2024, 6, 10) + timedelta(days=SETTLE_DAYS - 1))
    assert is_settled(part, date(2024, 6, 10) + timedelta(days=SETTLE_DAYS))
    assert is_settled(part, date(2025, 1, 1))


async def test_dump_partition_writes_dump_and_manifest(
    conn: asyncpg.Connection, tmp_path: Path
) -> None:
    await _insert_flight(conn)
    part = await _the_partition(conn)

    result = await dump_partition(conn, part, tmp_path, level=1)

    assert result.rows == 1
    assert result.path == tmp_path / f"{_PARTITION}.copy.zst"
    assert result.compressed_bytes == result.path.stat().st_size

    manifest = read_manifest(tmp_path, part)
    assert manifest is not None
    assert manifest["format"] == DUMP_FORMAT
    assert manifest["partition"] == _PARTITION
    assert manifest["rows"] == 1
    assert manifest["sha256"] == result.sha256
    assert manifest["range_start"].startswith("2024-06-03")
    assert manifest["alembic_revision"]
    assert "alt_min_pressure_ft" not in manifest["columns"]

    # The dump is COPY text, so the row is legible inside it.
    body = zstd.decompress(result.path.read_bytes()).decode()
    assert _ICAO in body
    assert "TEST123" in body
    assert body.count("\n") == 1


async def test_dump_round_trips_through_copy(conn: asyncpg.Connection, tmp_path: Path) -> None:
    """A dump loads back with COPY and reproduces the row it was taken from."""
    await _insert_flight(conn)
    part = await _the_partition(conn)
    await dump_partition(conn, part, tmp_path, level=1)
    manifest = read_manifest(tmp_path, part)
    assert manifest is not None

    original = await conn.fetchrow(
        f"SELECT {_FLIGHT_COLUMNS} FROM flights WHERE icao24 = $1 AND start_ts = $2",
        _ICAO,
        _START,
    )
    await _delete_flight(conn)

    body = zstd.decompress((tmp_path / f"{_PARTITION}.copy.zst").read_bytes())
    await conn.copy_to_table("flights", source=io.BytesIO(body), columns=manifest["columns"])

    restored = await conn.fetchrow(
        f"SELECT {_FLIGHT_COLUMNS} FROM flights WHERE icao24 = $1 AND start_ts = $2",
        _ICAO,
        _START,
    )
    assert restored is not None
    assert original is not None
    # Including the generated column, recomputed from the restored path.
    assert dict(restored) == dict(original)


async def test_partitions_due_skips_unsettled_and_already_dumped(
    conn: asyncpg.Connection, tmp_path: Path
) -> None:
    await _clear_batches(conn, _SETTLE_DATE)
    await _mark_batch(conn, _SETTLE_DATE, datetime(2024, 6, 14, tzinfo=UTC))
    assert await latest_succeeded_batch(conn) == _SETTLE_DATE

    part = await _the_partition(conn)
    due = await partitions_due(conn, tmp_path)
    assert part in due, "a settled partition with no dump is due"
    # Nothing past the settle frontier is offered.
    assert all(p.end.date() + timedelta(days=SETTLE_DAYS) <= _SETTLE_DATE for p in due)

    await dump_partition(conn, part, tmp_path, level=1)
    assert part not in await partitions_due(conn, tmp_path)
    # --force offers it again regardless.
    assert part in await partitions_due(conn, tmp_path, force=True)


async def test_partitions_due_redumps_after_a_reimport(
    conn: asyncpg.Connection, tmp_path: Path
) -> None:
    await _mark_batch(conn, _SETTLE_DATE, datetime(2024, 6, 14, tzinfo=UTC))
    part = await _the_partition(conn)
    await dump_partition(conn, part, tmp_path, level=1)
    assert part not in await partitions_due(conn, tmp_path)

    # A day inside the partition is re-imported after the dump was taken.
    await _mark_batch(conn, _WEEK_START + timedelta(days=2), datetime.now(UTC))
    assert part in await partitions_due(conn, tmp_path)


async def test_partitions_due_redumps_when_the_dump_is_unusable(
    conn: asyncpg.Connection, tmp_path: Path
) -> None:
    await _mark_batch(conn, _SETTLE_DATE, datetime(2024, 6, 14, tzinfo=UTC))
    part = await _the_partition(conn)
    await dump_partition(conn, part, tmp_path, level=1)

    (tmp_path / f"{_PARTITION}.copy.zst").unlink()
    assert part in await partitions_due(conn, tmp_path), "manifest without a dump file"

    # A manifest written by a format this code does not know is not trusted.
    await dump_partition(conn, part, tmp_path, level=1)
    manifest_path = tmp_path / f"{_PARTITION}.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["format"] = "postgres-copy-text-v99"
    manifest_path.write_text(json.dumps(manifest))
    assert part in await partitions_due(conn, tmp_path)


async def test_shipped_dump_is_not_redumped(conn: asyncpg.Connection, tmp_path: Path) -> None:
    """Once the shipper has moved a dump off to the volume, it stays done."""
    await _mark_batch(conn, _SETTLE_DATE, datetime(2024, 6, 14, tzinfo=UTC))
    part = await _the_partition(conn)
    await dump_partition(conn, part, tmp_path, level=1)

    # What adsb-backup-ship does: move the dump away, stamp the manifest.
    (tmp_path / f"{_PARTITION}.copy.zst").unlink()
    manifest_path = tmp_path / f"{_PARTITION}.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["shipped_to"] = "/mnt/backup/adsb/db/flights/flights_p20240603.copy.zst"
    manifest["shipped_at"] = datetime.now(UTC).isoformat()
    manifest_path.write_text(json.dumps(manifest))

    assert part not in await partitions_due(conn, tmp_path)

    # And if the volume loses the file, verify clears the manifest, which is
    # what brings the partition back around as due.
    manifest_path.unlink()
    assert part in await partitions_due(conn, tmp_path)


async def test_nothing_is_due_without_a_succeeded_batch(
    conn: asyncpg.Connection, tmp_path: Path
) -> None:
    await conn.execute("DELETE FROM ingest_batches")
    assert await latest_succeeded_batch(conn) is None
    assert await partitions_due(conn, tmp_path) == []
    assert await backup_due_partitions(conn, tmp_path) == []
    assert list(tmp_path.iterdir()) == []


async def test_backup_due_partitions_dumps_and_then_finds_nothing(
    conn: asyncpg.Connection, tmp_path: Path
) -> None:
    await conn.execute("DELETE FROM ingest_batches")
    await _insert_flight(conn)
    # Settle only the partition under test: an earlier frontier leaves the rest open.
    await _mark_batch(conn, _SETTLE_DATE, datetime(2024, 6, 14, tzinfo=UTC))

    results = await backup_due_partitions(conn, tmp_path, level=1)

    assert _PARTITION in {r.partition for r in results}
    assert sum(r.rows for r in results) == 1
    assert all((tmp_path / f"{r.partition}.json").exists() for r in results)
    assert await backup_due_partitions(conn, tmp_path, level=1) == []


def test_read_manifest_tolerates_junk(tmp_path: Path) -> None:
    part = Partition(
        name=_PARTITION,
        start=datetime(2024, 6, 3, tzinfo=UTC),
        end=datetime(2024, 6, 10, tzinfo=UTC),
    )
    assert read_manifest(tmp_path, part) is None
    (tmp_path / f"{_PARTITION}.json").write_text("not json{")
    assert read_manifest(tmp_path, part) is None
    (tmp_path / f"{_PARTITION}.json").write_text("[1, 2]")
    assert read_manifest(tmp_path, part) is None
