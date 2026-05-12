"""Unit tests for compile_predicate and its helpers.

These tests verify SQL fragment structure and parameter binding only — no
database is required. For end-to-end filtering behaviour see test_api/test_query.py.
"""

from __future__ import annotations

from datetime import datetime

import pytest

from adsb_server.query.compiler import CompiledPredicate, compile_predicate
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

_T1 = datetime.fromisoformat("2025-04-01T00:00:00+00:00")
_T2 = datetime.fromisoformat("2025-04-02T00:00:00+00:00")


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
# trajectory_intersects — MobilityDB eIntersects / atStbox
# ---------------------------------------------------------------------------


class TestTrajectoryIntersects:
    def test_geometry_only_uses_eintersects(self) -> None:
        params: list = []
        pred = TrajectoryIntersects(
            trajectory_intersects=SpatioTemporalAltitudeValue(geometry=_POLYGON)
        )
        sql = compile_predicate(pred, params)
        assert "eIntersects(path," in sql
        assert "atStbox" not in sql
        assert "stbox" not in sql

    def test_geometry_altitude_min_uses_atStbox_cte(self) -> None:
        params: list = []
        pred = TrajectoryIntersects(
            trajectory_intersects=SpatioTemporalAltitudeValue(
                geometry=_POLYGON, altitude_min_ft=10000
            )
        )
        compiled = compile_predicate(pred, params)
        # CTE carries geometry + 3D STBOX; WHERE references the CTE alias.
        assert isinstance(compiled, CompiledPredicate)
        assert compiled.ctes
        cte_body = compiled.ctes[0][1]
        assert "ST_3DMakeBox(" in cte_body
        assert "stbox(" in cte_body
        assert "path && " in compiled
        assert "atStbox(path," in compiled
        assert "eIntersects(atStbox(" in compiled
        assert "ST_ZMax(trajectory(path)::box3d)" not in compiled
        assert 10000.0 in params

    def test_geometry_altitude_max_uses_atStbox_cte(self) -> None:
        params: list = []
        pred = TrajectoryIntersects(
            trajectory_intersects=SpatioTemporalAltitudeValue(
                geometry=_POLYGON, altitude_max_ft=40000
            )
        )
        compiled = compile_predicate(pred, params)
        assert compiled.ctes
        cte_body = compiled.ctes[0][1]
        assert "ST_3DMakeBox(" in cte_body
        assert "eIntersects(atStbox(" in compiled
        assert "ST_ZMin(trajectory(path)::box3d)" not in compiled
        assert 40000.0 in params

    def test_geometry_both_altitude_bounds_uses_atStbox_cte(self) -> None:
        params: list = []
        pred = TrajectoryIntersects(
            trajectory_intersects=SpatioTemporalAltitudeValue(
                geometry=_POLYGON, altitude_min_ft=10000, altitude_max_ft=40000
            )
        )
        compiled = compile_predicate(pred, params)
        assert compiled.ctes
        cte_body = compiled.ctes[0][1]
        assert "ST_3DMakeBox(" in cte_body
        assert "eIntersects(atStbox(" in compiled
        assert "ST_ZMax(trajectory(path)::box3d)" not in compiled
        assert "ST_ZMin(trajectory(path)::box3d)" not in compiled
        assert 10000.0 in params
        assert 40000.0 in params

    def test_geometry_only_no_extra_conditions(self) -> None:
        params: list = []
        pred = TrajectoryIntersects(
            trajectory_intersects=SpatioTemporalAltitudeValue(geometry=_POLYGON)
        )
        compiled = compile_predicate(pred, params)
        assert "ST_ZMax" not in compiled
        assert "ST_ZMin" not in compiled
        assert "EXISTS" not in compiled
        assert "atStbox" not in compiled
        assert not compiled.ctes

    def test_altitude_min_no_geometry_uses_trajectory_zmax(self) -> None:
        params: list = []
        pred = TrajectoryIntersects(
            trajectory_intersects=SpatioTemporalAltitudeValue(altitude_min_ft=35000)
        )
        sql = compile_predicate(pred, params)
        assert "ST_ZMax(trajectory(path)::box3d)" in sql
        assert "eIntersects" not in sql
        assert "atStbox" not in sql
        assert len(params) == 1

    def test_altitude_max_no_geometry_uses_trajectory_zmin(self) -> None:
        params: list = []
        pred = TrajectoryIntersects(
            trajectory_intersects=SpatioTemporalAltitudeValue(altitude_max_ft=10000)
        )
        sql = compile_predicate(pred, params)
        assert "ST_ZMin(trajectory(path)::box3d)" in sql
        assert "eIntersects" not in sql
        assert len(params) == 1

    def test_altitude_and_time_no_geometry(self) -> None:
        params: list = []
        pred = TrajectoryIntersects(
            trajectory_intersects=SpatioTemporalAltitudeValue(
                altitude_min_ft=35000, time_from=_T1, time_to=_T2
            )
        )
        sql = compile_predicate(pred, params)
        assert "ST_ZMax(trajectory(path)::box3d)" in sql
        assert "end_ts >=" in sql
        assert "start_ts <" in sql
        assert "eIntersects" not in sql
        assert "atStbox" not in sql
        assert len(params) == 3

    def test_all_fields_uses_3d_t_stbox_cte(self) -> None:
        # geometry + altitude + time → 3D+T STBOX in CTE; altitude enforced via atStbox
        params: list = []
        pred = TrajectoryIntersects(
            trajectory_intersects=SpatioTemporalAltitudeValue(
                geometry=_POLYGON, altitude_min_ft=10000, altitude_max_ft=40000,
                time_from=_T1, time_to=_T2,
            )
        )
        compiled = compile_predicate(pred, params)
        assert compiled.ctes
        cte_body = compiled.ctes[0][1]
        assert "ST_3DMakeBox(" in cte_body
        assert "stbox(" in cte_body
        assert "span(" in cte_body
        assert "eIntersects(atStbox(" in compiled
        assert "end_ts >=" in compiled
        assert "start_ts <" in compiled
        # Altitude is now in the STBOX, not separate btree expressions.
        assert "ST_ZMax(trajectory(path)::box3d)" not in compiled
        assert "ST_ZMin(trajectory(path)::box3d)" not in compiled
        # Params: alt_min, alt_max, time_from, time_to, geom — each bound once.
        assert len(params) == 5

    def test_geometry_time_only_uses_stbox_cte(self) -> None:
        params: list = []
        pred = TrajectoryIntersects(
            trajectory_intersects=SpatioTemporalAltitudeValue(
                geometry=_POLYGON, time_from=_T1, time_to=_T2
            )
        )
        compiled = compile_predicate(pred, params)
        assert compiled.ctes
        cte_body = compiled.ctes[0][1]
        assert "stbox(" in cte_body
        assert "span(" in cte_body
        assert "eIntersects(atStbox(" in compiled
        assert "end_ts >=" in compiled
        assert "start_ts <" in compiled


