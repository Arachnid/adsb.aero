"""Unit tests for adsb_server.terrain.agl."""

from __future__ import annotations

from pathlib import Path  # noqa: TC003
from unittest.mock import MagicMock

import numpy as np
import pytest

from adsb_server.terrain.agl import (
    _AGL_EPSILON_FRACTION,
    _AGL_MIN_EPSILON_FT,
    _densify,
    _simplify_agl,
    _stepwise_correction,
    compute_agl_series,
)
from adsb_server.terrain.tiles import TileManager, _tile_name

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_flat_tile(data_dir: Path, tile_lat: int, tile_lon: int, elev_m: float) -> None:
    name = _tile_name(tile_lat, tile_lon)
    path = data_dir / f"{name}.npy"
    fill_ft = round(elev_m / 0.3048)
    data = np.full((20, 20), fill_ft, dtype=np.int16)
    np.save(path, data)


def _flat_tile_manager(tmp_path: Path, tile_lat: int, tile_lon: int, elev_m: float) -> TileManager:
    _make_flat_tile(tmp_path, tile_lat, tile_lon, elev_m)
    return TileManager(tmp_path)


# ---------------------------------------------------------------------------
# _densify
# ---------------------------------------------------------------------------


def test_densify_single_point() -> None:
    seq = [(10.0, 20.0, 5000.0, 1000.0)]
    lons, _lats, _alts, _ts = _densify(seq)
    assert len(lons) == 1
    assert float(lons[0]) == pytest.approx(10.0)


def test_densify_empty() -> None:
    lons, _lats, _alts, _ts = _densify([])
    assert len(lons) == 0


def test_densify_adds_intermediate_points() -> None:
    # Two points 1° apart horizontally → should produce > 2 output points.
    seq = [(0.0, 0.0, 0.0, 0.0), (1.0, 0.0, 0.0, 1.0)]
    lons, _lats, _alts, _ts = _densify(seq)
    assert len(lons) > 2


def test_densify_endpoints_preserved() -> None:
    seq = [(5.0, 10.0, 1000.0, 0.0), (5.1, 10.1, 2000.0, 60.0)]
    lons, lats, _alts, _ts = _densify(seq)
    assert float(lons[0]) == pytest.approx(5.0)
    assert float(lats[0]) == pytest.approx(10.0)
    assert float(lons[-1]) == pytest.approx(5.1, abs=1e-9)
    assert float(lats[-1]) == pytest.approx(10.1, abs=1e-9)


def test_densify_altitude_interpolated() -> None:
    seq = [(0.0, 0.0, 0.0, 0.0), (0.0, 0.1, 10000.0, 100.0)]
    _lons, _lats, alts, _ts = _densify(seq)
    # Altitude at the midpoint should be approximately 5000.
    mid = len(alts) // 2
    assert float(alts[mid]) == pytest.approx(5000.0, rel=0.1)


def test_densify_antimeridian_crossing() -> None:
    # Flight from lon=179.9 to lon=-179.9 (antimeridian crossing).
    seq = [(179.9, 0.0, 0.0, 0.0), (-179.9, 0.0, 0.0, 1.0)]
    lons, _lats, _alts, _ts = _densify(seq)
    # All intermediate longitudes should stay near ±180, not pass through 0.
    assert len(lons) >= 2
    # No intermediate point should be near 0° (would indicate wrong direction).
    interior = lons[1:-1]
    if len(interior) > 0:
        assert np.all(np.abs(interior) > 90.0)


# ---------------------------------------------------------------------------
# _stepwise_correction
# ---------------------------------------------------------------------------


def test_stepwise_correction_empty_series() -> None:
    ts = np.array([100.0, 200.0, 300.0])
    result = _stepwise_correction(ts, [], [])
    np.testing.assert_array_equal(result, np.zeros(3))


def test_stepwise_correction_single_value() -> None:
    ts = np.array([50.0, 150.0, 250.0])
    result = _stepwise_correction(ts, [0.0], [42.0])
    np.testing.assert_allclose(result, [42.0, 42.0, 42.0])


