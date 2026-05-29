import type { FlightDetail } from "./api";

/* v8 ignore start */
function triggerDownload(
  filename: string,
  mimeType: string,
  content: string,
): void {
  const blob = new Blob([content], { type: mimeType });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}
/* v8 ignore stop */

function csvCell(value: string): string {
  if (value.includes(",") || value.includes('"') || value.includes("\n")) {
    return `"${value.replace(/"/g, '""')}"`;
  }
  return value;
}

function escapeXml(s: string): string {
  return s
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&apos;");
}

export function flightsToGeoJSON(flights: FlightDetail[]): string {
  const features = flights
    .filter((f) => f.path != null)
    .map((f) => ({
      type: "Feature" as const,
      geometry: f.path,
      properties: {
        flight_id: f.flight_id,
        icao24: f.icao24,
        callsign: f.callsign,
        registration: f.registration,
        model: f.model,
        operator: f.operator,
        icao_type: f.icao_type,
        start_ts: f.start_ts,
        end_ts: f.end_ts,
      },
    }));
  return JSON.stringify({ type: "FeatureCollection", features }, null, 2);
}

export function flightsToGPX(flights: FlightDetail[]): string {
  const lines: string[] = [
    '<?xml version="1.0" encoding="UTF-8"?>',
    '<gpx version="1.1" creator="adsb.aero" xmlns="http://www.topografix.com/GPX/1/1">',
  ];

  for (const f of flights) {
    const coords = f.path?.coordinates ?? [];
    if (coords.length === 0) continue;
    lines.push("  <trk>");
    lines.push(`    <name>${escapeXml(f.callsign ?? f.icao24)}</name>`);
    for (let si = 0; si < coords.length; si++) {
      const subseq = coords[si] ?? [];
      const timestamps = f.timestamps?.[si];
      lines.push("    <trkseg>");
      for (let j = 0; j < subseq.length; j++) {
        const pt = subseq[j];
        if (!pt) continue;
        const [lon, lat, altFt] = pt;
        const altM = (altFt * 0.3048).toFixed(1);
        const ts = timestamps?.[j];
        const timeStr = ts != null ? new Date(ts * 1000).toISOString() : null;
        lines.push(`      <trkpt lat="${String(lat)}" lon="${String(lon)}">`);
        lines.push(`        <ele>${altM}</ele>`);
        if (timeStr) lines.push(`        <time>${timeStr}</time>`);
        lines.push("      </trkpt>");
      }
      lines.push("    </trkseg>");
    }
    lines.push("  </trk>");
  }

  lines.push("</gpx>");
  return lines.join("\n");
}

export function flightsToCSV(flights: FlightDetail[]): string {
  const rows: string[] = [
    "flight_id,icao24,callsign,registration,model,icao_type,start_ts,end_ts,seq,point_idx,timestamp_utc,longitude,latitude,altitude_ft",
  ];

  for (const f of flights) {
    const coords = f.path?.coordinates ?? [];
    for (let si = 0; si < coords.length; si++) {
      const subseq = coords[si] ?? [];
      const timestamps = f.timestamps?.[si];
      for (let j = 0; j < subseq.length; j++) {
        const pt = subseq[j];
        if (!pt) continue;
        const [lon, lat, altFt] = pt;
        const ts = timestamps?.[j];
        const timeStr = ts != null ? new Date(ts * 1000).toISOString() : "";
        rows.push(
          [
            csvCell(f.flight_id),
            csvCell(f.icao24),
            csvCell(f.callsign ?? ""),
            csvCell(f.registration ?? ""),
            csvCell(f.model ?? ""),
            csvCell(f.icao_type ?? ""),
            csvCell(f.start_ts),
            csvCell(f.end_ts),
            String(si),
            String(j),
            csvCell(timeStr),
            lon.toFixed(6),
            lat.toFixed(6),
            String(altFt),
          ].join(","),
        );
      }
    }
  }

  return rows.join("\n");
}

