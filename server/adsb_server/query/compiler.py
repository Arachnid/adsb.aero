"""Compile DSL predicates into SQL WHERE clause fragments."""

from __future__ import annotations

from typing import Any

from adsb_server.query.models import (
    AndPredicate,
    AnyGeometry,
    CallsignMatches,
    CircleGeometry,
    Duration,
    EmitterCategory,
    EndsWithin,
    IcaoType,
    NotPredicate,
    OrPredicate,
    Predicate,
    SpatialPredicateValue,
    StartsWithin,
    TimeRange,
    TrajectoryDisjoint,
    TrajectoryIntersects,
    TrajectoryWithin,
)


def _p(params: list[Any], val: Any) -> str:
    """Append val to params list and return the $n placeholder string."""
    params.append(val)
    return f"${len(params)}"


def _compile_geometry_sql(geom: AnyGeometry, params: list[Any]) -> str:
    """SQL expression for a geometry value (Circle extension or standard GeoJSON)."""
    if isinstance(geom, CircleGeometry):
        lon_p = _p(params, geom.coordinates[0])
        lat_p = _p(params, geom.coordinates[1])
        radius_p = _p(params, geom.radius)
        return (
            f"ST_SetSRID(ST_Buffer("
            f"ST_SetSRID(ST_MakePoint({lon_p}, {lat_p}), 4326)::geography, "
            f"{radius_p})::geometry, 4326)"
        )
    geom_p = _p(params, geom.model_dump_json())
    return f"ST_SetSRID(ST_GeomFromGeoJSON({geom_p}), 4326)"


def _compile_spatial_path(
    spatial_fn: str, v: SpatialPredicateValue, params: list[Any]
) -> str:
    """Compile a spatial path predicate (intersects/within/disjoint) with optional altitude."""
    geom_sql = _compile_geometry_sql(v.geometry, params)
    sql = f"{spatial_fn}(path_geom, {geom_sql})"
    if v.altitude_min_ft is not None:
        alt_min = _p(params, v.altitude_min_ft)
        sql += f" AND ST_ZMax(path_geom::box3d) >= {alt_min}"
    if v.altitude_max_ft is not None:
        alt_max = _p(params, v.altitude_max_ft)
        sql += f" AND ST_ZMin(path_geom::box3d) <= {alt_max}"
    return sql


def _compile_point_within(col: str, val: AnyGeometry, params: list[Any]) -> str:
    """Compile a spatial 'within' check on a point column."""
    if isinstance(val, CircleGeometry):
        lon_p = _p(params, val.coordinates[0])
        lat_p = _p(params, val.coordinates[1])
        radius_p = _p(params, val.radius)
        return (
            f"ST_DWithin({col}::geography, "
            f"ST_SetSRID(ST_MakePoint({lon_p}, {lat_p}), 4326)::geography, "
            f"{radius_p})"
        )
    geom_p = _p(params, val.model_dump_json())
    return f"ST_Within({col}, ST_SetSRID(ST_GeomFromGeoJSON({geom_p}), 4326))"


def _compile_time_window(col: str, val: TimeRange, params: list[Any]) -> str:
    """Compile a temporal 'within' check on a timestamp column."""
    parts: list[str] = []
    if val.from_ is not None:
        parts.append(f"{col} >= {_p(params, val.from_)}")
    if val.to is not None:
        parts.append(f"{col} < {_p(params, val.to)}")
    return " AND ".join(parts) if parts else "TRUE"


def compile_predicate(pred: Predicate, params: list[Any]) -> str:
    """Compile a Predicate into a SQL fragment, appending bind params."""
    if isinstance(pred, TrajectoryIntersects):
        return _compile_spatial_path("ST_Intersects", pred.trajectory_intersects, params)

    if isinstance(pred, TrajectoryWithin):
        return _compile_spatial_path("ST_Within", pred.trajectory_within, params)

    if isinstance(pred, TrajectoryDisjoint):
        return _compile_spatial_path("ST_Disjoint", pred.trajectory_disjoint, params)

    if isinstance(pred, StartsWithin):
        val = pred.starts_within
        if isinstance(val, TimeRange):
            return _compile_time_window("start_ts", val, params)
        return _compile_point_within("start_point", val, params)

    if isinstance(pred, EndsWithin):
        val = pred.ends_within
        if isinstance(val, TimeRange):
            return _compile_time_window("end_ts", val, params)
        return _compile_point_within("end_point", val, params)

    if isinstance(pred, IcaoType):
        types = _p(params, pred.icao_type)
        return f"icao_type = ANY({types}::varchar[])"

    if isinstance(pred, EmitterCategory):
        cats = _p(params, pred.emitter_category)
        return f"emitter_category = ANY({cats}::varchar[])"

    if isinstance(pred, CallsignMatches):
        pattern = _p(params, pred.callsign_matches)
        return f"callsign ~ {pattern}"

    if isinstance(pred, Duration):
        v = pred.duration
        parts_d: list[str] = []
        if v.min_s is not None:
            parts_d.append(
                f"EXTRACT(EPOCH FROM (end_ts - start_ts)) >= {_p(params, v.min_s)}"
            )
        if v.max_s is not None:
            parts_d.append(
                f"EXTRACT(EPOCH FROM (end_ts - start_ts)) <= {_p(params, v.max_s)}"
            )
        return " AND ".join(parts_d) if parts_d else "TRUE"

    if isinstance(pred, AndPredicate):
        if not pred.and_:
            return "TRUE"
        parts_and = [f"({compile_predicate(p, params)})" for p in pred.and_]
        return " AND ".join(parts_and)

    if isinstance(pred, OrPredicate):
        if not pred.or_:
            return "FALSE"
        parts_or = [f"({compile_predicate(p, params)})" for p in pred.or_]
        return " OR ".join(parts_or)

    if isinstance(pred, NotPredicate):
        inner = compile_predicate(pred.not_, params)
        return f"NOT ({inner})"

    # exhaustive — should never reach here
    raise ValueError(f"Unknown predicate type: {type(pred)}")
