import { Fragment, useEffect, useRef } from "react";
import { Plane } from "../Icons";
import type { FlightDetail } from "../../lib/api";
import type { HoveredPoint } from "../map/MapView";

interface ResultsPanelProps {
  flights: FlightDetail[] | null;
  loading: boolean;
  error: string | null;
  hasMore: boolean;
  onLoadMore: () => void;
  selectedFlightId?: string | null;
  onSelectFlight?: (id: string | null) => void;
  hoveredPoint?: HoveredPoint | null;
  onHoverPoint?: (p: HoveredPoint | null) => void;
}

function fmtTime(iso: string): string {
  return iso.slice(11, 19) + " UTC";
}

function fmtEndTime(endIso: string, startDate: string): string {
  const endDate = endIso.slice(0, 10);
  const t = fmtTime(endIso);
  if (endDate === startDate) return t;
  const diff = Math.round((Date.parse(endDate) - Date.parse(startDate)) / 86400000);
  return `${t} (+${String(diff)}d)`;
}

type ListItem =
  | { type: "divider"; date: string; key: string }
  | { type: "flight"; flight: FlightDetail };

function buildList(flights: FlightDetail[]): ListItem[] {
  const items: ListItem[] = [];
  let lastDate = "";
  for (const f of flights) {
    const date = f.start_ts.slice(0, 10);
    if (date !== lastDate) {
      items.push({ type: "divider", date, key: "div-" + date });
      lastDate = date;
    }
    items.push({ type: "flight", flight: f });
  }
  return items;
}

function SparklineChart({
  coords,
  hoveredIdx,
  onHoverIdx,
}: {
  coords: [number, number, number][];
  hoveredIdx: number | null;
  onHoverIdx: (idx: number | null) => void;
}): React.ReactElement | null {
  if (coords.length < 2) return null;

  const W = 200,
    H = 28,
    PAD = 2;
  const n = coords.length;
  const alts = coords.map((c) => c[2]);
  const minAlt = Math.min(...alts);
  const maxAlt = Math.max(...alts);
  const range = maxAlt - minAlt || 1;

  const toX = (i: number): number => PAD + (i / (n - 1)) * (W - PAD * 2);
  const toY = (alt: number): number => PAD + (1 - (alt - minAlt) / range) * (H - PAD * 2);
  const n2s = (x: number): string => x.toFixed(3);

  const firstAlt = alts[0] ?? 0;
  const polyPoints = alts.map((alt, i) => `${n2s(toX(i))},${n2s(toY(alt))}`).join(" ");
  const fillD =
    `M ${n2s(toX(0))},${n2s(toY(firstAlt))} ` +
    alts
      .slice(1)
      .map((alt, i) => `L ${n2s(toX(i + 1))},${n2s(toY(alt))}`)
      .join(" ") +
    ` L ${n2s(toX(n - 1))},${String(H)} L ${n2s(toX(0))},${String(H)} Z`;

  const activeIdx = hoveredIdx !== null && hoveredIdx >= 0 && hoveredIdx < n ? hoveredIdx : null;
  const activeAlt = activeIdx !== null ? (alts[activeIdx] ?? 0) : 0;
  const activeHx = activeIdx !== null ? toX(activeIdx) : 0;
  const activeHy = activeIdx !== null ? toY(activeAlt) : 0;
  const tooltipLeft = activeIdx !== null ? `${((toX(activeIdx) / W) * 100).toFixed(2)}%` : "0%";

  return (
    <div style={{ position: "relative", marginTop: 5 }}>
      {activeIdx !== null && (
        <div
          style={{
            position: "absolute",
            left: tooltipLeft,
            bottom: "100%",
            transform: "translateX(-50%)",
            marginBottom: 2,
            background: "var(--bg-1)",
            border: "1px solid var(--line-1)",
            borderRadius: "var(--radius-1)",
            padding: "2px 5px",
            fontSize: 10,
            color: "var(--fg-1)",
            whiteSpace: "nowrap",
            pointerEvents: "none",
            zIndex: 10,
            boxShadow: "var(--shadow-1)",
          }}
        >
          {Math.round(activeAlt).toLocaleString()} ft
        </div>
      )}
      <svg
        viewBox="0 0 200 28"
        preserveAspectRatio="none"
        style={{ width: "100%", height: 20, display: "block" }}
        onMouseMove={(e): void => {
          const rect = e.currentTarget.getBoundingClientRect();
          const x = e.clientX - rect.left;
          const idx = Math.min(n - 1, Math.max(0, Math.round((x / rect.width) * (n - 1))));
          onHoverIdx(idx);
        }}
        onMouseLeave={(): void => {
          onHoverIdx(null);
        }}
      >
        <path d={fillD} fill="rgba(110,168,255,0.15)" stroke="none" />
        <polyline
          points={polyPoints}
          fill="none"
          stroke="rgba(110,168,255,0.8)"
          strokeWidth="1.5"
        />
        {activeIdx !== null && (
          <g>
            <line
              x1={activeHx}
              y1={PAD}
              x2={activeHx}
              y2={H - PAD}
              stroke="rgba(110,168,255,0.6)"
              strokeWidth="1"
            />
            <circle
              cx={activeHx}
              cy={activeHy}
              r={2.5}
              style={{ fill: "var(--bg-1)" }}
              stroke="rgb(110,168,255)"
              strokeWidth="1.5"
            />
          </g>
        )}
      </svg>
    </div>
  );
}

