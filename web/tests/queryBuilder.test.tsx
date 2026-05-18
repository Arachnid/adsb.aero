import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";

vi.mock("react-aria-components");
vi.mock("../src/lib/api", () => ({
  getIcaoTypes: vi.fn().mockResolvedValue([
    { icao_type: "B738", model: "Boeing 737-800", count: 1000 },
    { icao_type: "A320", model: "Airbus A320", count: 800 },
  ]),
}));
import {
  QueryBuilderFooter,
  QueryBuilderAddMenu,
  QueryBuilderBody,
  FilterGroup,
  makeId,
} from "../src/components/query/QueryBuilder";

// ---- helpers ----------------------------------------------------------------

function emptyGroup(): FilterGroup {
  return { id: makeId(), kind: "group", mode: "all", items: [] };
}

function makeGroup(items: FilterGroup["items"]): FilterGroup {
  return { id: makeId(), kind: "group", mode: "all", items };
}

const noop = (): void => {};

function bodyProps(group: FilterGroup, onChange = vi.fn()) {
  return {
    rootGroup: group,
    onGroupChange: onChange,
    onArmPicker: noop as (id: string) => void,
    pickingId: null,
    onArmDraw: noop as (id: string) => void,
    drawingId: null,
    onArmAirspacePicker: noop as (id: string) => void,
    airspacePickingId: null,
    dateRange: null,
    globalDateRange: { from: "2024-01-01", to: "2024-01-07" },
  };
}

// ---- QueryBuilderFooter -----------------------------------------------------

describe("QueryBuilderFooter", () => {
  it("is disabled when rootGroup has no items", () => {
    render(
      <QueryBuilderFooter
        rootGroup={emptyGroup()}
        dateRangeValid={true}
        onRun={noop}
      />,
    );
    expect(screen.getByRole("button", { name: /run query/i })).toBeDisabled();
  });

  it("is disabled when group contains an invalid predicate", () => {
    const group = makeGroup([
      { id: makeId(), kind: "aircraft", icaoTypes: [], emitters: [] },
    ]);
    render(
      <QueryBuilderFooter
        rootGroup={group}
        dateRangeValid={true}
        onRun={noop}
      />,
    );
    expect(screen.getByRole("button", { name: /run query/i })).toBeDisabled();
  });

  it("is disabled when dateRangeValid is false", () => {
    const group = makeGroup([
      { id: makeId(), kind: "callsign", pattern: "^BAW" },
    ]);
    render(
      <QueryBuilderFooter
        rootGroup={group}
        dateRangeValid={false}
        onRun={noop}
      />,
    );
    expect(screen.getByRole("button", { name: /run query/i })).toBeDisabled();
  });

  it("is enabled when group contains a valid predicate and date range is valid", () => {
    const group = makeGroup([
      { id: makeId(), kind: "callsign", pattern: "^BAW" },
    ]);
    render(
      <QueryBuilderFooter
        rootGroup={group}
        dateRangeValid={true}
        onRun={noop}
      />,
    );
    expect(
      screen.getByRole("button", { name: /run query/i }),
    ).not.toBeDisabled();
  });

  it("calls onRun when clicked while enabled", () => {
    const onRun = vi.fn();
    const group = makeGroup([
      { id: makeId(), kind: "callsign", pattern: "^BAW" },
    ]);
    render(
      <QueryBuilderFooter
        rootGroup={group}
        dateRangeValid={true}
        onRun={onRun}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: /run query/i }));
    expect(onRun).toHaveBeenCalledOnce();
  });

  it("does not call onRun when button is disabled", () => {
    const onRun = vi.fn();
    render(
      <QueryBuilderFooter
        rootGroup={emptyGroup()}
        dateRangeValid={true}
        onRun={onRun}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: /run query/i }));
    expect(onRun).not.toHaveBeenCalled();
  });
});

// ---- QueryBuilderAddMenu ----------------------------------------------------

