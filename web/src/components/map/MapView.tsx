import { GeoJSONSource, Map as MaplibreMap, MapMouseEvent, setWorkerUrl, StyleSpecification } from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import { useEffect, useRef } from "react";

import workerUrl from "maplibre-gl/dist/maplibre-gl-csp-worker?url";
setWorkerUrl(workerUrl);

type Basemap = "dark" | "light" | "sat";

const SAT_STYLE: StyleSpecification = {
  version: 8,
  glyphs: "https://demotiles.maplibre.org/font/{fontstack}/{range}.pbf",
  sources: {
    "esri-sat": {
      type: "raster",
      tiles: ["https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}"],
      tileSize: 256,
      attribution: "Tiles &copy; Esri &mdash; Esri, DigitalGlobe, GeoEye, USDA, USGS, and the GIS User Community",
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
  | { type: "Feature"; properties: Record<string, string>; geometry: { type: "Polygon"; coordinates: Coord[][] } }
  | { type: "Feature"; properties: Record<string, never>; geometry: { type: "Point"; coordinates: Coord } }
  | { type: "Feature"; properties: Record<string, never>; geometry: { type: "LineString"; coordinates: Coord[] } }
  | { type: "Feature"; properties: { label: string; color: string; rotation: number }; geometry: { type: "Point"; coordinates: Coord } };
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
  let bestA: Coord = [0, 0], bestB: Coord = [0, 0];
  for (let i = 0; i < n; i++) {
    const a = pts[i]!;
    const b = pts[(i + 1) % n]!;
    const avgLat = (a[1] + b[1]) / 2;
    if (avgLat > bestAvgLat) { bestAvgLat = avgLat; bestA = a; bestB = b; }
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
      return [{ type: "Feature", properties: { color: g.color }, geometry: { type: "Polygon", coordinates: [ring] } }];
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
      return [{ type: "Feature", properties: { label: g.label, color: g.color, rotation }, geometry: { type: "Point", coordinates: center } }];
    }),
  };
}

function buildDraftFC(pts: Coord[]): GeoFC {
  return {
    type: "FeatureCollection",
    features: [
      ...pts.map((p): GeoFeat => ({ type: "Feature", properties: {}, geometry: { type: "Point", coordinates: p } })),
      ...(pts.length >= 2
        ? [{ type: "Feature" as const, properties: {} as Record<string, never>, geometry: { type: "LineString" as const, coordinates: pts } }]
        : []),
    ],
  };
}

function setSource(src: GeoJSONSource | undefined, data: GeoFC): void {
  src?.setData(data as Parameters<GeoJSONSource["setData"]>[0]);
}

function initOverlays(map: MaplibreMap, geoms: MapGeometry[]): void {
  map.addSource("filter-geoms", { type: "geojson", data: buildFillFC(geoms) as Parameters<GeoJSONSource["setData"]>[0] });
  map.addSource("filter-labels", { type: "geojson", data: buildLabelFC(geoms) as Parameters<GeoJSONSource["setData"]>[0] });
  map.addSource("draft", { type: "geojson", data: EMPTY_FC as Parameters<GeoJSONSource["setData"]>[0] });

  map.addLayer({ id: "filter-fill", type: "fill", source: "filter-geoms", paint: { "fill-color": ["get", "color"], "fill-opacity": 0.15 } });
  map.addLayer({ id: "filter-line", type: "line", source: "filter-geoms", paint: { "line-color": ["get", "color"], "line-width": 2 } });
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
    paint: { "circle-radius": 4, "circle-color": "#ffffff", "circle-stroke-width": 1.5, "circle-stroke-color": "#000000" },
  });
}

// [west, south, east, north] in degrees
export type MapBounds = [number, number, number, number];

interface MapViewProps {
  basemap: Basemap;
  pickingActive: boolean;
  drawingActive: boolean;
  onPickPoint: (lat: number, lng: number) => void;
  onDrawComplete: (points: [number, number][]) => void;
  geometries: MapGeometry[];
  onMoveEnd?: (bounds: MapBounds) => void;
}

