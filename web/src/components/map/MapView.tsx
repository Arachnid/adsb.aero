import {
  GeoJSONSource,
  Map as MaplibreMap,
  MapMouseEvent,
  setWorkerUrl,
  StyleSpecification,
} from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import { useEffect, useRef, useState } from "react";
import { MapboxOverlay } from "@deck.gl/mapbox";
import { LineLayer, ScatterplotLayer } from "@deck.gl/layers";
import type { FlightDetail } from "../../lib/api";
import { altToColor, catToColor, squawkToColor, vsToColor, gsToColor, iasToColor, type RGBA } from "../../lib/colors";

import workerUrl from "maplibre-gl/dist/maplibre-gl-csp-worker?url";
setWorkerUrl(workerUrl);

type Basemap = "dark" | "light" | "sat";
export type ColorMode = "alt" | "cat" | "vs" | "gs" | "ias" | "sqk";

// Precomputed segment for LineLayer — one per adjacent vertex pair in a path.
type Seg = {
  from: [number, number];
  to: [number, number];
  altMid: number;
  altFt: number;
  altFtTo: number;
  cat: string | null;
  squawk: string | null;
  flightId: string;
  pointIdx: number;
  vs: number | null;
  gs: number | null;
  ias: number | null;
  track: number | null;
  callsign: string | null;
  icao24: string;
  icaoType: string | null;
  tsFrom: number;
  tsTo: number;
};

// Step-interpolate (forward-fill) a [[ts, value], ...] series at a given timestamp.
export function stepValueAt(series: number[][] | null | undefined, ts: number): number | null {
  if (!series || series.length === 0) return null;
  let val: number | null = null;
  for (const entry of series) {
    const entryTs = entry[0]; const entryVal = entry[1];
    if (entryTs === undefined || entryVal === undefined) continue;
    if (entryTs <= ts) val = entryVal;
    else break;
  }
  return val;
}

// Project cursor (lng/lat) onto segment [from, to], return t in [0, 1].
export function projectOntoSegment(
  from: [number, number],
  to: [number, number],
  cursor: [number, number],
): number {
  const dx = to[0] - from[0];
  const dy = to[1] - from[1];
  const lenSq = dx * dx + dy * dy;
  if (lenSq === 0) return 0;
  return Math.max(0, Math.min(1, ((cursor[0] - from[0]) * dx + (cursor[1] - from[1]) * dy) / lenSq));
}

export function trackToCompass(deg: number): string {
  const dirs = ["N","NNE","NE","ENE","E","ESE","SE","SSE","S","SSW","SW","WSW","W","WNW","NW","NNW"] as const;
  return dirs[Math.round(deg / 22.5) % 16] ?? "N";
}

function fmtUtc(ts: number): string {
  return new Date(ts * 1000).toISOString().slice(11, 19);
}

// Return the active squawk code at unix timestamp ts, or null if none applies.
// runs must be sorted ascending by timestamp (as returned by the API).
export function squawkAt(runs: [number, string][], ts: number): string | null {
  let code: string | null = null;
  for (const [runTs, c] of runs) {
    if (runTs <= ts) code = c;
    else break;
  }
  return code;
}

const SAT_STYLE: StyleSpecification = {
  version: 8,
  glyphs: "https://demotiles.maplibre.org/font/{fontstack}/{range}.pbf",
  sources: {
    "esri-sat": {
      type: "raster",
      tiles: [
        "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
      ],
      tileSize: 256,
      attribution:
        "Tiles &copy; Esri &mdash; Esri, DigitalGlobe, GeoEye, USDA, USGS, and the GIS User Community",
      maxzoom: 19,
    },
  },
  layers: [{ id: "esri-sat", type: "raster", source: "esri-sat", minzoom: 0, maxzoom: 22 }],
};

const STYLES: Record<Basemap, string | StyleSpecification> = {
  dark: "https://tiles.openfreemap.org/styles/dark",
  light: "https://tiles.openfreemap.org/styles/liberty",
  sat: SAT_STYLE,
};

