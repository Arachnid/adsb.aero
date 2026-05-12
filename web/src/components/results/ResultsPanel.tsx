import { useEffect, useRef } from "react";
import { Plane } from "../Icons";
import type { FlightDetail } from "../../lib/api";

interface ResultsPanelProps {
  flights: FlightDetail[] | null;
  loading: boolean;
  error: string | null;
  hasMore: boolean;
  onLoadMore: () => void;
  selectedFlightId?: string | null;
  onSelectFlight?: (id: string | null) => void;
}

function fmtTime(iso: string): string {
  return iso.slice(11, 19) + " UTC";
}

function fmtEndTime(endIso: string, startDate: string): string {
  const endDate = endIso.slice(0, 10);
  const t = fmtTime(endIso);
  if (endDate === startDate) return t;
  const diff = Math.round((Date.parse(endDate) - Date.parse(startDate)) / 86400000);
  return `${t} (+${diff}d)`;
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

export function ResultsPanel({ flights, loading, error, hasMore, onLoadMore, selectedFlightId, onSelectFlight }: ResultsPanelProps): React.ReactElement {
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!selectedFlightId || !scrollRef.current) return;
    const el = scrollRef.current.querySelector<HTMLElement>(`[data-flight-id="${selectedFlightId}"]`);
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
      <div style={{ textAlign: "center", padding: "40px 20px", color: "var(--fg-3)", fontSize: 12 }}>
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
      <div style={{ textAlign: "center", padding: "40px 20px", color: "var(--fg-3)", fontSize: 12 }}>
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
              onClick={() => { onSelectFlight?.(item.flight.flight_id === selectedFlightId ? null : item.flight.flight_id); }}
            />
          )
        )}
        {loading && (
          <div style={{ padding: "12px 16px", color: "var(--fg-3)", fontSize: 12, textAlign: "center" }}>
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

function FlightRow({ flight, selected, onClick }: { flight: FlightDetail; selected: boolean; onClick: () => void }): React.ReactElement {
  const label = flight.callsign ?? flight.icao24;
  const sub = [flight.icao_type, flight.emitter_category].filter(Boolean).join(" · ") || "—";

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
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", gap: 8 }}>
        <span style={{ fontWeight: 600, color: "var(--fg-1)", fontFamily: "var(--font-mono, monospace)" }}>
          {label}
        </span>
        <span style={{ color: "var(--fg-3)", fontSize: 11, whiteSpace: "nowrap" }}>{sub}</span>
      </div>
      <div style={{ color: "var(--fg-3)", marginTop: 2 }}>
        {fmtTime(flight.start_ts)} → {fmtEndTime(flight.end_ts, flight.start_ts.slice(0, 10))}
      </div>
    </div>
  );
}
