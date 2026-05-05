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
    op.execute(sa.text("CREATE SCHEMA IF NOT EXISTS partman"))
    op.execute(sa.text("CREATE EXTENSION IF NOT EXISTS pg_partman SCHEMA partman"))

    # ------------------------------------------------------------------
    # flights — finalised trajectories, partitioned monthly by start_ts
    #
    # Primary key is (icao24, start_ts). Postgres requires the partition
    # key to be part of any unique constraint on a partitioned table;
    # (icao24, start_ts) is the natural compound identity for a flight.
    # ------------------------------------------------------------------
    op.execute(
        sa.text("""
        CREATE TABLE flights (
            icao24            VARCHAR                       NOT NULL,
            callsign          VARCHAR,
            icao_type         VARCHAR,
            emitter_category  VARCHAR,
            start_ts          TIMESTAMPTZ                   NOT NULL,
            end_ts            TIMESTAMPTZ                   NOT NULL,
            start_point       GEOMETRY(POINTZM, 4326)       NOT NULL,
            end_point         GEOMETRY(POINTZM, 4326)       NOT NULL,
            path_geom         GEOMETRY(LINESTRINGZM, 4326)  NOT NULL,
            path_tracks       SMALLINT[]                    NOT NULL DEFAULT '{}',
            squawk_runs       JSONB                         NOT NULL DEFAULT '[]',
            raw_point_count   INTEGER                       NOT NULL DEFAULT 0,
            ingest_batch_date DATE                          NOT NULL,
            PRIMARY KEY (icao24, start_ts)
        ) PARTITION BY RANGE (start_ts)
        """)
    )

    # Hand pg_partman the parent table. It creates monthly partitions
    # from p_start_partition up to now + p_premake months, and the
    # pg_partman_bgw background worker then keeps rolling them forward.
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

    # Indexes on the parent cascade to all existing and future partitions.
    op.execute(
        sa.text("""
        CREATE INDEX flights_path_geom_nd
            ON flights USING GIST (path_geom gist_geometry_ops_nd)
        """)
    )
    op.execute(sa.text("CREATE INDEX flights_start_point ON flights USING GIST (start_point)"))
    op.execute(sa.text("CREATE INDEX flights_end_point   ON flights USING GIST (end_point)"))
    op.execute(sa.text("CREATE INDEX flights_start_ts    ON flights (start_ts)"))
    op.execute(sa.text("CREATE INDEX flights_end_ts      ON flights (end_ts)"))
    op.execute(sa.text("CREATE INDEX flights_icao24      ON flights (icao24)"))
    op.execute(sa.text("CREATE INDEX flights_icao_type   ON flights (icao_type)"))
    op.execute(sa.text("CREATE INDEX flights_emitter_cat ON flights (emitter_category)"))
    # Expression indexes for altitude-range queries (avoids storing min/max columns).
    op.execute(sa.text("CREATE INDEX flights_alt_min ON flights ((ST_ZMin(path_geom::box3d)))"))
    op.execute(sa.text("CREATE INDEX flights_alt_max ON flights ((ST_ZMax(path_geom::box3d)))"))

    # ------------------------------------------------------------------
    # staging_flights — in-progress flights awaiting finalisation
    # ------------------------------------------------------------------
    op.execute(
        sa.text("""
        CREATE TABLE staging_flights (
            icao24    VARCHAR     NOT NULL,
            start_ts  TIMESTAMPTZ NOT NULL,
            last_ts   TIMESTAMPTZ NOT NULL,
            points    JSONB       NOT NULL DEFAULT '[]',
            source    VARCHAR     NOT NULL CHECK (source IN ('batch', 'stream')),
            PRIMARY KEY (icao24, start_ts)
        )
        """)
    )
    op.execute(sa.text("CREATE INDEX staging_flights_icao24 ON staging_flights (icao24)"))

    # ------------------------------------------------------------------
    # ingest_batches — per-release job state for the scheduler
    # ------------------------------------------------------------------
    op.execute(
        sa.text("""
        CREATE TABLE ingest_batches (
            batch_date      DATE    PRIMARY KEY,
            status          VARCHAR NOT NULL
                                CHECK (status IN ('pending','running','succeeded','failed')),
            started_at      TIMESTAMPTZ,
            finished_at     TIMESTAMPTZ,
            flight_count    INTEGER,
            error_message   TEXT,
            attempts        INTEGER     NOT NULL DEFAULT 0,
            last_attempt_at TIMESTAMPTZ
        )
        """)
    )


def downgrade() -> None:
    op.execute(sa.text("DROP TABLE IF EXISTS ingest_batches"))
    op.execute(sa.text("DROP TABLE IF EXISTS staging_flights"))
    op.execute(sa.text("DROP TABLE IF EXISTS flights"))
    op.execute(sa.text("DROP EXTENSION IF EXISTS pg_partman"))
    op.execute(sa.text("DROP SCHEMA IF EXISTS partman CASCADE"))