import type { MapGeometry } from "../../lib/queryGeometry";
export type { MapGeometry } from "../../lib/queryGeometry";

// Minimal inline GeoJSON types to avoid @types/geojson dependency issues.
type Coord = [number, number];
type GeoFeat =
  | {
      type: "Feature";
      properties: Record<string, string>;
      geometry: { type: "Polygon"; coordinates: Coord[][] };
    }
  | {
      type: "Feature";
      properties: Record<string, never>;
      geometry: { type: "Point"; coordinates: Coord };
    }
  | {
      type: "Feature";
      properties: Record<string, never>;
      geometry: { type: "LineString"; coordinates: Coord[] };
    }
  | {
      type: "Feature";
      properties: { label: string; color: string; rotation: number };
      geometry: { type: "Point"; coordinates: Coord };
    };
type GeoFC = { type: "FeatureCollection"; features: GeoFeat[] };

const EMPTY_FC: GeoFC = { type: "FeatureCollection", features: [] };

function approxCircle(lng: number, lat: number, radiusKm: number): Coord[] {
  const R = 6371;
  const latRad = (lat * Math.PI) / 180;
  const dLat = (radiusKm / R) * (180 / Math.PI);
  const dLng = dLat / Math.cos(latRad);
  const pts: Coord[] = [];
  for (let i = 0; i <= 64; i++) {
    const a = (i / 64) * 2 * Math.PI;
    pts.push([lng + dLng * Math.sin(a), lat + dLat * Math.cos(a)]);
  }
  return pts;
}

function topEdgeInfo(pts: Coord[]): { center: Coord; rotation: number } {
  const n = pts.length;
  const lats = pts.map((p) => p[1]);
  const maxLat = Math.max(...lats);
  const minLat = Math.min(...lats);
  const threshold = maxLat - (maxLat - minLat) * 0.5;

  type EdgeInfo = { dx: number; dy: number; len: number };
  const topEdges: EdgeInfo[] = [];
  let topMinLng = Infinity,
    topMaxLng = -Infinity;

  for (let i = 0; i < n; i++) {
    const a = pts[i];
    const b = pts[(i + 1) % n];
    if (!a || !b) continue;
    const midLat = (a[1] + b[1]) / 2;
    if (midLat >= threshold) {
      const cosLat = Math.cos((midLat * Math.PI) / 180);
      const dx = (b[0] - a[0]) * cosLat;
      const dy = b[1] - a[1];
      topEdges.push({ dx, dy, len: Math.sqrt(dx * dx + dy * dy) });
    }
    if (a[1] >= threshold) {
      topMinLng = Math.min(topMinLng, a[0]);
      topMaxLng = Math.max(topMaxLng, a[0]);
    }
  }

  if (topEdges.length === 0) {
    for (let i = 0; i < n; i++) {
      const a = pts[i];
      const b = pts[(i + 1) % n];
      if (!a || !b) continue;
      const midLat = (a[1] + b[1]) / 2;
      const cosLat = Math.cos((midLat * Math.PI) / 180);
      const dx = (b[0] - a[0]) * cosLat;
      const dy = b[1] - a[1];
      topEdges.push({ dx, dy, len: Math.sqrt(dx * dx + dy * dy) });
    }
    topMinLng = Math.min(...pts.map((p) => p[0]));
    topMaxLng = Math.max(...pts.map((p) => p[0]));
  }

  // An edge is "long" if it spans > 15% of the polygon's projected width.
  // Long edges are authoritative on their own — pick the most horizontal one
  // rather than averaging, so that a flat edge and a slightly angled neighbour
  // of similar length don't combine into a jaunty result.
  // When all edges are short (e.g. a circle), average them by length instead.
  const polyWidth =
    (topMaxLng - topMinLng) * Math.cos((maxLat * Math.PI) / 180);
  const longThreshold = polyWidth * 0.15;
  const longEdges = topEdges.filter((e) => e.len > longThreshold);

  let sumDx = 0,
    sumDy = 0;
  if (longEdges.length > 0) {
    const best = longEdges.reduce((a, b) =>
      Math.abs(a.dx) / a.len > Math.abs(b.dx) / b.len ? a : b,
    );
    sumDx = best.dx;
    sumDy = best.dy;
  } else {
    for (const e of topEdges) {
      sumDx += e.dx * e.len;
      sumDy += e.dy * e.len;
    }
  }

  const centerLng = (topMinLng + topMaxLng) / 2;
  const center: Coord = [centerLng, maxLat];

  let rotation = Math.atan2(sumDx, sumDy) * (180 / Math.PI) - 90;
  if (rotation > 90) rotation -= 180;
  if (rotation < -90) rotation += 180;
  return { center, rotation };
}

