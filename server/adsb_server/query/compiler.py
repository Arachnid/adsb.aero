"""Compile DSL predicates into SQL WHERE clause fragments."""

from __future__ import annotations

from typing import Any

from adsb_server.geometry.h3_cells import query_disk, query_polygon_cells
from adsb_server.query.models import (
    AndPredicate,
    AnyGeometry,
    CallsignMatches,
    CircleGeometry,
    Duration,
    EmitterCategory,
    EndpointWithin,
    GeoJSONMultiPolygon,
    GeoJSONPolygon,
    IcaoType,
    NotPredicate,
    OrPredicate,
    Predicate,
    SpatioTemporalAltitudeValue,
    TrajectoryIntersects,
    TrajectoryWithin,
)

# SQL expression for QNH-corrected altitude in feet.
# Uses uncorrected getZ(path) when alt_correction_ft is NULL (no correction stored).
_CORR_ALT = (
    "CASE WHEN alt_correction_ft IS NULL THEN getZ(path) ELSE getZ(path) + alt_correction_ft END"
)


def _float_span_sql(alt_min_p: str | None, alt_max_p: str | None) -> str:
    """SQL span() expression for a floatspan altitude range (one or both bounds may be open)."""
    lb = f"{alt_min_p}::float8" if alt_min_p is not None else "'-infinity'::float8"
    ub = f"{alt_max_p}::float8" if alt_max_p is not None else "'infinity'::float8"
    ub_inc = "true" if alt_max_p is not None else "false"
    return f"span({lb}, {ub}, true, {ub_inc})"


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
    ) -> CompiledPredicate:
        instance: CompiledPredicate = super().__new__(cls, where)
        instance.ctes = ctes if ctes is not None else []
        return instance


def _p(params: list[Any], val: Any) -> str:
    """Append val to params list and return the $n placeholder string."""
    params.append(val)
    return f"${len(params)}"


