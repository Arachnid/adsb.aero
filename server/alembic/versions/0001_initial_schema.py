"""Initial schema

Revision ID: 0001
Revises:
Create Date: 2026-05-03

"""

from typing import TYPE_CHECKING

import sqlalchemy as sa

from alembic import op

if TYPE_CHECKING:
    from collections.abc import Sequence

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(sa.text("CREATE EXTENSION IF NOT EXISTS postgis"))
    op.execute(sa.text("CREATE EXTENSION IF NOT EXISTS mobilitydb"))
    op.execute(sa.text("CREATE EXTENSION IF NOT EXISTS h3"))
    op.execute(sa.text("CREATE SCHEMA IF NOT EXISTS partman"))
    op.execute(sa.text("CREATE EXTENSION IF NOT EXISTS pg_partman SCHEMA partman"))

    # ------------------------------------------------------------------
    # flights — finalised trajectories, partitioned monthly by start_ts
    #
    # path        tgeompoint  — SRID 4326, 3D with Z=pressure-alt-ft;
    #                           timestamps are the native temporal dimension.
    # path_tracks tint        — per-instant heading (0-359°), stepwise.
    # path_h3     h3index[]   — H3 res-4 cells covering the trajectory,
    #                           computed in Python at ingestion; drives the
    #                           GIN spatial pre-filter.
    # squawk_codes text[]     — distinct squawk codes seen on the flight,
    #                           computed in Python at ingestion; drives the
    #                           GIN squawk pre-filter.
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
            path_tracks       tint,
            path_gs           tint,
            path_vr           tint,
            path_ias          tint,
            squawk_seq        ttext,
            alt_correction_ft tfloat,
            alt_min_pressure_ft FLOAT4
                GENERATED ALWAYS AS (CAST(minValue(getZ(path)) AS float4)) STORED,
            alt_max_pressure_ft FLOAT4
                GENERATED ALWAYS AS (CAST(maxValue(getZ(path)) AS float4)) STORED,
            alt_min_qnh_ft    FLOAT4
                GENERATED ALWAYS AS (
                    CAST(COALESCE(
                        minValue(getZ(path) + alt_correction_ft),
                        minValue(getZ(path))
                    ) AS float4)
                ) STORED,
            alt_max_qnh_ft    FLOAT4
                GENERATED ALWAYS AS (
                    CAST(COALESCE(
                        maxValue(getZ(path) + alt_correction_ft),
                        maxValue(getZ(path))
                    ) AS float4)
                ) STORED,
            raw_point_count   INTEGER      NOT NULL DEFAULT 0,
            ingest_batch_date DATE         NOT NULL,
            path_h3           h3index[]    NOT NULL DEFAULT '{}',
            squawk_codes      text[]       NOT NULL DEFAULT '{}',
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

    # H3 GIN index — drives spatial pre-filtering via path_h3 && $cells::h3index[].
    # Replaces the old MobilityDB GiST index on path.
    op.execute(
        sa.text("CREATE INDEX flights_path_h3_gin ON flights USING GIN (path_h3)")
    )

    # Squawk GIN index — pre-filters squawk queries before MobilityDB temporal check.
    op.execute(
        sa.text("CREATE INDEX flights_squawk_codes_gin ON flights USING GIN (squawk_codes)")
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

    op.execute(sa.text("CREATE INDEX flights_alt_min_pressure ON flights (alt_min_pressure_ft)"))
    op.execute(sa.text("CREATE INDEX flights_alt_max_pressure ON flights (alt_max_pressure_ft)"))
    op.execute(sa.text("CREATE INDEX flights_alt_min_qnh ON flights (alt_min_qnh_ft)"))
    op.execute(sa.text("CREATE INDEX flights_alt_max_qnh ON flights (alt_max_qnh_ft)"))

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
                                CHECK (status IN (
                                    'pending','running','succeeded','failed','errored'
                                )),
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

    # ------------------------------------------------------------------
    # icao_type_stats — per-day ICAO type flight counts with model name
    #
    # Maintained incrementally: after each batch ingestion, a single
    # partition-pruned aggregation upserts one row per (day, icao_type).
    # model is the most common airframes.model string for that type.
    # ------------------------------------------------------------------
    op.execute(
        sa.text("""
        CREATE TABLE icao_type_stats (
            day          DATE     NOT NULL,
            icao_type    VARCHAR  NOT NULL,
            model        VARCHAR,
            flight_count INTEGER  NOT NULL,
            PRIMARY KEY (day, icao_type)
        )
        """)
    )

    # ------------------------------------------------------------------
    # airframes — per-icao24 registration/type/operator reference data
    #
    # Sourced from tar1090-db (Mictronics aircraft database).
    # icao24 matches the flights.icao24 column.
    # flags is a bitmask: bit 0 = military, bit 1 = interesting,
    #                      bit 3 = FAA LADD (privacy-protected).
    # ------------------------------------------------------------------
    op.execute(
        sa.text("""
        CREATE TABLE airframes (
            icao24       VARCHAR(6)   PRIMARY KEY,
            registration VARCHAR,
            icao_type    VARCHAR,
            flags        SMALLINT     NOT NULL DEFAULT 0,
            model        VARCHAR,
            year         SMALLINT,
            operator     VARCHAR,
            fetched_at   TIMESTAMPTZ  NOT NULL DEFAULT now()
        )
        """)
    )
    op.execute(sa.text("CREATE INDEX airframes_icao_type ON airframes (icao_type)"))
    op.execute(sa.text("CREATE INDEX airframes_registration ON airframes (registration)"))


def downgrade() -> None:
    op.execute(sa.text("DROP TABLE IF EXISTS airframes"))
    op.execute(sa.text("DROP TABLE IF EXISTS icao_type_stats"))
    op.execute(sa.text("DROP TABLE IF EXISTS ingest_batches"))
    op.execute(sa.text("DROP TABLE IF EXISTS flight_staging"))
    op.execute(sa.text("DROP TABLE IF EXISTS flights"))
    op.execute(sa.text("DROP EXTENSION IF EXISTS pg_partman"))
    op.execute(sa.text("DROP SCHEMA IF EXISTS partman CASCADE"))
    op.execute(sa.text("DROP EXTENSION IF EXISTS mobilitydb"))
    op.execute(sa.text("DROP EXTENSION IF EXISTS h3"))
