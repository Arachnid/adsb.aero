"""Off-host backups of the `flights` table, one file per weekly partition.

Why partitions and not days
---------------------------
`flights` is partitioned weekly by `start_ts` (pg_partman, see migration 0001),
and retention drops whole partitions.  Making the backup unit the partition too
means the backup set and the database always agree on what exists: one file per
partition, deleted when the partition is dropped.  A day is not a table here —
dumping one would mean a filtered scan across two partitions, and the union of
day files would not line up with what retention removes.

The cost is recency: a partition is only dumped once it can no longer change
(see `SETTLE_DAYS`), so the most recent ~10 days of flights are not in the
backup set.  That is deliberate — those days are reproducible by re-running
ingestion against the adsb.lol archive, which is where they came from.

What a backup is
----------------
`COPY ... TO STDOUT` in the default text format, zstd-compressed, plus a JSON
manifest beside it.  Text rather than binary because the dumps outlive the
server that wrote them: text survives a PostgreSQL or MobilityDB major-version
change, and can be inspected with `zstdcat`.  Binary is ~2.3x smaller on the
wire but only ~8% smaller after compression — not worth the version coupling.

Generated columns (`alt_min_pressure_ft` and friends) are excluded: PostgreSQL
refuses to COPY into them, and they are recomputed on load.  The column list is
read from the catalogue at dump time and recorded in the manifest, so a restore
does not depend on the schema still matching what the code expects today.

Writes land in a local spool directory; a host-side timer (`adsb-backup-ship`)
moves them to the backup volume.  Ingestion never touches the network
filesystem itself, so an outage there cannot stall or fail a batch — dumps
simply queue in the spool until shipping recovers.

The spool manifests are kept after shipping, stamped with `shipped_to`, and are
what this module consults to decide whether a partition still needs dumping.
If a dump goes missing from the backup volume, `adsb-backup-verify` deletes the
matching spool manifest, which brings the partition back around as due.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import logging
import os
import re
import sys
from compression import zstd
from compression.zstd import CompressionParameter
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any, BinaryIO

import asyncpg

from adsb_server.config import get_settings

logger = logging.getLogger(__name__)

PARENT_TABLE = "flights"

DUMP_SUFFIX = ".copy.zst"
MANIFEST_SUFFIX = ".json"

# Format tag recorded in every manifest.  Bump if the on-disk layout changes in
# a way a reader has to know about; the restore script checks it.
DUMP_FORMAT = "postgres-copy-text-v1"

# A batch for date D writes flights whose start_ts falls as far back as D-2:
# a flight in progress at midnight is carried forward through flight_staging
# and only finalised on the batch that sees it end, which can be two days on.
# So a partition ending at E is not final until the batch for E+2 has run.
# Three days of margin, then, before a partition is considered immutable.
SETTLE_DAYS = 3

_COPY_STATUS_RE = re.compile(r"^COPY (\d+)$")


@dataclass(frozen=True)
class Partition:
    """One weekly child table of `flights`, with its range bounds."""

    name: str
    start: datetime
    end: datetime

    @property
    def dump_name(self) -> str:
        return f"{self.name}{DUMP_SUFFIX}"

    @property
    def manifest_name(self) -> str:
        return f"{self.name}{MANIFEST_SUFFIX}"


@dataclass(frozen=True)
class DumpResult:
    """What `dump_partition` wrote."""

    partition: str
    path: Path
    rows: int
    raw_bytes: int
    compressed_bytes: int
    sha256: str


class _HashingWriter:
    """File wrapper that sha256s and counts everything written through it.

    Hashing the compressed stream (rather than the COPY output) is what lets
    the shipper and the verifier check a file without decompressing it.
    """

    def __init__(self, fh: BinaryIO) -> None:
        self._fh = fh
        self.digest = hashlib.sha256()
        self.bytes_written = 0

    def write(self, data: bytes, /) -> int:
        self.digest.update(data)
        self.bytes_written += len(data)
        return self._fh.write(data)

    def flush(self) -> None:
        self._fh.flush()

    def close(self) -> None:
        """Flush only — the wrapped file belongs to the caller.

        ZstdFile's file protocol requires `close`, but it only closes a file it
        opened itself, so this is here to satisfy the type rather than to run.
        """
        self.flush()


async def list_partitions(conn: asyncpg.Connection) -> list[Partition]:
    """Every bounded child partition of `flights`, oldest first.

    `flights_default` is skipped — partman reports no bounds for it, and it is
    never a backup unit: rows only land there if they fall outside every
    weekly range, which in a healthy database does not happen.  The nightly
    verification checks it is empty rather than dumping it.
    """
    rows = await conn.fetch(
        """
        SELECT c.relname AS name,
               p.child_start_time AS start_time,
               p.child_end_time AS end_time
        FROM pg_class c
        JOIN pg_inherits i ON i.inhrelid = c.oid
        JOIN pg_class parent ON parent.oid = i.inhparent
        JOIN pg_namespace n ON n.oid = parent.relnamespace
        CROSS JOIN LATERAL partman.show_partition_info(
            n.nspname || '.' || c.relname, p_parent_table := $1
        ) AS p
        WHERE parent.relname = $2 AND n.nspname = 'public'
          AND c.relispartition
          AND p.child_start_time IS NOT NULL
        ORDER BY p.child_start_time
        """,
        f"public.{PARENT_TABLE}",
        PARENT_TABLE,
    )
    return [Partition(name=r["name"], start=r["start_time"], end=r["end_time"]) for r in rows]


async def dumpable_columns(conn: asyncpg.Connection, table: str = PARENT_TABLE) -> list[str]:
    """Column names in ordinal order, excluding generated columns.

    Generated columns cannot be COPY'd into, so they are neither dumped nor
    restored — PostgreSQL recomputes them from the stored columns on load.
    """
    rows = await conn.fetch(
        """
        SELECT column_name
        FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = $1 AND is_generated = 'NEVER'
        ORDER BY ordinal_position
        """,
        table,
    )
    return [r["column_name"] for r in rows]


async def latest_succeeded_batch(conn: asyncpg.Connection) -> date | None:
    """The newest batch date that has been ingested successfully."""
    result: date | None = await conn.fetchval(
        "SELECT MAX(batch_date) FROM ingest_batches WHERE status = 'succeeded'"
    )
    return result


async def _last_ingest_touching(conn: asyncpg.Connection, part: Partition) -> datetime | None:
    """When a batch last wrote rows that could land in this partition.

    Used to spot a partition whose dump has gone stale because a day inside it
    was re-imported after the dump was taken.  The window matches the one in
    `SETTLE_DAYS`: a batch for date D can write start_ts values in [D-2, D].
    """
    result: datetime | None = await conn.fetchval(
        """
        SELECT MAX(finished_at) FROM ingest_batches
        WHERE status = 'succeeded'
          AND batch_date >= ($1::date - $3::int) AND batch_date <= ($2::date + $3::int)
        """,
        part.start.date(),
        part.end.date(),
        SETTLE_DAYS,
    )
    return result


def read_manifest(out_dir: Path, part: Partition) -> dict[str, Any] | None:
    """The manifest for an existing dump, or None if there isn't a usable one."""
    path = out_dir / part.manifest_name
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError) as exc:
        logger.debug("No usable manifest at %s: %s", path, exc)
        return None
    return data if isinstance(data, dict) else None


