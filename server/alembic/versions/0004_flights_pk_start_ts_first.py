"""Reorder flights PK to (start_ts, icao24) and drop redundant start_ts index

Revision ID: 0004
Revises: 0003
Create Date: 2026-05-25

"""

from typing import TYPE_CHECKING

import sqlalchemy as sa

from alembic import op

if TYPE_CHECKING:
    from collections.abc import Sequence

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Drop the standalone start_ts index first — it will be redundant once
    # start_ts is the leading column of the primary key.
    op.execute(sa.text("DROP INDEX IF EXISTS flights_start_ts"))
    # Recreate the primary key with start_ts leading.  On a partitioned table
    # this propagates automatically to all child partitions.
    op.execute(sa.text("ALTER TABLE flights DROP CONSTRAINT flights_pkey"))
    op.execute(sa.text("ALTER TABLE flights ADD PRIMARY KEY (start_ts, icao24)"))


def downgrade() -> None:
    op.execute(sa.text("ALTER TABLE flights DROP CONSTRAINT flights_pkey"))
    op.execute(sa.text("ALTER TABLE flights ADD PRIMARY KEY (icao24, start_ts)"))
    op.execute(sa.text("CREATE INDEX flights_start_ts ON flights (start_ts)"))
