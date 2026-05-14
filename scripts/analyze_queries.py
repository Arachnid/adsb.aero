#!/usr/bin/env python3
"""Analyze representative DSL queries against the live Postgres instance.

Compiles each query through compile_predicate, assembles the full SQL as the
API does, then runs EXPLAIN (ANALYZE, BUFFERS) and prints the plan.  Useful for
identifying missing indexes or poor cardinality estimates.

Usage (from repo root, venv activated):
    python scripts/analyze_queries.py [--dsn postgresql://adsb:...@localhost/adsb]
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import textwrap
from datetime import datetime, timezone
from typing import Any

def _dt(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00")).replace(tzinfo=timezone.utc)

# Allow running from repo root without installing the package
sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent.parent / "server"))

import asyncpg  # noqa: E402

from adsb_server.query.compiler import CompiledPredicate, compile_predicate  # noqa: E402
from adsb_server.query.models import (  # noqa: E402
    AndPredicate,
    CircleGeometry,
    Duration,
    GeoJSONPolygon,
    IcaoType,
    SpatioTemporalAltitudeValue,
    SpatioTemporalValue,
    StartsWithin,
    TrajectoryIntersects,
    TrajectoryWithin,
)

# ---------------------------------------------------------------------------
# SQL assembly (mirrors api/main.py exactly)
# ---------------------------------------------------------------------------

FLIGHT_ID_EXPR = (
    "icao24 || ':' || to_char(start_ts AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS\"Z\"')"
)
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
    asText(f.path_gs) AS path_gs_text,
    asText(f.path_vr) AS path_vr_text,
    asText(f.path_ias) AS path_ias_text,
    asText(f.squawk_seq) AS squawk_seq_text,
    asText(f.alt_correction_ft) AS alt_correction_ft_text,
    f.raw_point_count,
    f.ingest_batch_date,
    numInstants(f.path) AS point_count
"""


def _p(params: list[Any], val: Any) -> str:
    params.append(val)
    return f"${len(params)}"


def build_sql(
    pred: Any,
    start_from: datetime,
    start_to: datetime,
    limit: int = 100,
) -> tuple[str, list[Any]]:
    """Compile a predicate and assemble the full SELECT statement.

    Replicates the exact WHERE-building logic from api/main.py, including the
    mandatory start_ts range that is always prepended before the compiled predicate.
    """
    params: list[Any] = []
    where_parts: list[str] = []

    # Global start-time range — always first, matches API behaviour exactly
    where_parts.append(f"start_ts >= {_p(params, start_from)}")
    where_parts.append(f"start_ts < {_p(params, start_to)}")

    compiled: CompiledPredicate = compile_predicate(pred, params)
    where_parts.append(f"({compiled})")

    where_sql = "WHERE " + " AND ".join(where_parts)
    limit_p = _p(params, limit)

    ctes = compiled.ctes
    with_clause = (
        "WITH " + ", ".join(f"{name} AS ({body})" for name, body in ctes) + "\n"
        if ctes
        else ""
    )
    from_extras = (", " + ", ".join(name for name, _ in ctes)) if ctes else ""

    sql = textwrap.dedent(f"""
        {with_clause}SELECT {_FLIGHT_COLS}
        FROM flights f{from_extras}
        {where_sql}
        ORDER BY start_ts DESC, icao24 DESC
        LIMIT {limit_p}
    """).strip()
    return sql, params


# ---------------------------------------------------------------------------
# Representative test cases
# ---------------------------------------------------------------------------

# A polygon over the UK
_UK_POLYGON = GeoJSONPolygon(
    type="Polygon",
    coordinates=[[
        [-6.0, 49.5], [2.5, 49.5], [2.5, 59.5], [-6.0, 59.5], [-6.0, 49.5],
    ]],
)

# Heathrow circle (~20 km)
_HEATHROW = CircleGeometry(type="Circle", coordinates=[-0.4543, 51.4700], radius=20_000)

# One-week time window — all queries are scoped to this to match typical frontend usage
_WEEK_FROM = _dt("2026-05-08T00:00:00Z")
_WEEK_TO = _dt("2026-05-13T00:00:00Z")


def _and(*preds: Any) -> AndPredicate:
    return AndPredicate.model_validate({"and": list(preds)})


def _week_and(*preds: Any) -> AndPredicate:
    """Wrap predicates in an AND with the one-week time window."""
    time_pred = TrajectoryIntersects(trajectory_intersects=SpatioTemporalAltitudeValue(
        time_from=_WEEK_FROM, time_to=_WEEK_TO,
    ))
    return _and(time_pred, *preds)


