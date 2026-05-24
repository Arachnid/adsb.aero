"""Unit tests for adsb_server.terrain.tiles.TileManager."""

from __future__ import annotations

from pathlib import Path  # noqa: TC003

import numpy as np
import pytest

from adsb_server.terrain.tiles import TileManager, _tile_name

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_npy_tile(data_dir: Path, tile_lat: int, tile_lon: int, fill_ft: int = 328) -> Path:
    """Write a synthetic .npy int16 tile with uniform elevation (feet)."""
    name = _tile_name(tile_lat, tile_lon)
    path = data_dir / f"{name}.npy"
    data = np.full((1200, 1200), fill_ft, dtype=np.int16)
    np.save(path, data)
    return path


def _make_npy_gradient_tile(
    data_dir: Path, tile_lat: int, tile_lon: int, base_ft: int, slope_ft_per_deg: float
) -> Path:
    """Write a .npy tile where elevation varies linearly with latitude.

    elevation_ft(row) = base_ft + slope_ft_per_deg * (lat - tile_lat)
    Row 0 is northernmost (lat = tile_lat+1), last row is southernmost (lat = tile_lat).
    """
    name = _tile_name(tile_lat, tile_lon)
    path = data_dir / f"{name}.npy"
    height = width = 120
    rows = np.arange(height)
    lats = (tile_lat + 1) - (rows + 0.5) / height
    data_ft = (base_ft + slope_ft_per_deg * (lats - tile_lat))[:, np.newaxis] * np.ones((1, width))
    data = np.clip(np.round(data_ft), -32768, 32767).astype(np.int16)
    np.save(path, data)
    return path


# ---------------------------------------------------------------------------
# _tile_name
# ---------------------------------------------------------------------------


def test_tile_name_northern_eastern() -> None:
    assert _tile_name(51, 4) == "Copernicus_DSM_COG_30_N51_00_E004_00_DEM"


def test_tile_name_southern_western() -> None:
    assert _tile_name(-34, -70) == "Copernicus_DSM_COG_30_S34_00_W070_00_DEM"


def test_tile_name_zero_lat_lon() -> None:
    assert _tile_name(0, 0) == "Copernicus_DSM_COG_30_N00_00_E000_00_DEM"


# ---------------------------------------------------------------------------
# TileManager — sample_elevations
# ---------------------------------------------------------------------------


def test_sample_uniform_elevation(tmp_path: Path) -> None:
    _make_npy_tile(tmp_path, tile_lat=51, tile_lon=4, fill_ft=656)
    tm = TileManager(tmp_path)

    lons = np.array([4.5], dtype=np.float64)
    lats = np.array([51.5], dtype=np.float64)
    elevs = tm.sample_elevations(lons, lats)

    assert elevs.shape == (1,)
    assert abs(float(elevs[0]) - 656.0) < 1.0


def test_sample_multiple_points_same_tile(tmp_path: Path) -> None:
    _make_npy_tile(tmp_path, tile_lat=0, tile_lon=0, fill_ft=1640)
    tm = TileManager(tmp_path)

    lons = np.array([0.1, 0.5, 0.9], dtype=np.float64)
    lats = np.array([0.1, 0.5, 0.9], dtype=np.float64)
    elevs = tm.sample_elevations(lons, lats)

    assert elevs.shape == (3,)
    for e in elevs:
        assert abs(float(e) - 1640.0) < 1.0


def test_sample_missing_tile_returns_zero(tmp_path: Path) -> None:
    """A tile absent from the dataset (ocean / not yet downloaded) returns 0 ft."""
    tm = TileManager(tmp_path)  # empty directory

    lons = np.array([10.5], dtype=np.float64)
    lats = np.array([20.5], dtype=np.float64)
    elevs = tm.sample_elevations(lons, lats)

    assert float(elevs[0]) == pytest.approx(0.0)


def test_sample_across_two_tiles(tmp_path: Path) -> None:
    _make_npy_tile(tmp_path, tile_lat=51, tile_lon=4, fill_ft=328)
    _make_npy_tile(tmp_path, tile_lat=51, tile_lon=5, fill_ft=656)
    tm = TileManager(tmp_path)

    lons = np.array([4.5, 5.5], dtype=np.float64)
    lats = np.array([51.5, 51.5], dtype=np.float64)
    elevs = tm.sample_elevations(lons, lats)

    assert abs(float(elevs[0]) - 328.0) < 1.0
    assert abs(float(elevs[1]) - 656.0) < 1.0


def test_missing_tile_recorded(tmp_path: Path) -> None:
    """After the first miss, the tile key is added to _missing to skip future stat() calls."""
    tm = TileManager(tmp_path)

    lons = np.array([50.5], dtype=np.float64)
    lats = np.array([50.5], dtype=np.float64)
    tm.sample_elevations(lons, lats)

    assert (50, 50) in tm._missing


def test_gradient_elevation_bilinear(tmp_path: Path) -> None:
    """Elevation varies linearly with latitude; bilinear interpolation should be close."""
    # slope = 3281 ft/deg
    _make_npy_gradient_tile(tmp_path, tile_lat=0, tile_lon=0, base_ft=0, slope_ft_per_deg=3281)
    tm = TileManager(tmp_path)

    # At lat=0.25, expected elevation ≈ 3281 * 0.25 ≈ 820 ft.
    # Bilinear is essentially exact for a linear gradient; int16 quantisation ≈ 1 ft.
    lons = np.array([0.5], dtype=np.float64)
    lats = np.array([0.25], dtype=np.float64)
    elevs = tm.sample_elevations(lons, lats)

    assert abs(float(elevs[0]) - 820.0) < 5.0  # within 5 ft
