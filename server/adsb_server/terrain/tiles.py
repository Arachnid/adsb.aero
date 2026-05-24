"""GLO-90 DEM tile reader.

Reads Copernicus 90-m DEM tiles from a pre-populated local dataset directory.
Use `download-terrain` to populate that directory.

One TileManager instance is created per batch in the parent process and
inherited by forked workers.  Each worker opens tile files on-demand and
relies on the OS page cache for repeated access — no Python-level tile cache
is maintained to avoid OOM on long-haul flights that span many tiles.
"""

from __future__ import annotations

import logging
from pathlib import Path  # noqa: TC003

import numpy as np
import numpy.typing as npt

logger = logging.getLogger(__name__)


def _tile_name(tile_lat: int, tile_lon: int) -> str:
    """Return the GLO-90 tile name for the cell whose SW corner is (tile_lat, tile_lon)."""
    ns = "N" if tile_lat >= 0 else "S"
    ew = "E" if tile_lon >= 0 else "W"
    return f"Copernicus_DSM_COG_30_{ns}{abs(tile_lat):02d}_00_{ew}{abs(tile_lon):03d}_00_DEM"


def _sample_tile(
    path: Path,
    tile_lat: int,
    tile_lon: int,
    lons: npt.NDArray[np.float64],
    lats: npt.NDArray[np.float64],
) -> npt.NDArray[np.float64]:
    """Read a GLO-90 int16-feet .npy tile and return elevation in feet at each point.

    Uses bilinear interpolation over the four surrounding pixels.
    GLO-90 is always 1200x1200 pixels per degree; the hardcoded transform
    matches every tile without needing rasterio metadata.
    """
    data_feet: npt.NDArray[np.int16] = np.load(path)
    nrows, ncols = data_feet.shape
    # GLO-90 pixel-centre convention (row 0 = northernmost):
    #   lat_centre(r) = (tile_lat+1) - (r+0.5)/nrows
    #   lon_centre(c) = tile_lon      + (c+0.5)/ncols
    row_f = ((tile_lat + 1) - lats) * nrows - 0.5
    col_f = (lons - tile_lon) * ncols - 0.5
    # Clamp floor indices so r0+1 and c0+1 are always in bounds.
    r0 = np.clip(np.floor(row_f).astype(np.int32), 0, nrows - 2)
    c0 = np.clip(np.floor(col_f).astype(np.int32), 0, ncols - 2)
    r1 = r0 + 1
    c1 = c0 + 1
    dr = np.clip((row_f - r0).astype(np.float64), 0.0, 1.0)
    dc = np.clip((col_f - c0).astype(np.float64), 0.0, 1.0)
    v00 = data_feet[r0, c0].astype(np.float64)
    v01 = data_feet[r0, c1].astype(np.float64)
    v10 = data_feet[r1, c0].astype(np.float64)
    v11 = data_feet[r1, c1].astype(np.float64)
    return (
        (1.0 - dr) * (1.0 - dc) * v00
        + (1.0 - dr) * dc * v01
        + dr * (1.0 - dc) * v10
        + dr * dc * v11
    )


class TileManager:
    """Sample terrain elevations from a pre-downloaded GLO-90 dataset directory."""

    def __init__(self, data_dir: Path) -> None:
        self._data_dir = data_dir
        # Lightweight set of confirmed-absent tiles (ocean / not downloaded).
        # Avoids repeated stat() calls; stores only (int, int) tuples.
        self._missing: set[tuple[int, int]] = set()

    def sample_elevations(
        self,
        lons: npt.NDArray[np.float64],
        lats: npt.NDArray[np.float64],
    ) -> npt.NDArray[np.float64]:
        """Return terrain elevation in feet for each (lon, lat) pair.

        Points with no corresponding tile (ocean or dataset not yet downloaded)
        return 0.0 ft (sea level).
        """
        result: npt.NDArray[np.float64] = np.zeros(len(lons), dtype=np.float64)

        tile_lats = np.floor(lats).astype(np.int32)
        tile_lons = np.floor(lons).astype(np.int32)

        unique_tiles = set(zip(tile_lats.tolist(), tile_lons.tolist(), strict=False))
        for tile_lat, tile_lon in unique_tiles:
            key = (tile_lat, tile_lon)
            if key in self._missing:
                continue

            name = _tile_name(tile_lat, tile_lon)
            npy_path = self._data_dir / f"{name}.npy"
            if not npy_path.exists():
                self._missing.add(key)
                continue

            mask = (tile_lats == tile_lat) & (tile_lons == tile_lon)
            indices = np.where(mask)[0]
            try:
                result[indices] = _sample_tile(
                    npy_path, tile_lat, tile_lon, lons[indices], lats[indices]
                )
            except Exception:
                logger.warning("Failed to sample DEM tile %s", npy_path, exc_info=True)

        return result


def tile_name_for_point(lat: float, lon: float) -> str:
    """Return the GLO-90 tile name for the given coordinate (for testing/CLI use)."""
    import math

    return _tile_name(math.floor(lat), math.floor(lon))
