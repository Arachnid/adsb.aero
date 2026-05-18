"""Compute QNH altitude correction timeseries for flights from MSLP data."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import numpy as np
import numpy.typing as npt
from scipy.interpolate import RegularGridInterpolator

if TYPE_CHECKING:
    import xarray as xr

logger = logging.getLogger(__name__)

_ISA_HPA = 1013.25
_FT_PER_HPA = 27.3
_THRESHOLD_FT = 30.0


def build_correction_interpolator(
    mslp: xr.DataArray,
) -> tuple[RegularGridInterpolator, float, float]:
    """
    Build a scipy RegularGridInterpolator from an MSLP DataArray.

    Call once per batch and pass the result to compute_correction_series.
    Building on every flight call is the primary performance bottleneck.

    Returns (interp, t_min, t_max) where t_min/t_max are Unix-epoch seconds
    bounding the time axis, used by compute_correction_series for clamping.

    Axes: (time_seconds, latitude, longitude).
    Time axis uses float64 seconds since Unix epoch so query points (unix
    epoch floats from vertex timestamps) match without any unit conversion.
    Latitude and longitude axes are sorted ascending as required.
    """
    t_float: npt.NDArray[np.float64] = mslp.valid_time.values.astype("datetime64[s]").astype(
        np.float64
    )
    lat_float: npt.NDArray[np.float64] = mslp.latitude.values.astype(np.float64)
    lon_float: npt.NDArray[np.float64] = mslp.longitude.values.astype(np.float64)
    data: npt.NDArray[np.float64] = mslp.values.astype(np.float64)

    t_idx = np.argsort(t_float)
    lat_idx = np.argsort(lat_float)
    t_sorted = t_float[t_idx]
    lat_sorted = lat_float[lat_idx]
    data_sorted = data[t_idx][:, lat_idx, :]

    interp = RegularGridInterpolator(
        (t_sorted, lat_sorted, lon_float),
        data_sorted,
        method="linear",
        bounds_error=False,
        fill_value=np.nan,
    )
    return interp, float(t_sorted[0]), float(t_sorted[-1])


def compute_correction_series(
    vertices: list[tuple[float, float, float, float]],
    interp: RegularGridInterpolator,
    t_min: float,
    t_max: float,
) -> tuple[list[float], list[float]] | None:
    """
    Compute a stepwise QNH altitude correction timeseries for one flight.

    vertices: list of (lon, lat, pressure_alt_ft, ts_epoch) sorted by ts.
              Longitudes in [-180, 180].
    interp: pre-built interpolator from build_correction_interpolator().
    t_min/t_max: Unix-epoch time bounds of the MSLP grid (for clamping).

    Vertex timestamps outside [t_min, t_max] are clamped to the nearest
    boundary before querying, which gives a far better approximation than
    falling back to ISA standard (pressure doesn't change much in one hour).

    Returns (timestamps_epoch, corrections_ft) where timestamps_epoch is a list
    of unix epoch floats and corrections_ft is the matching list of correction
    values in feet.  The first entry anchors the flight's start and the last
    anchors its end, so the tfloat's temporal domain spans the full flight.

    Returns None if vertices is empty.
    """
    if not vertices:
        return None

    lons: npt.NDArray[np.float64] = np.array([v[0] for v in vertices], dtype=np.float64)
    lats: npt.NDArray[np.float64] = np.array([v[1] for v in vertices], dtype=np.float64)
    ts_epoch: npt.NDArray[np.float64] = np.array([v[3] for v in vertices], dtype=np.float64)

    # Normalise to [0, 360) to align with the padded DataArray's coordinate range
    lons_norm: npt.NDArray[np.float64] = lons % 360.0

    # Clamp timestamps to the grid's time bounds.  GFS boundary values are a
    # much better proxy for just-outside-range times than ISA standard.
    out_of_bounds = (ts_epoch < t_min) | (ts_epoch > t_max)
    if out_of_bounds.any():
        logger.debug(
            "%d vertices outside MSLP time bounds; clamping to nearest boundary",
            int(out_of_bounds.sum()),
        )
    ts_clamped: npt.NDArray[np.float64] = np.clip(ts_epoch, t_min, t_max)

    try:
        query: npt.NDArray[np.float64] = np.column_stack([ts_clamped, lats, lons_norm])
        raw: npt.NDArray[np.float64] = interp(query).astype(np.float64)
    except Exception:
        logger.exception("MSLP interpolation failed for flight correction")
        return None

    # After time clamping, NaN can only come from lat/lon out of range —
    # unexpected given the padded grid covers all valid coordinates.
    nan_mask: npt.NDArray[np.bool_] = np.isnan(raw)
    if nan_mask.any():
        logger.warning(
            "%d unexpected NaN after time clamping (lat/lon out of bounds?); using ISA fallback",
            int(nan_mask.sum()),
        )
        raw = np.where(nan_mask, _ISA_HPA, raw)

    corrections_ft: npt.NDArray[np.float64] = (raw - _ISA_HPA) * _FT_PER_HPA

    # Run-length deduplicate with _THRESHOLD_FT tolerance.
    # Always emit the first vertex (anchors the tfloat start).
    # Always emit the last vertex (anchors the tfloat end).
    out_ts: list[float] = [float(ts_epoch[0])]
    out_corr: list[float] = [float(corrections_ft[0])]

    for i in range(1, len(vertices) - 1):
        if abs(float(corrections_ft[i]) - out_corr[-1]) >= _THRESHOLD_FT:
            out_ts.append(float(ts_epoch[i]))
            out_corr.append(float(corrections_ft[i]))

    if len(vertices) > 1:
        out_ts.append(float(ts_epoch[-1]))
        out_corr.append(float(corrections_ft[-1]))

    return out_ts, out_corr