function buildFillFC(geoms: MapGeometry[]): GeoFC {
  return {
    type: "FeatureCollection",
    features: geoms.flatMap((g): GeoFeat[] => {
      let ring: Coord[] | null = null;
      if (g.kind === "polygon" && g.polygon && g.polygon.length >= 3) {
        const first = g.polygon[0];
        if (first) ring = [...g.polygon, first];
      } else if (g.kind === "circle" && g.lat != null && g.lng != null) {
        ring = approxCircle(g.lng, g.lat, g.radiusNm * 1.852);
      }
      if (!ring) return [];
      return [
        {
          type: "Feature",
          properties: { color: g.color },
          geometry: { type: "Polygon", coordinates: [ring] },
        },
      ];
    }),
  };
}

function buildLabelFC(geoms: MapGeometry[]): GeoFC {
  return {
    type: "FeatureCollection",
    features: geoms.flatMap((g): GeoFeat[] => {
      let center: Coord | null = null;
      let rotation = 0;
      if (g.kind === "polygon" && g.polygon && g.polygon.length >= 3) {
        const info = topEdgeInfo(g.polygon);
        center = info.center;
        rotation = info.rotation;
      } else if (g.kind === "circle" && g.lat != null && g.lng != null) {
        center = [g.lng, g.lat + (g.radiusNm * 1.852) / 111.32];
      }
      if (!center) return [];
      return [
        {
          type: "Feature",
          properties: { label: g.label, color: g.color, rotation },
          geometry: { type: "Point", coordinates: center },
        },
      ];
    }),
  };
}

function buildDraftFC(pts: Coord[]): GeoFC {
  return {
    type: "FeatureCollection",
    features: [
      ...pts.map(
        (p): GeoFeat => ({
          type: "Feature",
          properties: {},
          geometry: { type: "Point", coordinates: p },
        }),
      ),
      ...(pts.length >= 2
        ? [
            {
              type: "Feature" as const,
              properties: {} as Record<string, never>,
              geometry: { type: "LineString" as const, coordinates: pts },
            },
          ]
        : []),
    ],
  };
}

function setSource(src: GeoJSONSource | undefined, data: GeoFC): void {
  src?.setData(data);
}

