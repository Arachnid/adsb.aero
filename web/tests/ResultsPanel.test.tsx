import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { ResultsPanel } from "../src/components/results/ResultsPanel";
import type { FlightDetail } from "../src/lib/api";

function makeFlight(overrides: Partial<FlightDetail> = {}): FlightDetail {
  return {
    flight_id: "aabbcc:2025-01-01T10:00:00Z",
    icao24: "aabbcc",
    callsign: "BAW123",
    icao_type: "B738",
    emitter_category: "A3",
    start_ts: "2025-01-01T10:00:00Z",
    end_ts: "2025-01-01T12:30:00Z",
    start_point: { type: "Point", coordinates: [0, 51, 0] },
    end_point: { type: "Point", coordinates: [2, 52, 0] },
    point_count: 50,
    raw_point_count: 200,
    ingest_batch_date: "2025-01-01",
    ...overrides,
  };
}

describe("ResultsPanel", () => {
  it("shows idle placeholder when no flights and not loading", () => {
    render(<ResultsPanel flights={null} loading={false} error={null} hasMore={false} onLoadMore={() => {}} />);
    expect(screen.getByText("No results yet.")).toBeInTheDocument();
    expect(screen.getByText("Run a query to see flights.")).toBeInTheDocument();
  });

  it("shows loading indicator when loading with no flights yet", () => {
    render(<ResultsPanel flights={null} loading={true} error={null} hasMore={false} onLoadMore={() => {}} />);
    expect(screen.getByText("Loading…")).toBeInTheDocument();
  });

  it("shows empty state when flights list is empty and not loading", () => {
    render(<ResultsPanel flights={[]} loading={false} error={null} hasMore={false} onLoadMore={() => {}} />);
    expect(screen.getByText("No flights matched.")).toBeInTheDocument();
  });

  it("shows error message", () => {
    render(<ResultsPanel flights={null} loading={false} error="Server error" hasMore={false} onLoadMore={() => {}} />);
    expect(screen.getByText(/Server error/)).toBeInTheDocument();
  });

  it("renders a flight row with callsign and type", () => {
    render(<ResultsPanel flights={[makeFlight()]} loading={false} error={null} hasMore={false} onLoadMore={() => {}} />);
    expect(screen.getByText("BAW123")).toBeInTheDocument();
    expect(screen.getByText(/B738/)).toBeInTheDocument();
  });

  it("falls back to icao24 when callsign is null", () => {
    render(<ResultsPanel flights={[makeFlight({ callsign: null })]} loading={false} error={null} hasMore={false} onLoadMore={() => {}} />);
    expect(screen.getByText("aabbcc")).toBeInTheDocument();
  });

  it("shows em-dash when no type or emitter category", () => {
    render(<ResultsPanel flights={[makeFlight({ icao_type: null, emitter_category: null })]} loading={false} error={null} hasMore={false} onLoadMore={() => {}} />);
    expect(screen.getByText("—")).toBeInTheDocument();
  });

  it("renders multiple flight rows", () => {
    const flights = [
      makeFlight({ flight_id: "a:1", icao24: "aa1111", callsign: "EZY001" }),
      makeFlight({ flight_id: "b:2", icao24: "bb2222", callsign: "RYR002" }),
    ];
    render(<ResultsPanel flights={flights} loading={false} error={null} hasMore={false} onLoadMore={() => {}} />);
    expect(screen.getByText("EZY001")).toBeInTheDocument();
    expect(screen.getByText("RYR002")).toBeInTheDocument();
  });

  it("shows Load more button when hasMore is true", () => {
    render(<ResultsPanel flights={[makeFlight()]} loading={false} error={null} hasMore={true} onLoadMore={() => {}} />);
    expect(screen.getByRole("button", { name: "Load more" })).toBeInTheDocument();
  });

  it("does not show Load more button when hasMore is false", () => {
    render(<ResultsPanel flights={[makeFlight()]} loading={false} error={null} hasMore={false} onLoadMore={() => {}} />);
    expect(screen.queryByRole("button", { name: "Load more" })).not.toBeInTheDocument();
  });

  it("calls onLoadMore when Load more is clicked", () => {
    const onLoadMore = vi.fn();
    render(<ResultsPanel flights={[makeFlight()]} loading={false} error={null} hasMore={true} onLoadMore={onLoadMore} />);
    fireEvent.click(screen.getByRole("button", { name: "Load more" }));
    expect(onLoadMore).toHaveBeenCalledOnce();
  });

  it("hides Load more button while loading (to prevent double-clicks)", () => {
    render(<ResultsPanel flights={[makeFlight()]} loading={true} error={null} hasMore={true} onLoadMore={() => {}} />);
    expect(screen.queryByRole("button", { name: "Load more" })).not.toBeInTheDocument();
    expect(screen.getByText("Loading…")).toBeInTheDocument();
  });
});
