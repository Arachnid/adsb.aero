"""In-memory KD-tree index for O(log n) nearest-airport lookup during ingestion.

Built once from the airports table before the worker pool is forked; all forked
workers inherit it via copy-on-write.  Single-query radius lookups take ~1 µs.

Matching logic by emitter category:
- Fixed-wing (non-A7): nearest airport of type large/medium/small/seaplane_base
  within MATCH_RADIUS_M.  Heliports are excluded.
- Rotorcraft (A7): nearest heliport within MATCH_RADIUS_M; if none, fall back
  to the fixed-wing tree.  This ensures helicopters are matched to a heliport
  when one is nearby rather than a large airport that happens to be closer.
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

import numpy as np
from scipy.spatial import cKDTree

if TYPE_CHECKING:
    from collections.abc import Sequence

MATCH_RADIUS_M: float = 5_000.0
# Only assign an airport when the first/last ADS-B point is below this AGL
# threshold.  At 5 km horizontal distance a 3° glide path puts the aircraft at
# ~640 ft, so 1 000 ft provides a comfortable margin while excluding overflying
# traffic.  Applied only when AGL data is available; falls back to
# proximity-only matching when it is not.
AGL_MATCH_MAX_FT: float = 1_000.0
_EARTH_RADIUS_M: float = 6_371_000.0

FIXED_WING_TYPES: frozenset[str] = frozenset(
    {"large_airport", "medium_airport", "small_airport", "seaplane_base"}
)
HELIPORT_TYPES: frozenset[str] = frozenset({"heliport"})


def _build_tree(
    rows: Sequence[tuple[str, float, float, str]],
    accepted_types: frozenset[str],
) -> tuple[cKDTree | None, list[str]]:
    filtered = [(r[0], r[1], r[2]) for r in rows if r[3] in accepted_types]
    if not filtered:
        return None, []
    idents = [r[0] for r in filtered]
    lons_r = np.radians([r[1] for r in filtered])
    lats_r = np.radians([r[2] for r in filtered])
    xs = _EARTH_RADIUS_M * np.cos(lats_r) * np.cos(lons_r)
    ys = _EARTH_RADIUS_M * np.cos(lats_r) * np.sin(lons_r)
    zs = _EARTH_RADIUS_M * np.sin(lats_r)
    return cKDTree(np.column_stack([xs, ys, zs])), idents


def _query(
    tree: cKDTree | None,
    idents: list[str],
    x: float,
    y: float,
    z: float,
) -> str | None:
    if tree is None or not idents:
        return None
    dist, idx = tree.query([x, y, z], distance_upper_bound=MATCH_RADIUS_M)
    if dist == np.inf:
        return None
    return idents[int(idx)]


class AirportIndex:
    """Spatial index of airport locations for fast nearest-airport queries."""

    __slots__ = ("_fw_idents", "_fw_tree", "_hp_idents", "_hp_tree")

    def __init__(self, rows: Sequence[tuple[str, float, float, str]]) -> None:
        """rows: sequence of (ident, lon_deg, lat_deg, airport_type)."""
        self._fw_tree, self._fw_idents = _build_tree(rows, FIXED_WING_TYPES)
        self._hp_tree, self._hp_idents = _build_tree(rows, HELIPORT_TYPES)

    @classmethod
    def from_rows(cls, rows: Sequence[tuple[str, float, float, str]]) -> AirportIndex:
        return cls(rows)

    def nearest(self, lon: float, lat: float, emitter_category: str | None = None) -> str | None:
        """Return the ident of the nearest matching airport within MATCH_RADIUS_M.

        For rotorcraft (A7): prefers the nearest heliport; falls back to the
        nearest fixed-wing airport if no heliport is within range.
        For all other categories: nearest fixed-wing airport only.
        """
        lon_r = math.radians(lon)
        lat_r = math.radians(lat)
        x = _EARTH_RADIUS_M * math.cos(lat_r) * math.cos(lon_r)
        y = _EARTH_RADIUS_M * math.cos(lat_r) * math.sin(lon_r)
        z = _EARTH_RADIUS_M * math.sin(lat_r)

        if emitter_category == "A7":
            result = _query(self._hp_tree, self._hp_idents, x, y, z)
            if result is not None:
                return result

        return _query(self._fw_tree, self._fw_idents, x, y, z)
