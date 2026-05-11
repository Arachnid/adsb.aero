import type { components } from "../types/api";
import type { FilterGroup, UIPredicate } from "../components/query/QueryBuilder";
import type { MapBounds } from "../components/map/MapView";

type Predicate = NonNullable<components["schemas"]["QueryRequest"]["match"]>;
type SpatioTemporalValue = components["schemas"]["SpatioTemporalValue"];
type SpatioTemporalAltitudeValue = components["schemas"]["SpatioTemporalAltitudeValue"];
type ApiGeometry = NonNullable<SpatioTemporalValue["geometry"]>;

/**
 * Compile a FilterGroup into an API Predicate. Returns null for an empty group
 * (caller should send `match: null` to return all flights).
 *
 * `bounds` is the current map viewport as [west, south, east, north] and is
 * required to resolve any "viewport" shape predicates.
 */
export function compileGroup(
  group: FilterGroup,
  bounds: MapBounds | null,
): Predicate | null {
  const children = group.items
    .map((item) => (item.kind === "group" ? compileGroup(item, bounds) : compilePred(item, bounds)))
    .filter((p): p is Predicate => p !== null);

  if (children.length === 0) return null;
  if (children.length === 1) return children[0]!;
  return group.mode === "all" ? { and: children } : { or: children };
}

function compilePred(pred: UIPredicate, bounds: MapBounds | null): Predicate | null {
  switch (pred.kind) {
    case "aircraft": {
      const parts: Predicate[] = [];
      if (pred.icaoTypes.length > 0) parts.push({ icao_type: pred.icaoTypes });
      if (pred.emitters.length > 0) parts.push({ emitter_category: pred.emitters });
      if (parts.length === 0) return null;
      if (parts.length === 1) return parts[0]!;
      return { and: parts };
    }

    case "callsign":
      return pred.pattern.trim() ? { callsign_matches: pred.pattern.trim() } : null;

    case "starts_within": {
      const v = buildSpatioTemporal(pred, bounds);
      return v ? { starts_within: v } : null;
    }

    case "ends_within": {
      const v = buildSpatioTemporal(pred, bounds);
      return v ? { ends_within: v } : null;
    }

    case "region": {
      const geom = shapeToGeometry(pred, bounds);
      const v: SpatioTemporalAltitudeValue = {
        ...(geom ? { geometry: geom } : {}),
        ...(pred.altMin !== null ? { altitude_min_ft: pred.altMin } : {}),
        ...(pred.altMax !== null ? { altitude_max_ft: pred.altMax } : {}),
        ...(pred.timeFrom ? { time_from: toIso(pred.timeFrom) } : {}),
        ...(pred.timeTo ? { time_to: toIso(pred.timeTo) } : {}),
      };
      return { trajectory_intersects: v };
    }
  }
}

function buildSpatioTemporal(
  pred: { shape: string; lat: number | null; lng: number | null; radiusNm: number; polygon: [number, number][] | null; timeFrom: string; timeTo: string },
  bounds: MapBounds | null,
): SpatioTemporalValue | null {
  const geom = shapeToGeometry(pred, bounds);
  const v: SpatioTemporalValue = {
    ...(geom ? { geometry: geom } : {}),
    ...(pred.timeFrom ? { time_from: toIso(pred.timeFrom) } : {}),
    ...(pred.timeTo ? { time_to: toIso(pred.timeTo) } : {}),
  };
  // Guard: at least one field must be present (mirrors server-side validator)
  if (!geom && !pred.timeFrom && !pred.timeTo) return null;
  return v;
}

function shapeToGeometry(
  pred: { shape: string; lat: number | null; lng: number | null; radiusNm: number; polygon: [number, number][] | null },
  bounds: MapBounds | null,
): ApiGeometry | null {
  switch (pred.shape) {
    case "circle":
      if (pred.lat === null || pred.lng === null) return null;
      return { type: "Circle", coordinates: [pred.lng, pred.lat], radius: pred.radiusNm * 1852 };

    case "polygon": {
      if (!pred.polygon || pred.polygon.length < 3) return null;
      // GeoJSON rings must be closed (first === last vertex)
      const ring = [...pred.polygon, pred.polygon[0]] as [number, number][];
      return { type: "Polygon", coordinates: [ring] };
    }

    case "viewport": {
      if (!bounds) return null;
      const [w, s, e, n] = bounds;
      return { type: "Polygon", coordinates: [[[w, s], [e, s], [e, n], [w, n], [w, s]]] };
    }

    default: // "none"
      return null;
  }
}

/** Convert a datetime-local string ("YYYY-MM-DDTHH:mm") to an ISO 8601 UTC string. */
function toIso(dt: string): string {
  if (dt.length === 16) return dt + ":00Z";
  if (dt.length === 19) return dt + "Z";
  return dt;
}