def is_settled(part: Partition, latest_batch: date | None) -> bool:
    """True once no future batch can add rows to this partition."""
    if latest_batch is None:
        return False
    return latest_batch >= part.end.date() + timedelta(days=SETTLE_DAYS)


async def partitions_due(
    conn: asyncpg.Connection,
    out_dir: Path,
    *,
    force: bool = False,
) -> list[Partition]:
    """Settled partitions with no current dump, oldest first.

    A partition is due when it is settled and either has never been dumped, was
    dumped by an older format, or was dumped before the last ingest that could
    have changed it (a re-import of a day inside its range).
    """
    latest_batch = await latest_succeeded_batch(conn)
    due: list[Partition] = []
    for part in await list_partitions(conn):
        if not is_settled(part, latest_batch):
            continue
        if force:
            due.append(part)
            continue
        manifest = read_manifest(out_dir, part)
        if manifest is None or manifest.get("format") != DUMP_FORMAT:
            due.append(part)
            continue
        # The manifest stays in the spool for the life of the partition; it is
        # the local record of what has been backed up.  The dump file itself
        # only stays until the shipper moves it to the backup volume, at which
        # point the shipper stamps `shipped_to` on the manifest.  So a dump is
        # accounted for if it is still here, or if it is known to be there.
        if not (out_dir / part.dump_name).exists() and not manifest.get("shipped_to"):
            due.append(part)
            continue
        dumped_at = _parse_ts(manifest.get("dumped_at"))
        changed_at = await _last_ingest_touching(conn, part)
        if dumped_at is None or (changed_at is not None and changed_at > dumped_at):
            logger.info("Dump of %s is stale (re-import since) — redumping", part.name)
            due.append(part)
    return due


