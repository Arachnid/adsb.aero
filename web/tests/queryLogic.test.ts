import { describe, it, expect } from "vitest";
import {
  computeLabels,
  FilterGroup,
  isPredValid,
  isGroupValid,
  isDateRangeValid,
  dateRangeToApiParams,
  countPredicates,
  makeId,
} from "../src/components/query/QueryBuilder";
import { collectGeometries, anyViewportFilter } from "../src/lib/queryGeometry";

// ---- helpers ----------------------------------------------------------------

function group(...items: FilterGroup["items"]): FilterGroup {
  return { id: makeId(), kind: "group", mode: "all", items };
}

const POLYGON: [number, number][] = [
  [-2, 50],
  [2, 50],
  [2, 52],
  [-2, 52],
  [-2, 50],
];

// ---- isPredValid ------------------------------------------------------------

describe("isPredValid", () => {
  describe("aircraft", () => {
    it("invalid when both lists empty", () => {
      expect(isPredValid({ id: "1", kind: "aircraft", icaoTypes: [], emitters: [] })).toBe(false);
    });
    it("valid with icao types", () => {
      expect(isPredValid({ id: "1", kind: "aircraft", icaoTypes: ["B738"], emitters: [] })).toBe(
        true,
      );
    });
    it("valid with emitters", () => {
      expect(isPredValid({ id: "1", kind: "aircraft", icaoTypes: [], emitters: ["A3"] })).toBe(
        true,
      );
    });
  });

  describe("callsign", () => {
    it("invalid when blank", () => {
      expect(isPredValid({ id: "1", kind: "callsign", pattern: "" })).toBe(false);
    });
    it("invalid when whitespace only", () => {
      expect(isPredValid({ id: "1", kind: "callsign", pattern: "  " })).toBe(false);
    });
    it("valid with a pattern", () => {
      expect(isPredValid({ id: "1", kind: "callsign", pattern: "^BAW" })).toBe(true);
    });
  });

  describe("starts_within / ends_within", () => {
    it("none shape invalid without time", () => {
      expect(
        isPredValid({
          id: "1",
          kind: "starts_within",
          shape: "none",
          lat: null,
          lng: null,
          radiusNm: 25,
          polygon: null,
          timeFrom: "",
          timeTo: "",
        }),
      ).toBe(false);
    });
    it("none shape valid with timeFrom", () => {
      expect(
        isPredValid({
          id: "1",
          kind: "starts_within",
          shape: "none",
          lat: null,
          lng: null,
          radiusNm: 25,
          polygon: null,
          timeFrom: "2025-01-01T00:00",
          timeTo: "",
        }),
      ).toBe(true);
    });
    it("none shape valid with timeTo", () => {
      expect(
        isPredValid({
          id: "1",
          kind: "ends_within",
          shape: "none",
          lat: null,
          lng: null,
          radiusNm: 25,
          polygon: null,
          timeFrom: "",
          timeTo: "2025-01-02T00:00",
        }),
      ).toBe(true);
    });
    it("viewport always valid", () => {
      expect(
        isPredValid({
          id: "1",
          kind: "starts_within",
          shape: "viewport",
          lat: null,
          lng: null,
          radiusNm: 25,
          polygon: null,
          timeFrom: "",
          timeTo: "",
        }),
      ).toBe(true);
    });
    it("circle invalid without coordinates", () => {
      expect(
        isPredValid({
          id: "1",
          kind: "starts_within",
          shape: "circle",
          lat: null,
          lng: null,
          radiusNm: 25,
          polygon: null,
          timeFrom: "",
          timeTo: "",
        }),
      ).toBe(false);
    });
    it("circle valid with coordinates", () => {
      expect(
        isPredValid({
          id: "1",
          kind: "starts_within",
          shape: "circle",
          lat: 51.5,
          lng: -0.1,
          radiusNm: 25,
          polygon: null,
          timeFrom: "",
          timeTo: "",
        }),
      ).toBe(true);
    });
    it("polygon invalid without polygon", () => {
      expect(
        isPredValid({
          id: "1",
          kind: "ends_within",
          shape: "polygon",
          lat: null,
          lng: null,
          radiusNm: 25,
          polygon: null,
          timeFrom: "",
          timeTo: "",
        }),
      ).toBe(false);
    });
    it("polygon invalid with fewer than 3 points", () => {
      expect(
        isPredValid({
          id: "1",
          kind: "ends_within",
          shape: "polygon",
          lat: null,
          lng: null,
          radiusNm: 25,
          polygon: [
            [-2, 50],
            [2, 50],
          ],
          timeFrom: "",
          timeTo: "",
        }),
      ).toBe(false);
    });
    it("polygon valid with 3+ points", () => {
      expect(
        isPredValid({
          id: "1",
          kind: "ends_within",
          shape: "polygon",
          lat: null,
          lng: null,
          radiusNm: 25,
          polygon: POLYGON,
          timeFrom: "",
          timeTo: "",
        }),
      ).toBe(true);
    });
  });

  describe("region", () => {
    it("none shape invalid without time", () => {
      expect(
        isPredValid({
          id: "1",
          kind: "region",
          regionName: "R",
          shape: "none",
          lat: null,
          lng: null,
          radiusNm: 25,
          polygon: null,
          altMin: null,
          altMax: null,
          timeFrom: "",
          timeTo: "",
          squawkCodes: [],
        }),
      ).toBe(false);
    });
    it("none shape valid with time", () => {
      expect(
        isPredValid({
          id: "1",
          kind: "region",
          regionName: "R",
          shape: "none",
          lat: null,
          lng: null,
          radiusNm: 25,
          polygon: null,
          altMin: null,
          altMax: null,
          timeFrom: "2025-01-01T00:00",
          timeTo: "",
          squawkCodes: [],
        }),
      ).toBe(true);
    });
    it("viewport always valid", () => {
      expect(
        isPredValid({
          id: "1",
          kind: "region",
          regionName: "R",
          shape: "viewport",
          lat: null,
          lng: null,
          radiusNm: 25,
          polygon: null,
          altMin: null,
          altMax: null,
          timeFrom: "",
          timeTo: "",
          squawkCodes: [],
        }),
      ).toBe(true);
    });
    it("circle invalid without coordinates", () => {
      expect(
        isPredValid({
          id: "1",
          kind: "region",
          regionName: "R",
          shape: "circle",
          lat: null,
          lng: null,
          radiusNm: 25,
          polygon: null,
          altMin: null,
          altMax: null,
          timeFrom: "",
          timeTo: "",
          squawkCodes: [],
        }),
      ).toBe(false);
    });
    it("circle valid with coordinates", () => {
      expect(
        isPredValid({
          id: "1",
          kind: "region",
          regionName: "R",
          shape: "circle",
          lat: 51.5,
          lng: -0.1,
          radiusNm: 25,
          polygon: null,
          altMin: null,
          altMax: null,
          timeFrom: "",
          timeTo: "",
          squawkCodes: [],
        }),
      ).toBe(true);
    });
    it("polygon invalid without polygon", () => {
      expect(
        isPredValid({
          id: "1",
          kind: "region",
          regionName: "R",
          shape: "polygon",
          lat: null,
          lng: null,
          radiusNm: 25,
          polygon: null,
          altMin: null,
          altMax: null,
          timeFrom: "",
          timeTo: "",
          squawkCodes: [],
        }),
      ).toBe(false);
    });
    it("polygon valid with 3+ points", () => {
      expect(
        isPredValid({
          id: "1",
          kind: "region",
          regionName: "R",
          shape: "polygon",
          lat: null,
          lng: null,
          radiusNm: 25,
          polygon: POLYGON,
          altMin: null,
          altMax: null,
          timeFrom: "",
          timeTo: "",
          squawkCodes: [],
        }),
      ).toBe(true);
    });
    it("invalid when altMin > altMax", () => {
      expect(
        isPredValid({
          id: "1",
          kind: "region",
          regionName: "R",
          shape: "circle",
          lat: 51.5,
          lng: -0.1,
          radiusNm: 25,
          polygon: null,
          altMin: 40000,
          altMax: 10000,
          timeFrom: "",
          timeTo: "",
          squawkCodes: [],
        }),
      ).toBe(false);
    });
    it("valid when altMin === altMax", () => {
      expect(
        isPredValid({
          id: "1",
          kind: "region",
          regionName: "R",
          shape: "circle",
          lat: 51.5,
          lng: -0.1,
          radiusNm: 25,
          polygon: null,
          altMin: 35000,
          altMax: 35000,
          timeFrom: "",
          timeTo: "",
          squawkCodes: [],
        }),
      ).toBe(true);
    });
    it("valid when only altMin set", () => {
      expect(
        isPredValid({
          id: "1",
          kind: "region",
          regionName: "R",
          shape: "circle",
          lat: 51.5,
          lng: -0.1,
          radiusNm: 25,
          polygon: null,
          altMin: 35000,
          altMax: null,
          timeFrom: "",
          timeTo: "",
          squawkCodes: [],
        }),
      ).toBe(true);
    });
  });
});

