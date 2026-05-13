"""Unit tests for pressure altitude correction computation."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
import xarray as xr

from adsb_server.pressure.correct import (
    _FT_PER_HPA,
    _ISA_HPA,
    _THRESHOLD_FT,
    build_correction_interpolator,
    compute_correction_series,
)


def _compute(
    vertices: list[tuple[float, float, float, float]],
    mslp: xr.DataArray,
) -> tuple[list[float], list[float]] | None:
    interp, t_min, t_max = build_correction_interpolator(mslp)
    return compute_correction_series(vertices, interp, t_min, t_max)

# Base unix epoch for test vertices: 2025-01-01T01:00:00 UTC
_BASE_TS = pd.Timestamp("2025-01-01T01:00:00", tz="UTC").timestamp()
_HOUR = 3600.0


def _make_mslp(
    mslp_val: float = _ISA_HPA,
    lon_gradient: float = 0.0,
) -> xr.DataArray:
    """
    Build a minimal padded MSLP DataArray for testing.

    Covers 24 hourly steps from 2025-01-01T00:00Z.
    Longitude is already padded to [-0.25, 360.0].
    mslp_val: uniform base pressure in hPa.
    lon_gradient: adds (lon / 360) * lon_gradient to the uniform value,
                  where lon is in the padded [0, 360] coordinate space.
    """
    lons = np.array([-0.25, 0.0, 90.0, 180.0, 270.0, 359.75, 360.0])
    lats = np.array([-90.0, -45.0, 0.0, 45.0, 90.0])
    times = pd.date_range("2025-01-01T00:00", periods=24, freq="1h")

    # Build a (time, lat, lon) array
    lon_vals = np.clip(lons, 0.0, 360.0)  # for gradient calc use 0-360 range
    data = mslp_val + lon_gradient * (lon_vals / 360.0)
    # Broadcast to full shape: (time, lat, lon)
    data_3d = np.broadcast_to(
        data[np.newaxis, np.newaxis, :],
        (len(times), len(lats), len(lons)),
    ).copy()

    return xr.DataArray(
        data_3d,
        dims=("valid_time", "latitude", "longitude"),
        coords={"valid_time": times, "latitude": lats, "longitude": lons},
    )


def _vertex(lon: float, lat: float, ts_offset: float = 0.0) -> tuple[float, float, float, float]:
    """Convenience: build a vertex tuple with a fixed pressure alt of 5000 ft."""
    return (lon, lat, 5000.0, _BASE_TS + ts_offset)


# ---------------------------------------------------------------------------
# Basic correctness
# ---------------------------------------------------------------------------


def test_correction_formula() -> None:
    """Correction = (mslp - 1013.25) * 27.3."""
    mslp_val = 1020.0
    expected = (mslp_val - _ISA_HPA) * _FT_PER_HPA
    mslp = _make_mslp(mslp_val)
    vertices = [_vertex(0.0, 51.5, 0.0), _vertex(1.0, 51.5, _HOUR)]
    result = _compute(vertices, mslp)
    assert result is not None
    ts, corr = result
    assert corr[0] == pytest.approx(expected, abs=1.0)
    assert corr[-1] == pytest.approx(expected, abs=1.0)


# ---------------------------------------------------------------------------
# Deduplication tests
# ---------------------------------------------------------------------------


def test_stable_pressure_two_entries() -> None:
    """Uniform pressure produces exactly two entries: start and end."""
    mslp = _make_mslp(1013.25)
    vertices = [_vertex(0.0, 51.0, i * 600.0) for i in range(10)]
    result = _compute(vertices, mslp)
    assert result is not None
    ts, corr = result
    assert len(ts) == 2
    assert len(corr) == 2
    assert pytest.approx(corr[0], abs=0.01) == 0.0
    assert pytest.approx(corr[-1], abs=0.01) == 0.0


def test_below_threshold_two_entries() -> None:
    """Corrections varying by less than threshold collapse to just start+end entries."""
    # lon_gradient=1.0 → correction varies by at most 1.0*(4.5/360)*27.3 ≈ 0.34 ft
    # over the 4.5° flight — well below the 5 ft threshold.
    mslp = _make_mslp(lon_gradient=1.0)
    vertices = [_vertex(float(i) * 0.5, 51.0, i * 600.0) for i in range(10)]
    result = _compute(vertices, mslp)
    assert result is not None
    ts, corr = result
    assert len(ts) == 2


def test_at_threshold_three_entries() -> None:
    """A midpoint with correction >= _THRESHOLD_FT is emitted as a separate entry."""
    # Use a peak of 40 ft — clearly above the 30 ft threshold.
    peak_ft = 40.0
    peak_hpa = peak_ft / _FT_PER_HPA

    lons = np.array([-0.25, 0.0, 5.0, 10.0, 360.0])
    lats = np.array([-90.0, 0.0, 90.0])
    times = pd.date_range("2025-01-01T00:00", periods=24, freq="1h")

    data_1d = np.array([_ISA_HPA, _ISA_HPA, _ISA_HPA + peak_hpa, _ISA_HPA, _ISA_HPA])
    data_3d = np.broadcast_to(
        data_1d[np.newaxis, np.newaxis, :],
        (len(times), len(lats), len(lons)),
    ).copy()
    mslp = xr.DataArray(
        data_3d,
        dims=("valid_time", "latitude", "longitude"),
        coords={"valid_time": times, "latitude": lats, "longitude": lons},
    )

    vertices = [
        _vertex(0.0, 0.0, 0.0),          # correction ≈ 0
        _vertex(5.0, 0.0, _HOUR),         # correction ≈ 10 ft (above threshold)
        _vertex(10.0, 0.0, 2 * _HOUR),   # correction ≈ 0 (always emitted as last)
    ]
    result = _compute(vertices, mslp)
    assert result is not None
    ts, corr = result
    assert len(ts) == 3
    assert corr[1] == pytest.approx(peak_ft, rel=0.01)


def test_single_vertex() -> None:
    """A single-vertex flight produces exactly one entry."""
    mslp = _make_mslp(1015.0)
    vertices = [_vertex(0.0, 51.0, 0.0)]
    result = _compute(vertices, mslp)
    assert result is not None
    ts, corr = result
    assert len(ts) == 1
    assert len(corr) == 1
    expected = (1015.0 - _ISA_HPA) * _FT_PER_HPA
    assert corr[0] == pytest.approx(expected, abs=1.0)


def test_empty_vertices_returns_none() -> None:
    mslp = _make_mslp()
    assert _compute([], mslp) is None


# ---------------------------------------------------------------------------
# Seam and longitude normalisation tests
# ---------------------------------------------------------------------------


def test_seam_crossing_no_nan() -> None:
    """A flight crossing the 0°/360° seam produces no NaN corrections."""
    mslp = _make_mslp(1013.25)
    # Vertices on both sides of the seam (normalises to 358, 359, 0, 1, 2)
    seam_lons = [-2.0, -1.0, 0.0, 1.0, 2.0]
    vertices = [_vertex(lon, 51.0, i * 600.0) for i, lon in enumerate(seam_lons)]
    result = _compute(vertices, mslp)
    assert result is not None
    ts, corr = result
    assert not any(np.isnan(c) for c in corr)


def test_negative_longitude_equals_360_equiv() -> None:
    """lon=-5 and lon=355 normalise identically and produce the same corrections."""
    mslp = _make_mslp(1018.0)
    vertices_neg = [_vertex(-5.0, 51.0, 0.0), _vertex(-5.0, 51.0, _HOUR)]
    vertices_pos = [_vertex(355.0, 51.0, 0.0), _vertex(355.0, 51.0, _HOUR)]
    result_neg = _compute(vertices_neg, mslp)
    result_pos = _compute(vertices_pos, mslp)
    assert result_neg is not None and result_pos is not None
    _, corr_neg = result_neg
    _, corr_pos = result_pos
    assert corr_neg == pytest.approx(corr_pos, abs=0.01)
