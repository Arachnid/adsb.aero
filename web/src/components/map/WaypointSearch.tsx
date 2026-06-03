import { useEffect, useRef, useState } from "react";
import type { Waypoint } from "../../lib/api";
import { searchWaypoints } from "../../lib/api";

interface WaypointSearchProps {
  onSelect: (lat: number, lng: number, label: string) => void;
}

// Airport type_code → display label used in the icon badge
const APT_TYPE: Record<number, string> = {
  0: "APT",
  1: "GLD",
  2: "AF",
  3: "APT",
  4: "HEL",
  5: "MIL",
  6: "ULM",
  7: "HEL",
  8: "CLO",
  9: "APT",
  10: "H₂O",
  11: "STR",
  12: "AGR",
  13: "ALT",
};

// Navaid type_code → abbreviation
const NAV_TYPE: Record<number, string> = {
  0: "DME",
  1: "TCN",
  2: "NDB",
  3: "VOR",
  4: "VDM",
  5: "VTC",
  6: "DVR",
  7: "DDM",
  8: "DTC",
};

function kindIcon(w: Waypoint): React.ReactElement {
  if (w.kind === "navaid") {
    const label =
      w.type_code != null ? (NAV_TYPE[w.type_code] ?? "NAV") : "NAV";
    return <Badge color="var(--accent)">{label}</Badge>;
  }
  if (w.kind === "reporting_point") {
    return <Badge color="#a78bfa">RPT</Badge>;
  }
  if (w.kind === "airspace") {
    return <Badge color="#60a5fa">ASP</Badge>;
  }
  // airport
  const label = w.type_code != null ? (APT_TYPE[w.type_code] ?? "APT") : "APT";
  const color =
    w.type_code === 4 || w.type_code === 7
      ? "#34d399" // heliport — green
      : w.type_code === 5 || w.type_code === 0
        ? "#94a3b8" // military — muted
        : "var(--fg-2)";
  return <Badge color={color}>{label}</Badge>;
}

function Badge({
  children,
  color,
}: {
  children: string;
  color: string;
}): React.ReactElement {
  return (
    <span
      style={{
        fontFamily: "'JetBrains Mono', monospace",
        fontSize: 9,
        fontWeight: 700,
        color,
        minWidth: 32,
        flexShrink: 0,
        letterSpacing: "0.02em",
      }}
    >
      {children}
    </span>
  );
}

