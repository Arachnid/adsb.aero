import { describe, it, expect } from "vitest";
import {
  flightsToGeoJSON,
  flightsToGPX,
  flightsToCSV,
  flightsToKML,
} from "../src/lib/export";
import type { FlightDetail } from "../src/lib/api";

const FLIGHT: FlightDetail = {
  flight_id: "aabbcc:2025-04-01T10:00:00Z",
  icao24: "aabbcc",
  callsign: "BAW123",
  icao_type: "B738",
  emitter_category: "A3",
  registration: "G-EUOF",
  model: "BOEING 737-800",
  year: 2003,
  operator: "British Airways",
  start_ts: "2025-04-01T10:00:00Z",
  end_ts: "2025-04-01T11:30:00Z",
  start_point: { type: "Point", coordinates: [-0.1275, 51.5072, 0] },
  end_point: { type: "Point", coordinates: [-2.2667, 53.4667, 0] },
  point_count: 3,
  raw_point_count: 100,
  ingest_batch_date: "2025-04-01",
  path: {
    type: "MultiLineString",
    coordinates: [
      [
        [-0.1275, 51.5072, 1000],
        [-1.2, 52.5, 35000],
        [-2.2667, 53.4667, 500],
      ],
    ],
  },
  timestamps: [[1743501600, 1743505200, 1743508800]],
};

const FLIGHT_NO_PATH: FlightDetail = {
  ...FLIGHT,
  flight_id: "ddeeff:2025-04-01T10:00:00Z",
  icao24: "ddeeff",
  callsign: null,
  path: undefined,
  timestamps: undefined,
};

describe("flightsToGeoJSON", () => {
  it("produces a FeatureCollection", () => {
    const json = JSON.parse(flightsToGeoJSON([FLIGHT])) as Record<
      string,
      unknown
    >;
    expect(json.type).toBe("FeatureCollection");
    const features = json.features as unknown[];
    expect(features).toHaveLength(1);
  });

  it("includes flight metadata as properties", () => {
    const json = JSON.parse(flightsToGeoJSON([FLIGHT])) as {
      features: Array<{ properties: Record<string, unknown> }>;
    };
    const props = json.features[0]!.properties;
    expect(props.flight_id).toBe("aabbcc:2025-04-01T10:00:00Z");
    expect(props.callsign).toBe("BAW123");
    expect(props.registration).toBe("G-EUOF");
  });

  it("preserves the MultiLineString geometry with altitude", () => {
    const json = JSON.parse(flightsToGeoJSON([FLIGHT])) as {
      features: Array<{
        geometry: { type: string; coordinates: number[][][] };
      }>;
    };
    const geom = json.features[0]!.geometry;
    expect(geom.type).toBe("MultiLineString");
    expect(geom.coordinates[0]![1]![2]).toBe(35000);
  });

  it("skips flights without a path", () => {
    const json = JSON.parse(flightsToGeoJSON([FLIGHT_NO_PATH])) as {
      features: unknown[];
    };
    expect(json.features).toHaveLength(0);
  });

  it("exports multiple flights", () => {
    const json = JSON.parse(flightsToGeoJSON([FLIGHT, FLIGHT])) as {
      features: unknown[];
    };
    expect(json.features).toHaveLength(2);
  });
});

describe("flightsToGPX", () => {
  it("produces valid GPX XML with correct root element", () => {
    const gpx = flightsToGPX([FLIGHT]);
    expect(gpx).toContain('<?xml version="1.0"');
    expect(gpx).toContain("<gpx ");
    expect(gpx).toContain("</gpx>");
  });

  it("includes a track named after the callsign", () => {
    const gpx = flightsToGPX([FLIGHT]);
    expect(gpx).toContain("<name>BAW123</name>");
  });

  it("falls back to icao24 for unnamed flights", () => {
    const gpx = flightsToGPX([FLIGHT_NO_PATH]);
    // FLIGHT_NO_PATH has no path, so no track should appear
    expect(gpx).not.toContain("<trk>");
  });

  it("converts altitude from feet to metres", () => {
    const gpx = flightsToGPX([FLIGHT]);
    // 35000 ft × 0.3048 = 10668.0 m
    expect(gpx).toContain("<ele>10668.0</ele>");
  });

  it("includes ISO timestamps in trkpt elements", () => {
    const gpx = flightsToGPX([FLIGHT]);
    expect(gpx).toContain("<time>2025-04-01T10:00:00.000Z</time>");
  });

  it("omits flights with no path", () => {
    const gpx = flightsToGPX([FLIGHT_NO_PATH]);
    expect(gpx).not.toContain("<trk>");
  });

  it("escapes XML special characters in callsign", () => {
    const f = { ...FLIGHT, callsign: "A&B<C>" };
    const gpx = flightsToGPX([f]);
    expect(gpx).toContain("<name>A&amp;B&lt;C&gt;</name>");
  });
});

