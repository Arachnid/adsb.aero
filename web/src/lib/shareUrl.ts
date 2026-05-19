/**
 * Encode and decode the app state (filter group + date range + map view) as a
 * URL-safe base64 JSON fragment suitable for use as window.location.hash.
 *
 * IDs are stripped on encode and regenerated on decode to keep URLs short.
 * A version tag ("v") guards against silent misparse if the schema changes.
 */

import type {
  FilterGroup,
  GlobalDateRange,
  QueryItem,
} from "../components/query/QueryBuilder";
import { makeId } from "../components/query/QueryBuilder";
import type { MapViewState } from "../components/map/MapView";

const CURRENT_VERSION = 2;

// ── Encode ──────────────────────────────────────────────────────────────────

function omitId<T extends { id: string }>(obj: T): Omit<T, "id"> {
  // eslint-disable-next-line @typescript-eslint/no-unused-vars
  const { id: _, ...rest } = obj;
  return rest;
}

const round5 = (n: number): number => Math.round(n * 1e5) / 1e5;

function compactPolygon(
  poly: [number, number][] | null,
): [number, number][] | null {
  if (poly === null) return null;
  return poly.map(([lng, lat]) => [round5(lng), round5(lat)]);
}

function stripIds(item: QueryItem): unknown {
  if (item.kind === "group") {
    return { ...omitId(item), items: item.items.map(stripIds) };
  }
  const stripped = omitId(item) as Record<string, unknown>;
  if ("polygon" in stripped)
    stripped["polygon"] = compactPolygon(
      stripped["polygon"] as [number, number][] | null,
    );
  return stripped;
}

export function encodeShareUrl(
  rootGroup: FilterGroup,
  dateRange: GlobalDateRange,
  mapView: MapViewState | null,
): string {
  const payload = {
    v: CURRENT_VERSION,
    g: stripIds(rootGroup),
    d: dateRange,
    ...(mapView !== null ? { m: mapView } : {}),
  };
  const json = JSON.stringify(payload);
  const b64 = btoa(json);
  return "#" + b64;
}

// ── Decode ───────────────────────────────────────────────────────────────────

function rehydrateIds(item: unknown): QueryItem {
  if (typeof item !== "object" || item === null)
    throw new Error("invalid item");
  const obj = item as Record<string, unknown>;
  if (obj["kind"] === "group") {
    const raw = obj as { kind: "group"; mode: unknown; items?: unknown[] };
    return {
      id: makeId(),
      kind: "group",
      mode: raw.mode as FilterGroup["mode"],
      items: (raw.items ?? ([] as unknown[])).map(rehydrateIds),
    };
  }
  return { id: makeId(), ...(obj as object) } as QueryItem;
}

interface SharePayload {
  v: number;
  g: unknown;
  d: GlobalDateRange;
  m?: MapViewState;
}

export interface DecodedShare {
  rootGroup: FilterGroup;
  dateRange: GlobalDateRange;
  mapView: MapViewState | null;
}

export function decodeShareUrl(hash: string): DecodedShare | null {
  try {
    const b64 = hash.startsWith("#") ? hash.slice(1) : hash;
    if (!b64) return null;
    const json = atob(b64);
    const payload = JSON.parse(json) as SharePayload;
    if (payload.v !== CURRENT_VERSION) return null;
    const rootGroup = rehydrateIds(payload.g) as FilterGroup;
    if ((rootGroup as { kind: unknown }).kind !== "group") return null;
    return {
      rootGroup,
      dateRange: payload.d,
      mapView: payload.m ?? null,
    };
  } catch {
    return null;
  }
}
