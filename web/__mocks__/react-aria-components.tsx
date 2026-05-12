import React from "react";
import { parseDateTime } from "@internationalized/date";
import type { CalendarDateTime } from "@internationalized/date";

// Minimal mocks for components used in DateTimeField.

export function DatePicker({
  value,
  onChange,
  children: _children,
}: {
  value: CalendarDateTime | null;
  onChange: (d: CalendarDateTime | null) => void;
  granularity?: string;
  minValue?: unknown;
  maxValue?: unknown;
  children?: React.ReactNode;
}): React.ReactElement {
  const dateTimeStr = value ? value.toString().slice(0, 16) : "";
  return (
    <input
      placeholder="YYYY-MM-DDTHH:MM"
      value={dateTimeStr}
      onChange={(e) => {
        const v = e.target.value;
        try {
          onChange(v.length >= 16 ? parseDateTime(v + ":00") : null);
        } catch {
          onChange(null);
        }
      }}
    />
  );
}

// Stub structural components used as imports in QueryBuilder.tsx.
export function Group({ children }: { children?: React.ReactNode }): React.ReactElement {
  return <div>{children}</div>;
}
export function Button({
  children,
  slot: _slot,
}: {
  children?: React.ReactNode;
  slot?: string;
  [key: string]: unknown;
}): React.ReactElement {
  return <button type="button">{children}</button>;
}
export function Popover({ children }: { children?: React.ReactNode }): React.ReactElement {
  return <>{children}</>;
}
export function Dialog({ children }: { children?: React.ReactNode }): React.ReactElement {
  return <div>{children}</div>;
}
export function Calendar({ children }: { children?: React.ReactNode }): React.ReactElement {
  return <div>{children}</div>;
}
export function CalendarGrid({ children }: { children?: unknown }): React.ReactElement {
  return <table>{typeof children === "function" ? null : (children as React.ReactNode)}</table>;
}
export function CalendarGridHeader({ children }: { children?: unknown }): React.ReactElement {
  return <thead>{typeof children === "function" ? null : (children as React.ReactNode)}</thead>;
}
export function CalendarGridBody({ children }: { children?: unknown }): React.ReactElement {
  return <tbody>{typeof children === "function" ? null : (children as React.ReactNode)}</tbody>;
}
export function CalendarHeaderCell({ children }: { children?: React.ReactNode }): React.ReactElement {
  return <th>{children}</th>;
}
export function CalendarCell(): React.ReactElement {
  return <td />;
}
export function Heading({ children }: { children?: React.ReactNode }): React.ReactElement {
  return <div>{children}</div>;
}
export function DateInput({ children }: { children?: unknown }): React.ReactElement {
  return <span>{typeof children === "function" ? null : (children as React.ReactNode)}</span>;
}
export function DateSegment(): React.ReactElement {
  return <span />;
}
