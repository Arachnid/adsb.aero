"""Flight splitting logic: converts raw point streams into discrete flights."""

from __future__ import annotations

import dataclasses
import logging
from collections import Counter
from datetime import UTC, datetime

from adsb_server.geometry.simplify import simplify_flight
from adsb_server.ingestion.models import (
    FinalizedFlight,
    RawFlight,
    RawPoint,
    TraceHeader,
)

logger = logging.getLogger(__name__)

# Seconds before cutoff within which a flight is considered in-progress
_IN_PROGRESS_WINDOW = 600.0


def interpolate_missing_values(points: list[RawPoint]) -> list[RawPoint]:
    """
    Fill missing alt_baro and track values by linear interpolation between
    bracketing known values. Points outside the first/last known value are
    left as None. Sets alt_baro_interpolated / track_interpolated on filled
    points so callers can distinguish measured from derived values.

    Called on each flight segment before simplification.
    """
    result = list(points)

    # --- alt_baro (linear in feet) ---
    known_alt = [i for i, p in enumerate(result) if p.alt_baro is not None]
    for k in range(len(known_alt) - 1):
        left, right = known_alt[k], known_alt[k + 1]
        if right - left <= 1:
            continue
        left_alt = result[left].alt_baro
        right_alt = result[right].alt_baro
        if left_alt is None or right_alt is None:
            continue  # narrowing for mypy; guaranteed non-None by filter above
        dt = result[right].ts - result[left].ts
        for m in range(left + 1, right):
            t = (result[m].ts - result[left].ts) / dt if dt > 0 else 0.5
            result[m] = dataclasses.replace(
                result[m],
                alt_baro=left_alt + t * (right_alt - left_alt),
                alt_baro_interpolated=True,
            )

    # --- squawk (forward fill: carry last known code to subsequent None points) ---
    last_squawk: str | None = None
    for i, p in enumerate(result):
        if p.squawk is not None:
            last_squawk = p.squawk
        elif last_squawk is not None:
            result[i] = dataclasses.replace(result[i], squawk=last_squawk)

    # --- track (circular, shortest arc) ---
    known_trk = [i for i, p in enumerate(result) if p.track is not None]
    for k in range(len(known_trk) - 1):
        left, right = known_trk[k], known_trk[k + 1]
        if right - left <= 1:
            continue
        left_trk = result[left].track
        right_trk = result[right].track
        if left_trk is None or right_trk is None:
            continue
        arc = ((right_trk - left_trk) + 180.0) % 360.0 - 180.0
        dt = result[right].ts - result[left].ts
        for m in range(left + 1, right):
            t = (result[m].ts - result[left].ts) / dt if dt > 0 else 0.5
            result[m] = dataclasses.replace(
                result[m],
                track=(left_trk + t * arc) % 360.0,
                track_interpolated=True,
            )

    return result


def _most_common_non_null(values: list[str | None]) -> str | None:
    """Return the most common non-null value, or None if all are null."""
    non_null = [v for v in values if v is not None]
    if not non_null:
        return None
    counter: Counter[str] = Counter(non_null)
    return counter.most_common(1)[0][0]


def _build_squawk_runs(points: list[RawPoint]) -> list[tuple[float, str]]:
    """
    Build run-length encoding of squawk codes.
    Emits a new run when squawk changes from the previous non-null value.
    """
    runs: list[tuple[float, str]] = []
    last_squawk: str | None = None
    for p in points:
        if p.squawk is not None and p.squawk != last_squawk:
            runs.append((p.ts, p.squawk))
            last_squawk = p.squawk
    return runs


def _finalize_segment(
    header: TraceHeader,
    seg_points: list[RawPoint],
    icao_type: str | None,
) -> FinalizedFlight | None:
    """
    Convert a list of RawPoints into a FinalizedFlight.
    Returns None if the segment has fewer than 2 points.
    """
    if len(seg_points) < 2:
        return None

    callsign = _most_common_non_null([p.callsign for p in seg_points])
    emitter_category = _most_common_non_null([p.emitter_category for p in seg_points])

    interp_points = interpolate_missing_values(seg_points)
    kept_indices = simplify_flight(interp_points)

    if len(kept_indices) < 2:
        kept_indices = [0, len(interp_points) - 1]

    vertices: list[tuple[float, float, float, float]] = []
    path_tracks: list[int] = []
    for i in kept_indices:
        p = interp_points[i]
        alt_ft = p.alt_baro if p.alt_baro is not None else 0.0
        vertices.append((p.lon, p.lat, alt_ft, p.ts))
        track_int = round(p.track) % 360 if p.track is not None else 0
        path_tracks.append(track_int)

    squawk_runs = _build_squawk_runs([interp_points[i] for i in kept_indices])

    start_ts = datetime.fromtimestamp(vertices[0][3], tz=UTC)
    end_ts = datetime.fromtimestamp(vertices[-1][3], tz=UTC)

    return FinalizedFlight(
        icao24=header.icao24,
        callsign=callsign,
        icao_type=icao_type,
        emitter_category=emitter_category,
        start_ts=start_ts,
        end_ts=end_ts,
        vertices=vertices,
        path_tracks=path_tracks,
        squawk_runs=squawk_runs,
        raw_point_count=len(seg_points),
    )


def split_flights(
    header: TraceHeader,
    points: list[RawPoint],  # sorted by ts, non-empty
    cutoff_ts: float,  # unix epoch — flights ending >= 10 min before this are finalized
) -> tuple[list[FinalizedFlight], RawFlight | None]:
    """
    Split a sorted sequence of RawPoints into discrete flights.

    Splitting relies entirely on the new_leg flag (flags & 2) set by readsb in the
    source trace data. readsb already detects time gaps, spatial jumps, and other
    leg boundaries, so we trust its judgement rather than re-implementing heuristics.

    Returns:
        (list_of_finalized_flights, optional_in_progress_raw_flight)
    """
    segments: list[list[RawPoint]] = []
    current_seg: list[RawPoint] = [points[0]]

    for curr in points[1:]:
        if curr.new_leg:
            segments.append(current_seg)
            current_seg = [curr]
        else:
            current_seg.append(curr)

    segments.append(current_seg)

    # Determine icao_type for each segment using per-point data from header
    # (RawPoint doesn't carry icao_type; it's on the header)
    # We use header.icao_type for all segments
    icao_type = header.icao_type

    finalized: list[FinalizedFlight] = []
    in_progress: RawFlight | None = None

    for seg_idx, seg in enumerate(segments):
        if len(seg) < 2:
            continue

        last_ts = seg[-1].ts
        is_last_segment = seg_idx == len(segments) - 1

        if is_last_segment and last_ts >= cutoff_ts - _IN_PROGRESS_WINDOW:
            # This segment is in-progress
            callsign = _most_common_non_null([p.callsign for p in seg])
            emitter_category = _most_common_non_null([p.emitter_category for p in seg])
            in_progress = RawFlight(
                icao24=header.icao24,
                callsign=callsign,
                icao_type=icao_type,
                emitter_category=emitter_category,
                points=seg,
            )
        else:
            result = _finalize_segment(header, seg, icao_type)
            if result is not None:
                finalized.append(result)

    return finalized, in_progress
