"""Unit tests for compile_predicate and its helpers.

These tests verify SQL fragment structure and parameter binding only — no
database is required. For end-to-end filtering behaviour see test_api/test_query.py.
"""

from __future__ import annotations

import pytest

from datetime import datetime

from adsb_server.query.compiler import compile_predicate
from adsb_server.query.models import (
    AndPredicate,
    Duration,
    DurationValue,
    EmitterCategory,
    EndsWithin,
    IcaoType,
    NotPredicate,
    OrPredicate,
    SpatioTemporalAltitudeValue,
    SpatioTemporalValue,
    StartsWithin,
    TrajectoryDisjoint,
    TrajectoryIntersects,
    TrajectoryWithin,
)

_POLYGON = {
    "type": "Polygon",
    "coordinates": [[[-2, 50], [2, 50], [2, 52], [-2, 52], [-2, 50]]],
}
_CIRCLE = {"type": "Circle", "coordinates": [-1.0, 52.0], "radius": 50000}


# ---------------------------------------------------------------------------
# Value model validators
# ---------------------------------------------------------------------------


class TestValueValidators:
    def test_spatio_temporal_value_empty_raises(self) -> None:
        with pytest.raises(ValueError, match="at least one"):
            SpatioTemporalValue()

    def test_spatio_temporal_altitude_value_empty_raises(self) -> None:
        with pytest.raises(ValueError, match="at least one"):
            SpatioTemporalAltitudeValue()


# ---------------------------------------------------------------------------
# _compile_geometry_sql — Circle vs GeoJSON
# ---------------------------------------------------------------------------


class TestCircleGeometry:
    def test_circle_path_predicate_uses_st_buffer(self) -> None:
        params: list = []
        pred = TrajectoryIntersects(
            trajectory_intersects=SpatioTemporalAltitudeValue(geometry=_CIRCLE)
        )
        sql = compile_predicate(pred, params)
        assert "ST_Buffer" in sql
        assert "ST_MakePoint" in sql
        assert len(params) == 3  # lon, lat, radius

    def test_polygon_path_predicate_uses_geomfromgeojson(self) -> None:
        params: list = []
        pred = TrajectoryIntersects(
            trajectory_intersects=SpatioTemporalAltitudeValue(geometry=_POLYGON)
        )
        sql = compile_predicate(pred, params)
        assert "ST_GeomFromGeoJSON" in sql
        assert "ST_Buffer" not in sql
        assert len(params) == 1  # serialised GeoJSON string


# ---------------------------------------------------------------------------
# _compile_spatial_path — altitude bounds
# ---------------------------------------------------------------------------


