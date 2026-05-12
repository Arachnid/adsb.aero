import { useEffect, useId, useRef, useState } from "react";
import { Braces, Circle, Pin, Plane, Play, Plus, Polygon, Text, Viewport, X } from "../Icons";

// ===== Types =====

export type GroupMode = "all" | "any";

interface BasePred {
  id: string;
}
interface AircraftPred extends BasePred {
  kind: "aircraft";
  icaoTypes: string[];
  emitters: string[];
}
interface StartsWithinPred extends BasePred {
  kind: "starts_within";
  shape: "none" | "circle" | "polygon" | "viewport";
  lat: number | null;
  lng: number | null;
  radiusNm: number;
  polygon: [number, number][] | null;
  timeFrom: string;
  timeTo: string;
}
interface EndsWithinPred extends BasePred {
  kind: "ends_within";
  shape: "none" | "circle" | "polygon" | "viewport";
  lat: number | null;
  lng: number | null;
  radiusNm: number;
  polygon: [number, number][] | null;
  timeFrom: string;
  timeTo: string;
}
interface IntersectsPred extends BasePred {
  kind: "region";
  regionName: string;
  shape: "none" | "circle" | "polygon" | "viewport";
  polygon: [number, number][] | null;
  lat: number | null;
  lng: number | null;
  radiusNm: number;
  altMin: number | null;
  altMax: number | null;
  timeFrom: string;
  timeTo: string;
}
interface CallsignPred extends BasePred {
  kind: "callsign";
  pattern: string;
}

export type UIPredicate =
  | AircraftPred
  | StartsWithinPred
  | EndsWithinPred
  | IntersectsPred
  | CallsignPred;

export interface FilterGroup {
  id: string;
  kind: "group";
  mode: GroupMode;
  items: QueryItem[];
}

export type QueryItem = UIPredicate | FilterGroup;

export function makeId(): string {
  return Math.random().toString(36).slice(2, 8);
}

type AddKind = UIPredicate["kind"] | "group_all" | "group_any";

function makeItem(kind: AddKind, regionCount = 0): QueryItem {
  const id = makeId();
  if (kind === "group_all" || kind === "group_any") {
    return { id, kind: "group", mode: kind === "group_all" ? "all" : "any", items: [] };
  }
  if (kind === "starts_within" || kind === "ends_within") {
    return { id, kind, shape: "none", lat: null, lng: null, radiusNm: 2, polygon: null, timeFrom: "", timeTo: "" };
  }
  if (kind === "region") {
    return {
      id, kind, regionName: "Region " + String(regionCount + 1), shape: "none",
      polygon: null, lat: null, lng: null, radiusNm: 2,
      altMin: null, altMax: null, timeFrom: "", timeTo: "",
    };
  }
  if (kind === "aircraft") {
    return { id, kind, icaoTypes: [], emitters: [] };
  }
  return { id, kind: "callsign", pattern: "" };
}

// ===== Reference data =====

const ICAO_TYPES: string[] = [
  "B738", "A320", "A321", "B737", "A319", "A20N", "B77W", "B789", "A359",
  "C172", "C152", "PA28", "DA42", "SR22", "P28A", "BE36",
  "E190", "E195", "AT76", "DH8D", "CRJ9",
  "EC35", "AS50", "R44", "EC30",
  "GLF6", "F2TH", "C56X", "C25A", "BE40",
];

const EMITTER_CATEGORIES: { code: string; label: string }[] = [
  { code: "A1", label: "Light (<15500 lbs)" },
  { code: "A2", label: "Small (15500-75000 lbs)" },
  { code: "A3", label: "Large (75000-300000 lbs)" },
  { code: "A5", label: "Heavy (>300000 lbs)" },
  { code: "A7", label: "Rotorcraft" },
  { code: "B1", label: "Glider/Sailplane" },
  { code: "B2", label: "Lighter-than-air" },
  { code: "B6", label: "UAV" },
];

