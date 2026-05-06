#!/usr/bin/env python3
"""Analyze 490 flights with >24h durations in staging table."""

import asyncio
import gzip
import json
import tarfile
from collections import defaultdict
from typing import Any

import asyncpg

DB_DSN = "postgresql://adsb:devpass@localhost:5432/adsb"
TARBALLS = [
    "/home/arachnid/projects/vfrhotness/cache/traces/2025-04-01/2025-04-01.tar",
    "/home/arachnid/projects/vfrhotness/cache/traces/2025-04-02/2025-04-02.tar",
]


async def get_icao24s() -> list[str]:
    conn = await asyncpg.connect(DB_DSN)
    try:
        rows = await conn.fetch(
            """
            SELECT DISTINCT icao24 FROM staging_flights
            WHERE EXTRACT(EPOCH FROM (last_ts - start_ts)) > 86400
            ORDER BY icao24
            """
        )
        return [r["icao24"] for r in rows]
    finally:
        await conn.close()


def _parse_alt(raw: Any) -> float | None:
    """Returns None for ground/null, float otherwise."""
    if raw is None or raw == "ground":
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def load_traces_from_tar(
    tarpath: str, icao24_set: set[str]
) -> dict[str, list[list[Any]]]:
    """Returns dict icao24 -> list of raw trace point arrays (ALL points, incl. ground)."""
    results: dict[str, list[list[Any]]] = defaultdict(list)
    try:
        with tarfile.open(tarpath, "r") as tf:
            for member in tf.getmembers():
                name = member.name
                # Format: ./traces/<last2>/trace_full_<icao24>.json
                if not (name.endswith(".json") and "trace_full_" in name):
                    continue
                basename = name.rsplit("/", 1)[-1]  # trace_full_<icao24>.json
                icao = basename.removeprefix("trace_full_").removesuffix(".json").lower()
                if icao not in icao24_set:
                    continue
                f = tf.extractfile(member)
                if f is None:
                    continue
                raw = f.read()
                # Files may be gzip-compressed even without .gz extension
                if raw[:2] == b"\x1f\x8b":
                    raw = gzip.decompress(raw)
                obj = json.loads(raw)
                trace = obj.get("trace", [])
                results[icao].extend(trace)
    except FileNotFoundError:
        print(f"WARNING: tarball not found: {tarpath}")
    return results


def classify(
    icao: str, all_points: list[list[Any]]
) -> tuple[str, dict[str, Any]]:
    """Classify an aircraft based on all raw trace points (including ground)."""
    if not all_points:
        return "missing", {}

    # Sort by offset (index 0)
    pts = sorted(all_points, key=lambda p: p[0] if p else 0)

    new_leg_on_ground = 0
    new_leg_on_airborne = 0
    has_ground = False
    max_gap = 0.0
    prev_offset: float | None = None

    for pt in pts:
        if not isinstance(pt, list) or len(pt) < 3:
            continue
        offset = pt[0]
        alt = _parse_alt(pt[3] if len(pt) > 3 else None)
        # flags at index 6; new_leg = bit 2
        flags_raw = pt[6] if len(pt) > 6 else None
        try:
            flags = int(flags_raw or 0)
        except (TypeError, ValueError):
            flags = 0
        new_leg = bool(flags & 2)

        is_ground = alt is None or alt <= 0

        if is_ground:
            has_ground = True

        if new_leg:
            if is_ground:
                new_leg_on_ground += 1
            else:
                new_leg_on_airborne += 1

        if prev_offset is not None:
            gap = float(offset) - float(prev_offset)
            if gap > max_gap:
                max_gap = gap
        prev_offset = float(offset)

    total_new_leg = new_leg_on_ground + new_leg_on_airborne

    stats: dict[str, Any] = {
        "total_new_leg": total_new_leg,
        "new_leg_on_ground": new_leg_on_ground,
        "new_leg_on_airborne": new_leg_on_airborne,
        "max_gap_s": max_gap,
        "has_ground": has_ground,
        "num_points": len(pts),
    }

    if new_leg_on_airborne > 0:
        cat = "new_leg_on_airborne"
    elif new_leg_on_ground > 0:
        cat = "new_leg_on_ground"
    elif max_gap > 7200:
        cat = "no_new_leg_gap"
    else:
        cat = "no_new_leg_no_gap"

    return cat, stats


