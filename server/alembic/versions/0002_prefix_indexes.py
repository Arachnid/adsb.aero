"""Add text_pattern_ops indexes for callsign and registration prefix filters

Revision ID: 0002
Revises: 0001
Create Date: 2026-05-20

"""

from typing import TYPE_CHECKING

import sqlalchemy as sa

from alembic import op

if TYPE_CHECKING:
    from collections.abc import Sequence

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # text_pattern_ops enables LIKE 'prefix%' index scans (bypasses locale collation).
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


def downgrade() -> None:
    op.execute(sa.text("DROP INDEX IF EXISTS flights_callsign_prefix"))
    op.execute(sa.text("DROP INDEX IF EXISTS airframes_registration_prefix"))