class TestAltitudeBounds:
    def test_altitude_min_with_geometry_uses_prism_and_vertex_check(self) -> None:
        # 3D prism &&& pre-filter (ndgist) + exact per-vertex EXISTS refinement.
        params: list = []
        pred = TrajectoryIntersects(
            trajectory_intersects=SpatioTemporalAltitudeValue(
                geometry=_POLYGON, altitude_min_ft=10000
            )
        )
        sql = compile_predicate(pred, params)
        assert "path_geom &&&" in sql                     # 3D prism uses ndgist index
        assert "ST_Force3D" in sql
        assert "ST_ZMax(path_geom::box3d)" not in sql     # btree check replaced by prism
        assert "EXISTS" in sql                            # exact vertex check
        assert "ST_Z(dp.geom) >=" in sql
        assert 10000.0 in params

    def test_altitude_max_with_geometry_uses_prism_and_vertex_check(self) -> None:
        params: list = []
        pred = TrajectoryIntersects(
            trajectory_intersects=SpatioTemporalAltitudeValue(
                geometry=_POLYGON, altitude_max_ft=40000
            )
        )
        sql = compile_predicate(pred, params)
        assert "path_geom &&&" in sql
        assert "ST_Force3D" in sql
        assert "ST_ZMin(path_geom::box3d)" not in sql
        assert "EXISTS" in sql
        assert "ST_Z(dp.geom) <=" in sql
        assert 40000.0 in params

    def test_both_altitude_bounds_with_geometry(self) -> None:
        params: list = []
        pred = TrajectoryIntersects(
            trajectory_intersects=SpatioTemporalAltitudeValue(
                geometry=_POLYGON, altitude_min_ft=10000, altitude_max_ft=40000
            )
        )
        sql = compile_predicate(pred, params)
        assert "path_geom &&&" in sql
        assert "ST_Force3D" in sql
        assert "ST_ZMax(path_geom::box3d)" not in sql
        assert "ST_ZMin(path_geom::box3d)" not in sql
        assert "EXISTS" in sql
        assert "ST_Z(dp.geom) >=" in sql
        assert "ST_Z(dp.geom) <=" in sql
        assert len(params) == 3  # alt_min, alt_max, geom

    def test_no_altitude_bounds_no_extra_conditions(self) -> None:
        params: list = []
        pred = TrajectoryIntersects(
            trajectory_intersects=SpatioTemporalAltitudeValue(geometry=_POLYGON)
        )
        sql = compile_predicate(pred, params)
        assert "ST_ZMax" not in sql
        assert "ST_ZMin" not in sql
        assert "EXISTS" not in sql

    def test_altitude_min_only_no_geometry_uses_bbox(self) -> None:
        # Without geometry: bounding-box check only (semantics: flight reached this altitude).
        params: list = []
        pred = TrajectoryIntersects(
            trajectory_intersects=SpatioTemporalAltitudeValue(altitude_min_ft=35000)
        )
        sql = compile_predicate(pred, params)
        assert "ST_ZMax(path_geom::box3d)" in sql
        assert "ST_Intersects" not in sql
        assert "EXISTS" not in sql
        assert len(params) == 1

    def test_altitude_max_only_no_geometry_uses_bbox(self) -> None:
        params: list = []
        pred = TrajectoryIntersects(
            trajectory_intersects=SpatioTemporalAltitudeValue(altitude_max_ft=10000)
        )
        sql = compile_predicate(pred, params)
        assert "ST_ZMin(path_geom::box3d)" in sql
        assert "ST_Intersects" not in sql
        assert "EXISTS" not in sql
        assert len(params) == 1

    def test_altitude_and_time_no_geometry_uses_whole_flight_checks(self) -> None:
        params: list = []
        pred = TrajectoryIntersects(
            trajectory_intersects=SpatioTemporalAltitudeValue(
                altitude_min_ft=35000, time_from=_T1, time_to=_T2
            )
        )
        sql = compile_predicate(pred, params)
        assert "ST_ZMax" in sql
        assert "end_ts >=" in sql
        assert "start_ts <" in sql
        assert "ST_Intersects" not in sql
        assert "EXISTS" not in sql
        assert len(params) == 3

    def test_all_fields_uses_prism_and_vertex_exists(self) -> None:
        # geometry + altitude + time: 3D prism &&& for index, EXISTS for exact vertex check.
        params: list = []
        pred = TrajectoryIntersects(
            trajectory_intersects=SpatioTemporalAltitudeValue(
                geometry=_POLYGON, altitude_min_ft=10000, altitude_max_ft=40000,
                time_from=_T1, time_to=_T2,
            )
        )
        sql = compile_predicate(pred, params)
        assert "path_geom &&&" in sql                     # 3D prism ndgist pre-filter
        assert "ST_Force3D" in sql
        assert "ST_Intersects(path_geom," not in sql      # redundant when EXISTS present
        assert "ST_ZMax(path_geom::box3d)" not in sql     # replaced by prism
        assert "ST_ZMin(path_geom::box3d)" not in sql
        assert "end_ts >=" in sql                         # time pre-filter
        assert "start_ts <" in sql
        assert "EXISTS" in sql                            # exact vertex check
        assert "ST_DumpPoints" in sql
        assert "ST_Z(dp.geom) >=" in sql
        assert "ST_Z(dp.geom) <=" in sql
        assert "ST_M(dp.geom) >=" in sql
        assert "ST_M(dp.geom) <" in sql
        assert len(params) == 5  # alt_min, alt_max, T1, T2, geom — each bound once


