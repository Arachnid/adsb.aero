"""Add path_length_m to flights for whole-flight track distance filters

Revision ID: 0007
Revises: 0006
Create Date: 2026-09-30

"""

from typing import TYPE_CHECKING

import sqlalchemy as sa

from alembic import op

if TYPE_CHECKING:
    from collections.abc import Sequence

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # A plain nullable column rather than GENERATED ... STORED: adding a stored
    # generated column rewrites every partition, whereas this is metadata-only.
    # Ingest fills it for new flights; backfill-path-length fills existing ones.
    op.execute(sa.text("ALTER TABLE flights ADD COLUMN IF NOT EXISTS path_length_m FLOAT4"))
    op.execute(
        sa.text("CREATE INDEX IF NOT EXISTS flights_path_length_m ON flights (path_length_m)")
    )


def downgrade() -> None:
    op.execute(sa.text("DROP INDEX IF EXISTS flights_path_length_m"))
    op.execute(sa.text("ALTER TABLE flights DROP COLUMN IF EXISTS path_length_m"))
