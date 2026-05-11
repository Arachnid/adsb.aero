import { useEffect, useMemo, useState } from "react";
import { MapView } from "./components/map/MapView";
import { anyViewportFilter, collectGeometries, MapGeometry } from "./lib/queryGeometry";
import { Topbar } from "./components/layout/Topbar";
import { Sidebar } from "./components/layout/Sidebar";
import {
  countPredicates,
  FilterGroup,
  makeId,
  QueryBuilderAddMenu,
  QueryBuilderBody,
  QueryBuilderFooter,
  updatePredInGroup,
  UIPredicate,
} from "./components/query/QueryBuilder";
import { ResultsPanel } from "./components/results/ResultsPanel";
import { Legend } from "./components/ui/Legend";
import { ChevronLeft, ChevronRight } from "./components/Icons";

type Basemap = "dark" | "light" | "sat";
type ColorMode = "alt" | "cat" | "tod";
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
      aria-label={collapsed ? "Expand " + side + " panel" : "Collapse " + side + " panel"}
      style={{
        position: "absolute",
        top: "50%",
        [isLeft ? "left" : "right"]: collapsed ? SIDEBAR_MARGIN : expandedEdge,
        transform: "translateY(-50%)",
        transition: (isLeft ? "left" : "right") + " 240ms cubic-bezier(0.4, 0, 0.2, 1)",
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
        borderRadius: isLeft ? "0 var(--radius-2) var(--radius-2) 0" : "var(--radius-2) 0 0 var(--radius-2)",
        boxShadow: "var(--shadow-2)",
        cursor: "pointer",
        color: "var(--fg-2)",
        padding: 0,
      }}
    >
      {isLeft
        ? collapsed ? <ChevronRight size={13} /> : <ChevronLeft size={13} />
        : collapsed ? <ChevronLeft size={13} /> : <ChevronRight size={13} />}
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
  const [pickingId, setPickingId] = useState<string | null>(null);
  const [drawingId, setDrawingId] = useState<string | null>(null);

  const [viewportVersion, setViewportVersion] = useState(0);
  const [lastRunVersion, setLastRunVersion] = useState<number | null>(null);

  useEffect(() => {
    document.documentElement.dataset["theme"] = theme;
  }, [theme]);

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
    setPickingId((prev) => (prev === predId ? null : predId));
  };

  const armDraw = (predId: string): void => {
    setPickingId(null);
    setDrawingId((prev) => (prev === predId ? null : predId));
  };

  const handlePickPoint = (lat: number, lng: number): void => {
    if (!pickingId) return;
    const id = pickingId;
    setRootGroup((g) =>
      updatePredInGroup(g, id, (p: UIPredicate) => {
        if (p.kind === "starts_within" || p.kind === "ends_within" || p.kind === "region") {
          return { ...p, lat, lng };
        }
        return p;
      })
    );
    setPickingId(null);
  };

  const handleDrawComplete = (points: [number, number][]): void => {
    if (!drawingId) return;
    const id = drawingId;
    setRootGroup((g) =>
      updatePredInGroup(g, id, (p: UIPredicate) => {
        if (p.kind === "starts_within" || p.kind === "ends_within" || p.kind === "region") {
          return { ...p, polygon: points };
        }
        return p;
      })
    );
    setDrawingId(null);
  };

  const handleRun = (): void => {
    setLastRunVersion(viewportVersion);
    /* TODO: execute query */
  };

  const handleMoveEnd = (): void => {
    setViewportVersion((v) => v + 1);
  };

  const mapGeometries = useMemo(() => collectGeometries(rootGroup), [rootGroup]);
  const hasViewport = anyViewportFilter(rootGroup);
  const showRerunChip = hasViewport && lastRunVersion !== null && viewportVersion !== lastRunVersion;

  const predCount = countPredicates(rootGroup);
  const filterMeta = predCount === 0
    ? "no filters"
    : String(predCount) + " filter" + (predCount !== 1 ? "s" : "");

  return (
    <div style={{ position: "relative", width: "100%", height: "100%", overflow: "hidden" }}>
      <MapView
        basemap={basemap}
        pickingActive={pickingId !== null}
        drawingActive={drawingId !== null}
        onPickPoint={handlePickPoint}
        onDrawComplete={handleDrawComplete}
        geometries={mapGeometries}
        onMoveEnd={handleMoveEnd}
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
        onToggleAirspace={() => { setAirspaceOn((v) => !v); }}
        theme={theme}
        onTheme={handleTheme}
      />

      <Sidebar
        side="left"
        collapsed={leftCollapsed}
        title="Query Builder"
        meta={filterMeta}
        toolbar={<QueryBuilderAddMenu rootGroup={rootGroup} onGroupChange={setRootGroup} />}
        footer={
          <QueryBuilderFooter
            rootGroup={rootGroup}
            onRun={handleRun}
          />
        }
      >
        <QueryBuilderBody
          rootGroup={rootGroup}
          onGroupChange={setRootGroup}
          onArmPicker={armPicker}
          pickingId={pickingId}
          onArmDraw={armDraw}
          drawingId={drawingId}
        />
      </Sidebar>
      <ToggleButton side="left" collapsed={leftCollapsed} onToggle={() => { setLeftCollapsed((v) => !v); }} />

      <Sidebar side="right" collapsed={rightCollapsed} title="Results" meta="—">
        <ResultsPanel />
      </Sidebar>
      <ToggleButton side="right" collapsed={rightCollapsed} onToggle={() => { setRightCollapsed((v) => !v); }} />

      <Legend colorMode={colorMode} />
    </div>
  );
}
