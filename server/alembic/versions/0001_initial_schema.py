"""Initial schema

Revision ID: 0001
Revises:
Create Date: 2026-05-03

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(sa.text("CREATE EXTENSION IF NOT EXISTS postgis"))
    op.execute(sa.text("CREATE EXTENSION IF NOT EXISTS mobilitydb"))
    op.execute(sa.text("CREATE SCHEMA IF NOT EXISTS partman"))
    op.execute(sa.text("CREATE EXTENSION IF NOT EXISTS pg_partman SCHEMA partman"))

    # ------------------------------------------------------------------
    # flights — finalised trajectories, partitioned monthly by start_ts
    #
    # path       tgeompoint — SRID 4326, 3D with Z=pressure-alt-ft;
    #                         timestamps are the native temporal dimension.
    # path_tracks tint      — per-instant heading (0–359°), stepwise.
    # start_point / end_point are derived at query time via startValue(path)
    # and endValue(path), with expression indexes for radius queries.
    # ------------------------------------------------------------------
    op.execute(
        sa.text("""
        CREATE TABLE flights (
            icao24            VARCHAR      NOT NULL,
            callsign          VARCHAR,
            icao_type         VARCHAR,
            emitter_category  VARCHAR,
            start_ts          TIMESTAMPTZ  NOT NULL,
            end_ts            TIMESTAMPTZ  NOT NULL,
            path              tgeompoint   NOT NULL,
            path_tracks       tint         NOT NULL,
            squawk_runs       JSONB        NOT NULL DEFAULT '[]',
            raw_point_count   INTEGER      NOT NULL DEFAULT 0,
            ingest_batch_date DATE         NOT NULL,
            PRIMARY KEY (icao24, start_ts)
        ) PARTITION BY RANGE (start_ts)
        """)
    )

    op.execute(
        sa.text("""
        SELECT partman.create_parent(
            p_parent_table   := 'public.flights',
            p_control        := 'start_ts',
            p_interval       := '1 month',
            p_start_partition := '2022-01-01 00:00:00',
            p_premake        := 1
        )
        """)
    )

    # STBOX GiST index on path — covers X, Y, Z (altitude), T (time) in a
    # single scan; replaces the old gist_geometry_ops_nd + alt btree indexes.
    op.execute(
        sa.text("""
        CREATE INDEX flights_path ON flights USING GIST (path)
        """)
    )

    # Expression indexes on the derived start/end points for radius queries.
    # startValue/endValue return the first/last geometry instant of the tgeompoint.
    op.execute(
        sa.text("""
        CREATE INDEX flights_start_point
            ON flights USING GIST ((startValue(path)::geometry))
        """)
    )
    op.execute(
        sa.text("""
        CREATE INDEX flights_end_point
            ON flights USING GIST ((endValue(path)::geometry))
        """)
    )

    # Btree expression indexes for altitude-range queries when no geometry is
    # present (trajectory(path) converts the tgeompoint to a PostGIS LineStringZ).
    op.execute(sa.text("CREATE INDEX flights_alt_min ON flights ((ST_ZMin(trajectory(path)::box3d)))"))
    op.execute(sa.text("CREATE INDEX flights_alt_max ON flights ((ST_ZMax(trajectory(path)::box3d)))"))

    op.execute(sa.text("CREATE INDEX flights_start_ts    ON flights (start_ts)"))
    op.execute(sa.text("CREATE INDEX flights_end_ts      ON flights (end_ts)"))
    op.execute(sa.text("CREATE INDEX flights_icao24      ON flights (icao24)"))
    op.execute(sa.text("CREATE INDEX flights_icao_type   ON flights (icao_type)"))
    op.execute(sa.text("CREATE INDEX flights_emitter_cat ON flights (emitter_category)"))

    # ------------------------------------------------------------------
    # flight_staging — raw in-progress points for idempotent re-processing
    # ------------------------------------------------------------------
    op.execute(
        sa.text("""
        CREATE TABLE flight_staging (
            batch_date   DATE  PRIMARY KEY,
            staging_data BYTEA NOT NULL
        )
        """)
    )

    # ------------------------------------------------------------------
    # ingest_batches — per-release job state for the scheduler
    # ------------------------------------------------------------------
    op.execute(
        sa.text("""
        CREATE TABLE ingest_batches (
            batch_date      DATE    PRIMARY KEY,
            status          VARCHAR NOT NULL
                                CHECK (status IN ('pending','running','succeeded','failed','errored')),
            started_at      TIMESTAMPTZ,
            finished_at     TIMESTAMPTZ,
            flight_count    INTEGER,
            error_message   TEXT,
            attempts        INTEGER     NOT NULL DEFAULT 0,
            last_attempt_at TIMESTAMPTZ,
            release_url     TEXT
        )
        """)
    )


def downgrade() -> None:
    op.execute(sa.text("DROP TABLE IF EXISTS ingest_batches"))
    op.execute(sa.text("DROP TABLE IF EXISTS flight_staging"))
    op.execute(sa.text("DROP TABLE IF EXISTS flights"))
    op.execute(sa.text("DROP EXTENSION IF EXISTS pg_partman"))
    op.execute(sa.text("DROP SCHEMA IF EXISTS partman CASCADE"))
    op.execute(sa.text("DROP EXTENSION IF EXISTS mobilitydb"))
