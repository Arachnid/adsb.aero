import { useEffect, useRef, useState } from "react";
import {
  DatePicker,
  DateInput,
  DateSegment,
  Group,
  Button,
  Popover,
  Dialog,
  Calendar,
  CalendarGrid,
  CalendarGridBody,
  CalendarGridHeader,
  CalendarHeaderCell,
  CalendarCell,
  Heading,
} from "react-aria-components";
import { parseDate, parseDateTime } from "@internationalized/date";
import type { CalendarDate, CalendarDateTime } from "@internationalized/date";
import { Braces, Circle, Pin, Plane, Play, Plus, Polygon, Text, Viewport, X } from "../Icons";
import type { DataRange } from "../../lib/api";

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
  squawkCodes: string[];
}
interface AlwaysWithinPred extends BasePred {
  kind: "always_within";
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
  squawkCodes: string[];
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
  | AlwaysWithinPred
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
    return {
      id,
      kind,
      shape: "circle",
      lat: null,
      lng: null,
      radiusNm: 1,
      polygon: null,
      timeFrom: "",
      timeTo: "",
    };
  }
  if (kind === "region" || kind === "always_within") {
    return {
      id,
      kind,
      regionName: "Region " + String(regionCount + 1),
      shape: "polygon",
      polygon: null,
      lat: null,
      lng: null,
      radiusNm: 25,
      altMin: null,
      altMax: null,
      timeFrom: "",
      timeTo: "",
      squawkCodes: [],
    };
  }
  if (kind === "aircraft") {
    return { id, kind, icaoTypes: [], emitters: [] };
  }
  return { id, kind: "callsign", pattern: "" };
}

// ===== Reference data =====

const ICAO_TYPES: string[] = [
  "B738",
  "A320",
  "A321",
  "B737",
  "A319",
  "A20N",
  "B77W",
  "B789",
  "A359",
  "C172",
  "C152",
  "PA28",
  "DA42",
  "SR22",
  "P28A",
  "BE36",
  "E190",
  "E195",
  "AT76",
  "DH8D",
  "CRJ9",
  "EC35",
  "AS50",
  "R44",
  "EC30",
  "GLF6",
  "F2TH",
  "C56X",
  "C25A",
  "BE40",
];

const EMITTER_CATEGORIES: { code: string; label: string }[] = [
  { code: "A1", label: "Light (<15,500 lb)" },
  { code: "A2", label: "Small (15,500–75,000 lb)" },
  { code: "A3", label: "Large (75,000–300,000 lb)" },
  { code: "A4", label: "High vortex (757-type)" },
  { code: "A5", label: "Heavy (>300,000 lb)" },
  { code: "A6", label: "High performance" },
  { code: "A7", label: "Rotorcraft" },
  { code: "B1", label: "Glider / sailplane" },
  { code: "B2", label: "Lighter-than-air" },
  { code: "B3", label: "Parachutist / skydiver" },
  { code: "B4", label: "Ultralight / hang-glider" },
  { code: "B6", label: "UAV" },
  { code: "B7", label: "Space / trans-atmospheric" },
  { code: "C1", label: "Emergency vehicle" },
  { code: "C2", label: "Service vehicle" },
  { code: "C3", label: "Ground obstruction" },
];

// ===== Global date range =====

export interface GlobalDateRange {
  from: string; // "YYYY-MM-DD" inclusive
  to: string; // "YYYY-MM-DD" inclusive
}

const MAX_RANGE_DAYS = 6; // 7-day inclusive window = 6-day difference

export function isDateRangeValid(range: GlobalDateRange): boolean {
  if (!range.from || !range.to) return false;
  try {
    const f = parseDate(range.from);
    const t = parseDate(range.to);
    const diffMs = t.toDate("UTC").getTime() - f.toDate("UTC").getTime();
    return diffMs >= 0 && diffMs <= MAX_RANGE_DAYS * 86400000;
  } catch {
    return false;
  }
}