def test_stepwise_correction_steps() -> None:
    corr_ts = [0.0, 100.0, 200.0]
    corr_vals = [10.0, 20.0, 30.0]
    ts = np.array([50.0, 100.0, 150.0, 200.0, 250.0])
    result = _stepwise_correction(ts, corr_ts, corr_vals)
    # ts=50 → step at 0→10; ts=100 → step at 100→20; ts=150 → still 20;
    # ts=200 → step at 200→30; ts=250 → still 30.
    np.testing.assert_allclose(result, [10.0, 20.0, 20.0, 30.0, 30.0])


# ---------------------------------------------------------------------------
# _simplify_agl
# ---------------------------------------------------------------------------


def test_simplify_empty() -> None:
    vals, ts = _simplify_agl(np.array([]), np.array([]))
    assert vals == []
    assert ts == []


def test_simplify_two_points() -> None:
    ts = np.array([0.0, 1.0])
    agl = np.array([100.0, 200.0])
    vals, _out_ts = _simplify_agl(ts, agl)
    assert vals == pytest.approx([100.0, 200.0])


def test_simplify_constant_series_collapses() -> None:
    # All interior points are on the line → should keep only endpoints.
    ts = np.linspace(0.0, 100.0, 50)
    agl = np.full(50, 35000.0)
    vals, _out_ts = _simplify_agl(ts, agl)
    assert len(vals) == 2


def test_simplify_spike_retained() -> None:
    # 500 ft spike at 1000 ft AGL: epsilon = min (50 ft); spike >> 50 ft → kept.
    ts = np.array([0.0, 50.0, 100.0])
    agl = np.array([1000.0, 1500.0, 1000.0])
    vals, _out_ts = _simplify_agl(ts, agl)
    assert 1500.0 in vals


def test_simplify_collinear_dropped() -> None:
    # Point exactly on the linear interpolant → zero deviation → always dropped.
    ts = np.array([0.0, 50.0, 100.0])
    agl = np.array([1000.0, 1020.0, 1040.0])  # linear ramp
    vals, _out_ts = _simplify_agl(ts, agl)
    assert len(vals) == 2


def test_simplify_height_dependent_low_altitude() -> None:
    # At low AGL, epsilon = _AGL_MIN_EPSILON_FT (50 ft).
    # 30 ft spike → below min epsilon → dropped.
    # 80 ft spike → above min epsilon → kept.
    ts_drop = np.array([0.0, 50.0, 100.0])
    agl_drop = np.array([500.0, 530.0, 500.0])  # 30 ft spike at ~500 ft AGL
    vals_drop, _ = _simplify_agl(ts_drop, agl_drop)
    assert len(vals_drop) == 2

    ts_keep = np.array([0.0, 50.0, 100.0])
    agl_keep = np.array([500.0, 580.0, 500.0])  # 80 ft spike at ~500 ft AGL
    vals_keep, _ = _simplify_agl(ts_keep, agl_keep)
    assert 580.0 in vals_keep


def test_simplify_height_dependent_cruise_altitude() -> None:
    # At 35 000 ft AGL, epsilon ≈ 35000 * _AGL_EPSILON_FRACTION (>> min).
    cruise_eps = 35000.0 * _AGL_EPSILON_FRACTION
    assert cruise_eps > _AGL_MIN_EPSILON_FT  # sanity

    ts = np.array([0.0, 50.0, 100.0])
    # Spike half the cruise epsilon → below tolerance → dropped.
    small_spike = cruise_eps * 0.4
    agl_drop = np.array([35000.0, 35000.0 + small_spike, 35000.0])
    vals_drop, _ = _simplify_agl(ts, agl_drop)
    assert len(vals_drop) == 2

    # Spike 1.5x the cruise epsilon -> above tolerance -> kept.
    large_spike = cruise_eps * 1.5
    agl_keep = np.array([35000.0, 35000.0 + large_spike, 35000.0])
    vals_keep, _ = _simplify_agl(ts, agl_keep)
    assert 35000.0 + large_spike in vals_keep


