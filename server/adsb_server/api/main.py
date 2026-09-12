"""FastAPI application — health, query, and flight-detail endpoints."""

from __future__ import annotations

import json
import logging
import re
import textwrap
import time
from collections.abc import AsyncGenerator  # noqa: TC003
from contextlib import asynccontextmanager
from datetime import UTC, date, datetime, timedelta
from typing import TYPE_CHECKING, Annotated, Any

from fastapi import APIRouter, Body, FastAPI, HTTPException, Path, Query, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from scalar_fastapi import get_scalar_api_reference

from adsb_server.cache import FLIGHT_TTL, QUERY_TTL, ResultCache
from adsb_server.config import get_settings
from adsb_server.db.pool import create_pool
from adsb_server.query.compiler import (
    INNER_SUBQUERY_LIMIT,
    CompiledPredicate,
    GeometryTooLargeError,
    compile_predicate,
)
from adsb_server.query.models import (
    AERODROME_AIRSPACE_TYPES,
    AIRSPACE_LIMIT_REFS,
    AIRSPACE_LIMIT_UNITS,
    AerodromeAirspace,
    Airport,
    AirspaceLimit,
    DataRange,
    FlightDetail,
    GeoJSONMultiLineStringZ,
    GeoJSONPointZ,
    IcaoTypeStat,
    QueryRequest,
    QueryResponse,
    Waypoint,
    decode_cursor,
    encode_cursor,
    to_utc,
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
    "f.icao24 || ':' || to_char(f.start_ts AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS\"Z\"')"
)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
    settings = get_settings()
    settings.init_sentry()
    if settings.log_queries:
        # Root logger stays at WARNING in uvicorn; add a handler directly so
        # INFO messages from adsb_server reach stderr without relying on
        # uvicorn's internal logger structure.
        adsb_logger = logging.getLogger("adsb_server")
        adsb_logger.setLevel(logging.INFO)
        if not adsb_logger.handlers:
            adsb_logger.addHandler(logging.StreamHandler())

    owned = not hasattr(app.state, "pool")
    if owned:
        app.state.pool = await create_pool(settings.asyncpg_dsn)

    cache: ResultCache | None = None
    if settings.redis_url:
        from redis.asyncio import Redis

        cache = ResultCache(Redis.from_url(settings.redis_url, decode_responses=False))
    app.state.redis = cache

    try:
        yield
    finally:
        if owned:
            await app.state.pool.close()
        if cache is not None:
            await cache.close()


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

# Public read-only data: allow any origin so browser-resident clients (and
# agents running inside a page) can call the API directly.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type"],
    max_age=86400,
)

DOCS_URL = "https://adsb.aero/llms.txt"


@app.exception_handler(RequestValidationError)
async def validation_error_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    """Return FastAPI's validation errors with a pointer to the docs.

    Callers that guessed at the request shape — agents especially — recover from
    a bad request far more reliably when the response says where the vocabulary
    is written down. `detail` keeps FastAPI's exact default shape so existing
    clients are unaffected; `documentation` is purely additive.
    """
    return JSONResponse(
        status_code=422,
        content={
            "detail": jsonable_encoder(exc.errors()),
            "documentation": DOCS_URL,
            "hint": (
                "Request body did not validate. The full query vocabulary, with worked "
                f"examples, is at {DOCS_URL} (machine-readable schema: /api/openapi.json)."
            ),
        },
    )


@app.exception_handler(HTTPException)
async def http_error_handler(request: Request, exc: HTTPException) -> JSONResponse:
    """Attach the docs pointer to errors the API raises deliberately.

    llms.txt tells agents that a rejected request explains itself, but only body
    validation failures carried a `hint`; everything raised from the query path —
    an oversized geometry, a statement timeout — came back as a bare `detail`
    string. `detail` keeps its exact shape, so existing clients are unaffected.
    """
    content: dict[str, Any] = {"detail": exc.detail, "documentation": DOCS_URL}
    if isinstance(exc.detail, str):
        content["hint"] = f"{exc.detail} Full query vocabulary: {DOCS_URL}"
    return JSONResponse(status_code=exc.status_code, content=content, headers=exc.headers)


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


def get_cache(request: Request) -> ResultCache | None:
    return getattr(request.app.state, "redis", None)


# The archive's first and last `start_ts` back two things on the query path: the
# default `end_date`, and the end-of-archive test that terminates a cursor walk.
# The underlying MIN/MAX costs ~100 ms and only moves when a nightly ingestion
# batch lands, so it is cached on app state rather than run per request.
_DATA_BOUNDS_TTL_S = 300.0


