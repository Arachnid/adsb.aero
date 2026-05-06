"""FastAPI application — health, query, and flight-detail endpoints."""

from __future__ import annotations

import json
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any, AsyncGenerator

import asyncpg
from fastapi import APIRouter, FastAPI, HTTPException, Request

from adsb_server.config import get_settings
from adsb_server.db.pool import create_pool
from adsb_server.query.compiler import compile_predicate
from adsb_server.query.models import (
    FlightDetail,
    FlightSummary,
    QueryRequest,
    QueryResponse,
    decode_cursor,
    encode_cursor,
)

# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------

FLIGHT_ID_EXPR = (
    "icao24 || ':' || to_char(start_ts AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS\"Z\"')"
)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    owned = not hasattr(app.state, "pool")
    if owned:
        app.state.pool = await create_pool(get_settings().asyncpg_dsn)
    try:
        yield
    finally:
        if owned:
            await app.state.pool.close()


app = FastAPI(title="adsb.aero API", version="0.1.0", lifespan=lifespan)
router = APIRouter(prefix="/api/v1")


# ---------------------------------------------------------------------------
# Dependencies
# ---------------------------------------------------------------------------


async def get_pool(request: Request) -> asyncpg.Pool:
    pool: asyncpg.Pool = request.app.state.pool
    return pool


# ---------------------------------------------------------------------------
# Helper: row → FlightSummary
# ---------------------------------------------------------------------------


def _row_to_summary(row: asyncpg.Record) -> FlightSummary:
    return FlightSummary(
        flight_id=row["flight_id"],
        icao24=row["icao24"],
        callsign=row["callsign"],
        icao_type=row["icao_type"],
        emitter_category=row["emitter_category"],
        start_ts=row["start_ts"],
        end_ts=row["end_ts"],
        start_point=json.loads(row["start_point"]),
        end_point=json.loads(row["end_point"]),
    )


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@router.post("/query", response_model=QueryResponse)
async def query_flights(
    body: QueryRequest,
    request: Request,
) -> QueryResponse:
    pool = await get_pool(request)
    params: list[Any] = []

    # Build WHERE clause
    where_parts: list[str] = []
    if body.match is not None:
        where_parts.append(f"({compile_predicate(body.match, params)})")

    # Cursor condition
    if body.cursor is not None:
        cursor_ts, cursor_icao = decode_cursor(body.cursor)
        ts_p = _p(params, cursor_ts)
        icao_p = _p(params, cursor_icao)
        where_parts.append(
            f"(start_ts < {ts_p} OR (start_ts = {ts_p} AND icao24 < {icao_p}))"
        )

    where_sql = ("WHERE " + " AND ".join(where_parts)) if where_parts else ""

    limit_p = _p(params, body.limit + 1)

    sql = f"""
        SELECT
            {FLIGHT_ID_EXPR} AS flight_id,
            icao24,
            callsign,
            icao_type,
            emitter_category,
            start_ts,
            end_ts,
            ST_AsGeoJSON(start_point, 6) AS start_point,
            ST_AsGeoJSON(end_point, 6) AS end_point
        FROM flights f
        {where_sql}
        ORDER BY start_ts DESC, icao24 DESC
        LIMIT {limit_p}
    """

    rows = await pool.fetch(sql, *params)

    has_more = len(rows) > body.limit
    result_rows = rows[: body.limit]

    next_cursor: str | None = None
    if has_more and result_rows:
        last = result_rows[-1]
        next_cursor = encode_cursor(last["start_ts"], last["icao24"])

    return QueryResponse(
        flights=[_row_to_summary(r) for r in result_rows],
        cursor=next_cursor,
    )


@router.get("/flights/{flight_id:path}", response_model=FlightDetail)
async def get_flight(
    flight_id: str,
    request: Request,
) -> FlightDetail:
    pool = await get_pool(request)

    # Parse flight_id: "icao24:ISO8601"
    colon_idx = flight_id.find(":")
    if colon_idx < 0:
        raise HTTPException(status_code=422, detail="Malformed flight_id")

    icao24 = flight_id[:colon_idx]
    ts_str = flight_id[colon_idx + 1 :]

    try:
        start_ts: datetime = datetime.fromisoformat(ts_str)
    except ValueError:
        raise HTTPException(status_code=422, detail="Malformed flight_id timestamp")

    sql = f"""
        SELECT
            {FLIGHT_ID_EXPR} AS flight_id,
            f.icao24,
            f.callsign,
            f.icao_type,
            f.emitter_category,
            f.start_ts,
            f.end_ts,
            ST_AsGeoJSON(f.start_point, 6) AS start_point,
            ST_AsGeoJSON(f.end_point, 6) AS end_point,
            ST_AsGeoJSON(f.path_geom, 6) AS path,
            ts_agg.timestamps,
            f.path_tracks,
            f.squawk_runs,
            f.raw_point_count,
            f.ingest_batch_date
        FROM flights f,
        LATERAL (
            SELECT ARRAY_AGG(ST_M(dp.geom) ORDER BY dp.path) AS timestamps
            FROM ST_DumpPoints(f.path_geom) AS dp
        ) ts_agg
        WHERE f.icao24 = $1 AND f.start_ts = $2
    """

    row = await pool.fetchrow(sql, icao24, start_ts)
    if row is None:
        raise HTTPException(status_code=404, detail="Flight not found")

    path_geojson: dict[str, Any] = json.loads(row["path"])
    # Strip M coordinate from each vertex — GeoJSON from ST_AsGeoJSON includes
    # Z but the 6-decimal call may include M as 4th element; keep only first 3.
    if "coordinates" in path_geojson:
        path_geojson["coordinates"] = [
            c[:3] for c in path_geojson["coordinates"]
        ]

    squawk_raw = row["squawk_runs"]
    squawk_runs: list[list[Any]] = json.loads(squawk_raw) if squawk_raw else []

    return FlightDetail(
        flight_id=row["flight_id"],
        icao24=row["icao24"],
        callsign=row["callsign"],
        icao_type=row["icao_type"],
        emitter_category=row["emitter_category"],
        start_ts=row["start_ts"],
        end_ts=row["end_ts"],
        start_point=json.loads(row["start_point"]),
        end_point=json.loads(row["end_point"]),
        path=path_geojson,
        timestamps=[float(t) for t in row["timestamps"]],
        path_tracks=list(row["path_tracks"]),
        squawk_runs=squawk_runs,
        raw_point_count=row["raw_point_count"],
        ingest_batch_date=row["ingest_batch_date"],
    )


def _p(params: list[Any], val: Any) -> str:
    """Append val to params and return its $n placeholder."""
    params.append(val)
    return f"${len(params)}"


app.include_router(router)
