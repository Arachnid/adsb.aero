"""Flight splitting logic: converts raw point streams into discrete flights."""

from __future__ import annotations

import dataclasses
import logging
import math
from collections import Counter
from datetime import UTC, datetime

from adsb_server.geometry.simplify import (
    gs_deviation,
    ias_deviation,
    simplify_flight,
    simplify_series,
    track_deviation,
    vr_deviation,
)
from adsb_server.ingestion.models import (
    FinalizedFlight,
    RawFlight,
    RawPoint,
    TraceHeader,
)

logger = logging.getLogger(__name__)

# Ground-to-ground gap above this → new flight (plane parked).
_GROUND_GAP_THRESHOLD = 600.0

# Hard cap: any flight segment longer than this is force-split.
_MAX_SEGMENT_DURATION = 86400.0

# Air-to-air gaps above this threshold produce a new seqset sub-sequence
# instead of being linearly interpolated.  60 s is just above the 99th
# percentile of normal ADS-B update intervals in raw trace data.
_SUB_SEQ_GAP_S = 60.0

# Air-to-air gaps above this always start a new flight record regardless of
# callsign or geography (catches same-ICAO24 reuse across very long breaks).
_MAX_STITCH_GAP_S = 43200.0  # 12 hours

# In-progress retention window for airborne last segments.
_IN_PROGRESS_WINDOW_AIR = 3600.0

# Geographic plausibility: max speed in m/s used to check whether two
# position reports separated by a coverage gap could be the same aircraft.
# 350 m/s ≈ 1260 km/h — faster than any airliner, so false positives are rare.
_MAX_STITCH_SPEED_MPS = 350.0

# Hard cap on implied speed between consecutive position reports within a
# flight sequence.  Points exceeding this are from a corrupted ADS-B receiver
# emitting garbage coordinates (observed cases were 570-14 000 m/s).
# Higher than _MAX_STITCH_SPEED_MPS because GPS quantisation can produce
# apparent bursts slightly above airliner speeds on very short intervals.
_MAX_POINT_SPEED_MPS = 500.0

# Minimum implied average speed for an aircraft to be considered continuously
# airborne across a gap.  Below this the aircraft was almost certainly stationary
# (parked at an airfield whose baro elevation is non-zero, so alt_baro is not
# None even on the ground).  10 m/s ≈ 19 kt — safely below any cruise speed.
_MIN_STITCH_SPEED_MPS = 10.0


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


def build_squawk_runs(points: list[RawPoint]) -> list[tuple[float, str]]:
    """
    Build run-length encoding of squawk codes.

    Emits a new run when squawk changes from the previous non-null value,
    then appends a closing instant at the last point's timestamp so the
    resulting ttext sequence covers the full flight extent.  Without the
    closing instant, ttext has no defined value after the final change point.
    """
    runs: list[tuple[float, str]] = []
    last_squawk: str | None = None
    for p in points:
        if p.squawk is not None and p.squawk != last_squawk:
            runs.append((p.ts, p.squawk))
            last_squawk = p.squawk
    # Add closing instant so ttext covers the flight's full temporal extent.
    if runs and last_squawk is not None and points[-1].ts != runs[-1][0]:
        runs.append((points[-1].ts, last_squawk))
    return runs


# TD-TR epsilons for secondary scalar passes.
_TRACK_EPSILON_DEG = 5.0
_GS_EPSILON_KT = 5.0
_VR_EPSILON_FPM = 100.0
_IAS_EPSILON_KT = 5.0


def build_scalar_series(
    sub: list[RawPoint],
) -> tuple[
    list[tuple[float, float]],
    list[tuple[float, float]],
    list[tuple[float, float]],
    list[tuple[float, float]],
]:
    """Apply per-field TD-TR on a sub-list of path-kept RawPoints.

    Returns (path_tracks_series, path_gs_series, path_vr_series, path_ias_series).
    Each series is a list of (ts, value) pairs after removing points redundant
    under linear interpolation within the stated epsilon.  None-valued points are
    excluded from the output series.
    """
    trk_idx = simplify_series(sub, _TRACK_EPSILON_DEG, track_deviation)
    gs_idx = simplify_series(sub, _GS_EPSILON_KT, gs_deviation)
    vr_idx = simplify_series(sub, _VR_EPSILON_FPM, vr_deviation)
    ias_idx = simplify_series(sub, _IAS_EPSILON_KT, ias_deviation)

    trk: list[tuple[float, float]] = []
    for i in trk_idx:
        p = sub[i]
        if p.track is not None:
            trk.append((p.ts, p.track % 360.0))
    gs_: list[tuple[float, float]] = []
    for i in gs_idx:
        p = sub[i]
        if p.gs is not None:
            gs_.append((p.ts, p.gs))
    vr_: list[tuple[float, float]] = []
    for i in vr_idx:
        p = sub[i]
        if p.vr is not None:
            vr_.append((p.ts, p.vr))
    ias: list[tuple[float, float]] = []
    for i in ias_idx:
        p = sub[i]
        if p.ias is not None:
            ias.append((p.ts, p.ias))
    return trk, gs_, vr_, ias