// ---- isGroupValid -----------------------------------------------------------

describe("isGroupValid", () => {
  it("empty group is valid", () => {
    expect(isGroupValid(group())).toBe(true);
  });

  it("group with valid preds is valid", () => {
    expect(
      isGroupValid(
        group(
          { id: "1", kind: "callsign", pattern: "^BAW" },
          { id: "2", kind: "aircraft", icaoTypes: ["B738"], emitters: [] },
        ),
      ),
    ).toBe(true);
  });

  it("group with one invalid pred is invalid", () => {
    expect(
      isGroupValid(
        group(
          { id: "1", kind: "callsign", pattern: "^BAW" },
          { id: "2", kind: "callsign", pattern: "" },
        ),
      ),
    ).toBe(false);
  });

  it("nested group: invalid inner makes outer invalid", () => {
    const inner = group({ id: "1", kind: "callsign", pattern: "" });
    expect(isGroupValid(group(inner))).toBe(false);
  });

  it("nested group: all valid", () => {
    const inner = group({ id: "1", kind: "callsign", pattern: "^EZY" });
    expect(
      isGroupValid(group(inner, { id: "2", kind: "aircraft", icaoTypes: ["A320"], emitters: [] })),
    ).toBe(true);
  });
});

// ---- computeLabels ----------------------------------------------------------