function initOverlays(map: MaplibreMap, geoms: MapGeometry[]): void {
  map.addSource("filter-geoms", {
    type: "geojson",
    data: buildFillFC(geoms) as Parameters<GeoJSONSource["setData"]>[0],
  });
  map.addSource("filter-labels", {
    type: "geojson",
    data: buildLabelFC(geoms) as Parameters<GeoJSONSource["setData"]>[0],
  });
  map.addSource("draft", {
    type: "geojson",
    data: EMPTY_FC as Parameters<GeoJSONSource["setData"]>[0],
  });

  map.addLayer({
    id: "filter-fill",
    type: "fill",
    source: "filter-geoms",
    paint: { "fill-color": ["get", "color"], "fill-opacity": 0.15 },
  });
  map.addLayer({
    id: "filter-line",
    type: "line",
    source: "filter-geoms",
    paint: { "line-color": ["get", "color"], "line-width": 2 },
  });
  map.addLayer({
    id: "filter-label",
    type: "symbol",
    source: "filter-labels",
    layout: {
      "text-field": ["get", "label"],
      "text-size": 11,
      "text-font": ["Open Sans Semibold", "Arial Unicode MS Bold"],
      "text-anchor": "center",
      "text-rotate": ["get", "rotation"],
      "text-offset": [0, 0.6],
    },
    paint: {
      "text-color": ["get", "color"],
      "text-halo-color": "rgba(255,255,255,0.9)",
      "text-halo-width": 2,
    },
  });
  map.addLayer({
    id: "draft-line",
    type: "line",
    source: "draft",
    filter: ["==", "$type", "LineString"],
    paint: { "line-color": "#ffffff", "line-width": 1.5, "line-dasharray": [3, 2] },
  });
  map.addLayer({
    id: "draft-point",
    type: "circle",
    source: "draft",
    filter: ["==", "$type", "Point"],
    paint: {
      "circle-radius": 4,
      "circle-color": "#ffffff",
      "circle-stroke-width": 1.5,
      "circle-stroke-color": "#000000",
    },
  });
}

// [west, south, east, north] in degrees
export type MapBounds = [number, number, number, number];

export type HoveredPoint = { flightId: string; pointIdx: number };

interface MapViewProps {
  basemap: Basemap;
  chartsOn: boolean;
  pickingActive: boolean;
  drawingActive: boolean;
  airspacePickingActive: boolean;
  onPickPoint: (lat: number, lng: number) => void;
  onDrawComplete: (points: [number, number][]) => void;
  onPickAirspace: (lat: number, lng: number, x: number, y: number) => void;
  geometries: MapGeometry[];
  onMoveEnd?: (bounds: MapBounds) => void;
  flights: FlightDetail[] | null;
  colorMode: ColorMode;
  selectedFlightId: string | null;
  onSelectFlight: (id: string | null) => void;
  hoveredPoint: HoveredPoint | null;
  onHoverPoint: (p: HoveredPoint | null) => void;
}