def _haversine_m(prev: RawPoint, curr: RawPoint) -> float:
    """Haversine distance in metres between two RawPoints."""
    lat1, lon1 = math.radians(prev.lat), math.radians(prev.lon)
    lat2, lon2 = math.radians(curr.lat), math.radians(curr.lon)
    dlat, dlon = lat2 - lat1, lon2 - lon1
    a = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 6_371_000.0 * 2.0 * math.asin(math.sqrt(max(0.0, min(1.0, a))))


def _geographically_plausible(prev: RawPoint, curr: RawPoint, gap: float) -> bool:
    """Return True if the two positions are reachable within gap seconds at max aircraft speed."""
    return _haversine_m(prev, curr) <= _MAX_STITCH_SPEED_MPS * gap


def _geographically_active(prev: RawPoint, curr: RawPoint, gap: float) -> bool:
    """Return True if the implied average speed across the gap suggests continuous flight."""
    return _haversine_m(prev, curr) >= _MIN_STITCH_SPEED_MPS * gap


def _should_flight_split(prev: RawPoint, curr: RawPoint, flight_start_ts: float) -> bool:
    """Return True if curr begins a new discrete flight rather than continuing the current one.

    Two levels of splitting exist:
    - Flight split (this function): creates a new FinalizedFlight row.
    - Sub-sequence split (handled in finalize_segment): adds a new seqset bracket
      for a coverage gap within the same flight.
    """
    gap = curr.ts - prev.ts

    # Duration safety cap — also catches infinite-loop ground stations.
    if curr.ts - flight_start_ts > _MAX_SEGMENT_DURATION:
        return True

    # Ground-to-ground gap > 10 min → plane parked, new flight.
    if prev.alt_baro is None and curr.alt_baro is None and gap > _GROUND_GAP_THRESHOLD:
        return True

    # Large air-to-air gap: stitch if plausible, otherwise split.
    if prev.alt_baro is not None and curr.alt_baro is not None and gap > _SUB_SEQ_GAP_S:
        if gap > _MAX_STITCH_GAP_S or not _geographically_plausible(prev, curr, gap):
            return True
        # Stationary across a long gap → aircraft was parked (catches sea-level
        # airfields where baro altitude is non-None even on the ground).
        return bool(gap > _GROUND_GAP_THRESHOLD and not _geographically_active(prev, curr, gap))

    # For all other transitions (including ground/air changes), trust readsb's new_leg.
    return curr.new_leg


def _drop_implausible_positions(icao24: str, points: list[RawPoint]) -> list[RawPoint]:
    """Drop position reports that imply speed > _MAX_STITCH_SPEED_MPS from the previous kept point.

    Corrupted ADS-B receivers occasionally emit garbage coordinates for a real
    aircraft, producing planet-spanning linestrings that cause GEOS to error.
    """
    kept: list[RawPoint] = [points[0]]
    for curr in points[1:]:
        prev = kept[-1]
        dt = curr.ts - prev.ts
        if dt <= 0.0:
            kept.append(curr)
            continue
        speed = _haversine_m(prev, curr) / dt
        if speed <= _MAX_POINT_SPEED_MPS:
            kept.append(curr)
        else:
            logger.warning(
                "icao24=%s: dropping implausible position at ts=%.3f (%.0f m/s)",
                icao24,
                curr.ts,
                speed,
            )
    return kept


def _split_into_sub_sequences(points: list[RawPoint]) -> list[list[RawPoint]]:
    """Partition a flat list of airborne points into sub-sequences at coverage gaps.

    Any gap > _SUB_SEQ_GAP_S between consecutive points starts a new sub-sequence.
    This produces the brackets of the tgeompoint_seqset — no interpolation across gaps.
    """
    seqs: list[list[RawPoint]] = [[points[0]]]
    for curr in points[1:]:
        if curr.ts - seqs[-1][-1].ts > _SUB_SEQ_GAP_S:
            seqs.append([curr])
        else:
            seqs[-1].append(curr)
    return seqs


