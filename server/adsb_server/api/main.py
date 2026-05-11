"""FastAPI application — health, query, and flight-detail endpoints."""

from __future__ import annotations

import json
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Annotated, Any, AsyncGenerator

import asyncpg
from fastapi import APIRouter, Body, FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from scalar_fastapi import get_scalar_api_reference

from adsb_server.config import get_settings
from adsb_server.db.pool import create_pool
from adsb_server.query.compiler import compile_predicate
from adsb_server.query.models import (
    FlightDetail,
    GeoJSONLineStringZ,
    GeoJSONPointZ,
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


app = FastAPI(
    title="adsb.aero API",
    version="0.1.0",
    openapi_url="/api/openapi.json",
    description=(
        "Historical ADS-B flight trajectory API. "
        "Query flights by geometry, time, aircraft type, callsign, and more. "
        "All endpoints are under `/api/v1/`. No authentication required."
    ),
    lifespan=lifespan,
    docs_url=None,
    redoc_url="/api/redoc",
)
router = APIRouter(prefix="/api/v1")


# ---------------------------------------------------------------------------
# Documentation endpoints
# ---------------------------------------------------------------------------


@app.get("/api/docs", include_in_schema=False)
async def scalar_docs() -> HTMLResponse:
    return get_scalar_api_reference(
        openapi_url="/api/openapi.json",
        title="adsb.aero API",
    )


# ---------------------------------------------------------------------------
# Dependencies
# ---------------------------------------------------------------------------


async def get_pool(request: Request) -> asyncpg.Pool:
    pool: asyncpg.Pool = request.app.state.pool
    return pool


# ---------------------------------------------------------------------------
# Helper: row → FlightDetail
# ---------------------------------------------------------------------------

# Columns selected by both /query and /flights/{id}
_FLIGHT_COLS = f"""
    {FLIGHT_ID_EXPR} AS flight_id,
    f.icao24,
    f.callsign,
    f.icao_type,
    f.emitter_category,
    f.start_ts,
    f.end_ts,
    ST_AsGeoJSON(f.start_point, 6) AS start_point,
    ST_AsGeoJSON(f.end_point, 6) AS end_point,
    ST_AsText(f.path_geom) AS path_wkt,
    f.path_tracks,
    f.squawk_runs,
    f.raw_point_count,
    f.ingest_batch_date,
    ST_NPoints(f.path_geom) AS point_count
"""


def _parse_path_wkt(
    wkt: str, path_tracks: list[int],
) -> tuple[GeoJSONLineStringZ, list[float], list[int]]:
    """Parse a LINESTRINGZM WKT into a GeoJSON LineString, timestamps list, and path_tracks.

    ST_AsText preserves M (timestamp) values that ST_AsGeoJSON discards.
    Coordinates are rounded to 6 decimal places to match ST_AsGeoJSON precision.
    path_geom never contains ground points (they are excluded at ingest time).
    """
    inner = wkt[wkt.index("(") + 1 : wkt.rindex(")")]
    coords_3d: list[tuple[float, float, float]] = []
    timestamps: list[float] = []
    for point_str in inner.split(","):
        parts = point_str.split()
        coords_3d.append((round(float(parts[0]), 6), round(float(parts[1]), 6), round(float(parts[2]), 6)))
        timestamps.append(float(parts[3]))
    return GeoJSONLineStringZ(type="LineString", coordinates=coords_3d), timestamps, list(path_tracks)


def _row_to_detail(row: asyncpg.Record, include_path: bool = True) -> FlightDetail:
    path = None
    timestamps = None
    filtered_tracks = None
    squawk_runs = None
    if include_path:
        raw_tracks = list(row["path_tracks"])
        path, timestamps, filtered_tracks = _parse_path_wkt(row["path_wkt"], raw_tracks)
        squawk_raw: str | None = row["squawk_runs"]
        squawk_runs = (
            [(float(r[0]), str(r[1])) for r in json.loads(squawk_raw)] if squawk_raw else []
        )
    return FlightDetail(
        flight_id=row["flight_id"],
        icao24=row["icao24"],
        callsign=row["callsign"],
        icao_type=row["icao_type"],
        emitter_category=row["emitter_category"],
        start_ts=row["start_ts"],
        end_ts=row["end_ts"],
        start_point=GeoJSONPointZ.model_validate_json(row["start_point"]),
        end_point=GeoJSONPointZ.model_validate_json(row["end_point"]),
        point_count=row["point_count"],
        path=path,
        timestamps=timestamps,
        path_tracks=filtered_tracks,
        squawk_runs=squawk_runs,
        raw_point_count=row["raw_point_count"],
        ingest_batch_date=row["ingest_batch_date"],
    )


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.get("/health", summary="Health check")
async def health() -> dict[str, str]:
    """Return `{"status": "ok"}` when the server is running."""
    return {"status": "ok"}


@router.post(
    "/query",
    response_model=QueryResponse,
    summary="Query flights",
    description=(
        "Query flights matching a filter predicate. "
        "Returns a paginated list of flight details ordered by `start_ts` descending. "
        "\n\n"
        "### Pagination\n\n"
        "Use keyset-based cursor pagination: if the response includes a non-null `cursor`, "
        "repeat the same request with that value as `cursor` to fetch the next page. "
        "Stop when `cursor` is `null`.\n\n"
        "### Query DSL\n\n"
        "The `match` field accepts a predicate — a JSON object with exactly one key naming the "
        "predicate type. Predicates can be nested with `and`, `or`, and `not`. "
        "See the schema definitions for the full predicate vocabulary."
    ),
)
async def query_flights(
    body: Annotated[
        QueryRequest,
        Body(
            openapi_examples={
                "no_filter": {
                    "summary": "Most recent flights",
                    "value": {"limit": 10, "include_path": False},
                },
                "aircraft_type_at_airport": {
                    "summary": "B737 family arriving at Heathrow",
                    "value": {
                        "match": {
                            "and": [
                                {"icao_type": ["B738", "B737", "B737M"]},
                                {"ends_within": {"geometry": {"type": "Circle", "coordinates": [-0.4543, 51.4775], "radius": 8000}}},
                            ]
                        },
                        "limit": 50,
                        "include_path": False,
                    },
                },
                "area_and_altitude": {
                    "summary": "High-altitude flights over the UK on a given day",
                    "value": {
                        "match": {
                            "trajectory_intersects": {
                                "geometry": {
                                    "type": "Polygon",
                                    "coordinates": [[[-8, 49], [2, 49], [2, 61], [-8, 61], [-8, 49]]],
                                },
                                "altitude_min_ft": 35000,
                                "time_from": "2026-03-30T00:00:00Z",
                                "time_to": "2026-03-31T00:00:00Z",
                            }
                        },
                        "limit": 100,
                        "include_path": False,
                    },
                },
                "callsign_prefix": {
                    "summary": "British Airways flights (callsign prefix)",
                    "value": {"match": {"callsign_matches": "^BAW"}, "limit": 50, "include_path": False},
                },
                "short_haul": {
                    "summary": "Short flights (under 1 hour)",
                    "value": {"match": {"duration": {"max_s": 3600}}, "limit": 50, "include_path": False},
                },
                "departing_from": {
                    "summary": "Departures from Charles de Gaulle in a time window",
                    "value": {
                        "match": {
                            "starts_within": {
                                "geometry": {"type": "Circle", "coordinates": [2.5479, 49.0097], "radius": 10000},
                                "time_from": "2026-03-30T06:00:00Z",
                                "time_to": "2026-03-30T12:00:00Z",
                            }
                        },
                        "limit": 50,
                        "include_path": False,
                    },
                },
            }
        ),
    ],
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
        SELECT {_FLIGHT_COLS}
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
        flights=[_row_to_detail(r, include_path=body.include_path) for r in result_rows],
        cursor=next_cursor,
    )


@router.get(
    "/flights/{flight_id:path}",
    response_model=FlightDetail,
    summary="Get flight by ID",
    description=(
        "Fetch the full trajectory for a single flight by its `flight_id`. "
        "\n\n"
        "`flight_id` is the value returned in `flight_id` fields from `/query`, "
        "in the form `<icao24>:<start_ts_utc>` — for example, `aabbcc:2025-04-01T10:00:00Z`."
    ),
    responses={
        404: {"description": "No flight exists for the given `flight_id`."},
        422: {"description": "`flight_id` is malformed (missing `:` separator or invalid timestamp)."},
    },
)
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
        SELECT {_FLIGHT_COLS}
        FROM flights f
        WHERE f.icao24 = $1 AND date_trunc('second', f.start_ts) = $2
    """

    row = await pool.fetchrow(sql, icao24, start_ts)
    if row is None:
        raise HTTPException(status_code=404, detail="Flight not found")

    return _row_to_detail(row)


def _p(params: list[Any], val: Any) -> str:
    """Append val to params and return its $n placeholder."""
    params.append(val)
    return f"${len(params)}"


app.include_router(router)
