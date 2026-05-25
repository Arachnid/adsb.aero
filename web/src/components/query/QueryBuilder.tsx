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
import {
  Braces,
  Circle,
  Pin,
  Plane,
  Play,
  Plus,
  Polygon,
  Text,
  Viewport,
  X,
  Zone,
} from "../Icons";
import { getIcaoTypes } from "../../lib/api";
import type { DataRange } from "../../lib/api";
import {
  MAX_GEOMETRY_AREA_KM2,
  circleAreaKm2,
  polygonAreaKm2,
} from "../../lib/geometryUtils";

// ===== Types =====

export type GroupMode = "all" | "any";

interface BasePred {
  id: string;
  negated: boolean;
}
interface AircraftPred extends BasePred {
  kind: "aircraft";
  icaoTypes: string[];
  emitters: string[];
}
interface EndpointWithinPred extends BasePred {
  kind: "endpoint_within";
  mode: "start" | "end" | "either" | "both";
  shape: "none" | "circle" | "polygon" | "viewport" | "airspace";
  lat: number | null;
  lng: number | null;
  radiusNm: number;
  polygon: [number, number][] | null;
  airspaceName: string | null;
  airspaceLabel: string | null;
  startTimeFrom: string;
  startTimeTo: string;
  endTimeFrom: string;
  endTimeTo: string;
}
interface IntersectsPred extends BasePred {
  kind: "region";
  regionName: string;
  shape: "none" | "circle" | "polygon" | "viewport" | "airspace";
  polygon: [number, number][] | null;
  airspaceName: string | null;
  airspaceLabel: string | null;
  lat: number | null;
  lng: number | null;
  radiusNm: number;
  altMin: number | null;
  altMinRef: "ft" | "fl";
  altMax: number | null;
  altMaxRef: "ft" | "fl";
  timeFrom: string;
  timeTo: string;
  squawkCodes: string[];
  dwellMinMin: number | null;
  dwellMaxMin: number | null;
  distanceMinNm: number | null;
  distanceMaxNm: number | null;
  aglMin: number | null;
  aglMax: number | null;
}
interface AlwaysWithinPred extends BasePred {
  kind: "always_within";
  regionName: string;
  shape: "none" | "circle" | "polygon" | "viewport" | "airspace";
  polygon: [number, number][] | null;
  airspaceName: string | null;
  airspaceLabel: string | null;
  lat: number | null;
  lng: number | null;
  radiusNm: number;
  altMin: number | null;
  altMinRef: "ft" | "fl";
  altMax: number | null;
  altMaxRef: "ft" | "fl";
  timeFrom: string;
  timeTo: string;
  squawkCodes: string[];
  dwellMinMin: number | null;
  dwellMaxMin: number | null;
  distanceMinNm: number | null;
  distanceMaxNm: number | null;
  aglMin: number | null;
  aglMax: number | null;
}
interface CallsignPred extends BasePred {
  kind: "callsign";
  pattern: string;
}
interface RegistrationPred extends BasePred {
  kind: "registration";
  prefix: string;
}
interface Icao24Pred extends BasePred {
  kind: "icao24";
  addresses: string[];
}

export type UIPredicate =
  | AircraftPred
  | EndpointWithinPred
  | IntersectsPred
  | AlwaysWithinPred
  | CallsignPred
  | RegistrationPred
  | Icao24Pred;

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
    return {
      id,
      kind: "group",
      mode: kind === "group_all" ? "all" : "any",
      items: [],
    };
  }
  if (kind === "endpoint_within") {
    return {
      id,
      kind,
      negated: false,
      mode: "either" as const,
      shape: "circle" as const,
      lat: null,
      lng: null,
      radiusNm: 1,
      polygon: null,
      airspaceName: null,
      airspaceLabel: null,
      startTimeFrom: "",
      startTimeTo: "",
      endTimeFrom: "",
      endTimeTo: "",
    };
  }
  if (kind === "region" || kind === "always_within") {
    return {
      id,
      kind,
      negated: false,
      regionName: "Region " + String(regionCount + 1),
      shape: "polygon",
      polygon: null,
      airspaceName: null,
      airspaceLabel: null,
      lat: null,
      lng: null,
      radiusNm: 25,
      altMin: null,
      altMinRef: "ft" as const,
      altMax: null,
      altMaxRef: "ft" as const,
      timeFrom: "",
      timeTo: "",
      squawkCodes: [],
      dwellMinMin: null,
      dwellMaxMin: null,
      distanceMinNm: null,
      distanceMaxNm: null,
      aglMin: null,
      aglMax: null,
    };
  }
  if (kind === "aircraft") {
    return { id, kind, negated: false, icaoTypes: [], emitters: [] };
  }
  if (kind === "registration")
    return { id, kind: "registration", negated: false, prefix: "" };
  if (kind === "icao24")
    return { id, kind: "icao24", negated: false, addresses: [] };
  return { id, kind: "callsign", negated: false, pattern: "" };
}

// ===== Reference data =====

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
  to: string; // "YYYY-MM-DD" inclusive, mandatory end date
  from?: string; // "YYYY-MM-DD" inclusive, optional earliest bound
}

export function isDateRangeValid(range: GlobalDateRange): boolean {
  if (!range.to) return false;
  if (!range.from) return true;
  try {
    const f = parseDate(range.from);
    const t = parseDate(range.to);
    return f.compare(t) <= 0;
  } catch {
    return false;
  }
}

