import { FilterGroup } from "../components/query/QueryBuilder";

export interface MapGeometry {
  id: string;
  label: string;
  color: string;
  kind: "circle" | "polygon";
  polygon: [number, number][] | null;
  lat: number | null;
  lng: number | null;
  radiusNm: number;
}

const PALETTE = ["#3b82f6", "#22c55e", "#f59e0b", "#8b5cf6", "#ef4444", "#ec4899"];

export function collectGeometries(group: FilterGroup): MapGeometry[] {
  const result: MapGeometry[] = [];
  const counts: Record<string, number> = {};
  function walk(g: FilterGroup): void {
    for (const item of g.items) {
      if (item.kind === "group") {
        walk(item);
      } else if (item.kind === "starts_within" || item.kind === "ends_within" || item.kind === "region") {
        if (item.shape === "viewport" || item.shape === "none") continue;
        const color = PALETTE[result.length % PALETTE.length] ?? PALETTE[0] ?? "#3b82f6";
        const baseName =
          item.kind === "starts_within" ? "Starts Within" :
          item.kind === "ends_within" ? "Ends Within" :
          "Within";
        counts[baseName] = (counts[baseName] ?? 0) + 1;
        const label = `${baseName} ${counts[baseName]}`;
        result.push({
          id: item.id,
          label,
          color,
          kind: item.shape as "circle" | "polygon",
          polygon: item.polygon,
          lat: item.lat,
          lng: item.lng,
          radiusNm: item.radiusNm,
        });
      }
    }
  }
  walk(group);
  return result;
}

export function anyViewportFilter(group: FilterGroup): boolean {
  return group.items.some((item) => {
    if (item.kind === "group") return anyViewportFilter(item);
    if (item.kind === "starts_within" || item.kind === "ends_within" || item.kind === "region") {
      return item.shape === "viewport";
    }
    return false;
  });
}
