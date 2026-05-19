import { describe, it, expect } from "vitest";
import { encodeShareUrl, decodeShareUrl } from "../src/lib/shareUrl";
import type {
  FilterGroup,
  GlobalDateRange,
} from "../src/components/query/QueryBuilder";
import type { MapViewState } from "../src/components/map/MapView";

const group: FilterGroup = {
  id: "abc",
  kind: "group",
  mode: "all",
  items: [
    {
      id: "def",
      kind: "endpoint_within",
      mode: "either",
      shape: "viewport",
      lat: null,
      lng: null,
      radiusNm: 1,
      polygon: null,
      airspaceName: null,
      airspaceLabel: null,
      startTimeFrom: "",
      startTimeTo: "",
      endTimeFrom: "",
      endTimeTo: "",
    },
  ],
};

const dateRange: GlobalDateRange = { to: "2025-04-15", from: "2025-04-10" };
const mapView: MapViewState = { lng: -1.3, lat: 50.67, zoom: 9 };

describe("shareUrl", () => {
  it("round-trips group + dateRange + mapView", () => {
    const hash = encodeShareUrl(group, dateRange, mapView);
    const decoded = decodeShareUrl(hash);
    expect(decoded).not.toBeNull();
    expect(decoded!.dateRange).toEqual(dateRange);
    expect(decoded!.mapView).toEqual(mapView);
    // IDs are stripped on encode and regenerated — check structure, not ids
    expect(decoded!.rootGroup.kind).toBe("group");
    expect(decoded!.rootGroup.mode).toBe("all");
    expect(decoded!.rootGroup.items).toHaveLength(1);
    expect(decoded!.rootGroup.items[0]!.kind).toBe("endpoint_within");
  });

  it("round-trips without mapView", () => {
    const hash = encodeShareUrl(group, dateRange, null);
    const decoded = decodeShareUrl(hash);
    expect(decoded).not.toBeNull();
    expect(decoded!.mapView).toBeNull();
  });

  it("returns null for empty hash", () => {
    expect(decodeShareUrl("")).toBeNull();
    expect(decodeShareUrl("#")).toBeNull();
  });

  it("returns null for garbage input", () => {
    expect(decodeShareUrl("#notbase64!!!")).toBeNull();
  });

  it("returns null for wrong version", () => {
    const hash = encodeShareUrl(group, dateRange, null);
    // Tamper the version by decoding, changing v, re-encoding
    const b64 = hash.slice(1);
    const json = atob(b64);
    const tampered = json.replace('"v":2', '"v":99');
    const tamperedHash = "#" + btoa(tampered);
    expect(decodeShareUrl(tamperedHash)).toBeNull();
  });

  it("produces a hash string starting with #", () => {
    expect(encodeShareUrl(group, dateRange, mapView)).toMatch(/^#/);
  });
});
