"""Normalize stored callsigns to upper-case without hyphens

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


def upgrade() -> None:
    # Callsign prefix filters compile to `callsign LIKE 'prefix%'` against the
    # text_pattern_ops index from 0002, and the prefix is normalized before it gets
    # there. Normalize what is already stored so the comparison holds both ways;
    # ingestion normalizes everything written from here on.
    #
    # The WHERE clause keeps this to the rows that actually differ — ADS-B callsigns
    # are broadcast upper-case and unpunctuated, so on a clean archive it touches
    # nothing and the full-table rewrite is avoided.
    op.execute(
        sa.text("""
        UPDATE flights
        SET callsign = replace(upper(callsign), '-', '')
        WHERE callsign IS NOT NULL
          AND callsign <> replace(upper(callsign), '-', '')
        """)
    )


def downgrade() -> None:
    # The original spellings are not recoverable; normalized callsigns are valid
    # input for every earlier revision, so there is nothing to undo.
    pass