export function MapView({
  basemap,
  chartsOn,
  pickingActive,
  drawingActive,
  airspacePickingActive,
  onPickPoint,
  onDrawComplete,
  onPickAirspace,
  geometries,
  onMoveEnd,
  flights,
  colorMode,
  selectedFlightId,
  onSelectFlight,
  hoveredPoint,
  onHoverPoint,
}: MapViewProps): React.ReactElement {
  const containerRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<MaplibreMap | null>(null);
  const deckRef = useRef<MapboxOverlay | null>(null);
  const pickingRef = useRef(pickingActive);
  const drawingRef = useRef(drawingActive);
  const drawPointsRef = useRef<Coord[]>([]);
  const onPickRef = useRef(onPickPoint);
  const onDrawRef = useRef(onDrawComplete);
  const geometriesRef = useRef(geometries);
  const onMoveEndRef = useRef(onMoveEnd);
  const onSelectRef = useRef(onSelectFlight);
  const onHoverPointRef = useRef(onHoverPoint);
  const chartsOnRef = useRef(chartsOn);
  const airspacePickingRef = useRef(airspacePickingActive);
  const onPickAirspaceRef = useRef(onPickAirspace);
  const selectedFlightIdRef = useRef(selectedFlightId);
  // Persists the main flight layers so the hover-dot effect can append without rebuilding them.
  const mainLayersRef = useRef<(LineLayer<Seg> | ScatterplotLayer<FlightDetail>)[]>([]);

  const [mapTooltip, setMapTooltip] = useState<{
    x: number;
    y: number;
    dotPos: [number, number];
    altFt: number;
    ts: number;
    callsign: string | null;
    icao24: string;
    icaoType: string | null;
    cat: string | null;
    gs: number | null;
    vs: number | null;
    ias: number | null;
    track: number | null;
    squawk: string | null;
  } | null>(null);
  const setMapTooltipRef = useRef(setMapTooltip);
  setMapTooltipRef.current = setMapTooltip;

  pickingRef.current = pickingActive;
  drawingRef.current = drawingActive;
  onPickRef.current = onPickPoint;
  onDrawRef.current = onDrawComplete;
  geometriesRef.current = geometries;
  onMoveEndRef.current = onMoveEnd;
  onSelectRef.current = onSelectFlight;
  onHoverPointRef.current = onHoverPoint;
  chartsOnRef.current = chartsOn;
  airspacePickingRef.current = airspacePickingActive;
  onPickAirspaceRef.current = onPickAirspace;
  selectedFlightIdRef.current = selectedFlightId;

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !map.getSource("filter-geoms")) return;
    setSource(map.getSource("filter-geoms"), buildFillFC(geometries));
    setSource(
      map.getSource("filter-labels"),
      buildLabelFC(geometries),
    );
  }, [geometries]);

  useEffect(() => {
    if (!drawingActive) {
      drawPointsRef.current = [];
      setSource(mapRef.current?.getSource("draft"), EMPTY_FC);
    }
  }, [drawingActive]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !map.getLayer("openaip-charts")) return;
    map.setLayoutProperty("openaip-charts", "visibility", chartsOn ? "visible" : "none");
  }, [chartsOn]);

  useEffect(() => {
    const canvas = mapRef.current?.getCanvas();
    if (canvas) {
      canvas.style.cursor = pickingActive || drawingActive || airspacePickingActive ? "crosshair" : "";
    }
  }, [pickingActive, drawingActive, airspacePickingActive]);

  useEffect(() => {
    if (!containerRef.current || mapRef.current) return;

    const map = new MaplibreMap({
      container: containerRef.current,
      style: STYLES[basemap],
      center: [-2.0, 54.5],
      zoom: 5,
      attributionControl: { compact: true },
    });

    const onClick = (e: MapMouseEvent): void => {
      const { lat, lng } = e.lngLat;
      if (airspacePickingRef.current) {
        onPickAirspaceRef.current(lat, lng, e.point.x, e.point.y);
        return;
      }
      if (pickingRef.current) {
        onPickRef.current(lat, lng);
        return;
      }
      if (drawingRef.current) {
        const pts: Coord[] = [...drawPointsRef.current, [lng, lat]];
        drawPointsRef.current = pts;
        setSource(map.getSource("draft"), buildDraftFC(pts));
      }
    };

    const onDblClick = (e: MapMouseEvent & { preventDefault: () => void }): void => {
      if (!drawingRef.current) return;
      e.preventDefault();
      const { lat, lng } = e.lngLat;
      const pts: Coord[] = [...drawPointsRef.current, [lng, lat]];
      drawPointsRef.current = [];
      setSource(map.getSource("draft"), EMPTY_FC);
      if (pts.length >= 3) onDrawRef.current(pts);
    };

    const getBounds = (): MapBounds => {
      const b = map.getBounds().toArray();
      return [b[0][0], b[0][1], b[1][0], b[1][1]];
    };

    const onMoveEndHandler = (): void => {
      onMoveEndRef.current?.(getBounds());
    };

    const setupOverlays = (): void => {
      if (!map.getSource("filter-geoms")) {
        map.addSource("openaip", {
          type: "raster",
          tiles: ["/tiles/openaip/{z}/{x}/{y}.png"],
          tileSize: 256,
          minzoom: 5,
          maxzoom: 14,
          attribution: "© <a href='https://www.openaip.net/' target='_blank'>OpenAIP</a>",
        });
        map.addLayer({
          id: "openaip-charts",
          type: "raster",
          source: "openaip",
          layout: { visibility: chartsOnRef.current ? "visible" : "none" },
          paint: { "raster-opacity": 0.8 },
        });
        initOverlays(map, geometriesRef.current);
      }
    };

    const onLoadHandler = (): void => {
      onMoveEndRef.current?.(getBounds());
    };

    if (map.isStyleLoaded()) {
      setupOverlays();
      onLoadHandler();
    }
    map.on("style.load", (): void => {
      setupOverlays();
      onLoadHandler();
    });
    map.on("click", onClick);
    map.on("dblclick", onDblClick);
    map.on("moveend", onMoveEndHandler);
    const overlay = new MapboxOverlay({
      pickingRadius: 8,
      onClick: (info): void => {
        if (pickingRef.current || drawingRef.current) return;
        if (info.picked) {
          onSelectRef.current((info.object as Seg).flightId);
        } else {
          onSelectRef.current(null);
        }
      },
      onHover: (info): void => {
        const canvas = mapRef.current?.getCanvas();
        if (!canvas || pickingRef.current || drawingRef.current) return;
        canvas.style.cursor = info.picked ? "pointer" : "";
        if (info.picked) {
          const seg = info.object as Seg;
          const sel = selectedFlightIdRef.current;
          if (sel !== null && seg.flightId !== sel) {
            canvas.style.cursor = "";
            onHoverPointRef.current(null);
            setMapTooltipRef.current(null);
            return;
          }
          const cursor = info.coordinate as [number, number] | undefined;
          const t = cursor ? projectOntoSegment(seg.from, seg.to, cursor) : 0;
          const altFt = Math.round(seg.altFt + t * (seg.altFtTo - seg.altFt));
          const ts = seg.tsFrom + t * (seg.tsTo - seg.tsFrom);
          const dotPos: [number, number] = [
            seg.from[0] + t * (seg.to[0] - seg.from[0]),
            seg.from[1] + t * (seg.to[1] - seg.from[1]),
          ];
          onHoverPointRef.current({ flightId: seg.flightId, pointIdx: seg.pointIdx });
          setMapTooltipRef.current({
            x: info.x, y: info.y, dotPos,
            altFt, ts,
            callsign: seg.callsign,
            icao24: seg.icao24,
            icaoType: seg.icaoType,
            cat: seg.cat,
            gs: seg.gs,
            vs: seg.vs,
            ias: seg.ias,
            track: seg.track,
            squawk: seg.squawk,
          });
        } else {
          onHoverPointRef.current(null);
          setMapTooltipRef.current(null);
        }
      },
      layers: [],
    });
    map.addControl(overlay);
    deckRef.current = overlay;
    mapRef.current = map;

    return (): void => {
      map.off("click", onClick);
      map.off("dblclick", onDblClick);
      map.off("moveend", onMoveEndHandler);
      map.remove();
      mapRef.current = null;
      deckRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    const overlay = deckRef.current;
    if (!overlay) return;

    if (!flights?.length) {
      overlay.setProps({ layers: [] });
      return;
    }

    const segments: Seg[] = flights.flatMap((f) => {
      const coords = f.path?.coordinates;
      if (!coords || coords.length < 2) return [];
      const runs = f.squawk_runs ?? [];
      return coords.slice(0, -1).map((c, i): Seg => {
        // slice(0,-1) guarantees i+1 < coords.length
        const next = coords[i + 1] ?? c;
        const ts = f.timestamps?.[i] ?? 0;
        const tsNext = f.timestamps?.[i + 1] ?? ts;
        return {
          from: [c[0], c[1]],
          to: [next[0], next[1]],
          altMid: (c[2] + next[2]) / 2,
          altFt: c[2],
          altFtTo: next[2],
          cat: f.emitter_category ?? null,
          squawk: squawkAt(runs, ts),
          flightId: f.flight_id,
          pointIdx: i,
          vs: stepValueAt(f.path_vr, ts),
          gs: stepValueAt(f.path_gs, ts),
          ias: stepValueAt(f.path_ias, ts),
          track: stepValueAt(f.path_tracks, ts),
          callsign: f.callsign ?? null,
          icao24: f.icao24,
          icaoType: f.icao_type ?? null,
          tsFrom: ts,
          tsTo: tsNext,
        };
      });
    });

    const hasSel = selectedFlightId !== null;

    const getColor = (s: Seg): RGBA => {
      const base =
        colorMode === "alt" ? altToColor(s.altMid) :
        colorMode === "cat" ? catToColor(s.cat) :
        colorMode === "sqk" ? squawkToColor(s.squawk) :
        colorMode === "vs"  ? vsToColor(s.vs) :
        colorMode === "gs"  ? gsToColor(s.gs) :
        iasToColor(s.ias);
      if (hasSel && s.flightId !== selectedFlightId) {
        return [base[0], base[1], base[2], Math.round(base[3] * 0.2)];
      }
      return base;
    };

    const getWidth = (s: Seg): number => (hasSel && s.flightId === selectedFlightId ? 4 : 2.5);

    const layers = [
      new LineLayer<Seg>({
        id: "flights-lines",
        data: segments,
        getSourcePosition: (s): [number, number] => s.from,
        getTargetPosition: (s): [number, number] => s.to,
        getColor,
        getWidth,
        widthUnits: "pixels",
        pickable: true,
      }),
      new ScatterplotLayer<FlightDetail>({
        id: "flights-starts",
        data: flights,
        getPosition: (f): [number, number] => [
          f.start_point.coordinates[0],
          f.start_point.coordinates[1],
        ],
        getFillColor: (f): RGBA =>
          hasSel && f.flight_id !== selectedFlightId ? [60, 200, 80, 46] : [60, 200, 80, 230],
        getRadius: 3,
        radiusUnits: "pixels",
      }),
      new ScatterplotLayer<FlightDetail>({
        id: "flights-ends",
        data: flights,
        getPosition: (f): [number, number] => [
          f.end_point.coordinates[0],
          f.end_point.coordinates[1],
        ],
        getFillColor: (f): RGBA =>
          hasSel && f.flight_id !== selectedFlightId ? [220, 60, 60, 46] : [220, 60, 60, 230],
        getRadius: 3,
        radiusUnits: "pixels",
      }),
    ];
    mainLayersRef.current = layers;
    overlay.setProps({ layers });
  }, [flights, colorMode, selectedFlightId]);

  // Separate effect for the hover dot — avoids rebuilding all segments on every hover move.
  useEffect(() => {
    const overlay = deckRef.current;
    if (!overlay) return;

    const dot: [number, number][] = [];
    if (mapTooltip) {
      // Map hover: use interpolated position along the segment.
      dot.push(mapTooltip.dotPos);
    } else if (hoveredPoint && flights) {
      // Sparkline hover: snap to the nearest recorded vertex.
      const hf = flights.find((f) => f.flight_id === hoveredPoint.flightId);
      const coord = hf?.path?.coordinates[hoveredPoint.pointIdx];
      if (coord) dot.push([coord[0], coord[1]]);
    }

    overlay.setProps({
      layers: [
        ...mainLayersRef.current,
        new ScatterplotLayer<[number, number]>({
          id: "flight-hover-dot",
          data: dot,
          getPosition: (d): [number, number] => d,
          getFillColor: [255, 255, 255, 230],
          getLineColor: [110, 168, 255, 255],
          stroked: true,
          getRadius: 6,
          getLineWidth: 2,
          radiusUnits: "pixels",
          lineWidthUnits: "pixels",
        }),
      ],
    });
  }, [mapTooltip, hoveredPoint, flights]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    const url = STYLES[basemap];
    const applyStyle = (): void => {
      map.setStyle(url);
    };
    if (map.isStyleLoaded()) {
      map.setStyle(url);
    } else {
      void map.once("load", applyStyle);
    }
  }, [basemap]);

  return (
    <div style={{ position: "absolute", inset: 0 }}>
      <div ref={containerRef} style={{ position: "absolute", inset: 0 }} />
      {mapTooltip && (
        <div
          style={{
            position: "absolute",
            left: mapTooltip.x + 14,
            top: mapTooltip.y - 14,
            pointerEvents: "none",
            background: "color-mix(in oklab, var(--bg-1) 94%, transparent)",
            backdropFilter: "blur(8px)",
            WebkitBackdropFilter: "blur(8px)",
            border: "1px solid var(--line-1)",
            borderRadius: "var(--radius-1)",
            padding: "5px 8px",
            fontSize: 11,
            color: "var(--fg-1)",
            whiteSpace: "nowrap",
            zIndex: 10,
            boxShadow: "var(--shadow-1)",
            minWidth: 130,
          }}
        >
          <div style={{ display: "flex", alignItems: "baseline", gap: 6, marginBottom: 2 }}>
            <span style={{ fontWeight: 600, fontSize: 12 }}>
              {mapTooltip.callsign ?? mapTooltip.icao24}
            </span>
            {mapTooltip.callsign && (
              <span style={{ color: "var(--fg-3)", fontSize: 10 }}>{mapTooltip.icao24}</span>
            )}
          </div>
          {(mapTooltip.icaoType ?? mapTooltip.cat) && (
            <div style={{ fontSize: 10, color: "var(--fg-3)", marginBottom: 4 }}>
              {[mapTooltip.icaoType, mapTooltip.cat].filter(Boolean).join(" · ")}
            </div>
          )}
          <div style={{ borderTop: "1px solid var(--line-1)", marginBottom: 4 }} />
          <table style={{ borderCollapse: "collapse", fontSize: 11, lineHeight: 1.6 }}>
            <tbody>
              <tr>
                <td style={{ color: "var(--fg-3)", paddingRight: 8, verticalAlign: "top" }}>Alt</td>
                <td style={{ fontFamily: "JetBrains Mono, monospace", fontWeight: 500 }}>
                  {mapTooltip.altFt.toLocaleString()} ft
                </td>
              </tr>
              {mapTooltip.vs !== null && (
                <tr>
                  <td style={{ color: "var(--fg-3)", paddingRight: 8 }}>VS</td>
                  <td style={{ fontFamily: "JetBrains Mono, monospace" }}>
                    {mapTooltip.vs > 0 ? "+" : ""}{mapTooltip.vs.toLocaleString()} fpm{" "}
                    {mapTooltip.vs > 50 ? "↑" : mapTooltip.vs < -50 ? "↓" : ""}
                  </td>
                </tr>
              )}
              {mapTooltip.gs !== null && (
                <tr>
                  <td style={{ color: "var(--fg-3)", paddingRight: 8 }}>GS</td>
                  <td style={{ fontFamily: "JetBrains Mono, monospace" }}>
                    {mapTooltip.gs.toLocaleString()} kt
                  </td>
                </tr>
              )}
              {mapTooltip.ias !== null && (
                <tr>
                  <td style={{ color: "var(--fg-3)", paddingRight: 8 }}>IAS</td>
                  <td style={{ fontFamily: "JetBrains Mono, monospace" }}>
                    {mapTooltip.ias.toLocaleString()} kt
                  </td>
                </tr>
              )}
              {mapTooltip.track !== null && (
                <tr>
                  <td style={{ color: "var(--fg-3)", paddingRight: 8 }}>Hdg</td>
                  <td style={{ fontFamily: "JetBrains Mono, monospace" }}>
                    {String(Math.round(mapTooltip.track)).padStart(3, "0")}°{" "}
                    {trackToCompass(mapTooltip.track)}
                  </td>
                </tr>
              )}
              {mapTooltip.squawk !== null && (
                <tr>
                  <td style={{ color: "var(--fg-3)", paddingRight: 8 }}>Sqk</td>
                  <td style={{ fontFamily: "JetBrains Mono, monospace" }}>
                    {mapTooltip.squawk}
                  </td>
                </tr>
              )}
              {mapTooltip.ts > 0 && (
                <tr>
                  <td style={{ color: "var(--fg-3)", paddingRight: 8 }}>UTC</td>
                  <td style={{ fontFamily: "JetBrains Mono, monospace" }}>
                    {fmtUtc(mapTooltip.ts)}
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