describe("computeLabels", () => {
  it("aircraft and callsign get no label", () => {
    const g = group(
      { id: "a", kind: "aircraft", icaoTypes: [], emitters: [] },
      { id: "b", kind: "callsign", pattern: "" },
    );
    const labels = computeLabels(g);
    expect(labels.has("a")).toBe(false);
    expect(labels.has("b")).toBe(false);
  });

  it("circle preds are numbered per type", () => {
    const g = group(
      {
        id: "s1",
        kind: "starts_within",
        shape: "circle",
        lat: 51,
        lng: 0,
        radiusNm: 10,
        polygon: null,
        timeFrom: "",
        timeTo: "",
      },
      {
        id: "s2",
        kind: "starts_within",
        shape: "circle",
        lat: 52,
        lng: 1,
        radiusNm: 10,
        polygon: null,
        timeFrom: "",
        timeTo: "",
      },
      {
        id: "e1",
        kind: "ends_within",
        shape: "circle",
        lat: 53,
        lng: 2,
        radiusNm: 10,
        polygon: null,
        timeFrom: "",
        timeTo: "",
      },
    );
    const labels = computeLabels(g);
    expect(labels.get("s1")).toBe("Starts Within 1");
    expect(labels.get("s2")).toBe("Starts Within 2");
    expect(labels.get("e1")).toBe("Ends Within 1");
  });

  it("viewport preds get base name only, not counted", () => {
    const g = group(
      {
        id: "v1",
        kind: "starts_within",
        shape: "viewport",
        lat: null,
        lng: null,
        radiusNm: 25,
        polygon: null,
        timeFrom: "",
        timeTo: "",
      },
      {
        id: "c1",
        kind: "starts_within",
        shape: "circle",
        lat: 51,
        lng: 0,
        radiusNm: 10,
        polygon: null,
        timeFrom: "",
        timeTo: "",
      },
    );
    const labels = computeLabels(g);
    expect(labels.get("v1")).toBe("Starts Within");
    expect(labels.get("c1")).toBe("Starts Within 1");
  });

  it("none preds get base name only, not counted", () => {
    const g = group(
      {
        id: "n1",
        kind: "starts_within",
        shape: "none",
        lat: null,
        lng: null,
        radiusNm: 25,
        polygon: null,
        timeFrom: "2025-01-01T00:00",
        timeTo: "",
      },
      {
        id: "c1",
        kind: "starts_within",
        shape: "circle",
        lat: 51,
        lng: 0,
        radiusNm: 10,
        polygon: null,
        timeFrom: "",
        timeTo: "",
      },
    );
    const labels = computeLabels(g);
    expect(labels.get("n1")).toBe("Starts Within");
    expect(labels.get("c1")).toBe("Starts Within 1");
  });

  it("region uses 'Ever' base name", () => {
    const g = group(
      {
        id: "r1",
        kind: "region",
        regionName: "R",
        shape: "circle",
        lat: 51,
        lng: 0,
        radiusNm: 10,
        polygon: null,
        altMin: null,
        altMax: null,
        timeFrom: "",
        timeTo: "",
        squawkCodes: [],
      },
      {
        id: "r2",
        kind: "region",
        regionName: "R",
        shape: "polygon",
        lat: null,
        lng: null,
        radiusNm: 25,
        polygon: POLYGON,
        altMin: null,
        altMax: null,
        timeFrom: "",
        timeTo: "",
        squawkCodes: [],
      },
    );
    const labels = computeLabels(g);
    expect(labels.get("r1")).toBe("Ever 1");
    expect(labels.get("r2")).toBe("Ever 2");
  });

  it("always_within uses 'Always' base name", () => {
    const g = group({
      id: "a1",
      kind: "always_within",
      regionName: "R",
      shape: "circle",
      lat: 51,
      lng: 0,
      radiusNm: 10,
      polygon: null,
      altMin: null,
      altMax: null,
      timeFrom: "",
      timeTo: "",
      squawkCodes: [],
    });
    const labels = computeLabels(g);
    expect(labels.get("a1")).toBe("Always 1");
  });

  it("numbering is independent per type", () => {
    const g = group(
      {
        id: "r1",
        kind: "region",
        regionName: "R",
        shape: "circle",
        lat: 51,
        lng: 0,
        radiusNm: 10,
        polygon: null,
        altMin: null,
        altMax: null,
        timeFrom: "",
        timeTo: "",
        squawkCodes: [],
      },
      {
        id: "s1",
        kind: "starts_within",
        shape: "circle",
        lat: 51,
        lng: 0,
        radiusNm: 10,
        polygon: null,
        timeFrom: "",
        timeTo: "",
      },
    );
    const labels = computeLabels(g);
    expect(labels.get("r1")).toBe("Ever 1");
    expect(labels.get("s1")).toBe("Starts Within 1");
  });

  it("walks nested groups", () => {
    const inner = group({
      id: "s1",
      kind: "starts_within",
      shape: "circle",
      lat: 51,
      lng: 0,
      radiusNm: 10,
      polygon: null,
      timeFrom: "",
      timeTo: "",
    });
    const outer = group(inner, {
      id: "s2",
      kind: "starts_within",
      shape: "circle",
      lat: 52,
      lng: 1,
      radiusNm: 10,
      polygon: null,
      timeFrom: "",
      timeTo: "",
    });
    const labels = computeLabels(outer);
    expect(labels.get("s1")).toBe("Starts Within 1");
    expect(labels.get("s2")).toBe("Starts Within 2");
  });
});

