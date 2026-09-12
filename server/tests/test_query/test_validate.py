"""Unit tests for geometry size limiting inside compile_predicate.

These tests verify that oversized geometries raise GeometryTooLargeError at
compile time, that an area up to the documented cap still compiles, and that the
limit applies to trajectory predicates only (EndpointWithin is exempt because it
does not use the H3 GIN index). No database is required.
"""

from __future__ import annotations

from datetime import datetime

import pytest

from adsb_server.query.compiler import (
    MAX_QUERY_H3_CELLS,
    GeometryTooLargeError,
    compile_predicate,
)
from adsb_server.query.models import (
    AndPredicate,
    EndpointWithin,
    EndpointWithinValue,
    NotPredicate,
    OrPredicate,
    SpatioTemporalAltitudeValue,
    TrajectoryIntersects,
    TrajectoryWithin,
)

# Small polygon — well under the cell limit.
_SMALL_POLY = {
    "type": "Polygon",
    "coordinates": [[[-2, 50], [2, 50], [2, 52], [-2, 52], [-2, 50]]],
}

# Large polygon covering a substantial portion of the North Atlantic (>2000 cells).
_HUGE_POLY = {
    "type": "Polygon",
    "coordinates": [[[-60, 30], [20, 30], [20, 70], [-60, 70], [-60, 30]]],
}

# Small circle — well under the cell limit.
_SMALL_CIRCLE = {"type": "Circle", "coordinates": [-1.0, 52.0], "radius": 50_000}

# Large circle with radius 1500 km (~7M km²) — comfortably over the cell limit.
_HUGE_CIRCLE = {"type": "Circle", "coordinates": [0.0, 51.0], "radius": 1_500_000}

# The bounding box used by the "squawking 7700" worked example in llms.txt.
# ~723 cells once padded: under the cap, and the largest area the docs promise.
# A cap set below this made the documented example fail with a 422.
_UK_BOX = {
    "type": "Polygon",
    "coordinates": [[[-8, 49], [2, 49], [2, 61], [-8, 61], [-8, 49]]],
}


class TestGeometrySizeLimit:
    def test_small_polygon_intersects_compiles(self) -> None:
        pred = TrajectoryIntersects(
            trajectory_intersects=SpatioTemporalAltitudeValue(geometry=_SMALL_POLY)
        )
        params: list[object] = []
        compile_predicate(pred, params)  # must not raise

    def test_small_circle_within_compiles(self) -> None:
        pred = TrajectoryWithin(
            trajectory_within=SpatioTemporalAltitudeValue(geometry=_SMALL_CIRCLE)
        )
        params: list[object] = []
        compile_predicate(pred, params)  # must not raise

    def test_uk_sized_box_compiles(self) -> None:
        """The llms.txt 7700 example must not be refused by its own documented cap."""
        pred = TrajectoryIntersects(
            trajectory_intersects=SpatioTemporalAltitudeValue(geometry=_UK_BOX)
        )
        params: list[object] = []
        compile_predicate(pred, params)  # must not raise

    def test_huge_polygon_intersects_raises(self) -> None:
        pred = TrajectoryIntersects(
            trajectory_intersects=SpatioTemporalAltitudeValue(geometry=_HUGE_POLY)
        )
        params: list[object] = []
        with pytest.raises(GeometryTooLargeError, match=str(MAX_QUERY_H3_CELLS)):
            compile_predicate(pred, params)

    def test_huge_circle_intersects_raises(self) -> None:
        pred = TrajectoryIntersects(
            trajectory_intersects=SpatioTemporalAltitudeValue(geometry=_HUGE_CIRCLE)
        )
        params: list[object] = []
        with pytest.raises(GeometryTooLargeError, match="H3 cells"):
            compile_predicate(pred, params)

    def test_huge_polygon_within_raises(self) -> None:
        pred = TrajectoryWithin(trajectory_within=SpatioTemporalAltitudeValue(geometry=_HUGE_POLY))
        params: list[object] = []
        with pytest.raises(GeometryTooLargeError):
            compile_predicate(pred, params)

    def test_endpoint_within_large_geometry_exempt(self) -> None:
        # EndpointWithin does not use the H3 GIN index — no size limit applies.
        pred = EndpointWithin(
            endpoint_within=EndpointWithinValue(mode="start", geometry=_HUGE_POLY)
        )
        params: list[object] = []
        compile_predicate(pred, params)  # must not raise

    def test_and_predicate_raises_on_oversized_child(self) -> None:
        small = TrajectoryIntersects(
            trajectory_intersects=SpatioTemporalAltitudeValue(geometry=_SMALL_POLY)
        )
        huge = TrajectoryIntersects(
            trajectory_intersects=SpatioTemporalAltitudeValue(geometry=_HUGE_POLY)
        )
        pred = AndPredicate(**{"and": [small, huge]})
        params: list[object] = []
        with pytest.raises(GeometryTooLargeError):
            compile_predicate(pred, params)

    def test_or_predicate_raises_on_oversized_child(self) -> None:
        huge = TrajectoryWithin(
            trajectory_within=SpatioTemporalAltitudeValue(geometry=_HUGE_CIRCLE)
        )
        pred = OrPredicate(**{"or": [huge]})
        params: list[object] = []
        with pytest.raises(GeometryTooLargeError):
            compile_predicate(pred, params)

    def test_not_predicate_raises_on_oversized_inner(self) -> None:
        huge = TrajectoryIntersects(
            trajectory_intersects=SpatioTemporalAltitudeValue(geometry=_HUGE_POLY)
        )
        pred = NotPredicate(**{"not": huge})
        params: list[object] = []
        with pytest.raises(GeometryTooLargeError):
            compile_predicate(pred, params)

    def test_no_geometry_compiles(self) -> None:
        t1 = datetime.fromisoformat("2025-04-01T00:00:00+00:00")
        t2 = datetime.fromisoformat("2025-04-02T00:00:00+00:00")
        pred = TrajectoryIntersects(
            trajectory_intersects=SpatioTemporalAltitudeValue(time_from=t1, time_to=t2)
        )
        params: list[object] = []
        compile_predicate(pred, params)  # must not raise
