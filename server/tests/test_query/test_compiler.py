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

    def test_geometry_altitude_min_fl_uses_3d_stbox_cte(self) -> None:
        params: list = []
        pred = TrajectoryIntersects(
            trajectory_intersects=SpatioTemporalAltitudeValue(
                geometry=_POLYGON, altitude_min=100, altitude_min_ref="fl"  # FL100
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
        assert 10000.0 in params  # FL100 × 100

    def test_geometry_altitude_max_fl_uses_3d_stbox_cte(self) -> None:
        params: list = []
        pred = TrajectoryIntersects(
            trajectory_intersects=SpatioTemporalAltitudeValue(
                geometry=_POLYGON, altitude_max=400, altitude_max_ref="fl"  # FL400
            )
        )
        compiled = compile_predicate(pred, params)
        assert compiled.ctes
        cte_body = compiled.ctes[0][1]
        assert "ST_3DMakeBox(" in cte_body
        assert "eIntersects(atStbox(" in compiled
        assert "ST_ZMin(trajectory(path)::box3d)" not in compiled
        assert 40000.0 in params  # FL400 × 100

    def test_geometry_both_altitude_bounds_fl_uses_3d_stbox_cte(self) -> None:
        params: list = []
        pred = TrajectoryIntersects(
            trajectory_intersects=SpatioTemporalAltitudeValue(
                geometry=_POLYGON,
                altitude_min=100, altitude_min_ref="fl",
                altitude_max=400, altitude_max_ref="fl",
            )
        )
        compiled = compile_predicate(pred, params)
        assert compiled.ctes
        cte_body = compiled.ctes[0][1]
        assert "ST_3DMakeBox(" in cte_body
        assert "eIntersects(atStbox(" in compiled
        assert "ST_ZMax(trajectory(path)::box3d)" not in compiled
        assert "ST_ZMin(trajectory(path)::box3d)" not in compiled
        assert 10000.0 in params  # FL100 × 100
        assert 40000.0 in params  # FL400 × 100

    def test_geometry_altitude_min_ft_uses_atvalues(self) -> None:
        # altitude_min_ref="ft" (default) → corrected altitude via atvalues, no ST_3DMakeBox.
        params: list = []
        pred = TrajectoryIntersects(
            trajectory_intersects=SpatioTemporalAltitudeValue(
                geometry=_POLYGON, altitude_min=10000  # ft (default ref)
            )
        )
        compiled = compile_predicate(pred, params)
        assert compiled.ctes
        cte_body = compiled.ctes[0][1]
        assert "ST_3DMakeBox(" not in cte_body
        assert "atvalues(" in compiled
        assert "alt_correction_ft" in compiled
        assert "eIntersects(" in compiled
        assert 10000.0 in params  # ft value passed directly

    def test_geometry_mixed_refs_uses_both_stbox_and_atvalues(self) -> None:
        # floor in ft, ceiling in fl — STBOX gets FL ceiling Z, atvalues handles ft floor.
        params: list = []
        pred = TrajectoryIntersects(
            trajectory_intersects=SpatioTemporalAltitudeValue(
                geometry=_POLYGON,
                altitude_min=1500, altitude_min_ref="ft",
                altitude_max=100, altitude_max_ref="fl",  # FL100 ceiling
            )
        )
        compiled = compile_predicate(pred, params)
        assert compiled.ctes
        cte_body = compiled.ctes[0][1]
        assert "ST_3DMakeBox(" in cte_body   # FL ceiling in STBOX Z
        assert "atvalues(" in compiled        # ft floor via corrected alt
        assert "alt_correction_ft" in compiled
        assert 10000.0 in params  # FL100 × 100
        assert 1500.0 in params   # ft floor passed directly

    def test_geometry_altitude_max_ft_uses_atvalues(self) -> None:
        # altitude_max in ft (default ref) → no STBOX Z, atvalues with corrected alt.
        params: list = []
        pred = TrajectoryIntersects(
            trajectory_intersects=SpatioTemporalAltitudeValue(
                geometry=_POLYGON, altitude_max=10000  # ft ceiling
            )
        )
        compiled = compile_predicate(pred, params)
        assert compiled.ctes
        cte_body = compiled.ctes[0][1]
        assert "ST_3DMakeBox(" not in cte_body
        assert "atvalues(" in compiled
        assert "alt_correction_ft" in compiled
        assert "eIntersects(" in compiled
        assert 10000.0 in params

    def test_geometry_both_ft_bounds_uses_atvalues(self) -> None:
        # Both altitude bounds in ft → single atvalues span covering both; no STBOX Z.
        params: list = []
        pred = TrajectoryIntersects(
            trajectory_intersects=SpatioTemporalAltitudeValue(
                geometry=_POLYGON,
                altitude_min=5000, altitude_max=15000,  # both ft (default)
            )
        )
        compiled = compile_predicate(pred, params)
        assert compiled.ctes
        cte_body = compiled.ctes[0][1]
        assert "ST_3DMakeBox(" not in cte_body
        assert "atvalues(" in compiled
        assert "alt_correction_ft" in compiled
        assert "eIntersects(" in compiled
        assert 5000.0 in params
        assert 15000.0 in params

    def test_geometry_mixed_fl_min_ft_max(self) -> None:
        # FL floor in STBOX Z (pressure altitude); ft ceiling via atvalues (corrected alt).
        params: list = []
        pred = TrajectoryIntersects(
            trajectory_intersects=SpatioTemporalAltitudeValue(
                geometry=_POLYGON,
                altitude_min=350, altitude_min_ref="fl",  # FL350 floor
                altitude_max=50000,                        # 50000 ft QNH ceiling
            )
        )
        compiled = compile_predicate(pred, params)
        assert compiled.ctes
        cte_body = compiled.ctes[0][1]
        assert "ST_3DMakeBox(" in cte_body   # FL floor in STBOX Z
        assert "atvalues(" in compiled        # ft ceiling via corrected alt
        assert "alt_correction_ft" in compiled
        assert 35000.0 in params  # FL350 × 100
        assert 50000.0 in params

    def test_geometry_ft_altitude_and_time(self) -> None:
        # ft altitude + time + geometry: STBOX carries time span only (no Z); atvalues for ft.
        params: list = []
        pred = TrajectoryIntersects(
            trajectory_intersects=SpatioTemporalAltitudeValue(
                geometry=_POLYGON,
                altitude_min=5000,  # ft (default)
                time_from=_T1, time_to=_T2,
            )
        )
        compiled = compile_predicate(pred, params)
        assert compiled.ctes
        cte_body = compiled.ctes[0][1]
        assert "span(" in cte_body           # time span in STBOX
        assert "ST_3DMakeBox(" not in cte_body  # no FL bounds → no Z in STBOX
        assert "atvalues(" in compiled
        assert "alt_correction_ft" in compiled
        assert "eIntersects(" in compiled
        assert "end_ts >=" in compiled
        assert "start_ts <" in compiled
        assert 5000.0 in params

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

    def test_altitude_min_fl_no_geometry_uses_stored_column(self) -> None:
        params: list = []
        pred = TrajectoryIntersects(
            trajectory_intersects=SpatioTemporalAltitudeValue(
                altitude_min=350, altitude_min_ref="fl"  # FL350 = 35000 ft
            )
        )
        sql = compile_predicate(pred, params)
        assert "alt_max_pressure_ft >=" in sql
        assert "ST_ZMax" not in sql
        assert "eIntersects" not in sql
        assert "atStbox" not in sql
        assert 35000.0 in params
        assert len(params) == 1

    def test_altitude_max_fl_no_geometry_uses_stored_column(self) -> None:
        params: list = []
        pred = TrajectoryIntersects(
            trajectory_intersects=SpatioTemporalAltitudeValue(
                altitude_max=100, altitude_max_ref="fl"  # FL100 = 10000 ft
            )
        )
        sql = compile_predicate(pred, params)
        assert "alt_min_pressure_ft <=" in sql
        assert "ST_ZMin" not in sql
        assert "eIntersects" not in sql
        assert 10000.0 in params
        assert len(params) == 1

    def test_altitude_min_ft_no_geometry_uses_stored_column(self) -> None:
        params: list = []
        pred = TrajectoryIntersects(
            trajectory_intersects=SpatioTemporalAltitudeValue(altitude_min=35000)  # ft default
        )
        sql = compile_predicate(pred, params)
        assert "alt_max_qnh_ft >=" in sql
        assert "atvalues(" not in sql
        assert "ST_ZMax(trajectory(path)::box3d)" not in sql
        assert "eIntersects" not in sql
        assert 35000.0 in params
        assert len(params) == 1

    def test_altitude_max_ft_no_geometry_uses_stored_column(self) -> None:
        params: list = []
        pred = TrajectoryIntersects(
            trajectory_intersects=SpatioTemporalAltitudeValue(altitude_max=10000)  # ft default
        )
        sql = compile_predicate(pred, params)
        assert "alt_min_qnh_ft <=" in sql
        assert "alt_max_qnh_ft" not in sql
        assert "atvalues(" not in sql
        assert "eIntersects" not in sql
        assert 10000.0 in params
        assert len(params) == 1

    def test_both_fl_bounds_no_geometry(self) -> None:
        params: list = []
        pred = TrajectoryIntersects(
            trajectory_intersects=SpatioTemporalAltitudeValue(
                altitude_min=100, altitude_min_ref="fl",
                altitude_max=400, altitude_max_ref="fl",
            )
        )
        sql = compile_predicate(pred, params)
        assert "alt_max_pressure_ft >=" in sql
        assert "alt_min_pressure_ft <=" in sql
        assert "qnh" not in sql
        assert "eIntersects" not in sql
        assert 10000.0 in params  # FL100 × 100
        assert 40000.0 in params  # FL400 × 100
        assert len(params) == 2

    def test_both_ft_bounds_no_geometry(self) -> None:
        params: list = []
        pred = TrajectoryIntersects(
            trajectory_intersects=SpatioTemporalAltitudeValue(
                altitude_min=5000, altitude_max=15000  # both ft (default)
            )
        )
        sql = compile_predicate(pred, params)
        assert "alt_max_qnh_ft >=" in sql
        assert "alt_min_qnh_ft <=" in sql
        assert "pressure" not in sql
        assert "eIntersects" not in sql
        assert 5000.0 in params
        assert 15000.0 in params
        assert len(params) == 2

    def test_mixed_ft_min_fl_max_no_geometry(self) -> None:
        # ft floor → alt_max_qnh_ft; FL ceiling → alt_min_pressure_ft
        params: list = []
        pred = TrajectoryIntersects(
            trajectory_intersects=SpatioTemporalAltitudeValue(
                altitude_min=1500,
                altitude_max=100, altitude_max_ref="fl",  # FL100 ceiling
            )
        )
        sql = compile_predicate(pred, params)
        assert "alt_max_qnh_ft >=" in sql
        assert "alt_min_pressure_ft <=" in sql
        assert "alt_min_qnh_ft" not in sql
        assert "alt_max_pressure_ft" not in sql
        assert 1500.0 in params
        assert 10000.0 in params  # FL100 × 100
        assert len(params) == 2

    def test_mixed_fl_min_ft_max_no_geometry(self) -> None:
        # FL floor → alt_max_pressure_ft; ft ceiling → alt_min_qnh_ft
        params: list = []
        pred = TrajectoryIntersects(
            trajectory_intersects=SpatioTemporalAltitudeValue(
                altitude_min=350, altitude_min_ref="fl",  # FL350 floor
                altitude_max=50000,                        # 50000 ft QNH ceiling
            )
        )
        sql = compile_predicate(pred, params)
        assert "alt_max_pressure_ft >=" in sql
        assert "alt_min_qnh_ft <=" in sql
        assert "alt_min_pressure_ft" not in sql
        assert "alt_max_qnh_ft" not in sql
        assert 35000.0 in params  # FL350 × 100
        assert 50000.0 in params
        assert len(params) == 2

    def test_altitude_and_time_no_geometry_fl(self) -> None:
        params: list = []
        pred = TrajectoryIntersects(
            trajectory_intersects=SpatioTemporalAltitudeValue(
                altitude_min=350, altitude_min_ref="fl", time_from=_T1, time_to=_T2
            )
        )
        sql = compile_predicate(pred, params)
        assert "alt_max_pressure_ft >=" in sql
        assert "ST_ZMax" not in sql
        assert "end_ts >=" in sql
        assert "start_ts <" in sql
        assert "eIntersects" not in sql
        assert "atStbox" not in sql
        assert 35000.0 in params
        assert len(params) == 3

    def test_all_fields_fl_uses_3d_t_stbox_cte(self) -> None:
        # geometry + FL altitude + time → 3D+T STBOX in CTE; altitude enforced via atStbox
        params: list = []
        pred = TrajectoryIntersects(
            trajectory_intersects=SpatioTemporalAltitudeValue(
                geometry=_POLYGON,
                altitude_min=100, altitude_min_ref="fl",
                altitude_max=400, altitude_max_ref="fl",
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
        assert "ST_ZMax(trajectory(path)::box3d)" not in compiled
        assert "ST_ZMin(trajectory(path)::box3d)" not in compiled
        # Params: alt_min (×100), alt_max (×100), time_from, time_to, geom
        assert 10000.0 in params
        assert 40000.0 in params
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

    def test_altitude_bounds_fl_uses_atstbox_cte(self) -> None:
        params: list = []
        pred = TrajectoryWithin(
            trajectory_within=SpatioTemporalAltitudeValue(
                geometry=_POLYGON, altitude_min=50, altitude_min_ref="fl"  # FL050
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
# squawk filter — squawk_seq EXISTS check
# ---------------------------------------------------------------------------


class TestSquawkFilter:
    def test_squawk_codes_only_no_geometry(self) -> None:
        # No geometry: check entire squawk_seq, no atgeometry correlation.
        params: list = []
        pred = TrajectoryIntersects(
            trajectory_intersects=SpatioTemporalAltitudeValue(squawk_codes=["7700"])
        )
        sql = compile_predicate(pred, params)
        assert "squawk_seq IS NOT NULL" in sql
        assert "EXISTS" in sql
        assert "getValue(_inst)" in sql
        assert "atgeometry" not in sql
        assert ["7700"] in params

    def test_squawk_codes_multiple(self) -> None:
        params: list = []
        pred = TrajectoryIntersects(
            trajectory_intersects=SpatioTemporalAltitudeValue(
                squawk_codes=["7700", "7600", "7500"]
            )
        )
        sql = compile_predicate(pred, params)
        assert "squawk_seq IS NOT NULL" in sql
        assert ["7700", "7600", "7500"] in params

    def test_squawk_codes_with_geometry_correlates_atgeometry(self) -> None:
        # With geometry: squawk is checked only at instants the path was inside the polygon.
        params: list = []
        pred = TrajectoryIntersects(
            trajectory_intersects=SpatioTemporalAltitudeValue(
                geometry=_POLYGON, squawk_codes=["7700"]
            )
        )
        sql = compile_predicate(pred, params)
        assert "eIntersects(path," in sql
        assert "squawk_seq IS NOT NULL" in sql
        assert "atgeometry(path," in sql
        assert "getTime(atgeometry" in sql
        assert "atTime(squawk_seq" in sql
        assert ["7700"] in params

    def test_squawk_codes_with_geometry_and_altitude_fl_uses_stbox(self) -> None:
        # With geometry + FL altitude: clip to STBOX then to geometry for squawk correlation.
        params: list = []
        pred = TrajectoryIntersects(
            trajectory_intersects=SpatioTemporalAltitudeValue(
                geometry=_POLYGON,
                altitude_min=100, altitude_min_ref="fl",
                squawk_codes=["7700"],
            )
        )
        compiled = compile_predicate(pred, params)
        assert compiled.ctes
        assert "atgeometry(atStbox(path," in compiled
        assert "getTime(atgeometry" in compiled
        assert "atTime(squawk_seq" in compiled
        assert ["7700"] in params

    def test_squawk_codes_none_not_emitted(self) -> None:
        params: list = []
        pred = TrajectoryIntersects(
            trajectory_intersects=SpatioTemporalAltitudeValue(geometry=_POLYGON)
        )
        sql = compile_predicate(pred, params)
        assert "squawk_seq" not in sql
        assert "EXISTS" not in sql

    def test_empty_squawk_codes_not_valid(self) -> None:
        # squawk_codes=[] is falsy — treated as no constraint, triggers the validator.
        with pytest.raises(ValueError, match="at least one constraint"):
            SpatioTemporalAltitudeValue(squawk_codes=[])

    def test_squawk_codes_with_trajectory_within(self) -> None:
        params: list = []
        pred = TrajectoryWithin(
            trajectory_within=SpatioTemporalAltitudeValue(squawk_codes=["1200"])
        )
        sql = compile_predicate(pred, params)
        assert "squawk_seq IS NOT NULL" in sql
        assert ["1200"] in params

    def test_squawk_codes_with_geometry_trajectory_within(self) -> None:
        # trajectory_within + geometry + squawk: squawk correlated with geometry.
        params: list = []
        pred = TrajectoryWithin(
            trajectory_within=SpatioTemporalAltitudeValue(
                geometry=_POLYGON, squawk_codes=["7700"]
            )
        )
        sql = compile_predicate(pred, params)
        assert "ST_Within(trajectory(path)," in sql
        assert "atgeometry(path," in sql
        assert ["7700"] in params

    def test_squawk_codes_param_count_no_geometry(self) -> None:
        # squawk_codes alone = 1 param (the list itself, asyncpg sends as text[])
        params: list = []
        pred = TrajectoryIntersects(
            trajectory_intersects=SpatioTemporalAltitudeValue(squawk_codes=["7700"])
        )
        compile_predicate(pred, params)
        assert len(params) == 1


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