async def get_data_bounds(request: Request) -> tuple[datetime | None, datetime | None]:
    """Return `(earliest_start_ts, latest_start_ts)`, or `(None, None)` if no flights exist."""
    now = time.monotonic()
    cached: tuple[float, datetime | None, datetime | None] | None = getattr(
        request.app.state, "data_bounds", None
    )
    if cached is not None and now - cached[0] < _DATA_BOUNDS_TTL_S:
        return cached[1], cached[2]

    pool = await get_pool(request)
    row = await pool.fetchrow(
        "SELECT MIN(start_ts) AS first_ts, MAX(start_ts) AS last_ts FROM flights"
    )
    first: datetime | None = row["first_ts"] if row else None
    last: datetime | None = row["last_ts"] if row else None
    request.app.state.data_bounds = (now, first, last)
    return first, last


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
    af.registration,
    af.model,
    af.year,
    af.operator,
    f.start_ts,
    f.end_ts,
    ST_AsGeoJSON(startValue(f.path)::geometry, 6) AS start_point,
    ST_AsGeoJSON(endValue(f.path)::geometry, 6) AS end_point,
    asText(f.path) AS path_text,
    asText(f.path_tracks) AS path_tracks_text,
    asText(f.path_gs) AS path_gs_text,
    asText(f.path_vr) AS path_vr_text,
    asText(f.path_ias) AS path_ias_text,
    asText(f.squawk_seq) AS squawk_seq_text,
    asText(f.alt_correction_ft) AS alt_correction_ft_text,
    asText(f.path_agl_ft) AS path_agl_ft_text,
    f.raw_point_count,
    f.ingest_batch_date,
    sa.ident AS start_airport_ident,
    sa.name  AS start_airport_name,
    ea.ident AS end_airport_ident,
    ea.name  AS end_airport_name,
    numInstants(f.path) AS point_count
"""

_FLIGHT_JOIN = (
    "LEFT JOIN airframes af ON af.icao24 = f.icao24"
    " LEFT JOIN waypoints sa ON sa.id = f.start_airport_ident"
    " LEFT JOIN waypoints ea ON ea.id = f.end_airport_ident"
)

# Raw columns projected by the inner subquery of the two-level intersects plan.
# Excludes large arrays (path_h3, squawk_codes) and generated columns not needed
# by the outer query or _FLIGHT_COLS_OUTER.
_INNER_COLS = """
    f.icao24,
    f.callsign,
    f.icao_type,
    f.emitter_category,
    f.start_ts,
    f.end_ts,
    f.path,
    f.path_tracks,
    f.path_gs,
    f.path_vr,
    f.path_ias,
    f.squawk_seq,
    f.alt_correction_ft,
    f.path_agl_ft,
    f.raw_point_count,
    f.ingest_batch_date,
    sa.ident AS start_airport_ident,
    sa.name  AS start_airport_name,
    ea.ident AS end_airport_ident,
    ea.name  AS end_airport_name,
    af.registration,
    af.model,
    af.year,
    af.operator
"""

# Same derived columns as _FLIGHT_COLS but sourced from the inner subquery (alias f),
# where airframe columns are projected without the af. prefix.
_FLIGHT_COLS_OUTER = f"""
    {FLIGHT_ID_EXPR} AS flight_id,
    f.icao24,
    f.callsign,
    f.icao_type,
    f.emitter_category,
    f.registration,
    f.model,
    f.year,
    f.operator,
    f.start_ts,
    f.end_ts,
    ST_AsGeoJSON(startValue(f.path)::geometry, 6) AS start_point,
    ST_AsGeoJSON(endValue(f.path)::geometry, 6) AS end_point,
    asText(f.path) AS path_text,
    asText(f.path_tracks) AS path_tracks_text,
    asText(f.path_gs) AS path_gs_text,
    asText(f.path_vr) AS path_vr_text,
    asText(f.path_ias) AS path_ias_text,
    asText(f.squawk_seq) AS squawk_seq_text,
    asText(f.alt_correction_ft) AS alt_correction_ft_text,
    asText(f.path_agl_ft) AS path_agl_ft_text,
    f.raw_point_count,
    f.ingest_batch_date,
    f.start_airport_ident,
    f.start_airport_name,
    f.end_airport_ident,
    f.end_airport_name,
    numInstants(f.path) AS point_count