# ---------------------------------------------------------------------------
# trajectory_within — ST_Within(trajectory(path), geom)
# ---------------------------------------------------------------------------


class TestTrajectoryWithin:
    def test_geometry_only_uses_st_within_trajectory(self) -> None:
        params: list = []
        pred = TrajectoryWithin(
            trajectory_within=SpatioTemporalAltitudeValue(geometry=_POLYGON)
        )
        sql = compile_predicate(pred, params)
        assert "ST_Within(trajectory(path)," in sql
        assert "atStbox" not in sql

    def test_altitude_bounds_uses_atStbox_cte(self) -> None:
        params: list = []
        pred = TrajectoryWithin(
            trajectory_within=SpatioTemporalAltitudeValue(
                geometry=_POLYGON, altitude_min_ft=5000
            )
        )
        compiled = compile_predicate(pred, params)
        assert compiled.ctes
        cte_body = compiled.ctes[0][1]
        assert "ST_3DMakeBox(" in cte_body
        assert "path && " in compiled
        assert "atStbox(path," in compiled
        assert "IS NOT NULL" in compiled
        assert "ST_Within(trajectory(path)," in compiled
        assert "ST_ZMax(trajectory(path)::box3d)" not in compiled

    def test_time_bounds_uses_stbox_cte(self) -> None:
        params: list = []
        pred = TrajectoryWithin(
            trajectory_within=SpatioTemporalAltitudeValue(
                geometry=_POLYGON, time_from=_T1, time_to=_T2
            )
        )
        compiled = compile_predicate(pred, params)
        assert compiled.ctes
        cte_body = compiled.ctes[0][1]
        assert "stbox(" in cte_body
        assert "span(" in cte_body
        assert "ST_Within(trajectory(path)," in compiled
        assert "atStbox(path," in compiled
        assert "IS NOT NULL" in compiled
        assert "end_ts >=" in compiled
        assert "start_ts <" in compiled

    def test_time_only(self) -> None:
        params: list = []
        pred = TrajectoryWithin(
            trajectory_within=SpatioTemporalAltitudeValue(time_from=_T1)
        )
        sql = compile_predicate(pred, params)
        assert "ST_Within" not in sql
        assert "end_ts >=" in sql


