import { Fragment, useEffect, useRef, useState } from "react";
import { Download, Plane } from "../Icons";
import type { FlightDetail } from "../../lib/api";
import type { HoveredPoint } from "../map/MapView";
import { stepValueAt, linearValueAt } from "../../lib/seriesUtils";
import { haversineNm, trackDistanceNm } from "../../lib/geometryUtils";
import {
  downloadGeoJSON,
  downloadGPX,
  downloadCSV,
  downloadKML,
} from "../../lib/export";

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
  /** When true the panel is off-screen; skip scrollIntoView to avoid Chrome
   *  scrolling the overflow:hidden app container and shifting the map. */
  collapsed?: boolean;
}

function fmtDuration(startIso: string, endIso: string): string {
  const secs = Math.round((Date.parse(endIso) - Date.parse(startIso)) / 1000);
  const h = Math.floor(secs / 3600);
  const m = Math.floor((secs % 3600) / 60);
  if (h === 0) return `${String(m)}m`;
  return `${String(h)}h ${String(m)}m`;
}

function fmtDistNm(nm: number): string {
  return `${Math.round(nm).toLocaleString()} nm`;
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
  altCorrFt,
  aglFt,
  hoveredIdx,
  onHoverIdx,
}: {
  coords: [number, number, number][][];
  timestamps: number[][] | null | undefined;
  altCorrFt: number[][][] | null | undefined;
  aglFt: number[][][] | null | undefined;
  hoveredIdx: number | null;
  onHoverIdx: (idx: number | null) => void;
}): React.ReactElement | null {
  // Corrected altitude for each flat point.
  const flatAlts = coords.flatMap((seq, subIdx) => {
    const subTs = timestamps?.[subIdx];
    const subCorr = altCorrFt?.[subIdx] ?? null;
    return seq.map(
      (c, j) => c[2] + (stepValueAt(subCorr, subTs?.[j] ?? 0) ?? 0),
    );
  });
  // Ground elevation (alt - AGL) per sub-sequence; null when no AGL data for that sub-sequence.
  const groundAltsBySubSeq: (number[] | null)[] = coords.map((seq, subIdx) => {
    const subTs = timestamps?.[subIdx];
    const subCorr = altCorrFt?.[subIdx] ?? null;
    const subAgl = aglFt?.[subIdx] ?? null;
    if (subAgl === null) return null;
    return seq.map((c, j) => {
      const ts = subTs?.[j] ?? 0;
      const corrFt = stepValueAt(subCorr, ts) ?? 0;
      const aglVal = linearValueAt(subAgl, ts) ?? 0;
      return c[2] + corrFt - aglVal;
    });
  });
  // Flat ground alts aligned 1:1 with flatAlts; null where no AGL data for that sub-sequence.
  const flatGroundAlts: (number | null)[] = groundAltsBySubSeq.flatMap(
    (g, subIdx) => g ?? (coords[subIdx] ?? []).map(() => null),
  );
  const flatGroundAltsForScale = flatGroundAlts.filter(
    (v): v is number => v !== null,
  );

  const flatTs = timestamps?.flat() ?? null;
  const n = flatAlts.length;
  if (n < 2) return null;

  const W = 200,
    H = 28,
    PAD = 2;

  // Y scale: bottom fixed at 0 ft AMSL so terrain height is proportionally accurate.
  const minVal = 0;
  const maxVal = Math.max(...flatAlts, ...flatGroundAltsForScale, 1);
  const range = maxVal;

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
  const toY = (val: number): number =>
    PAD + (1 - (val - minVal) / range) * (H - PAD * 2);
  const n2s = (x: number): string => x.toFixed(3);

  // Build per-sub-sequence fills and polylines; no line crosses a coverage gap.
  let flatOffset = 0;
  const greenFills: React.ReactElement[] = [];
  const blueFills: React.ReactElement[] = [];
  const lines: React.ReactElement[] = [];

  for (let subIdx = 0; subIdx < coords.length; subIdx++) {
    const subSeq = coords[subIdx] ?? [];
    const subTs = timestamps?.[subIdx];
    const subCorr = altCorrFt?.[subIdx] ?? null;
    const groundAlts = groundAltsBySubSeq[subIdx] ?? null;
    const corrAlt = (c: [number, number, number], j: number): number =>
      c[2] + (stepValueAt(subCorr, subTs?.[j] ?? 0) ?? 0);

    if (subSeq.length >= 2) {
      const lastJ = subSeq.length - 1;
      const first = subSeq[0] ?? [0, 0, 0];
      const altPoints = subSeq.map(
        (c, j) => `${n2s(toX(flatOffset + j))},${n2s(toY(corrAlt(c, j)))}`,
      );

      if (groundAlts !== null) {
        // Green fill: ground line down to chart bottom.
        const groundFwdPoints = subSeq.map(
          (_, j) =>
            `${n2s(toX(flatOffset + j))},${n2s(toY(groundAlts[j] ?? 0))}`,
        );
        const greenD =
          `M ${groundFwdPoints.join(" L ")} ` +
          `L ${n2s(toX(flatOffset + lastJ))},${String(H)} ` +
          `L ${n2s(toX(flatOffset))},${String(H)} Z`;
        greenFills.push(
          <path
            key={flatOffset}
            d={greenD}
            fill="rgba(74,222,128,0.3)"
            stroke="none"
          />,
          <polyline
            key={String(flatOffset) + "-top"}
            points={groundFwdPoints.join(" ")}
            fill="none"
            stroke="rgba(74,222,128,0.75)"
            strokeWidth="1"
          />,
        );

        // Blue fill: polygon between altitude curve and ground curve.
        const groundRevPoints = subSeq.map(
          (_, j) =>
            `${n2s(toX(flatOffset + lastJ - j))},${n2s(toY(groundAlts[lastJ - j] ?? 0))}`,
        );
        const blueD = `M ${altPoints.join(" L ")} L ${groundRevPoints.join(" L ")} Z`;
        blueFills.push(
          <path
            key={flatOffset}
            d={blueD}
            fill="rgba(110,168,255,0.2)"
            stroke="none"
          />,
        );
      } else {
        // No AGL data: original blue fill from altitude to chart bottom.
        const fillD =
          `M ${n2s(toX(flatOffset))},${n2s(toY(corrAlt(first, 0)))} ` +
          subSeq
            .slice(1)
            .map(
              (c, j) =>
                `L ${n2s(toX(flatOffset + j + 1))},${n2s(toY(corrAlt(c, j + 1)))}`,
            )
            .join(" ") +
          ` L ${n2s(toX(flatOffset + lastJ))},${String(H)} L ${n2s(toX(flatOffset))},${String(H)} Z`;
        blueFills.push(
          <path
            key={flatOffset}
            d={fillD}
            fill="rgba(110,168,255,0.15)"
            stroke="none"
          />,
        );
      }

      // Altitude polyline.
      lines.push(
        <polyline
          key={flatOffset}
          points={altPoints.join(" ")}
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
  const activeGroundAlt =
    activeIdx !== null ? (flatGroundAlts[activeIdx] ?? null) : null;
  const activeAgl =
    activeGroundAlt !== null ? Math.round(activeAlt - activeGroundAlt) : null;
  const activeHx = activeIdx !== null ? toX(activeIdx) : 0;
  const activeHy = activeIdx !== null ? toY(activeAlt) : 0;
  const tooltipPct = activeIdx !== null ? (toX(activeIdx) / W) * 100 : 0;
  const tooltipLeft = activeIdx !== null ? `${tooltipPct.toFixed(2)}%` : "0%";
  // Anchor left near left edge, right near right edge, centered elsewhere,
  // so the tooltip doesn't overflow the sparkline container.
  const tooltipTransform =
    tooltipPct < 15
      ? "translateX(0)"
      : tooltipPct > 85
        ? "translateX(-100%)"
        : "translateX(-50%)";
  const tooltipText =
    activeAgl !== null
      ? `${Math.round(activeAlt).toLocaleString()} ft / ${activeAgl.toLocaleString()} agl`
      : `${Math.round(activeAlt).toLocaleString()} ft`;

  const handleTouchMove = (e: React.TouchEvent<SVGSVGElement>): void => {
    const touch = e.touches[0];
    if (!touch) return;
    const rect = e.currentTarget.getBoundingClientRect();
    const svgX = ((touch.clientX - rect.left) / rect.width) * W;
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
  };

  return (
    <div
      style={{ position: "relative", marginTop: 5 }}
      onClick={(e): void => {
        e.stopPropagation();
      }}
    >
      {activeIdx !== null && (
        <div
          style={{
            position: "absolute",
            left: tooltipLeft,
            bottom: "100%",
            transform: tooltipTransform,
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
          {tooltipText}
        </div>
      )}
      <svg
        viewBox="0 0 200 28"
        preserveAspectRatio="none"
        style={{ width: "100%", height: 20, display: "block" }}
        onTouchStart={handleTouchMove}
        onTouchMove={handleTouchMove}
        onTouchEnd={(): void => {
          onHoverIdx(null);
        }}
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
        {greenFills}
        {blueFills}
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

export function ExportMenu({
  flights,
}: {
  flights: FlightDetail[];
}): React.ReactElement {
  const [open, setOpen] = useState(false);

  const options: { label: string; action: () => void }[] = [
    {
      label: "GeoJSON",
      action: () => {
        downloadGeoJSON(flights);
      },
    },
    {
      label: "GPX",
      action: () => {
        downloadGPX(flights);
      },
    },
    {
      label: "KML",
      action: () => {
        downloadKML(flights);
      },
    },
    {
      label: "CSV",
      action: () => {
        downloadCSV(flights);
      },
    },
  ];

  return (
    <div style={{ position: "relative" }}>
      <button
        title="Export results"
        onClick={() => {
          setOpen((v) => !v);
        }}
        style={{
          padding: 3,
          borderRadius: "var(--radius-1)",
          border: "none",
          background: "transparent",
          color: "var(--fg-3)",
          cursor: "pointer",
          display: "flex",
          alignItems: "center",
          lineHeight: 0,
        }}
      >
        <Download size={14} />
      </button>
      {open && (
        <>
          <div
            style={{
              position: "fixed",
              inset: 0,
              zIndex: 99,
            }}
            onClick={() => {
              setOpen(false);
            }}
          />
          <div
            style={{
              position: "absolute",
              top: "calc(100% + 4px)",
              right: 0,
              zIndex: 100,
              background: "var(--bg-2)",
              border: "1px solid var(--line-1)",
              borderRadius: "var(--radius-1)",
              minWidth: 110,
              boxShadow: "0 4px 12px rgba(0,0,0,0.3)",
              overflow: "hidden",
            }}
          >
            {options.map(({ label, action }) => (
              <button
                key={label}
                onClick={() => {
                  action();
                  setOpen(false);
                }}
                style={{
                  display: "block",
                  width: "100%",
                  padding: "7px 12px",
                  border: "none",
                  background: "transparent",
                  color: "var(--fg-1)",
                  fontSize: 12,
                  textAlign: "left",
                  cursor: "pointer",
                }}
                onMouseEnter={(e) => {
                  e.currentTarget.style.background = "var(--bg-3, var(--bg-1))";
                }}
                onMouseLeave={(e) => {
                  e.currentTarget.style.background = "transparent";
                }}
              >
                {label}
              </button>
            ))}
          </div>
        </>
      )}
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
  windowFrom,
  queryEndDate,
  collapsed,
}: ResultsPanelProps): React.ReactElement {
  const scrollRef = useRef<HTMLDivElement>(null);
  const prevCollapsedRef = useRef(collapsed);

  useEffect(() => {
    const wasCollapsed = prevCollapsedRef.current;
    prevCollapsedRef.current = collapsed;
    // Skip when panel is off-screen — scrollIntoView would jolt the map.
    if (!selectedFlightId || !scrollRef.current || collapsed) return;
    const el = scrollRef.current.querySelector<HTMLElement>(
      `[data-flight-id="${selectedFlightId}"]`,
    );
    if (wasCollapsed) {
      // Panel just opened: wait for the 240ms slide-in transition before scrolling,
      // otherwise Chrome scrolls the overflow:hidden app container mid-animation.
      const id = setTimeout(() => {
        el?.scrollIntoView({ block: "nearest", behavior: "smooth" });
      }, 240);
      return () => {
        clearTimeout(id);
      };
    }
    el?.scrollIntoView({ block: "nearest", behavior: "smooth" });
    return undefined;
  }, [selectedFlightId, collapsed]);

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

  const trackNm = coords ? trackDistanceNm(coords) : null;
  const sp = flight.start_point.coordinates;
  const ep = flight.end_point.coordinates;
  const p2pNm = haversineNm(sp[0], sp[1], ep[0], ep[1]);

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
    ...(trackNm != null
      ? [["Track", fmtDistNm(trackNm), false] as [string, string, boolean]]
      : []),
    ["P2P", fmtDistNm(p2pNm), false],
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
        {" · "}
        {fmtDuration(flight.start_ts, flight.end_ts)}
      </div>
      {coords && (
        <SparklineChart
          coords={coords}
          timestamps={flight.timestamps}
          altCorrFt={flight.alt_correction_ft}
          aglFt={flight.path_agl_ft}
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
