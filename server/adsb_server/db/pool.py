from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import asyncpg


async def create_pool(dsn: str, min_size: int = 2, max_size: int = 10) -> asyncpg.Pool:
    pool = await asyncpg.create_pool(dsn, min_size=min_size, max_size=max_size)
    if pool is None:
        raise RuntimeError("asyncpg.create_pool returned None")
    return pool


@asynccontextmanager
async def acquire(pool: asyncpg.Pool) -> AsyncGenerator[asyncpg.Connection, None]:
    async with pool.acquire() as conn:
        yield conn