// ---- collectGeometries ------------------------------------------------------

describe("collectGeometries", () => {
  it("returns empty for empty group", () => {
    expect(collectGeometries(group())).toEqual([]);
  });

  it("skips aircraft and callsign preds", () => {
    const g = group(
      { id: "1", kind: "aircraft", icaoTypes: ["B738"], emitters: [] },
      { id: "2", kind: "callsign", pattern: "^BAW" },
    );
    expect(collectGeometries(g)).toEqual([]);
  });

  it("skips viewport and none shapes", () => {
    const g = group(
      {
        id: "1",
        kind: "starts_within",
        shape: "viewport",
        lat: null,
        lng: null,
        radiusNm: 25,
        polygon: null,
        timeFrom: "",
        timeTo: "",
      },
      {
        id: "2",
        kind: "starts_within",
        shape: "none",
        lat: null,
        lng: null,
        radiusNm: 25,
        polygon: null,
        timeFrom: "2025-01-01T00:00",
        timeTo: "",
      },
    );
    expect(collectGeometries(g)).toEqual([]);
  });

  it("includes circle geometry", () => {
    const g = group({
      id: "c1",
      kind: "starts_within",
      shape: "circle",
      lat: 51.5,
      lng: -0.1,
      radiusNm: 10,
      polygon: null,
      timeFrom: "",
      timeTo: "",
    });
    const [geom] = collectGeometries(g);
    expect(geom.kind).toBe("circle");
    expect(geom.lat).toBe(51.5);
    expect(geom.lng).toBe(-0.1);
    expect(geom.radiusNm).toBe(10);
    expect(geom.label).toBe("Starts Within 1");
  });

  it("includes polygon geometry", () => {
    const g = group({
      id: "p1",
      kind: "ends_within",
      shape: "polygon",
      lat: null,
      lng: null,
      radiusNm: 25,
      polygon: POLYGON,
      timeFrom: "",
      timeTo: "",
    });
    const [geom] = collectGeometries(g);
    expect(geom.kind).toBe("polygon");
    expect(geom.polygon).toEqual(POLYGON);
    expect(geom.label).toBe("Ends Within 1");
  });

  it("labels are numbered per type, matching computeLabels", () => {
    const g = group(
      {
        id: "s1",
        kind: "starts_within",
        shape: "circle",
        lat: 51,
        lng: 0,
        radiusNm: 10,
        polygon: null,
        timeFrom: "",
        timeTo: "",
      },
      {
        id: "s2",
        kind: "starts_within",
        shape: "circle",
        lat: 52,
        lng: 1,
        radiusNm: 10,
        polygon: null,
        timeFrom: "",
        timeTo: "",
      },
      {
        id: "e1",
        kind: "ends_within",
        shape: "polygon",
        lat: null,
        lng: null,
        radiusNm: 25,
        polygon: POLYGON,
        timeFrom: "",
        timeTo: "",
      },
    );
    const geoms = collectGeometries(g);
    expect(geoms).toHaveLength(3);
    expect(geoms[0].label).toBe("Starts Within 1");
    expect(geoms[1].label).toBe("Starts Within 2");
    expect(geoms[2].label).toBe("Ends Within 1");
  });

  it("assigns distinct colours cycling through palette", () => {
    const items = Array.from({ length: 7 }, (_, i) => ({
      id: String(i),
      kind: "starts_within" as const,
      shape: "circle" as const,
      lat: 51,
      lng: 0,
      radiusNm: 10,
      polygon: null,
      timeFrom: "",
      timeTo: "",
    }));
    const geoms = collectGeometries(group(...items));
    expect(geoms[0].color).toBe(geoms[6].color); // palette wraps at 6
    expect(geoms[0].color).not.toBe(geoms[1].color);
  });

  it("walks nested groups", () => {
    const inner = group({
      id: "s1",
      kind: "starts_within",
      shape: "circle",
      lat: 51,
      lng: 0,
      radiusNm: 10,
      polygon: null,
      timeFrom: "",
      timeTo: "",
    });
    const g = group(inner, {
      id: "e1",
      kind: "ends_within",
      shape: "polygon",
      lat: null,
      lng: null,
      radiusNm: 25,
      polygon: POLYGON,
      timeFrom: "",
      timeTo: "",
    });
    const geoms = collectGeometries(g);
    expect(geoms).toHaveLength(2);
  });
});

