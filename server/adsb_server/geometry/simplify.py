"""TD-TR trajectory simplification for ADS-B flight paths."""

from __future__ import annotations

import logging
from collections.abc import Callable

from pyproj import Geod

from adsb_server.ingestion.models import RawPoint

logger = logging.getLogger(__name__)

_GEOD = Geod(ellps="WGS84")

# Deviation function: (point, segment_start, segment_end) -> deviation in domain units.
# The function receives the three RawPoint objects directly so it is independent of
# the surrounding list structure and can be reasoned about and tested in isolation.
DeviationFn = Callable[[RawPoint, RawPoint, RawPoint], float]


def spatial_deviation(p: RawPoint, a: RawPoint, b: RawPoint) -> float:
    """
    TD-TR spatial deviation in metres (pyproj WGS-84 geodesic).

    Computes the distance between p and its temporally interpolated position on
    the geodesic from a to b. The interpolated position is found by walking
    along the geodesic a fraction t of its total length, where t is the time
    ratio of p between a and b.
    """
    dt = b.ts - a.ts
    t = (p.ts - a.ts) / dt if dt > 0 else 0.5
    az_ab, _, dist_ab = _GEOD.inv(a.lon, a.lat, b.lon, b.lat)
    if dist_ab == 0.0:
        _, _, dist = _GEOD.inv(p.lon, p.lat, a.lon, a.lat)
        return float(abs(dist))
    interp_lon, interp_lat, _ = _GEOD.fwd(a.lon, a.lat, az_ab, t * dist_ab)
    _, _, dist = _GEOD.inv(p.lon, p.lat, interp_lon, interp_lat)
    return float(abs(dist))


def altitude_deviation(p: RawPoint, a: RawPoint, b: RawPoint) -> float:
    """
    TD-TR altitude deviation in feet.

    Returns 0 when any of the three points lacks alt_baro, so altitude-unknown
    points are never spuriously retained.
    """
    if p.alt_baro is None or a.alt_baro is None or b.alt_baro is None:
        return 0.0
    dt = b.ts - a.ts
    t = (p.ts - a.ts) / dt if dt > 0 else 0.5
    return float(abs(p.alt_baro - (a.alt_baro + t * (b.alt_baro - a.alt_baro))))


def _td_tr(
    points: list[RawPoint],
    start: int,
    end: int,
    epsilon: float,
    dev_fn: DeviationFn,
    kept: set[int],
) -> None:
    """
    Top-Down Time-Ratio simplification (iterative, stack-based).

    Finds the intermediate point with the largest deviation from its temporally
    interpolated position. If that deviation exceeds epsilon, the point is
    retained and the interval is split for further processing.

    Both the spatial pass and the altitude pass use this same algorithm via
    different dev_fn implementations.
    """
    stack: list[tuple[int, int]] = [(start, end)]
    while stack:
        s, e = stack.pop()
        if e - s < 2:
            continue

        a, b = points[s], points[e]
        max_dev = 0.0
        max_idx = s + 1
        for j in range(s + 1, e):
            dev = dev_fn(points[j], a, b)
            if dev > max_dev:
                max_dev = dev
                max_idx = j

        if max_dev > epsilon:
            kept.add(max_idx)
            stack.append((s, max_idx))
            stack.append((max_idx, e))


def simplify_flight(
    points: list[RawPoint],
    spatial_m: float = 50.0,
    alt_ft: float = 100.0,
) -> list[int]:
    """
    Simplify a flight's trajectory using two-pass TD-TR.

    Expects points that have already had missing values interpolated (see
    interpolate_missing_values in the ingestion pipeline).

    1. Squawk change points are always kept and divide the track into
       squawk-constant intervals; simplification never bridges a squawk transition.
    2. Spatial pass: TD-TR with ε=spatial_m metres, run within each
       squawk-constant interval.
    3. Altitude pass: TD-TR with ε=alt_ft feet on every consecutive pair
       in the current kept set (squawk boundaries act as natural anchors).

    Returns sorted indices into points of the vertices to keep.
    """
    n = len(points)
    if n <= 2:
        return list(range(n))

    # Endpoints plus every point where squawk changes.
    kept: set[int] = {0, n - 1}
    for i in range(1, n):
        if points[i].squawk != points[i - 1].squawk:
            kept.add(i)

    # Spatial pass within each squawk-constant interval.
    squawk_intervals = sorted(kept)
    for k in range(len(squawk_intervals) - 1):
        _td_tr(
            points,
            squawk_intervals[k],
            squawk_intervals[k + 1],
            spatial_m,
            spatial_deviation,
            kept,
        )

    # Altitude pass on every consecutive kept pair. Squawk boundaries are
    # already in kept, so this naturally stays within squawk-constant ranges.
    kept_sorted = sorted(kept)
    for k in range(len(kept_sorted) - 1):
        _td_tr(points, kept_sorted[k], kept_sorted[k + 1], alt_ft, altitude_deviation, kept)

    return sorted(kept)