# ---------------------------------------------------------------------------
# Spatial path predicate variants
# ---------------------------------------------------------------------------


class TestTrajectoryWithin:
    def test_produces_st_within(self) -> None:
        params: list = []
        pred = TrajectoryWithin(
            trajectory_within=SpatioTemporalAltitudeValue(geometry=_POLYGON)
        )
        sql = compile_predicate(pred, params)
        assert sql.startswith("ST_Within(path_geom,")

    def test_altitude_bounds_with_geometry_uses_vertex_check(self) -> None:
        params: list = []
        pred = TrajectoryWithin(
            trajectory_within=SpatioTemporalAltitudeValue(
                geometry=_POLYGON, altitude_min_ft=5000
            )
        )
        sql = compile_predicate(pred, params)
        assert "path_geom &&&" in sql
        assert "ST_Force3D" in sql
        assert "EXISTS" in sql
        assert "ST_Z(dp.geom) >=" in sql
        assert "ST_ZMax" not in sql

    def test_time_bounds_with_geometry_uses_vertex_check(self) -> None:
        params: list = []
        pred = TrajectoryWithin(
            trajectory_within=SpatioTemporalAltitudeValue(
                geometry=_POLYGON, time_from=_T1, time_to=_T2
            )
        )
        sql = compile_predicate(pred, params)
        assert "EXISTS" in sql
        assert "ST_M(dp.geom) >=" in sql
        assert "ST_M(dp.geom) <" in sql
        assert "end_ts >=" in sql
        assert "start_ts <" in sql

    def test_time_only(self) -> None:
        params: list = []
        pred = TrajectoryWithin(
            trajectory_within=SpatioTemporalAltitudeValue(time_from=_T1)
        )
        sql = compile_predicate(pred, params)
        assert "ST_Within" not in sql
        assert "end_ts >=" in sql


class TestTrajectoryDisjoint:
    def test_produces_st_disjoint(self) -> None:
        params: list = []
        pred = TrajectoryDisjoint(
            trajectory_disjoint=SpatioTemporalAltitudeValue(geometry=_POLYGON)
        )
        sql = compile_predicate(pred, params)
        assert sql.startswith("ST_Disjoint(path_geom,")

    def test_altitude_bounds_propagated(self) -> None:
        params: list = []
        pred = TrajectoryDisjoint(
            trajectory_disjoint=SpatioTemporalAltitudeValue(
                geometry=_POLYGON, altitude_max_ft=18000
            )
        )
        sql = compile_predicate(pred, params)
        assert "ST_ZMin" in sql

    def test_time_bounds_propagated(self) -> None:
        params: list = []
        pred = TrajectoryDisjoint(
            trajectory_disjoint=SpatioTemporalAltitudeValue(
                geometry=_POLYGON, time_from=_T1, time_to=_T2
            )
        )
        sql = compile_predicate(pred, params)
        assert "end_ts >=" in sql
        assert "start_ts <" in sql


# ---------------------------------------------------------------------------
# _compile_point_within — Circle vs GeoJSON
# ---------------------------------------------------------------------------


