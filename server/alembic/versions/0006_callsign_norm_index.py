"""Index the normalized callsign for case- and hyphen-insensitive prefix filters

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
    # Callsign prefix filters now match against replace(upper(callsign), '-', ''),
    # so the plain text_pattern_ops index from 0002 is no longer usable. Replace it
    # with an expression index on the same normalization the compiler applies.
    op.execute(
        sa.text(
            "CREATE INDEX IF NOT EXISTS flights_callsign_norm_prefix"
            " ON flights (replace(upper(callsign), '-', '') text_pattern_ops)"
        )
    )
    op.execute(sa.text("DROP INDEX IF EXISTS flights_callsign_prefix"))


def downgrade() -> None:
    op.execute(
        sa.text(
            "CREATE INDEX IF NOT EXISTS flights_callsign_prefix"
            " ON flights (callsign text_pattern_ops)"
        )
    )
    op.execute(sa.text("DROP INDEX IF EXISTS flights_callsign_norm_prefix"))
