"""
Query performance profiler for adsb.aero.

Connects to a live database, compiles each scenario through the production
query compiler, runs EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) and times the
raw queries, then prints a Markdown table of planning/execution times, row
counts, and index usage.

Usage (from server/ with venv activated):

    python -m perf.query_perf \\
        --dsn "postgresql://adsb:secret@localhost/adsb" \\
        --start 2024-06-01 --end 2024-06-08

    DATABASE_URL="postgresql://adsb:secret@localhost/adsb" \\
        python -m perf.query_perf --start 2024-06-01 --end 2024-06-08 --runs 5

Output columns:
  Rows       — number of rows returned (capped at LIMIT)
  Plan ms    — PostgreSQL planner time from EXPLAIN ANALYZE
  Exec ms    — PostgreSQL executor time from EXPLAIN ANALYZE
  Wall ms    — median end-to-end time over --runs raw query executions
  Buf hit    — shared buffer cache hits (higher = data was in memory)
  Buf read   — shared buffer disk reads (higher = cold cache or large scan)
  Indexes    — index node types used (GiST, Bitmap, BTree, Seq)
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import os
import statistics
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import asyncpg

from adsb_server.query.compiler import INNER_SUBQUERY_LIMIT, compile_predicate
from adsb_server.query.models import (
    AndPredicate,
    CallsignMatches,
    CircleGeometry,
    Duration,
    DurationValue,
    EmitterCategory,
    EndpointWithin,
    EndpointWithinValue,
    IcaoType,
    NotPredicate,
    OrPredicate,
    Predicate,
    SpatioTemporalAltitudeValue,
    TrajectoryIntersects,
)

LIMIT = 200  # overridden by --limit; kept as module default for import compatibility

# ---------------------------------------------------------------------------
# Predicate construction helpers
# ---------------------------------------------------------------------------


def circle(lon: float, lat: float, radius_m: float) -> CircleGeometry:
    return CircleGeometry(type="Circle", coordinates=[lon, lat], radius=radius_m)


def intersects(lon: float, lat: float, radius_m: float, **kw: Any) -> Predicate:
    return TrajectoryIntersects(
        trajectory_intersects=SpatioTemporalAltitudeValue(geometry=circle(lon, lat, radius_m), **kw)
    )


def starts(lon: float, lat: float, radius_m: float) -> Predicate:
    return EndpointWithin(
        endpoint_within=EndpointWithinValue(mode="start", geometry=circle(lon, lat, radius_m))
    )


def ends(lon: float, lat: float, radius_m: float) -> Predicate:
    return EndpointWithin(
        endpoint_within=EndpointWithinValue(mode="end", geometry=circle(lon, lat, radius_m))
    )


def and_(*preds: Predicate) -> Predicate:
    return AndPredicate(and_=list(preds))


def or_(*preds: Predicate) -> Predicate:
    return OrPredicate(or_=list(preds))


def not_(pred: Predicate) -> Predicate:
    return NotPredicate(not_=pred)


# ---------------------------------------------------------------------------
# Well-known locations (lon, lat) — all major hubs with dense traffic
# ---------------------------------------------------------------------------

LHR = (-0.4543, 51.4700)  # London Heathrow
JFK = (-73.7789, 40.6397)  # New York JFK
FRA = (8.5622, 50.0379)  # Frankfurt
CDG = (2.5479, 49.0097)  # Paris CDG
ORD = (-87.9048, 41.9742)  # Chicago O'Hare
SIN = (103.9915, 1.3644)  # Singapore Changi


# ---------------------------------------------------------------------------
# Scenario definitions
# ---------------------------------------------------------------------------


@dataclass
class Scenario:
    name: str
    predicate: Predicate | None
    note: str = ""


def build_scenarios() -> list[Scenario]:
    return [
        # ── Baseline ──────────────────────────────────────────────────────────
        Scenario(
            "baseline",
            None,
            "no predicate — full partition scan",
        ),
        # ── Single trajectory intersection, varying radius ─────────────────
        Scenario(
            "intersects/LHR-1km",
            intersects(*LHR, 1_000),
            "tight: single runway threshold",
        ),
        Scenario(
            "intersects/LHR-10km",
            intersects(*LHR, 10_000),
            "medium: airport + immediate approach",
        ),
        Scenario(
            "intersects/LHR-100km",
            intersects(*LHR, 100_000),
            "loose: south-east England",
        ),
        Scenario(
            "intersects/FRA-1km",
            intersects(*FRA, 1_000),
            "tight: different hub for comparison",
        ),
        Scenario(
            "intersects/SIN-1km",
            intersects(*SIN, 1_000),
            "tight: low-density region for comparison",
        ),
        # ── Start / end point predicates ───────────────────────────────────
        Scenario(
            "starts/LHR-5km",
            starts(*LHR, 5_000),
            "departures from Heathrow area",
        ),
        Scenario(
            "starts/LHR-100km",
            starts(*LHR, 100_000),
            "departures from south-east England",
        ),
        Scenario(
            "ends/LHR-5km",
            ends(*LHR, 5_000),
            "arrivals at Heathrow area",
        ),
        Scenario(
            "starts+ends/LHR→FRA",
            and_(starts(*LHR, 30_000), ends(*FRA, 30_000)),
            "short-haul route filter — both selective",
        ),
        Scenario(
            "starts+ends/LHR→JFK",
            and_(starts(*LHR, 50_000), ends(*JFK, 50_000)),
            "transatlantic route — both selective, few results",
        ),
        Scenario(
            "starts+ends/LHR→LHR",
            and_(starts(*LHR, 100_000), ends(*LHR, 100_000)),
            "round-trip to same large area",
        ),
        # ── Attribute predicates ───────────────────────────────────────────
        Scenario(
            "icao_type/B738",
            IcaoType(icao_type=["B738"]),
            "common narrow-body — many results",
        ),
        Scenario(
            "icao_type/B738+A320+A321",
            IcaoType(icao_type=["B738", "A320", "A321"]),
            "top 3 types — very many results",
        ),
        Scenario(
            "icao_type/C172",
            IcaoType(icao_type=["C172"]),
            "common GA type — moderate density",
        ),
        Scenario(
            "emitter/A3",
            EmitterCategory(emitter_category=["A3"]),
            "large aircraft emitter category",
        ),
        Scenario(
            "callsign/prefix-BAW",
            CallsignMatches(callsign_matches="^BAW"),
            "airline prefix — no index",
        ),
        Scenario(
            "callsign/exact",
            CallsignMatches(callsign_matches="^BAW123$"),
            "exact callsign — very selective, no index",
        ),
        Scenario(
            "duration/short",
            Duration(duration=DurationValue(max_s=1800)),
            "flights ≤ 30 min",
        ),
        Scenario(
            "duration/long",
            Duration(duration=DurationValue(min_s=28800)),
            "flights ≥ 8 hours",
        ),
        # ── Spatial + attribute combinations ──────────────────────────────
        Scenario(
            "intersects(LHR-10km)+type/B738",
            and_(intersects(*LHR, 10_000), IcaoType(icao_type=["B738"])),
            "tight spatial + common type — BitmapAnd of two indexes",
        ),
        Scenario(
            "intersects(LHR-100km)+type/C172",
            and_(intersects(*LHR, 100_000), IcaoType(icao_type=["C172"])),
            "loose spatial + selective type",
        ),
        Scenario(
            "intersects(LHR-10km)+callsign/BAW",
            and_(intersects(*LHR, 10_000), CallsignMatches(callsign_matches="^BAW")),
            "tight spatial + unindexed callsign filter",
        ),
        Scenario(
            "intersects(LHR-100km)+callsign/BAW",
            and_(intersects(*LHR, 100_000), CallsignMatches(callsign_matches="^BAW")),
            "loose spatial + unindexed callsign — high discard ratio",
        ),
        Scenario(
            "starts(LHR-5km)+type/B738",
            and_(starts(*LHR, 5_000), IcaoType(icao_type=["B738"])),
            "point index + btree BitmapAnd",
        ),
        # ── Worst-case outer selectivity ──────────────────────────────────────
        # Tiny geometry: H3 candidate set identical to LHR-1km but eIntersects
        # passes for only a handful of flights; outer query exhausts all inner rows.
        Scenario(
            "worst-case/LHR-200m",
            intersects(*LHR, 200),
            "point-like: same H3 cells as LHR-1km, near-zero eIntersects pass rate",
        ),
        # Large area + implausible dwell: outer must evaluate atgeometry+duration
        # on every H3 candidate, and almost none qualify.
        Scenario(
            "worst-case/LHR-100km-dwell-12hr",
            intersects(*LHR, 100_000, dwell_min_s=43200),
            "large area + 12hr dwell: outer exhausts all inner rows, zero results expected",
        ),
        # 3hr dwell: many flights pass the end_ts-start_ts pre-filter but fail atgeometry+duration.
        Scenario(
            "worst-case/LHR-100km-dwell-3hr",
            intersects(*LHR, 100_000, dwell_min_s=10800),
            "large area + 3hr dwell: pre-filter leaky, outer still selective",
        ),
        # ── Dwell filters (expensive: O(path x candidates)) ──────────────────
        Scenario(
            "dwell/LHR-2km-60s",
            intersects(*LHR, 2_000, dwell_min_s=60),
            "dwell ≥1min: loose — nearly all landings qualify",
        ),
        Scenario(
            "dwell/LHR-2km-1800s",
            intersects(*LHR, 2_000, dwell_min_s=1800),
            "dwell ≥30min: tighter — taxiing/parked only",
        ),
        Scenario(
            "dwell/LHR-10km-3600s",
            intersects(*LHR, 10_000, dwell_min_s=3600),
            "dwell ≥1hr in wider area: tight",
        ),
        # ── Squawk filters (unindexed post-filter) ─────────────────────────
        Scenario(
            "squawk/LHR-100km-emergency",
            intersects(*LHR, 100_000, squawk_codes=["7700", "7600", "7500"]),
            "emergency squawk in wide area — rare event, high discard",
        ),
        Scenario(
            "squawk/LHR-10km-emergency",
            intersects(*LHR, 10_000, squawk_codes=["7700", "7600", "7500"]),
            "same squawk, tighter area — index reduces candidate set",
        ),
        # ── Multiple same-type predicates ──────────────────────────────────
        Scenario(
            "AND/intersects(LHR-20km)+intersects(FRA-20km)",
            and_(intersects(*LHR, 20_000), intersects(*FRA, 20_000)),
            "two spatial ANDs: LHR+FRA overflyers (both STBOXes in one scan)",
        ),
        Scenario(
            "AND/intersects(LHR-50km)+intersects(JFK-50km)",
            and_(intersects(*LHR, 50_000), intersects(*JFK, 50_000)),
            "two spatial ANDs: transatlantic — almost no candidates",
        ),
        Scenario(
            "OR/intersects(LHR-20km)+intersects(FRA-20km)",
            or_(intersects(*LHR, 20_000), intersects(*FRA, 20_000)),
            "two spatial ORs: either hub — visited independently",
        ),
        Scenario(
            "OR/intersects(LHR-20km)+intersects(JFK-20km)",
            or_(intersects(*LHR, 20_000), intersects(*JFK, 20_000)),
            "two spatial ORs: different continents",
        ),
        # ── NOT predicate (no index pushdown) ─────────────────────────────
        Scenario(
            "NOT/type-B738",
            not_(IcaoType(icao_type=["B738"])),
            "NOT on common type — full scan, nearly everything returned",
        ),
        Scenario(
            "NOT/intersects(LHR-1km)",
            not_(intersects(*LHR, 1_000)),
            "NOT on tight spatial — full scan",
        ),
    ]


# ---------------------------------------------------------------------------
# SQL builder (mirrors the production query handler in api/main.py)
# ---------------------------------------------------------------------------


def _p(params: list[Any], val: Any) -> str:
    params.append(val)
    return f"${len(params)}"


def build_sql(
    predicate: Predicate | None,
    start_from: datetime,
    start_to: datetime,
    params: list[Any],
    limit: int = LIMIT,
) -> str:
    where_parts: list[str] = []
    where_parts.append(f"start_ts >= {_p(params, start_from)}")
    where_parts.append(f"start_ts < {_p(params, start_to)}")

    compiled = None
    if predicate is not None:
        compiled = compile_predicate(predicate, params)
        where_parts.append(f"({compiled})")

    limit_p = _p(params, limit)

    ctes = compiled.ctes if compiled is not None else []
    with_clause = (
        "WITH " + ", ".join(f"{name} AS ({body})" for name, body in ctes) + "\n" if ctes else ""
    )

    if compiled is not None and compiled.outer_parts:
        from_extras = (", " + ", ".join(name for name, _ in ctes)) if ctes else ""
        inner_where = "WHERE " + " AND ".join(where_parts)
        outer_where = "WHERE " + " AND ".join(f"({p})" for p in compiled.outer_parts)
        return (
            f"{with_clause}"
            f"SELECT f.icao24, f.start_ts, f.end_ts\n"
            f"FROM (\n"
            f"    SELECT f.icao24, f.start_ts, f.end_ts, f.path, f.squawk_seq\n"
            f"    FROM flights f LEFT JOIN airframes af ON af.icao24 = f.icao24\n"
            f"    {inner_where}\n"
            f"    ORDER BY f.start_ts DESC, f.icao24 DESC\n"
            f"    LIMIT {INNER_SUBQUERY_LIMIT}\n"
            f") f{from_extras}\n"
            f"{outer_where}\n"
            f"ORDER BY f.start_ts DESC, f.icao24 DESC\n"
            f"LIMIT {limit_p}"
        )

    from_extras = (", " + ", ".join(name for name, _ in ctes)) if ctes else ""
    return (
        f"{with_clause}"
        f"SELECT f.icao24, f.start_ts, f.end_ts\n"
        f"FROM flights f LEFT JOIN airframes af ON af.icao24 = f.icao24{from_extras}\n"
        f"WHERE {' AND '.join(where_parts)}\n"
        f"ORDER BY f.start_ts DESC, f.icao24 DESC\n"
        f"LIMIT {limit_p}"
    )


# ---------------------------------------------------------------------------
# EXPLAIN output parsing
# ---------------------------------------------------------------------------


@dataclass
class PlanMetrics:
    planning_ms: float
    execution_ms: float
    rows_out: int
    shared_hit: int
    shared_read: int
    index_nodes: list[str]


def _walk_plan(node: dict[str, Any], index_nodes: list[str], totals: dict[str, int]) -> None:
    node_type: str = node.get("Node Type", "")
    if "Index Scan" in node_type or "Bitmap Index Scan" in node_type:
        index_nodes.append(node.get("Index Name", "?"))
    totals["shared_hit"] += node.get("Shared Hit Blocks", 0)
    totals["shared_read"] += node.get("Shared Read Blocks", 0)
    for child in node.get("Plans", []):
        _walk_plan(child, index_nodes, totals)


def parse_explain(plan_json_str: str) -> PlanMetrics:
    data = json.loads(plan_json_str)
    top = data[0]
    plan = top.get("Plan", {})
    index_nodes: list[str] = []
    totals: dict[str, int] = {"shared_hit": 0, "shared_read": 0}
    _walk_plan(plan, index_nodes, totals)
    return PlanMetrics(
        planning_ms=top.get("Planning Time", 0.0),
        execution_ms=top.get("Execution Time", 0.0),
        rows_out=plan.get("Actual Rows", 0),
        shared_hit=totals["shared_hit"],
        shared_read=totals["shared_read"],
        index_nodes=index_nodes,
    )


def _summarise_indexes(names: list[str]) -> str:
    if not names:
        return "Seq"
    # Shorten index names: strip the "flights_" prefix for brevity
    short = [n.replace("flights_", "") for n in names]
    # Deduplicate while preserving order
    seen: set[str] = set()
    unique = [s for s in short if not (s in seen or seen.add(s))]  # type: ignore[func-returns-value]
    return ", ".join(unique)


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------


@dataclass
class ScenarioResult:
    scenario: Scenario
    rows: int
    plan_ms: float
    exec_ms: float
    wall_ms: float
    shared_hit: int
    shared_read: int
    index_summary: str
    error: str | None = None


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------


async def run_scenario(
    conn: asyncpg.Connection,  # type: ignore[type-arg]
    scenario: Scenario,
    start_from: datetime,
    start_to: datetime,
    runs: int,
    limit: int = LIMIT,
) -> ScenarioResult:
    try:
        # --- EXPLAIN ANALYZE (one run, instrumented) ---
        params: list[Any] = []
        sql = build_sql(scenario.predicate, start_from, start_to, params, limit=limit)
        explain_sql = f"EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) {sql}"
        explain_rows = await conn.fetch(explain_sql, *params)
        metrics = parse_explain(explain_rows[0]["QUERY PLAN"])

        # --- Raw timing (runs x uninstrumented queries) ---
        wall_times: list[float] = []
        rows = 0
        for _ in range(runs):
            params2: list[Any] = []
            sql2 = build_sql(scenario.predicate, start_from, start_to, params2, limit=limit)
            t0 = time.perf_counter()
            result = await conn.fetch(sql2, *params2)
            wall_times.append((time.perf_counter() - t0) * 1000)
            rows = len(result)

        return ScenarioResult(
            scenario=scenario,
            rows=rows,
            plan_ms=metrics.planning_ms,
            exec_ms=metrics.execution_ms,
            wall_ms=statistics.median(wall_times),
            shared_hit=metrics.shared_hit,
            shared_read=metrics.shared_read,
            index_summary=_summarise_indexes(metrics.index_nodes),
        )

    except Exception as exc:
        return ScenarioResult(
            scenario=scenario,
            rows=0,
            plan_ms=0,
            exec_ms=0,
            wall_ms=0,
            shared_hit=0,
            shared_read=0,
            index_summary="",
            error=str(exc),
        )


async def _fresh_conn(pool: asyncpg.Pool, timeout_s: int) -> asyncpg.Connection:  # type: ignore[type-arg]
    conn = await pool.acquire()
    await conn.execute(f"SET statement_timeout = '{timeout_s}s'")
    return conn


async def run_all(
    dsn: str,
    start_from: datetime,
    start_to: datetime,
    runs: int,
    scenarios: list[Scenario],
    limit: int = LIMIT,
    timeout_s: int = 60,
) -> list[ScenarioResult]:
    pool = await asyncpg.create_pool(dsn, min_size=1, max_size=1)
    assert pool is not None
    results: list[ScenarioResult] = []
    conn = await _fresh_conn(pool, timeout_s)
    for i, scenario in enumerate(scenarios, 1):
        print(f"  [{i:2d}/{len(scenarios)}] {scenario.name} ...", end="", flush=True)
        result = await run_scenario(conn, scenario, start_from, start_to, runs, limit=limit)
        if result.error and conn.is_closed():
            # Backend crashed — release the dead connection and get a fresh one.
            with contextlib.suppress(Exception):
                await pool.release(conn, timeout=1)
            conn = await _fresh_conn(pool, timeout_s)
        status = f"ERROR: {result.error}" if result.error else f"{result.rows} rows"
        print(f" {status}")
        results.append(result)
    with contextlib.suppress(TimeoutError):
        await asyncio.wait_for(pool.close(), timeout=5)
    return results


# ---------------------------------------------------------------------------
# Output formatting
# ---------------------------------------------------------------------------


def _fmt(value: float, decimals: int = 1) -> str:
    return f"{value:.{decimals}f}"


def print_markdown_table(
    results: list[ScenarioResult],
    start_from: datetime,
    start_to: datetime,
    runs: int,
    limit: int = LIMIT,
) -> None:
    days = (start_to - start_from).days
    print(
        f"\n## Query performance — "
        f"{start_from.date()} to {start_to.date()} ({days}d window, "
        f"LIMIT {limit}, {runs} wall-time runs)\n"
    )

    cols = [
        "Scenario",
        "Note",
        "Rows",
        "Plan ms",
        "Exec ms",
        "Wall ms",
        "Buf hit",
        "Buf read",
        "Indexes",
    ]
    rows_data: list[list[str]] = []
    for r in results:
        if r.error:
            rows_data.append(
                [r.scenario.name, r.scenario.note, "ERR", "", "", "", "", "", r.error[:60]]
            )
        else:
            rows_data.append(
                [
                    r.scenario.name,
                    r.scenario.note,
                    str(r.rows),
                    _fmt(r.plan_ms),
                    _fmt(r.exec_ms),
                    _fmt(r.wall_ms),
                    str(r.shared_hit),
                    str(r.shared_read),
                    r.index_summary,
                ]
            )

    # Column widths
    widths = [
        max(len(cols[i]), max((len(row[i]) for row in rows_data), default=0))
        for i in range(len(cols))
    ]
    sep = "| " + " | ".join("-" * w for w in widths) + " |"
    header = "| " + " | ".join(cols[i].ljust(widths[i]) for i in range(len(cols))) + " |"

    print(header)
    print(sep)
    for row in rows_data:
        print("| " + " | ".join(row[i].ljust(widths[i]) for i in range(len(cols))) + " |")

    print()
    print(
        "> Exec ms = PostgreSQL executor time (EXPLAIN ANALYZE). "
        "Wall ms = median end-to-end over raw queries (includes network/asyncpg overhead). "
        f"Rows capped at LIMIT={limit}. "
        "Buf hit/read are summed across all plan nodes; high hit ratio = data in shared_buffers."
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _parse_dt(s: str) -> datetime:
    return datetime.fromisoformat(s).replace(tzinfo=UTC)


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--dsn",
        default=os.environ.get("DATABASE_URL", ""),
        help="asyncpg DSN. Defaults to $DATABASE_URL.",
    )
    parser.add_argument(
        "--start",
        required=True,
        metavar="YYYY-MM-DD",
        help="Inclusive start of the query window (e.g. 2024-06-01).",
    )
    parser.add_argument(
        "--end",
        required=True,
        metavar="YYYY-MM-DD",
        help="Exclusive end of the query window (e.g. 2024-06-08). Keep ≤7 days.",
    )
    parser.add_argument(
        "--runs",
        type=int,
        default=3,
        help="Number of raw (non-EXPLAIN) query executions for wall-time measurement (default: 3).",
    )
    parser.add_argument(
        "--filter",
        metavar="PREFIX",
        help="Only run scenarios whose name starts with PREFIX.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=LIMIT,
        help=f"Row limit per query (default: {LIMIT}). Lower values reduce saturation.",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=60,
        metavar="SECONDS",
        help="statement_timeout per query in seconds (default: 60). Prevents OOM crashes.",
    )
    args = parser.parse_args()

    if not args.dsn:
        parser.error("Provide --dsn or set DATABASE_URL")

    start_from = _parse_dt(args.start)
    start_to = _parse_dt(args.end)
    if start_to <= start_from:
        parser.error("--end must be after --start")

    scenarios = build_scenarios()
    if args.filter:
        scenarios = [s for s in scenarios if s.name.startswith(args.filter)]
        if not scenarios:
            parser.error(f"No scenarios match prefix '{args.filter}'")

    print(f"Running {len(scenarios)} scenarios against {args.dsn}")
    print(f"Window: {start_from.date()} → {start_to.date()}, {args.runs} wall-time run(s) each\n")

    results = asyncio.run(
        run_all(
            args.dsn,
            start_from,
            start_to,
            args.runs,
            scenarios,
            limit=args.limit,
            timeout_s=args.timeout,
        )
    )
    print_markdown_table(results, start_from, start_to, args.runs, limit=args.limit)


if __name__ == "__main__":
    main()
