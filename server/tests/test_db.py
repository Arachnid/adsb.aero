"""
Integration tests for the database schema and connection pool.
Requires Docker (testcontainers spins up adsb-postgres:test with pg_partman).
"""

import asyncpg
import pytest

# ---------------------------------------------------------------------------
# Schema verification
# ---------------------------------------------------------------------------

EXPECTED_TABLES = {
    "flights",
    "ingest_batches",
}


@pytest.mark.asyncio
async def test_expected_tables_exist(conn: asyncpg.Connection) -> None:  # type: ignore[type-arg]
    rows = await conn.fetch(
        """
        SELECT tablename FROM pg_tables
        WHERE schemaname = 'public'
          AND tablename = ANY($1)
        """,
        list(EXPECTED_TABLES),
    )
    found = {r["tablename"] for r in rows}
    assert found == EXPECTED_TABLES


@pytest.mark.asyncio
async def test_postgis_extension_loaded(conn: asyncpg.Connection) -> None:  # type: ignore[type-arg]
    row = await conn.fetchrow("SELECT PostGIS_Lib_Version()")
    assert row is not None
    version: str = row[0]
    major = int(version.split(".")[0])
    assert major >= 3


@pytest.mark.asyncio
async def test_mobilitydb_extension_loaded(conn: asyncpg.Connection) -> None:  # type: ignore[type-arg]
    row = await conn.fetchrow("SELECT mobilitydb_version()")
    assert row is not None
    assert row[0] is not None


@pytest.mark.asyncio
async def test_flights_partitioned(conn: asyncpg.Connection) -> None:  # type: ignore[type-arg]
    row = await conn.fetchrow(
        """
        SELECT partstrat FROM pg_partitioned_table pt
        JOIN pg_class c ON c.oid = pt.partrelid
        WHERE c.relname = 'flights'
        """
    )
    assert row is not None, "flights is not a partitioned table"
    assert row["partstrat"] in (b"r", "r"), "flights should use RANGE partitioning"


@pytest.mark.asyncio
async def test_flights_monthly_partitions_exist(conn: asyncpg.Connection) -> None:  # type: ignore[type-arg]
    rows = await conn.fetch(
        """
        SELECT c.relname FROM pg_inherits i
        JOIN pg_class c ON c.oid = i.inhrelid
        JOIN pg_class p ON p.oid = i.inhparent
        WHERE p.relname = 'flights'
          AND c.relname LIKE 'flights_p20%'
        """
    )
    partition_names = {r["relname"] for r in rows}
    # Historical partitions exist back to p_start_partition (pg_partman names: flights_pYYYYMMDD)
    for month in ["flights_p20220101", "flights_p20220601", "flights_p20230101"]:
        assert month in partition_names, f"Missing partition {month}"
    # Should have substantial coverage (2022-present + 1 premake)
    assert len(partition_names) >= 30, f"Expected ≥30 partitions, got {len(partition_names)}"


@pytest.mark.asyncio
async def test_flights_path_gist_index_exists(conn: asyncpg.Connection) -> None:  # type: ignore[type-arg]
    row = await conn.fetchrow(
        """
        SELECT indexname FROM pg_indexes
        WHERE tablename = 'flights' AND indexname = 'flights_path'
        """
    )
    assert row is not None, "MobilityDB STBOX GiST index flights_path not found"


@pytest.mark.asyncio
async def test_flights_altitude_expression_indexes_exist(
    conn: asyncpg.Connection,  # type: ignore[type-arg]
) -> None:
    rows = await conn.fetch(
        """
        SELECT indexname FROM pg_indexes
        WHERE tablename = 'flights'
          AND indexname IN ('flights_alt_min', 'flights_alt_max')
        """
    )
    found = {r["indexname"] for r in rows}
    assert found == {"flights_alt_min", "flights_alt_max"}


@pytest.mark.asyncio
async def test_partman_manages_flights(conn: asyncpg.Connection) -> None:  # type: ignore[type-arg]
    row = await conn.fetchrow(
        """
        SELECT control, partition_interval
        FROM partman.part_config
        WHERE parent_table = 'public.flights'
        """
    )
    assert row is not None, "pg_partman has no config entry for public.flights"
    assert row["control"] == "start_ts"
    assert row["partition_interval"] == "1 mon"


# ---------------------------------------------------------------------------
# Pool and round-trip
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pool_round_trip(conn: asyncpg.Connection) -> None:  # type: ignore[type-arg]
    row = await conn.fetchrow("SELECT 1 + 1 AS result")
    assert row is not None
    assert row["result"] == 2


@pytest.mark.asyncio
async def test_insert_and_query_ingest_batch(conn: asyncpg.Connection) -> None:  # type: ignore[type-arg]
    await conn.execute(
        """
        INSERT INTO ingest_batches (batch_date, status)
        VALUES ('2025-04-15', 'pending')
        """
    )
    row = await conn.fetchrow(
        "SELECT status, attempts FROM ingest_batches WHERE batch_date = '2025-04-15'"
    )
    assert row is not None
    assert row["status"] == "pending"
    assert row["attempts"] == 0


@pytest.mark.asyncio
async def test_pool_module(migrated_db: dict[str, str]) -> None:
    from adsb_server.db.pool import acquire, create_pool

    dsn = (
        f"postgresql://{migrated_db['POSTGRES_USER']}:{migrated_db['POSTGRES_PASSWORD']}"
        f"@{migrated_db['POSTGRES_HOST']}:{migrated_db['POSTGRES_PORT']}"
        f"/{migrated_db['POSTGRES_DB']}"
    )
    pool = await create_pool(dsn, min_size=1, max_size=2)
    try:
        async with acquire(pool) as c:
            row = await c.fetchrow("SELECT PostGIS_Lib_Version() AS v")
            assert row is not None
            assert row["v"]
    finally:
        await pool.close()
