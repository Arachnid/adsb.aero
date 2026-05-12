"""FastAPI application — health, query, and flight-detail endpoints."""

from __future__ import annotations

import json
import logging
import re
import textwrap
from collections.abc import AsyncGenerator  # noqa: TC003
from contextlib import asynccontextmanager
from datetime import date, datetime
from typing import TYPE_CHECKING, Annotated, Any

from fastapi import APIRouter, Body, FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse  # noqa: TC002
from scalar_fastapi import get_scalar_api_reference

from adsb_server.config import get_settings
from adsb_server.db.pool import create_pool
from adsb_server.query.compiler import CompiledPredicate, compile_predicate
from adsb_server.query.models import (
    DataRange,
    FlightDetail,
    GeoJSONLineStringZ,
    GeoJSONPointZ,
    QueryRequest,
    QueryResponse,
    decode_cursor,
    encode_cursor,
)

if TYPE_CHECKING:
    import asyncpg

logger = logging.getLogger(__name__)


def _p(params: list[Any], val: Any) -> str:
    """Append val to params and return its $n placeholder."""
    params.append(val)
    return f"${len(params)}"

# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------

FLIGHT_ID_EXPR = (
    "icao24 || ':' || to_char(start_ts AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS\"Z\"')"
)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    settings = get_settings()
    if settings.log_queries:
        # Uvicorn only configures its own loggers; root stays at WARNING.
        # Attach uvicorn's handler to adsb_server so INFO messages are visible.
        adsb_logger = logging.getLogger("adsb_server")
        adsb_logger.setLevel(logging.INFO)
        for handler in logging.getLogger("uvicorn").handlers:
            adsb_logger.addHandler(handler)

    owned = not hasattr(app.state, "pool")
    if owned:
        app.state.pool = await create_pool(settings.asyncpg_dsn)
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

# Columns selected by both /query and /flights/{id}.
# start_point and end_point are derived from the first/last instant of the tgeompoint.
# path_text and path_tracks_text are the MobilityDB text representations, parsed in Python.
_FLIGHT_COLS = f"""
    {FLIGHT_ID_EXPR} AS flight_id,
    f.icao24,
    f.callsign,
    f.icao_type,
    f.emitter_category,
    f.start_ts,
    f.end_ts,
    ST_AsGeoJSON(startValue(f.path)::geometry, 6) AS start_point,
    ST_AsGeoJSON(endValue(f.path)::geometry, 6) AS end_point,
    asText(f.path) AS path_text,
    asText(f.path_tracks) AS path_tracks_text,
    f.squawk_runs,
    f.raw_point_count,
    f.ingest_batch_date,
    numInstants(f.path) AS point_count
"""


_INSTANT_RE = re.compile(
    r"POINT\s+Z\s*\(\s*([^\s]+)\s+([^\s]+)\s+([^\s]+)\s*\)@([^,\]\)]+)",
    re.IGNORECASE,
)
_TINT_INSTANT_RE = re.compile(r"(-?\d+)@")


def _parse_path(
    path_text: str,
    path_tracks_text: str,
) -> tuple[GeoJSONLineStringZ, list[float], list[int]]:
    """Parse MobilityDB tgeompoint and tint text representations.

    path_text format:    '[POINT Z (lon lat alt)@YYYY-MM-DD HH:MM:SS+00, ...]'
    path_tracks_text:    '[val@YYYY-MM-DD HH:MM:SS+00, ...]'

    Returns (GeoJSON LineString, timestamps as unix epochs, track angles).
    Coordinates rounded to 6 decimal places.
    """
    coords_3d: list[tuple[float, float, float]] = []
    timestamps: list[float] = []
    for m in _INSTANT_RE.finditer(path_text):
        lon = round(float(m.group(1)), 6)
        lat = round(float(m.group(2)), 6)
        alt = round(float(m.group(3)), 6)
        ts_str = m.group(4).strip()
        # Normalise "+00" → "+00:00" so fromisoformat accepts it
        if ts_str.endswith("+00"):
            ts_str = ts_str + ":00"
        timestamps.append(datetime.fromisoformat(ts_str).timestamp())
        coords_3d.append((lon, lat, alt))

    path_tracks = [int(m.group(1)) for m in _TINT_INSTANT_RE.finditer(path_tracks_text)]

    return GeoJSONLineStringZ(type="LineString", coordinates=coords_3d), timestamps, path_tracks


