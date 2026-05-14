import { describe, it, expect } from "vitest";
import { compileGroup } from "../src/lib/compileQuery";
import { makeId, FilterGroup } from "../src/components/query/QueryBuilder";
import type { MapBounds } from "../src/components/map/MapView";

function group(...items: FilterGroup["items"]): FilterGroup {
  return { id: makeId(), kind: "group", mode: "all", items };
}

function anyGroup(...items: FilterGroup["items"]): FilterGroup {
  return { id: makeId(), kind: "group", mode: "any", items };
}

const BOUNDS: MapBounds = [-2, 50, 2, 52];
const POLYGON: [number, number][] = [[-2, 50], [2, 50], [2, 52], [-2, 52]];

// Fields required by IntersectsPred / AlwaysWithinPred that have no bearing on most tests.
const REGION_DEFAULTS = {
  altMinRef: "ft" as const,
  altMaxRef: "ft" as const,
  airspaceName: null,
  airspaceLabel: null,
  dwellMinMin: null,
  dwellMaxMin: null,
  distanceMinNm: null,
  distanceMaxNm: null,
};

// ---- empty group -----------------------------------------------------------

describe("empty group", () => {
  it("returns null", () => {
    expect(compileGroup(group(), null)).toBeNull();
  });
});

// ---- callsign --------------------------------------------------------------

describe("callsign", () => {
  it("compiles a pattern", () => {
    const g = group({ id: "1", kind: "callsign", pattern: "^BAW" });
    expect(compileGroup(g, null)).toEqual({ callsign_matches: "^BAW" });
  });

  it("trims whitespace", () => {
    const g = group({ id: "1", kind: "callsign", pattern: "  EZY  " });
    expect(compileGroup(g, null)).toEqual({ callsign_matches: "EZY" });
  });

  it("returns null for blank pattern", () => {
    const g = group({ id: "1", kind: "callsign", pattern: "   " });
    expect(compileGroup(g, null)).toBeNull();
  });
});

// ---- aircraft --------------------------------------------------------------

describe("aircraft", () => {
  it("compiles icao_type only", () => {
    const g = group({ id: "1", kind: "aircraft", icaoTypes: ["B738"], emitters: [] });
    expect(compileGroup(g, null)).toEqual({ icao_type: ["B738"] });
  });

  it("compiles emitter_category only", () => {
    const g = group({ id: "1", kind: "aircraft", icaoTypes: [], emitters: ["A3"] });
    expect(compileGroup(g, null)).toEqual({ emitter_category: ["A3"] });
  });

  it("combines both with and", () => {
    const g = group({ id: "1", kind: "aircraft", icaoTypes: ["B738"], emitters: ["A3"] });
    expect(compileGroup(g, null)).toEqual({
      and: [{ icao_type: ["B738"] }, { emitter_category: ["A3"] }],
    });
  });

  it("returns null when both empty", () => {
    const g = group({ id: "1", kind: "aircraft", icaoTypes: [], emitters: [] });
    expect(compileGroup(g, null)).toBeNull();
  });
});

// ---- starts_within ---------------------------------------------------------