export function MapView({
  basemap,
  pickingActive,
  drawingActive,
  onPickPoint,
  onDrawComplete,
  geometries,
  onMoveEnd,
}: MapViewProps): React.ReactElement {
  const containerRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<MaplibreMap | null>(null);
  const pickingRef = useRef(pickingActive);
  const drawingRef = useRef(drawingActive);
  const drawPointsRef = useRef<Coord[]>([]);
  const onPickRef = useRef(onPickPoint);
  const onDrawRef = useRef(onDrawComplete);
  const geometriesRef = useRef(geometries);
  const onMoveEndRef = useRef(onMoveEnd);

  pickingRef.current = pickingActive;
  drawingRef.current = drawingActive;
  onPickRef.current = onPickPoint;
  onDrawRef.current = onDrawComplete;
  geometriesRef.current = geometries;
  onMoveEndRef.current = onMoveEnd;

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !map.getSource("filter-geoms")) return;
    setSource(map.getSource("filter-geoms") as GeoJSONSource | undefined, buildFillFC(geometries));
    setSource(map.getSource("filter-labels") as GeoJSONSource | undefined, buildLabelFC(geometries));
  }, [geometries]);

  useEffect(() => {
    if (!drawingActive) {
      drawPointsRef.current = [];
      setSource(mapRef.current?.getSource("draft") as GeoJSONSource | undefined, EMPTY_FC);
    }
  }, [drawingActive]);

  useEffect(() => {
    const canvas = mapRef.current?.getCanvas();
    if (canvas) {
      canvas.style.cursor = pickingActive || drawingActive ? "crosshair" : "";
    }
  }, [pickingActive, drawingActive]);

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
      if (pickingRef.current) {
        onPickRef.current(lat, lng);
        return;
      }
      if (drawingRef.current) {
        const pts: Coord[] = [...drawPointsRef.current, [lng, lat]];
        drawPointsRef.current = pts;
        setSource(map.getSource("draft") as GeoJSONSource | undefined, buildDraftFC(pts));
      }
    };

    const onDblClick = (e: MapMouseEvent & { preventDefault: () => void }): void => {
      if (!drawingRef.current) return;
      e.preventDefault();
      const { lat, lng } = e.lngLat;
      const pts: Coord[] = [...drawPointsRef.current, [lng, lat]];
      drawPointsRef.current = [];
      setSource(map.getSource("draft") as GeoJSONSource | undefined, EMPTY_FC);
      if (pts.length >= 3) onDrawRef.current(pts);
    };

    const getBounds = (): MapBounds => {
      const b = map.getBounds().toArray() as [[number, number], [number, number]];
      return [b[0][0], b[0][1], b[1][0], b[1][1]];
    };

    const onMoveEndHandler = (): void => { onMoveEndRef.current?.(getBounds()); };

    const setupOverlays = (): void => {
      if (!map.getSource("filter-geoms")) {
        initOverlays(map, geometriesRef.current);
      }
    };

    const onLoadHandler = (): void => { onMoveEndRef.current?.(getBounds()); };

    if (map.isStyleLoaded()) { setupOverlays(); onLoadHandler(); }
    map.on("style.load", () => { setupOverlays(); onLoadHandler(); });
    map.on("click", onClick);
    map.on("dblclick", onDblClick);
    map.on("moveend", onMoveEndHandler);
    mapRef.current = map;

    return (): void => {
      map.off("click", onClick);
      map.off("dblclick", onDblClick);
      map.off("moveend", onMoveEndHandler);
      map.remove();
      mapRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    const url = STYLES[basemap];
    const applyStyle = (): void => { map.setStyle(url); };
    if (map.isStyleLoaded()) {
      map.setStyle(url);
    } else {
      void map.once("load", applyStyle);
    }
  }, [basemap]);

  return <div ref={containerRef} style={{ position: "absolute", inset: 0 }} />;
}
