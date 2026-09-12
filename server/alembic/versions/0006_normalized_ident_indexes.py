"""Index normalized identifiers for case- and hyphen-insensitive lookups

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


def _norm(col: str) -> str:
    """Mirrors normalize_ident() and compiler._norm()."""
    return f"replace(upper({col}), '-', '')"


def upgrade() -> None:
    # Identifier lookups normalize the query value and match it against the same
    # normalization of the column, so that `g-abcd` finds `G-ABCD` without the stored
    # value losing the spelling it was published with. Index the expression the
    # compiler emits, or every such filter is a sequential scan.
    #
    # text_pattern_ops on the prefix-matched columns enables LIKE 'prefix%' index
    # scans; the equality-matched ones take the default opclass. The plain-column
    # indexes from 0002 existed only for these two prefix filters, so they go; the
    # ones from 0001 stay, since they still serve lookups on the raw columns.
    op.execute(
        sa.text(
            "CREATE INDEX IF NOT EXISTS flights_callsign_norm_prefix"
            f" ON flights ({_norm('callsign')} text_pattern_ops)"
        )
    )
    op.execute(
        sa.text(
            "CREATE INDEX IF NOT EXISTS airframes_registration_norm_prefix"
            f" ON airframes ({_norm('registration')} text_pattern_ops)"
        )
    )
    op.execute(
        sa.text(
            "CREATE INDEX IF NOT EXISTS flights_icao_type_norm"
            f" ON flights ({_norm('icao_type')})"
        )
    )
    op.execute(
        sa.text(
            "CREATE INDEX IF NOT EXISTS flights_emitter_cat_norm"
            f" ON flights ({_norm('emitter_category')})"
        )
    )
    op.execute(sa.text("DROP INDEX IF EXISTS flights_callsign_prefix"))
    op.execute(sa.text("DROP INDEX IF EXISTS airframes_registration_prefix"))


def downgrade() -> None:
    op.execute(
        sa.text(
            "CREATE INDEX IF NOT EXISTS flights_callsign_prefix"
            " ON flights (callsign text_pattern_ops)"
        )
    )
    op.execute(
        sa.text(
            "CREATE INDEX IF NOT EXISTS airframes_registration_prefix"
            " ON airframes (registration text_pattern_ops)"
        )
    )
    op.execute(sa.text("DROP INDEX IF EXISTS flights_callsign_norm_prefix"))
    op.execute(sa.text("DROP INDEX IF EXISTS airframes_registration_norm_prefix"))
    op.execute(sa.text("DROP INDEX IF EXISTS flights_icao_type_norm"))
    op.execute(sa.text("DROP INDEX IF EXISTS flights_emitter_cat_norm"))
