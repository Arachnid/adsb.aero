import { Plane } from "../Icons";
import type { FlightDetail } from "../../lib/api";

interface ResultsPanelProps {
  flights: FlightDetail[] | null;
  loading: boolean;
  error: string | null;
  hasMore: boolean;
  onLoadMore: () => void;
}

function fmt(iso: string): string {
  return iso.replace("T", " ").replace(/\.\d+Z$/, "Z").replace(/Z$/, " UTC");
}

export function ResultsPanel({ flights, loading, error, hasMore, onLoadMore }: ResultsPanelProps): React.ReactElement {
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
      <div style={{ flex: 1, overflowY: "auto" }}>
        {(flights ?? []).map((f) => (
          <FlightRow key={f.flight_id} flight={f} />
        ))}
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

function FlightRow({ flight }: { flight: FlightDetail }): React.ReactElement {
  const label = flight.callsign ?? flight.icao24;
  const sub = [flight.icao_type, flight.emitter_category].filter(Boolean).join(" · ") || "—";

  return (
    <div
      style={{
        padding: "8px 14px",
        borderBottom: "1px solid var(--line-1)",
        fontSize: 12,
      }}
    >
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", gap: 8 }}>
        <span style={{ fontWeight: 600, color: "var(--fg-1)", fontFamily: "var(--font-mono, monospace)" }}>
          {label}
        </span>
        <span style={{ color: "var(--fg-3)", fontSize: 11, whiteSpace: "nowrap" }}>{sub}</span>
      </div>
      <div style={{ color: "var(--fg-3)", marginTop: 2 }}>
        {fmt(flight.start_ts)} → {fmt(flight.end_ts)}
      </div>
    </div>
  );
}