export function WaypointSearch({
  onSelect,
}: WaypointSearchProps): React.ReactElement {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<Waypoint[]>([]);
  const [activeIdx, setActiveIdx] = useState(-1);
  const inputRef = useRef<HTMLInputElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const q = query.trim();
    if (!q) {
      setResults([]);
      setActiveIdx(-1);
      return;
    }
    const controller = new AbortController();
    const timer = setTimeout((): void => {
      searchWaypoints(q, { limit: 10, signal: controller.signal })
        .then((r) => {
          setResults(r);
          setActiveIdx(-1);
        })
        .catch((): void => {});
    }, 180);
    return (): void => {
      clearTimeout(timer);
      controller.abort();
    };
  }, [query]);

  useEffect(() => {
    if (open) inputRef.current?.focus();
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const handler = (e: MouseEvent): void => {
      if (!containerRef.current?.contains(e.target as Node)) close();
    };
    document.addEventListener("mousedown", handler);
    return (): void => {
      document.removeEventListener("mousedown", handler);
    };
  }, [open]); // eslint-disable-line react-hooks/exhaustive-deps

  const close = (): void => {
    setOpen(false);
    setQuery("");
    setResults([]);
  };

  const handleSelect = (w: Waypoint): void => {
    onSelect(w.lat, w.lon, w.ident ?? w.name);
    close();
  };

  const handleKeyDown = (e: React.KeyboardEvent): void => {
    if (e.key === "Escape") {
      close();
      return;
    }
    if (!results.length) return;
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setActiveIdx((i) => Math.min(i + 1, results.length - 1));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setActiveIdx((i) => Math.max(i - 1, 0));
    } else if (e.key === "Enter" && activeIdx >= 0) {
      e.preventDefault();
      const w = results[activeIdx];
      if (w) handleSelect(w);
    }
  };

  if (!open) {
    return (
      <button
        onClick={() => {
          setOpen(true);
        }}
        title="Search waypoints"
        style={{
          background: "var(--bg-2)",
          border: "1px solid var(--line-1)",
          color: "var(--fg-2)",
          width: 28,
          height: 28,
          borderRadius: 6,
          display: "inline-flex",
          alignItems: "center",
          justifyContent: "center",
          cursor: "pointer",
          padding: 0,
          flexShrink: 0,
        }}
      >
        <SearchIcon />
      </button>
    );
  }

  return (
    <div
      ref={containerRef}
      style={{ position: "relative", display: "inline-flex", flexShrink: 0 }}
    >
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 6,
          background: "var(--bg-2)",
          border: "1px solid var(--accent)",
          borderRadius: 6,
          padding: "0 8px",
          height: 28,
        }}
      >
        <SearchIcon />
        <input
          ref={inputRef}
          value={query}
          onChange={(e) => {
            setQuery(e.target.value);
          }}
          onKeyDown={handleKeyDown}
          placeholder="EGLL, BNN, DIVIS…"
          style={{
            background: "none",
            border: "none",
            outline: "none",
            color: "var(--fg-1)",
            fontSize: 12,
            width: 170,
            padding: 0,
          }}
        />
        {query && (
          <button
            onMouseDown={(e) => {
              e.preventDefault();
            }}
            onClick={() => {
              setQuery("");
            }}
            style={{
              background: "none",
              border: "none",
              cursor: "pointer",
              color: "var(--fg-3)",
              padding: 0,
              fontSize: 14,
              lineHeight: 1,
            }}
          >
            ×
          </button>
        )}
      </div>

      {results.length > 0 && (
        <div
          style={{
            position: "absolute",
            top: "calc(100% + 6px)",
            left: 0,
            zIndex: 20,
            background: "color-mix(in oklab, var(--bg-1) 96%, transparent)",
            backdropFilter: "blur(12px)",
            WebkitBackdropFilter: "blur(12px)",
            border: "1px solid var(--line-1)",
            borderRadius: "var(--radius-2)",
            boxShadow: "var(--shadow-2)",
            minWidth: 320,
            overflow: "hidden",
          }}
        >
          {results.map((w, i) => (
            <button
              key={w.id}
              onMouseDown={(e) => {
                e.preventDefault();
              }}
              onClick={() => {
                handleSelect(w);
              }}
              onMouseEnter={() => {
                setActiveIdx(i);
              }}
              style={{
                display: "flex",
                alignItems: "baseline",
                gap: 8,
                width: "100%",
                padding: "7px 12px",
                background: i === activeIdx ? "var(--accent-soft)" : "none",
                border: "none",
                borderTop: i > 0 ? "1px solid var(--line-0)" : "none",
                color: i === activeIdx ? "var(--accent)" : "var(--fg-1)",
                fontSize: 12,
                cursor: "pointer",
                textAlign: "left",
              }}
            >
              {kindIcon(w)}
              <span
                style={{
                  fontFamily: "'JetBrains Mono', monospace",
                  fontWeight: 600,
                  fontSize: 11,
                  color: i === activeIdx ? "var(--accent)" : "var(--fg-0)",
                  minWidth: 44,
                  flexShrink: 0,
                }}
              >
                {w.ident ?? ""}
              </span>
              <span
                style={{
                  overflow: "hidden",
                  textOverflow: "ellipsis",
                  whiteSpace: "nowrap",
                  color: i === activeIdx ? "var(--accent)" : "var(--fg-2)",
                }}
              >
                {w.name}
              </span>
              <span
                style={{
                  marginLeft: "auto",
                  flexShrink: 0,
                  fontSize: 10,
                  color: "var(--fg-3)",
                }}
              >
                {w.country}
              </span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

function SearchIcon(): React.ReactElement {
  return (
    <svg
      width="14"
      height="14"
      viewBox="0 0 16 16"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.75"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <circle cx="6.5" cy="6.5" r="4.5" />
      <line x1="10.5" y1="10.5" x2="14" y2="14" />
    </svg>
  );
}