describe("QueryBuilderAddMenu", () => {
  it("does not show filter options initially", () => {
    render(
      <QueryBuilderAddMenu rootGroup={emptyGroup()} onGroupChange={noop} />,
    );
    expect(screen.queryByText("Callsign")).toBeNull();
  });

  it("shows filter options after clicking Add filter", () => {
    render(
      <QueryBuilderAddMenu rootGroup={emptyGroup()} onGroupChange={noop} />,
    );
    fireEvent.click(screen.getByRole("button", { name: /add filter/i }));
    expect(screen.getByText("Aircraft")).toBeDefined();
    expect(screen.getByText("Callsign")).toBeDefined();
    expect(screen.getByText("Ever")).toBeDefined();
    expect(screen.getByText("Always")).toBeDefined();
  });

  it("appends a callsign predicate when Callsign is clicked", () => {
    const onChange = vi.fn();
    const root = emptyGroup();
    render(<QueryBuilderAddMenu rootGroup={root} onGroupChange={onChange} />);
    fireEvent.click(screen.getByRole("button", { name: /add filter/i }));
    fireEvent.click(screen.getByText("Callsign"));
    expect(onChange).toHaveBeenCalledOnce();
    const updated: FilterGroup = onChange.mock.calls[0][0] as FilterGroup;
    expect(updated.items).toHaveLength(1);
    expect(updated.items[0]).toMatchObject({ kind: "callsign", pattern: "" });
  });

  it("appends an aircraft predicate when Aircraft is clicked", () => {
    const onChange = vi.fn();
    render(
      <QueryBuilderAddMenu rootGroup={emptyGroup()} onGroupChange={onChange} />,
    );
    fireEvent.click(screen.getByRole("button", { name: /add filter/i }));
    fireEvent.click(screen.getByText("Aircraft"));
    const updated: FilterGroup = onChange.mock.calls[0][0] as FilterGroup;
    expect(updated.items[0]).toMatchObject({
      kind: "aircraft",
      icaoTypes: [],
      emitters: [],
    });
  });

  it("closes the menu after an option is selected", () => {
    render(
      <QueryBuilderAddMenu rootGroup={emptyGroup()} onGroupChange={noop} />,
    );
    fireEvent.click(screen.getByRole("button", { name: /add filter/i }));
    fireEvent.click(screen.getByText("Callsign"));
    expect(screen.queryByText("Aircraft")).toBeNull();
  });

  it("toggles the menu closed when Add filter is clicked again", () => {
    render(
      <QueryBuilderAddMenu rootGroup={emptyGroup()} onGroupChange={noop} />,
    );
    fireEvent.click(screen.getByRole("button", { name: /add filter/i }));
    fireEvent.click(screen.getByRole("button", { name: /add filter/i }));
    expect(screen.queryByText("Callsign")).toBeNull();
  });
});

// ---- QueryBuilderBody -------------------------------------------------------

