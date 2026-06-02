import { useEffect, useRef, useState } from "react";
import type { Airport } from "../../lib/api";
import { searchAirports } from "../../lib/api";

interface AirportSearchProps {
  onSelect: (lat: number, lng: number, name: string) => void;
}

const TYPE_LABEL: Record<string, string> = {
  large_airport: "✈",
  medium_airport: "✈",
  small_airport: "✈",
  heliport: "H",
  seaplane_base: "~",
  balloonport: "◯",
};

export function AirportSearch({
  onSelect,
}: AirportSearchProps): React.ReactElement {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<Airport[]>([]);
  const [activeIdx, setActiveIdx] = useState(-1);
  const inputRef = useRef<HTMLInputElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);

  // Debounced search
  useEffect(() => {
    const q = query.trim();
    if (!q) {
      setResults([]);
      setActiveIdx(-1);
      return;
    }
    const controller = new AbortController();
    const timer = setTimeout((): void => {
      searchAirports(q, { limit: 8, signal: controller.signal })
        .then((r) => {
          setResults(r);
          setActiveIdx(-1);
        })
        .catch((): void => {
          /* aborted or network error — leave stale results */
        });
    }, 180);
    return (): void => {
      clearTimeout(timer);
      controller.abort();
    };
  }, [query]);

  // Focus input when opened
  useEffect(() => {
    if (open) inputRef.current?.focus();
  }, [open]);

  // Close on outside click
  useEffect(() => {
    if (!open) return;
    const handler = (e: MouseEvent): void => {
      if (!containerRef.current?.contains(e.target as Node)) {
        close();
      }
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

  const handleSelect = (airport: Airport): void => {
    onSelect(airport.lat, airport.lon, airport.ident);
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
      const a = results[activeIdx];
      if (a) handleSelect(a);
    }
  };

  if (!open) {
    return (
      <button
        onClick={() => {
          setOpen(true);
        }}
        title="Search airports"
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
          fontSize: 14,
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
          placeholder="EGLL, Heathrow…"
          style={{
            background: "none",
            border: "none",
            outline: "none",
            color: "var(--fg-1)",
            fontSize: 12,
            width: 160,
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
            minWidth: 300,
            overflow: "hidden",
          }}
        >
          {results.map((airport, i) => (
            <button
              key={airport.ident}
              onMouseDown={(e) => {
                e.preventDefault();
              }}
              onClick={() => {
                handleSelect(airport);
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
                {airport.ident}
              </span>
              <span
                style={{
                  fontSize: 10,
                  color: "var(--fg-3)",
                  flexShrink: 0,
                }}
              >
                {TYPE_LABEL[airport.type] ?? "✈"}
              </span>
              <span
                style={{
                  overflow: "hidden",
                  textOverflow: "ellipsis",
                  whiteSpace: "nowrap",
                  color: i === activeIdx ? "var(--accent)" : "var(--fg-2)",
                }}
              >
                {airport.name}
              </span>
              <span
                style={{
                  marginLeft: "auto",
                  flexShrink: 0,
                  fontSize: 10,
                  color: "var(--fg-3)",
                }}
              >
                {airport.iso_country}
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
