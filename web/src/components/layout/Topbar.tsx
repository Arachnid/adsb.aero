import { useEffect, useState } from "react";
import { Layers, Link, Moon, Satellite, Sun } from "../Icons";
import { useMobile } from "../../hooks/useMobile";
import type { ColorMode } from "../map/MapView";
import { AirportSearch } from "../map/AirportSearch";

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
  onAbout: () => void;
  onFlyToAirport: (lat: number, lng: number, ident: string) => void;
}

const COLOR_MODE_LABELS: Record<ColorMode, string> = {
  alt: "Altitude",
  agl: "AGL height",
  cat: "Category",
  vs: "Vert. speed",
  gs: "Ground speed",
  ias: "Airspeed",
  sqk: "Squawk",
};

const COLOR_MODE_SHORT: Record<ColorMode, string> = {
  alt: "ALT",
  agl: "AGL",
  cat: "CAT",
  vs: "VS",
  gs: "GS",
  ias: "IAS",
  sqk: "SQK",
};

export function Topbar({
  basemap,
  onBasemap,
  colorMode,
  onColorMode,
  airspaceOn,
  onToggleAirspace,
  theme,
  onTheme,
  onAbout,
  onFlyToAirport,
}: TopbarProps): React.ReactElement {
  const [copied, setCopied] = useState(false);
  const [dropdown, setDropdown] = useState<"basemap" | "color" | null>(null);
  const mobile = useMobile();

  const handleCopyLink = (): void => {
    void navigator.clipboard.writeText(window.location.href).then(() => {
      setCopied(true);
      setTimeout(() => {
        setCopied(false);
      }, 1500);
    });
  };

  useEffect(() => {
    if (!dropdown) return;
    const close = (): void => {
      setDropdown(null);
    };
    document.addEventListener("click", close);
    return (): void => {
      document.removeEventListener("click", close);
    };
  }, [dropdown]);

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
      <button
        onClick={onAbout}
        title="About adsb.aero"
        style={{
          display: "flex",
          alignItems: "center",
          gap: 8,
          fontWeight: 600,
          fontSize: 13,
          letterSpacing: "-0.01em",
          color: "inherit",
          background: "none",
          border: "none",
          padding: 0,
          cursor: "pointer",
        }}
      >
        <img
          src="/logo.png"
          alt=""
          width={22}
          height={22}
          style={{
            borderRadius: "50%",
            objectFit: "cover",
            display: "block",
            flexShrink: 0,
          }}
        />
        adsb.aero
        {!mobile && (
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
        )}
      </button>

      <Sep />
      <AirportSearch onSelect={onFlyToAirport} />
      <Sep />

      {mobile ? (
        <>
          <DropdownSection>
            <IconBtn
              onClick={(e) => {
                e.stopPropagation();
                setDropdown((d) => (d === "basemap" ? null : "basemap"));
              }}
              title="Basemap"
            >
              {basemap === "dark" ? (
                <Moon />
              ) : basemap === "sat" ? (
                <Satellite />
              ) : (
                <Sun />
              )}
            </IconBtn>
            {dropdown === "basemap" && (
              <DropMenu
                onClick={(e) => {
                  e.stopPropagation();
                }}
              >
                <DropItem
                  active={basemap === "dark"}
                  onClick={() => {
                    onBasemap("dark");
                    setDropdown(null);
                  }}
                >
                  <Moon /> Dark
                </DropItem>
                <DropItem
                  active={basemap === "light"}
                  onClick={() => {
                    onBasemap("light");
                    setDropdown(null);
                  }}
                >
                  <Sun /> Light
                </DropItem>
                <DropItem
                  active={basemap === "sat"}
                  onClick={() => {
                    onBasemap("sat");
                    setDropdown(null);
                  }}
                >
                  <Satellite /> Satellite
                </DropItem>
              </DropMenu>
            )}
          </DropdownSection>

          <DropdownSection>
            <IconBtn
              onClick={(e) => {
                e.stopPropagation();
                setDropdown((d) => (d === "color" ? null : "color"));
              }}
              title="Color by"
            >
              <span
                style={{
                  fontSize: 9,
                  fontFamily: "'JetBrains Mono', monospace",
                  letterSpacing: 0,
                }}
              >
                {COLOR_MODE_SHORT[colorMode]}
              </span>
            </IconBtn>
            {dropdown === "color" && (
              <DropMenu
                align="right"
                onClick={(e) => {
                  e.stopPropagation();
                }}
              >
                {(
                  ["alt", "agl", "cat", "vs", "gs", "ias", "sqk"] as ColorMode[]
                ).map((mode) => (
                  <DropItem
                    key={mode}
                    active={colorMode === mode}
                    onClick={() => {
                      onColorMode(mode);
                      setDropdown(null);
                    }}
                  >
                    {COLOR_MODE_LABELS[mode]}
                  </DropItem>
                ))}
              </DropMenu>
            )}
          </DropdownSection>
        </>
      ) : (
        <>
          <SegLabel>Basemap</SegLabel>
          <Seg>
            <SegBtn
              active={basemap === "dark"}
              onClick={() => {
                onBasemap("dark");
              }}
              title="Dark"
            >
              <Moon />
            </SegBtn>
            <SegBtn
              active={basemap === "light"}
              onClick={() => {
                onBasemap("light");
              }}
              title="Light"
            >
              <Sun />
            </SegBtn>
            <SegBtn
              active={basemap === "sat"}
              onClick={() => {
                onBasemap("sat");
              }}
              title="Satellite"
            >
              <Satellite />
            </SegBtn>
          </Seg>

          <Sep />
          <SegLabel>Color by</SegLabel>
          <Seg>
            <SegBtn
              active={colorMode === "alt"}
              onClick={() => {
                onColorMode("alt");
              }}
            >
              Altitude
            </SegBtn>
            <SegBtn
              active={colorMode === "agl"}
              onClick={() => {
                onColorMode("agl");
              }}
            >
              AGL
            </SegBtn>
            <SegBtn
              active={colorMode === "cat"}
              onClick={() => {
                onColorMode("cat");
              }}
            >
              Category
            </SegBtn>
            <SegBtn
              active={colorMode === "vs"}
              onClick={() => {
                onColorMode("vs");
              }}
            >
              VS
            </SegBtn>
            <SegBtn
              active={colorMode === "gs"}
              onClick={() => {
                onColorMode("gs");
              }}
            >
              GS
            </SegBtn>
            <SegBtn
              active={colorMode === "ias"}
              onClick={() => {
                onColorMode("ias");
              }}
            >
              IAS
            </SegBtn>
            <SegBtn
              active={colorMode === "sqk"}
              onClick={() => {
                onColorMode("sqk");
              }}
            >
              Squawk
            </SegBtn>
          </Seg>
        </>
      )}

      <Sep />

      <IconBtn
        active={airspaceOn}
        onClick={onToggleAirspace}
        title="Toggle airspace overlay"
      >
        <Layers />
      </IconBtn>
      <IconBtn onClick={onTheme} title="Toggle theme">
        {theme === "dark" ? <Sun /> : <Moon />}
      </IconBtn>

      <Sep />
      <IconBtn onClick={handleCopyLink} title="Copy share link">
        {copied ? (
          <span
            style={{
              fontSize: 10,
              fontFamily: "'JetBrains Mono', monospace",
            }}
          >
            ✓
          </span>
        ) : (
          <Link />
        )}
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

function SegBtn({
  active,
  onClick,
  title,
  children,
}: SegBtnProps): React.ReactElement {
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
  onClick: (e: React.MouseEvent) => void;
  title?: string;
  children: React.ReactNode;
}

function IconBtn({
  active = false,
  onClick,
  title,
  children,
}: IconBtnProps): React.ReactElement {
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

function DropdownSection({
  children,
}: {
  children: React.ReactNode;
}): React.ReactElement {
  return (
    <div style={{ position: "relative", display: "inline-flex" }}>
      {children}
    </div>
  );
}

interface DropMenuProps {
  align?: "left" | "right";
  onClick?: (e: React.MouseEvent) => void;
  children: React.ReactNode;
}

function DropMenu({
  align = "left",
  onClick,
  children,
}: DropMenuProps): React.ReactElement {
  return (
    <div
      onClick={onClick}
      style={{
        position: "absolute",
        top: "calc(100% + 6px)",
        ...(align === "right" ? { right: 0 } : { left: 0 }),
        zIndex: 20,
        background: "color-mix(in oklab, var(--bg-1) 96%, transparent)",
        backdropFilter: "blur(12px)",
        WebkitBackdropFilter: "blur(12px)",
        border: "1px solid var(--line-1)",
        borderRadius: "var(--radius-2)",
        boxShadow: "var(--shadow-2)",
        minWidth: 130,
        overflow: "hidden",
      }}
    >
      {children}
    </div>
  );
}

interface DropItemProps {
  active: boolean;
  onClick: () => void;
  children: React.ReactNode;
}

function DropItem({
  active,
  onClick,
  children,
}: DropItemProps): React.ReactElement {
  return (
    <button
      onClick={onClick}
      style={{
        display: "flex",
        alignItems: "center",
        gap: 8,
        width: "100%",
        padding: "9px 12px",
        background: active ? "var(--accent-soft)" : "none",
        border: "none",
        borderTop: "1px solid var(--line-0)",
        color: active ? "var(--accent)" : "var(--fg-1)",
        fontSize: 13,
        cursor: "pointer",
        textAlign: "left",
      }}
    >
      {children}
    </button>
  );
}