// ===== Validation =====

export function isPredValid(pred: UIPredicate): boolean {
  switch (pred.kind) {
    case "aircraft":
      return pred.icaoTypes.length > 0 || pred.emitters.length > 0;
    case "callsign":
      return pred.pattern.trim() !== "";
    case "starts_within":
    case "ends_within": {
      const hasTime = pred.timeFrom !== "" || pred.timeTo !== "";
      if (pred.shape === "none") return hasTime;
      if (pred.shape === "viewport") return true;
      if (pred.shape === "circle") return pred.lat !== null && pred.lng !== null;
      return pred.polygon !== null && pred.polygon.length >= 3;
    }
    case "region": {
      const hasTime = pred.timeFrom !== "" || pred.timeTo !== "";
      if (pred.shape === "none") return hasTime;
      if (pred.shape === "viewport") return true;
      if (pred.shape === "circle") {
        if (pred.lat === null) return false;
      } else if (pred.polygon === null || pred.polygon.length < 3) {
        return false;
      }
      if (pred.altMin !== null && pred.altMax !== null && pred.altMin > pred.altMax) return false;
      return true;
    }
  }
}

export function isGroupValid(group: FilterGroup): boolean {
  return group.items.every((item) =>
    item.kind === "group" ? isGroupValid(item) : isPredValid(item)
  );
}

// ===== Shared sub-components =====

function PredCard({
  icon,
  name,
  onRemove,
  children,
  invalid,
}: {
  icon: React.ReactNode;
  name: string;
  onRemove: () => void;
  children: React.ReactNode;
  invalid?: boolean;
}): React.ReactElement {
  return (
    <div className={"pred" + (invalid ? " pred--invalid" : "")}>
      <div className="pred-head">
        <span className="pred-icon">{icon}</span>
        <span className="pred-name">{name}</span>
        <button className="pred-x" onClick={onRemove} title="Remove filter">
          <X size={12} />
        </button>
      </div>
      <div className="pred-body">{children}</div>
    </div>
  );
}

function FieldLabel({ children }: { children: React.ReactNode }): React.ReactElement {
  return <div className="field-label">{children}</div>;
}

type Shape = "none" | "circle" | "polygon" | "viewport";

function ShapeToggle({
  shape,
  onChange,
}: {
  shape: Shape;
  onChange: (s: Shape) => void;
}): React.ReactElement {
  return (
    <div className="shape-toggle">
      <button className={shape === "none" ? "active" : ""} onClick={() => { onChange("none"); }}>
        —
      </button>
      <button className={shape === "circle" ? "active" : ""} onClick={() => { onChange("circle"); }}>
        <Circle size={12} /> Circle
      </button>
      <button className={shape === "polygon" ? "active" : ""} onClick={() => { onChange("polygon"); }}>
        <Polygon size={12} /> Polygon
      </button>
      <button className={shape === "viewport" ? "active" : ""} onClick={() => { onChange("viewport"); }}>
        <Viewport size={12} /> Viewport
      </button>
    </div>
  );
}

type ChipOption = string | { code: string; label: string };

function optCode(o: ChipOption): string {
  return typeof o === "string" ? o : o.code;
}
function optLabel(o: ChipOption): string | null {
  return typeof o === "string" ? null : o.label;
}

