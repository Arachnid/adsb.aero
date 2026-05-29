"""Result cache backed by Redis.

Keys:
  query:v1:<sha256_hex>   — POST /query response, keyed on canonical request JSON
  flight:v1:<flight_id>   — GET /flights/{id} response, keyed on flight_id

Values are zlib-compressed JSON bytes. Compression reduces Redis memory and
network overhead significantly for large flight-path payloads.

The cache is optional: if REDIS_URL is not configured, all operations are
no-ops. Redis errors are logged but never propagated — a cache miss just
falls through to Postgres.
"""

from __future__ import annotations

import hashlib
import logging
import zlib
from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from redis.asyncio import Redis as _Redis

logger = logging.getLogger(__name__)

QUERY_TTL = 86400  # 24 h — matches ingestion cadence; historical results are immutable
FLIGHT_TTL = 604800  # 7 days — individual flights never change once finalised


class ResultCache:
    """Thin async wrapper around a redis.asyncio.Redis client."""

    def __init__(self, client: _Redis) -> None:
        self._client = client

    async def get(self, key: str) -> bytes | None:
        """Return decompressed value for *key*, or None on miss/error."""
        try:
            raw = cast("bytes | None", await self._client.get(key))
            if raw is None:
                return None
            return zlib.decompress(raw)
        except Exception:
            logger.warning("Cache get failed for key %s", key, exc_info=True)
            return None

    async def set(self, key: str, data: bytes, ttl: int) -> None:
        """Store *data* compressed under *key* with the given TTL in seconds."""
        try:
            await self._client.set(key, zlib.compress(data), ex=ttl)
        except Exception:
            logger.warning("Cache set failed for key %s", key, exc_info=True)

    async def close(self) -> None:
        await self._client.aclose()

    @staticmethod
    def query_key(body_json: str) -> str:
        digest = hashlib.sha256(body_json.encode()).hexdigest()
        return f"query:v1:{digest}"

    @staticmethod
    def flight_key(flight_id: str) -> str:
        return f"flight:v1:{flight_id}"
