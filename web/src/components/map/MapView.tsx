import { Map as MaplibreMap, setWorkerUrl, StyleSpecification } from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import { useEffect, useRef } from "react";

// Use the CSP build's separate worker so Vite can serve it as a static asset
// rather than trying to inline the blob URL (which breaks under the optimizer).
import workerUrl from "maplibre-gl/dist/maplibre-gl-csp-worker?url";
setWorkerUrl(workerUrl);

type Basemap = "dark" | "light" | "sat";

const SAT_STYLE: StyleSpecification = {
  version: 8,
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

interface MapViewProps {
  basemap: Basemap;
}

export function MapView({ basemap }: MapViewProps): React.ReactElement {
  const containerRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<MaplibreMap | null>(null);

  useEffect(() => {
    if (!containerRef.current || mapRef.current) return;

    mapRef.current = new MaplibreMap({
      container: containerRef.current,
      style: STYLES[basemap],
      center: [-2.0, 54.5],
      zoom: 5,
      attributionControl: { compact: true },
    });

    return () => {
      mapRef.current?.remove();
      mapRef.current = null;
    };
    // basemap excluded — style swaps handled in the effect below
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    const url = STYLES[basemap];
    if (map.isStyleLoaded()) {
      map.setStyle(url);
    } else {
      map.once("load", () => map.setStyle(url));
    }
  }, [basemap]);

  return <div ref={containerRef} style={{ position: "absolute", inset: 0 }} />;
}
