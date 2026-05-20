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
  /** ISO datetime lower bound from last response — how far back has been searched. */
  windowFrom?: string | null;
  /** The end date shown in the query form ("YYYY-MM-DD"), for the range label. */
  queryEndDate?: string | null;
}

function fmtTime(iso: string): string {
  return iso.slice(11, 19) + " UTC";
}

function fmtEndTime(endIso: string, startDate: string): string {
  const endDate = endIso.slice(0, 10);
  const t = fmtTime(endIso);
  if (endDate === startDate) return t;
  const diff = Math.round(
    (Date.parse(endDate) - Date.parse(startDate)) / 86400000,
  );
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
  timestamps,
  hoveredIdx,
  onHoverIdx,
}: {
  coords: [number, number, number][][];
  timestamps: number[][] | null | undefined;
  hoveredIdx: number | null;
  onHoverIdx: (idx: number | null) => void;
}): React.ReactElement | null {
  const flatAlts = coords.flatMap((seq) => seq.map((c) => c[2]));
  const flatTs = timestamps?.flat() ?? null;
  const n = flatAlts.length;
  if (n < 2) return null;

  const W = 200,
    H = 28,
    PAD = 2;
  const minAlt = Math.min(...flatAlts);
  const maxAlt = Math.max(...flatAlts);
  const range = maxAlt - minAlt || 1;

  // X is time-proportional when timestamps are available, index-based otherwise.
  const t0 = flatTs?.[0] ?? 0;
  const tSpan = flatTs != null ? (flatTs[n - 1] ?? 0) - t0 : n - 1;
  const toX = (flatIdx: number): number => {
    if (flatTs != null) {
      return (
        PAD + (((flatTs[flatIdx] ?? 0) - t0) / (tSpan || 1)) * (W - PAD * 2)
      );
    }
    return PAD + (flatIdx / (n - 1)) * (W - PAD * 2);
  };
  const toY = (alt: number): number =>
    PAD + (1 - (alt - minAlt) / range) * (H - PAD * 2);
  const n2s = (x: number): string => x.toFixed(3);

  // Build per-sub-sequence fills and polylines; no line crosses a coverage gap.
  let flatOffset = 0;
  const fills: React.ReactElement[] = [];
  const lines: React.ReactElement[] = [];
  for (const subSeq of coords) {
    if (subSeq.length >= 2) {
      const lastJ = subSeq.length - 1;
      const fillD =
        `M ${n2s(toX(flatOffset))},${n2s(toY(subSeq[0]?.[2] ?? 0))} ` +
        subSeq
          .slice(1)
          .map((c, j) => `L ${n2s(toX(flatOffset + j + 1))},${n2s(toY(c[2]))}`)
          .join(" ") +
        ` L ${n2s(toX(flatOffset + lastJ))},${String(H)} L ${n2s(toX(flatOffset))},${String(H)} Z`;
      const polyPoints = subSeq
        .map((c, j) => `${n2s(toX(flatOffset + j))},${n2s(toY(c[2]))}`)
        .join(" ");
      fills.push(
        <path
          key={flatOffset}
          d={fillD}
          fill="rgba(110,168,255,0.15)"
          stroke="none"
        />,
      );
      lines.push(
        <polyline
          key={flatOffset}
          points={polyPoints}
          fill="none"
          stroke="rgba(110,168,255,0.8)"
          strokeWidth="1.5"
        />,
      );
    }
    flatOffset += subSeq.length;
  }

  const activeIdx =
    hoveredIdx !== null && hoveredIdx >= 0 && hoveredIdx < n
      ? hoveredIdx
      : null;
  const activeAlt = activeIdx !== null ? (flatAlts[activeIdx] ?? 0) : 0;
  const activeHx = activeIdx !== null ? toX(activeIdx) : 0;
  const activeHy = activeIdx !== null ? toY(activeAlt) : 0;
  const tooltipLeft =
    activeIdx !== null ? `${((toX(activeIdx) / W) * 100).toFixed(2)}%` : "0%";

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
          const svgX = ((e.clientX - rect.left) / rect.width) * W;
          // Find the flat point index whose x position is closest to the cursor.
          let best = 0,
            bestDist = Infinity;
          for (let i = 0; i < n; i++) {
            const d = Math.abs(toX(i) - svgX);
            if (d < bestDist) {
              bestDist = d;
              best = i;
            }
          }
          onHoverIdx(best);
        }}
        onMouseLeave={(): void => {
          onHoverIdx(null);
        }}
      >
        {fills}
        {lines}
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