CASES: list[tuple[str, Any]] = [
    # 1. Time window only — exercises B-tree on start_ts/end_ts + partition pruning
    (
        "time_window_only",
        TrajectoryIntersects(trajectory_intersects=SpatioTemporalAltitudeValue(
            time_from=_WEEK_FROM,
            time_to=_WEEK_TO,
        )),
    ),

    # 2. ICAO type + time window — B-tree on icao_type
    (
        "icao_type_B738",
        _week_and(IcaoType(icao_type=["B738", "B737", "B736", "B739"])),
    ),

    # 3. Starts within circle (Heathrow) + time — GIST index on startValue(path)
    (
        "starts_within_circle",
        StartsWithin(starts_within=SpatioTemporalValue(
            geometry=_HEATHROW,
            time_from=_WEEK_FROM,
            time_to=_WEEK_TO,
        )),
    ),

    # 4. Trajectory intersects polygon (UK), no altitude — GIST index on path
    (
        "trajectory_intersects_polygon",
        TrajectoryIntersects(trajectory_intersects=SpatioTemporalAltitudeValue(
            geometry=_UK_POLYGON,
            time_from=_WEEK_FROM, time_to=_WEEK_TO,
        )),
    ),

    # 5. Trajectory intersects polygon + FL altitude (FL100-FL200)
    #    Uses STBOX Z dimension — exercises MobilityDB GiST index
    (
        "trajectory_intersects_polygon_FL",
        TrajectoryIntersects(trajectory_intersects=SpatioTemporalAltitudeValue(
            geometry=_UK_POLYGON,
            altitude_min=100, altitude_min_ref="fl",
            altitude_max=200, altitude_max_ref="fl",
            time_from=_WEEK_FROM, time_to=_WEEK_TO,
        )),
    ),

    # 6. Trajectory intersects polygon + ft/QNH altitude (10000–20000 ft)
    #    Uses atvalues on corrected-altitude tfloat; no Z index path
    (
        "trajectory_intersects_polygon_ft",
        TrajectoryIntersects(trajectory_intersects=SpatioTemporalAltitudeValue(
            geometry=_UK_POLYGON,
            altitude_min=10_000, altitude_min_ref="ft",
            altitude_max=20_000, altitude_max_ref="ft",
            time_from=_WEEK_FROM, time_to=_WEEK_TO,
        )),
    ),

    # 7. Trajectory intersects polygon + FL altitude + dwell ≥ 5 min
    (
        "trajectory_intersects_polygon_FL_dwell",
        TrajectoryIntersects(trajectory_intersects=SpatioTemporalAltitudeValue(
            geometry=_UK_POLYGON,
            altitude_min=100, altitude_min_ref="fl",
            altitude_max=200, altitude_max_ref="fl",
            dwell_min_s=300.0,
            time_from=_WEEK_FROM, time_to=_WEEK_TO,
        )),
    ),

    # 8. Trajectory within polygon — ST_Within on full trajectory
    (
        "trajectory_within_polygon",
        TrajectoryWithin(trajectory_within=SpatioTemporalAltitudeValue(
            geometry=_UK_POLYGON,
            time_from=_WEEK_FROM, time_to=_WEEK_TO,
        )),
    ),

    # 9. AND composition: ICAO type + polygon intersect (start_ts range from outer filter)
    (
        "and_type_polygon",
        _and(
            IcaoType(icao_type=["B738"]),
            TrajectoryIntersects(trajectory_intersects=SpatioTemporalAltitudeValue(
                geometry=_UK_POLYGON,
                time_from=_WEEK_FROM, time_to=_WEEK_TO,
            )),
        ),
    ),

    # 10. Duration filter + time window — tests EXTRACT(EPOCH ...) expression
    (
        "duration_min_1h",
        _week_and(Duration(duration={"min_s": 3600.0})),  # type: ignore[arg-type]
    ),

    # 11. FL altitude only + time window — exercises B-tree on alt_min/max_pressure_ft
    #     FL350-420 (common cruise) matches ~30% of flights; FL500+ matches ~0.05%.
    #     Using FL500+ to demonstrate the B-tree kicking in for a selective range.
    (
        "fl_altitude_only_selective",
        _week_and(TrajectoryIntersects(trajectory_intersects=SpatioTemporalAltitudeValue(
            altitude_min=500, altitude_min_ref="fl",
        ))),
    ),

    # 12. ft altitude only + time window — exercises B-tree on alt_min/max_qnh_ft
    #     Using a low max to target flights that never exceeded FL100 (~36% of data).
    (
        "ft_altitude_only_low",
        _week_and(TrajectoryIntersects(trajectory_intersects=SpatioTemporalAltitudeValue(
            altitude_max=10_000, altitude_max_ref="ft",
        ))),
    ),
]


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

async def analyze(dsn: str) -> None:
    conn = await asyncpg.connect(dsn)
    try:
        sep = "=" * 72
        for label, pred in CASES:
            print(f"\n{sep}")
            print(f"QUERY: {label}")
            print(sep)

            sql, params = build_sql(pred, start_from=_WEEK_FROM, start_to=_WEEK_TO)
            print("\n--- Compiled SQL ---")
            print(sql)
            if params:
                print(f"\nParams: {params}")

            explain_sql = f"EXPLAIN (ANALYZE, BUFFERS, FORMAT TEXT) {sql}"
            try:
                rows = await conn.fetch(explain_sql, *params)
                plan_lines = [r[0] for r in rows]
                print("\n--- Query Plan ---")
                print("\n".join(plan_lines))
            except Exception as exc:
                print(f"\n[ERROR running EXPLAIN: {exc}]")

        print(f"\n{sep}")
        print("Done.")
    finally:
        await conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dsn",
        default="postgresql://adsb:adsb_dev_password@localhost:5432/adsb",
        help="asyncpg DSN for the target database",
    )
    parser.add_argument(
        "--case",
        help="Run only the named case (substring match on label)",
    )
    args = parser.parse_args()

    global CASES
    if args.case:
        CASES = [(label, pred) for label, pred in CASES if args.case in label]
        if not CASES:
            print(f"No cases matching {args.case!r}", file=sys.stderr)
            sys.exit(1)

    asyncio.run(analyze(args.dsn))


if __name__ == "__main__":
    main()