describe("QueryBuilderBody", () => {
  it("shows empty state message when no filters", () => {
    render(<QueryBuilderBody {...bodyProps(emptyGroup())} />);
    expect(screen.getByText("No filters yet.")).toBeDefined();
  });

  // ---- AircraftCard ---------------------------------------------------------

  describe("AircraftCard", () => {
    it("renders with invalid style when both lists are empty", () => {
      const group = makeGroup([
        { id: "a1", kind: "aircraft", icaoTypes: [], emitters: [] },
      ]);
      const { container } = render(<QueryBuilderBody {...bodyProps(group)} />);
      expect(container.querySelector(".pred--invalid")).not.toBeNull();
    });

    it("renders without invalid style when icaoTypes is populated", () => {
      const group = makeGroup([
        { id: "a1", kind: "aircraft", icaoTypes: ["B738"], emitters: [] },
      ]);
      const { container } = render(<QueryBuilderBody {...bodyProps(group)} />);
      expect(container.querySelector(".pred--invalid")).toBeNull();
    });

    it("shows aircraft name in header", () => {
      const group = makeGroup([
        { id: "a1", kind: "aircraft", icaoTypes: [], emitters: [] },
      ]);
      render(<QueryBuilderBody {...bodyProps(group)} />);
      expect(screen.getByText("Aircraft")).toBeDefined();
    });

    it("calls onGroupChange with updated icaoTypes when a chip is toggled", async () => {
      const onChange = vi.fn();
      const group = makeGroup([
        { id: "a1", kind: "aircraft", icaoTypes: [], emitters: [] },
      ]);
      render(<QueryBuilderBody {...bodyProps(group, onChange)} />);
      // open the ICAO types dropdown (first "+ choose" button)
      fireEvent.click(screen.getAllByText("+ choose")[0]);
      // wait for async options to load then click B738
      await waitFor(() => screen.getByText("B738"));
      fireEvent.click(screen.getByText("B738"));
      const updated: FilterGroup = onChange.mock.calls[0][0] as FilterGroup;
      const pred = updated.items[0];
      expect(pred.kind === "aircraft" && pred.icaoTypes).toContain("B738");
    });
  });

  // ---- CallsignCard ---------------------------------------------------------

  describe("CallsignCard", () => {
    it("renders with invalid style when pattern is empty", () => {
      const group = makeGroup([{ id: "c1", kind: "callsign", pattern: "" }]);
      const { container } = render(<QueryBuilderBody {...bodyProps(group)} />);
      expect(container.querySelector(".pred--invalid")).not.toBeNull();
    });

    it("calls onGroupChange with updated pattern on input change", () => {
      const onChange = vi.fn();
      const group = makeGroup([{ id: "c1", kind: "callsign", pattern: "" }]);
      render(<QueryBuilderBody {...bodyProps(group, onChange)} />);
      fireEvent.change(screen.getByPlaceholderText("^BAW.*"), {
        target: { value: "^DLH" },
      });
      const updated: FilterGroup = onChange.mock.calls[0][0] as FilterGroup;
      const pred = updated.items[0];
      expect(pred.kind === "callsign" && pred.pattern).toBe("^DLH");
    });
  });

  // ---- PointRadiusCard (endpoint_within) -------------------------------------

  describe("PointRadiusCard", () => {
    const basePred = {
      id: "p1",
      kind: "endpoint_within" as const,
      mode: "start" as const,
      shape: "none" as const,
      lat: null,
      lng: null,
      radiusNm: 25,
      polygon: null,
      airspaceName: null,
      airspaceLabel: null,
      startTimeFrom: "",
      startTimeTo: "",
      endTimeFrom: "",
      endTimeTo: "",
    };

    it("shows From and To inputs regardless of shape", () => {
      const group = makeGroup([basePred]);
      render(<QueryBuilderBody {...bodyProps(group)} />);
      expect(screen.getByText("From")).toBeDefined();
      expect(screen.getByText("To")).toBeDefined();
    });

    it("does not show radius slider for shape=none", () => {
      const group = makeGroup([basePred]);
      render(<QueryBuilderBody {...bodyProps(group)} />);
      expect(screen.queryByText("Radius")).toBeNull();
    });

    it("shows radius slider when shape=circle", () => {
      const group = makeGroup([{ ...basePred, shape: "circle" as const }]);
      render(<QueryBuilderBody {...bodyProps(group)} />);
      expect(screen.getByText("Radius")).toBeDefined();
    });

    it("shows Draw on map button when shape=polygon", () => {
      const group = makeGroup([{ ...basePred, shape: "polygon" as const }]);
      render(<QueryBuilderBody {...bodyProps(group)} />);
      expect(screen.getByText("Draw on map")).toBeDefined();
    });

    it("shows viewport message when shape=viewport", () => {
      const group = makeGroup([{ ...basePred, shape: "viewport" as const }]);
      render(<QueryBuilderBody {...bodyProps(group)} />);
      expect(screen.getByText("Uses current map viewport")).toBeDefined();
    });

    it("updates startTimeFrom via From datetime input", () => {
      const onChange = vi.fn();
      const group = makeGroup([basePred]);
      render(<QueryBuilderBody {...bodyProps(group, onChange)} />);
      fireEvent.change(screen.getAllByPlaceholderText("YYYY-MM-DDTHH:MM")[0], {
        target: { value: "2024-01-01T00:00" },
      });
      const updated: FilterGroup = onChange.mock.calls[0][0] as FilterGroup;
      const pred = updated.items[0];
      expect(pred.kind === "endpoint_within" && pred.startTimeFrom).toBe(
        "2024-01-01T00:00",
      );
    });

    it("is invalid with shape=none and no time", () => {
      const group = makeGroup([basePred]);
      const { container } = render(<QueryBuilderBody {...bodyProps(group)} />);
      expect(container.querySelector(".pred--invalid")).not.toBeNull();
    });

    it("is valid with shape=none and startTimeFrom set", () => {
      const group = makeGroup([
        { ...basePred, startTimeFrom: "2024-01-01T00:00" },
      ]);
      const { container } = render(<QueryBuilderBody {...bodyProps(group)} />);
      expect(container.querySelector(".pred--invalid")).toBeNull();
    });

    it("clicking 'End' mode button changes mode to end", () => {
      const onChange = vi.fn();
      const group = makeGroup([basePred]);
      render(<QueryBuilderBody {...bodyProps(group, onChange)} />);
      fireEvent.click(screen.getByText("End"));
      const updated: FilterGroup = onChange.mock.calls[0][0] as FilterGroup;
      const pred = updated.items[0];
      expect(pred.kind === "endpoint_within" && pred.mode).toBe("end");
    });

    it("shows 'Departure time' and 'Arrival time' labels in both mode", () => {
      const group = makeGroup([{ ...basePred, mode: "both" as const }]);
      render(<QueryBuilderBody {...bodyProps(group)} />);
      expect(screen.getByText("Departure time")).toBeDefined();
      expect(screen.getByText("Arrival time")).toBeDefined();
    });
  });

  // ---- IntersectsCard (region) ---------------------------------------------

  describe("IntersectsCard", () => {
    const basePred = {
      id: "r1",
      kind: "region" as const,
      regionName: "Region 1",
      shape: "none" as const,
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
      squawkCodes: [] as string[],
      dwellMinMin: null,
      dwellMaxMin: null,
      distanceMinNm: null,
      distanceMaxNm: null,
    };

    it("shows altitude checkbox even when shape=none", () => {
      const group = makeGroup([basePred]);
      render(<QueryBuilderBody {...bodyProps(group)} />);
      expect(screen.getByText("Altitude range")).toBeDefined();
      expect(screen.queryByText("Alt min")).toBeNull();
    });

    it("shows altitude inputs after checking the altitude checkbox", () => {
      const group = makeGroup([basePred]);
      render(<QueryBuilderBody {...bodyProps(group)} />);
      fireEvent.click(screen.getByLabelText("Altitude range"));
      expect(screen.getByText("Alt min")).toBeDefined();
      expect(screen.getByText("Alt max")).toBeDefined();
    });

    it("shows Time range checkbox", () => {
      const group = makeGroup([basePred]);
      render(<QueryBuilderBody {...bodyProps(group)} />);
      expect(screen.getByText("Time range")).toBeDefined();
    });

    it("shows From and To inputs after checking the time range checkbox", () => {
      const group = makeGroup([basePred]);
      render(<QueryBuilderBody {...bodyProps(group)} />);
      fireEvent.click(screen.getByLabelText("Time range"));
      expect(screen.getAllByText("From").length).toBeGreaterThan(0);
      expect(screen.getAllByText("To").length).toBeGreaterThan(0);
    });

    it("shows Ever label for region pred", () => {
      const group = makeGroup([{ ...basePred, shape: "viewport" as const }]);
      render(<QueryBuilderBody {...bodyProps(group)} />);
      expect(screen.getByText("Ever")).toBeDefined();
    });

    it("shows Squawk filter checkbox", () => {
      const group = makeGroup([basePred]);
      render(<QueryBuilderBody {...bodyProps(group)} />);
      expect(screen.getByText("Squawk filter")).toBeDefined();
    });

    it("shows squawk input after checking Squawk filter", () => {
      const group = makeGroup([basePred]);
      render(<QueryBuilderBody {...bodyProps(group)} />);
      fireEvent.click(screen.getByLabelText("Squawk filter"));
      expect(screen.getByPlaceholderText("e.g. 7700")).toBeDefined();
    });

    it("shows altitude inputs when altMin is pre-set (e.g. from airspace selection)", () => {
      const group = makeGroup([
        { ...basePred, altMin: 5000, altMinRef: "ft" as const },
      ]);
      render(<QueryBuilderBody {...bodyProps(group)} />);
      // Section must be visible even though the user never clicked the checkbox
      expect(screen.getByText("Alt min")).toBeDefined();
      expect(screen.getByText("Alt max")).toBeDefined();
    });

    it("shows time inputs when timeFrom is pre-set", () => {
      const group = makeGroup([{ ...basePred, timeFrom: "2024-01-01T10:00" }]);
      render(<QueryBuilderBody {...bodyProps(group)} />);
      expect(screen.getAllByText("From").length).toBeGreaterThan(0);
    });

    it("unchecking altitude checkbox clears the values", () => {
      const onChange = vi.fn();
      const group = makeGroup([
        { ...basePred, altMin: 5000, altMinRef: "ft" as const },
      ]);
      render(<QueryBuilderBody {...bodyProps(group, onChange)} />);
      fireEvent.click(screen.getByLabelText("Altitude range"));
      const updated: FilterGroup = onChange.mock.calls[0][0] as FilterGroup;
      const pred = updated.items[0];
      expect(pred.kind === "region" && pred.altMin).toBeNull();
      expect(pred.kind === "region" && pred.altMax).toBeNull();
    });
  });

  // ---- Remove button --------------------------------------------------------

  describe("remove button", () => {
    it("removes the predicate from the group", () => {
      const onChange = vi.fn();
      const group = makeGroup([
        { id: "c1", kind: "callsign", pattern: "^BAW" },
      ]);
      render(<QueryBuilderBody {...bodyProps(group, onChange)} />);
      fireEvent.click(screen.getByTitle("Remove filter"));
      const updated: FilterGroup = onChange.mock.calls[0][0] as FilterGroup;
      expect(updated.items).toHaveLength(0);
    });

    it("removes only the targeted predicate when multiple exist", () => {
      const onChange = vi.fn();
      const group = makeGroup([
        { id: "c1", kind: "callsign", pattern: "^BAW" },
        { id: "c2", kind: "callsign", pattern: "^DLH" },
      ]);
      render(<QueryBuilderBody {...bodyProps(group, onChange)} />);
      fireEvent.click(screen.getAllByTitle("Remove filter")[0]);
      const updated: FilterGroup = onChange.mock.calls[0][0] as FilterGroup;
      expect(updated.items).toHaveLength(1);
      const remaining = updated.items[0];
      expect(remaining.kind === "callsign" && remaining.pattern).toBe("^DLH");
    });
  });

  // ---- ShapeToggle via PointRadiusCard -------------------------------------

  describe("ShapeToggle", () => {
    const basePred = {
      id: "p1",
      kind: "endpoint_within" as const,
      mode: "start" as const,
      shape: "none" as const,
      lat: null,
      lng: null,
      radiusNm: 25,
      polygon: null,
      airspaceName: null,
      airspaceLabel: null,
      startTimeFrom: "",
      startTimeTo: "",
      endTimeFrom: "",
      endTimeTo: "",
    };

    it("calls onGroupChange with shape=circle when Circle is clicked", () => {
      const onChange = vi.fn();
      const group = makeGroup([basePred]);
      render(<QueryBuilderBody {...bodyProps(group, onChange)} />);
      fireEvent.click(screen.getByText("Circle"));
      const updated: FilterGroup = onChange.mock.calls[0][0] as FilterGroup;
      const pred = updated.items[0];
      expect(pred.kind === "endpoint_within" && pred.shape).toBe("circle");
    });

    it("calls onGroupChange with shape=viewport when Viewport is clicked", () => {
      const onChange = vi.fn();
      const group = makeGroup([basePred]);
      render(<QueryBuilderBody {...bodyProps(group, onChange)} />);
      fireEvent.click(screen.getByText("View"));
      const updated: FilterGroup = onChange.mock.calls[0][0] as FilterGroup;
      const pred = updated.items[0];
      expect(pred.kind === "endpoint_within" && pred.shape).toBe("viewport");
    });
  });
});