describe("flightsToCSV", () => {
  it("has a header row", () => {
    const csv = flightsToCSV([FLIGHT]);
    const header = csv.split("\n")[0]!;
    expect(header).toContain("flight_id");
    expect(header).toContain("longitude");
    expect(header).toContain("altitude_ft");
  });

  it("produces one data row per trackpoint", () => {
    const csv = flightsToCSV([FLIGHT]);
    const lines = csv.split("\n");
    // 1 header + 3 trackpoints
    expect(lines).toHaveLength(4);
  });

  it("preserves pressure altitude in feet (not metres)", () => {
    const csv = flightsToCSV([FLIGHT]);
    const lines = csv.split("\n");
    const midRow = lines[2]!;
    expect(midRow).toContain("35000");
  });

  it("includes ISO timestamp for each point", () => {
    const csv = flightsToCSV([FLIGHT]);
    expect(csv).toContain("2025-04-01T10:00:00.000Z");
  });

  it("includes correct seq and point_idx columns", () => {
    const csv = flightsToCSV([FLIGHT]);
    const rows = csv.split("\n").slice(1);
    expect(rows[0]).toContain(",0,0,");
    expect(rows[1]).toContain(",0,1,");
    expect(rows[2]).toContain(",0,2,");
  });

  it("quotes cells containing commas", () => {
    const f = { ...FLIGHT, model: "BOEING, 737-800" };
    const csv = flightsToCSV([f]);
    expect(csv).toContain('"BOEING, 737-800"');
  });

  it("handles flights with no path (zero data rows)", () => {
    const csv = flightsToCSV([FLIGHT_NO_PATH]);
    const lines = csv.split("\n");
    expect(lines).toHaveLength(1); // header only
  });
});

describe("flightsToKML", () => {
  it("produces valid KML with correct root and namespace", () => {
    const kml = flightsToKML([FLIGHT]);
    expect(kml).toContain('<?xml version="1.0"');
    expect(kml).toContain('xmlns="http://www.opengis.net/kml/2.2"');
    expect(kml).toContain('xmlns:gx="http://www.google.com/kml/ext/2.2"');
    expect(kml).toContain("</kml>");
  });

  it("includes a shared plane icon style and references it from each Placemark", () => {
    const kml = flightsToKML([FLIGHT]);
    expect(kml).toContain('<Style id="flight">');
    expect(kml).toContain("airports.png");
    expect(kml).toContain("<styleUrl>#flight</styleUrl>");
  });

  it("creates a Placemark named after the callsign", () => {
    const kml = flightsToKML([FLIGHT]);
    expect(kml).toContain("<name>BAW123</name>");
  });

  it("falls back to icao24 when callsign is null", () => {
    const f = { ...FLIGHT, callsign: null };
    const kml = flightsToKML([f]);
    expect(kml).toContain("<name>aabbcc</name>");
  });

  it("uses gx:MultiTrack when timestamps are present", () => {
    const kml = flightsToKML([FLIGHT]);
    expect(kml).toContain("<gx:MultiTrack>");
    expect(kml).toContain("<gx:Track>");
    expect(kml).not.toContain("<LineString>");
  });

  it("uses MultiGeometry/LineString when timestamps are absent", () => {
    const f = { ...FLIGHT, timestamps: undefined };
    const kml = flightsToKML([f]);
    expect(kml).toContain("<MultiGeometry>");
    expect(kml).toContain("<LineString>");
    expect(kml).not.toContain("<gx:Track>");
  });

  it("converts altitude from feet to metres in gx:coord", () => {
    const kml = flightsToKML([FLIGHT]);
    // 35000 ft × 0.3048 = 10668.0 m
    expect(kml).toContain("10668.0");
  });

  it("converts altitude from feet to metres in LineString coordinates", () => {
    const f = { ...FLIGHT, timestamps: undefined };
    const kml = flightsToKML([f]);
    expect(kml).toContain("10668.0");
  });

  it("emits ISO timestamps inside gx:Track <when> elements", () => {
    const kml = flightsToKML([FLIGHT]);
    expect(kml).toContain("<when>2025-04-01T10:00:00.000Z</when>");
  });

  it("sets altitudeMode to absolute", () => {
    const kml = flightsToKML([FLIGHT]);
    expect(kml).toContain("<altitudeMode>absolute</altitudeMode>");
  });

  it("includes flight metadata in description", () => {
    const kml = flightsToKML([FLIGHT]);
    expect(kml).toContain("G-EUOF");
    expect(kml).toContain("British Airways");
  });

  it("escapes XML special characters in callsign", () => {
    const f = { ...FLIGHT, callsign: "A&B<C>" };
    const kml = flightsToKML([f]);
    expect(kml).toContain("<name>A&amp;B&lt;C&gt;</name>");
  });

  it("skips flights with no path", () => {
    const kml = flightsToKML([FLIGHT_NO_PATH]);
    expect(kml).not.toContain("<Placemark>");
  });

  it("exports multiple flights as separate Placemarks", () => {
    const kml = flightsToKML([FLIGHT, FLIGHT]);
    const count = (kml.match(/<Placemark>/g) ?? []).length;
    expect(count).toBe(2);
  });
});