def _h3_cells_for_geometry(geom: AnyGeometry) -> list[str] | None:
    """Compute H3 res-4 pre-filter cells for a geometry, or None if unsupported.

    Returns None for Point and MultiPoint (intersecting a trajectory with a point
    is measure-zero and never true in practice) and for LineString / MultiLineString
    / GeometryCollection, which lack an implementation here.  LineString could be
    handled via path_h3_cells on its coordinates if crossing queries become common.
    Queries with unsupported types still work correctly — they just skip the GIN
    pre-filter and rely on ST_Intersects to do the full scan.
    """
    if isinstance(geom, CircleGeometry):
        return query_disk(geom.coordinates[1], geom.coordinates[0], geom.radius)
    if isinstance(geom, GeoJSONPolygon):
        rings: list[list[tuple[float, float]]] = [
            [(p[0], p[1]) for p in ring] for ring in geom.coordinates
        ]
        return query_polygon_cells(rings)
    if isinstance(geom, GeoJSONMultiPolygon):
        cells: set[str] = set()
        for polygon in geom.coordinates:
            poly_rings: list[list[tuple[float, float]]] = [
                [(p[0], p[1]) for p in ring] for ring in polygon
            ]
            cells.update(query_polygon_cells(poly_rings))
        return list(cells)
    return None


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

    With altitude: builds a 3D+T STBOX via ST_3DMakeBox.  Safe to use with the
    && index pre-filter (pure bounding-box comparison, no interpolation).  Must
    NOT be passed to atStbox() — atStbox interpolates Z-boundary entry/exit
    instants, which can produce duplicate timestamps and crash with "Timestamps
    for temporal value must be increasing".
    With time only: builds a 2D+T STBOX via stbox(geom, span(...)).
    """
    has_alt = alt_min_p is not None or alt_max_p is not None
    has_time = time_from_p is not None or time_to_p is not None

    if has_alt:
        floor = f"{alt_min_p}::float8" if alt_min_p is not None else "'-99999'::float8"
        ceiling = f"{alt_max_p}::float8" if alt_max_p is not None else "'99999'::float8"
        box3d = (
            f"ST_3DMakeBox("
            f"ST_SetSRID(ST_MakePoint("
            f"ST_XMin({geom_alias}), ST_YMin({geom_alias}), {floor}), 4326), "
            f"ST_SetSRID(ST_MakePoint("
            f"ST_XMax({geom_alias}), ST_YMax({geom_alias}), {ceiling}), 4326)"
            f")"
        )
        if has_time:
            inf = "'-infinity'::timestamptz"
            sup = "'infinity'::timestamptz"
            t_min = f"{time_from_p}::timestamptz" if time_from_p is not None else inf
            t_max = f"{time_to_p}::timestamptz" if time_to_p is not None else sup
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

    spatial_fn is one of "ST_Intersects", "ST_Within".

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

    squawk_codes correlation:
      When geometry is present, squawk codes are checked only at the instants when
      the path was inside the geometry (and within any altitude/time window).
      atgeometry(path, geom) clips the trajectory to instants inside the polygon;
      getTime() extracts the time spans; atTime(squawk_seq, ...) restricts the
      squawk sequence to those same spans.  Without geometry, squawk codes are
      checked against the entire squawk_seq.
    """
    parts: list[str] = []
    ctes: list[tuple[str, str]] = []

    # Altitude bounds, separated by reference system.
    # FL bounds use raw barometric altitude: getZ(path) in feet (FL x 100).
    # ft bounds use QNH-corrected altitude: getZ(path) + alt_correction_ft.
    #
    # FL altitude IS encoded in the STBOX Z dimension for the && index pre-filter
    # (sb_idx in the CTE) so the GiST index can filter by altitude bounding box.
    # It is deliberately excluded from the atStbox() STBOX (sb): atStbox with a 3D
    # STBOX interpolates Z-boundary entry/exit instants, which can produce duplicate
    # timestamps and crash with "Timestamps for temporal value must be increasing".
    #
    # ft/QNH altitude cannot go in the STBOX Z because the per-row alt_correction_ft
    # offset is not known at plan time.  Both FL and ft are applied precisely via
    # atvalues() after atStbox() clipping.
    fl_alt_min_p: str | None = None
    fl_alt_max_p: str | None = None
    ft_alt_min_p: str | None = None
    ft_alt_max_p: str | None = None

    if v.altitude_min is not None:
        if v.altitude_min_ref == "fl":
            fl_alt_min_p = _p(params, v.altitude_min * 100.0)
        else:
            ft_alt_min_p = _p(params, float(v.altitude_min))

    if v.altitude_max is not None:
        if v.altitude_max_ref == "fl":
            fl_alt_max_p = _p(params, v.altitude_max * 100.0)
        else:
            ft_alt_max_p = _p(params, float(v.altitude_max))

    time_from_p = _p(params, v.time_from) if v.time_from is not None else None
    time_to_p = _p(params, v.time_to) if v.time_to is not None else None

    has_fl_alt = fl_alt_min_p is not None or fl_alt_max_p is not None
    has_ft_alt = ft_alt_min_p is not None or ft_alt_max_p is not None
    has_alt = has_fl_alt or has_ft_alt
    has_time = time_from_p is not None or time_to_p is not None

    # Altitude span SQL expressions for atvalues() calls.
    fl_span_sql = _float_span_sql(fl_alt_min_p, fl_alt_max_p) if has_fl_alt else ""
    ft_span_sql = _float_span_sql(ft_alt_min_p, ft_alt_max_p) if has_ft_alt else ""

    # clipped_path_expr: SQL expression for the path restricted to the region of
    # interest.  Used for squawk correlation so squawk codes are only checked
    # during the instants the flight was inside the constrained region.
    clipped_path_expr: str | None = None

    if v.geometry is not None:
        h3_cells = _h3_cells_for_geometry(v.geometry)
        if h3_cells is not None:
            h3_p = _p(params, h3_cells)
            parts.append(f"path_h3 && {h3_p}::h3index[]")

        geom_sql = _compile_geometry_sql(v.geometry, params)

        if has_time or has_alt:
            assert geom_sql is not None
            # CTE name is unique because len(params) grows monotonically across the
            # entire compile call; each spatial predicate with a CTE adds at least one
            # param before reaching this point.
            cte_name = f"_s{len(params)}"

            # sb: 2D+T STBOX for atStbox() — no Z to avoid the crash described above.
            stbox_clip_sql = _build_stbox_sql("geom", None, None, time_from_p, time_to_p)

            # sb_idx: 3D+T STBOX for the && index pre-filter when FL altitude is
            # present.  The && operator is a pure bbox comparison (no interpolation),
            # so Z bounds are safe and let the GiST index filter by altitude.
            # ft/QNH altitude is excluded because the correction is per-row.
            if has_fl_alt:
                stbox_idx_sql = _build_stbox_sql(
                    "geom", fl_alt_min_p, fl_alt_max_p, time_from_p, time_to_p
                )
                cte_body = (
                    f"SELECT geom, {stbox_clip_sql} AS sb, {stbox_idx_sql} AS sb_idx"
                    f" FROM (VALUES ({geom_sql})) AS _base(geom)"
                )
                idx_stbox = f"{cte_name}.sb_idx"
            else:
                cte_body = (
                    f"SELECT geom, {stbox_clip_sql} AS sb FROM (VALUES ({geom_sql})) AS _base(geom)"
                )
                idx_stbox = f"{cte_name}.sb"
            ctes.append((cte_name, cte_body))

            # GiST pre-filter: 3D+T (altitude-selective) when FL alt present, else 2D+T.
            parts.append(f"path && {idx_stbox}")

            # Clip path to 2D spatial + time window (no Z — avoids crash).
            clipped_stbox = f"atStbox(path, {cte_name}.sb)"

            # Further restrict to altitude range(s) via atvalues.
            # FL uses raw barometric getZ(path); ft uses QNH-corrected altitude.
            clipped_full = clipped_stbox
            if has_fl_alt:
                clipped_full = (
                    f"atTime({clipped_full}, getTime(atvalues(getZ(path), {fl_span_sql})))"
                )
            if has_ft_alt:
                clipped_full = (
                    f"atTime({clipped_full}, getTime(atvalues({_CORR_ALT}, {ft_span_sql})))"
                )

            if spatial_fn == "ST_Within":
                parts.append(f"{clipped_stbox} IS NOT NULL")
                if has_fl_alt:
                    parts.append(f"atvalues(getZ(path), {fl_span_sql}) IS NOT NULL")
                if has_ft_alt:
                    parts.append(f"atvalues({_CORR_ALT}, {ft_span_sql}) IS NOT NULL")
                parts.append(f"ST_Within(trajectory(path), {cte_name}.geom)")
            else:
                parts.append(f"eIntersects({clipped_full}, {cte_name}.geom)")

            clipped_path_expr = f"atgeometry({clipped_full}, {cte_name}.geom)"

        else:
            # Geometry only — no altitude or time constraints.
            if spatial_fn == "ST_Within":
                parts.append(f"ST_Within(trajectory(path), {geom_sql})")
            else:
                parts.append(f"eIntersects(path, {geom_sql})")
            clipped_path_expr = f"atgeometry(path, {geom_sql})"

    # Altitude when no geometry: btree indexes on stored generated columns for all refs.
    if v.geometry is None:
        if fl_alt_min_p is not None:
            parts.append(f"alt_max_pressure_ft >= {fl_alt_min_p}::float4")
        if fl_alt_max_p is not None:
            parts.append(f"alt_min_pressure_ft <= {fl_alt_max_p}::float4")
        if ft_alt_min_p is not None:
            parts.append(f"alt_max_qnh_ft >= {ft_alt_min_p}::float4")
        if ft_alt_max_p is not None:
            parts.append(f"alt_min_qnh_ft <= {ft_alt_max_p}::float4")

    # Btree time bounds for partition pruning and activity-window filtering.
    if time_from_p is not None:
        parts.append(f"end_ts >= {time_from_p}")
    if time_to_p is not None:
        parts.append(f"start_ts < {time_to_p}")

    # Dwell time / distance filters on the clipped path inside the geometry.
    # The model validator guarantees geometry is set when these are present,
    # so clipped_path_expr is always non-None here.
    if v.dwell_min_s is not None:
        dmin_p = _p(params, v.dwell_min_s)
        parts.append(f"EXTRACT(EPOCH FROM duration(getTime({clipped_path_expr}))) >= {dmin_p}")
    if v.dwell_max_s is not None:
        dmax_p = _p(params, v.dwell_max_s)
        parts.append(f"EXTRACT(EPOCH FROM duration(getTime({clipped_path_expr}))) <= {dmax_p}")
    if v.distance_min_m is not None:
        distmin_p = _p(params, v.distance_min_m)
        parts.append(f"length(trajectory({clipped_path_expr})::geography) >= {distmin_p}")
    if v.distance_max_m is not None:
        distmax_p = _p(params, v.distance_max_m)
        parts.append(f"length(trajectory({clipped_path_expr})::geography) <= {distmax_p}")

    # Squawk filter: GIN pre-filter then precise temporal check.
    # squawk_codes (text[] GIN) eliminates flights that never had any of the
    # queried codes.  squawk_seq IS NOT NULL + EXISTS then checks exact instants.
    if v.squawk_codes:
        codes_p = _p(params, v.squawk_codes)
        parts.append(f"squawk_codes && {codes_p}::text[]")
        parts.append("squawk_seq IS NOT NULL")
        if clipped_path_expr is not None:
            # Correlate: squawk must match during the instants the path was in the region.
            parts.append(
                f"EXISTS ("
                f"SELECT 1 FROM unnest(instants("
                f"atTime(squawk_seq, getTime({clipped_path_expr}))"
                f")) AS _inst"
                f" WHERE getValue(_inst) = ANY({codes_p}::text[])"
                f")"
            )
        else:
            # No geometry: check squawk for the entire flight.
            parts.append(
                f"EXISTS ("
                f"SELECT 1 FROM unnest(instants(squawk_seq)) AS _inst"
                f" WHERE getValue(_inst) = ANY({codes_p}::text[])"
                f")"
            )

    where = " AND ".join(parts) if parts else "TRUE"
    return CompiledPredicate(where, ctes=ctes)