def _parse_ts(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


async def _schema_identity(conn: asyncpg.Connection) -> dict[str, Any]:
    """Version and migration state, recorded so a restore knows what it holds."""
    return {
        "server_version": await conn.fetchval("SHOW server_version"),
        "mobilitydb_version": await conn.fetchval(
            "SELECT extversion FROM pg_extension WHERE extname = 'mobilitydb'"
        ),
        "postgis_version": await conn.fetchval(
            "SELECT extversion FROM pg_extension WHERE extname = 'postgis'"
        ),
        "alembic_revision": await conn.fetchval("SELECT version_num FROM alembic_version"),
    }


async def dump_partition(
    conn: asyncpg.Connection,
    part: Partition,
    out_dir: Path,
    *,
    level: int = 19,
    workers: int = 4,
) -> DumpResult:
    """Dump one partition to `out_dir`, atomically, with a manifest beside it.

    The dump is written to a temporary name and renamed into place only after
    the manifest is complete, so a crash mid-dump cannot leave a truncated file
    that later looks like a valid backup.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    columns = await dumpable_columns(conn)
    col_sql = ", ".join(f'"{c}"' for c in columns)

    dump_path = out_dir / part.dump_name
    tmp_path = out_dir / f".{part.dump_name}.tmp"
    raw_bytes = 0

    started = datetime.now(UTC)
    with tmp_path.open("wb") as raw_fh:
        hashing = _HashingWriter(raw_fh)
        # ZstdFile writes through the hasher, so the digest covers exactly the
        # bytes that end up on disk.  Options rather than `level=` because the
        # two cannot be combined, and the worker count is what makes the high
        # compression levels affordable.
        # Annotated as plain ints: CompressionParameter is an IntEnum, and
        # Mapping is invariant in its key type, so dict[CompressionParameter, int]
        # does not satisfy the stub's Mapping[int, int].
        options: dict[int, int] = {
            CompressionParameter.compression_level: level,
            CompressionParameter.nb_workers: workers,
        }
        with zstd.ZstdFile(hashing, "wb", options=options) as zf:

            async def write(data: bytes) -> None:
                nonlocal raw_bytes
                raw_bytes += len(data)
                # Compression is CPU-bound C code that drops the GIL; running
                # it off the event loop keeps this connection responsive.
                await asyncio.to_thread(zf.write, data)

            status = await conn.copy_from_query(
                # Identifiers come from the catalogue, not from user input.
                f'SELECT {col_sql} FROM ONLY "{part.name}"',
                output=write,
            )
        raw_fh.flush()
        os.fsync(raw_fh.fileno())

    rows = _rows_from_status(status)
    result = DumpResult(
        partition=part.name,
        path=dump_path,
        rows=rows,
        raw_bytes=raw_bytes,
        compressed_bytes=hashing.bytes_written,
        sha256=hashing.digest.hexdigest(),
    )

    manifest: dict[str, Any] = {
        "format": DUMP_FORMAT,
        "table": PARENT_TABLE,
        "partition": part.name,
        "range_start": part.start.isoformat(),
        "range_end": part.end.isoformat(),
        "columns": columns,
        "rows": rows,
        "raw_bytes": raw_bytes,
        "compressed_bytes": result.compressed_bytes,
        "sha256": result.sha256,
        "zstd_level": level,
        "zstd_workers": workers,
        "dump_file": part.dump_name,
        "dumped_at": started.isoformat(),
        "duration_seconds": round((datetime.now(UTC) - started).total_seconds(), 1),
        **await _schema_identity(conn),
    }

    tmp_path.replace(dump_path)
    _write_json_atomic(out_dir / part.manifest_name, manifest)
    _fsync_dir(out_dir)

    logger.info(
        "Dumped %s: %d rows, %.1f MiB raw -> %.1f MiB compressed (%.1fx)",
        part.name,
        rows,
        raw_bytes / 1048576,
        result.compressed_bytes / 1048576,
        raw_bytes / result.compressed_bytes if result.compressed_bytes else 0,
    )
    return result


def _rows_from_status(status: str) -> int:
    """Row count out of a `COPY 12345` command tag."""
    match = _COPY_STATUS_RE.match(status.strip())
    return int(match.group(1)) if match else 0


def _write_json_atomic(path: Path, data: dict[str, Any]) -> None:
    tmp = path.with_name(f".{path.name}.tmp")
    with tmp.open("w") as fh:
        json.dump(data, fh, indent=2, sort_keys=True)
        fh.write("\n")
        fh.flush()
        os.fsync(fh.fileno())
    tmp.replace(path)


def _fsync_dir(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


async def backup_due_partitions(
    conn: asyncpg.Connection,
    out_dir: Path,
    *,
    level: int = 19,
    workers: int = 4,
    force: bool = False,
) -> list[DumpResult]:
    """Dump every partition that needs it.  Returns what was written.

    Called as the last step of each batch, and by the `backup-flights` command
    to fill gaps (after a spool outage, or to seed a fresh backup volume).
    """
    due = await partitions_due(conn, out_dir, force=force)
    if not due:
        logger.info("No partitions due for backup")
        return []
    logger.info("Backing up %d partition(s): %s", len(due), ", ".join(p.name for p in due))
    return [await dump_partition(conn, part, out_dir, level=level, workers=workers) for part in due]


async def _run(args: argparse.Namespace) -> int:
    settings = get_settings()
    out_dir = args.out_dir or settings.flight_backup_dir
    if out_dir is None:
        print(
            "No output directory: pass --out-dir or set FLIGHT_BACKUP_DIR.",
            file=sys.stderr,
        )
        return 2

    conn: asyncpg.Connection[asyncpg.Record] = await asyncpg.connect(settings.asyncpg_dsn)
    try:
        if args.list:
            latest = await latest_succeeded_batch(conn)
            for part in await list_partitions(conn):
                manifest = read_manifest(out_dir, part)
                state = "settled" if is_settled(part, latest) else "open"
                have = f"{manifest['rows']} rows" if manifest else "no dump"
                print(f"{part.name}  {part.start.date()}..{part.end.date()}  {state:8} {have}")
            return 0

        if args.partitions:
            wanted = set(args.partitions)
            parts = [p for p in await list_partitions(conn) if p.name in wanted]
            missing = wanted - {p.name for p in parts}
            if missing:
                print(f"No such partition(s): {', '.join(sorted(missing))}", file=sys.stderr)
                return 2
            results = [
                await dump_partition(
                    conn,
                    p,
                    out_dir,
                    level=settings.flight_backup_zstd_level,
                    workers=settings.flight_backup_zstd_workers,
                )
                for p in parts
            ]
        else:
            results = await backup_due_partitions(
                conn,
                out_dir,
                level=settings.flight_backup_zstd_level,
                workers=settings.flight_backup_zstd_workers,
                force=args.force,
            )

        total = sum(r.compressed_bytes for r in results)
        print(
            f"Wrote {len(results)} dump(s), {total / 1048576:.1f} MiB total, to {out_dir}",
            file=sys.stderr,
        )
        return 0
    finally:
        await conn.close()


def main() -> None:
    """`backup-flights` — dump flights partitions that are due for backup.

    Ingestion calls `backup_due_partitions` itself after each batch; this
    command is for filling gaps: seeding a new backup volume, catching up after
    the spool was full, or re-dumping a partition on demand.
    """
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=sys.stderr,
    )
    settings = get_settings()
    settings.init_sentry()

    parser = argparse.ArgumentParser(
        prog="backup-flights",
        description="Dump settled weekly partitions of the flights table.",
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=None,
        help="Where to write dumps (default: FLIGHT_BACKUP_DIR).",
    )
    parser.add_argument(
        "--partitions",
        nargs="+",
        metavar="NAME",
        help="Dump these partitions by name, settled or not, current dump or not.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-dump every settled partition, even one with a current dump.",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="Show every partition, whether it is settled, and what is backed up.",
    )
    args = parser.parse_args()
    sys.exit(asyncio.run(_run(args)))


if __name__ == "__main__":
    main()
