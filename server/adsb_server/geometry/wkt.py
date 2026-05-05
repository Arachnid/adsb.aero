"""WKT geometry construction helpers for PostGIS insertion."""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def point_zm(lon: float, lat: float, alt_ft: float, ts_epoch: float) -> str:
    """Return a WKT POINTZM string."""
    return f"POINTZM({lon} {lat} {alt_ft} {ts_epoch})"


def linestring_zm(vertices: list[tuple[float, float, float, float]]) -> str:
    """Return a WKT LINESTRINGZM string from a list of (lon, lat, alt_ft, ts) tuples."""
    coords = ", ".join(f"{lon} {lat} {alt_ft} {ts}" for lon, lat, alt_ft, ts in vertices)
    return f"LINESTRINGZM({coords})"