/** Convert a GlobalDateRange to the ISO strings the API expects. */
export function dateRangeToApiParams(range: GlobalDateRange): {
  endDate: string;
  startFrom: string | null;
} {
  const toDate = parseDate(range.to).add({ days: 1 });
  return {
    endDate: toDate.toString() + "T00:00:00Z",
    startFrom: range.from ? range.from + "T00:00:00Z" : null,
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

  const handleFromChange = (d: CalendarDate | null): void => {
    if (d) {
      onChange({ ...range, from: d.toString() });
    } else {
      onChange({ to: range.to });
    }
  };

  const handleToChange = (d: CalendarDate | null): void => {
    onChange({ ...range, to: d ? d.toString() : "" });
  };

  const handleReset = (): void => {
    if (!dataRange?.last_date) return;
    const { from } = range;
    onChange(
      from !== undefined
        ? { to: dataRange.last_date, from }
        : { to: dataRange.last_date },
    );
  };

  let error: string | null = null;
  if (range.from && range.to) {
    try {
      if (parseDate(range.from).compare(parseDate(range.to)) > 0)
        error = "Start must be on or before end date";
    } catch {
      error = "Invalid date";
    }
  }

  return (
    <div className="date-range-bar">
      <div className="date-range-bar-header">
        <div className="date-range-bar-label">Date range</div>
        {dataRange?.last_date && (
          <button className="date-range-reset" onClick={handleReset}>
            ↺ Latest
          </button>
        )}
      </div>
      <div className="date-range-bar-row">
        <div className="date-range-bar-field">
          <FieldLabel>From (optional)</FieldLabel>
          <div style={{ display: "flex", gap: 4, alignItems: "center" }}>
            <DatePicker<CalendarDate>
              style={{ flex: 1, minWidth: 0 }}
              aria-label="From (optional)"
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
                        {(day) => (
                          <CalendarHeaderCell>{day}</CalendarHeaderCell>
                        )}
                      </CalendarGridHeader>
                      <CalendarGridBody>
                        {(date) => <CalendarCell date={date} />}
                      </CalendarGridBody>
                    </CalendarGrid>
                  </Calendar>
                </Dialog>
              </Popover>
            </DatePicker>
            {range.from && (
              <button
                onClick={() => {
                  onChange({ to: range.to });
                }}
                style={{
                  background: "none",
                  border: "none",
                  color: "var(--fg-3)",
                  cursor: "pointer",
                  fontSize: 14,
                  lineHeight: 1,
                  padding: "0 2px",
                }}
                title="Clear start date"
              >
                ×
              </button>
            )}
          </div>
        </div>
        <div className="date-range-bar-field">
          <FieldLabel>To</FieldLabel>
          <DatePicker<CalendarDate>
            aria-label="To"
            granularity="day"
            value={toValue}
            onChange={handleToChange}
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
                    <CalendarGridBody>
                      {(date) => <CalendarCell date={date} />}
                    </CalendarGridBody>
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
    case "registration":
      return pred.prefix.trim() !== "";
    case "icao24":
      return pred.addresses.length > 0;
    case "endpoint_within": {
      const hasTime =
        pred.startTimeFrom !== "" ||
        pred.startTimeTo !== "" ||
        pred.endTimeFrom !== "" ||
        pred.endTimeTo !== "";
      if (pred.shape === "none") return hasTime;
      if (pred.shape === "viewport") return true;
      if (pred.shape === "circle")
        return pred.lat !== null && pred.lng !== null;
      // polygon and airspace both require a polygon to be set
      return pred.polygon !== null && pred.polygon.length >= 3;
    }
    case "region":
    case "always_within": {
      const hasConstraint =
        pred.timeFrom !== "" ||
        pred.timeTo !== "" ||
        pred.altMin !== null ||
        pred.altMax !== null ||
        pred.aglMin !== null ||
        pred.aglMax !== null ||
        pred.squawkCodes.length > 0;
      if (pred.shape === "none") return hasConstraint;
      if (pred.shape === "viewport") return true;
      if (pred.shape === "circle") {
        if (pred.lat === null) return false;
        if (circleAreaKm2(pred.radiusNm) > MAX_GEOMETRY_AREA_KM2) return false;
      } else if (pred.polygon === null || pred.polygon.length < 3) {
        // polygon and airspace both require a polygon to be set
        return false;
      } else if (polygonAreaKm2(pred.polygon) > MAX_GEOMETRY_AREA_KM2) {
        return false;
      }
      if (
        pred.altMin !== null &&
        pred.altMax !== null &&
        pred.altMin > pred.altMax
      )
        return false;
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
  negated,
  onToggleNegate,
  children,
  invalid,
}: {
  icon: React.ReactNode;
  name: string;
  onRemove: () => void;
  negated: boolean;
  onToggleNegate: () => void;
  children: React.ReactNode;
  invalid?: boolean;
}): React.ReactElement {
  const classes =
    "pred" +
    (invalid ? " pred--invalid" : "") +
    (negated && !invalid ? " pred--negated" : "");
  return (
    <div className={classes}>
      <div className="pred-head">
        <span className="pred-icon">{icon}</span>
        <span className="pred-name">
          {negated && <span className="pred-not-badge">NOT</span>}
          {name}
        </span>
        <button
          className={"pred-not-toggle" + (negated ? " active" : "")}
          onClick={onToggleNegate}
          title={negated ? "Remove NOT" : "Negate filter"}
        >
          ¬
        </button>
        <button className="pred-x" onClick={onRemove} title="Remove filter">
          <X size={12} />
        </button>
      </div>
      <div className="pred-body">{children}</div>
    </div>
  );
}

function FieldLabel({
  children,
}: {
  children: React.ReactNode;
}): React.ReactElement {
  return <div className="field-label">{children}</div>;
}

function RefToggle({
  value,
  onChange,
}: {
  value: "ft" | "fl";
  onChange: (r: "ft" | "fl") => void;
}): React.ReactElement {
  return (
    <div
      style={{
        display: "inline-flex",
        border: "1px solid var(--line-2)",
        borderRadius: 3,
        overflow: "hidden",
        fontSize: 9.5,
        fontFamily: "JetBrains Mono, monospace",
      }}
    >
      {(["ft", "fl"] as const).map((ref) => (
        <button
          key={ref}
          onClick={() => {
            onChange(ref);
          }}
          style={{
            padding: "1px 5px",
            background: value === ref ? "var(--accent)" : "transparent",
            color: value === ref ? "white" : "var(--fg-3)",
            border: "none",
            cursor: "pointer",
            lineHeight: 1.4,
          }}
        >
          {ref === "fl" ? "FL" : "ft"}
        </button>
      ))}
    </div>
  );
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
        aria-label={label}
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
                <CalendarGridBody>
                  {(date) => <CalendarCell date={date} />}
                </CalendarGridBody>
              </CalendarGrid>
            </Calendar>
          </Dialog>
        </Popover>
      </DatePicker>
    </div>
  );
}

type Shape = "none" | "circle" | "polygon" | "viewport" | "airspace";

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
        <Polygon size={12} /> Poly
      </button>
      <button
        className={shape === "viewport" ? "active" : ""}
        onClick={() => {
          onChange("viewport");
        }}
      >
        <Viewport size={12} /> View
      </button>
      <button
        className={shape === "airspace" ? "active" : ""}
        onClick={() => {
          onChange("airspace");
        }}
      >
        <Zone size={12} /> Zone
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
      if (ref.current && !ref.current.contains(e.target as Node))
        setOpen(false);
    };
    document.addEventListener("mousedown", onDoc);
    return (): void => {
      document.removeEventListener("mousedown", onDoc);
    };
  }, [open]);

  const filtered = options.filter((o) => {
    const txt = (
      typeof o === "string" ? o : o.code + " " + o.label
    ).toLowerCase();
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
  globalDateRange,
}: {
  pred: AircraftPred;
  onChange: (p: AircraftPred) => void;
  onRemove: () => void;
  globalDateRange: GlobalDateRange | null;
}): React.ReactElement {
  const [icaoTypeOptions, setIcaoTypeOptions] = useState<ChipOption[]>([]);

  useEffect(() => {
    if (!globalDateRange?.to) return;
    // Use explicit start if provided, otherwise a 7-day window before end.
    const end = globalDateRange.to;
    const start =
      globalDateRange.from ??
      new Date(Date.parse(end + "T00:00:00Z") - 7 * 86400000)
        .toISOString()
        .slice(0, 10);
    const controller = new AbortController();
    getIcaoTypes(start, end, { signal: controller.signal })
      .then((stats) => {
        setIcaoTypeOptions(
          stats.map((s) => ({
            code: s.icao_type,
            label: s.model ?? s.icao_type,
          })),
        );
      })
      .catch((err: unknown) => {
        if ((err as Error).name !== "AbortError") setIcaoTypeOptions([]);
      });
    return (): void => {
      controller.abort();
    };
  }, [globalDateRange?.from, globalDateRange?.to]);

  return (
    <PredCard
      icon={<Plane />}
      name="Aircraft"
      onRemove={onRemove}
      negated={pred.negated}
      onToggleNegate={() => {
        onChange({ ...pred, negated: !pred.negated });
      }}
      invalid={!isPredValid(pred)}
    >
      <ChipMultiSelect
        label="ICAO type"
        value={pred.icaoTypes}
        options={icaoTypeOptions}
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
  onArmAirspacePicker,
  isPickingAirspace,
  name,
  dateRange,
  globalDateRange,
}: {
  pred: EndpointWithinPred;
  onChange: (p: EndpointWithinPred) => void;
  onRemove: () => void;
  onArmPicker: () => void;
  isPicking: boolean;
  onArmDraw: () => void;
  isDrawing: boolean;
  onArmAirspacePicker: () => void;
  isPickingAirspace: boolean;
  name: string;
  dateRange: DataRange | null;
  globalDateRange: GlobalDateRange | null;
}): React.ReactElement {
  const effectiveMinDate =
    globalDateRange?.from || dateRange?.first_date || undefined;
  const effectiveMaxDate =
    globalDateRange?.to || dateRange?.last_date || undefined;
  const showStartTime =
    pred.mode === "start" || pred.mode === "either" || pred.mode === "both";
  const showEndTime =
    pred.mode === "end" || pred.mode === "either" || pred.mode === "both";

  const hasStartTimeData = pred.startTimeFrom !== "" || pred.startTimeTo !== "";
  const hasEndTimeData = pred.endTimeFrom !== "" || pred.endTimeTo !== "";
  const [startTimeOpenLocal, setStartTimeOpenLocal] =
    useState(hasStartTimeData);
  const [endTimeOpenLocal, setEndTimeOpenLocal] = useState(hasEndTimeData);
  const startTimeOpen = startTimeOpenLocal || hasStartTimeData;
  const endTimeOpen = endTimeOpenLocal || hasEndTimeData;

  const toggleStartTime = (checked: boolean): void => {
    if (!checked) onChange({ ...pred, startTimeFrom: "", startTimeTo: "" });
    setStartTimeOpenLocal(checked);
  };
  const toggleEndTime = (checked: boolean): void => {
    if (!checked) onChange({ ...pred, endTimeFrom: "", endTimeTo: "" });
    setEndTimeOpenLocal(checked);
  };

  return (
    <PredCard
      icon={<Pin />}
      name={name}
      onRemove={onRemove}
      negated={pred.negated}
      onToggleNegate={() => {
        onChange({ ...pred, negated: !pred.negated });
      }}
      invalid={!isPredValid(pred)}
    >
      <div className="shape-toggle">
        {(
          [
            ["either", "Either"],
            ["start", "Start"],
            ["end", "End"],
            ["both", "Both"],
          ] as const
        ).map(([m, label]) => (
          <button
            key={m}
            className={pred.mode === m ? "active" : ""}
            onClick={() => {
              onChange({ ...pred, mode: m });
            }}
          >
            {label}
          </button>
        ))}
      </div>
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
            <button
              className={"btn-secondary" + (isPicking ? " armed" : "")}
              onClick={onArmPicker}
            >
              {isPicking ? "Click on map…" : "Pick on map"}
            </button>
          </div>
        </>
      ) : pred.shape === "polygon" ? (
        <>
          {pred.polygon ? (
            <div className="polygon-summary">
              ◆ Polygon{" "}
              <span style={{ color: "var(--fg-3)", fontSize: 10 }}>
                {pred.polygon.length} pts
              </span>
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
            <button
              className={"btn-secondary" + (isDrawing ? " armed" : "")}
              onClick={onArmDraw}
            >
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
          style={{
            fontFamily: "JetBrains Mono, monospace",
            fontSize: 10.5,
            color: "var(--fg-2)",
          }}
        >
          Uses current map viewport
        </div>
      ) : pred.shape === "airspace" ? (
        <>
          {pred.polygon && pred.airspaceName ? (
            <>
              <div className="polygon-summary">◆ {pred.airspaceName}</div>
              {pred.airspaceLabel && (
                <div
                  style={{ fontSize: 10.5, color: "var(--fg-3)", marginTop: 2 }}
                >
                  {pred.airspaceLabel}
                </div>
              )}
            </>
          ) : (
            <div
              style={{
                fontFamily: "JetBrains Mono, monospace",
                fontSize: 10.5,
                color: "var(--fg-3)",
              }}
            >
              No airspace selected
            </div>
          )}
          <div className="minimap-buttons">
            <button
              className={"btn-secondary" + (isPickingAirspace ? " armed" : "")}
              onClick={onArmAirspacePicker}
            >
              {isPickingAirspace
                ? "Click on map…"
                : pred.polygon
                  ? "Change"
                  : "Choose from map"}
            </button>
          </div>
        </>
      ) : null}
      {showStartTime && (
        <div className="optional-group" style={{ marginTop: 4 }}>
          <label className="optional-group-label">
            <input
              type="checkbox"
              checked={startTimeOpen}
              onChange={(e) => {
                toggleStartTime(e.target.checked);
              }}
            />
            Departure time
          </label>
          {startTimeOpen && (
            <div className="optional-group-body">
              <DateTimeField
                label="From"
                value={pred.startTimeFrom}
                onChange={(v) => {
                  onChange({ ...pred, startTimeFrom: v });
                }}
                minDate={effectiveMinDate}
                maxDate={effectiveMaxDate}
              />
              <DateTimeField
                label="To"
                value={pred.startTimeTo}
                onChange={(v) => {
                  onChange({ ...pred, startTimeTo: v });
                }}
                minDate={effectiveMinDate}
                maxDate={effectiveMaxDate}
              />
            </div>
          )}
        </div>
      )}
      {showEndTime && (
        <div className="optional-group" style={{ marginTop: 4 }}>
          <label className="optional-group-label">
            <input
              type="checkbox"
              checked={endTimeOpen}
              onChange={(e) => {
                toggleEndTime(e.target.checked);
              }}
            />
            Arrival time
          </label>
          {endTimeOpen && (
            <div className="optional-group-body">
              <DateTimeField
                label="From"
                value={pred.endTimeFrom}
                onChange={(v) => {
                  onChange({ ...pred, endTimeFrom: v });
                }}
                minDate={effectiveMinDate}
                maxDate={effectiveMaxDate}
              />
              <DateTimeField
                label="To"
                value={pred.endTimeTo}
                onChange={(v) => {
                  onChange({ ...pred, endTimeTo: v });
                }}
                minDate={effectiveMinDate}
                maxDate={effectiveMaxDate}
              />
            </div>
          )}
        </div>
      )}
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
  onArmAirspacePicker,
  isPickingAirspace,
  name,
  dateRange,
  globalDateRange,
}: {
  pred: RegionLikePred;
  onChange: (p: RegionLikePred) => void;
  onRemove: () => void;
  onArmDraw: () => void;
  isDrawing: boolean;
  onArmPicker: () => void;
  isPicking: boolean;
  onArmAirspacePicker: () => void;
  isPickingAirspace: boolean;
  name: string;
  dateRange: DataRange | null;
  globalDateRange: GlobalDateRange | null;
}): React.ReactElement {
  const effectiveMinDate =
    globalDateRange?.from || dateRange?.first_date || undefined;
  const effectiveMaxDate =
    globalDateRange?.to || dateRange?.last_date || undefined;
  const geometryTooLarge =
    (pred.shape === "circle" &&
      pred.lat !== null &&
      circleAreaKm2(pred.radiusNm) > MAX_GEOMETRY_AREA_KM2) ||
    (pred.shape !== "circle" &&
      pred.polygon !== null &&
      pred.polygon.length >= 3 &&
      polygonAreaKm2(pred.polygon) > MAX_GEOMETRY_AREA_KM2);

  const hasAltData = pred.altMin !== null || pred.altMax !== null;
  const hasTimeData = pred.timeFrom !== "" || pred.timeTo !== "";
  const hasSquawkData = pred.squawkCodes.length > 0;
  const hasDwellDistData =
    pred.dwellMinMin !== null ||
    pred.dwellMaxMin !== null ||
    pred.distanceMinNm !== null ||
    pred.distanceMaxNm !== null;
  const hasAglData = pred.aglMin !== null || pred.aglMax !== null;

  const [altOpenLocal, setAltOpenLocal] = useState(hasAltData);
  const [timeOpenLocal, setTimeOpenLocal] = useState(hasTimeData);
  const [squawkOpenLocal, setSquawkOpenLocal] = useState(hasSquawkData);
  const [squawkInput, setSquawkInput] = useState("");
  const [dwellDistOpenLocal, setDwellDistOpenLocal] =
    useState(hasDwellDistData);
  const [aglOpenLocal, setAglOpenLocal] = useState(hasAglData);

  // A section is open if the user has explicitly opened it OR if there is already data in it.
  // This prevents data set externally (e.g. altitude bounds from airspace selection) from
  // being silently included in the query while the section appears closed/unchecked.
  const altOpen = altOpenLocal || hasAltData;
  const timeOpen = timeOpenLocal || hasTimeData;
  const squawkOpen = squawkOpenLocal || hasSquawkData;
  const dwellDistOpen = dwellDistOpenLocal || hasDwellDistData;
  const aglOpen = aglOpenLocal || hasAglData;

  const handleShapeChange = (s: Shape): void => {
    onChange({ ...pred, shape: s });
  };

  const toggleAlt = (checked: boolean): void => {
    if (!checked)
      onChange({
        ...pred,
        altMin: null,
        altMinRef: "ft",
        altMax: null,
        altMaxRef: "ft",
      });
    setAltOpenLocal(checked);
  };

  const toggleTime = (checked: boolean): void => {
    if (!checked) onChange({ ...pred, timeFrom: "", timeTo: "" });
    setTimeOpenLocal(checked);
  };

  const toggleSquawk = (checked: boolean): void => {
    if (!checked) onChange({ ...pred, squawkCodes: [] });
    setSquawkOpenLocal(checked);
  };

  const toggleDwellDist = (checked: boolean): void => {
    if (!checked)
      onChange({
        ...pred,
        dwellMinMin: null,
        dwellMaxMin: null,
        distanceMinNm: null,
        distanceMaxNm: null,
      });
    setDwellDistOpenLocal(checked);
  };

  const toggleAgl = (checked: boolean): void => {
    if (!checked) onChange({ ...pred, aglMin: null, aglMax: null });
    setAglOpenLocal(checked);
  };

  const addSquawkCode = (raw: string): void => {
    const code = raw.trim();
    if (code && !pred.squawkCodes.includes(code)) {
      onChange({ ...pred, squawkCodes: [...pred.squawkCodes, code] });
    }
    setSquawkInput("");
  };

  return (
    <PredCard
      icon={<Polygon />}
      name={name}
      onRemove={onRemove}
      negated={pred.negated}
      onToggleNegate={() => {
        onChange({ ...pred, negated: !pred.negated });
      }}
      invalid={!isPredValid(pred)}
    >
      <ShapeToggle shape={pred.shape} onChange={handleShapeChange} />
      {pred.shape === "polygon" ? (
        <>
          {pred.polygon ? (
            <div className="polygon-summary">
              ◆ {pred.regionName}{" "}
              <span style={{ color: "var(--fg-3)", fontSize: 10 }}>
                {pred.polygon.length} pts
              </span>
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
            <button
              className={"btn-secondary" + (isDrawing ? " armed" : "")}
              onClick={onArmDraw}
            >
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
            <button
              className={"btn-secondary" + (isPicking ? " armed" : "")}
              onClick={onArmPicker}
            >
              {isPicking ? "Click on map…" : "Pick on map"}
            </button>
          </div>
        </>
      ) : pred.shape === "viewport" ? (
        <div
          style={{
            fontFamily: "JetBrains Mono, monospace",
            fontSize: 10.5,
            color: "var(--fg-2)",
          }}
        >
          Uses current map viewport
        </div>
      ) : pred.shape === "airspace" ? (
        <>
          {pred.polygon && pred.airspaceName ? (
            <>
              <div className="polygon-summary">◆ {pred.airspaceName}</div>
              {pred.airspaceLabel && (
                <div
                  style={{ fontSize: 10.5, color: "var(--fg-3)", marginTop: 2 }}
                >
                  {pred.airspaceLabel}
                </div>
              )}
            </>
          ) : (
            <div
              style={{
                fontFamily: "JetBrains Mono, monospace",
                fontSize: 10.5,
                color: "var(--fg-3)",
              }}
            >
              No airspace selected
            </div>
          )}
          <div className="minimap-buttons">
            <button
              className={"btn-secondary" + (isPickingAirspace ? " armed" : "")}
              onClick={onArmAirspacePicker}
            >
              {isPickingAirspace
                ? "Click on map…"
                : pred.polygon
                  ? "Change"
                  : "Choose from map"}
            </button>
          </div>
        </>
      ) : null}
      {geometryTooLarge && (
        <div className="pred-error">
          Area too large — reduce the search region.
        </div>
      )}
      {pred.shape !== "airspace" && (
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
                <div
                  style={{
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "space-between",
                    marginBottom: 4,
                  }}
                >
                  <span className="field-label" style={{ marginBottom: 0 }}>
                    Alt min
                  </span>
                  <RefToggle
                    value={pred.altMinRef}
                    onChange={(r) => {
                      onChange({ ...pred, altMinRef: r });
                    }}
                  />
                </div>
                <input
                  className="text-field mono"
                  type="number"
                  placeholder="0"
                  value={pred.altMin ?? ""}
                  onChange={(e) => {
                    onChange({
                      ...pred,
                      altMin: e.target.value === "" ? null : +e.target.value,
                    });
                  }}
                />
              </div>
              <div>
                <div
                  style={{
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "space-between",
                    marginBottom: 4,
                  }}
                >
                  <span className="field-label" style={{ marginBottom: 0 }}>
                    Alt max
                  </span>
                  <RefToggle
                    value={pred.altMaxRef}
                    onChange={(r) => {
                      onChange({ ...pred, altMaxRef: r });
                    }}
                  />
                </div>
                <input
                  className="text-field mono"
                  type="number"
                  placeholder="∞"
                  value={pred.altMax ?? ""}
                  onChange={(e) => {
                    onChange({
                      ...pred,
                      altMax: e.target.value === "" ? null : +e.target.value,
                    });
                  }}
                />
              </div>
            </div>
          )}
        </div>
      )}
      <div className="optional-group" style={{ marginTop: 4 }}>
        <label className="optional-group-label">
          <input
            type="checkbox"
            checked={aglOpen}
            onChange={(e) => {
              toggleAgl(e.target.checked);
            }}
          />
          AGL range
        </label>
        {aglOpen && (
          <div className="pred-row optional-group-body">
            <div>
              <FieldLabel>AGL min (ft)</FieldLabel>
              <input
                className="text-field mono"
                type="number"
                placeholder="0"
                value={pred.aglMin ?? ""}
                onChange={(e) => {
                  onChange({
                    ...pred,
                    aglMin: e.target.value === "" ? null : +e.target.value,
                  });
                }}
              />
            </div>
            <div>
              <FieldLabel>AGL max (ft)</FieldLabel>
              <input
                className="text-field mono"
                type="number"
                placeholder="∞"
                value={pred.aglMax ?? ""}
                onChange={(e) => {
                  onChange({
                    ...pred,
                    aglMax: e.target.value === "" ? null : +e.target.value,
                  });
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
              minDate={effectiveMinDate}
              maxDate={effectiveMaxDate}
            />
            <DateTimeField
              label="To"
              value={pred.timeTo}
              onChange={(v) => {
                onChange({ ...pred, timeTo: v });
              }}
              minDate={effectiveMinDate}
              maxDate={effectiveMaxDate}
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
      {pred.shape !== "none" && (
        <div className="optional-group" style={{ marginTop: 4 }}>
          <label className="optional-group-label">
            <input
              type="checkbox"
              checked={dwellDistOpen}
              onChange={(e) => {
                toggleDwellDist(e.target.checked);
              }}
            />
            Dwell &amp; distance
          </label>
          {dwellDistOpen && (
            <div className="optional-group-body" style={{ gap: 6 }}>
              <div className="pred-row">
                <div>
                  <FieldLabel>Min dwell (min)</FieldLabel>
                  <input
                    className="text-field mono"
                    type="number"
                    min="0"
                    placeholder="0"
                    value={pred.dwellMinMin ?? ""}
                    onChange={(e) => {
                      onChange({
                        ...pred,
                        dwellMinMin:
                          e.target.value === "" ? null : +e.target.value,
                      });
                    }}
                  />
                </div>
                <div>
                  <FieldLabel>Max dwell (min)</FieldLabel>
                  <input
                    className="text-field mono"
                    type="number"
                    min="0"
                    placeholder="∞"
                    value={pred.dwellMaxMin ?? ""}
                    onChange={(e) => {
                      onChange({
                        ...pred,
                        dwellMaxMin:
                          e.target.value === "" ? null : +e.target.value,
                      });
                    }}
                  />
                </div>
              </div>
              <div className="pred-row">
                <div>
                  <FieldLabel>Min dist (nm)</FieldLabel>
                  <input
                    className="text-field mono"
                    type="number"
                    min="0"
                    placeholder="0"
                    value={pred.distanceMinNm ?? ""}
                    onChange={(e) => {
                      onChange({
                        ...pred,
                        distanceMinNm:
                          e.target.value === "" ? null : +e.target.value,
                      });
                    }}
                  />
                </div>
                <div>
                  <FieldLabel>Max dist (nm)</FieldLabel>
                  <input
                    className="text-field mono"
                    type="number"
                    min="0"
                    placeholder="∞"
                    value={pred.distanceMaxNm ?? ""}
                    onChange={(e) => {
                      onChange({
                        ...pred,
                        distanceMaxNm:
                          e.target.value === "" ? null : +e.target.value,
                      });
                    }}
                  />
                </div>
              </div>
            </div>
          )}
        </div>
      )}
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
    <PredCard
      icon={<Text />}
      name="Callsign"
      onRemove={onRemove}
      negated={pred.negated}
      onToggleNegate={() => {
        onChange({ ...pred, negated: !pred.negated });
      }}
      invalid={!isPredValid(pred)}
    >
      <div>
        <FieldLabel>Prefix</FieldLabel>
        <input
          className="text-field mono"
          placeholder="BAW"
          value={pred.pattern}
          onChange={(e) => {
            onChange({ ...pred, pattern: e.target.value });
          }}
        />
      </div>
    </PredCard>
  );
}

function RegistrationCard({
  pred,
  onChange,
  onRemove,
}: {
  pred: RegistrationPred;
  onChange: (p: RegistrationPred) => void;
  onRemove: () => void;
}): React.ReactElement {
  return (
    <PredCard
      icon={<Text />}
      name="Registration"
      onRemove={onRemove}
      negated={pred.negated}
      onToggleNegate={() => {
        onChange({ ...pred, negated: !pred.negated });
      }}
      invalid={!isPredValid(pred)}
    >
      <div>
        <FieldLabel>Prefix</FieldLabel>
        <input
          className="text-field mono"
          placeholder="G-"
          value={pred.prefix}
          onChange={(e) => {
            onChange({ ...pred, prefix: e.target.value });
          }}
        />
      </div>
    </PredCard>
  );
}

function Icao24Card({
  pred,
  onChange,
  onRemove,
}: {
  pred: Icao24Pred;
  onChange: (p: Icao24Pred) => void;
  onRemove: () => void;
}): React.ReactElement {
  const [input, setInput] = useState("");

  function addAddress(raw: string): void {
    const v = raw.trim().toLowerCase();
    if (!v || pred.addresses.includes(v)) {
      setInput("");
      return;
    }
    onChange({ ...pred, addresses: [...pred.addresses, v] });
    setInput("");
  }

  return (
    <PredCard
      icon={<Text />}
      name="ICAO Address"
      onRemove={onRemove}
      negated={pred.negated}
      onToggleNegate={() => {
        onChange({ ...pred, negated: !pred.negated });
      }}
      invalid={!isPredValid(pred)}
    >
      <div>
        <FieldLabel>Addresses (hex)</FieldLabel>
        <div className="chip-group">
          {pred.addresses.map((addr) => (
            <span key={addr} className="chip mono">
              {addr}
              <button
                onClick={() => {
                  onChange({
                    ...pred,
                    addresses: pred.addresses.filter((a) => a !== addr),
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
            placeholder="a0b1c2"
            value={input}
            style={{ width: 80 }}
            onChange={(e) => {
              setInput(e.target.value);
            }}
            onKeyDown={(e) => {
              if (e.key === "Enter" || e.key === ",") {
                e.preventDefault();
                addAddress(input);
              }
            }}
            onBlur={() => {
              if (input.trim()) addAddress(input);
            }}
          />
        </div>
      </div>
    </PredCard>
  );
}

// ===== Add filter menu =====

const FILTER_OPTS: {
  kind: AddKind;
  icon: React.ReactNode;
  label: string;
  desc: string;
}[] = [
  {
    kind: "aircraft",
    icon: <Plane />,
    label: "Aircraft",
    desc: "Type, emitter category",
  },
  {
    kind: "endpoint_within",
    icon: <Pin />,
    label: "Endpoint",
    desc: "Departure/arrival area or time",
  },
  {
    kind: "region",
    icon: <Polygon />,
    label: "Ever",
    desc: "Ever intersects area/altitude/time",
  },
  {
    kind: "always_within",
    icon: <Polygon />,
    label: "Always",
    desc: "Always within area/altitude/time",
  },
  { kind: "callsign", icon: <Text />, label: "Callsign", desc: "Prefix match" },
  {
    kind: "registration",
    icon: <Text />,
    label: "Registration",
    desc: "Prefix match (e.g. G-)",
  },
  {
    kind: "icao24",
    icon: <Text />,
    label: "ICAO Address",
    desc: "Hex address",
  },
  {
    kind: "group_all",
    icon: <Braces />,
    label: "All of",
    desc: "All sub-filters must match",
  },
  {
    kind: "group_any",
    icon: <Braces />,
    label: "Any of",
    desc: "At least one sub-filter matches",
  },
];

function AddFilterMenu({
  onAdd,
}: {
  onAdd: (kind: AddKind) => void;
}): React.ReactElement {
  const [open, setOpen] = useState(false);
  const [dropUp, setDropUp] = useState(true);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onDoc = (e: MouseEvent): void => {
      if (ref.current && !ref.current.contains(e.target as Node))
        setOpen(false);
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
          style={
            dropUp
              ? undefined
              : { bottom: "auto", top: "100%", marginBottom: 0, marginTop: 6 }
          }
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
  onArmAirspacePicker,
  isPickingAirspace,
  name,
  dateRange,
  globalDateRange,
}: {
  pred: UIPredicate;
  onChange: (p: UIPredicate) => void;
  onRemove: () => void;
  onArmPicker: () => void;
  isPicking: boolean;
  onArmDraw: () => void;
  isDrawing: boolean;
  onArmAirspacePicker: () => void;
  isPickingAirspace: boolean;
  name: string;
  dateRange: DataRange | null;
  globalDateRange: GlobalDateRange | null;
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
          globalDateRange={globalDateRange}
        />
      );
    case "endpoint_within":
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
          onArmAirspacePicker={onArmAirspacePicker}
          isPickingAirspace={isPickingAirspace}
          name={name}
          dateRange={dateRange}
          globalDateRange={globalDateRange}
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
          onArmAirspacePicker={onArmAirspacePicker}
          isPickingAirspace={isPickingAirspace}
          name={name}
          dateRange={dateRange}
          globalDateRange={globalDateRange}
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
    case "registration":
      return (
        <RegistrationCard
          pred={pred}
          onChange={(p) => {
            onChange(p);
          }}
          onRemove={onRemove}
        />
      );
    case "icao24":
      return (
        <Icao24Card
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
  onArmAirspacePicker: (id: string) => void;
  airspacePickingId: string | null;
  regionCount: number;
  labels: Map<string, string>;
  noAddFilter?: boolean;
  dateRange: DataRange | null;
  globalDateRange: GlobalDateRange | null;
}

function GroupBlock({
  group,
  onChange,
  onRemove,
  onArmPicker,
  pickingId,
  onArmDraw,
  drawingId,
  onArmAirspacePicker,
  airspacePickingId,
  regionCount,
  labels,
  noAddFilter,
  dateRange,
  globalDateRange,
}: GroupBlockProps): React.ReactElement {
  const updateChild = (childId: string, next: QueryItem): void => {
    onChange({
      ...group,
      items: group.items.map((item) => (item.id === childId ? next : item)),
    });
  };
  const removeChild = (childId: string): void => {
    onChange({
      ...group,
      items: group.items.filter((item) => item.id !== childId),
    });
  };
  const addChild = (kind: AddKind): void => {
    const rc =
      group.items.filter(
        (i) => i.kind === "region" || i.kind === "always_within",
      ).length + regionCount;
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
            {group.mode === "all"
              ? "All filters must match"
              : "Any filter must match"}
          </span>
          <button className="pred-x" onClick={onRemove} title="Remove group">
            <X size={12} />
          </button>
        </div>
      )}

      <div className={isRoot ? "group-root-body" : "filter-group-body"}>
        {group.items.length === 0 && (
          <div
            style={{
              color: "var(--fg-3)",
              fontSize: 12,
              textAlign: "center",
              padding: "20px 0",
            }}
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
                <div style={{ marginTop: 4 }}>
                  Add a filter below to get started.
                </div>
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
              onArmAirspacePicker={onArmAirspacePicker}
              airspacePickingId={airspacePickingId}
              regionCount={regionCount}
              labels={labels}
              dateRange={dateRange}
              globalDateRange={globalDateRange}
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
              onArmAirspacePicker={() => {
                onArmAirspacePicker(item.id);
              }}
              isPickingAirspace={airspacePickingId === item.id}
              name={
                labels.get(item.id) ??
                (item.kind === "aircraft" ? "Aircraft" : "Callsign")
              }
              dateRange={dateRange}
              globalDateRange={globalDateRange}
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
  onArmAirspacePicker: (id: string) => void;
  airspacePickingId: string | null;
  dateRange: DataRange | null;
  globalDateRange: GlobalDateRange | null;
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
        item.kind !== "endpoint_within" &&
        item.kind !== "region" &&
        item.kind !== "always_within"
      )
        continue;
      const base =
        item.kind === "endpoint_within"
          ? item.mode === "start"
            ? "Starts Within"
            : item.mode === "end"
              ? "Ends Within"
              : "Endpoint" // "either" and "both"
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
  onArmAirspacePicker,
  airspacePickingId,
  dateRange,
  globalDateRange,
}: QueryBuilderBodyProps): React.ReactElement {
  return (
    <GroupBlock
      group={rootGroup}
      onChange={onGroupChange}
      onArmPicker={onArmPicker}
      pickingId={pickingId}
      onArmDraw={onArmDraw}
      drawingId={drawingId}
      onArmAirspacePicker={onArmAirspacePicker}
      airspacePickingId={airspacePickingId}
      regionCount={countRegions(rootGroup)}
      labels={computeLabels(rootGroup)}
      noAddFilter
      dateRange={dateRange}
      globalDateRange={globalDateRange}
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
    onGroupChange({
      ...rootGroup,
      items: [...rootGroup.items, makeItem(kind, rc)],
    });
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
  const enabled =
    dateRangeValid && rootGroup.items.length > 0 && isGroupValid(rootGroup);
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