"""


_INSTANT_RE = re.compile(
    r"POINT\s+Z\s*\(\s*([^\s]+)\s+([^\s]+)\s+([^\s]+)\s*\)@([^,\]\)]+)",
    re.IGNORECASE,
)
_SEQ_BLOCK_RE = re.compile(r"\[([^\[\]]+)\]")
_TINT_SERIES_RE = re.compile(r"(-?\d+)@(\d{4}-\d{2}-\d{2}[^,\[\]\{\}]*)")
_TTEXT_INSTANT_RE = re.compile(r"([^@,\[\]]+)@([^,\[\]]+)")
_TFLOAT_INSTANT_RE = re.compile(r"(-?[\d.]+(?:[eE][+-]?\d+)?)@(\d{4}-\d{2}-\d{2}[^,\[\]\{\}]*)")


def _parse_path(path_text: str) -> tuple[GeoJSONMultiLineStringZ, list[list[float]]]:
    """Parse a MobilityDB tgeompoint seqset into a GeoJSON MultiLineString.

    Each `[...]` block in the seqset becomes one sub-sequence element.
    Returns (MultiLineString, per-sequence timestamp lists). Coordinates rounded to 6 dp.
    """
    all_coords: list[list[tuple[float, float, float]]] = []
    all_timestamps: list[list[float]] = []
    for block in _SEQ_BLOCK_RE.finditer(path_text):
        seq_coords: list[tuple[float, float, float]] = []
        seq_ts: list[float] = []
        for m in _INSTANT_RE.finditer(block.group(1)):
            lon = round(float(m.group(1)), 6)
            lat = round(float(m.group(2)), 6)
            alt = round(float(m.group(3)), 6)
            ts_str = m.group(4).strip()
            if ts_str.endswith("+00"):
                ts_str = ts_str + ":00"
            seq_ts.append(datetime.fromisoformat(ts_str).timestamp())
            seq_coords.append((lon, lat, alt))
        if seq_coords:
            all_coords.append(seq_coords)
            all_timestamps.append(seq_ts)
    return GeoJSONMultiLineStringZ(type="MultiLineString", coordinates=all_coords), all_timestamps


def _parse_tint_series(text: str | None) -> list[list[list[float]]] | None:
    """Parse a MobilityDB tint seqset into per-sub-sequence [[epoch_s, value], ...] lists."""
    if not text:
        return None
    result: list[list[list[float]]] = []
    for block in _SEQ_BLOCK_RE.finditer(text):
        seq: list[list[float]] = []
        for m in _TINT_SERIES_RE.finditer(block.group(1)):
            val = int(m.group(1))
            ts_str = m.group(2).strip()
            if ts_str.endswith("+00"):
                ts_str += ":00"
            seq.append([datetime.fromisoformat(ts_str).timestamp(), val])
        if seq:
            result.append(seq)
    return result if result else None


def _parse_squawk_seq(text: str | None) -> list[list[tuple[float, str]]] | None:
    """Parse a MobilityDB ttext seqset into per-sub-sequence [(epoch_s, code), ...] lists."""
    if not text:
        return None
    result: list[list[tuple[float, str]]] = []
    for block in _SEQ_BLOCK_RE.finditer(text):
        seq: list[tuple[float, str]] = []
        for m in _TTEXT_INSTANT_RE.finditer(block.group(1)):
            code = m.group(1).strip().strip('"')
            ts_str = m.group(2).strip()
            if ts_str.endswith("+00"):
                ts_str += ":00"
            seq.append((datetime.fromisoformat(ts_str).timestamp(), code))
        if seq:
            result.append(seq)
    return result if result else None


def _parse_alt_correction(text: str | None) -> list[list[list[float]]] | None:
    """Parse a MobilityDB tfloat seqset into per-sub-sequence [[epoch_s, val], ...] lists."""
    if not text:
        return None
    result: list[list[list[float]]] = []
    for block in _SEQ_BLOCK_RE.finditer(text):
        seq: list[list[float]] = []
        for m in _TFLOAT_INSTANT_RE.finditer(block.group(1)):
            val = float(m.group(1))
            ts_str = m.group(2).strip()
            if ts_str.endswith("+00"):
                ts_str += ":00"
            seq.append([datetime.fromisoformat(ts_str).timestamp(), val])
        if seq:
            result.append(seq)
    return result if result else None


def _row_to_detail(row: asyncpg.Record, include_path: bool = True) -> FlightDetail:
    path = None
    timestamps = None
    path_tracks = None
    path_gs = None
    path_vr = None
    path_ias = None
    squawk_runs = None
    alt_correction_ft = None
    path_agl_ft = None
    if include_path:
        path, timestamps = _parse_path(row["path_text"])
        path_tracks = _parse_tint_series(row["path_tracks_text"])
        path_gs = _parse_tint_series(row["path_gs_text"])
        path_vr = _parse_tint_series(row["path_vr_text"])
        path_ias = _parse_tint_series(row["path_ias_text"])
        squawk_runs = _parse_squawk_seq(row["squawk_seq_text"])
        alt_correction_ft = _parse_alt_correction(row["alt_correction_ft_text"])
        path_agl_ft = _parse_alt_correction(row["path_agl_ft_text"])
    return FlightDetail(
        flight_id=row["flight_id"],
        icao24=row["icao24"],
        callsign=row["callsign"],
        icao_type=row["icao_type"],
        emitter_category=row["emitter_category"],
        registration=row["registration"],
        model=row["model"],
        year=row["year"],
        operator=row["operator"],
        start_ts=row["start_ts"],
        end_ts=row["end_ts"],
        start_point=GeoJSONPointZ.model_validate_json(row["start_point"]),
        end_point=GeoJSONPointZ.model_validate_json(row["end_point"]),
        start_airport_ident=row["start_airport_ident"],
        start_airport_name=row["start_airport_name"],
        end_airport_ident=row["end_airport_ident"],
        end_airport_name=row["end_airport_name"],
        point_count=row["point_count"],
        path=path,
        timestamps=timestamps,
        path_tracks=path_tracks,
        path_gs=path_gs,
        path_vr=path_vr,
        path_ias=path_ias,
        squawk_runs=squawk_runs,
        alt_correction_ft=alt_correction_ft,
        path_agl_ft=path_agl_ft,
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


@router.get(
    "/icao-types",
    response_model=list[IcaoTypeStat],
    summary="ICAO type counts for a date range",
    description=(
        "Return all ICAO aircraft type designators observed between `start` and `end` (inclusive), "
        "with the total flight count and a representative model name for each. "
        "Sorted by count descending. Backed by a pre-aggregated per-day stats table — fast "
        "even over wide date ranges."
    ),
)
async def get_icao_types(
    start: date,
    end: date,
    request: Request,
) -> list[IcaoTypeStat]:
    pool = await get_pool(request)
    rows = await pool.fetch(
        """
        SELECT icao_type,
               mode() WITHIN GROUP (ORDER BY model) AS model,
               SUM(flight_count)::int AS count
        FROM icao_type_stats
        WHERE day >= $1 AND day <= $2
        GROUP BY icao_type
        ORDER BY count DESC
        """,
        start,
        end,
    )
    return [
        IcaoTypeStat(icao_type=r["icao_type"], model=r["model"], count=r["count"]) for r in rows
    ]


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
                                {
                                    "endpoint_within": {
                                        "mode": "end",
                                        "geometry": {
                                            "type": "Circle",
                                            "coordinates": [-0.4543, 51.4775],
                                            "radius": 8000,
                                        },
                                    }
                                },
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
                                    "coordinates": [
                                        [[-8, 49], [2, 49], [2, 61], [-8, 61], [-8, 49]]
                                    ],
                                },
                                "altitude_min": 35000,
                                "altitude_min_ref": "ft",
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
                    "value": {
                        "match": {"callsign_prefix": "BAW"},
                        "limit": 50,
                        "include_path": False,
                    },
                },
                "short_haul": {
                    "summary": "Short flights (under 1 hour)",
                    "value": {
                        "match": {"duration": {"max_s": 3600}},
                        "limit": 50,
                        "include_path": False,
                    },
                },
                "departing_from": {
                    "summary": "Departures from Charles de Gaulle in a time window",
                    "value": {
                        "match": {
                            "endpoint_within": {
                                "mode": "start",
                                "geometry": {
                                    "type": "Circle",
                                    "coordinates": [2.5479, 49.0097],
                                    "radius": 10000,
                                },
                                "start_time_from": "2026-03-30T06:00:00Z",
                                "start_time_to": "2026-03-30T12:00:00Z",
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
    cache = get_cache(request)

    # Resolve the default end_date *before* the cache key is computed: the key has
    # to name the window actually searched, or a request that omitted end_date
    # would keep serving the same window for QUERY_TTL after a new batch lands.
    earliest_ts, latest_ts = await get_data_bounds(request)
    if body.end_date is None:
        # end_date is exclusive, so step just past the newest flight to include it.
        end_date = (
            latest_ts + timedelta(microseconds=1) if latest_ts is not None else datetime.now(UTC)
        )
        body = body.model_copy(update={"end_date": end_date})
    else:
        end_date = body.end_date

    cache_key = ResultCache.query_key(body.model_dump_json()) if cache else ""
    if cache and (cached := await cache.get(cache_key)):
        return QueryResponse.model_validate_json(cached)

    params: list[Any] = []

    # Decode cursor to get its timestamp, used both for keyset dedup and window anchoring.
    cursor_ts: datetime | None = None
    cursor_icao: str | None = None
    if body.cursor is not None:
        cursor_ts, cursor_icao = decode_cursor(body.cursor)

    # Effective upper bound: the earlier of end_date and the cursor position.
    # This anchors the window floor so each page slides back by window_days.
    effective_end: datetime = min(end_date, cursor_ts) if cursor_ts is not None else end_date

    # Window floor: window_days back from the effective upper bound, then clamped
    # up to start_from if the caller supplied an explicit earliest bound.
    window_floor: datetime = effective_end - timedelta(days=body.window_days)
    if body.start_from is not None and body.start_from > window_floor:
        window_floor = body.start_from

    # Build WHERE clause
    where_parts: list[str] = []

    # Time bounds: window floor (inclusive) and end_date (exclusive).
    where_parts.append(f"f.start_ts >= {_p(params, window_floor)}")
    where_parts.append(f"f.start_ts < {_p(params, end_date)}")

    compiled: CompiledPredicate | None = None
    if body.match is not None:
        try:
            compiled = compile_predicate(body.match, params)
        except GeometryTooLargeError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        where_parts.append(f"({compiled})")

    limit_p = _p(params, body.limit + 1)

    ctes = compiled.ctes if compiled is not None else []
    with_clause = (
        "WITH " + ", ".join(f"{name} AS ({cte_body})" for name, cte_body in ctes) + "\n"
        if ctes
        else ""
    )

    if compiled is not None and compiled.outer_parts:
        # Two-level plan: inner subquery collects H3-prefiltered candidates sorted
        # by start_ts; outer applies eIntersects (and dwell/squawk correlations)
        # only to as many rows as needed to satisfy LIMIT.  The inner LIMIT is
        # large enough to never truncate real result sets while preventing
        # PostgreSQL from inlining the subquery.
        cursor_parts: list[str] = []
        if cursor_ts is not None and cursor_icao is not None:
            ts_p = _p(params, cursor_ts)
            icao_p = _p(params, cursor_icao)
            cursor_parts.append(
                f"(f.start_ts < {ts_p} OR (f.start_ts = {ts_p} AND f.icao24 < {icao_p}))"
            )
        inner_where = "WHERE " + " AND ".join(where_parts + cursor_parts)
        outer_where = "WHERE " + " AND ".join(f"({p})" for p in compiled.outer_parts)
        from_extras = (", " + ", ".join(name for name, _ in ctes)) if ctes else ""
        sql = f"""
            {with_clause}SELECT {_FLIGHT_COLS_OUTER}
            FROM (
                SELECT {_INNER_COLS}
                FROM flights f {_FLIGHT_JOIN}
                {inner_where}
                ORDER BY f.start_ts DESC, f.icao24 DESC
                LIMIT {INNER_SUBQUERY_LIMIT}
            ) f{from_extras}
            {outer_where}
            ORDER BY f.start_ts DESC, f.icao24 DESC
            LIMIT {limit_p}
        """
    else:
        # Flat single-level query.
        if cursor_ts is not None and cursor_icao is not None:
            ts_p = _p(params, cursor_ts)
            icao_p = _p(params, cursor_icao)
            where_parts.append(
                f"(f.start_ts < {ts_p} OR (f.start_ts = {ts_p} AND f.icao24 < {icao_p}))"
            )
        where_sql = ("WHERE " + " AND ".join(where_parts)) if where_parts else ""
        from_extras = (", " + ", ".join(name for name, _ in ctes)) if ctes else ""
        sql = f"""
            {with_clause}SELECT {_FLIGHT_COLS}
            FROM flights f {_FLIGHT_JOIN}{from_extras}
            {where_sql}
            ORDER BY f.start_ts DESC, f.icao24 DESC
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

    import asyncpg

    try:
        async with pool.acquire() as conn:
            await conn.execute("SET statement_timeout = '15s'")
            rows = await conn.fetch(sql, *params)
    except asyncpg.exceptions.QueryCanceledError as exc:
        raise HTTPException(
            status_code=504,
            detail="Query timed out. Reduce the search area or time range.",
        ) from exc

    has_more = len(rows) > body.limit
    result_rows = rows[: body.limit]

    next_cursor: str | None = None
    if has_more and result_rows:
        # Intra-window: more results exist; cursor points to the last returned row.
        last = result_rows[-1]
        next_cursor = encode_cursor(last["start_ts"], last["icao24"])
    else:
        # Window exhausted.  Emit a sentinel cursor pointing to window_floor so
        # the next call automatically searches [window_floor - window_days, window_floor).
        # Two things stop the walk, and both must, or "page until cursor is null"
        # never terminates: an explicit start_from floor, and running off the
        # start of the archive.
        floored_by_start = body.start_from is not None and window_floor <= body.start_from
        exhausted_archive = earliest_ts is None or window_floor <= earliest_ts
        if not floored_by_start and not exhausted_archive:
            next_cursor = encode_cursor(window_floor, "")

    response = QueryResponse(
        flights=[_row_to_detail(r, include_path=body.include_path) for r in result_rows],
        cursor=next_cursor,
        window_from=window_floor,
    )
    if cache:
        await cache.set(cache_key, response.model_dump_json().encode(), QUERY_TTL)
    return response


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
        422: {
            "description": "`flight_id` is malformed (missing `:` separator or invalid timestamp)."
        },
    },
)
async def get_flight(
    flight_id: str,
    request: Request,
) -> FlightDetail:
    pool = await get_pool(request)
    cache = get_cache(request)

    cache_key = ResultCache.flight_key(flight_id)
    if cache and (cached := await cache.get(cache_key)):
        return FlightDetail.model_validate_json(cached)

    # Parse flight_id: "icao24:ISO8601"
    colon_idx = flight_id.find(":")
    if colon_idx < 0:
        raise HTTPException(status_code=422, detail="Malformed flight_id")

    icao24 = flight_id[:colon_idx]
    ts_str = flight_id[colon_idx + 1 :]

    try:
        start_ts: datetime = to_utc(datetime.fromisoformat(ts_str))
    except ValueError:
        raise HTTPException(status_code=422, detail="Malformed flight_id timestamp") from None

    sql = f"""
        SELECT {_FLIGHT_COLS}
        FROM flights f {_FLIGHT_JOIN}
        WHERE f.icao24 = $1 AND date_trunc('second', f.start_ts) = $2
    """

    row = await pool.fetchrow(sql, icao24, start_ts)
    if row is None:
        raise HTTPException(status_code=404, detail="Flight not found")

    detail = _row_to_detail(row)
    if cache:
        await cache.set(cache_key, detail.model_dump_json().encode(), FLIGHT_TTL)
    return detail


