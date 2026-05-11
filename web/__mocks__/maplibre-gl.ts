import { vi } from "vitest";

const mockMap = {
  on: vi.fn().mockReturnThis(),
  once: vi.fn().mockReturnThis(),
  off: vi.fn(),
  remove: vi.fn(),
  addSource: vi.fn(),
  getSource: vi.fn(() => null),
  addLayer: vi.fn(),
  getLayer: vi.fn(() => null),
  isStyleLoaded: vi.fn(() => false),
  setLayoutProperty: vi.fn(),
  setPaintProperty: vi.fn(),
  getCanvas: vi.fn(() => ({ style: {} })),
  getCenter: vi.fn(() => ({ lng: 0, lat: 0 })),
  getZoom: vi.fn(() => 5),
  getBounds: vi.fn(() => ({ toArray: vi.fn(() => [[-180, -90], [180, 90]]) })),
  project: vi.fn(() => ({ x: 0, y: 0 })),
  unproject: vi.fn(() => ({ lng: 0, lat: 0 })),
  fitBounds: vi.fn(),
  setCenter: vi.fn(),
};

export const Map = vi.fn(() => mockMap);
export const setWorkerUrl = vi.fn();
export const GeoJSONSource = vi.fn();
export const NavigationControl = vi.fn();
export const GeolocateControl = vi.fn();
export const ScaleControl = vi.fn();

export default { Map, setWorkerUrl, GeoJSONSource, NavigationControl, GeolocateControl, ScaleControl };