export function flightsToKML(flights: FlightDetail[]): string {
  const lines: string[] = [
    '<?xml version="1.0" encoding="UTF-8"?>',
    '<kml xmlns="http://www.opengis.net/kml/2.2" xmlns:gx="http://www.google.com/kml/ext/2.2">',
    "  <Document>",
    '    <Style id="flight">',
    "      <IconStyle>",
    "        <Icon>",
    "          <href>http://maps.google.com/mapfiles/kml/shapes/airports.png</href>",
    "        </Icon>",
    "      </IconStyle>",
    "    </Style>",
  ];

  for (const f of flights) {
    const coords = f.path?.coordinates ?? [];
    if (coords.length === 0) continue;

    const descLines = [
      `ICAO24: ${f.icao24}`,
      f.registration ? `Reg: ${f.registration}` : null,
      f.model ? `Model: ${f.model}` : null,
      f.operator ? `Operator: ${f.operator}` : null,
      `Start: ${f.start_ts}`,
      `End: ${f.end_ts}`,
    ]
      .filter(Boolean)
      .join("\n");

    lines.push("    <Placemark>");
    lines.push(`      <name>${escapeXml(f.callsign ?? f.icao24)}</name>`);
    lines.push("      <styleUrl>#flight</styleUrl>");
    lines.push(`      <description><![CDATA[${descLines}]]></description>`);

    if (f.timestamps != null) {
      // gx:MultiTrack preserves coverage gaps and supports time animation in Google Earth.
      lines.push("      <gx:MultiTrack>");
      for (let si = 0; si < coords.length; si++) {
        const subseq = coords[si] ?? [];
        const timestamps = f.timestamps[si] ?? [];
        lines.push("        <gx:Track>");
        lines.push("          <altitudeMode>absolute</altitudeMode>");
        for (const ts of timestamps) {
          lines.push(
            `          <when>${new Date(ts * 1000).toISOString()}</when>`,
          );
        }
        for (const pt of subseq) {
          const [lon, lat, altFt] = pt;
          lines.push(
            `          <gx:coord>${String(lon)} ${String(lat)} ${(altFt * 0.3048).toFixed(1)}</gx:coord>`,
          );
        }
        lines.push("        </gx:Track>");
      }
      lines.push("      </gx:MultiTrack>");
    } else {
      lines.push("      <MultiGeometry>");
      for (const subseq of coords) {
        lines.push("        <LineString>");
        lines.push("          <altitudeMode>absolute</altitudeMode>");
        lines.push("          <coordinates>");
        for (const pt of subseq) {
          const [lon, lat, altFt] = pt;
          lines.push(
            `            ${String(lon)},${String(lat)},${(altFt * 0.3048).toFixed(1)}`,
          );
        }
        lines.push("          </coordinates>");
        lines.push("        </LineString>");
      }
      lines.push("      </MultiGeometry>");
    }

    lines.push("    </Placemark>");
  }

  lines.push("  </Document>");
  lines.push("</kml>");
  return lines.join("\n");
}

/* v8 ignore start */
export function downloadGeoJSON(
  flights: FlightDetail[],
  filename = "flights.geojson",
): void {
  triggerDownload(filename, "application/geo+json", flightsToGeoJSON(flights));
}

export function downloadGPX(
  flights: FlightDetail[],
  filename = "flights.gpx",
): void {
  triggerDownload(filename, "application/gpx+xml", flightsToGPX(flights));
}

export function downloadCSV(
  flights: FlightDetail[],
  filename = "flights.csv",
): void {
  triggerDownload(filename, "text/csv", flightsToCSV(flights));
}

export function downloadKML(
  flights: FlightDetail[],
  filename = "flights.kml",
): void {
  triggerDownload(
    filename,
    "application/vnd.google-earth.kml+xml",
    flightsToKML(flights),
  );
}
/* v8 ignore stop */