class TestPointWithin:
    def test_starts_within_polygon_uses_st_within(self) -> None:
        params: list = []
        pred = StartsWithin(starts_within=SpatioTemporalValue(geometry=_POLYGON))
        sql = compile_predicate(pred, params)
        assert "ST_Within(start_point," in sql
        assert "ST_GeomFromGeoJSON" in sql

    def test_ends_within_polygon_uses_st_within(self) -> None:
        params: list = []
        pred = EndsWithin(ends_within=SpatioTemporalValue(geometry=_POLYGON))
        sql = compile_predicate(pred, params)
        assert "ST_Within(end_point," in sql

    def test_starts_within_circle_uses_st_dwithin(self) -> None:
        params: list = []
        pred = StartsWithin(starts_within=SpatioTemporalValue(geometry=_CIRCLE))
        sql = compile_predicate(pred, params)
        assert "ST_DWithin(start_point::geography," in sql
        assert len(params) == 3  # lon, lat, radius


# ---------------------------------------------------------------------------
# Time fields on starts_within / ends_within / trajectory_intersects
# ---------------------------------------------------------------------------

_T1 = datetime.fromisoformat("2025-04-01T00:00:00+00:00")
_T2 = datetime.fromisoformat("2025-04-02T00:00:00+00:00")


class TestTimeFields:
    def test_starts_within_time_from_filters_start_ts(self) -> None:
        params: list = []
        pred = StartsWithin(starts_within=SpatioTemporalValue(time_from=_T1))
        sql = compile_predicate(pred, params)
        assert "start_ts >=" in sql
        assert "start_ts <" not in sql
        assert len(params) == 1

    def test_starts_within_time_to_filters_start_ts(self) -> None:
        params: list = []
        pred = StartsWithin(starts_within=SpatioTemporalValue(time_to=_T2))
        sql = compile_predicate(pred, params)
        assert "start_ts <" in sql
        assert "start_ts >=" not in sql
        assert len(params) == 1

    def test_starts_within_time_window(self) -> None:
        params: list = []
        pred = StartsWithin(starts_within=SpatioTemporalValue(time_from=_T1, time_to=_T2))
        sql = compile_predicate(pred, params)
        assert "start_ts >=" in sql
        assert "start_ts <" in sql
        assert len(params) == 2

    def test_ends_within_time_filters_end_ts(self) -> None:
        params: list = []
        pred = EndsWithin(ends_within=SpatioTemporalValue(time_to=_T1))
        sql = compile_predicate(pred, params)
        assert "end_ts <" in sql
        assert "start_ts" not in sql
        assert len(params) == 1

    def test_intersects_time_no_geometry_uses_activity_semantics(self) -> None:
        # No geometry: time_from → end_ts >= time_from (flight was still active)
        #              time_to   → start_ts < time_to  (flight had started)
        # This is correct for "flights active during this window" without a spatial constraint.
        params: list = []
        pred = TrajectoryIntersects(
            trajectory_intersects=SpatioTemporalAltitudeValue(time_from=_T1, time_to=_T2)
        )
        sql = compile_predicate(pred, params)
        assert "end_ts >=" in sql
        assert "start_ts <" in sql
        assert "EXISTS" not in sql
        assert len(params) == 2

    def test_ends_within_time_from_filters_end_ts(self) -> None:
        params: list = []
        pred = EndsWithin(ends_within=SpatioTemporalValue(time_from=_T1))
        sql = compile_predicate(pred, params)
        assert "end_ts >=" in sql
        assert "end_ts <" not in sql
        assert len(params) == 1

    def test_intersects_time_to_only(self) -> None:
        params: list = []
        pred = TrajectoryIntersects(
            trajectory_intersects=SpatioTemporalAltitudeValue(time_to=_T2)
        )
        sql = compile_predicate(pred, params)
        assert "start_ts <" in sql
        assert "end_ts >=" not in sql
        assert len(params) == 1

    def test_starts_within_geometry_and_time(self) -> None:
        params: list = []
        pred = StartsWithin(starts_within=SpatioTemporalValue(geometry=_POLYGON, time_from=_T1))
        sql = compile_predicate(pred, params)
        assert "ST_Within(start_point," in sql
        assert "start_ts >=" in sql

    def test_starts_within_geometry_and_time_to(self) -> None:
        params: list = []
        pred = StartsWithin(starts_within=SpatioTemporalValue(geometry=_POLYGON, time_to=_T2))
        sql = compile_predicate(pred, params)
        assert "ST_Within(start_point," in sql
        assert "start_ts <" in sql
        assert "start_ts >=" not in sql

    def test_starts_within_all_fields(self) -> None:
        params: list = []
        pred = StartsWithin(
            starts_within=SpatioTemporalValue(geometry=_POLYGON, time_from=_T1, time_to=_T2)
        )
        sql = compile_predicate(pred, params)
        assert "ST_Within(start_point," in sql
        assert "start_ts >=" in sql
        assert "start_ts <" in sql
        assert len(params) == 3


