/**
 * Area calculations for query geometry size limiting.
 *
 * The backend enforces a hard limit based on H3 res-4 cell count; this module
 * provides a frontend approximation using enclosed area so the UI can reject
 * clearly oversized queries without an H3 dependency.
 */

/**
 * Maximum enclosed area in km² for trajectory predicates (region / always_within).
 *
 * Calibrated against the H3 res-4 GIN index flip point: Postgres stops using
 * the path_h3 GIN index at ~270 cells over dense airspace (≈ Ireland-sized area).
 * 75,000 km² corresponds to a circle of radius ~155 km, the last k where the
 * planner uses the index.
 */
export const MAX_GEOMETRY_AREA_KM2 = 75_000;

const KM_PER_DEG = 111.32;
const KM_PER_NM = 1.852;
const DEG_TO_RAD = Math.PI / 180;

/** Approximate area in km² of a circle given its radius in nautical miles. */
export function circleAreaKm2(radiusNm: number): number {
  const radiusKm = radiusNm * KM_PER_NM;
  return Math.PI * radiusKm * radiusKm;
}

/**
 * Approximate area in km² of a closed polygon using a flat-earth Shoelace formula
 * with cosine-latitude scaling on the longitude axis.
 *
 * polygon: ring of [longitude, latitude] pairs (closing point may or may not be repeated).
 */
export function polygonAreaKm2(polygon: [number, number][]): number {
  const n = polygon.length;
  if (n < 3) return 0;
  const meanLat = polygon.reduce((s, p) => s + p[1], 0) / n;
  const cosLat = Math.cos(meanLat * DEG_TO_RAD);
  let area = 0;
  for (let i = 0; i < n; i++) {
    const p1 = polygon[i];
    const p2 = polygon[(i + 1) % n];
    if (p1 === undefined || p2 === undefined) continue;
    area += p1[0] * cosLat * p2[1] - p2[0] * cosLat * p1[1];
  }
  return (Math.abs(area) / 2) * KM_PER_DEG * KM_PER_DEG;
}