export function ResultsPanel({
  flights,
  loading,
  error,
  hasMore,
  onLoadMore,
  selectedFlightId,
  onSelectFlight,
  hoveredPoint,
  onHoverPoint,
}: ResultsPanelProps): React.ReactElement {
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!selectedFlightId || !scrollRef.current) return;
    const el = scrollRef.current.querySelector<HTMLElement>(
      `[data-flight-id="${selectedFlightId}"]`,
    );
    el?.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }, [selectedFlightId]);

  if (error) {
    return (
      <div style={{ padding: "20px 16px", color: "var(--color-red, #e55)", fontSize: 12 }}>
        <strong>Error:</strong> {error}
      </div>
    );
  }

  if (flights === null && !loading) {
    return (
      <div
        style={{ textAlign: "center", padding: "40px 20px", color: "var(--fg-3)", fontSize: 12 }}
      >
        <div style={{ marginBottom: 8, opacity: 0.4 }}>
          <Plane size={32} />
        </div>
        <div>No results yet.</div>
        <div style={{ marginTop: 4 }}>Run a query to see flights.</div>
      </div>
    );
  }

  if (flights !== null && flights.length === 0 && !loading) {
    return (
      <div
        style={{ textAlign: "center", padding: "40px 20px", color: "var(--fg-3)", fontSize: 12 }}
      >
        <div>No flights matched.</div>
      </div>
    );
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%" }}>
      <div ref={scrollRef} style={{ flex: 1, overflowY: "auto" }}>
        {buildList(flights ?? []).map((item) =>
          item.type === "divider" ? (
            <div
              key={item.key}
              style={{
                position: "sticky",
                top: 0,
                padding: "4px 14px",
                background: "var(--bg-2)",
                borderBottom: "1px solid var(--line-1)",
                fontSize: 11,
                fontWeight: 600,
                color: "var(--fg-3)",
                letterSpacing: "0.04em",
                zIndex: 1,
              }}
            >
              {item.date}
            </div>
          ) : (
            <FlightRow
              key={item.flight.flight_id}
              flight={item.flight}
              selected={item.flight.flight_id === selectedFlightId}
              onClick={() => {
                onSelectFlight?.(
                  item.flight.flight_id === selectedFlightId ? null : item.flight.flight_id,
                );
              }}
              hoveredPointIdx={
                hoveredPoint?.flightId === item.flight.flight_id ? hoveredPoint.pointIdx : null
              }
              onHoverPointIdx={(idx) => {
                onHoverPoint?.(
                  idx !== null ? { flightId: item.flight.flight_id, pointIdx: idx } : null,
                );
              }}
            />
          ),
        )}
        {loading && (
          <div
            style={{
              padding: "12px 16px",
              color: "var(--fg-3)",
              fontSize: 12,
              textAlign: "center",
            }}
          >
            Loading…
          </div>
        )}
      </div>

      {hasMore && !loading && (
        <div style={{ padding: "8px 12px", borderTop: "1px solid var(--line-1)", flexShrink: 0 }}>
          <button
            onClick={onLoadMore}
            style={{
              width: "100%",
              padding: "7px 0",
              borderRadius: "var(--radius-1)",
              border: "1px solid var(--line-1)",
              background: "var(--bg-2)",
              color: "var(--fg-1)",
              fontSize: 12,
              fontWeight: 600,
              cursor: "pointer",
            }}
          >
            Load more
          </button>
        </div>
      )}
    </div>
  );
}

