import { Layers, Moon, Satellite, Sun } from "../Icons";
import type { ColorMode } from "../map/MapView";

type Basemap = "dark" | "light" | "sat";
type Theme = "dark" | "light";

interface TopbarProps {
  basemap: Basemap;
  onBasemap: (b: Basemap) => void;
  colorMode: ColorMode;
  onColorMode: (c: ColorMode) => void;
  airspaceOn: boolean;
  onToggleAirspace: () => void;
  theme: Theme;
  onTheme: () => void;
}

export function Topbar({
  basemap,
  onBasemap,
  colorMode,
  onColorMode,
  airspaceOn,
  onToggleAirspace,
  theme,
  onTheme,
}: TopbarProps): React.ReactElement {
  return (
    <div
      style={{
        position: "absolute",
        top: 12,
        left: "50%",
        transform: "translateX(-50%)",
        zIndex: 10,
        display: "flex",
        alignItems: "center",
        gap: 16,
        padding: "6px 8px 6px 14px",
        background: "color-mix(in oklab, var(--bg-1) 92%, transparent)",
        backdropFilter: "blur(12px)",
        WebkitBackdropFilter: "blur(12px)",
        border: "1px solid var(--line-1)",
        borderRadius: "var(--radius-3)",
        boxShadow: "var(--shadow-2)",
        whiteSpace: "nowrap",
      }}
    >
      {/* Brand */}
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 8,
          fontWeight: 600,
          fontSize: 13,
          letterSpacing: "-0.01em",
        }}
      >
        <span
          style={{
            width: 8,
            height: 8,
            background: "var(--accent)",
            borderRadius: "50%",
            boxShadow: "0 0 0 3px var(--accent-soft)",
          }}
        />
        adsb.aero
        <span
          style={{
            fontFamily: "'JetBrains Mono', monospace",
            fontSize: 10,
            color: "var(--fg-2)",
            background: "var(--bg-3)",
            padding: "2px 6px",
            borderRadius: 3,
            marginLeft: 4,
          }}
        >
          HISTORICAL
        </span>
      </div>

      <Sep />

      <SegLabel>Basemap</SegLabel>
      <Seg>
        <SegBtn active={basemap === "dark"} onClick={() => { onBasemap("dark"); }} title="Dark">
          <Moon />
        </SegBtn>
        <SegBtn active={basemap === "light"} onClick={() => { onBasemap("light"); }} title="Light">
          <Sun />
        </SegBtn>
        <SegBtn active={basemap === "sat"} onClick={() => { onBasemap("sat"); }} title="Satellite">
          <Satellite />
        </SegBtn>
      </Seg>

      <Sep />

      <SegLabel>Color by</SegLabel>
      <Seg>
        <SegBtn active={colorMode === "alt"} onClick={() => { onColorMode("alt"); }}>
          Altitude
        </SegBtn>
        <SegBtn active={colorMode === "cat"} onClick={() => { onColorMode("cat"); }}>
          Category
        </SegBtn>
        <SegBtn active={colorMode === "vs"} onClick={() => { onColorMode("vs"); }}>
          VS
        </SegBtn>
        <SegBtn active={colorMode === "gs"} onClick={() => { onColorMode("gs"); }}>
          GS
        </SegBtn>
        <SegBtn active={colorMode === "ias"} onClick={() => { onColorMode("ias"); }}>
          IAS
        </SegBtn>
        <SegBtn active={colorMode === "sqk"} onClick={() => { onColorMode("sqk"); }}>
          Squawk
        </SegBtn>
      </Seg>

      <Sep />

      <IconBtn active={airspaceOn} onClick={onToggleAirspace} title="Toggle airspace overlay">
        <Layers />
      </IconBtn>
      <IconBtn onClick={onTheme} title="Toggle theme">
        {theme === "dark" ? <Sun /> : <Moon />}
      </IconBtn>
    </div>
  );
}

function Sep(): React.ReactElement {
  return <div style={{ width: 1, height: 20, background: "var(--line-1)" }} />;
}

function SegLabel({ children }: { children: string }): React.ReactElement {
  return (
    <span
      style={{
        fontSize: 10.5,
        textTransform: "uppercase",
        letterSpacing: "0.06em",
        color: "var(--fg-3)",
        marginRight: 6,
        fontWeight: 500,
      }}
    >
      {children}
    </span>
  );
}

function Seg({ children }: { children: React.ReactNode }): React.ReactElement {
  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        background: "var(--bg-2)",
        border: "1px solid var(--line-1)",
        borderRadius: 6,
        padding: 2,
        gap: 1,
      }}
    >
      {children}
    </div>
  );
}

interface SegBtnProps {
  active: boolean;
  onClick: () => void;
  title?: string;
  children: React.ReactNode;
}

function SegBtn({ active, onClick, title, children }: SegBtnProps): React.ReactElement {
  return (
    <button
      onClick={onClick}
      title={title}
      style={{
        background: active ? "var(--bg-3)" : "none",
        border: active ? "1px solid var(--line-2)" : "1px solid transparent",
        color: active ? "var(--fg-0)" : "var(--fg-2)",
        padding: "4px 10px",
        fontSize: 11.5,
        borderRadius: 4,
        cursor: "pointer",
        display: "flex",
        alignItems: "center",
        gap: 4,
      }}
    >
      {children}
    </button>
  );
}

interface IconBtnProps {
  active?: boolean;
  onClick: () => void;
  title?: string;
  children: React.ReactNode;
}

function IconBtn({ active = false, onClick, title, children }: IconBtnProps): React.ReactElement {
  return (
    <button
      onClick={onClick}
      title={title}
      style={{
        background: active ? "var(--accent-soft)" : "var(--bg-2)",
        border: active
          ? "1px solid color-mix(in oklab, var(--accent) 50%, var(--line-2))"
          : "1px solid var(--line-1)",
        color: active ? "var(--accent)" : "var(--fg-1)",
        width: 28,
        height: 28,
        borderRadius: 6,
        display: "inline-flex",
        alignItems: "center",
        justifyContent: "center",
        cursor: "pointer",
        padding: 0,
      }}
    >
      {children}
    </button>
  );
}
