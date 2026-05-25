import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
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
    render(
      <ResultsPanel
        flights={null}
        loading={false}
        error={null}
        hasMore={false}
        onLoadMore={() => {}}
      />,
    );
    expect(screen.getByText("No results yet.")).toBeInTheDocument();
    expect(screen.getByText("Run a query to see flights.")).toBeInTheDocument();
  });

  it("shows loading indicator when loading with no flights yet", () => {
    render(
      <ResultsPanel
        flights={null}
        loading={true}
        error={null}
        hasMore={false}
        onLoadMore={() => {}}
      />,
    );
    expect(screen.getByText("Loading…")).toBeInTheDocument();
  });

  it("shows empty state when flights list is empty and not loading", () => {
    render(
      <ResultsPanel
        flights={[]}
        loading={false}
        error={null}
        hasMore={false}
        onLoadMore={() => {}}
      />,
    );
    expect(screen.getByText("No flights matched.")).toBeInTheDocument();
  });

  it("shows empty state and load-more footer when zero results but hasMore", () => {
    render(
      <ResultsPanel
        flights={[]}
        loading={false}
        error={null}
        hasMore={true}
        onLoadMore={() => {}}
        windowFrom="2025-03-05T00:00:00Z"
        queryEndDate="2025-04-01"
      />,
    );
    expect(screen.getByText("No flights matched.")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Load earlier results" }),
    ).toBeInTheDocument();
    expect(screen.getByText(/Fetched/)).toBeInTheDocument();
  });

  it("shows error message", () => {
    render(
      <ResultsPanel
        flights={null}
        loading={false}
        error="Server error"
        hasMore={false}
        onLoadMore={() => {}}
      />,
    );
    expect(screen.getByText(/Server error/)).toBeInTheDocument();
  });

  it("renders a flight row with callsign and type", () => {
    render(
      <ResultsPanel
        flights={[makeFlight()]}
        loading={false}
        error={null}
        hasMore={false}
        onLoadMore={() => {}}
      />,
    );
    expect(screen.getByText("BAW123")).toBeInTheDocument();
    expect(screen.getByText(/B738/)).toBeInTheDocument();
  });

  it("falls back to icao24 when callsign is null", () => {
    render(
      <ResultsPanel
        flights={[makeFlight({ callsign: null })]}
        loading={false}
        error={null}
        hasMore={false}
        onLoadMore={() => {}}
      />,
    );
    expect(screen.getByText("aabbcc")).toBeInTheDocument();
  });

  it("shows em-dash when no type or emitter category", () => {
    render(
      <ResultsPanel
        flights={[makeFlight({ icao_type: null, emitter_category: null })]}
        loading={false}
        error={null}
        hasMore={false}
        onLoadMore={() => {}}
      />,
    );
    expect(screen.getByText("—")).toBeInTheDocument();
  });

  it("renders multiple flight rows", () => {
    const flights = [
      makeFlight({ flight_id: "a:1", icao24: "aa1111", callsign: "EZY001" }),
      makeFlight({ flight_id: "b:2", icao24: "bb2222", callsign: "RYR002" }),
    ];
    render(
      <ResultsPanel
        flights={flights}
        loading={false}
        error={null}
        hasMore={false}
        onLoadMore={() => {}}
      />,
    );
    expect(screen.getByText("EZY001")).toBeInTheDocument();
    expect(screen.getByText("RYR002")).toBeInTheDocument();
  });

  it("shows Load more button when hasMore is true", () => {
    render(
      <ResultsPanel
        flights={[makeFlight()]}
        loading={false}
        error={null}
        hasMore={true}
        onLoadMore={() => {}}
      />,
    );
    expect(
      screen.getByRole("button", { name: "Load earlier results" }),
    ).toBeInTheDocument();
  });

  it("does not show Load more button when hasMore is false", () => {
    render(
      <ResultsPanel
        flights={[makeFlight()]}
        loading={false}
        error={null}
        hasMore={false}
        onLoadMore={() => {}}
      />,
    );
    expect(
      screen.queryByRole("button", { name: "Load earlier results" }),
    ).not.toBeInTheDocument();
  });

  it("calls onLoadMore when Load more is clicked", () => {
    const onLoadMore = vi.fn();
    render(
      <ResultsPanel
        flights={[makeFlight()]}
        loading={false}
        error={null}
        hasMore={true}
        onLoadMore={onLoadMore}
      />,
    );
    fireEvent.click(
      screen.getByRole("button", { name: "Load earlier results" }),
    );
    expect(onLoadMore).toHaveBeenCalledOnce();
  });

  it("hides Load more button while loading (to prevent double-clicks)", () => {
    render(
      <ResultsPanel
        flights={[makeFlight()]}
        loading={true}
        error={null}
        hasMore={true}
        onLoadMore={() => {}}
      />,
    );
    expect(
      screen.queryByRole("button", { name: "Load earlier results" }),
    ).not.toBeInTheDocument();
    expect(screen.getByText("Loading…")).toBeInTheDocument();
  });

  it("renders a date divider for each group of flights on the same day", () => {
    const flights = [
      makeFlight({
        flight_id: "a:1",
        start_ts: "2025-01-01T10:00:00Z",
        end_ts: "2025-01-01T12:00:00Z",
      }),
      makeFlight({
        flight_id: "b:2",
        start_ts: "2025-01-02T08:00:00Z",
        end_ts: "2025-01-02T10:00:00Z",
      }),
    ];
    render(
      <ResultsPanel
        flights={flights}
        loading={false}
        error={null}
        hasMore={false}
        onLoadMore={() => {}}
      />,
    );
    expect(screen.getByText("2025-01-01")).toBeInTheDocument();
    expect(screen.getByText("2025-01-02")).toBeInTheDocument();
  });

  it("renders one divider for multiple flights on the same date", () => {
    const flights = [
      makeFlight({
        flight_id: "a:1",
        start_ts: "2025-03-15T08:00:00Z",
        end_ts: "2025-03-15T10:00:00Z",
        callsign: "EZY100",
      }),
      makeFlight({
        flight_id: "b:2",
        start_ts: "2025-03-15T12:00:00Z",
        end_ts: "2025-03-15T14:00:00Z",
        callsign: "EZY200",
      }),
    ];
    render(
      <ResultsPanel
        flights={flights}
        loading={false}
        error={null}
        hasMore={false}
        onLoadMore={() => {}}
      />,
    );
    const dividers = screen.getAllByText("2025-03-15");
    expect(dividers).toHaveLength(1);
  });

  it("shows +Nd suffix when flight end date differs from start date", () => {
    const flight = makeFlight({
      start_ts: "2025-06-30T23:00:00Z",
      end_ts: "2025-07-01T01:30:00Z",
    });
    render(
      <ResultsPanel
        flights={[flight]}
        loading={false}
        error={null}
        hasMore={false}
        onLoadMore={() => {}}
      />,
    );
    expect(screen.getByText(/\+1d/)).toBeInTheDocument();
  });

  it("renders a sparkline SVG when the flight has path coordinates", () => {
    const flight = makeFlight({
      path: {
        type: "MultiLineString",
        coordinates: [
          [
            [0, 51, 1000],
            [1, 52, 5000],
            [2, 53, 8000],
          ],
        ] as [number, number, number][][],
      },
    });
    const { container } = render(
      <ResultsPanel
        flights={[flight]}
        loading={false}
        error={null}
        hasMore={false}
        onLoadMore={() => {}}
      />,
    );
    expect(container.querySelector("svg")).not.toBeNull();
  });

  it("renders green terrain fill when path_agl_ft is provided", () => {
    const flight = makeFlight({
      path: {
        type: "MultiLineString",
        coordinates: [
          [
            [0, 51, 5000],
            [1, 52, 10000],
            [2, 53, 15000],
          ],
        ] as [number, number, number][][],
      },
      timestamps: [[1000, 2000, 3000]],
      path_agl_ft: [
        [
          [1000, 2000],
          [2000, 3000],
          [3000, 4000],
        ],
      ],
    });
    const { container } = render(
      <ResultsPanel
        flights={[flight]}
        loading={false}
        error={null}
        hasMore={false}
        onLoadMore={() => {}}
      />,
    );
    const paths = container.querySelectorAll("path");
    const greenPath = Array.from(paths).find((p) =>
      p.getAttribute("fill")?.includes("74,222,128"),
    );
    expect(greenPath).not.toBeUndefined();
  });

  it("shows altitude and AGL in sparkline hover tooltip when AGL data is present", () => {
    const flight = makeFlight({
      flight_id: "aabbcc:2025-01-01T10:00:00Z",
      path: {
        type: "MultiLineString",
        coordinates: [
          [
            [0, 51, 5000],
            [1, 52, 10000],
            [2, 53, 15000],
          ],
        ] as [number, number, number][][],
      },
      timestamps: [[1000, 2000, 3000]],
      path_agl_ft: [
        [
          [1000, 2000],
          [2000, 3000],
          [3000, 4000],
        ],
      ],
    });
    const { container } = render(
      <ResultsPanel
        flights={[flight]}
        loading={false}
        error={null}
        hasMore={false}
        onLoadMore={() => {}}
        hoveredPoint={{ flightId: flight.flight_id, pointIdx: 1 }}
      />,
    );
    expect(container.querySelector("line")).not.toBeNull();
    expect(screen.getByText(/agl/)).toBeInTheDocument();
  });

  it("does not render a sparkline when path is absent", () => {
    const { container } = render(
      <ResultsPanel
        flights={[makeFlight()]}
        loading={false}
        error={null}
        hasMore={false}
        onLoadMore={() => {}}
      />,
    );
    expect(container.querySelector("svg")).toBeNull();
  });

  it("calls onSelectFlight with the flight id when a flight row is clicked", () => {
    const onSelectFlight = vi.fn();
    const flight = makeFlight();
    render(
      <ResultsPanel
        flights={[flight]}
        loading={false}
        error={null}
        hasMore={false}
        onLoadMore={() => {}}
        onSelectFlight={onSelectFlight}
      />,
    );
    fireEvent.click(screen.getByText("BAW123"));
    expect(onSelectFlight).toHaveBeenCalledWith(flight.flight_id);
  });

  it("calls onSelectFlight with null when clicking the already-selected flight", () => {
    const onSelectFlight = vi.fn();
    const flight = makeFlight();
    render(
      <ResultsPanel
        flights={[flight]}
        loading={false}
        error={null}
        hasMore={false}
        onLoadMore={() => {}}
        selectedFlightId={flight.flight_id}
        onSelectFlight={onSelectFlight}
      />,
    );
    fireEvent.click(screen.getByText("BAW123"));
    expect(onSelectFlight).toHaveBeenCalledWith(null);
  });

  it("renders the sparkline hover tooltip when hoveredPoint matches the flight", () => {
    const flight = makeFlight({
      flight_id: "aabbcc:2025-01-01T10:00:00Z",
      path: {
        type: "MultiLineString",
        coordinates: [
          [
            [0, 51, 1000],
            [1, 52, 5000],
            [2, 53, 8000],
          ],
        ] as [number, number, number][][],
      },
    });
    const { container } = render(
      <ResultsPanel
        flights={[flight]}
        loading={false}
        error={null}
        hasMore={false}
        onLoadMore={() => {}}
        hoveredPoint={{ flightId: flight.flight_id, pointIdx: 1 }}
      />,
    );
    // Hover crosshair line is rendered inside the SVG
    expect(container.querySelector("line")).not.toBeNull();
  });

  it("calls onHoverPoint with null when mouse leaves the sparkline", () => {
    const onHoverPoint = vi.fn();
    const flight = makeFlight({
      path: {
        type: "MultiLineString",
        coordinates: [
          [
            [0, 51, 1000],
            [1, 52, 5000],
          ],
        ] as [number, number, number][][],
      },
    });
    const { container } = render(
      <ResultsPanel
        flights={[flight]}
        loading={false}
        error={null}
        hasMore={false}
        onLoadMore={() => {}}
        onHoverPoint={onHoverPoint}
      />,
    );
    const svg = container.querySelector("svg")!;
    fireEvent.mouseLeave(svg);
    expect(onHoverPoint).toHaveBeenCalledWith(null);
  });

  it("calls onHoverPoint with flight and point index on sparkline mouse move", () => {
    const onHoverPoint = vi.fn();
    const flight = makeFlight({
      path: {
        type: "MultiLineString",
        coordinates: [
          [
            [0, 51, 1000],
            [1, 52, 5000],
            [2, 53, 8000],
          ],
        ] as [number, number, number][][],
      },
    });
    const { container } = render(
      <ResultsPanel
        flights={[flight]}
        loading={false}
        error={null}
        hasMore={false}
        onLoadMore={() => {}}
        onHoverPoint={onHoverPoint}
      />,
    );
    const svg = container.querySelector("svg")!;
    vi.spyOn(svg, "getBoundingClientRect").mockReturnValue({
      left: 0,
      top: 0,
      width: 200,
      height: 20,
      right: 200,
      bottom: 20,
      x: 0,
      y: 0,
      toJSON: () => ({}),
    } as DOMRect);
    fireEvent.mouseMove(svg, { clientX: 100, clientY: 10 });
    expect(onHoverPoint).toHaveBeenCalledWith({
      flightId: flight.flight_id,
      pointIdx: expect.any(Number),
    });
  });

  it("shows registration, model, year, and operator when present", () => {
    const flight = makeFlight({
      registration: "G-EUUU",
      model: "Boeing 737-800",
      year: 2010,
      operator: "British Airways",
    });
    render(
      <ResultsPanel
        flights={[flight]}
        loading={false}
        error={null}
        hasMore={false}
        onLoadMore={() => {}}
        selectedFlightId={flight.flight_id}
      />,
    );
    expect(screen.getByText("G-EUUU")).toBeInTheDocument();
    expect(screen.getByText("Boeing 737-800")).toBeInTheDocument();
    expect(screen.getByText("2010")).toBeInTheDocument();
    expect(screen.getByText("British Airways")).toBeInTheDocument();
  });

  describe("scrollIntoView behaviour", () => {
    let scrollIntoView: ReturnType<typeof vi.fn>;

    beforeEach(() => {
      vi.useFakeTimers();
      scrollIntoView = vi.fn();
      window.HTMLElement.prototype.scrollIntoView = scrollIntoView;
    });

    afterEach(() => {
      vi.useRealTimers();
    });

    it("scrolls immediately when panel is already open and selectedFlightId changes", () => {
      const flight = makeFlight();
      const { rerender } = render(
        <ResultsPanel
          flights={[flight]}
          loading={false}
          error={null}
          hasMore={false}
          onLoadMore={() => {}}
          collapsed={false}
          selectedFlightId={null}
        />,
      );
      rerender(
        <ResultsPanel
          flights={[flight]}
          loading={false}
          error={null}
          hasMore={false}
          onLoadMore={() => {}}
          collapsed={false}
          selectedFlightId={flight.flight_id}
        />,
      );
      expect(scrollIntoView).toHaveBeenCalledOnce();
    });

    it("defers scrollIntoView until after the slide-in transition when panel opens", () => {
      const flight = makeFlight();
      const { rerender } = render(
        <ResultsPanel
          flights={[flight]}
          loading={false}
          error={null}
          hasMore={false}
          onLoadMore={() => {}}
          collapsed={true}
          selectedFlightId={flight.flight_id}
        />,
      );
      rerender(
        <ResultsPanel
          flights={[flight]}
          loading={false}
          error={null}
          hasMore={false}
          onLoadMore={() => {}}
          collapsed={false}
          selectedFlightId={flight.flight_id}
        />,
      );
      expect(scrollIntoView).not.toHaveBeenCalled();
      vi.advanceTimersByTime(240);
      expect(scrollIntoView).toHaveBeenCalledOnce();
    });
  });
});
