import type { components } from "../types/api";
import type {
  FilterGroup,
  UIPredicate,
} from "../components/query/QueryBuilder";
import type { MapBounds } from "../components/map/MapView";

type Predicate = NonNullable<components["schemas"]["QueryRequest"]["match"]>;
type EndpointWithinValue = components["schemas"]["EndpointWithinValue"];
type SpatioTemporalAltitudeValue =
  components["schemas"]["SpatioTemporalAltitudeValue"];
type ApiGeometry = NonNullable<EndpointWithinValue["geometry"]>;

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
    .map((item) =>
      item.kind === "group"
        ? compileGroup(item, bounds)
        : compilePred(item, bounds),
    )
    .filter((p): p is Predicate => p !== null);

  if (children.length === 0) return null;
  if (children.length === 1) {
    const only = children[0];
    if (only !== undefined) return only;
  }
  return group.mode === "all" ? { and: children } : { or: children };
}

function compilePred(
  pred: UIPredicate,
  bounds: MapBounds | null,
): Predicate | null {
  switch (pred.kind) {
    case "aircraft": {
      const parts: Predicate[] = [];
      if (pred.icaoTypes.length > 0) parts.push({ icao_type: pred.icaoTypes });
      if (pred.emitters.length > 0)
        parts.push({ emitter_category: pred.emitters });
      if (parts.length === 0) return null;
      if (parts.length === 1) {
        const only = parts[0];
        if (only !== undefined) return only;
      }
      return { and: parts };
    }

    case "callsign":
      return pred.pattern.trim()
        ? { callsign_prefix: pred.pattern.trim() }
        : null;

    case "registration":
      return pred.prefix.trim()
        ? { registration_prefix: pred.prefix.trim() }
        : null;

    case "icao24":
      return pred.addresses.length > 0
        ? { icao24: pred.addresses.map((a) => a.toLowerCase()) }
        : null;

    case "endpoint_within": {
      const geom = shapeToGeometry(pred, bounds);
      const v: EndpointWithinValue = {
        mode: pred.mode,
        ...(geom ? { geometry: geom } : {}),
        ...(pred.startTimeFrom
          ? { start_time_from: toIso(pred.startTimeFrom) }
          : {}),
        ...(pred.startTimeTo ? { start_time_to: toIso(pred.startTimeTo) } : {}),
        ...(pred.endTimeFrom ? { end_time_from: toIso(pred.endTimeFrom) } : {}),
        ...(pred.endTimeTo ? { end_time_to: toIso(pred.endTimeTo) } : {}),
      };
      if (
        !geom &&
        !pred.startTimeFrom &&
        !pred.startTimeTo &&
        !pred.endTimeFrom &&
        !pred.endTimeTo
      )
        return null;
      return { endpoint_within: v };
    }

    case "region": {
      const geom = shapeToGeometry(pred, bounds);
      const v: SpatioTemporalAltitudeValue = {
        altitude_min_ref: pred.altMinRef,
        altitude_max_ref: pred.altMaxRef,
        ...(geom ? { geometry: geom } : {}),
        ...(pred.altMin !== null ? { altitude_min: pred.altMin } : {}),
        ...(pred.altMax !== null ? { altitude_max: pred.altMax } : {}),
        ...(pred.timeFrom ? { time_from: toIso(pred.timeFrom) } : {}),
        ...(pred.timeTo ? { time_to: toIso(pred.timeTo) } : {}),
        ...(pred.squawkCodes.length > 0
          ? { squawk_codes: pred.squawkCodes }
          : {}),
        ...(pred.dwellMinMin !== null
          ? { dwell_min_s: pred.dwellMinMin * 60 }
          : {}),
        ...(pred.dwellMaxMin !== null
          ? { dwell_max_s: pred.dwellMaxMin * 60 }
          : {}),
        ...(pred.distanceMinNm !== null
          ? { distance_min_m: pred.distanceMinNm * 1852 }
          : {}),
        ...(pred.distanceMaxNm !== null
          ? { distance_max_m: pred.distanceMaxNm * 1852 }
          : {}),
        ...(pred.aglMin !== null ? { agl_min_ft: pred.aglMin } : {}),
        ...(pred.aglMax !== null ? { agl_max_ft: pred.aglMax } : {}),
      };
      return { trajectory_intersects: v };
    }

    case "always_within": {
      const geom = shapeToGeometry(pred, bounds);
      const v: SpatioTemporalAltitudeValue = {
        altitude_min_ref: pred.altMinRef,
        altitude_max_ref: pred.altMaxRef,
        ...(geom ? { geometry: geom } : {}),
        ...(pred.altMin !== null ? { altitude_min: pred.altMin } : {}),
        ...(pred.altMax !== null ? { altitude_max: pred.altMax } : {}),
        ...(pred.timeFrom ? { time_from: toIso(pred.timeFrom) } : {}),
        ...(pred.timeTo ? { time_to: toIso(pred.timeTo) } : {}),
        ...(pred.squawkCodes.length > 0
          ? { squawk_codes: pred.squawkCodes }
          : {}),
        ...(pred.dwellMinMin !== null
          ? { dwell_min_s: pred.dwellMinMin * 60 }
          : {}),
        ...(pred.dwellMaxMin !== null
          ? { dwell_max_s: pred.dwellMaxMin * 60 }
          : {}),
        ...(pred.distanceMinNm !== null
          ? { distance_min_m: pred.distanceMinNm * 1852 }
          : {}),
        ...(pred.distanceMaxNm !== null
          ? { distance_max_m: pred.distanceMaxNm * 1852 }
          : {}),
        ...(pred.aglMin !== null ? { agl_min_ft: pred.aglMin } : {}),
        ...(pred.aglMax !== null ? { agl_max_ft: pred.aglMax } : {}),
      };
      return { trajectory_within: v };
    }
  }
}

function shapeToGeometry(
  pred: {
    shape: string;
    lat: number | null;
    lng: number | null;
    radiusNm: number;
    polygon: [number, number][] | null;
  },
  bounds: MapBounds | null,
): ApiGeometry | null {
  switch (pred.shape) {
    case "circle":
      if (pred.lat === null || pred.lng === null) return null;
      return {
        type: "Circle",
        coordinates: [pred.lng, pred.lat],
        radius: pred.radiusNm * 1852,
      };

    case "polygon":
    case "airspace": {
      if (!pred.polygon || pred.polygon.length < 3) return null;
      // GeoJSON rings must be closed (first === last vertex)
      const ring = [...pred.polygon, pred.polygon[0]] as [number, number][];
      return { type: "Polygon", coordinates: [ring] };
    }

    case "viewport": {
      if (!bounds) return null;
      const [w, s, e, n] = bounds;
      return {
        type: "Polygon",
        coordinates: [
          [
            [w, s],
            [e, s],
            [e, n],
            [w, n],
            [w, s],
          ],
        ],
      };
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