describe("starts_within", () => {
  it("circle geometry", () => {
    const g = group({
      id: "1", kind: "starts_within", shape: "circle",
      lat: 51.5, lng: -0.1, radiusNm: 10,
      polygon: null, timeFrom: "", timeTo: "",
    });
    expect(compileGroup(g, null)).toEqual({
      starts_within: {
        geometry: { type: "Circle", coordinates: [-0.1, 51.5], radius: 10 * 1852 },
      },
    });
  });

  it("polygon geometry (ring closed)", () => {
    const g = group({
      id: "1", kind: "starts_within", shape: "polygon",
      lat: null, lng: null, radiusNm: 25,
      polygon: POLYGON, timeFrom: "", timeTo: "",
    });
    const result = compileGroup(g, null) as { starts_within: { geometry: unknown } };
    const geom = result.starts_within.geometry as { type: string; coordinates: unknown[][] };
    expect(geom.type).toBe("Polygon");
    const ring = geom.coordinates[0] as [number, number][];
    expect(ring[0]).toEqual(ring[ring.length - 1]);
    expect(ring).toHaveLength(POLYGON.length + 1);
  });

  it("viewport geometry from bounds", () => {
    const g = group({
      id: "1", kind: "starts_within", shape: "viewport",
      lat: null, lng: null, radiusNm: 25,
      polygon: null, timeFrom: "", timeTo: "",
    });
    expect(compileGroup(g, BOUNDS)).toEqual({
      starts_within: {
        geometry: {
          type: "Polygon",
          coordinates: [[[-2, 50], [2, 50], [2, 52], [-2, 52], [-2, 50]]],
        },
      },
    });
  });

  it("viewport with no bounds returns null", () => {
    const g = group({
      id: "1", kind: "starts_within", shape: "viewport",
      lat: null, lng: null, radiusNm: 25,
      polygon: null, timeFrom: "", timeTo: "",
    });
    expect(compileGroup(g, null)).toBeNull();
  });

  it("includes time fields", () => {
    const g = group({
      id: "1", kind: "starts_within", shape: "circle",
      lat: 51.5, lng: -0.1, radiusNm: 10,
      polygon: null, timeFrom: "2025-01-01T12:00", timeTo: "2025-01-02T00:00",
    });
    const result = compileGroup(g, null) as { starts_within: Record<string, unknown> };
    expect(result.starts_within.time_from).toBe("2025-01-01T12:00:00Z");
    expect(result.starts_within.time_to).toBe("2025-01-02T00:00:00Z");
  });

  it("none shape with time only", () => {
    const g = group({
      id: "1", kind: "starts_within", shape: "none",
      lat: null, lng: null, radiusNm: 25,
      polygon: null, timeFrom: "2025-06-01T00:00", timeTo: "",
    });
    expect(compileGroup(g, null)).toEqual({
      starts_within: { time_from: "2025-06-01T00:00:00Z" },
    });
  });

  it("none shape without time or geometry returns null", () => {
    const g = group({
      id: "1", kind: "starts_within", shape: "none",
      lat: null, lng: null, radiusNm: 25,
      polygon: null, timeFrom: "", timeTo: "",
    });
    expect(compileGroup(g, null)).toBeNull();
  });
});

// ---- ends_within -----------------------------------------------------------

describe("ends_within", () => {
  it("circle geometry", () => {
    const g = group({
      id: "1", kind: "ends_within", shape: "circle",
      lat: 53.0, lng: -1.0, radiusNm: 5,
      polygon: null, timeFrom: "", timeTo: "",
    });
    expect(compileGroup(g, null)).toEqual({
      ends_within: {
        geometry: { type: "Circle", coordinates: [-1.0, 53.0], radius: 5 * 1852 },
      },
    });
  });
});

// ---- region (trajectory_intersects) ----------------------------------------