// ---- QueryBuilderAddMenu: remaining predicate types -------------------------

describe("QueryBuilderAddMenu additional filter types", () => {
  it("appends an endpoint_within predicate when Endpoint is clicked", () => {
    const onChange = vi.fn();
    render(
      <QueryBuilderAddMenu rootGroup={emptyGroup()} onGroupChange={onChange} />,
    );
    fireEvent.click(screen.getByRole("button", { name: /add filter/i }));
    fireEvent.click(screen.getByText("Endpoint"));
    const updated: FilterGroup = onChange.mock.calls[0][0] as FilterGroup;
    expect(updated.items[0]).toMatchObject({
      kind: "endpoint_within",
      mode: "either",
      shape: "circle",
      lat: null,
      lng: null,
    });
  });

  it("appends a region predicate when Ever is clicked", () => {
    const onChange = vi.fn();
    render(
      <QueryBuilderAddMenu rootGroup={emptyGroup()} onGroupChange={onChange} />,
    );
    fireEvent.click(screen.getByRole("button", { name: /add filter/i }));
    fireEvent.click(screen.getByText("Ever"));
    const updated: FilterGroup = onChange.mock.calls[0][0] as FilterGroup;
    expect(updated.items[0]).toMatchObject({
      kind: "region",
      shape: "polygon",
      regionName: "Region 1",
    });
  });

  it("appends an always_within predicate when Always is clicked", () => {
    const onChange = vi.fn();
    render(
      <QueryBuilderAddMenu rootGroup={emptyGroup()} onGroupChange={onChange} />,
    );
    fireEvent.click(screen.getByRole("button", { name: /add filter/i }));
    fireEvent.click(screen.getByText("Always"));
    const updated: FilterGroup = onChange.mock.calls[0][0] as FilterGroup;
    expect(updated.items[0]).toMatchObject({
      kind: "always_within",
      shape: "polygon",
    });
  });

  it("appends a group_all predicate when All of is clicked", () => {
    const onChange = vi.fn();
    render(
      <QueryBuilderAddMenu rootGroup={emptyGroup()} onGroupChange={onChange} />,
    );
    fireEvent.click(screen.getByRole("button", { name: /add filter/i }));
    fireEvent.click(screen.getByText("All of"));
    const updated: FilterGroup = onChange.mock.calls[0][0] as FilterGroup;
    expect(updated.items[0]).toMatchObject({
      kind: "group",
      mode: "all",
      items: [],
    });
  });

  it("appends a group_any predicate when Any of is clicked", () => {
    const onChange = vi.fn();
    render(
      <QueryBuilderAddMenu rootGroup={emptyGroup()} onGroupChange={onChange} />,
    );
    fireEvent.click(screen.getByRole("button", { name: /add filter/i }));
    fireEvent.click(screen.getByText("Any of"));
    const updated: FilterGroup = onChange.mock.calls[0][0] as FilterGroup;
    expect(updated.items[0]).toMatchObject({
      kind: "group",
      mode: "any",
      items: [],
    });
  });

  it("numbers region predicates using existing region count", () => {
    const onChange = vi.fn();
    const root = makeGroup([
      {
        id: makeId(),
        kind: "region",
        regionName: "Region 1",
        shape: "circle" as const,
        lat: 51,
        lng: 0,
        radiusNm: 10,
        polygon: null,
        airspaceName: null,
        airspaceLabel: null,
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
      },
    ]);
    render(<QueryBuilderAddMenu rootGroup={root} onGroupChange={onChange} />);
    fireEvent.click(screen.getByRole("button", { name: /add filter/i }));
    fireEvent.click(screen.getByText("Ever"));
    const updated: FilterGroup = onChange.mock.calls[0][0] as FilterGroup;
    const newPred = updated.items[1];
    expect(newPred).toMatchObject({ kind: "region", regionName: "Region 2" });
  });
});

