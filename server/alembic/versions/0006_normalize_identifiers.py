"""Normalize stored identifiers to the form lookups are normalized to

Revision ID: 0006
Revises: 0005
Create Date: 2026-09-12

"""

from typing import TYPE_CHECKING

import sqlalchemy as sa

from alembic import op

if TYPE_CHECKING:
    from collections.abc import Sequence

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Mirrors normalize_ident(): upper-case, hyphens removed.
_NORM = "replace(upper({col}), '-', '')"


def upgrade() -> None:
    # Callsign, registration, type designator and emitter category are all matched
    # against values normalized on the way in (`callsign LIKE 'prefix%'`,
    # `icao_type = ANY(...)`), so normalize what is already stored and the comparison
    # holds both ways. Ingestion normalizes everything written from here on.
    #
    # Each WHERE clause keeps the rewrite to rows that actually differ: these values
    # are published upper-case, so on a clean archive this touches nothing and no
    # full-table rewrite happens. icao24 is left alone — it is lower-cased at
    # ingestion already, and it is the primary key of both tables.
    op.execute(
        sa.text(f"""
        UPDATE flights
        SET callsign = {_NORM.format(col="callsign")},
            icao_type = {_NORM.format(col="icao_type")},
            emitter_category = {_NORM.format(col="emitter_category")}
        WHERE callsign IS DISTINCT FROM {_NORM.format(col="callsign")}
           OR icao_type IS DISTINCT FROM {_NORM.format(col="icao_type")}
           OR emitter_category IS DISTINCT FROM {_NORM.format(col="emitter_category")}
        """)
    )
    op.execute(
        sa.text(f"""
        UPDATE airframes
        SET registration = {_NORM.format(col="registration")},
            icao_type = {_NORM.format(col="icao_type")}
        WHERE registration IS DISTINCT FROM {_NORM.format(col="registration")}
           OR icao_type IS DISTINCT FROM {_NORM.format(col="icao_type")}
        """)
    )


def downgrade() -> None:
    # The original spellings are not recoverable; normalized identifiers are valid
    # input for every earlier revision, so there is nothing to undo.
    pass