_WAYPOINT_COLS = """
    id, kind, name, ident, iata_code, type_code, country,
    ST_X(location) AS lon, ST_Y(location) AS lat,
    elevation_ft, frequency_mhz, compulsory
"""


def _row_to_waypoint(row: asyncpg.Record) -> Waypoint:
    return Waypoint(
        id=row["id"],
        kind=row["kind"],
        name=row["name"],
        ident=row["ident"],
        iata_code=row["iata_code"],
        type_code=row["type_code"],
        country=row["country"],
        lon=row["lon"],
        lat=row["lat"],
        elevation_ft=row["elevation_ft"],
        frequency_mhz=row["frequency_mhz"],
        compulsory=row["compulsory"],
    )


def _build_tsquery(q: str) -> str | None:
    """Convert a user search string into a 'simple' prefix tsquery.

    Each whitespace-separated token becomes a prefix term (token:*), joined
    with AND.  Non-word characters are stripped to avoid tsquery parse errors.
    Returns None if no usable tokens remain.
    """
    words = re.sub(r"[^\w\s]", " ", q).split()
    return " & ".join(f"{w}:*" for w in words) if words else None


@router.get(
    "/waypoints/search",
    response_model=list[Waypoint],
    summary="Waypoint typeahead search",
    description=(
        "Search airports, navaids, and VFR reporting points by name, ICAO code, "
        "IATA code, or navaid identifier using prefix matching. "
        "Optionally filter by kind. Results ordered by kind priority then name."
    ),
)
async def search_waypoints(
    request: Request,
    q: Annotated[str, Query(min_length=1, max_length=100, description="Search query.")],
    kinds: Annotated[
        str | None,
        Query(description="Comma-separated kinds to include: airport,navaid,reporting_point."),
    ] = None,
    limit: Annotated[int, Query(ge=1, le=20, description="Max results.")] = 10,
) -> list[Waypoint]:
    tsquery = _build_tsquery(q)
    if tsquery is None:
        return []
    pool = await get_pool(request)
    kind_filter = [k.strip() for k in kinds.split(",") if k.strip()] if kinds else None
    # Waypoints + airspace centroids via UNION ALL wrapped in a subquery
    # so we can ORDER BY a CASE expression (PostgreSQL requires this).
    sql = f"""
        SELECT * FROM (
            SELECT {_WAYPOINT_COLS}
            FROM waypoints
            WHERE search_vec @@ to_tsquery('simple', $1)
              AND ($3::text[] IS NULL OR kind = ANY($3::text[]))
              AND (type_code IS NULL OR type_code != 8)
            UNION ALL
            SELECT id, 'airspace' AS kind, name, NULL AS ident,
                   NULL AS iata_code, type_code, country,
                   ST_X(ST_Centroid(geometry)) AS lon,
                   ST_Y(ST_Centroid(geometry)) AS lat,
                   NULL AS elevation_ft, NULL AS frequency_mhz,
                   NULL AS compulsory
            FROM airspaces
            WHERE search_vec @@ to_tsquery('simple', $1)
              AND ($3::text[] IS NULL OR 'airspace' = ANY($3::text[]))
        ) sub
        ORDER BY
            CASE kind
                WHEN 'airport' THEN 1 WHEN 'navaid' THEN 2
                WHEN 'reporting_point' THEN 3 ELSE 4
            END,
            name
        LIMIT $2
    """
    rows = await pool.fetch(sql, tsquery, limit, kind_filter)
    return [_row_to_waypoint(r) for r in rows]


