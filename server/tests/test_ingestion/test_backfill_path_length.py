"""Integration tests for adsb_server.ingestion.backfill_path_length."""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import TYPE_CHECKING

import pytest

from adsb_server.geometry.wkt import tgeompoint_seqset
from adsb_server.ingestion.backfill_path_length import main, run_backfill

if TYPE_CHECKING:
    import asyncpg

_ICAO = "b0f111"
_START = datetime(2024, 6, 1, 9, 0, tzinfo=UTC)
_END = datetime(2024, 6, 1, 9, 30, tzinfo=UTC)
_T0 = _START.timestamp()

# Two sub-sequences along the equator with a 20-minute coverage gap between them.
# Stitched track: 0.0° → 0.3° of longitude.  Unstitched it would be only 0.2°.
_PATH = tgeompoint_seqset(
    [
        [(0.0, 0.0, 5000.0, _T0), (0.1, 0.0, 5000.0, _T0 + 300)],
        [(0.2, 0.0, 5000.0, _T0 + 1500), (0.3, 0.0, 5000.0, _T0 + 1800)],
    ]
)
# 0.3° of longitude on the WGS84 equator.
_EXPECTED_M = 33_395.8


def _dsn(settings: dict[str, str]) -> str:
    return (
        f"postgresql://{settings['POSTGRES_USER']}:{settings['POSTGRES_PASSWORD']}"
        f"@{settings['POSTGRES_HOST']}:{settings['POSTGRES_PORT']}/{settings['POSTGRES_DB']}"
    )


async def test_backfill_fills_null_path_length(
    pool: asyncpg.Pool, migrated_db: dict[str, str]
) -> None:
    await pool.execute(
        "INSERT INTO flights (icao24, start_ts, end_ts, path, ingest_batch_date)"
        " VALUES ($1, $2, $3, $4::tgeompoint, $5)",
        _ICAO,
        _START,
        _END,
        _PATH,
        date(2024, 6, 1),
    )
    try:
        updated = await run_backfill(_dsn(migrated_db))
        assert updated >= 1
        length = await pool.fetchval(
            "SELECT path_length_m FROM flights WHERE icao24 = $1 AND start_ts = $2",
            _ICAO,
            _START,
        )
        # The gap is bridged: close to the full 0.3°, not the 0.2° actually observed.
        assert length == pytest.approx(_EXPECTED_M, rel=1e-3)

        # Idempotent: everything is filled, so a second run touches nothing.
        assert await run_backfill(_dsn(migrated_db)) == 0
    finally:
        await pool.execute("DELETE FROM flights WHERE icao24 = $1 AND start_ts = $2", _ICAO, _START)


async def test_backfill_with_nothing_to_do(pool: asyncpg.Pool, migrated_db: dict[str, str]) -> None:
    await run_backfill(_dsn(migrated_db))  # fill anything left NULL by other tests
    assert await run_backfill(_dsn(migrated_db)) == 0


def test_main_runs_backfill(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    async def fake_run_backfill(dsn: str) -> int:
        calls.append(dsn)
        return 0

    monkeypatch.setattr(
        "adsb_server.ingestion.backfill_path_length.run_backfill", fake_run_backfill
    )
    main()
    assert len(calls) == 1
