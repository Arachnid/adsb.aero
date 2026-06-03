"""FastAPI application — health, query, and flight-detail endpoints."""

from __future__ import annotations

import json
import logging
import re
import textwrap
from collections.abc import AsyncGenerator  # noqa: TC003
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta
from typing import TYPE_CHECKING, Annotated, Any

from fastapi import APIRouter, Body, FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse  # noqa: TC002
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
    effective_end: datetime = (
        min(body.end_date, cursor_ts) if cursor_ts is not None else body.end_date
    )

    # Window floor: window_days back from the effective upper bound, then clamped
    # up to start_from if the caller supplied an explicit earliest bound.
    window_floor: datetime = effective_end - timedelta(days=body.window_days)
    if body.start_from is not None and body.start_from > window_floor:
        window_floor = body.start_from

    # Build WHERE clause
    where_parts: list[str] = []

    # Time bounds: window floor (inclusive) and end_date (exclusive).
    where_parts.append(f"f.start_ts >= {_p(params, window_floor)}")
    where_parts.append(f"f.start_ts < {_p(params, body.end_date)}")

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
        # Exception: if window_floor was clamped to start_from we've reached the
        # explicit floor and there is nowhere further to look.
        floored_by_start = body.start_from is not None and window_floor <= body.start_from
        if not floored_by_start:
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
        start_ts: datetime = datetime.fromisoformat(ts_str)
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