@router.get(
    "/waypoints/{waypoint_id}",
    response_model=Waypoint,
    summary="Look up a waypoint by OpenAIP ID",
    description="Return a single waypoint (airport, navaid, or reporting point) by its OpenAIP ID.",
)
async def get_waypoint(waypoint_id: str, request: Request) -> Waypoint:
    pool = await get_pool(request)
    row = await pool.fetchrow(
        f"SELECT {_WAYPOINT_COLS} FROM waypoints WHERE id = $1",
        waypoint_id,
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Waypoint not found")
    return _row_to_waypoint(row)


_AIRPORT_LOOKUP_SQL = f"""
    SELECT {_WAYPOINT_COLS}
    FROM waypoints
    WHERE kind = 'airport'
      AND (upper(ident) = upper($1) OR upper(iata_code) = upper($1))
    ORDER BY (upper(ident) = upper($1)) DESC, name
    LIMIT 1
"""

# Aerodrome airspaces containing the field's reference point, most specific
# (smallest) first.  Area is computed on the geography type so it is real
# ground area rather than square degrees.
_AERODROME_AIRSPACE_SQL = """
    SELECT id, name, type_code, icao_class,
           lower_limit_value, lower_limit_unit, lower_limit_ref,
           upper_limit_value, upper_limit_unit, upper_limit_ref,
           ST_Area(geometry::geography) / 1e6 AS area_km2,
           ST_AsGeoJSON(geometry) AS geojson
    FROM airspaces
    WHERE type_code = ANY($1::int[])
      AND ST_Intersects(geometry, ST_SetSRID(ST_MakePoint($2, $3), 4326))
    ORDER BY area_km2
"""


def _airspace_limit(value: int | None, unit: int | None, ref: int | None) -> AirspaceLimit | None:
    """Decode OpenAIP's numeric limit codes into a symbolic limit.

    Returns None when the limit is absent or uses a code we don't recognise —
    a wrong altitude is worse than a missing one.
    """
    if value is None or unit is None:
        return None
    unit_name = AIRSPACE_LIMIT_UNITS.get(unit)
    if unit_name is None:
        return None
    return AirspaceLimit(
        value=value,
        unit=unit_name,
        ref=AIRSPACE_LIMIT_REFS.get(ref if ref is not None else -1, "msl"),
    )


async def _aerodrome_airspaces(
    pool: asyncpg.Pool, lon: float, lat: float
) -> list[AerodromeAirspace]:
    rows = await pool.fetch(
        _AERODROME_AIRSPACE_SQL,
        list(AERODROME_AIRSPACE_TYPES),
        lon,
        lat,
    )
    return [
        AerodromeAirspace(
            id=r["id"],
            name=r["name"],
            type_code=r["type_code"],
            type_name=AERODROME_AIRSPACE_TYPES[r["type_code"]],
            icao_class=r["icao_class"],
            lower_limit=_airspace_limit(
                r["lower_limit_value"], r["lower_limit_unit"], r["lower_limit_ref"]
            ),
            upper_limit=_airspace_limit(
                r["upper_limit_value"], r["upper_limit_unit"], r["upper_limit_ref"]
            ),
            area_km2=round(r["area_km2"], 3),
            geometry=json.loads(r["geojson"]),
        )
        for r in rows
    ]


@router.get(
    "/airports/{code}",
    response_model=Airport,
    summary="Look up an airport by ICAO or IATA code",
    description=(
        "Resolve an airport code to its position **and the aerodrome airspaces around it**, "
        "in one call. Matching is case-insensitive; ICAO codes take precedence over IATA.\n\n"
        "### Use this to build departure/arrival queries\n\n"
        "For 'who flew into X' or 'who departed X', use `airspaces[0].geometry` as the "
        "`geometry` of an `endpoint_within` predicate. The ATZ, MATZ, or CTR is the published "
        "boundary that traffic to and from the field actually crosses, so it is a far better "
        "match than guessing a radius — it is correctly shaped and correctly sized for that "
        "particular field.\n\n"
        "`airspaces` is ordered most-specific-first (smallest ground area). It is empty for "
        "fields with no published aerodrome airspace, such as most unlicensed strips; only "
        "then fall back to a `Circle` centred on `lon`/`lat`."
    ),
    responses={404: {"description": "No airport matches the given code."}},
)
async def get_airport(
    code: Annotated[
        str,
        Path(
            min_length=2,
            max_length=8,
            description="ICAO code (e.g. `EGLL`, `EGHP`) or IATA code (e.g. `LHR`).",
            examples=["EGHP"],
        ),
    ],
    request: Request,
) -> Airport:
    pool = await get_pool(request)
    row = await pool.fetchrow(_AIRPORT_LOOKUP_SQL, code)
    if row is None:
        raise HTTPException(
            status_code=404,
            detail=(
                f"No airport with ICAO or IATA code {code!r}. "
                "Search by name with GET /api/v1/waypoints/search?q=..."
            ),
        )
    waypoint = _row_to_waypoint(row)
    return Airport(
        **waypoint.model_dump(),
        airspaces=await _aerodrome_airspaces(pool, waypoint.lon, waypoint.lat),
    )


@router.get(
    "/airspaces",
    summary="Find airspaces near a point",
    description=(
        "Return airspaces whose geometry intersects or is within `dist` km of the given "
        "coordinate.  Response shape matches the OpenAIP /api/airspaces proxy it replaces."
    ),
)
async def get_airspaces(
    pos: Annotated[str, Query(description="Latitude,longitude (decimal degrees).")],
    dist: Annotated[float, Query(ge=0, le=100, description="Search radius in km.")] = 1.0,
    request: Request = ...,  # type: ignore[assignment]
) -> dict[str, list[dict[str, object]]]:
    try:
        lat_s, lng_s = pos.split(",", 1)
        lat, lng = float(lat_s.strip()), float(lng_s.strip())
    except ValueError, AttributeError:
        raise HTTPException(status_code=422, detail="pos must be 'lat,lng'") from None
    pool = await get_pool(request)
    rows = await pool.fetch(
        """
        SELECT id, name, type_code, icao_class, country,
               lower_limit_value, lower_limit_unit,
               upper_limit_value, upper_limit_unit,
               ST_AsGeoJSON(geometry) AS geojson
        FROM airspaces
        WHERE ST_DWithin(
            geometry::geography,
            ST_SetSRID(ST_MakePoint($2, $1), 4326)::geography,
            $3
        )
        ORDER BY COALESCE(lower_limit_value, 0)
        LIMIT 50
        """,
        lat,
        lng,
        dist * 1000.0,
    )

    def _limit(value: int | None, unit: int | None) -> dict[str, int] | None:
        if value is None or unit is None:
            return None
        return {"value": value, "unit": unit}

    items = [
        {
            "_id": r["id"],
            "name": r["name"],
            "type": r["type_code"],
            "icaoClass": r["icao_class"],
            "country": r["country"],
            "lowerLimit": _limit(r["lower_limit_value"], r["lower_limit_unit"]),
            "upperLimit": _limit(r["upper_limit_value"], r["upper_limit_unit"]),
            "geometry": json.loads(r["geojson"]),
        }
        for r in rows
    ]
    return {"items": items}


app.include_router(router)
