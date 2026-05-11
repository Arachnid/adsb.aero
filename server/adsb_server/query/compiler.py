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
    SpatioTemporalAltitudeValue,
    SpatioTemporalValue,
    StartsWithin,
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
    spatial_fn: str, v: SpatioTemporalAltitudeValue, params: list[Any]
) -> str:
    """Compile a trajectory predicate (intersects/within/disjoint) with optional geometry, altitude, and time.

    Strategy (geometry + altitude bounds, spatial_fn != ST_Disjoint):

    1. 3D prism pre-filter via &&& — extrudes the 2D input geometry to the altitude range,
       then uses the gist_geometry_ops_nd index to prune on X, Y, and Z in a single scan.
       This replaces a 2D ST_Intersects + separate ZMax/ZMin btree checks.

    2. Exact 2D spatial check (ST_Intersects/ST_Within) on the 2D geometry.

    3. Exact per-vertex refinement via EXISTS(ST_DumpPoints) — ensures at least one vertex
       satisfies geometry ∧ altitude ∧ time simultaneously.
       Each bound reuses the same $N placeholder already bound in step 1.

    Altitude-only (no geometry): btree index on ST_ZMax/ST_ZMin expression columns.
    ST_Disjoint + altitude: btree checks (&&& prism semantics don't apply to disjoint).
    """
    parts: list[str] = []

    # Bind altitude/time params once; placeholders are reused in both pre-filters and EXISTS.
    alt_min_p = _p(params, v.altitude_min_ft) if v.altitude_min_ft is not None else None
    alt_max_p = _p(params, v.altitude_max_ft) if v.altitude_max_ft is not None else None
    time_from_p = _p(params, v.time_from) if v.time_from is not None else None
    time_to_p = _p(params, v.time_to) if v.time_to is not None else None

    if v.geometry is not None:
        geom_sql = _compile_geometry_sql(v.geometry, params)
        has_altitude = alt_min_p is not None or alt_max_p is not None

        if has_altitude and spatial_fn != "ST_Disjoint":
            # Extrude the 2D geometry to a 3D prism spanning the altitude range.
            # ST_Collect of two copies at floor/ceiling Z gives the right 3D bounding box.
            # &&& hits the gist_geometry_ops_nd index, pruning on X, Y, Z in one scan.
            floor_sql = alt_min_p if alt_min_p is not None else "-10000"
            ceiling_sql = alt_max_p if alt_max_p is not None else "200000"
            parts.append(
                f"path_geom &&& ST_Collect("
                f"ST_Force3D({geom_sql}, {floor_sql}::float8), "
                f"ST_Force3D({geom_sql}, {ceiling_sql}::float8))"
            )
            # ST_Intersects is redundant here: any row satisfying EXISTS (a vertex inside
            # the polygon at the right altitude/time) also satisfies ST_Intersects.
            # ST_Within is not redundant — EXISTS checks "≥1 vertex inside" while ST_Within
            # checks "whole path inside", so keep it for trajectory_within.
            if spatial_fn != "ST_Intersects":
                parts.append(f"{spatial_fn}(path_geom, {geom_sql})")
        else:
            parts.append(f"{spatial_fn}(path_geom, {geom_sql})")

        # Exact combined check: geometry ∧ altitude ∧ time must coincide at the same vertex.
        if spatial_fn != "ST_Disjoint":
            has_zmt = has_altitude or time_from_p is not None or time_to_p is not None
            if has_zmt:
                vertex_conds: list[str] = [f"ST_Intersects(ST_Force2D(dp.geom), {geom_sql})"]
                if alt_min_p is not None:
                    vertex_conds.append(f"ST_Z(dp.geom) >= {alt_min_p}")
                if alt_max_p is not None:
                    vertex_conds.append(f"ST_Z(dp.geom) <= {alt_max_p}")
                if time_from_p is not None:
                    vertex_conds.append(f"ST_M(dp.geom) >= EXTRACT(EPOCH FROM {time_from_p}::timestamptz)")
                if time_to_p is not None:
                    vertex_conds.append(f"ST_M(dp.geom) < EXTRACT(EPOCH FROM {time_to_p}::timestamptz)")
                parts.append(
                    f"EXISTS (SELECT 1 FROM ST_DumpPoints(path_geom) dp"
                    f" WHERE {' AND '.join(vertex_conds)})"
                )

    # Altitude pre-filters via btree expression indexes on ST_ZMax/ST_ZMin.
    # Used when there's no geometry (altitude-only query) or ST_Disjoint (prism inapplicable).
    if v.geometry is None or spatial_fn == "ST_Disjoint":
        if alt_min_p is not None:
            parts.append(f"ST_ZMax(path_geom::box3d) >= {alt_min_p}")
        if alt_max_p is not None:
            parts.append(f"ST_ZMin(path_geom::box3d) <= {alt_max_p}")

    if time_from_p is not None:
        parts.append(f"end_ts >= {time_from_p}")
    if time_to_p is not None:
        parts.append(f"start_ts < {time_to_p}")

    return " AND ".join(parts) if parts else "TRUE"


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


def compile_predicate(pred: Predicate, params: list[Any]) -> str:
    """Compile a Predicate into a SQL fragment, appending bind params."""
    if isinstance(pred, TrajectoryIntersects):
        return _compile_spatial_path("ST_Intersects", pred.trajectory_intersects, params)

    if isinstance(pred, TrajectoryWithin):
        return _compile_spatial_path("ST_Within", pred.trajectory_within, params)

    if isinstance(pred, TrajectoryDisjoint):
        return _compile_spatial_path("ST_Disjoint", pred.trajectory_disjoint, params)

    if isinstance(pred, StartsWithin):
        v = pred.starts_within
        parts_s: list[str] = []
        if v.geometry is not None:
            parts_s.append(_compile_point_within("start_point", v.geometry, params))
        if v.time_from is not None:
            parts_s.append(f"start_ts >= {_p(params, v.time_from)}")
        if v.time_to is not None:
            parts_s.append(f"start_ts < {_p(params, v.time_to)}")
        return " AND ".join(parts_s) if parts_s else "TRUE"

    if isinstance(pred, EndsWithin):
        v = pred.ends_within
        parts_e: list[str] = []
        if v.geometry is not None:
            parts_e.append(_compile_point_within("end_point", v.geometry, params))
        if v.time_from is not None:
            parts_e.append(f"end_ts >= {_p(params, v.time_from)}")
        if v.time_to is not None:
            parts_e.append(f"end_ts < {_p(params, v.time_to)}")
        return " AND ".join(parts_e) if parts_e else "TRUE"

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
