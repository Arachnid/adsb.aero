"""Retention for the ingestion tables that partitioning does not cover.

`flights` is partitioned weekly and pg_partman drops whole partitions once they
fall outside the retention window.  `flight_staging` is not partitioned — it is
keyed by `batch_date`, one compressed blob of in-progress flights per ingested
day — so nothing was ageing it out, and it had grown to ~105 GB.

Ingestion only ever reads the previous day's blob.  The rest are kept anyway,
for the same window as the traces: they are what makes a re-import cheap, since
re-running a day with its staging blob present reproduces the same flight keys
without having to re-derive the cross-midnight carry from scratch.  Beyond the
retention window the traces are gone, so keeping the staging that would have
regenerated them has no purpose.

The window is read from `partman.part_config` rather than configured here, so
there is one place that defines it.  If partman has no retention set, this does
nothing — declining to invent a policy the operator has not chosen.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import asyncpg

logger = logging.getLogger(__name__)

PARENT_TABLE = "public.flights"

_RETENTION_SQL = """
SELECT retention
FROM partman.part_config
WHERE parent_table = $1 AND retention IS NOT NULL AND retention <> ''
"""

# The cast to interval is what normalises partman's free-text retention:
# '18 months', '18 mons' and '1 year 6 mons' are the same window.
#
# The double cast is deliberate.  A bare `$1::interval` makes asyncpg infer the
# parameter as an interval and demand a timedelta, but what partman stores — and
# what we want Postgres itself to parse — is text.
_PURGE_STAGING_SQL = """
DELETE FROM flight_staging
WHERE batch_date < (CURRENT_DATE - ($1::text)::interval)
"""


async def flights_retention_interval(conn: asyncpg.Connection) -> str | None:
    """The retention window pg_partman applies to `flights`, or None if unset."""
    result: str | None = await conn.fetchval(_RETENTION_SQL, PARENT_TABLE)
    return result


async def purge_expired_staging(conn: asyncpg.Connection) -> int:
    """Delete `flight_staging` rows older than the flights retention window.

    Returns the number of rows deleted.  A no-op when partman has no retention
    configured, so enabling retention is a single decision made in one place.
    """
    retention = await flights_retention_interval(conn)
    if retention is None:
        logger.debug("No partman retention on %s; leaving flight_staging alone", PARENT_TABLE)
        return 0

    status = await conn.execute(_PURGE_STAGING_SQL, retention)
    # asyncpg returns the command tag, e.g. "DELETE 12".
    deleted = int(status.rsplit(" ", 1)[-1]) if status.startswith("DELETE ") else 0
    if deleted:
        logger.info(
            "Purged %d flight_staging row(s) older than %s",
            deleted,
            retention,
        )
    return deleted
