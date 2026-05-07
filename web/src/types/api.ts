export interface GeoJSONPointZ {
  type: "Point";
  coordinates: [number, number, number]; // [lon, lat, alt_ft]
}

export interface GeoJSONLineStringZ {
  type: "LineString";
  coordinates: Array<[number, number, number]>; // [lon, lat, alt_ft]
}

export interface FlightDetail {
  flight_id: string; // "icao24:YYYY-MM-DDTHH:MM:SSZ"
  icao24: string;
  callsign: string | null;
  icao_type: string | null;
  emitter_category: string | null;
  start_ts: string; // ISO 8601
  end_ts: string;
  start_point: GeoJSONPointZ;
  end_point: GeoJSONPointZ;
  point_count: number;
  path: GeoJSONLineStringZ | null;
  timestamps: number[] | null; // unix seconds, one per path vertex
  path_tracks: number[] | null; // degrees, one per path vertex
  squawk_runs: Array<[number, string]> | null; // [unix_ts, squawk]
  raw_point_count: number;
  ingest_batch_date: string; // "YYYY-MM-DD"
}

export interface QueryResponse {
  flights: FlightDetail[];
  cursor: string | null;
}

// ---- Predicate DSL types (mirrors server query/models.py) ----

export type GeometryCircle = {
  type: "Circle";
  coordinates: [number, number]; // [lon, lat]
  radius: number; // metres
};

export type GeometryPolygon = {
  type: "Polygon";
  coordinates: Array<Array<[number, number]>>;
};

export type TimeRange = {
  type: "TimeRange";
  from: string; // ISO 8601
  to: string;
};

export type Predicate =
  | { and: Predicate[] }
  | { or: Predicate[] }
  | { not: Predicate }
  | { icao_type: string[] }
  | { emitter_category: string[] }
  | { callsign_matches: string }
  | { starts_within: GeometryCircle | GeometryPolygon }
  | { ends_within: GeometryCircle | GeometryPolygon }
  | { trajectory_intersects: { geometry: GeometryPolygon; altitude_min_ft?: number; altitude_max_ft?: number } }
  | { starts_within: TimeRange }
  | { duration: { min_s?: number; max_s?: number } };

export interface QueryRequest {
  match?: Predicate;
  cursor?: string;
  limit?: number;
  include_path?: boolean;
}