// ---- anyViewportFilter ------------------------------------------------------

describe("anyViewportFilter", () => {
  it("false for empty group", () => {
    expect(anyViewportFilter(group())).toBe(false);
  });

  it("false when no viewport shapes", () => {
    const g = group({
      id: "1",
      kind: "starts_within",
      shape: "circle",
      lat: 51,
      lng: 0,
      radiusNm: 10,
      polygon: null,
      timeFrom: "",
      timeTo: "",
    });
    expect(anyViewportFilter(g)).toBe(false);
  });

  it("true when any pred has viewport shape", () => {
    const g = group(
      {
        id: "1",
        kind: "starts_within",
        shape: "circle",
        lat: 51,
        lng: 0,
        radiusNm: 10,
        polygon: null,
        timeFrom: "",
        timeTo: "",
      },
      {
        id: "2",
        kind: "ends_within",
        shape: "viewport",
        lat: null,
        lng: null,
        radiusNm: 25,
        polygon: null,
        timeFrom: "",
        timeTo: "",
      },
    );
    expect(anyViewportFilter(g)).toBe(true);
  });

  it("detects viewport in nested group", () => {
    const inner = group({
      id: "1",
      kind: "region",
      regionName: "R",
      shape: "viewport",
      lat: null,
      lng: null,
      radiusNm: 25,
      polygon: null,
      altMin: null,
      altMax: null,
      timeFrom: "",
      timeTo: "",
      squawkCodes: [],
    });
    expect(anyViewportFilter(group(inner))).toBe(true);
  });
});

