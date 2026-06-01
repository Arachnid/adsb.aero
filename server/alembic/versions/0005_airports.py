"""Add airports table (OurAirports reference data)

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
    # airports — OurAirports reference data for radius-from-airfield
    # queries and typeahead search in the query builder.
    #
    # ident is the OurAirports primary identifier (often == icao_code
    # for airports that have one, but may differ for US FAA identifiers
    # and smaller fields without ICAO designators).
    # ------------------------------------------------------------------
    op.execute(
        sa.text("""
        CREATE TABLE airports (
            ident             TEXT         PRIMARY KEY,
            type              TEXT         NOT NULL,
            name              TEXT         NOT NULL,
            location          GEOMETRY(Point, 4326) NOT NULL,
            elevation_ft      INTEGER,
            iso_country       CHAR(2)      NOT NULL,
            iso_region        TEXT         NOT NULL,
            municipality      TEXT,
            scheduled_service BOOLEAN      NOT NULL DEFAULT false,
            icao_code         TEXT,
            iata_code         TEXT,
            local_code        TEXT,
            keywords          TEXT,
            fetched_at        TIMESTAMPTZ  NOT NULL DEFAULT now(),
            search_vec        TSVECTOR     GENERATED ALWAYS AS (
                to_tsvector('simple',
                    ident || ' ' ||
                    coalesce(icao_code, '') || ' ' ||
                    coalesce(iata_code, '') || ' ' ||
                    name || ' ' ||
                    coalesce(municipality, '')
                )
            ) STORED
        )
        """)
    )
    op.execute(sa.text("CREATE INDEX airports_location ON airports USING GIST (location)"))
    op.execute(
        sa.text(
            "CREATE INDEX airports_icao_code ON airports (icao_code) WHERE icao_code IS NOT NULL"
        )
    )
    op.execute(
        sa.text(
            "CREATE INDEX airports_iata_code ON airports (iata_code) WHERE iata_code IS NOT NULL"
        )
    )
    op.execute(sa.text("CREATE INDEX airports_search ON airports USING GIN (search_vec)"))


def downgrade() -> None:
    op.execute(sa.text("DROP TABLE IF EXISTS airports"))
