"""Add path_agl_ft column to flights for AGL height series

Revision ID: 0003
Revises: 0002
Create Date: 2026-05-24

"""

from typing import TYPE_CHECKING

import sqlalchemy as sa

from alembic import op

if TYPE_CHECKING:
    from collections.abc import Sequence

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ALTER TABLE on the parent partitioned table propagates to all child partitions
    # automatically in PostgreSQL 12+.
    op.execute(sa.text("ALTER TABLE flights ADD COLUMN IF NOT EXISTS path_agl_ft tfloat"))
    op.execute(
        sa.text(
            "CREATE INDEX IF NOT EXISTS flights_agl_min_ft"
            " ON flights ((minvalue(path_agl_ft)::float4))"
            " WHERE path_agl_ft IS NOT NULL"
        )
    )
    op.execute(
        sa.text(
            "CREATE INDEX IF NOT EXISTS flights_agl_max_ft"
            " ON flights ((maxvalue(path_agl_ft)::float4))"
            " WHERE path_agl_ft IS NOT NULL"
        )
    )


def downgrade() -> None:
    op.execute(sa.text("DROP INDEX IF EXISTS flights_agl_min_ft"))
    op.execute(sa.text("DROP INDEX IF EXISTS flights_agl_max_ft"))
    op.execute(sa.text("ALTER TABLE flights DROP COLUMN IF EXISTS path_agl_ft"))
