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
import { altToColor, catToColor, squawkToColor, todToColor, type RGBA } from "../../lib/colors";

import workerUrl from "maplibre-gl/dist/maplibre-gl-csp-worker?url";
setWorkerUrl(workerUrl);

type Basemap = "dark" | "light" | "sat";
type ColorMode = "alt" | "cat" | "tod" | "sqk";

// Precomputed segment for LineLayer — one per adjacent vertex pair in a path.
type Seg = {
  from: [number, number];
  to: [number, number];
  altMid: number;
  altFt: number;
  altFtTo: number;
  cat: string | null;
  squawk: string | null;
  startTs: string;
  flightId: string;
  pointIdx: number;
};

// Project cursor (lng/lat) onto segment [from, to], return t in [0, 1].
function projectOntoSegment(
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

// Return the active squawk code at unix timestamp ts, or null if none applies.
// runs must be sorted ascending by timestamp (as returned by the API).
function squawkAt(runs: [number, string][], ts: number): string | null {
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
  let bestAvgLat = -Infinity;
  let bestA: Coord = [0, 0],
    bestB: Coord = [0, 0];
  for (let i = 0; i < n; i++) {
    const a = pts[i];
    const b = pts[(i + 1) % n];
    if (!a || !b) continue;
    const avgLat = (a[1] + b[1]) / 2;
    if (avgLat > bestAvgLat) {
      bestAvgLat = avgLat;
      bestA = a;
      bestB = b;
    }
  }
  const center: Coord = [(bestA[0] + bestB[0]) / 2, bestAvgLat];
  // text-rotate is clockwise from east (horizontal); bearing is clockwise from north, so subtract 90.
  const midLat = bestAvgLat;
  const dx = (bestB[0] - bestA[0]) * Math.cos((midLat * Math.PI) / 180);
  const dy = bestB[1] - bestA[1];
  let rotation = Math.atan2(dx, dy) * (180 / Math.PI) - 90;
  // Clamp to [-90, 90] so the text is never upside-down.
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
  // Persists the main flight layers so the hover-dot effect can append without rebuilding them.
  const mainLayersRef = useRef<(LineLayer<Seg> | ScatterplotLayer<FlightDetail>)[]>([]);

  const [mapTooltip, setMapTooltip] = useState<{
    x: number;
    y: number;
    altFt: number;
    dotPos: [number, number];
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
          const cursor = info.coordinate as [number, number] | undefined;
          const t = cursor ? projectOntoSegment(seg.from, seg.to, cursor) : 0;
          const altFt = Math.round(seg.altFt + t * (seg.altFtTo - seg.altFt));
          const dotPos: [number, number] = [
            seg.from[0] + t * (seg.to[0] - seg.from[0]),
            seg.from[1] + t * (seg.to[1] - seg.from[1]),
          ];
          onHoverPointRef.current({ flightId: seg.flightId, pointIdx: seg.pointIdx });
          setMapTooltipRef.current({ x: info.x, y: info.y, altFt, dotPos });
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
        return {
          from: [c[0], c[1]],
          to: [next[0], next[1]],
          altMid: (c[2] + next[2]) / 2,
          altFt: c[2],
          altFtTo: next[2],
          cat: f.emitter_category ?? null,
          squawk: squawkAt(runs, ts),
          startTs: f.start_ts,
          flightId: f.flight_id,
          pointIdx: i,
        };
      });
    });

    const hasSel = selectedFlightId !== null;

    const getColor = (s: Seg): RGBA => {
      const base =
        colorMode === "alt"
          ? altToColor(s.altMid)
          : colorMode === "cat"
            ? catToColor(s.cat)
            : colorMode === "sqk"
              ? squawkToColor(s.squawk)
              : todToColor(s.startTs);
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
            padding: "3px 7px",
            fontSize: 11,
            color: "var(--fg-1)",
            whiteSpace: "nowrap",
            zIndex: 10,
            boxShadow: "var(--shadow-1)",
          }}
        >
          {mapTooltip.altFt.toLocaleString()} ft
        </div>
      )}
    </div>
  );
}