/** Convert an inclusive GlobalDateRange to the exclusive ISO strings the API expects. */
export function dateRangeToApiParams(range: GlobalDateRange): {
  startFrom: string;
  startTo: string;
} {
  const toDate = parseDate(range.to).add({ days: 1 });
  return {
    startFrom: range.from + "T00:00:00Z",
    startTo: toDate.toString() + "T00:00:00Z",
  };
}

export function QueryBuilderDateRange({
  range,
  onChange,
  dataRange,
}: {
  range: GlobalDateRange;
  onChange: (r: GlobalDateRange) => void;
  dataRange: DataRange | null;
}): React.ReactElement {
  const minValue =
    dataRange?.first_date !== undefined && dataRange.first_date !== null
      ? parseDate(dataRange.first_date)
      : undefined;
  const maxValue =
    dataRange?.last_date !== undefined && dataRange.last_date !== null
      ? parseDate(dataRange.last_date)
      : undefined;

  const fromValue = range.from ? parseDate(range.from) : null;
  const toValue = range.to ? parseDate(range.to) : null;

  const toMaxValue = fromValue
    ? maxValue
      ? fromValue.add({ days: MAX_RANGE_DAYS }).compare(maxValue) < 0
        ? fromValue.add({ days: MAX_RANGE_DAYS })
        : maxValue
      : fromValue.add({ days: MAX_RANGE_DAYS })
    : maxValue;

  const handleFromChange = (d: CalendarDate | null): void => {
    const newFrom = d ? d.toString() : "";
    let newTo = range.to;
    if (d && range.to) {
      const maxTo = d.add({ days: MAX_RANGE_DAYS });
      if (parseDate(range.to).compare(maxTo) > 0) newTo = maxTo.toString();
    }
    onChange({ from: newFrom, to: newTo });
  };

  const handleToChange = (d: CalendarDate | null): void => {
    onChange({ ...range, to: d ? d.toString() : "" });
  };

  const handleReset = (): void => {
    if (!dataRange?.last_date) return;
    const last = new Date(dataRange.last_date + "T00:00:00Z");
    last.setUTCDate(last.getUTCDate() - MAX_RANGE_DAYS);
    onChange({ from: last.toISOString().slice(0, 10), to: dataRange.last_date });
  };

  const bothSet = range.from && range.to;
  let error: string | null = null;
  if (bothSet) {
    try {
      const f = parseDate(range.from);
      const t = parseDate(range.to);
      const diffMs = t.toDate("UTC").getTime() - f.toDate("UTC").getTime();
      if (diffMs < 0) error = "End must be after start";
      else if (diffMs > MAX_RANGE_DAYS * 86400000) error = "Range must be 7 days or less";
    } catch {
      error = "Invalid date";
    }
  }

  return (
    <div className="date-range-bar">
      <div className="date-range-bar-header">
        <div className="date-range-bar-label">Departure window</div>
        {dataRange?.last_date && (
          <button className="date-range-reset" onClick={handleReset}>
            ↺ Last 7 days
          </button>
        )}
      </div>
      <div className="date-range-bar-row">
        <div className="date-range-bar-field">
          <FieldLabel>From</FieldLabel>
          <DatePicker<CalendarDate>
            granularity="day"
            value={fromValue}
            onChange={handleFromChange}
            {...(minValue !== undefined ? { minValue } : {})}
            {...(maxValue !== undefined ? { maxValue } : {})}
          >
            <Group className="datetime-date-group">
              <DateInput className="datetime-date-input">
                {(segment) => <DateSegment segment={segment} />}
              </DateInput>
              <Button className="datetime-cal-btn">▾</Button>
            </Group>
            <Popover className="datetime-popover">
              <Dialog>
                <Calendar>
                  <header className="datetime-cal-header">
                    <Button slot="previous">◀</Button>
                    <Heading />
                    <Button slot="next">▶</Button>
                  </header>
                  <CalendarGrid>
                    <CalendarGridHeader>
                      {(day) => <CalendarHeaderCell>{day}</CalendarHeaderCell>}
                    </CalendarGridHeader>
                    <CalendarGridBody>{(date) => <CalendarCell date={date} />}</CalendarGridBody>
                  </CalendarGrid>
                </Calendar>
              </Dialog>
            </Popover>
          </DatePicker>
        </div>
        <div className="date-range-bar-field">
          <FieldLabel>To</FieldLabel>
          <DatePicker<CalendarDate>
            granularity="day"
            value={toValue}
            onChange={handleToChange}
            {...(minValue !== undefined ? { minValue } : {})}
            {...(toMaxValue !== undefined ? { maxValue: toMaxValue } : {})}
          >
            <Group className="datetime-date-group">
              <DateInput className="datetime-date-input">
                {(segment) => <DateSegment segment={segment} />}
              </DateInput>
              <Button className="datetime-cal-btn">▾</Button>
            </Group>
            <Popover className="datetime-popover">
              <Dialog>
                <Calendar>
                  <header className="datetime-cal-header">
                    <Button slot="previous">◀</Button>
                    <Heading />
                    <Button slot="next">▶</Button>
                  </header>
                  <CalendarGrid>
                    <CalendarGridHeader>
                      {(day) => <CalendarHeaderCell>{day}</CalendarHeaderCell>}
                    </CalendarGridHeader>
                    <CalendarGridBody>{(date) => <CalendarCell date={date} />}</CalendarGridBody>
                  </CalendarGrid>
                </Calendar>
              </Dialog>
            </Popover>
          </DatePicker>
        </div>
      </div>
      {error && <div className="date-range-error">{error}</div>}
    </div>
  );
}

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
    case "region":
    case "always_within": {
      const hasConstraint =
        pred.timeFrom !== "" ||
        pred.timeTo !== "" ||
        pred.altMin !== null ||
        pred.altMax !== null ||
        pred.squawkCodes.length > 0;
      if (pred.shape === "none") return hasConstraint;
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
    item.kind === "group" ? isGroupValid(item) : isPredValid(item),
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

function DateTimeField({
  label,
  value,
  onChange,
  minDate,
  maxDate,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  minDate: string | undefined;
  maxDate: string | undefined;
}): React.ReactElement {
  let dateTimeValue: CalendarDateTime | null = null;
  if (value.length >= 16) {
    try {
      dateTimeValue = parseDateTime(value + ":00");
    } catch {
      /* invalid */
    }
  }

  const handleChange = (d: CalendarDateTime | null): void => {
    onChange(d ? d.toString().slice(0, 16) : "");
  };

  const minValue = minDate !== undefined ? parseDate(minDate) : undefined;
  const maxValue = maxDate !== undefined ? parseDate(maxDate) : undefined;

  return (
    <div>
      <FieldLabel>{label}</FieldLabel>
      <DatePicker<CalendarDateTime>
        granularity="minute"
        value={dateTimeValue}
        onChange={handleChange}
        {...(minValue !== undefined ? { minValue } : {})}
        {...(maxValue !== undefined ? { maxValue } : {})}
      >
        <Group className="datetime-date-group">
          <DateInput className="datetime-date-input">
            {(segment) => <DateSegment segment={segment} />}
          </DateInput>
          <Button className="datetime-cal-btn">▾</Button>
        </Group>
        <Popover className="datetime-popover">
          <Dialog>
            <Calendar>
              <header className="datetime-cal-header">
                <Button slot="previous">◀</Button>
                <Heading />
                <Button slot="next">▶</Button>
              </header>
              <CalendarGrid>
                <CalendarGridHeader>
                  {(day) => <CalendarHeaderCell>{day}</CalendarHeaderCell>}
                </CalendarGridHeader>
                <CalendarGridBody>{(date) => <CalendarCell date={date} />}</CalendarGridBody>
              </CalendarGrid>
            </Calendar>
          </Dialog>
        </Popover>
      </DatePicker>
    </div>
  );
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
      <button
        className={shape === "none" ? "active" : ""}
        onClick={() => {
          onChange("none");
        }}
      >
        —
      </button>
      <button
        className={shape === "circle" ? "active" : ""}
        onClick={() => {
          onChange("circle");
        }}
      >
        <Circle size={12} /> Circle
      </button>
      <button
        className={shape === "polygon" ? "active" : ""}
        onClick={() => {
          onChange("polygon");
        }}
      >
        <Polygon size={12} /> Polygon
      </button>
      <button
        className={shape === "viewport" ? "active" : ""}
        onClick={() => {
          onChange("viewport");
        }}
      >
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
    return (): void => {
      document.removeEventListener("mousedown", onDoc);
    };
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
            <button
              onClick={() => {
                onChange(value.filter((x) => x !== v));
              }}
              aria-label="Remove"
            >
              ×
            </button>
          </span>
        ))}
        <div ref={ref} style={{ position: "relative" }}>
          <button
            className="chip-add"
            onClick={() => {
              setOpen((prev) => !prev);
            }}
          >
            {value.length === 0 ? "+ choose" : "+ add"}
          </button>
          {open && (
            <div className="chip-dropdown">
              <input
                autoFocus
                placeholder={placeholder}
                value={filter}
                onChange={(e) => {
                  setFilter(e.target.value);
                }}
              />
              {filtered.slice(0, 50).map((opt) => {
                const code = optCode(opt);
                const meta = optLabel(opt);
                const sel = value.includes(code);
                return (
                  <div
                    key={code}
                    className={"chip-opt" + (sel ? " selected" : "")}
                    onMouseDown={(e) => {
                      e.preventDefault();
                    }}
                    onClick={() => {
                      toggle(opt);
                    }}
                  >
                    <span className="chip-opt-check">{sel ? "✓" : ""}</span>
                    <span className="chip-opt-code">{code}</span>
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
        onChange={(v) => {
          onChange({ ...pred, icaoTypes: v });
        }}
      />
      <ChipMultiSelect
        label="Emitter category"
        value={pred.emitters}
        options={EMITTER_CATEGORIES}
        onChange={(v) => {
          onChange({ ...pred, emitters: v });
        }}
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
  dateRange,
}: {
  pred: StartsWithinPred | EndsWithinPred;
  onChange: (p: StartsWithinPred | EndsWithinPred) => void;
  onRemove: () => void;
  onArmPicker: () => void;
  isPicking: boolean;
  onArmDraw: () => void;
  isDrawing: boolean;
  name: string;
  dateRange: DataRange | null;
}): React.ReactElement {
  return (
    <PredCard icon={<Pin />} name={name} onRemove={onRemove} invalid={!isPredValid(pred)}>
      <ShapeToggle
        shape={pred.shape}
        onChange={(s) => {
          onChange({ ...pred, shape: s });
        }}
      />
      {pred.shape === "circle" ? (
        <>
          <div className="slider-row">
            <label>Radius</label>
            <input
              type="range"
              min="1"
              max="100"
              step="1"
              value={pred.radiusNm}
              onChange={(e) => {
                onChange({ ...pred, radiusNm: +e.target.value });
              }}
            />
            <span className="val">{pred.radiusNm.toFixed(0)} nm</span>
          </div>
          {pred.lat != null ? (
            <div
              style={{
                fontFamily: "JetBrains Mono, monospace",
                fontSize: 10.5,
                color: "var(--fg-2)",
              }}
            >
              {pred.lat.toFixed(3)}°N, {Math.abs(pred.lng ?? 0).toFixed(3)}°
              {(pred.lng ?? 0) < 0 ? "W" : "E"}
            </div>
          ) : (
            <div
              style={{
                fontFamily: "JetBrains Mono, monospace",
                fontSize: 10.5,
                color: "var(--fg-3)",
              }}
            >
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
              ◆ Polygon{" "}
              <span style={{ color: "var(--fg-3)", fontSize: 10 }}>{pred.polygon.length} pts</span>
            </div>
          ) : (
            <div
              style={{
                fontFamily: "JetBrains Mono, monospace",
                fontSize: 10.5,
                color: "var(--fg-3)",
              }}
            >
              No polygon defined
            </div>
          )}
          <div className="minimap-buttons">
            <button className={"btn-secondary" + (isDrawing ? " armed" : "")} onClick={onArmDraw}>
              {isDrawing
                ? "Drawing… (dbl-click to finish)"
                : pred.polygon
                  ? "Redraw"
                  : "Draw on map"}
            </button>
          </div>
        </>
      ) : pred.shape === "viewport" ? (
        <div
          style={{ fontFamily: "JetBrains Mono, monospace", fontSize: 10.5, color: "var(--fg-2)" }}
        >
          Uses current map viewport
        </div>
      ) : null}
      <div style={{ marginTop: 4 }}>
        <DateTimeField
          label="From"
          value={pred.timeFrom}
          onChange={(v) => {
            onChange({ ...pred, timeFrom: v });
          }}
          minDate={dateRange?.first_date ?? undefined}
          maxDate={dateRange?.last_date ?? undefined}
        />
      </div>
      <div>
        <DateTimeField
          label="To"
          value={pred.timeTo}
          onChange={(v) => {
            onChange({ ...pred, timeTo: v });
          }}
          minDate={dateRange?.first_date ?? undefined}
          maxDate={dateRange?.last_date ?? undefined}
        />
      </div>
    </PredCard>
  );
}

type RegionLikePred = IntersectsPred | AlwaysWithinPred;

function RegionCard({
  pred,
  onChange,
  onRemove,
  onArmDraw,
  isDrawing,
  onArmPicker,
  isPicking,
  name,
  dateRange,
}: {
  pred: RegionLikePred;
  onChange: (p: RegionLikePred) => void;
  onRemove: () => void;
  onArmDraw: () => void;
  isDrawing: boolean;
  onArmPicker: () => void;
  isPicking: boolean;
  name: string;
  dateRange: DataRange | null;
}): React.ReactElement {
  const [altOpen, setAltOpen] = useState(pred.altMin !== null || pred.altMax !== null);
  const [timeOpen, setTimeOpen] = useState(pred.timeFrom !== "" || pred.timeTo !== "");
  const [squawkOpen, setSquawkOpen] = useState(pred.squawkCodes.length > 0);
  const [squawkInput, setSquawkInput] = useState("");

  const handleShapeChange = (s: Shape): void => {
    onChange({ ...pred, shape: s });
  };

  const toggleAlt = (checked: boolean): void => {
    if (!checked) onChange({ ...pred, altMin: null, altMax: null });
    setAltOpen(checked);
  };

  const toggleTime = (checked: boolean): void => {
    if (!checked) onChange({ ...pred, timeFrom: "", timeTo: "" });
    setTimeOpen(checked);
  };

  const toggleSquawk = (checked: boolean): void => {
    if (!checked) onChange({ ...pred, squawkCodes: [] });
    setSquawkOpen(checked);
  };

  const addSquawkCode = (raw: string): void => {
    const code = raw.trim();
    if (code && !pred.squawkCodes.includes(code)) {
      onChange({ ...pred, squawkCodes: [...pred.squawkCodes, code] });
    }
    setSquawkInput("");
  };

  return (
    <PredCard icon={<Polygon />} name={name} onRemove={onRemove} invalid={!isPredValid(pred)}>
      <ShapeToggle shape={pred.shape} onChange={handleShapeChange} />
      {pred.shape === "polygon" ? (
        <>
          {pred.polygon ? (
            <div className="polygon-summary">
              ◆ {pred.regionName}{" "}
              <span style={{ color: "var(--fg-3)", fontSize: 10 }}>{pred.polygon.length} pts</span>
            </div>
          ) : (
            <div
              style={{
                fontFamily: "JetBrains Mono, monospace",
                fontSize: 10.5,
                color: "var(--fg-3)",
              }}
            >
              No region defined
            </div>
          )}
          <div className="minimap-buttons">
            <button className={"btn-secondary" + (isDrawing ? " armed" : "")} onClick={onArmDraw}>
              {isDrawing
                ? "Drawing… (dbl-click to finish)"
                : pred.polygon
                  ? "Redraw"
                  : "Draw on map"}
            </button>
          </div>
        </>
      ) : pred.shape === "circle" ? (
        <>
          <div className="slider-row">
            <label>Radius</label>
            <input
              type="range"
              min="1"
              max="100"
              step="1"
              value={pred.radiusNm}
              onChange={(e) => {
                onChange({ ...pred, radiusNm: +e.target.value });
              }}
            />
            <span className="val">{pred.radiusNm.toFixed(0)} nm</span>
          </div>
          {pred.lat != null ? (
            <div
              style={{
                fontFamily: "JetBrains Mono, monospace",
                fontSize: 10.5,
                color: "var(--fg-2)",
              }}
            >
              {pred.lat.toFixed(3)}°N, {Math.abs(pred.lng ?? 0).toFixed(3)}°
              {(pred.lng ?? 0) < 0 ? "W" : "E"}
            </div>
          ) : (
            <div
              style={{
                fontFamily: "JetBrains Mono, monospace",
                fontSize: 10.5,
                color: "var(--fg-3)",
              }}
            >
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
        <div
          style={{ fontFamily: "JetBrains Mono, monospace", fontSize: 10.5, color: "var(--fg-2)" }}
        >
          Uses current map viewport
        </div>
      ) : null}
      <div className="optional-group" style={{ marginTop: 4 }}>
        <label className="optional-group-label">
          <input
            type="checkbox"
            checked={altOpen}
            onChange={(e) => {
              toggleAlt(e.target.checked);
            }}
          />
          Altitude range
        </label>
        {altOpen && (
          <div className="pred-row optional-group-body">
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
      </div>
      <div className="optional-group" style={{ marginTop: 4 }}>
        <label className="optional-group-label">
          <input
            type="checkbox"
            checked={timeOpen}
            onChange={(e) => {
              toggleTime(e.target.checked);
            }}
          />
          Time range
        </label>
        {timeOpen && (
          <div className="optional-group-body">
            <DateTimeField
              label="From"
              value={pred.timeFrom}
              onChange={(v) => {
                onChange({ ...pred, timeFrom: v });
              }}
              minDate={dateRange?.first_date ?? undefined}
              maxDate={dateRange?.last_date ?? undefined}
            />
            <DateTimeField
              label="To"
              value={pred.timeTo}
              onChange={(v) => {
                onChange({ ...pred, timeTo: v });
              }}
              minDate={dateRange?.first_date ?? undefined}
              maxDate={dateRange?.last_date ?? undefined}
            />
          </div>
        )}
      </div>
      <div className="optional-group" style={{ marginTop: 4 }}>
        <label className="optional-group-label">
          <input
            type="checkbox"
            checked={squawkOpen}
            onChange={(e) => {
              toggleSquawk(e.target.checked);
            }}
          />
          Squawk filter
        </label>
        {squawkOpen && (
          <div className="optional-group-body">
            <div className="chip-group">
              {pred.squawkCodes.map((code) => (
                <span key={code} className="chip">
                  {code}
                  <button
                    onClick={() => {
                      onChange({
                        ...pred,
                        squawkCodes: pred.squawkCodes.filter((c) => c !== code),
                      });
                    }}
                    aria-label="Remove"
                  >
                    ×
                  </button>
                </span>
              ))}
              <input
                className="text-field mono"
                placeholder="e.g. 7700"
                value={squawkInput}
                style={{ width: 80 }}
                onChange={(e) => {
                  setSquawkInput(e.target.value);
                }}
                onKeyDown={(e) => {
                  if (e.key === "Enter" || e.key === ",") {
                    e.preventDefault();
                    addSquawkCode(squawkInput);
                  }
                }}
                onBlur={() => {
                  if (squawkInput.trim()) addSquawkCode(squawkInput);
                }}
              />
            </div>
          </div>
        )}
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
          onChange={(e) => {
            onChange({ ...pred, pattern: e.target.value });
          }}
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
  { kind: "region", icon: <Polygon />, label: "Ever", desc: "Ever intersects area/altitude/time" },
  {
    kind: "always_within",
    icon: <Polygon />,
    label: "Always",
    desc: "Always within area/altitude/time",
  },
  { kind: "callsign", icon: <Text />, label: "Callsign", desc: "Regex match" },
  { kind: "group_all", icon: <Braces />, label: "All of", desc: "All sub-filters must match" },
  { kind: "group_any", icon: <Braces />, label: "Any of", desc: "At least one sub-filter matches" },
];

function AddFilterMenu({ onAdd }: { onAdd: (kind: AddKind) => void }): React.ReactElement {
  const [open, setOpen] = useState(false);
  const [dropUp, setDropUp] = useState(true);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onDoc = (e: MouseEvent): void => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", onDoc);
    return (): void => {
      document.removeEventListener("mousedown", onDoc);
    };
  }, [open]);

  const toggle = (): void => {
    if (!open && ref.current) {
      const rect = ref.current.getBoundingClientRect();
      setDropUp(rect.top > window.innerHeight - rect.bottom);
    }
    setOpen((v) => !v);
  };

  return (
    <div ref={ref} style={{ position: "relative" }}>
      <button className="add-filter" onClick={toggle}>
        <Plus size={14} /> Add filter
      </button>
      {open && (
        <div
          className="add-filter-menu"
          style={dropUp ? undefined : { bottom: "auto", top: "100%", marginBottom: 0, marginTop: 6 }}
        >
          {FILTER_OPTS.map((o) => (
            <button
              key={o.kind}
              onClick={() => {
                onAdd(o.kind);
                setOpen(false);
              }}
            >
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
  dateRange,
}: {
  pred: UIPredicate;
  onChange: (p: UIPredicate) => void;
  onRemove: () => void;
  onArmPicker: () => void;
  isPicking: boolean;
  onArmDraw: () => void;
  isDrawing: boolean;
  name: string;
  dateRange: DataRange | null;
}): React.ReactElement | null {
  switch (pred.kind) {
    case "aircraft":
      return (
        <AircraftCard
          pred={pred}
          onChange={(p) => {
            onChange(p);
          }}
          onRemove={onRemove}
        />
      );
    case "starts_within":
    case "ends_within":
      return (
        <PointRadiusCard
          pred={pred}
          onChange={(p) => {
            onChange(p);
          }}
          onRemove={onRemove}
          onArmPicker={onArmPicker}
          isPicking={isPicking}
          onArmDraw={onArmDraw}
          isDrawing={isDrawing}
          name={name}
          dateRange={dateRange}
        />
      );
    case "region":
    case "always_within":
      return (
        <RegionCard
          pred={pred}
          onChange={(p) => {
            onChange(p);
          }}
          onRemove={onRemove}
          onArmDraw={onArmDraw}
          isDrawing={isDrawing}
          onArmPicker={onArmPicker}
          isPicking={isPicking}
          name={name}
          dateRange={dateRange}
        />
      );
    case "callsign":
      return (
        <CallsignCard
          pred={pred}
          onChange={(p) => {
            onChange(p);
          }}
          onRemove={onRemove}
        />
      );
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
  dateRange: DataRange | null;
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
  dateRange,
}: GroupBlockProps): React.ReactElement {
  const updateChild = (childId: string, next: QueryItem): void => {
    onChange({ ...group, items: group.items.map((item) => (item.id === childId ? next : item)) });
  };
  const removeChild = (childId: string): void => {
    onChange({ ...group, items: group.items.filter((item) => item.id !== childId) });
  };
  const addChild = (kind: AddKind): void => {
    const rc =
      group.items.filter((i) => i.kind === "region" || i.kind === "always_within").length +
      regionCount;
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
              onClick={() => {
                onChange({ ...group, mode: "all" });
              }}
            >
              ALL
            </button>
            <button
              className={group.mode === "any" ? "active" : ""}
              onClick={() => {
                onChange({ ...group, mode: "any" });
              }}
            >
              ANY
            </button>
          </div>
          <span className="group-mode-label">
            {group.mode === "all" ? "All filters must match" : "Any filter must match"}
          </span>
          <button className="pred-x" onClick={onRemove} title="Remove group">
            <X size={12} />
          </button>
        </div>
      )}

      <div className={isRoot ? "group-root-body" : "filter-group-body"}>
        {group.items.length === 0 && (
          <div
            style={{ color: "var(--fg-3)", fontSize: 12, textAlign: "center", padding: "20px 0" }}
          >
            {isRoot ? (
              <>
                <div style={{ marginBottom: 8, opacity: 0.4 }}>
                  <svg
                    width="32"
                    height="32"
                    viewBox="0 0 24 24"
                    fill="none"
                    stroke="currentColor"
                    strokeWidth="1.5"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                  >
                    <circle cx="11" cy="11" r="8" />
                    <path d="M21 21l-4.35-4.35" />
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
              onChange={(g) => {
                updateChild(item.id, g);
              }}
              onRemove={() => {
                removeChild(item.id);
              }}
              onArmPicker={onArmPicker}
              pickingId={pickingId}
              onArmDraw={onArmDraw}
              drawingId={drawingId}
              regionCount={regionCount}
              labels={labels}
              dateRange={dateRange}
            />
          ) : (
            <PredicateRenderer
              key={item.id}
              pred={item}
              onChange={(p) => {
                updateChild(item.id, p);
              }}
              onRemove={() => {
                removeChild(item.id);
              }}
              onArmPicker={() => {
                onArmPicker(item.id);
              }}
              isPicking={pickingId === item.id}
              onArmDraw={() => {
                onArmDraw(item.id);
              }}
              isDrawing={drawingId === item.id}
              name={labels.get(item.id) ?? (item.kind === "aircraft" ? "Aircraft" : "Callsign")}
              dateRange={dateRange}
            />
          ),
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
  dateRange: DataRange | null;
}

export function computeLabels(group: FilterGroup): Map<string, string> {
  const result = new Map<string, string>();
  const counts: Record<string, number> = {};
  function walk(g: FilterGroup): void {
    for (const item of g.items) {
      if (item.kind === "group") {
        walk(item);
        continue;
      }
      if (
        item.kind !== "starts_within" &&
        item.kind !== "ends_within" &&
        item.kind !== "region" &&
        item.kind !== "always_within"
      )
        continue;
      const base =
        item.kind === "starts_within"
          ? "Starts Within"
          : item.kind === "ends_within"
            ? "Ends Within"
            : item.kind === "region"
              ? "Ever"
              : "Always";
      if (item.shape === "none" || item.shape === "viewport") {
        result.set(item.id, base);
      } else {
        counts[base] = (counts[base] ?? 0) + 1;
        result.set(item.id, `${base} ${String(counts[base])}`);
      }
    }
  }
  walk(group);
  return result;
}

function countRegions(g: FilterGroup): number {
  return g.items.reduce<number>((n, item) => {
    if (item.kind === "group") return n + countRegions(item);
    if (item.kind === "region" || item.kind === "always_within") return n + 1;
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
  dateRange,
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
      dateRange={dateRange}
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
  dateRangeValid: boolean;
  onRun: () => void;
}

export function QueryBuilderFooter({
  rootGroup,
  dateRangeValid,
  onRun,
}: QueryBuilderFooterProps): React.ReactElement {
  const enabled = dateRangeValid && rootGroup.items.length > 0 && isGroupValid(rootGroup);
  return (
    <button className="run-btn" onClick={onRun} disabled={!enabled}>
      <Play /> Run query
    </button>
  );
}

export function updatePredInGroup(
  group: FilterGroup,
  predId: string,
  update: (p: UIPredicate) => UIPredicate,
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
