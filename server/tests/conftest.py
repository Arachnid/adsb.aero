"""
Session-scoped fixtures that spin up a real PostGIS+pg_partman container,
apply all Alembic migrations, and expose an asyncpg connection pool for tests.

Each test that needs DB isolation should use the `conn` fixture, which
wraps the test in a transaction that is rolled back on teardown.
"""

import os
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING

import asyncpg
import pytest
from testcontainers.postgres import PostgresContainer

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

ADSB_POSTGRES_IMAGE = "adsb-postgres:test"
INFRA_DIR = Path(__file__).parent.parent.parent / "infra"
SERVER_DIR = Path(__file__).parent.parent


def _build_postgres_image() -> None:
    result = subprocess.run(
        ["docker", "build", "-t", ADSB_POSTGRES_IMAGE, "./postgres"],
        cwd=INFRA_DIR,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"Failed to build {ADSB_POSTGRES_IMAGE}:\n{result.stdout}\n{result.stderr}"
        )


@pytest.fixture(scope="session")
def pg_container() -> PostgresContainer:
    _build_postgres_image()
    with PostgresContainer(ADSB_POSTGRES_IMAGE) as container:
        yield container  # type: ignore[misc]


@pytest.fixture(scope="session")
def db_settings(pg_container: PostgresContainer) -> dict[str, str]:
    return {
        "POSTGRES_HOST": pg_container.get_container_host_ip(),
        "POSTGRES_PORT": str(pg_container.get_exposed_port(5432)),
        "POSTGRES_DB": pg_container.dbname,
        "POSTGRES_USER": pg_container.username,
        "POSTGRES_PASSWORD": pg_container.password,
    }


@pytest.fixture(scope="session")
def migrated_db(db_settings: dict[str, str]) -> dict[str, str]:
    """Run Alembic migrations against the test container once per session."""
    env = {**os.environ, **db_settings}
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=SERVER_DIR,
        env=env,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"Alembic migration failed:\nstdout: {result.stdout}\nstderr: {result.stderr}"
        )
    return db_settings


@pytest.fixture(scope="session")
async def pool(migrated_db: dict[str, str]) -> AsyncGenerator[asyncpg.Pool]:
    dsn = (
        f"postgresql://{migrated_db['POSTGRES_USER']}:{migrated_db['POSTGRES_PASSWORD']}"
        f"@{migrated_db['POSTGRES_HOST']}:{migrated_db['POSTGRES_PORT']}"
        f"/{migrated_db['POSTGRES_DB']}"
    )
    pg_pool = await asyncpg.create_pool(dsn)
    assert pg_pool is not None
    yield pg_pool
    await pg_pool.close()


@pytest.fixture
async def conn(pool: asyncpg.Pool) -> AsyncGenerator[asyncpg.Connection]:  # type: ignore[type-arg]
    """Per-test connection wrapped in a rolled-back transaction."""
    async with pool.acquire() as connection:
        tr = connection.transaction()
        await tr.start()
        yield connection  # type: ignore[misc]
        await tr.rollback()