function fmtDateLabel(iso: string): string {
  return iso.slice(0, 10);
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
  windowFrom,
  queryEndDate,
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
      <div
        style={{
          padding: "20px 16px",
          color: "var(--color-red, #e55)",
          fontSize: 12,
        }}
      >
        <strong>Error:</strong> {error}
      </div>
    );
  }

  if (flights === null && !loading) {
    return (
      <div
        style={{
          textAlign: "center",
          padding: "40px 20px",
          color: "var(--fg-3)",
          fontSize: 12,
        }}
      >
        <div style={{ marginBottom: 8, opacity: 0.4 }}>
          <Plane size={32} />
        </div>
        <div>No results yet.</div>
        <div style={{ marginTop: 4 }}>Run a query to see flights.</div>
      </div>
    );
  }

  if (
    flights !== null &&
    flights.length === 0 &&
    !loading &&
    !hasMore &&
    !windowFrom
  ) {
    return (
      <div
        style={{
          textAlign: "center",
          padding: "40px 20px",
          color: "var(--fg-3)",
          fontSize: 12,
        }}
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
                  item.flight.flight_id === selectedFlightId
                    ? null
                    : item.flight.flight_id,
                );
              }}
              hoveredPointIdx={
                hoveredPoint?.flightId === item.flight.flight_id
                  ? hoveredPoint.pointIdx
                  : null
              }
              onHoverPointIdx={(idx) => {
                onHoverPoint?.(
                  idx !== null
                    ? { flightId: item.flight.flight_id, pointIdx: idx }
                    : null,
                );
              }}
            />
          ),
        )}
        {flights !== null && flights.length === 0 && !loading && (
          <div
            style={{
              textAlign: "center",
              padding: "40px 20px",
              color: "var(--fg-3)",
              fontSize: 12,
            }}
          >
            No flights matched.
          </div>
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

      {(hasMore || windowFrom) && !loading && (
        <div
          style={{
            padding: "8px 12px",
            borderTop: "1px solid var(--line-1)",
            flexShrink: 0,
            display: "flex",
            flexDirection: "column",
            gap: 6,
          }}
        >
          {windowFrom && queryEndDate && (
            <div
              style={{
                fontSize: 11,
                color: "var(--fg-3)",
                textAlign: "center",
              }}
            >
              {`Fetched ${fmtDateLabel(windowFrom)} – ${queryEndDate}`}
            </div>
          )}
          {hasMore && (
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
              Load earlier results
            </button>
          )}
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
  const sub =
    [flight.icao_type, flight.emitter_category].filter(Boolean).join(" · ") ||
    "—";
  const coords = flight.path?.coordinates ?? null;

  const detailRows: [string, string, boolean][] = [
    ["ICAO24", flight.icao24, true],
    ...(flight.registration != null
      ? [["Reg", flight.registration, false] as [string, string, boolean]]
      : []),
    ...(flight.model != null
      ? [["Model", flight.model, false] as [string, string, boolean]]
      : []),
    ...(flight.year != null
      ? [["Year", String(flight.year), false] as [string, string, boolean]]
      : []),
    ...(flight.operator != null
      ? [["Operator", flight.operator, false] as [string, string, boolean]]
      : []),
  ];

  return (
    <div
      data-flight-id={flight.flight_id}
      onClick={onClick}
      style={{
        padding: "8px 14px",
        borderBottom: "1px solid var(--line-1)",
        borderLeft: selected
          ? "3px solid var(--accent)"
          : "3px solid transparent",
        background: selected ? "var(--accent-soft)" : "transparent",
        fontSize: 12,
        cursor: "pointer",
      }}
    >
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "baseline",
          gap: 8,
        }}
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
        <span
          style={{ color: "var(--fg-3)", fontSize: 11, whiteSpace: "nowrap" }}
        >
          {sub}
        </span>
      </div>
      <div style={{ color: "var(--fg-3)", marginTop: 2 }}>
        {fmtTime(flight.start_ts)} →{" "}
        {fmtEndTime(flight.end_ts, flight.start_ts.slice(0, 10))}
      </div>
      {coords && (
        <SparklineChart
          coords={coords}
          timestamps={flight.timestamps}
          hoveredIdx={hoveredPointIdx}
          onHoverIdx={onHoverPointIdx}
        />
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
