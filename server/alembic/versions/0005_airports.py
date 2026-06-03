"""Add waypoints, airspaces tables; start/end airport columns on flights

Revision ID: 0005
Revises: 0004
Create Date: 2026-06-01

"""

from typing import TYPE_CHECKING

import sqlalchemy as sa

from alembic import op

if TYPE_CHECKING:
    from collections.abc import Sequence

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # waypoints — OpenAIP airports, navaids, and VFR reporting points.
    #
    # kind         : 'airport' | 'navaid' | 'reporting_point'
    # ident        : ICAO code (airports), identifier (navaids), null (rpp)
    # iata_code    : airports only
    # type_code    : numeric OpenAIP type (airport/navaid sub-type)
    # frequency_mhz: navaids only (MHz; NDB kHz values converted)
    # compulsory   : reporting points only
    # ------------------------------------------------------------------
    op.execute(
        sa.text("""
        CREATE TABLE waypoints (
            id              TEXT        PRIMARY KEY,
            kind            TEXT        NOT NULL
                                CHECK (kind IN ('airport', 'navaid', 'reporting_point')),
            name            TEXT        NOT NULL,
            ident           TEXT,
            iata_code       TEXT,
            type_code       INTEGER,
            country         TEXT        NOT NULL,
            location        GEOMETRY(Point, 4326) NOT NULL,
            elevation_ft    INTEGER,
            frequency_mhz   FLOAT4,
            compulsory      BOOLEAN,
            fetched_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
            search_vec      TSVECTOR    GENERATED ALWAYS AS (
                to_tsvector('simple',
                    coalesce(ident, '') || ' ' ||
                    coalesce(iata_code, '') || ' ' ||
                    name
                )
            ) STORED
        )
        """)
    )
    op.execute(sa.text("CREATE INDEX waypoints_location ON waypoints USING GIST (location)"))
    op.execute(sa.text("CREATE INDEX waypoints_search  ON waypoints USING GIN  (search_vec)"))
    op.execute(sa.text("CREATE INDEX waypoints_ident ON waypoints (ident) WHERE ident IS NOT NULL"))
    op.execute(sa.text("CREATE INDEX waypoints_kind ON waypoints (kind)"))

    # ------------------------------------------------------------------
    # airspaces — OpenAIP airspace polygons for the chart overlay and
    #             zone-selection in the query builder.
    #
    # Altitude limits preserve the raw OpenAIP unit/ref codes so the
    # existing frontend formatter (which expects the original API shape)
    # needs no changes.  unit: 0=m 1=ft 6=FL.  ref: 0=GND 1=MSL 2=STD.
    # ------------------------------------------------------------------
    op.execute(
        sa.text("""
        CREATE TABLE airspaces (
            id                  TEXT        PRIMARY KEY,
            name                TEXT        NOT NULL,
            type_code           INTEGER     NOT NULL,
            icao_class          INTEGER,
            country             TEXT        NOT NULL,
            geometry            GEOMETRY(Geometry, 4326) NOT NULL,
            lower_limit_value   INTEGER,
            lower_limit_unit    SMALLINT,
            lower_limit_ref     SMALLINT,
            upper_limit_value   INTEGER,
            upper_limit_unit    SMALLINT,
            upper_limit_ref     SMALLINT,
            fetched_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
            search_vec          TSVECTOR    GENERATED ALWAYS AS (
                to_tsvector('simple', name)
            ) STORED
        )
        """)
    )
    op.execute(sa.text("CREATE INDEX airspaces_geometry ON airspaces USING GIST (geometry)"))
    op.execute(sa.text("CREATE INDEX airspaces_search ON airspaces USING GIN (search_vec)"))

    # ------------------------------------------------------------------
    # start/end airport columns on flights — store waypoints.id so joins
    # are a simple PK lookup.  The API returns the human-readable ident
    # (ICAO code etc.) via a separate start_airport_code field.
    # ------------------------------------------------------------------
    op.execute(sa.text("ALTER TABLE flights ADD COLUMN start_airport_ident TEXT"))
    op.execute(sa.text("ALTER TABLE flights ADD COLUMN end_airport_ident TEXT"))


def downgrade() -> None:
    op.execute(sa.text("ALTER TABLE flights DROP COLUMN IF EXISTS end_airport_ident"))
    op.execute(sa.text("ALTER TABLE flights DROP COLUMN IF EXISTS start_airport_ident"))
    op.execute(sa.text("DROP TABLE IF EXISTS airspaces"))
    op.execute(sa.text("DROP TABLE IF EXISTS waypoints"))