# ---------------------------------------------------------------------------
# Attribute predicates
# ---------------------------------------------------------------------------


class TestAttributePredicates:
    def test_icao_type(self) -> None:
        params: list = []
        sql = compile_predicate(IcaoType(icao_type=["B738", "A320"]), params)
        assert "icao_type = ANY" in sql
        assert len(params) == 1

    def test_emitter_category(self) -> None:
        params: list = []
        sql = compile_predicate(EmitterCategory(emitter_category=["A3"]), params)
        assert "emitter_category = ANY" in sql
        assert len(params) == 1

    def test_duration_min_only(self) -> None:
        params: list = []
        sql = compile_predicate(Duration(duration=DurationValue(min_s=3600)), params)
        assert ">=" in sql
        assert "<=" not in sql

    def test_duration_max_only(self) -> None:
        params: list = []
        sql = compile_predicate(Duration(duration=DurationValue(max_s=7200)), params)
        assert "<=" in sql
        assert ">=" not in sql

    def test_duration_both_bounds(self) -> None:
        params: list = []
        sql = compile_predicate(Duration(duration=DurationValue(min_s=1800, max_s=7200)), params)
        assert ">=" in sql
        assert "<=" in sql
        assert len(params) == 2

    def test_duration_no_bounds_returns_true(self) -> None:
        params: list = []
        sql = compile_predicate(Duration(duration=DurationValue()), params)
        assert sql == "TRUE"
        assert params == []


# ---------------------------------------------------------------------------
# Logical predicates
# ---------------------------------------------------------------------------


class TestLogicalPredicates:
    def test_empty_and_returns_true(self) -> None:
        params: list = []
        pred = AndPredicate.model_validate({"and": []})
        assert compile_predicate(pred, params) == "TRUE"

    def test_and_combines_with_and(self) -> None:
        params: list = []
        pred = AndPredicate.model_validate(
            {"and": [{"icao_type": ["B738"]}, {"icao_type": ["A320"]}]}
        )
        sql = compile_predicate(pred, params)
        assert " AND " in sql
        assert sql.startswith("(")

    def test_empty_or_returns_false(self) -> None:
        params: list = []
        pred = OrPredicate.model_validate({"or": []})
        assert compile_predicate(pred, params) == "FALSE"

    def test_or_combines_with_or(self) -> None:
        params: list = []
        pred = OrPredicate.model_validate(
            {"or": [{"icao_type": ["B738"]}, {"icao_type": ["A320"]}]}
        )
        sql = compile_predicate(pred, params)
        assert " OR " in sql
        assert sql.startswith("(")

    def test_not_wraps_with_not(self) -> None:
        params: list = []
        pred = NotPredicate.model_validate({"not": {"callsign_matches": "^BAW"}})
        sql = compile_predicate(pred, params)
        assert sql.startswith("NOT (")

    def test_nested_and_or(self) -> None:
        params: list = []
        pred = AndPredicate.model_validate(
            {
                "and": [
                    {"or": [{"icao_type": ["B738"]}, {"icao_type": ["A320"]}]},
                    {"callsign_matches": "^[A-Z]"},
                ]
            }
        )
        sql = compile_predicate(pred, params)
        assert " AND " in sql
        assert " OR " in sql
