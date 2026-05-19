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

async function compressJson(obj: unknown): Promise<string> {
  const cs = new CompressionStream("deflate-raw");
  const writer = cs.writable.getWriter();
  await writer.write(
    new TextEncoder().encode(JSON.stringify(obj)) as Uint8Array<ArrayBuffer>,
  );
  await writer.close();
  const chunks: Uint8Array[] = [];
  const reader = cs.readable.getReader();
  let chunk = await reader.read();
  while (!chunk.done) {
    chunks.push(chunk.value);
    chunk = await reader.read();
  }
  const out = new Uint8Array(chunks.reduce((n, c) => n + c.length, 0));
  let off = 0;
  for (const c of chunks) {
    out.set(c, off);
    off += c.length;
  }
  let latin1 = "";
  out.forEach((b) => (latin1 += String.fromCharCode(b)));
  return "#" + btoa(latin1);
}

describe("shareUrl", () => {
  it("round-trips group + dateRange + mapView", async () => {
    const hash = await encodeShareUrl(group, dateRange, mapView);
    const decoded = await decodeShareUrl(hash);
    expect(decoded).not.toBeNull();
    expect(decoded!.dateRange).toEqual(dateRange);
    expect(decoded!.mapView).toEqual(mapView);
    // IDs are stripped on encode and regenerated — check structure, not ids
    expect(decoded!.rootGroup.kind).toBe("group");
    expect(decoded!.rootGroup.mode).toBe("all");
    expect(decoded!.rootGroup.items).toHaveLength(1);
    expect(decoded!.rootGroup.items[0]!.kind).toBe("endpoint_within");
  });

  it("round-trips without mapView", async () => {
    const hash = await encodeShareUrl(group, dateRange, null);
    const decoded = await decodeShareUrl(hash);
    expect(decoded).not.toBeNull();
    expect(decoded!.mapView).toBeNull();
  });

  it("returns null for empty hash", async () => {
    expect(await decodeShareUrl("")).toBeNull();
    expect(await decodeShareUrl("#")).toBeNull();
  });

  it("returns null for garbage input", async () => {
    expect(await decodeShareUrl("#notbase64!!!")).toBeNull();
  });

  it("returns null for wrong version", async () => {
    const hash = await compressJson({
      v: 99,
      g: { kind: "group", mode: "all", items: [] },
      d: { to: "" },
    });
    expect(await decodeShareUrl(hash)).toBeNull();
  });

  it("produces a hash string starting with #", async () => {
    expect(await encodeShareUrl(group, dateRange, mapView)).toMatch(/^#/);
  });
});