# ---------------------------------------------------------------------------
# trajectory_disjoint — NOT eIntersects
# ---------------------------------------------------------------------------


class TestTrajectoryDisjoint:
    def test_geometry_only_uses_not_eintersects(self) -> None:
        params: list = []
        pred = TrajectoryDisjoint(
            trajectory_disjoint=SpatioTemporalAltitudeValue(geometry=_POLYGON)
        )
        sql = compile_predicate(pred, params)
        assert "NOT eIntersects(path," in sql

    def test_altitude_bounds_use_trajectory_btree(self) -> None:
        params: list = []
        pred = TrajectoryDisjoint(
            trajectory_disjoint=SpatioTemporalAltitudeValue(
                geometry=_POLYGON, altitude_max_ft=18000
            )
        )
        sql = compile_predicate(pred, params)
        assert "NOT eIntersects(path," in sql
        assert "ST_ZMin(trajectory(path)::box3d)" in sql
        assert "stbox" not in sql  # no STBOX prism for disjoint

    def test_time_bounds_propagated(self) -> None:
        params: list = []
        pred = TrajectoryDisjoint(
            trajectory_disjoint=SpatioTemporalAltitudeValue(
                geometry=_POLYGON, time_from=_T1, time_to=_T2
            )
        )
        sql = compile_predicate(pred, params)
        assert "NOT eIntersects(path," in sql
        assert "end_ts >=" in sql
        assert "start_ts <" in sql


# ---------------------------------------------------------------------------
# _compile_point_within — startValue/endValue expressions
# ---------------------------------------------------------------------------


class TestPointWithin:
    def test_starts_within_polygon_uses_startvalue(self) -> None:
        params: list = []
        pred = StartsWithin(starts_within=SpatioTemporalValue(geometry=_POLYGON))
        sql = compile_predicate(pred, params)
        assert "ST_Within(startValue(path)::geometry," in sql
        assert "ST_GeomFromGeoJSON" in sql

    def test_ends_within_polygon_uses_endvalue(self) -> None:
        params: list = []
        pred = EndsWithin(ends_within=SpatioTemporalValue(geometry=_POLYGON))
        sql = compile_predicate(pred, params)
        assert "ST_Within(endValue(path)::geometry," in sql

    def test_starts_within_circle_uses_st_dwithin_geography(self) -> None:
        params: list = []
        pred = StartsWithin(starts_within=SpatioTemporalValue(geometry=_CIRCLE))
        sql = compile_predicate(pred, params)
        assert "ST_DWithin(startValue(path)::geometry::geography," in sql
        assert len(params) == 3  # lon, lat, radius

    def test_ends_within_circle_uses_st_dwithin_geography(self) -> None:
        params: list = []
        pred = EndsWithin(ends_within=SpatioTemporalValue(geometry=_CIRCLE))
        sql = compile_predicate(pred, params)
        assert "ST_DWithin(endValue(path)::geometry::geography," in sql


# ---------------------------------------------------------------------------
# Time fields on starts_within / ends_within / trajectory_intersects
# ---------------------------------------------------------------------------


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
        params: list = []
        pred = TrajectoryIntersects(
            trajectory_intersects=SpatioTemporalAltitudeValue(time_from=_T1, time_to=_T2)
        )
        sql = compile_predicate(pred, params)
        assert "end_ts >=" in sql
        assert "start_ts <" in sql
        assert "eIntersects" not in sql
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
        assert "ST_Within(startValue(path)::geometry," in sql
        assert "start_ts >=" in sql

    def test_starts_within_all_fields(self) -> None:
        params: list = []
        pred = StartsWithin(
            starts_within=SpatioTemporalValue(geometry=_POLYGON, time_from=_T1, time_to=_T2)
        )
        sql = compile_predicate(pred, params)
        assert "ST_Within(startValue(path)::geometry," in sql
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