# ---------------------------------------------------------------------------
# compute_agl_series
# ---------------------------------------------------------------------------


def test_compute_agl_flat_terrain(tmp_path: Path) -> None:
    """Flight at 10,000 ft over flat 0 m terrain → AGL ≈ 10,000 ft."""
    _make_flat_tile(tmp_path, tile_lat=0, tile_lon=0, elev_m=0.0)
    tm = TileManager(tmp_path)

    seqs = [[(0.5, 0.5, 10000.0, 0.0), (0.5, 0.6, 10000.0, 60.0)]]
    result = compute_agl_series(seqs, None, None, tm)

    assert result is not None
    agl_vals, _ = result[0]
    assert all(abs(v - 10000.0) < 50.0 for v in agl_vals)


def test_compute_agl_terrain_offset(tmp_path: Path) -> None:
    """Flight at 1000 ft over 100 m terrain → AGL ≈ 672 ft (100 m ≈ 328 ft)."""
    elev_m = 100.0
    _make_flat_tile(tmp_path, tile_lat=0, tile_lon=0, elev_m=elev_m)
    tm = TileManager(tmp_path)

    seqs = [[(0.5, 0.5, 1000.0, 0.0), (0.5, 0.6, 1000.0, 60.0)]]
    result = compute_agl_series(seqs, None, None, tm)

    assert result is not None
    agl_vals, _ = result[0]
    expected = 1000.0 - elev_m / 0.3048
    assert all(abs(v - expected) < 50.0 for v in agl_vals)


def test_compute_agl_with_correction(tmp_path: Path) -> None:
    """Correction is added before subtracting terrain elevation."""
    _make_flat_tile(tmp_path, tile_lat=0, tile_lon=0, elev_m=0.0)
    tm = TileManager(tmp_path)

    # pressure_alt=9500 ft, correction=+500 ft → QNH alt=10000 ft, terrain=0 → AGL≈10000 ft.
    seqs = [[(0.5, 0.5, 9500.0, 0.0), (0.5, 0.6, 9500.0, 60.0)]]
    result = compute_agl_series(seqs, [0.0], [500.0], tm)

    assert result is not None
    agl_vals, _ = result[0]
    assert all(abs(v - 10000.0) < 50.0 for v in agl_vals)


def test_compute_agl_empty_sequences() -> None:
    tm = MagicMock(spec=TileManager)
    result = compute_agl_series([], None, None, tm)
    assert result is None


def test_compute_agl_ocean_tile(tmp_path: Path) -> None:
    """When tile is absent from the dataset (ocean), elevation defaults to 0 m."""
    tm = TileManager(tmp_path)  # empty dir — no tiles present

    seqs = [[(100.5, 20.5, 5000.0, 0.0), (100.6, 20.5, 5000.0, 60.0)]]
    result = compute_agl_series(seqs, None, None, tm)

    assert result is not None
    agl_vals, _ = result[0]
    assert all(abs(v - 5000.0) < 50.0 for v in agl_vals)


def test_compute_agl_multiple_subsequences(tmp_path: Path) -> None:
    """Each sub-sequence is processed independently."""
    _make_flat_tile(tmp_path, tile_lat=0, tile_lon=0, elev_m=0.0)
    tm = TileManager(tmp_path)

    seqs = [
        [(0.1, 0.1, 1000.0, 0.0), (0.2, 0.1, 1000.0, 60.0)],
        [(0.3, 0.3, 2000.0, 120.0), (0.4, 0.3, 2000.0, 180.0)],
    ]
    result = compute_agl_series(seqs, None, None, tm)

    assert result is not None
    assert len(result) == 2
    agl0, _ = result[0]
    agl1, _ = result[1]
    assert all(abs(v - 1000.0) < 50.0 for v in agl0)
    assert all(abs(v - 2000.0) < 50.0 for v in agl1)