def _compile_point_within(col: str, val: AnyGeometry, params: list[Any]) -> str:
    """Compile a spatial 'within' check on a point column expression.

    col should be 'startValue(path)::geometry' or 'endValue(path)::geometry'.

    For CircleGeometry the radius (metres) is converted to degrees using the
    standard 111,320 m/° approximation so the existing GIST index on the
    geometry column can be used.  The approximation introduces small errors at
    high latitudes but is acceptable for start/end-point proximity queries.
    """
    if isinstance(val, CircleGeometry):
        lon_p = _p(params, val.coordinates[0])
        lat_p = _p(params, val.coordinates[1])
        radius_deg_p = _p(params, val.radius / 111_320.0)
        return (
            f"ST_DWithin({col}, ST_SetSRID(ST_MakePoint({lon_p}, {lat_p}), 4326), {radius_deg_p})"
        )
    geom_p = _p(params, val.model_dump_json())
    return f"ST_Within({col}, ST_SetSRID(ST_GeomFromGeoJSON({geom_p}), 4326))"


def compile_predicate(pred: Predicate, params: list[Any]) -> CompiledPredicate:
    """Compile a Predicate into a SQL fragment, appending bind params."""
    if isinstance(pred, TrajectoryIntersects):
        return _compile_spatial_path("ST_Intersects", pred.trajectory_intersects, params)

    if isinstance(pred, TrajectoryWithin):
        return _compile_spatial_path("ST_Within", pred.trajectory_within, params)

    if isinstance(pred, EndpointWithin):
        v = pred.endpoint_within
        parts_ep: list[str] = []
        if v.mode == "either":
            # OR semantics: start branch OR end branch.
            start_parts: list[str] = []
            end_parts: list[str] = []
            if v.geometry is not None:
                if isinstance(v.geometry, CircleGeometry):
                    lon_p = _p(params, v.geometry.coordinates[0])
                    lat_p = _p(params, v.geometry.coordinates[1])
                    radius_deg_p = _p(params, v.geometry.radius / 111_320.0)
                    circle = (
                        f"ST_DWithin({{col}}, ST_SetSRID(ST_MakePoint({lon_p}, {lat_p}), 4326),"
                        f" {radius_deg_p})"
                    )
                    start_parts.append(circle.format(col="startValue(path)::geometry"))
                    end_parts.append(circle.format(col="endValue(path)::geometry"))
                else:
                    geom_p = _p(params, v.geometry.model_dump_json())
                    geom_expr = f"ST_SetSRID(ST_GeomFromGeoJSON({geom_p}), 4326)"
                    start_parts.append(f"ST_Within(startValue(path)::geometry, {geom_expr})")
                    end_parts.append(f"ST_Within(endValue(path)::geometry, {geom_expr})")
            if v.start_time_from is not None:
                start_parts.append(f"start_ts >= {_p(params, v.start_time_from)}")
            if v.start_time_to is not None:
                start_parts.append(f"start_ts < {_p(params, v.start_time_to)}")
            if v.end_time_from is not None:
                end_parts.append(f"end_ts >= {_p(params, v.end_time_from)}")
            if v.end_time_to is not None:
                end_parts.append(f"end_ts < {_p(params, v.end_time_to)}")
            if start_parts or end_parts:
                branches: list[str] = []
                if start_parts:
                    branches.append(f"({' AND '.join(start_parts)})")
                if end_parts:
                    branches.append(f"({' AND '.join(end_parts)})")
                parts_ep.append(f"({' OR '.join(branches)})")
        else:
            if v.geometry is not None:
                if v.mode == "both":
                    # Add geometry to params once; reference same index for both endpoints.
                    if isinstance(v.geometry, CircleGeometry):
                        lon_p = _p(params, v.geometry.coordinates[0])
                        lat_p = _p(params, v.geometry.coordinates[1])
                        radius_deg_p = _p(params, v.geometry.radius / 111_320.0)
                        circle = (
                            f"ST_DWithin({{col}}, ST_SetSRID(ST_MakePoint({lon_p}, {lat_p}),"
                            f" 4326), {radius_deg_p})"
                        )
                        parts_ep.append(circle.format(col="startValue(path)::geometry"))
                        parts_ep.append(circle.format(col="endValue(path)::geometry"))
                    else:
                        geom_p = _p(params, v.geometry.model_dump_json())
                        geom_expr = f"ST_SetSRID(ST_GeomFromGeoJSON({geom_p}), 4326)"
                        parts_ep.append(f"ST_Within(startValue(path)::geometry, {geom_expr})")
                        parts_ep.append(f"ST_Within(endValue(path)::geometry, {geom_expr})")
                elif v.mode == "start":
                    parts_ep.append(
                        _compile_point_within("startValue(path)::geometry", v.geometry, params)
                    )
                else:
                    parts_ep.append(
                        _compile_point_within("endValue(path)::geometry", v.geometry, params)
                    )
            if v.mode in ("start", "both"):
                if v.start_time_from is not None:
                    parts_ep.append(f"start_ts >= {_p(params, v.start_time_from)}")
                if v.start_time_to is not None:
                    parts_ep.append(f"start_ts < {_p(params, v.start_time_to)}")
            if v.mode in ("end", "both"):
                if v.end_time_from is not None:
                    parts_ep.append(f"end_ts >= {_p(params, v.end_time_from)}")
                if v.end_time_to is not None:
                    parts_ep.append(f"end_ts < {_p(params, v.end_time_to)}")
        return CompiledPredicate(" AND ".join(parts_ep) if parts_ep else "TRUE")

    if isinstance(pred, IcaoType):
        types = _p(params, pred.icao_type)
        return CompiledPredicate(f"f.icao_type = ANY({types}::varchar[])")

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
            parts_d.append(f"EXTRACT(EPOCH FROM (end_ts - start_ts)) >= {_p(params, dur.min_s)}")
        if dur.max_s is not None:
            parts_d.append(f"EXTRACT(EPOCH FROM (end_ts - start_ts)) <= {_p(params, dur.max_s)}")
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
