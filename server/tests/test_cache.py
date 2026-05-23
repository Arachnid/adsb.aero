"""Unit tests for adsb_server.cache.ResultCache."""

from __future__ import annotations

import zlib
from unittest.mock import AsyncMock

import pytest

from adsb_server.cache import FLIGHT_TTL, QUERY_TTL, ResultCache


@pytest.fixture
def redis_client() -> AsyncMock:
    client = AsyncMock()
    client.aclose = AsyncMock()
    return client


@pytest.fixture
def cache(redis_client: AsyncMock) -> ResultCache:
    return ResultCache(redis_client)


# ---------------------------------------------------------------------------
# get
# ---------------------------------------------------------------------------


async def test_get_miss(cache: ResultCache, redis_client: AsyncMock) -> None:
    redis_client.get.return_value = None
    assert await cache.get("key") is None


async def test_get_hit(cache: ResultCache, redis_client: AsyncMock) -> None:
    payload = b'{"foo": "bar"}'
    redis_client.get.return_value = zlib.compress(payload)
    assert await cache.get("key") == payload


async def test_get_swallows_redis_error(cache: ResultCache, redis_client: AsyncMock) -> None:
    redis_client.get.side_effect = OSError("connection refused")
    assert await cache.get("key") is None  # falls through, does not raise


# ---------------------------------------------------------------------------
# set
# ---------------------------------------------------------------------------


async def test_set_stores_compressed(cache: ResultCache, redis_client: AsyncMock) -> None:
    data = b'{"flights": []}'
    await cache.set("key", data, ttl=60)
    redis_client.set.assert_awaited_once()
    call_args = redis_client.set.call_args
    stored_bytes: bytes = call_args.args[1]
    assert zlib.decompress(stored_bytes) == data
    assert call_args.kwargs == {"ex": 60}


async def test_set_swallows_redis_error(cache: ResultCache, redis_client: AsyncMock) -> None:
    redis_client.set.side_effect = OSError("connection refused")
    await cache.set("key", b"data", ttl=60)  # must not raise


# ---------------------------------------------------------------------------
# close
# ---------------------------------------------------------------------------


async def test_close(cache: ResultCache, redis_client: AsyncMock) -> None:
    await cache.close()
    redis_client.aclose.assert_awaited_once()


# ---------------------------------------------------------------------------
# key helpers
# ---------------------------------------------------------------------------


def test_query_key_is_deterministic() -> None:
    k1 = ResultCache.query_key('{"end_date": "2025-04-01"}')
    k2 = ResultCache.query_key('{"end_date": "2025-04-01"}')
    assert k1 == k2
    assert k1.startswith("query:v1:")


def test_query_key_differs_for_different_bodies() -> None:
    k1 = ResultCache.query_key('{"end_date": "2025-04-01"}')
    k2 = ResultCache.query_key('{"end_date": "2025-04-02"}')
    assert k1 != k2


def test_flight_key() -> None:
    key = ResultCache.flight_key("aabbcc:2025-04-01T10:00:00Z")
    assert key == "flight:v1:aabbcc:2025-04-01T10:00:00Z"


# ---------------------------------------------------------------------------
# TTL constants
# ---------------------------------------------------------------------------


def test_query_ttl_is_one_day() -> None:
    assert QUERY_TTL == 86400


def test_flight_ttl_is_one_week() -> None:
    assert FLIGHT_TTL == 604800
