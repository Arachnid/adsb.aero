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
    GeoJSONMultiLineStringZ,
    GeoJSONPointZ,
    IcaoTypeStat,
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
    "f.icao24 || ':' || to_char(f.start_ts AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS\"Z\"')"
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
    f.raw_point_count,
    f.ingest_batch_date,
    numInstants(f.path) AS point_count
"""

_FLIGHT_JOIN = "LEFT JOIN airframes af ON af.icao24 = f.icao24"


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
    """Parse a MobilityDB stepwise tint seqset into per-sub-sequence [[epoch_s, value], ...] lists."""
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
    """Parse a MobilityDB stepwise tfloat seqset into per-sub-sequence [[epoch_s, val], ...] lists."""
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
        point_count=row["point_count"],
        path=path,
        timestamps=timestamps,
        path_tracks=path_tracks,
        path_gs=path_gs,
        path_vr=path_vr,
        path_ias=path_ias,
        squawk_runs=squawk_runs,
        alt_correction_ft=alt_correction_ft,
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
                                    "ends_within": {
                                        "geometry": {
                                            "type": "Circle",
                                            "coordinates": [-0.4543, 51.4775],
                                            "radius": 8000,
                                        }
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
                        "match": {"callsign_matches": "^BAW"},
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
                            "starts_within": {
                                "geometry": {
                                    "type": "Circle",
                                    "coordinates": [2.5479, 49.0097],
                                    "radius": 10000,
                                },
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

    # Global start-time range (always present — validated in QueryRequest)
    where_parts.append(f"start_ts >= {_p(params, body.start_from)}")
    where_parts.append(f"start_ts < {_p(params, body.start_to)}")

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
            f"(f.start_ts < {ts_p} OR (f.start_ts = {ts_p} AND f.icao24 < {icao_p}))"
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

    return _row_to_detail(row)


app.include_router(router)