def _row_to_detail(row: asyncpg.Record, include_path: bool = True) -> FlightDetail:
    path = None
    timestamps = None
    filtered_tracks = None
    squawk_runs = None
    if include_path:
        path, timestamps, filtered_tracks = _parse_path(row["path_text"], row["path_tracks_text"])
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


@router.get(
    "/data-range",
    response_model=DataRange,
    summary="Data availability range",
    description="Return the earliest and latest dates for which flight data exists in the archive.",
)
async def get_data_range(request: Request) -> DataRange:
    pool = await get_pool(request)
    row = await pool.fetchrow(
        "SELECT MIN(start_ts)::date AS first_date, MAX(end_ts)::date AS last_date FROM flights"
    )
    first: date | None = row["first_date"] if row else None
    last: date | None = row["last_date"] if row else None
    return DataRange(first_date=first, last_date=last)


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
                                {"ends_within": {"geometry": {"type": "Circle", "coordinates": [-0.4543, 51.4775], "radius": 8000}}},  # noqa: E501
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
                                    "coordinates": [[[-8, 49], [2, 49], [2, 61], [-8, 61], [-8, 49]]],  # noqa: E501
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
                    "value": {"match": {"callsign_matches": "^BAW"}, "limit": 50, "include_path": False},  # noqa: E501
                },
                "short_haul": {
                    "summary": "Short flights (under 1 hour)",
                    "value": {"match": {"duration": {"max_s": 3600}}, "limit": 50, "include_path": False},  # noqa: E501
                },
                "departing_from": {
                    "summary": "Departures from Charles de Gaulle in a time window",
                    "value": {
                        "match": {
                            "starts_within": {
                                "geometry": {"type": "Circle", "coordinates": [2.5479, 49.0097], "radius": 10000},  # noqa: E501
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
    compiled: CompiledPredicate | None = None
    if body.match is not None:
        compiled = compile_predicate(body.match, params)
        where_parts.append(f"({compiled})")

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

    ctes = compiled.ctes if compiled is not None else []
    with_clause = (
        "WITH " + ", ".join(f"{name} AS ({cte_body})" for name, cte_body in ctes) + "\n"
        if ctes
        else ""
    )
    from_extras = (", " + ", ".join(name for name, _ in ctes)) if ctes else ""

    sql = f"""
        {with_clause}SELECT {_FLIGHT_COLS}
        FROM flights f{from_extras}
        {where_sql}
        ORDER BY start_ts DESC, icao24 DESC
        LIMIT {limit_p}
    """

    if get_settings().log_queries:
        dsl = body.match.model_dump(mode="json") if body.match is not None else None
        logger.info(
            "query dsl=%s sql=%s params=%s",
            json.dumps(dsl),
            textwrap.dedent(sql).strip(),
            params,
        )

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
        422: {"description": "`flight_id` is malformed (missing `:` separator or invalid timestamp)."},  # noqa: E501
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
        raise HTTPException(status_code=422, detail="Malformed flight_id timestamp") from None

    sql = f"""
        SELECT {_FLIGHT_COLS}
        FROM flights f
        WHERE f.icao24 = $1 AND date_trunc('second', f.start_ts) = $2
    """

    row = await pool.fetchrow(sql, icao24, start_ts)
    if row is None:
        raise HTTPException(status_code=404, detail="Flight not found")

    return _row_to_detail(row)


app.include_router(router)