function ChipMultiSelect({
  label,
  value,
  options,
  onChange,
  placeholder = "Type to filter…",
}: {
  label?: string;
  value: string[];
  options: ChipOption[];
  onChange: (v: string[]) => void;
  placeholder?: string;
}): React.ReactElement {
  const [open, setOpen] = useState(false);
  const [filter, setFilter] = useState("");
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onDoc = (e: MouseEvent): void => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", onDoc);
    return (): void => { document.removeEventListener("mousedown", onDoc); };
  }, [open]);

  const filtered = options.filter((o) => {
    const txt = (typeof o === "string" ? o : o.code + " " + o.label).toLowerCase();
    return txt.includes(filter.toLowerCase());
  });

  function toggle(opt: ChipOption): void {
    const code = optCode(opt);
    if (value.includes(code)) {
      onChange(value.filter((v) => v !== code));
    } else {
      onChange([...value, code]);
    }
    setOpen(false);
  }

  return (
    <div>
      {label && <FieldLabel>{label}</FieldLabel>}
      <div className="chip-group">
        {value.map((v) => (
          <span key={v} className="chip">
            {v}
            <button onClick={() => { onChange(value.filter((x) => x !== v)); }} aria-label="Remove">
              ×
            </button>
          </span>
        ))}
        <div ref={ref} style={{ position: "relative" }}>
          <button className="chip-add" onClick={() => { setOpen((prev) => !prev); }}>
            {value.length === 0 ? "+ choose" : "+ add"}
          </button>
          {open && (
            <div className="chip-dropdown">
              <input
                autoFocus
                placeholder={placeholder}
                value={filter}
                onChange={(e) => { setFilter(e.target.value); }}
              />
              {filtered.slice(0, 50).map((opt) => {
                const code = optCode(opt);
                const meta = optLabel(opt);
                const sel = value.includes(code);
                return (
                  <div
                    key={code}
                    className={"chip-opt" + (sel ? " selected" : "")}
                    onMouseDown={(e) => { e.preventDefault(); }}
                    onClick={() => { toggle(opt); }}
                  >
                    <span>{sel ? "✓ " : "  "}{code}</span>
                    {meta && <span className="chip-opt-meta">{meta}</span>}
                  </div>
                );
              })}
              {filtered.length === 0 && (
                <div className="chip-opt" style={{ color: "var(--fg-3)" }}>
                  No matches
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function MiniMapPreview({
  lat: _lat,
  lng: _lng,
  radiusNm,
}: {
  lat: number | null;
  lng: number | null;
  radiusNm: number;
}): React.ReactElement {
  const patternId = useId().replace(/:/g, "");
  const w = 100, h = 100;
  const r = Math.max(8, Math.min(45, radiusNm * 0.8));
  const cx = 50, cy = 50;
  const vb = "0 0 " + String(w) + " " + String(h);
  return (
    <div className="minimap">
      <svg viewBox={vb} width="100%" height="100%" preserveAspectRatio="none">
        <defs>
          <pattern id={patternId} width="10" height="10" patternUnits="userSpaceOnUse">
            <path d="M10 0H0V10" fill="none" stroke="var(--line-1)" strokeWidth="0.4" />
          </pattern>
        </defs>
        <rect width={w} height={h} fill="var(--bg-1)" />
        <rect width={w} height={h} fill={"url(#" + patternId + ")"} />
        <path
          d="M 20 30 Q 30 22 45 28 Q 55 35 50 50 Q 60 60 55 75 Q 35 80 25 65 Q 15 50 20 30 Z"
          fill="var(--bg-3)"
          stroke="var(--line-2)"
          strokeWidth="0.6"
          opacity="0.7"
        />
        <circle
          cx={cx}
          cy={cy}
          r={r}
          fill="var(--accent-soft)"
          stroke="var(--accent)"
          strokeWidth="1"
          strokeDasharray="2 2"
        />
        <circle cx={cx} cy={cy} r="2" fill="var(--accent)" stroke="var(--bg-1)" strokeWidth="1" />
      </svg>
    </div>
  );
}

// ===== Predicate cards =====

function AircraftCard({
  pred,
  onChange,
  onRemove,
}: {
  pred: AircraftPred;
  onChange: (p: AircraftPred) => void;
  onRemove: () => void;
}): React.ReactElement {
  return (
    <PredCard icon={<Plane />} name="Aircraft" onRemove={onRemove} invalid={!isPredValid(pred)}>
      <ChipMultiSelect
        label="ICAO type"
        value={pred.icaoTypes}
        options={ICAO_TYPES}
        onChange={(v) => { onChange({ ...pred, icaoTypes: v }); }}
      />
      <ChipMultiSelect
        label="Emitter category"
        value={pred.emitters}
        options={EMITTER_CATEGORIES}
        onChange={(v) => { onChange({ ...pred, emitters: v }); }}
      />
    </PredCard>
  );
}

function PointRadiusCard({
  pred,
  onChange,
  onRemove,
  onArmPicker,
  isPicking,
  onArmDraw,
  isDrawing,
  name,
}: {
  pred: StartsWithinPred | EndsWithinPred;
  onChange: (p: StartsWithinPred | EndsWithinPred) => void;
  onRemove: () => void;
  onArmPicker: () => void;
  isPicking: boolean;
  onArmDraw: () => void;
  isDrawing: boolean;
  name: string;
}): React.ReactElement {
  return (
    <PredCard icon={<Pin />} name={name} onRemove={onRemove} invalid={!isPredValid(pred)}>
      <ShapeToggle
        shape={pred.shape}
        onChange={(s) => { onChange({ ...pred, shape: s }); }}
      />
      {pred.shape === "circle" ? (
        <>
          <MiniMapPreview lat={pred.lat} lng={pred.lng} radiusNm={pred.radiusNm} />
          <div className="slider-row">
            <label>Radius</label>
            <input
              type="range"
              min="1"
              max="100"
              step="1"
              value={pred.radiusNm}
              onChange={(e) => { onChange({ ...pred, radiusNm: +e.target.value }); }}
            />
            <span className="val">{pred.radiusNm.toFixed(0)} nm</span>
          </div>
          {pred.lat != null ? (
            <div style={{ fontFamily: "JetBrains Mono, monospace", fontSize: 10.5, color: "var(--fg-2)" }}>
              {pred.lat.toFixed(3)}°N, {Math.abs(pred.lng ?? 0).toFixed(3)}°
              {(pred.lng ?? 0) < 0 ? "W" : "E"}
            </div>
          ) : (
            <div style={{ fontFamily: "JetBrains Mono, monospace", fontSize: 10.5, color: "var(--fg-3)" }}>
              No point selected
            </div>
          )}
          <div className="minimap-buttons">
            <button className={"btn-secondary" + (isPicking ? " armed" : "")} onClick={onArmPicker}>
              {isPicking ? "Click on map…" : "Pick on map"}
            </button>
          </div>
        </>
      ) : pred.shape === "polygon" ? (
        <>
          {pred.polygon ? (
            <div className="polygon-summary">
              ◆ Polygon <span style={{ color: "var(--fg-3)", fontSize: 10 }}>{pred.polygon.length} pts</span>
            </div>
          ) : (
            <div style={{ fontFamily: "JetBrains Mono, monospace", fontSize: 10.5, color: "var(--fg-3)" }}>
              No polygon defined
            </div>
          )}
          <div className="minimap-buttons">
            <button className={"btn-secondary" + (isDrawing ? " armed" : "")} onClick={onArmDraw}>
              {isDrawing ? "Drawing… (dbl-click to finish)" : pred.polygon ? "Redraw" : "Draw on map"}
            </button>
          </div>
        </>
      ) : pred.shape === "viewport" ? (
        <div style={{ fontFamily: "JetBrains Mono, monospace", fontSize: 10.5, color: "var(--fg-2)" }}>
          Uses current map viewport
        </div>
      ) : null}
      <div style={{ marginTop: 4 }}>
        <FieldLabel>From</FieldLabel>
        <input
          className="text-field mono"
          type="datetime-local"
          value={pred.timeFrom}
          onChange={(e) => { onChange({ ...pred, timeFrom: e.target.value }); }}
        />
      </div>
      <div>
        <FieldLabel>To</FieldLabel>
        <input
          className="text-field mono"
          type="datetime-local"
          value={pred.timeTo}
          onChange={(e) => { onChange({ ...pred, timeTo: e.target.value }); }}
        />
      </div>
    </PredCard>
  );
}

function IntersectsCard({
  pred,
  onChange,
  onRemove,
  onArmDraw,
  isDrawing,
  onArmPicker,
  isPicking,
  name,
}: {
  pred: IntersectsPred;
  onChange: (p: IntersectsPred) => void;
  onRemove: () => void;
  onArmDraw: () => void;
  isDrawing: boolean;
  onArmPicker: () => void;
  isPicking: boolean;
  name: string;
}): React.ReactElement {
  return (
    <PredCard icon={<Polygon />} name={name} onRemove={onRemove} invalid={!isPredValid(pred)}>
      <ShapeToggle
        shape={pred.shape}
        onChange={(s) => { onChange({ ...pred, shape: s }); }}
      />
      {pred.shape === "polygon" ? (
        <>
          {pred.polygon ? (
            <div className="polygon-summary">
              ◆ {pred.regionName} <span style={{ color: "var(--fg-3)", fontSize: 10 }}>{pred.polygon.length} pts</span>
            </div>
          ) : (
            <div style={{ fontFamily: "JetBrains Mono, monospace", fontSize: 10.5, color: "var(--fg-3)" }}>
              No region defined
            </div>
          )}
          <div className="minimap-buttons">
            <button className={"btn-secondary" + (isDrawing ? " armed" : "")} onClick={onArmDraw}>
              {isDrawing ? "Drawing… (dbl-click to finish)" : pred.polygon ? "Redraw" : "Draw on map"}
            </button>
          </div>
        </>
      ) : pred.shape === "circle" ? (
        <>
          <MiniMapPreview lat={pred.lat} lng={pred.lng} radiusNm={pred.radiusNm} />
          <div className="slider-row">
            <label>Radius</label>
            <input
              type="range"
              min="1"
              max="100"
              step="1"
              value={pred.radiusNm}
              onChange={(e) => { onChange({ ...pred, radiusNm: +e.target.value }); }}
            />
            <span className="val">{pred.radiusNm.toFixed(0)} nm</span>
          </div>
          {pred.lat != null ? (
            <div style={{ fontFamily: "JetBrains Mono, monospace", fontSize: 10.5, color: "var(--fg-2)" }}>
              {pred.lat.toFixed(3)}°N, {Math.abs(pred.lng ?? 0).toFixed(3)}°
              {(pred.lng ?? 0) < 0 ? "W" : "E"}
            </div>
          ) : (
            <div style={{ fontFamily: "JetBrains Mono, monospace", fontSize: 10.5, color: "var(--fg-3)" }}>
              No point selected
            </div>
          )}
          <div className="minimap-buttons">
            <button className={"btn-secondary" + (isPicking ? " armed" : "")} onClick={onArmPicker}>
              {isPicking ? "Click on map…" : "Pick on map"}
            </button>
          </div>
        </>
      ) : pred.shape === "viewport" ? (
        <div style={{ fontFamily: "JetBrains Mono, monospace", fontSize: 10.5, color: "var(--fg-2)" }}>
          Uses current map viewport
        </div>
      ) : null}
      {pred.shape !== "none" && (
        <div className="pred-row" style={{ marginTop: 4 }}>
          <div>
            <FieldLabel>Alt min (ft)</FieldLabel>
            <input
              className="text-field mono"
              type="number"
              placeholder="0"
              value={pred.altMin ?? ""}
              onChange={(e) => {
                onChange({ ...pred, altMin: e.target.value === "" ? null : +e.target.value });
              }}
            />
          </div>
          <div>
            <FieldLabel>Alt max (ft)</FieldLabel>
            <input
              className="text-field mono"
              type="number"
              placeholder="∞"
              value={pred.altMax ?? ""}
              onChange={(e) => {
                onChange({ ...pred, altMax: e.target.value === "" ? null : +e.target.value });
              }}
            />
          </div>
        </div>
      )}
      <div style={{ marginTop: 4 }}>
        <FieldLabel>From</FieldLabel>
        <input
          className="text-field mono"
          type="datetime-local"
          value={pred.timeFrom}
          onChange={(e) => { onChange({ ...pred, timeFrom: e.target.value }); }}
        />
      </div>
      <div>
        <FieldLabel>To</FieldLabel>
        <input
          className="text-field mono"
          type="datetime-local"
          value={pred.timeTo}
          onChange={(e) => { onChange({ ...pred, timeTo: e.target.value }); }}
        />
      </div>
    </PredCard>
  );
}

function CallsignCard({
  pred,
  onChange,
  onRemove,
}: {
  pred: CallsignPred;
  onChange: (p: CallsignPred) => void;
  onRemove: () => void;
}): React.ReactElement {
  return (
    <PredCard icon={<Text />} name="Callsign" onRemove={onRemove} invalid={!isPredValid(pred)}>
      <div>
        <FieldLabel>Regex pattern</FieldLabel>
        <input
          className="text-field mono"
          placeholder="^BAW.*"
          value={pred.pattern}
          onChange={(e) => { onChange({ ...pred, pattern: e.target.value }); }}
        />
      </div>
    </PredCard>
  );
}

// ===== Add filter menu =====

const FILTER_OPTS: { kind: AddKind; icon: React.ReactNode; label: string; desc: string }[] = [
  { kind: "aircraft", icon: <Plane />, label: "Aircraft", desc: "Type, emitter category" },
  { kind: "starts_within", icon: <Pin />, label: "Starts within", desc: "Area, time, or both" },
  { kind: "ends_within", icon: <Pin />, label: "Ends within", desc: "Area, time, or both" },
  { kind: "region", icon: <Polygon />, label: "Within", desc: "Area, altitude, time" },
  { kind: "callsign", icon: <Text />, label: "Callsign", desc: "Regex match" },
  { kind: "group_all", icon: <Braces />, label: "All of", desc: "All sub-filters must match" },
  { kind: "group_any", icon: <Braces />, label: "Any of", desc: "At least one sub-filter matches" },
];

function AddFilterMenu({ onAdd }: { onAdd: (kind: AddKind) => void }): React.ReactElement {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onDoc = (e: MouseEvent): void => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", onDoc);
    return (): void => { document.removeEventListener("mousedown", onDoc); };
  }, [open]);

  return (
    <div ref={ref} style={{ position: "relative" }}>
      <button className="add-filter" onClick={() => { setOpen((v) => !v); }}>
        <Plus size={14} /> Add filter
      </button>
      {open && (
        <div className="add-filter-menu">
          {FILTER_OPTS.map((o) => (
            <button key={o.kind} onClick={() => { onAdd(o.kind); setOpen(false); }}>
              <span style={{ color: "var(--accent)" }}>{o.icon}</span>
              <span>
                <div>{o.label}</div>
                <div className="desc">{o.desc}</div>
              </span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

// ===== Predicate renderer =====

function PredicateRenderer({
  pred,
  onChange,
  onRemove,
  onArmPicker,
  isPicking,
  onArmDraw,
  isDrawing,
  name,
}: {
  pred: UIPredicate;
  onChange: (p: UIPredicate) => void;
  onRemove: () => void;
  onArmPicker: () => void;
  isPicking: boolean;
  onArmDraw: () => void;
  isDrawing: boolean;
  name: string;
}): React.ReactElement | null {
  switch (pred.kind) {
    case "aircraft":
      return <AircraftCard pred={pred} onChange={(p) => { onChange(p); }} onRemove={onRemove} />;
    case "starts_within":
    case "ends_within":
      return (
        <PointRadiusCard
          pred={pred}
          onChange={(p) => { onChange(p); }}
          onRemove={onRemove}
          onArmPicker={onArmPicker}
          isPicking={isPicking}
          onArmDraw={onArmDraw}
          isDrawing={isDrawing}
          name={name}
        />
      );
    case "region":
      return (
        <IntersectsCard
          pred={pred}
          onChange={(p) => { onChange(p); }}
          onRemove={onRemove}
          onArmDraw={onArmDraw}
          isDrawing={isDrawing}
          onArmPicker={onArmPicker}
          isPicking={isPicking}
          name={name}
        />
      );
    case "callsign":
      return <CallsignCard pred={pred} onChange={(p) => { onChange(p); }} onRemove={onRemove} />;
  }
}

// ===== Group block (recursive) =====

interface GroupBlockProps {
  group: FilterGroup;
  onChange: (g: FilterGroup) => void;
  onRemove?: () => void;
  onArmPicker: (id: string) => void;
  pickingId: string | null;
  onArmDraw: (id: string) => void;
  drawingId: string | null;
  regionCount: number;
  labels: Map<string, string>;
  noAddFilter?: boolean;
}

function GroupBlock({
  group,
  onChange,
  onRemove,
  onArmPicker,
  pickingId,
  onArmDraw,
  drawingId,
  regionCount,
  labels,
  noAddFilter,
}: GroupBlockProps): React.ReactElement {
  const updateChild = (childId: string, next: QueryItem): void => {
    onChange({ ...group, items: group.items.map((item) => (item.id === childId ? next : item)) });
  };
  const removeChild = (childId: string): void => {
    onChange({ ...group, items: group.items.filter((item) => item.id !== childId) });
  };
  const addChild = (kind: AddKind): void => {
    const rc = group.items.filter((i) => i.kind === "region").length + regionCount;
    onChange({ ...group, items: [...group.items, makeItem(kind, rc)] });
  };

  const isRoot = onRemove === undefined;

  return (
    <div className={isRoot ? "group-root" : "filter-group"}>
      {!isRoot && (
        <div className="filter-group-header">
          <div className="match-mode-toggle">
            <button
              className={group.mode === "all" ? "active" : ""}
              onClick={() => { onChange({ ...group, mode: "all" }); }}
            >
              ALL
            </button>
            <button
              className={group.mode === "any" ? "active" : ""}
              onClick={() => { onChange({ ...group, mode: "any" }); }}
            >
              ANY
            </button>
          </div>
          <span className="group-mode-label">
            {group.mode === "all" ? "All filters must match" : "Any filter must match"}
          </span>
          {onRemove !== undefined && (
            <button className="pred-x" onClick={onRemove} title="Remove group">
              <X size={12} />
            </button>
          )}
        </div>
      )}

      <div className={isRoot ? "group-root-body" : "filter-group-body"}>
        {group.items.length === 0 && (
          <div style={{ color: "var(--fg-3)", fontSize: 12, textAlign: "center", padding: "20px 0" }}>
            {isRoot ? (
              <>
                <div style={{ marginBottom: 8, opacity: 0.4 }}>
                  <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
                    <circle cx="11" cy="11" r="8" /><path d="M21 21l-4.35-4.35" />
                  </svg>
                </div>
                <div>No filters yet.</div>
                <div style={{ marginTop: 4 }}>Add a filter below to get started.</div>
              </>
            ) : (
              <div>Empty group</div>
            )}
          </div>
        )}
        {group.items.map((item) =>
          item.kind === "group" ? (
            <GroupBlock
              key={item.id}
              group={item}
              onChange={(g) => { updateChild(item.id, g); }}
              onRemove={() => { removeChild(item.id); }}
              onArmPicker={onArmPicker}
              pickingId={pickingId}
              onArmDraw={onArmDraw}
              drawingId={drawingId}
              regionCount={regionCount}
              labels={labels}
            />
          ) : (
            <PredicateRenderer
              key={item.id}
              pred={item}
              onChange={(p) => { updateChild(item.id, p); }}
              onRemove={() => { removeChild(item.id); }}
              onArmPicker={() => { onArmPicker(item.id); }}
              isPicking={pickingId === item.id}
              onArmDraw={() => { onArmDraw(item.id); }}
              isDrawing={drawingId === item.id}
              name={labels.get(item.id) ?? (item.kind === "aircraft" ? "Aircraft" : "Callsign")}
            />
          )
        )}
        {!noAddFilter && <AddFilterMenu onAdd={addChild} />}
      </div>
    </div>
  );
}

// ===== Public exports =====

export interface QueryBuilderBodyProps {
  rootGroup: FilterGroup;
  onGroupChange: (g: FilterGroup) => void;
  onArmPicker: (id: string) => void;
  pickingId: string | null;
  onArmDraw: (id: string) => void;
  drawingId: string | null;
}

export function computeLabels(group: FilterGroup): Map<string, string> {
  const result = new Map<string, string>();
  const counts: Record<string, number> = {};
  function walk(g: FilterGroup): void {
    for (const item of g.items) {
      if (item.kind === "group") { walk(item); continue; }
      if (item.kind !== "starts_within" && item.kind !== "ends_within" && item.kind !== "region") continue;
      const base =
        item.kind === "starts_within" ? "Starts Within" :
        item.kind === "ends_within" ? "Ends Within" :
        "Within";
      if (item.shape === "none" || item.shape === "viewport") {
        result.set(item.id, base);
      } else {
        counts[base] = (counts[base] ?? 0) + 1;
        result.set(item.id, `${base} ${counts[base]}`);
      }
    }
  }
  walk(group);
  return result;
}

function countRegions(g: FilterGroup): number {
  return g.items.reduce<number>((n, item) => {
    if (item.kind === "group") return n + countRegions(item);
    if (item.kind === "region") return n + 1;
    return n;
  }, 0);
}

export function QueryBuilderBody({
  rootGroup,
  onGroupChange,
  onArmPicker,
  pickingId,
  onArmDraw,
  drawingId,
}: QueryBuilderBodyProps): React.ReactElement {
  return (
    <GroupBlock
      group={rootGroup}
      onChange={onGroupChange}
      onArmPicker={onArmPicker}
      pickingId={pickingId}
      onArmDraw={onArmDraw}
      drawingId={drawingId}
      regionCount={countRegions(rootGroup)}
      labels={computeLabels(rootGroup)}
      noAddFilter
    />
  );
}

export function QueryBuilderAddMenu({
  rootGroup,
  onGroupChange,
}: {
  rootGroup: FilterGroup;
  onGroupChange: (g: FilterGroup) => void;
}): React.ReactElement {
  const onAdd = (kind: AddKind): void => {
    const rc = countRegions(rootGroup);
    onGroupChange({ ...rootGroup, items: [...rootGroup.items, makeItem(kind, rc)] });
  };
  return <AddFilterMenu onAdd={onAdd} />;
}

export interface QueryBuilderFooterProps {
  rootGroup: FilterGroup;
  onRun: () => void;
}

export function QueryBuilderFooter({ rootGroup, onRun }: QueryBuilderFooterProps): React.ReactElement {
  const enabled = rootGroup.items.length > 0 && isGroupValid(rootGroup);
  return (
    <button className="run-btn" onClick={onRun} disabled={!enabled}>
      <Play /> Run query
    </button>
  );
}

export function updatePredInGroup(
  group: FilterGroup,
  predId: string,
  update: (p: UIPredicate) => UIPredicate
): FilterGroup {
  return {
    ...group,
    items: group.items.map((item) => {
      if (item.kind === "group") return updatePredInGroup(item, predId, update);
      if (item.id === predId) return update(item);
      return item;
    }),
  };
}

export function countPredicates(group: FilterGroup): number {
  return group.items.reduce<number>((n, item) => {
    if (item.kind === "group") return n + countPredicates(item);
    return n + 1;
  }, 0);
}
