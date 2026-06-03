"""In-memory KD-tree index for O(log n) nearest-airport lookup during ingestion.

Built once from the waypoints table before the worker pool is forked; all forked
workers inherit it via copy-on-write.  Single-query radius lookups take ~1 µs.

Matching logic by emitter category:
- Fixed-wing (non-A7): nearest airport of a fixed-wing type within MATCH_RADIUS_M.
  Heliports (types 4, 7) excluded.
- Rotorcraft (A7): nearest civil/military heliport (types 4, 7) preferred; falls
  back to the nearest fixed-wing airport if no heliport is within range.

OpenAIP airport type codes (stored in waypoints.type_code):
  0  Airport (civil/military)   1  Glider Site
  2  Airfield Civil              3  International Airport
  4  Heliport Military           5  Military Aerodrome
  6  Ultra Light Flying Site     7  Heliport Civil
  8  Aerodrome Closed            9  Airport / Airfield IFR
  10 Airfield Water              11 Landing Strip
  12 Agricultural Landing Strip  13 Altiport
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

import numpy as np
from scipy.spatial import cKDTree

if TYPE_CHECKING:
    from collections.abc import Sequence

MATCH_RADIUS_M: float = 5_000.0
# At 5 km horizontal distance a standard 3° glide path puts an aircraft at
# ~640 ft AGL; 1 000 ft provides a comfortable safety margin.
AGL_MATCH_MAX_FT: float = 1_000.0
_EARTH_RADIUS_M: float = 6_371_000.0

# Closed aerodromes — excluded from both trees.
CLOSED_TYPES: frozenset[int] = frozenset({8})
# Types representing heliport facilities.
HELIPORT_TYPES: frozenset[int] = frozenset({4, 7})
# All non-closed, non-heliport types accepted by fixed-wing traffic.
FIXED_WING_TYPES: frozenset[int] = frozenset({0, 1, 2, 3, 5, 6, 9, 10, 11, 12, 13})


def _build_tree(
    rows: Sequence[tuple[str, float, float, int | None]],
    accepted_types: frozenset[int],
) -> tuple[cKDTree | None, list[str]]:
    filtered = [(r[0], r[1], r[2]) for r in rows if r[3] is not None and r[3] in accepted_types]
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
    """Spatial index of waypoints for fast nearest-airport queries."""

    __slots__ = ("_fw_idents", "_fw_tree", "_hp_idents", "_hp_tree")

    def __init__(self, rows: Sequence[tuple[str, float, float, int | None]]) -> None:
        """rows: sequence of (waypoints.id, lon_deg, lat_deg, type_code)."""
        self._fw_tree, self._fw_idents = _build_tree(rows, FIXED_WING_TYPES)
        self._hp_tree, self._hp_idents = _build_tree(rows, HELIPORT_TYPES)

    @classmethod
    def from_rows(cls, rows: Sequence[tuple[str, float, float, int | None]]) -> AirportIndex:
        return cls(rows)

    def nearest(self, lon: float, lat: float, emitter_category: str | None = None) -> str | None:
        """Return the waypoints.id of the nearest matching airport within MATCH_RADIUS_M.

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
