import { useEffect, useState } from "react";
import { MapView } from "./components/map/MapView";
import { Topbar } from "./components/layout/Topbar";
import { Sidebar } from "./components/layout/Sidebar";
import { QueryBuilderBody, QueryBuilderFooter } from "./components/query/QueryBuilder";
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
      aria-label={collapsed ? `Expand ${side} panel` : `Collapse ${side} panel`}
      style={{
        position: "absolute",
        top: "50%",
        [isLeft ? "left" : "right"]: collapsed ? SIDEBAR_MARGIN : expandedEdge,
        transform: "translateY(-50%)",
        transition: `${isLeft ? "left" : "right"} 240ms cubic-bezier(0.4, 0, 0.2, 1)`,
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

  return (
    <div style={{ position: "relative", width: "100%", height: "100%", overflow: "hidden" }}>
      <MapView basemap={basemap} />

      <Topbar
        basemap={basemap}
        onBasemap={setBasemap}
        colorMode={colorMode}
        onColorMode={setColorMode}
        airspaceOn={airspaceOn}
        onToggleAirspace={() => setAirspaceOn((v) => !v)}
        theme={theme}
        onTheme={handleTheme}
      />

      <Sidebar
        side="left"
        collapsed={leftCollapsed}
        title="Query Builder"
        meta="0 filters"
        footer={<QueryBuilderFooter />}
      >
        <QueryBuilderBody />
      </Sidebar>
      <ToggleButton side="left" collapsed={leftCollapsed} onToggle={() => setLeftCollapsed((v) => !v)} />

      <Sidebar side="right" collapsed={rightCollapsed} title="Results" meta="—">
        <ResultsPanel />
      </Sidebar>
      <ToggleButton side="right" collapsed={rightCollapsed} onToggle={() => setRightCollapsed((v) => !v)} />

      <Legend colorMode={colorMode} />
    </div>
  );
}