describe("region", () => {
  it("circle geometry", () => {
    const g = group({
      id: "1", kind: "region", regionName: "R", shape: "circle",
      lat: 51.5, lng: -0.1, radiusNm: 20,
      polygon: null, altMin: null, altMax: null, timeFrom: "", timeTo: "", squawkCodes: [],
      ...REGION_DEFAULTS,
    });
    expect(compileGroup(g, null)).toEqual({
      trajectory_intersects: {
        altitude_min_ref: "ft", altitude_max_ref: "ft",
        geometry: { type: "Circle", coordinates: [-0.1, 51.5], radius: 20 * 1852 },
      },
    });
  });

  it("includes altitude fields", () => {
    const g = group({
      id: "1", kind: "region", regionName: "R", shape: "circle",
      lat: 51.5, lng: -0.1, radiusNm: 20,
      polygon: null, altMin: 10000, altMax: 40000, timeFrom: "", timeTo: "", squawkCodes: [],
      ...REGION_DEFAULTS,
    });
    const result = compileGroup(g, null) as { trajectory_intersects: Record<string, unknown> };
    expect(result.trajectory_intersects.altitude_min).toBe(10000);
    expect(result.trajectory_intersects.altitude_max).toBe(40000);
  });

  it("omits altitude fields when null", () => {
    const g = group({
      id: "1", kind: "region", regionName: "R", shape: "circle",
      lat: 51.5, lng: -0.1, radiusNm: 20,
      polygon: null, altMin: null, altMax: null, timeFrom: "", timeTo: "", squawkCodes: [],
      ...REGION_DEFAULTS,
    });
    const result = compileGroup(g, null) as { trajectory_intersects: Record<string, unknown> };
    expect("altitude_min" in result.trajectory_intersects).toBe(false);
    expect("altitude_max" in result.trajectory_intersects).toBe(false);
  });

  it("none shape always produces trajectory_intersects with default refs", () => {
    const g = group({
      id: "1", kind: "region", regionName: "R", shape: "none",
      lat: null, lng: null, radiusNm: 25,
      polygon: null, altMin: null, altMax: null, timeFrom: "", timeTo: "", squawkCodes: [],
      ...REGION_DEFAULTS,
    });
    expect(compileGroup(g, null)).toEqual({
      trajectory_intersects: { altitude_min_ref: "ft", altitude_max_ref: "ft" },
    });
  });

  it("includes time fields", () => {
    const g = group({
      id: "1", kind: "region", regionName: "R", shape: "none",
      lat: null, lng: null, radiusNm: 25,
      polygon: null, altMin: null, altMax: null,
      timeFrom: "2025-03-15T06:00", timeTo: "2025-03-15T18:00", squawkCodes: [],
      ...REGION_DEFAULTS,
    });
    const result = compileGroup(g, null) as { trajectory_intersects: Record<string, unknown> };
    expect(result.trajectory_intersects.time_from).toBe("2025-03-15T06:00:00Z");
    expect(result.trajectory_intersects.time_to).toBe("2025-03-15T18:00:00Z");
  });

  it("includes squawk_codes when non-empty", () => {
    const g = group({
      id: "1", kind: "region", regionName: "R", shape: "none",
      lat: null, lng: null, radiusNm: 25,
      polygon: null, altMin: null, altMax: null, timeFrom: "", timeTo: "",
      squawkCodes: ["7700", "7600"],
      ...REGION_DEFAULTS,
    });
    const result = compileGroup(g, null) as { trajectory_intersects: Record<string, unknown> };
    expect(result.trajectory_intersects.squawk_codes).toEqual(["7700", "7600"]);
  });

  it("omits squawk_codes when empty", () => {
    const g = group({
      id: "1", kind: "region", regionName: "R", shape: "none",
      lat: null, lng: null, radiusNm: 25,
      polygon: null, altMin: null, altMax: null, timeFrom: "", timeTo: "", squawkCodes: [],
      ...REGION_DEFAULTS,
    });
    const result = compileGroup(g, null) as { trajectory_intersects: Record<string, unknown> };
    expect("squawk_codes" in result.trajectory_intersects).toBe(false);
  });
});

// ---- always_within (trajectory_within) -------------------------------------