async def main() -> None:
    print("Fetching icao24s from postgres...")
    icao24s = await get_icao24s()
    print(f"Found {len(icao24s)} icao24s with flights >24h\n")

    icao24_set = set(icao24s)

    all_traces: dict[str, list[list[Any]]] = defaultdict(list)
    for tarpath in TARBALLS:
        print(f"Loading traces from {tarpath}...")
        traces = load_traces_from_tar(tarpath, icao24_set)
        for icao, pts in traces.items():
            all_traces[icao].extend(pts)
        print(f"  Found {len(traces)} matching aircraft in this tarball")

    print()

    categories: dict[str, list[tuple[str, dict[str, Any]]]] = defaultdict(list)
    for icao in icao24s:
        pts = all_traces.get(icao, [])
        cat, stats = classify(icao, pts)
        categories[cat].append((icao, stats))

    cat_order = [
        "new_leg_on_airborne",
        "new_leg_on_ground",
        "no_new_leg_gap",
        "no_new_leg_no_gap",
        "missing",
    ]

    print("=" * 60)
    print("CATEGORY SUMMARY")
    print("=" * 60)
    for cat in cat_order:
        items = categories.get(cat, [])
        print(f"  {cat}: {len(items)}")

    print()

    for cat in cat_order:
        items = categories.get(cat, [])
        if not items:
            continue
        print(f"--- {cat} ({len(items)} aircraft) ---")
        for icao, stats in items[:5]:
            parts = [f"icao={icao}"]
            if stats:
                parts.append(f"pts={stats['num_points']}")
                parts.append(f"max_gap={stats['max_gap_s']:.0f}s ({stats['max_gap_s']/3600:.1f}h)")
                parts.append(
                    f"new_leg={stats['total_new_leg']}"
                    f"(gnd={stats['new_leg_on_ground']},air={stats['new_leg_on_airborne']})"
                )
                parts.append(f"has_gnd={stats['has_ground']}")
            print("  " + "  ".join(parts))
        if len(items) > 5:
            print(f"  ... and {len(items) - 5} more")
        print()

    print("=" * 60)
    print("ADDITIONAL STATS")
    print("=" * 60)

    all_max_gaps = [
        (icao, s["max_gap_s"])
        for cat in cat_order
        for icao, s in categories.get(cat, [])
        if s
    ]
    all_max_gaps.sort(key=lambda x: -x[1])
    print("Top 5 max gaps (any category):")
    for icao, gap in all_max_gaps[:5]:
        print(f"  {icao}: {gap:.0f}s ({gap / 3600:.1f}h)")

    no_gap_no_leg = categories.get("no_new_leg_no_gap", [])
    if no_gap_no_leg:
        with_ground = sum(1 for _, s in no_gap_no_leg if s.get("has_ground"))
        print(
            f"\nno_new_leg_no_gap: {with_ground}/{len(no_gap_no_leg)} touch ground "
            f"({len(no_gap_no_leg) - with_ground} are pure high-alt / no-ground)"
        )

    # Gap distribution for no_new_leg_gap
    gap_items = categories.get("no_new_leg_gap", [])
    if gap_items:
        gaps = sorted([s["max_gap_s"] for _, s in gap_items], reverse=True)
        print(f"\nno_new_leg_gap max gap distribution (top 10):")
        for g in gaps[:10]:
            print(f"  {g:.0f}s ({g/3600:.1f}h)")


asyncio.run(main())
