import React, {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import {
  MapView,
  MapBounds,
  HoveredPoint,
  ColorMode,
} from "./components/map/MapView";

// Numeric codes from the OpenAIP API
const AIRSPACE_TYPES: Record<number, string> = {
  0: "Other",
  1: "Restricted",
  2: "Danger",
  3: "Prohibited",
  4: "CTR",
  5: "TMZ",
  6: "RMZ",
  7: "TMA",
  8: "TRA",
  9: "TSA",
  10: "FIR",
  11: "UIR",
  12: "ADIZ",
  13: "ATZ",
  14: "MATZ",
  15: "Airway",
  16: "MTR",
  17: "Alert",
  18: "Warning",
  19: "Protected",
  20: "MOA",
  21: "CTA",
  22: "ACC",
  23: "Sport",
};
const ICAO_CLASSES: Record<number, string> = {
  0: "A",
  1: "B",
  2: "C",
  3: "D",
  4: "E",
  5: "F",
  6: "G",
};

interface AltLimit {
  value: number;
  ref: "ft" | "fl";
}

interface AirspaceCandidate {
  id: string;
  name: string;
  typeCode: number;
  icaoClassCode: number | null;
  country: string;
  lowerLimit: AltLimit | null;
  upperLimit: AltLimit | null;
  polygon: [number, number][];
}

function formatAltLimit(limit: AltLimit | null): string {
  if (!limit) return "GND";
  return limit.ref === "fl"
    ? `FL${String(limit.value)}`
    : `${limit.value.toLocaleString()} ft`;
}

function airspaceSubtitle(c: AirspaceCandidate): string {
  const type = AIRSPACE_TYPES[c.typeCode] ?? `Type ${String(c.typeCode)}`;
  const cls =
    c.icaoClassCode !== null
      ? `Class ${ICAO_CLASSES[c.icaoClassCode] ?? String(c.icaoClassCode)}`
      : null;
  const typeClass = [type, cls].filter(Boolean).join(" · ");
  const altRange =
    c.lowerLimit !== null || c.upperLimit !== null
      ? `${formatAltLimit(c.lowerLimit)} – ${c.upperLimit !== null ? formatAltLimit(c.upperLimit) : "∞"}`
      : null;
  return [typeClass, altRange].filter(Boolean).join(" · ");
}

function openaipLimit(
  limit: { value: number; unit: number } | null | undefined,
): AltLimit | null {
  if (!limit) return null;
  return limit.unit === 6
    ? { value: limit.value, ref: "fl" }
    : { value: limit.value, ref: "ft" };
}
import { anyViewportFilter, collectGeometries } from "./lib/queryGeometry";
import { Topbar } from "./components/layout/Topbar";
import { Sidebar } from "./components/layout/Sidebar";
import {
  countPredicates,
  dateRangeToApiParams,
  FilterGroup,
  GlobalDateRange,
  isDateRangeValid,
  isGroupValid,
  makeId,
  QueryBuilderAddMenu,
  QueryBuilderBody,
  QueryBuilderDateRange,
  QueryBuilderFooter,
  updatePredInGroup,
  UIPredicate,
} from "./components/query/QueryBuilder";
import { ResultsPanel } from "./components/results/ResultsPanel";
import { Legend } from "./components/ui/Legend";
import { ChevronLeft, ChevronRight } from "./components/Icons";
import { compileGroup } from "./lib/compileQuery";
import {
  postQuery,
  getDataRange,
  FlightDetail,
  ApiError,
  DataRange,
} from "./lib/api";

type Basemap = "dark" | "light" | "sat";
type Theme = "dark" | "light";

const SIDEBAR_W = 340;
const SIDEBAR_MARGIN = 12;

function ToggleButton({
  side,
  collapsed,
  onToggle,
}: {
  side: "left" | "right";
  collapsed: boolean;
  onToggle: () => void;
}): React.ReactElement {
  const isLeft = side === "left";
  const expandedEdge = SIDEBAR_MARGIN + SIDEBAR_W;

  return (
    <button
      onClick={onToggle}
      aria-label={
        collapsed ? "Expand " + side + " panel" : "Collapse " + side + " panel"
      }
      style={{
        position: "absolute",
        top: "50%",
        [isLeft ? "left" : "right"]: collapsed ? SIDEBAR_MARGIN : expandedEdge,
        transform: "translateY(-50%)",
        transition:
          (isLeft ? "left" : "right") + " 240ms cubic-bezier(0.4, 0, 0.2, 1)",
        zIndex: 10,
        width: 22,
        height: 44,
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        background: "color-mix(in oklab, var(--bg-1) 94%, transparent)",
        backdropFilter: "blur(14px)",
        WebkitBackdropFilter: "blur(14px)",
        border: "1px solid var(--line-1)",
        borderRadius: isLeft
          ? "0 var(--radius-2) var(--radius-2) 0"
          : "var(--radius-2) 0 0 var(--radius-2)",
        boxShadow: "var(--shadow-2)",
        cursor: "pointer",
        color: "var(--fg-2)",
        padding: 0,
      }}
    >
      {isLeft ? (
        collapsed ? (
          <ChevronRight size={13} />
        ) : (
          <ChevronLeft size={13} />
        )
      ) : collapsed ? (
        <ChevronLeft size={13} />
      ) : (
        <ChevronRight size={13} />
      )}
    </button>
  );
}

export function App(): React.ReactElement {
  const [theme, setTheme] = useState<Theme>(() => {
    document.documentElement.dataset["theme"] = "light";
    return "light";
  });
  const [basemap, setBasemap] = useState<Basemap>("light");
  const [colorMode, setColorMode] = useState<ColorMode>("alt");
  const [airspaceOn, setAirspaceOn] = useState(true);
  const [leftCollapsed, setLeftCollapsed] = useState(false);
  const [rightCollapsed, setRightCollapsed] = useState(true);

  const [rootGroup, setRootGroup] = useState<FilterGroup>({
    id: makeId(),
    kind: "group",
    mode: "all",
    items: [],
  });
  const [globalDateRange, setGlobalDateRange] = useState<GlobalDateRange>({
    to: "",
  });
  const [pickingId, setPickingId] = useState<string | null>(null);
  const [drawingId, setDrawingId] = useState<string | null>(null);
  const [airspacePickingId, setAirspacePickingId] = useState<string | null>(
    null,
  );
  const [airspaceMenu, setAirspaceMenu] = useState<{
    x: number;
    y: number;
    predId: string;
    candidates: AirspaceCandidate[] | null; // null = loading
  } | null>(null);

  const [viewportVersion, setViewportVersion] = useState(0);
  const [lastRunVersion, setLastRunVersion] = useState<number | null>(null);
  const [lastRunGroup, setLastRunGroup] = useState<FilterGroup | null>(null);

  const [dataRange, setDataRange] = useState<DataRange | null>(null);

  const [mapBounds, setMapBounds] = useState<MapBounds | null>(null);
  const [queryFlights, setQueryFlights] = useState<FlightDetail[] | null>(null);
  const [queryCursor, setQueryCursor] = useState<string | null>(null);
  const [queryWindowFrom, setQueryWindowFrom] = useState<string | null>(null);
  const [queryLoading, setQueryLoading] = useState(false);
  const [queryError, setQueryError] = useState<string | null>(null);
  const [selectedFlightId, setSelectedFlightId] = useState<string | null>(null);
  const [hoveredPoint, setHoveredPoint] = useState<HoveredPoint | null>(null);
  const queryAbortRef = useRef<AbortController | null>(null);

  useEffect(() => {
    document.documentElement.dataset["theme"] = theme;
  }, [theme]);

  useEffect(() => {
    getDataRange()
      .then((dr) => {
        setDataRange(dr);
        if (dr.last_date) {
          setGlobalDateRange({ to: dr.last_date });
        }
      })
      .catch(() => {
        /* non-critical */
      });
  }, []);

  const handleTheme = (): void => {
    setTheme((t) => {
      const next = t === "dark" ? "light" : "dark";
      if (next === "light" && basemap === "dark") setBasemap("light");
      if (next === "dark" && basemap === "light") setBasemap("dark");
      return next;
    });
  };

  const armPicker = (predId: string): void => {
    setDrawingId(null);
    setAirspacePickingId(null);
    setAirspaceMenu(null);
    setPickingId((prev) => (prev === predId ? null : predId));
  };

  const armDraw = (predId: string): void => {
    setPickingId(null);
    setAirspacePickingId(null);
    setAirspaceMenu(null);
    setDrawingId((prev) => (prev === predId ? null : predId));
  };

  const armAirspacePicker = (predId: string): void => {
    setPickingId(null);
    setDrawingId(null);
    setAirspaceMenu(null);
    setAirspacePickingId((prev) => (prev === predId ? null : predId));
  };

  const handlePickAirspace = (
    lat: number,
    lng: number,
    x: number,
    y: number,
  ): void => {
    const predId = airspacePickingId;
    if (!predId) return;
    setAirspacePickingId(null);
    setAirspaceMenu({ x, y, predId, candidates: null });
    fetch(`/api/airspaces?pos=${lat.toFixed(6)},${lng.toFixed(6)}&dist=1`)
      .then((r) => r.json())
      .then(
        (data: {
          items: Array<{
            _id: string;
            name: string;
            type: number;
            icaoClass?: number;
            country: string;
            lowerLimit?: { value: number; unit: number };
            upperLimit?: { value: number; unit: number };
            geometry: { type: string; coordinates: number[][][] };
          }>;
        }) => {
          const candidates: AirspaceCandidate[] = data.items
            .filter((item) => item.geometry.type === "Polygon")
            .map((item) => ({
              id: item._id,
              name: item.name,
              typeCode: item.type,
              icaoClassCode:
                typeof item.icaoClass === "number" && item.icaoClass <= 6
                  ? item.icaoClass
                  : null,
              country: item.country,
              lowerLimit: openaipLimit(item.lowerLimit),
              upperLimit: openaipLimit(item.upperLimit),
              polygon: (item.geometry.coordinates[0] ?? []) as [
                number,
                number,
              ][],
            }))
            .filter((c) => c.polygon.length >= 3);
          if (candidates.length === 0) {
            setAirspaceMenu(null);
          } else if (candidates.length === 1) {
            const only = candidates[0];
            setAirspaceMenu(null);
            if (only) applyAirspace(predId, only);
          } else {
            setAirspaceMenu((m) => (m ? { ...m, candidates } : null));
          }
        },
      )
      .catch(() => {
        setAirspaceMenu(null);
      });
  };

  const applyAirspace = (predId: string, c: AirspaceCandidate): void => {
    const airspaceLabel = airspaceSubtitle(c) || null;
    setRootGroup((g) =>
      updatePredInGroup(g, predId, (p: UIPredicate) => {
        if (
          p.kind === "endpoint_within" ||
          p.kind === "region" ||
          p.kind === "always_within"
        ) {
          const base = {
            ...p,
            shape: "airspace" as const,
            polygon: c.polygon,
            airspaceName: c.name,
            airspaceLabel,
          };
          if (p.kind === "region" || p.kind === "always_within") {
            return {
              ...base,
              altMin: c.lowerLimit?.value ?? null,
              altMinRef: c.lowerLimit?.ref ?? "ft",
              altMax: c.upperLimit?.value ?? null,
              altMaxRef: c.upperLimit?.ref ?? "ft",
            };
          }
          return base;
        }
        return p;
      }),
    );
    setAirspaceMenu(null);
  };

  const handlePickPoint = (lat: number, lng: number): void => {
    if (!pickingId) return;
    const id = pickingId;
    setRootGroup((g) =>
      updatePredInGroup(g, id, (p: UIPredicate) => {
        if (
          p.kind === "endpoint_within" ||
          p.kind === "region" ||
          p.kind === "always_within"
        ) {
          return { ...p, lat, lng };
        }
        return p;
      }),
    );
    setPickingId(null);
  };

  const handleDrawComplete = (points: [number, number][]): void => {
    if (!drawingId) return;
    const id = drawingId;
    setRootGroup((g) =>
      updatePredInGroup(g, id, (p: UIPredicate) => {
        if (
          p.kind === "endpoint_within" ||
          p.kind === "region" ||
          p.kind === "always_within"
        ) {
          return { ...p, polygon: points };
        }
        return p;
      }),
    );
    setDrawingId(null);
  };

  const handleRun = useCallback((): void => {
    if (!isDateRangeValid(globalDateRange)) return;
    setLastRunVersion(viewportVersion);
    setLastRunGroup(rootGroup);
    queryAbortRef.current?.abort();
    const ctrl = new AbortController();
    queryAbortRef.current = ctrl;

    const match = compileGroup(rootGroup, mapBounds);
    const { endDate, startFrom } = dateRangeToApiParams(globalDateRange);
    setQueryLoading(true);
    setQueryError(null);
    setQueryFlights(null);
    setQueryCursor(null);
    setQueryWindowFrom(null);
    setSelectedFlightId(null);
    setHoveredPoint(null);
    setRightCollapsed(false);

    postQuery(match, { endDate, startFrom, signal: ctrl.signal })
      .then((res) => {
        setQueryFlights(res.flights);
        setQueryCursor(res.cursor);
        setQueryWindowFrom(res.window_from);
      })
      .catch((err: unknown) => {
        if (err instanceof Error && err.name === "AbortError") return;
        setQueryError(err instanceof ApiError ? err.message : "Query failed");
      })
      .finally(() => {
        setQueryLoading(false);
      });
  }, [rootGroup, mapBounds, viewportVersion, globalDateRange]);

  const handleLoadMore = useCallback((): void => {
    if (!queryCursor || queryLoading) return;
    queryAbortRef.current?.abort();
    const ctrl = new AbortController();
    queryAbortRef.current = ctrl;

    const match = compileGroup(rootGroup, mapBounds);
    const { endDate, startFrom } = dateRangeToApiParams(globalDateRange);

    setQueryLoading(true);
    setQueryError(null);

    postQuery(match, {
      endDate,
      startFrom,
      cursor: queryCursor,
      signal: ctrl.signal,
    })
      .then((res) => {
        setQueryFlights((prev) => [...(prev ?? []), ...res.flights]);
        setQueryCursor(res.cursor);
        setQueryWindowFrom(res.window_from);
      })
      .catch((err: unknown) => {
        if (err instanceof Error && err.name === "AbortError") return;
        setQueryError(err instanceof ApiError ? err.message : "Query failed");
      })
      .finally(() => {
        setQueryLoading(false);
      });
  }, [rootGroup, mapBounds, queryCursor, queryLoading, globalDateRange]);

  const handleMoveEnd = useCallback((bounds: MapBounds): void => {
    setMapBounds(bounds);
    setViewportVersion((v) => v + 1);
  }, []);

  const mapGeometries = useMemo(
    () => collectGeometries(rootGroup),
    [rootGroup],
  );
  const hasViewport = anyViewportFilter(rootGroup);
  const predCount = countPredicates(rootGroup);
  const queryStructureChanged =
    lastRunGroup !== null && rootGroup !== lastRunGroup;
  const viewportChanged =
    hasViewport &&
    lastRunVersion !== null &&
    viewportVersion !== lastRunVersion;
  const dateRangeOk = isDateRangeValid(globalDateRange);
  // Cursor is always set by the server when there may be more data (both intra-window
  // truncation and exhausted-window sentinel).  Only suppress the button once the
  // window_from has scrolled past the beginning of the available data.
  const hasMore =
    queryCursor !== null &&
    (queryWindowFrom === null ||
      dataRange?.first_date == null ||
      new Date(queryWindowFrom) >
        new Date(dataRange.first_date + "T00:00:00Z"));
  const showRerunChip =
    dateRangeOk &&
    isGroupValid(rootGroup) &&
    (queryStructureChanged || viewportChanged);
  const filterMeta =
    predCount === 0
      ? "no filters"
      : String(predCount) + " filter" + (predCount !== 1 ? "s" : "");

  return (
    <div
      style={{
        position: "relative",
        width: "100%",
        height: "100%",
        overflow: "hidden",
      }}
    >
      <MapView
        basemap={basemap}
        chartsOn={airspaceOn}
        pickingActive={pickingId !== null}
        airspacePickingActive={airspacePickingId !== null}
        onPickAirspace={handlePickAirspace}
        drawingActive={drawingId !== null}
        onPickPoint={handlePickPoint}
        onDrawComplete={handleDrawComplete}
        geometries={mapGeometries}
        onMoveEnd={handleMoveEnd}
        flights={queryFlights}
        colorMode={colorMode}
        selectedFlightId={selectedFlightId}
        onSelectFlight={setSelectedFlightId}
        hoveredPoint={hoveredPoint}
        onHoverPoint={setHoveredPoint}
      />

      {showRerunChip && (
        <button
          onClick={handleRun}
          style={{
            position: "absolute",
            bottom: 48,
            left: "50%",
            transform: "translateX(-50%)",
            zIndex: 10,
            padding: "7px 18px",
            borderRadius: 999,
            background: "color-mix(in oklab, var(--bg-1) 94%, transparent)",
            backdropFilter: "blur(14px)",
            WebkitBackdropFilter: "blur(14px)",
            border: "1px solid var(--line-1)",
            boxShadow: "var(--shadow-2)",
            cursor: "pointer",
            color: "var(--fg-1)",
            fontSize: 13,
            fontWeight: 600,
            whiteSpace: "nowrap",
          }}
        >
          ↺ Rerun query
        </button>
      )}

      <Topbar
        basemap={basemap}
        onBasemap={setBasemap}
        colorMode={colorMode}
        onColorMode={setColorMode}
        airspaceOn={airspaceOn}
        onToggleAirspace={() => {
          setAirspaceOn((v) => !v);
        }}
        theme={theme}
        onTheme={handleTheme}
      />

      <Sidebar
        side="left"
        collapsed={leftCollapsed}
        title="Query Builder"
        meta={filterMeta}
        toolbar={
          <QueryBuilderAddMenu
            rootGroup={rootGroup}
            onGroupChange={setRootGroup}
          />
        }
        footer={
          <QueryBuilderFooter
            rootGroup={rootGroup}
            dateRangeValid={dateRangeOk}
            onRun={handleRun}
          />
        }
      >
        <QueryBuilderDateRange
          range={globalDateRange}
          onChange={setGlobalDateRange}
          dataRange={dataRange}
        />
        <QueryBuilderBody
          rootGroup={rootGroup}
          onGroupChange={setRootGroup}
          onArmPicker={armPicker}
          pickingId={pickingId}
          onArmDraw={armDraw}
          drawingId={drawingId}
          onArmAirspacePicker={armAirspacePicker}
          airspacePickingId={airspacePickingId}
          dateRange={dataRange}
          globalDateRange={globalDateRange}
        />
      </Sidebar>
      <ToggleButton
        side="left"
        collapsed={leftCollapsed}
        onToggle={() => {
          setLeftCollapsed((v) => !v);
        }}
      />

      <Sidebar
        side="right"
        collapsed={rightCollapsed}
        title="Results"
        meta={
          queryFlights === null
            ? "—"
            : String(queryFlights.length) +
              (hasMore ? "+" : "") +
              " flight" +
              (queryFlights.length !== 1 ? "s" : "")
        }
      >
        <ResultsPanel
          flights={queryFlights}
          loading={queryLoading}
          error={queryError}
          hasMore={hasMore}
          onLoadMore={handleLoadMore}
          selectedFlightId={selectedFlightId}
          onSelectFlight={setSelectedFlightId}
          hoveredPoint={hoveredPoint}
          onHoverPoint={setHoveredPoint}
          windowFrom={queryWindowFrom}
          queryEndDate={globalDateRange.to || null}
        />
      </Sidebar>
      <ToggleButton
        side="right"
        collapsed={rightCollapsed}
        onToggle={() => {
          setRightCollapsed((v) => !v);
        }}
      />

      <Legend colorMode={colorMode} />

      {airspaceMenu && (
        <AirspacePickerMenu
          x={airspaceMenu.x}
          y={airspaceMenu.y}
          candidates={airspaceMenu.candidates}
          onSelect={(c) => {
            applyAirspace(airspaceMenu.predId, c);
          }}
          onDismiss={() => {
            setAirspaceMenu(null);
          }}
        />
      )}
    </div>
  );
}

function AirspaceShapePreview({
  polygon,
}: {
  polygon: [number, number][];
}): React.ReactElement {
  const SIZE = 48;
  const PAD = 3;
  const inner = SIZE - PAD * 2;
  const lngs = polygon.map(([lng]) => lng);
  const lats = polygon.map(([, lat]) => lat);
  const minLng = Math.min(...lngs),
    maxLng = Math.max(...lngs);
  const minLat = Math.min(...lats),
    maxLat = Math.max(...lats);
  const dLng = maxLng - minLng || 0.001;
  const dLat = maxLat - minLat || 0.001;
  const scale = inner / Math.max(dLng, dLat);
  const offX = (SIZE - dLng * scale) / 2;
  const pts = polygon.map(([lng, lat]) => [
    (lng - minLng) * scale + offX,
    (SIZE + dLat * scale) / 2 - (lat - minLat) * scale,
  ]);
  const d =
    pts
      .map(
        ([x, y], i) =>
          `${i === 0 ? "M" : "L"}${(x ?? 0).toFixed(1)},${(y ?? 0).toFixed(1)}`,
      )
      .join(" ") + " Z";
  return (
    <svg width={SIZE} height={SIZE} style={{ display: "block", flexShrink: 0 }}>
      <path
        d={d}
        fill="rgba(60,100,220,0.18)"
        stroke="#3c64dc"
        strokeWidth="1.2"
      />
    </svg>
  );
}

function AirspacePickerMenu({
  x,
  y,
  candidates,
  onSelect,
  onDismiss,
}: {
  x: number;
  y: number;
  candidates: AirspaceCandidate[] | null;
  onSelect: (c: AirspaceCandidate) => void;
  onDismiss: () => void;
}): React.ReactElement {
  const ref = React.useRef<HTMLDivElement>(null);
  React.useEffect(() => {
    const handler = (e: MouseEvent): void => {
      if (ref.current && !ref.current.contains(e.target as Node)) onDismiss();
    };
    document.addEventListener("mousedown", handler);
    return (): void => {
      document.removeEventListener("mousedown", handler);
    };
  }, [onDismiss]);

  return (
    <div
      ref={ref}
      style={{
        position: "absolute",
        left: x + 8,
        top: y + 8,
        zIndex: 20,
        background: "color-mix(in oklab, var(--bg-1) 96%, transparent)",
        backdropFilter: "blur(12px)",
        WebkitBackdropFilter: "blur(12px)",
        border: "1px solid var(--line-1)",
        borderRadius: "var(--radius-2)",
        boxShadow: "var(--shadow-2)",
        minWidth: 240,
        maxWidth: 320,
        overflow: "hidden",
      }}
    >
      <div
        style={{
          padding: "6px 10px 4px",
          fontSize: 10.5,
          color: "var(--fg-3)",
          fontWeight: 500,
          textTransform: "uppercase",
          letterSpacing: "0.05em",
        }}
      >
        {candidates === null ? "Searching…" : "Select airspace"}
      </div>
      {candidates === null && (
        <div
          style={{
            padding: "8px 10px 10px",
            fontSize: 12,
            color: "var(--fg-3)",
          }}
        >
          Looking up airspaces…
        </div>
      )}
      {candidates?.map((c) => (
        <button
          key={c.id}
          onClick={() => {
            onSelect(c);
          }}
          style={{
            display: "flex",
            alignItems: "center",
            gap: 10,
            width: "100%",
            padding: "6px 10px",
            background: "none",
            border: "none",
            borderTop: "1px solid var(--line-0)",
            cursor: "pointer",
            textAlign: "left",
            color: "var(--fg-1)",
          }}
          onMouseEnter={(e) => {
            e.currentTarget.style.background = "var(--bg-2)";
          }}
          onMouseLeave={(e) => {
            e.currentTarget.style.background = "none";
          }}
        >
          <AirspaceShapePreview polygon={c.polygon} />
          <div style={{ minWidth: 0 }}>
            <div
              style={{
                fontSize: 12,
                fontWeight: 600,
                whiteSpace: "nowrap",
                overflow: "hidden",
                textOverflow: "ellipsis",
              }}
            >
              {c.name}
            </div>
            <div
              style={{
                fontSize: 10.5,
                color: "var(--fg-3)",
                marginTop: 1,
                whiteSpace: "nowrap",
                overflow: "hidden",
                textOverflow: "ellipsis",
              }}
            >
              {airspaceSubtitle(c)}
            </div>
          </div>
        </button>
      ))}
    </div>
  );
}