// ---- isDateRangeValid -------------------------------------------------------

describe("isDateRangeValid", () => {
  it("false when to is empty", () => {
    expect(isDateRangeValid({ to: "" })).toBe(false);
  });
  it("true with only to set", () => {
    expect(isDateRangeValid({ to: "2025-01-07" })).toBe(true);
  });
  it("true when from and to are valid and from <= to", () => {
    expect(isDateRangeValid({ from: "2025-01-01", to: "2025-01-07" })).toBe(true);
  });
  it("true for a single-day range (from === to)", () => {
    expect(isDateRangeValid({ from: "2025-06-15", to: "2025-06-15" })).toBe(true);
  });
  it("false when to is before from", () => {
    expect(isDateRangeValid({ from: "2025-01-07", to: "2025-01-01" })).toBe(false);
  });
  it("false for an invalid date string (triggers catch branch)", () => {
    expect(isDateRangeValid({ from: "not-a-date", to: "2025-01-07" })).toBe(false);
  });
});

// ---- dateRangeToApiParams ---------------------------------------------------

describe("dateRangeToApiParams", () => {
  it("converts inclusive end date to exclusive ISO string", () => {
    const params = dateRangeToApiParams({ from: "2025-01-01", to: "2025-01-07" });
    expect(params.endDate).toBe("2025-01-08T00:00:00Z");
    expect(params.startFrom).toBe("2025-01-01T00:00:00Z");
  });
  it("adds exactly one day to the to date", () => {
    const params = dateRangeToApiParams({ from: "2025-12-31", to: "2025-12-31" });
    expect(params.endDate).toBe("2026-01-01T00:00:00Z");
    expect(params.startFrom).toBe("2025-12-31T00:00:00Z");
  });
  it("returns null startFrom when from is omitted", () => {
    const params = dateRangeToApiParams({ to: "2025-06-01" });
    expect(params.endDate).toBe("2025-06-02T00:00:00Z");
    expect(params.startFrom).toBeNull();
  });
});

// ---- countPredicates --------------------------------------------------------

describe("countPredicates", () => {
  it("returns 0 for empty group", () => {
    expect(countPredicates(group())).toBe(0);
  });
  it("counts direct predicate items", () => {
    const g = group(
      { id: "1", kind: "callsign", pattern: "BAW" },
      { id: "2", kind: "callsign", pattern: "DLH" },
    );
    expect(countPredicates(g)).toBe(2);
  });
  it("recursively counts predicates in nested groups", () => {
    const inner = group(
      { id: "1", kind: "callsign", pattern: "BAW" },
      { id: "2", kind: "callsign", pattern: "DLH" },
    );
    const outer = group(inner, { id: "3", kind: "callsign", pattern: "EZY" });
    expect(countPredicates(outer)).toBe(3);
  });
});
