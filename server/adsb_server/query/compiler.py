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
    StartsWithin,
    TrajectoryDisjoint,
    TrajectoryIntersects,
    TrajectoryWithin,
)


class CompiledPredicate(str):
    """SQL WHERE fragment that may carry CTE definitions for use in WITH clauses.

    Subclasses str so it works as a plain string in most contexts.
    ctes holds (alias, select_body) pairs; each CTE produces a single row with
    'geom' (the 2D geometry) and 'sb' (the STBOX) columns.
    """

    ctes: list[tuple[str, str]]

    def __new__(
        cls,
        where: str,
        ctes: list[tuple[str, str]] | None = None,
    ) -> "CompiledPredicate":
        instance: "CompiledPredicate" = super().__new__(cls, where)
        instance.ctes = ctes if ctes is not None else []
        return instance


def _p(params: list[Any], val: Any) -> str:
    """Append val to params list and return the $n placeholder string."""
    params.append(val)
    return f"${len(params)}"


def _compile_geometry_sql(geom: AnyGeometry, params: list[Any]) -> str:
    """SQL expression for a 2D geometry value (Circle extension or standard GeoJSON)."""
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


def _build_stbox_sql(
    geom_alias: str,
    alt_min_p: str | None,
    alt_max_p: str | None,
    time_from_p: str | None,
    time_to_p: str | None,
) -> str:
    """Build an STBOX SQL expression referencing geom_alias as the 2D geometry.

    With altitude: builds a 3D STBOX via ST_3DMakeBox so that atStbox clips
    the tgeompoint to both the spatial region and the altitude window —
    correctly enforcing that the path intersected the geometry at that altitude.
    With time only: builds a 2D+T STBOX via stbox(geom, span(...)).
    """
    has_alt = alt_min_p is not None or alt_max_p is not None
    has_time = time_from_p is not None or time_to_p is not None

    if has_alt:
        floor = f"{alt_min_p}::float8" if alt_min_p is not None else "'-99999'::float8"
        ceiling = f"{alt_max_p}::float8" if alt_max_p is not None else "'99999'::float8"
        box3d = (
            f"ST_3DMakeBox("
            f"ST_SetSRID(ST_MakePoint(ST_XMin({geom_alias}), ST_YMin({geom_alias}), {floor}), 4326), "
            f"ST_SetSRID(ST_MakePoint(ST_XMax({geom_alias}), ST_YMax({geom_alias}), {ceiling}), 4326)"
            f")"
        )
        if has_time:
            t_min = f"{time_from_p}::timestamptz" if time_from_p is not None else "'-infinity'::timestamptz"
            t_max = f"{time_to_p}::timestamptz" if time_to_p is not None else "'infinity'::timestamptz"
            return f"stbox({box3d}, span({t_min}, {t_max}, true, false))"
        return f"stbox({box3d})"

    # Time only — no altitude bounds.
    t_min = f"{time_from_p}::timestamptz" if time_from_p is not None else "'-infinity'::timestamptz"
    t_max = f"{time_to_p}::timestamptz" if time_to_p is not None else "'infinity'::timestamptz"
    return f"stbox({geom_alias}, span({t_min}, {t_max}, true, false))"


def _compile_spatial_path(
    spatial_fn: str, v: SpatioTemporalAltitudeValue, params: list[Any]
) -> CompiledPredicate:
    """Compile a trajectory predicate using MobilityDB operators.

    spatial_fn is one of "ST_Intersects", "ST_Within", "ST_Disjoint".

    When geometry is combined with altitude or time constraints, a CTE is emitted
    that computes the geometry and its STBOX once.  The WHERE fragment references
    the CTE alias (e.g. _s0.geom, _s0.sb) to avoid repeating expensive expressions.

    trajectory_intersects (eIntersects):
      atStbox clips the tgeompoint to the altitude+time window; eIntersects then
      checks whether the clipped path intersects the geometry.  This correctly
      enforces that the intersection occurred at the specified altitude.

    trajectory_within:
      path && STBOX pre-filters via the GiST index; atStbox IS NOT NULL confirms
      the path has instants in the window; ST_Within(trajectory(path), geom)
      verifies the entire path lies inside the geometry.

    trajectory_disjoint:
      NOT eIntersects(path, geom).  No STBOX (negative lookup can't use the
      index); altitude/time fall back to btree expression indexes.
    """
    parts: list[str] = []
    ctes: list[tuple[str, str]] = []

    alt_min_p = _p(params, v.altitude_min_ft) if v.altitude_min_ft is not None else None
    alt_max_p = _p(params, v.altitude_max_ft) if v.altitude_max_ft is not None else None
    time_from_p = _p(params, v.time_from) if v.time_from is not None else None
    time_to_p = _p(params, v.time_to) if v.time_to is not None else None

    has_time = time_from_p is not None or time_to_p is not None
    has_alt = alt_min_p is not None or alt_max_p is not None

    if v.geometry is not None:
        geom_sql = _compile_geometry_sql(v.geometry, params)

        if spatial_fn == "ST_Disjoint":
            # Disjoint: no index-friendly STBOX for negative lookups; btree altitude below.
            parts.append(f"NOT eIntersects(path, {geom_sql})")

        elif has_time or has_alt:
            # CTE name is unique because len(params) grows monotonically across the
            # entire compile call; each spatial predicate with a CTE adds at least one
            # param before reaching this point.
            cte_name = f"_s{len(params)}"
            stbox_sql = _build_stbox_sql(
                "geom", alt_min_p, alt_max_p, time_from_p, time_to_p
            )
            cte_body = (
                f"SELECT geom, {stbox_sql} AS sb "
                f"FROM (VALUES ({geom_sql})) AS _base(geom)"
            )
            ctes.append((cte_name, cte_body))

            # GiST STBOX index pre-filter.
            parts.append(f"path && {cte_name}.sb")

            if spatial_fn == "ST_Within":
                # Confirm at least one instant falls in the altitude/time window.
                parts.append(f"atStbox(path, {cte_name}.sb) IS NOT NULL")
                # The entire path must lie within the geometry.
                parts.append(f"ST_Within(trajectory(path), {cte_name}.geom)")
            else:  # ST_Intersects → clip to altitude+time window then check intersection
                parts.append(
                    f"eIntersects(atStbox(path, {cte_name}.sb), {cte_name}.geom)"
                )

        else:
            # Geometry only — no altitude or time constraints.
            if spatial_fn == "ST_Within":
                parts.append(f"ST_Within(trajectory(path), {geom_sql})")
            else:  # ST_Intersects
                parts.append(f"eIntersects(path, {geom_sql})")

    # Altitude via btree expression indexes when there is no geometry, or for disjoint.
    if v.geometry is None or spatial_fn == "ST_Disjoint":
        if alt_min_p is not None:
            parts.append(f"ST_ZMax(trajectory(path)::box3d) >= {alt_min_p}::float8")
        if alt_max_p is not None:
            parts.append(f"ST_ZMin(trajectory(path)::box3d) <= {alt_max_p}::float8")

    # Btree time bounds for partition pruning and activity-window filtering.
    if time_from_p is not None:
        parts.append(f"end_ts >= {time_from_p}")
    if time_to_p is not None:
        parts.append(f"start_ts < {time_to_p}")

    where = " AND ".join(parts) if parts else "TRUE"
    return CompiledPredicate(where, ctes=ctes)