def finalize_segment(
    icao24: str,
    seg_points: list[RawPoint],
    icao_type: str | None,
) -> FinalizedFlight | None:
    """Convert a list of RawPoints into a FinalizedFlight with a seqset path.

    The path is a tgeompoint_seqset: coverage gaps > _SUB_SEQ_GAP_S produce separate
    sub-sequences with no interpolation across the gap.  Returns None if there are
    fewer than 2 airborne points across all sub-sequences.
    """
    airborne = [p for p in seg_points if p.alt_baro is not None]
    if len(airborne) < 2:
        return None

    airborne = _drop_implausible_positions(icao24, airborne)
    if len(airborne) < 2:
        return None

    callsign = _most_common_non_null([p.callsign for p in seg_points])
    emitter_category = _most_common_non_null([p.emitter_category for p in seg_points])

    sub_seqs = _split_into_sub_sequences(airborne)

    vertex_sequences: list[list[tuple[float, float, float, float]]] = []
    squawk_runs: list[list[tuple[float, str]]] = []
    path_tracks_series: list[list[tuple[float, float]]] = []
    path_gs_series: list[list[tuple[float, float]]] = []
    path_vr_series: list[list[tuple[float, float]]] = []
    path_ias_series: list[list[tuple[float, float]]] = []

    for sub_pts in sub_seqs:
        if len(sub_pts) < 2:
            continue

        interp_points = interpolate_missing_values(sub_pts)
        kept_indices = simplify_flight(interp_points)
        if len(kept_indices) < 2:
            kept_indices = [0, len(interp_points) - 1]

        verts: list[tuple[float, float, float, float]] = [
            (p.lon, p.lat, p.alt_baro if p.alt_baro is not None else 0.0, p.ts)
            for p in (interp_points[i] for i in kept_indices)
        ]
        if len(verts) < 2:
            continue

        vertex_sequences.append(verts)
        sub = [interp_points[i] for i in kept_indices]
        squawk_runs.append(build_squawk_runs(sub))
        trk, gs_, vr_, ias = build_scalar_series(sub)
        path_tracks_series.append(trk)
        path_gs_series.append(gs_)
        path_vr_series.append(vr_)
        path_ias_series.append(ias)

    if not vertex_sequences:
        return None

    start_ts = datetime.fromtimestamp(vertex_sequences[0][0][3], tz=UTC)
    end_ts = datetime.fromtimestamp(vertex_sequences[-1][-1][3], tz=UTC)

    return FinalizedFlight(
        icao24=icao24,
        callsign=callsign,
        icao_type=icao_type,
        emitter_category=emitter_category,
        start_ts=start_ts,
        end_ts=end_ts,
        vertex_sequences=vertex_sequences,
        squawk_runs=squawk_runs,
        raw_point_count=len(seg_points),
        path_tracks_series=path_tracks_series,
        path_gs_series=path_gs_series,
        path_vr_series=path_vr_series,
        path_ias_series=path_ias_series,
    )


def _in_progress_window(seg: list[RawPoint]) -> float:
    """In-progress retention window based on the last point's altitude state."""
    return _GROUND_GAP_THRESHOLD if seg[-1].alt_baro is None else _IN_PROGRESS_WINDOW_AIR


def split_flights(
    header: TraceHeader,
    points: list[RawPoint],  # sorted by ts, non-empty
    cutoff_ts: float,  # unix epoch — flights ending before this are finalized
) -> tuple[list[FinalizedFlight], RawFlight | None]:
    """Split a sorted sequence of RawPoints into discrete flights.

    Two-level split:
    - Flight boundaries (_should_flight_split): produce separate FinalizedFlight rows.
    - Sub-sequence boundaries (inside finalize_segment): produce seqset brackets for
      coverage gaps within the same flight — no interpolation across those gaps.

    Air-to-air gaps of 60 s-12 h that are geographically plausible are kept in the
    same flight and become sub-sequence boundaries, enabling transatlantic and other
    over-water routes to appear as single queryable records.

    Returns:
        (list_of_finalized_flights, optional_in_progress_raw_flight)
    """
    segments: list[list[RawPoint]] = []
    current_seg: list[RawPoint] = [points[0]]
    flight_start_ts = points[0].ts

    for curr in points[1:]:
        if _should_flight_split(current_seg[-1], curr, flight_start_ts):
            segments.append(current_seg)
            current_seg = [curr]
            flight_start_ts = curr.ts
        else:
            current_seg.append(curr)

    segments.append(current_seg)

    icao_type = header.icao_type
    finalized: list[FinalizedFlight] = []
    in_progress: RawFlight | None = None

    for seg_idx, seg in enumerate(segments):
        if len(seg) < 2:
            continue

        last_ts = seg[-1].ts
        is_last_segment = seg_idx == len(segments) - 1

        if is_last_segment and last_ts >= cutoff_ts - _in_progress_window(seg):
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
            result = finalize_segment(header.icao24, seg, icao_type)
            if result is not None:
                finalized.append(result)

    return finalized, in_progress
