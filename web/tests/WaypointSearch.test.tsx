import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import * as api from "../src/lib/api";
import { WaypointSearch } from "../src/components/map/WaypointSearch";

vi.mock("../src/lib/api", () => ({
  searchWaypoints: vi.fn(),
}));

const mockSearch = vi.mocked(api.searchWaypoints);

const EGLL: api.Waypoint = {
  id: "wp-egll",
  kind: "airport",
  name: "LONDON HEATHROW",
  ident: "EGLL",
  iata_code: "LHR",
  type_code: 3,
  country: "GB",
  lon: -0.461389,
  lat: 51.4775,
  elevation_ft: 82,
  frequency_mhz: null,
  compulsory: null,
};

const BNN: api.Waypoint = {
  id: "wp-bnn",
  kind: "navaid",
  name: "BOVINGDON",
  ident: "BNN",
  iata_code: null,
  type_code: 3,
  country: "GB",
  lon: -0.549,
  lat: 51.726,
  elevation_ft: 531,
  frequency_mhz: 113.75,
  compulsory: null,
};

beforeEach(() => {
  vi.clearAllMocks();
});

describe("WaypointSearch", () => {
  it("renders a search button when closed", () => {
    render(<WaypointSearch onSelect={() => undefined} />);
    expect(
      screen.getByRole("button", { name: "Search waypoints" }),
    ).toBeInTheDocument();
  });

  it("opens the input when the search button is clicked", () => {
    render(<WaypointSearch onSelect={() => undefined} />);
    fireEvent.click(screen.getByTitle("Search waypoints"));
    expect(
      screen.getByPlaceholderText("EGLL, BNN, DIVIS…"),
    ).toBeInTheDocument();
  });

  it("shows airport and navaid results after typing", async () => {
    mockSearch.mockResolvedValue([EGLL, BNN]);
    render(<WaypointSearch onSelect={() => undefined} />);
    fireEvent.click(screen.getByTitle("Search waypoints"));
    fireEvent.change(screen.getByPlaceholderText("EGLL, BNN, DIVIS…"), {
      target: { value: "bo" },
    });
    await waitFor(() => {
      expect(screen.getByText("EGLL")).toBeInTheDocument();
      expect(screen.getByText("BOVINGDON")).toBeInTheDocument();
    });
  });

  it("calls onSelect with airport coords when a result is clicked", async () => {
    mockSearch.mockResolvedValue([EGLL]);
    const onSelect = vi.fn();
    render(<WaypointSearch onSelect={onSelect} />);
    fireEvent.click(screen.getByTitle("Search waypoints"));
    fireEvent.change(screen.getByPlaceholderText("EGLL, BNN, DIVIS…"), {
      target: { value: "heath" },
    });
    await waitFor(() => screen.getByText("LONDON HEATHROW"));
    fireEvent.click(screen.getByText("LONDON HEATHROW"));
    expect(onSelect).toHaveBeenCalledWith(51.4775, -0.461389, "EGLL");
  });

  it("closes and clears after selection", async () => {
    mockSearch.mockResolvedValue([EGLL]);
    render(<WaypointSearch onSelect={() => undefined} />);
    fireEvent.click(screen.getByTitle("Search waypoints"));
    fireEvent.change(screen.getByPlaceholderText("EGLL, BNN, DIVIS…"), {
      target: { value: "egll" },
    });
    await waitFor(() => screen.getByText("LONDON HEATHROW"));
    fireEvent.click(screen.getByText("LONDON HEATHROW"));
    expect(
      screen.queryByPlaceholderText("EGLL, BNN, DIVIS…"),
    ).not.toBeInTheDocument();
  });

  it("closes on Escape key", () => {
    render(<WaypointSearch onSelect={() => undefined} />);
    fireEvent.click(screen.getByTitle("Search waypoints"));
    const input = screen.getByPlaceholderText("EGLL, BNN, DIVIS…");
    fireEvent.keyDown(input, { key: "Escape" });
    expect(input).not.toBeInTheDocument();
  });

  it("clears query with the × button", () => {
    render(<WaypointSearch onSelect={() => undefined} />);
    fireEvent.click(screen.getByTitle("Search waypoints"));
    const input = screen.getByPlaceholderText("EGLL, BNN, DIVIS…");
    fireEvent.change(input, { target: { value: "EGLL" } });
    expect(input).toHaveValue("EGLL");
    fireEvent.click(screen.getByText("×"));
    expect(input).toHaveValue("");
  });

  it("uses ident as onSelect label for airports", async () => {
    mockSearch.mockResolvedValue([EGLL]);
    const onSelect = vi.fn();
    render(<WaypointSearch onSelect={onSelect} />);
    fireEvent.click(screen.getByTitle("Search waypoints"));
    fireEvent.change(screen.getByPlaceholderText("EGLL, BNN, DIVIS…"), {
      target: { value: "egll" },
    });
    await waitFor(() => screen.getByText("LONDON HEATHROW"));
    fireEvent.click(screen.getByText("LONDON HEATHROW"));
    expect(onSelect).toHaveBeenCalledWith(51.4775, -0.461389, "EGLL");
  });
});