def _compile_point_within(col: str, val: AnyGeometry, params: list[Any]) -> str:
    """Compile a spatial 'within' check on a point column expression.

    col should be 'startValue(path)::geometry' or 'endValue(path)::geometry'.
    """
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


def compile_predicate(pred: Predicate, params: list[Any]) -> CompiledPredicate:
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
            parts_s.append(_compile_point_within("startValue(path)::geometry", v.geometry, params))
        if v.time_from is not None:
            parts_s.append(f"start_ts >= {_p(params, v.time_from)}")
        if v.time_to is not None:
            parts_s.append(f"start_ts < {_p(params, v.time_to)}")
        return CompiledPredicate(" AND ".join(parts_s) if parts_s else "TRUE")

    if isinstance(pred, EndsWithin):
        v = pred.ends_within
        parts_e: list[str] = []
        if v.geometry is not None:
            parts_e.append(_compile_point_within("endValue(path)::geometry", v.geometry, params))
        if v.time_from is not None:
            parts_e.append(f"end_ts >= {_p(params, v.time_from)}")
        if v.time_to is not None:
            parts_e.append(f"end_ts < {_p(params, v.time_to)}")
        return CompiledPredicate(" AND ".join(parts_e) if parts_e else "TRUE")

    if isinstance(pred, IcaoType):
        types = _p(params, pred.icao_type)
        return CompiledPredicate(f"icao_type = ANY({types}::varchar[])")

    if isinstance(pred, EmitterCategory):
        cats = _p(params, pred.emitter_category)
        return CompiledPredicate(f"emitter_category = ANY({cats}::varchar[])")

    if isinstance(pred, CallsignMatches):
        pattern = _p(params, pred.callsign_matches)
        return CompiledPredicate(f"callsign ~ {pattern}")

    if isinstance(pred, Duration):
        dur = pred.duration
        parts_d: list[str] = []
        if dur.min_s is not None:
            parts_d.append(
                f"EXTRACT(EPOCH FROM (end_ts - start_ts)) >= {_p(params, dur.min_s)}"
            )
        if dur.max_s is not None:
            parts_d.append(
                f"EXTRACT(EPOCH FROM (end_ts - start_ts)) <= {_p(params, dur.max_s)}"
            )
        return CompiledPredicate(" AND ".join(parts_d) if parts_d else "TRUE")

    if isinstance(pred, AndPredicate):
        if not pred.and_:
            return CompiledPredicate("TRUE")
        compiled_parts = [compile_predicate(p, params) for p in pred.and_]
        all_ctes = [cte for c in compiled_parts for cte in c.ctes]
        parts_and = [f"({c})" for c in compiled_parts]
        return CompiledPredicate(" AND ".join(parts_and), ctes=all_ctes)

    if isinstance(pred, OrPredicate):
        if not pred.or_:
            return CompiledPredicate("FALSE")
        compiled_parts = [compile_predicate(p, params) for p in pred.or_]
        all_ctes = [cte for c in compiled_parts for cte in c.ctes]
        parts_or = [f"({c})" for c in compiled_parts]
        return CompiledPredicate(" OR ".join(parts_or), ctes=all_ctes)

    if isinstance(pred, NotPredicate):
        inner = compile_predicate(pred.not_, params)
        return CompiledPredicate(f"NOT ({inner})", ctes=inner.ctes)

    # exhaustive — should never reach here
    raise ValueError(f"Unknown predicate type: {type(pred)}")
