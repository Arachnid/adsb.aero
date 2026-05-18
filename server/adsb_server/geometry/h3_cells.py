"""H3 cell coverage for flight trajectories and query circles."""

from __future__ import annotations

import math

import h3
from pyproj import Geod

_GEOD = Geod(ellps="WGS84")

# H3 resolution 4 geometry constants (approximate).
H3_RES = 4
_EDGE_M = 22_600  # edge length in metres
_CIRCUMRADIUS_M = 24_800  # circumradius (centre to vertex) in metres

# Densification step: half an edge length guarantees consecutive densified
# waypoints are always in the same or adjacent cells, so grid_path_cells
# captures all cells the segment passes through.
_MAX_SEGMENT_M = _EDGE_M // 2


def path_h3_cells(
    vertex_sequences: list[list[tuple[float, float, float, float]]],
) -> list[str]:
    """Return distinct H3 res-4 cell IDs covering every sub-sequence of a flight path.

    vertex_sequences: one list per sub-sequence, each element (lon, lat, alt_ft, ts_epoch).

    For each sub-sequence the path is densified so no segment exceeds _MAX_SEGMENT_M,
    then h3.grid_path_cells walks between consecutive cells to capture every cell the
    linestring passes through — including cells only briefly clipped at a corner.
    Cross-face failures (h3.grid_path_cells raises) fall back to adding the destination
    cell only; at _MAX_SEGMENT_M ≈ 11 km this is extremely rare.
    """
    cells: set[str] = set()

    for seq in vertex_sequences:
        if len(seq) < 1:
            continue

        # Build a densified list of (lon, lat) at most _MAX_SEGMENT_M apart.
        dense: list[tuple[float, float]] = [(seq[0][0], seq[0][1])]
        for i in range(len(seq) - 1):
            lon1, lat1 = seq[i][0], seq[i][1]
            lon2, lat2 = seq[i + 1][0], seq[i + 1][1]
            _, _, dist_m = _GEOD.inv(lon1, lat1, lon2, lat2)
            if dist_m > _MAX_SEGMENT_M:
                n_inter = math.ceil(dist_m / _MAX_SEGMENT_M) - 1
                dense.extend(_GEOD.npts(lon1, lat1, lon2, lat2, n_inter))
            dense.append((lon2, lat2))

        # Walk the densified waypoints, collecting cells via grid_path_cells.
        prev = h3.latlng_to_cell(dense[0][1], dense[0][0], H3_RES)
        cells.add(prev)
        for lon, lat in dense[1:]:
            curr = h3.latlng_to_cell(lat, lon, H3_RES)
            if curr == prev:
                continue
            try:
                cells.update(h3.grid_path_cells(prev, curr))
            except Exception:
                cells.add(curr)
            prev = curr

    return list(cells)


def query_disk(lat: float, lon: float, radius_m: float) -> list[str]:
    """Return H3 res-4 cell IDs for a disk covering the given circle.

    k is chosen so every H3 cell geometrically overlapping the circle is included.
    A boundary cell's centroid can be up to radius + 2*circumradius from the query
    centre cell's centroid, so: k = max(1, floor((radius + 2*circumradius) / edge)).
    """
    k = max(1, int((radius_m + 2 * _CIRCUMRADIUS_M) / _EDGE_M))
    center = h3.latlng_to_cell(lat, lon, H3_RES)
    return list(h3.grid_disk(center, k))


def query_polygon_cells(rings: list[list[tuple[float, float]]]) -> list[str]:
    """Return H3 res-4 cell IDs covering a GeoJSON polygon.

    rings: list of coordinate rings as (lon, lat) pairs; rings[0] is the exterior.

    Strategy:
      1. polygon_to_cells (centre containment) for the interior.
      2. Treat each ring as a path and collect boundary cells with path_h3_cells.
      3. Expand the union by one ring so that paths clipping just the polygon edge
         (whose sample cells are adjacent to a polygon cell) are still found.

    This handles thin polygons (where polygon_to_cells returns nothing) because the
    boundary-path step always produces cells regardless of polygon width.
    """
    exterior_lonlat = rings[0]

    # Interior cells — centres inside the polygon.
    try:
        latlng_poly = h3.LatLngPoly([(lat, lon) for lon, lat in exterior_lonlat])
        if len(rings) > 1:
            holes = [[(lat, lon) for lon, lat in ring] for ring in rings[1:]]
            latlng_poly = h3.LatLngPoly([(lat, lon) for lon, lat in exterior_lonlat], *holes)
        interior: set[str] = set(h3.polygon_to_cells(latlng_poly, H3_RES))
    except Exception:
        interior = set()

    # Boundary cells — walk each ring as a path.
    boundary: set[str] = set()
    for ring in rings:
        closed = list(ring)
        if closed[0] != closed[-1]:
            closed.append(closed[0])
        # vertex_sequences format: (lon, lat, alt_ft, ts_epoch)
        seq: list[tuple[float, float, float, float]] = [(lon, lat, 0.0, 0.0) for lon, lat in closed]
        boundary.update(path_h3_cells([seq]))

    # One-ring expansion so adjacent-to-boundary sample cells are covered.
    all_cells = interior | boundary
    result: set[str] = set()
    for cell in all_cells:
        result.update(h3.grid_disk(cell, 1))
    return list(result)