// ---- GroupBlock (nested group) -----------------------------------------------

describe("GroupBlock (nested group in QueryBuilderBody)", () => {
  function nestedGroupProps(
    innerItems: FilterGroup["items"] = [],
    mode: "all" | "any" = "all",
  ) {
    const inner: FilterGroup = {
      id: makeId(),
      kind: "group",
      mode,
      items: innerItems,
    };
    const root = makeGroup([inner]);
    return { root, inner };
  }

  it("renders 'Empty group' placeholder for an empty child group", () => {
    const { root } = nestedGroupProps();
    render(<QueryBuilderBody {...bodyProps(root)} />);
    expect(screen.getByText("Empty group")).toBeInTheDocument();
  });

  it("shows ALL and ANY mode toggle buttons in a child group header", () => {
    const { root } = nestedGroupProps();
    render(<QueryBuilderBody {...bodyProps(root)} />);
    expect(screen.getByRole("button", { name: "ALL" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "ANY" })).toBeInTheDocument();
  });

  it("calls onGroupChange with mode=any when ANY is clicked", () => {
    const onChange = vi.fn();
    const { root } = nestedGroupProps([], "all");
    render(<QueryBuilderBody {...bodyProps(root, onChange)} />);
    fireEvent.click(screen.getByRole("button", { name: "ANY" }));
    const updated: FilterGroup = onChange.mock.calls[0][0] as FilterGroup;
    const inner = updated.items[0] as FilterGroup;
    expect(inner.mode).toBe("any");
  });

  it("calls onGroupChange with mode=all when ALL is clicked from any mode", () => {
    const onChange = vi.fn();
    const { root } = nestedGroupProps([], "any");
    render(<QueryBuilderBody {...bodyProps(root, onChange)} />);
    fireEvent.click(screen.getByRole("button", { name: "ALL" }));
    const updated: FilterGroup = onChange.mock.calls[0][0] as FilterGroup;
    const inner = updated.items[0] as FilterGroup;
    expect(inner.mode).toBe("all");
  });

  it("calls onGroupChange removing the child group when X is clicked", () => {
    const onChange = vi.fn();
    const { root } = nestedGroupProps();
    render(<QueryBuilderBody {...bodyProps(root, onChange)} />);
    fireEvent.click(screen.getByTitle("Remove group"));
    const updated: FilterGroup = onChange.mock.calls[0][0] as FilterGroup;
    expect(updated.items).toHaveLength(0);
  });

  it("shows 'All filters must match' label for all-mode nested group", () => {
    const { root } = nestedGroupProps([], "all");
    render(<QueryBuilderBody {...bodyProps(root)} />);
    expect(screen.getByText("All filters must match")).toBeInTheDocument();
  });

  it("shows 'Any filter must match' label for any-mode nested group", () => {
    const { root } = nestedGroupProps([], "any");
    render(<QueryBuilderBody {...bodyProps(root)} />);
    expect(screen.getByText("Any filter must match")).toBeInTheDocument();
  });

  it("renders a callsign predicate inside a nested group", () => {
    const innerItems: FilterGroup["items"] = [
      { id: makeId(), kind: "callsign", pattern: "BAW" },
    ];
    const { root } = nestedGroupProps(innerItems);
    render(<QueryBuilderBody {...bodyProps(root)} />);
    expect(screen.getByDisplayValue("BAW")).toBeInTheDocument();
  });
});
