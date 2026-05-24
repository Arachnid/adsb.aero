"""Above-Ground-Level (AGL) height computation for flight paths.

Pipeline per sub-sequence:
  1. Densify the simplified vertex path at ~90 m intervals (GLO-90 resolution).
  2. Look up the QNH correction at every point (stepwise from the correction series).
  3. Sample terrain elevation from the GLO-90 DEM via TileManager.
  4. Compute AGL = pressure_alt_ft + correction_ft - terrain_elev_ft.
  5. Simplify the resulting 1-D (ts, AGL) series with TD-TR at 100 ft.

Returns per-sub-sequence (values, timestamps) pairs ready for tfloat_stepwise_seqset.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import numpy as np
import numpy.typing as npt
from pyproj import Geod

if TYPE_CHECKING:
    from adsb_server.terrain.tiles import TileManager

logger = logging.getLogger(__name__)

# GLO-90 pixel spacing: 3 arcseconds ≈ 90 m.
_STEP_M: float = 90.0
_GEOD = Geod(ellps="WGS84")

# Height-dependent TD-TR epsilon: max(min, agl * fraction).
# Below ~3300 ft the minimum (50 ft) dominates; at cruise (35 000 ft) epsilon ≈ 525 ft.
_AGL_MIN_EPSILON_FT: float = 50.0
_AGL_EPSILON_FRACTION: float = 0.015


def _densify(
    seq: list[tuple[float, float, float, float]],
) -> tuple[
    npt.NDArray[np.float64],
    npt.NDArray[np.float64],
    npt.NDArray[np.float64],
    npt.NDArray[np.float64],
]:
    """Densify a vertex sub-sequence at GLO-90 grid resolution.

    For each segment between consecutive vertices, insert intermediate points
    spaced at most _STEP_M apart along the WGS-84 geodesic.  Lon/lat positions
    come from pyproj.Geod; altitude and timestamp are linearly interpolated.

    Returns (lons, lats, alts_ft, ts) as float64 arrays.
    """
    if not seq:
        return (
            np.array([], dtype=np.float64),
            np.array([], dtype=np.float64),
            np.array([], dtype=np.float64),
            np.array([], dtype=np.float64),
        )

    out_lon: list[float] = [seq[0][0]]
    out_lat: list[float] = [seq[0][1]]
    out_alt: list[float] = [seq[0][2]]
    out_ts: list[float] = [seq[0][3]]

    for i in range(1, len(seq)):
        lon0, lat0, alt0, ts0 = seq[i - 1]
        lon1, lat1, alt1, ts1 = seq[i]

        _, _, dist_m = _GEOD.inv(lon0, lat0, lon1, lat1)
        n = max(1, int(dist_m / _STEP_M))

        t_arr: npt.NDArray[np.float64] = np.linspace(1.0 / n, 1.0, n)
        out_alt.extend((alt0 + t_arr * (alt1 - alt0)).tolist())
        out_ts.extend((ts0 + t_arr * (ts1 - ts0)).tolist())

        if n > 1:
            pts = _GEOD.npts(lon0, lat0, lon1, lat1, n - 1)
            out_lon.extend(p[0] for p in pts)
            out_lat.extend(p[1] for p in pts)
        out_lon.append(lon1)
        out_lat.append(lat1)

    return (
        np.array(out_lon, dtype=np.float64),
        np.array(out_lat, dtype=np.float64),
        np.array(out_alt, dtype=np.float64),
        np.array(out_ts, dtype=np.float64),
    )


def _stepwise_correction(
    query_ts: npt.NDArray[np.float64],
    corr_ts: list[float],
    corr_vals: list[float],
) -> npt.NDArray[np.float64]:
    """Return the stepwise correction value in effect at each query timestamp."""
    if not corr_ts:
        return np.zeros(len(query_ts), dtype=np.float64)
    corr_ts_arr = np.array(corr_ts, dtype=np.float64)
    corr_vals_arr = np.array(corr_vals, dtype=np.float64)
    indices = np.searchsorted(corr_ts_arr, query_ts, side="right") - 1
    indices = np.clip(indices, 0, len(corr_ts) - 1)
    return corr_vals_arr[indices]


def _td_tr_1d(
    ts: npt.NDArray[np.float64],
    vals: npt.NDArray[np.float64],
    epsilons: npt.NDArray[np.float64],
    start: int,
    end: int,
    kept: set[int],
) -> None:
    """Iterative TD-TR on a 1-D scalar series with per-point epsilon tolerances.

    Selects the interior point with the largest deviation relative to its local
    epsilon (deviation / epsilon[j]); recurses if that ratio exceeds 1.0.
    """
    stack = [(start, end)]
    while stack:
        s, e = stack.pop()
        if e - s < 2:
            continue
        dt = ts[e] - ts[s]
        if dt == 0.0:
            continue
        t_frac = (ts[s + 1 : e] - ts[s]) / dt
        interp = vals[s] + t_frac * (vals[e] - vals[s])
        deviations = np.abs(vals[s + 1 : e] - interp)
        normalized = deviations / epsilons[s + 1 : e]
        rel = int(np.argmax(normalized))
        if float(normalized[rel]) > 1.0:
            j = s + 1 + rel
            kept.add(j)
            stack.append((s, j))
            stack.append((j, e))


def _simplify_agl(
    ts: npt.NDArray[np.float64],
    agl: npt.NDArray[np.float64],
) -> tuple[list[float], list[float]]:
    """Apply TD-TR to a 1-D (ts, agl_ft) series with height-dependent epsilon.

    epsilon(agl) = max(_AGL_MIN_EPSILON_FT, agl * _AGL_EPSILON_FRACTION).
    Negative AGL values (data-quality artefacts) use the minimum epsilon.
    """
    n = len(ts)
    if n == 0:
        return [], []
    if n <= 2:
        return agl.tolist(), ts.tolist()
    epsilons = np.maximum(_AGL_MIN_EPSILON_FT, agl * _AGL_EPSILON_FRACTION)
    kept: set[int] = {0, n - 1}
    _td_tr_1d(ts, agl, epsilons, 0, n - 1, kept)
    idx = sorted(kept)
    return [float(agl[i]) for i in idx], [float(ts[i]) for i in idx]


def compute_agl_series(
    vertex_sequences: list[list[tuple[float, float, float, float]]],
    corr_ts: list[float] | None,
    corr_vals: list[float] | None,
    tile_manager: TileManager,
) -> list[tuple[list[float], list[float]]] | None:
    """Compute a simplified AGL height series for a flight.

    vertex_sequences: per-sub-sequence list of (lon, lat, pressure_alt_ft, ts_epoch).
    corr_ts, corr_vals: stepwise QNH correction series (timestamps_epoch, corrections_ft),
        or None when the correction is unavailable.
    tile_manager: provides terrain elevation sampling.

    Returns a list of (agl_ft_values, timestamps) pairs — one per sub-sequence —
    ready for tfloat_stepwise_seqset(), or None if no sub-sequence produced data.
    """
    result: list[tuple[list[float], list[float]]] = []
    has_any = False

    for seq in vertex_sequences:
        if not seq:
            result.append(([], []))
            continue

        lons, lats, alts_ft, ts = _densify(seq)

        corrections_ft = (
            _stepwise_correction(ts, corr_ts, corr_vals)
            if corr_ts and corr_vals
            else np.zeros(len(ts), dtype=np.float64)
        )

        try:
            elev_ft = tile_manager.sample_elevations(lons, lats)
        except Exception:
            logger.warning("Terrain sampling failed for sub-sequence", exc_info=True)
            result.append(([], []))
            continue

        agl_ft = alts_ft + corrections_ft - elev_ft

        simplified_vals, simplified_ts = _simplify_agl(ts, agl_ft)
        if simplified_vals:
            has_any = True
        result.append((simplified_vals, simplified_ts))

    return result if has_any else None