function FlightRow({
  flight,
  selected,
  onClick,
  hoveredPointIdx,
  onHoverPointIdx,
}: {
  flight: FlightDetail;
  selected: boolean;
  onClick: () => void;
  hoveredPointIdx: number | null;
  onHoverPointIdx: (idx: number | null) => void;
}): React.ReactElement {
  const label = flight.callsign ?? flight.icao24;
  const sub = [flight.icao_type, flight.emitter_category].filter(Boolean).join(" · ") || "—";
  const coords = flight.path?.coordinates ?? null;

  const detailRows: [string, string, boolean][] = [
    ["ICAO24", flight.icao24, true],
    ...(flight.registration != null ? [["Reg", flight.registration, false] as [string, string, boolean]] : []),
    ...(flight.model != null ? [["Model", flight.model, false] as [string, string, boolean]] : []),
    ...(flight.year != null ? [["Year", String(flight.year), false] as [string, string, boolean]] : []),
    ...(flight.operator != null ? [["Operator", flight.operator, false] as [string, string, boolean]] : []),
  ];

  return (
    <div
      data-flight-id={flight.flight_id}
      onClick={onClick}
      style={{
        padding: "8px 14px",
        borderBottom: "1px solid var(--line-1)",
        borderLeft: selected ? "3px solid var(--accent)" : "3px solid transparent",
        background: selected ? "var(--accent-soft)" : "transparent",
        fontSize: 12,
        cursor: "pointer",
      }}
    >
      <div
        style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", gap: 8 }}
      >
        <span
          style={{
            fontWeight: 600,
            color: "var(--fg-1)",
            fontFamily: "var(--font-mono, monospace)",
          }}
        >
          {label}
        </span>
        <span style={{ color: "var(--fg-3)", fontSize: 11, whiteSpace: "nowrap" }}>{sub}</span>
      </div>
      <div style={{ color: "var(--fg-3)", marginTop: 2 }}>
        {fmtTime(flight.start_ts)} → {fmtEndTime(flight.end_ts, flight.start_ts.slice(0, 10))}
      </div>
      {coords && (
        <SparklineChart coords={coords} hoveredIdx={hoveredPointIdx} onHoverIdx={onHoverPointIdx} />
      )}
      {selected && (
        <div
          style={{
            marginTop: 8,
            paddingTop: 7,
            borderTop: "1px solid var(--line-1)",
            display: "grid",
            gridTemplateColumns: "52px 1fr",
            columnGap: 8,
            rowGap: 3,
            fontSize: 11,
          }}
        >
          {detailRows.map(([lbl, val, mono]) => (
            <Fragment key={lbl}>
              <span style={{ color: "var(--fg-3)" }}>{lbl}</span>
              <span
                style={{
                  color: "var(--fg-1)",
                  fontFamily: mono ? "var(--font-mono, monospace)" : undefined,
                  wordBreak: "break-word",
                }}
              >
                {val}
              </span>
            </Fragment>
          ))}
        </div>
      )}
    </div>
  );
}