describe("always_within", () => {
  it("circle geometry compiles to trajectory_within", () => {
    const g = group({
      id: "1", kind: "always_within", regionName: "R", shape: "circle",
      lat: 51.5, lng: -0.1, radiusNm: 20,
      polygon: null, altMin: null, altMax: null, timeFrom: "", timeTo: "", squawkCodes: [],
      ...REGION_DEFAULTS,
    });
    expect(compileGroup(g, null)).toEqual({
      trajectory_within: {
        altitude_min_ref: "ft", altitude_max_ref: "ft",
        geometry: { type: "Circle", coordinates: [-0.1, 51.5], radius: 20 * 1852 },
      },
    });
  });

  it("includes altitude and time fields", () => {
    const g = group({
      id: "1", kind: "always_within", regionName: "R", shape: "circle",
      lat: 51.5, lng: -0.1, radiusNm: 20,
      polygon: null, altMin: 5000, altMax: 30000,
      timeFrom: "2025-04-01T00:00", timeTo: "2025-04-01T12:00", squawkCodes: [],
      ...REGION_DEFAULTS,
    });
    const result = compileGroup(g, null) as { trajectory_within: Record<string, unknown> };
    expect(result.trajectory_within.altitude_min).toBe(5000);
    expect(result.trajectory_within.altitude_max).toBe(30000);
    expect(result.trajectory_within.time_from).toBe("2025-04-01T00:00:00Z");
    expect(result.trajectory_within.time_to).toBe("2025-04-01T12:00:00Z");
  });

  it("includes squawk_codes when non-empty", () => {
    const g = group({
      id: "1", kind: "always_within", regionName: "R", shape: "none",
      lat: null, lng: null, radiusNm: 25,
      polygon: null, altMin: null, altMax: null, timeFrom: "", timeTo: "",
      squawkCodes: ["1200"],
      ...REGION_DEFAULTS,
    });
    const result = compileGroup(g, null) as { trajectory_within: Record<string, unknown> };
    expect(result.trajectory_within.squawk_codes).toEqual(["1200"]);
  });
});

// ---- boolean combinators ---------------------------------------------------

describe("group combinators", () => {
  it("single valid pred is unwrapped (no and/or)", () => {
    const g = group({ id: "1", kind: "callsign", pattern: "^BAW" });
    const result = compileGroup(g, null);
    expect(result).toEqual({ callsign_matches: "^BAW" });
    expect(result).not.toHaveProperty("and");
  });

  it("two preds in all-mode → and", () => {
    const g = group(
      { id: "1", kind: "callsign", pattern: "^BAW" },
      { id: "2", kind: "aircraft", icaoTypes: ["B738"], emitters: [] },
    );
    expect(compileGroup(g, null)).toEqual({
      and: [{ callsign_matches: "^BAW" }, { icao_type: ["B738"] }],
    });
  });

  it("two preds in any-mode → or", () => {
    const g = anyGroup(
      { id: "1", kind: "callsign", pattern: "^BAW" },
      { id: "2", kind: "callsign", pattern: "^EZY" },
    );
    expect(compileGroup(g, null)).toEqual({
      or: [{ callsign_matches: "^BAW" }, { callsign_matches: "^EZY" }],
    });
  });

  it("null predicates are excluded from children", () => {
    const g = group(
      { id: "1", kind: "callsign", pattern: "" },
      { id: "2", kind: "callsign", pattern: "^BAW" },
    );
    expect(compileGroup(g, null)).toEqual({ callsign_matches: "^BAW" });
  });

  it("group with all-null predicates returns null", () => {
    const g = group(
      { id: "1", kind: "callsign", pattern: "" },
      { id: "2", kind: "aircraft", icaoTypes: [], emitters: [] },
    );
    expect(compileGroup(g, null)).toBeNull();
  });

  it("nested groups: inner compiled and included", () => {
    const inner = anyGroup(
      { id: "1", kind: "callsign", pattern: "^BAW" },
      { id: "2", kind: "callsign", pattern: "^EZY" },
    );
    const outer = group(inner, { id: "3", kind: "aircraft", icaoTypes: ["B738"], emitters: [] });
    expect(compileGroup(outer, null)).toEqual({
      and: [
        { or: [{ callsign_matches: "^BAW" }, { callsign_matches: "^EZY" }] },
        { icao_type: ["B738"] },
      ],
    });
  });
});

// ---- toIso -----------------------------------------------------------------
// Tested indirectly via time fields above. This spot-check covers the 19-char form.

describe("toIso (via time fields)", () => {
  it("passes through an already-full ISO string", () => {
    const g = group({
      id: "1", kind: "starts_within", shape: "none",
      lat: null, lng: null, radiusNm: 25,
      polygon: null, timeFrom: "2025-01-01T12:00:00", timeTo: "",
    });
    const result = compileGroup(g, null) as { starts_within: Record<string, unknown> };
    expect(result.starts_within.time_from).toBe("2025-01-01T12:00:00Z");
  });
});
