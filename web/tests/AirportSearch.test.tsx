import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import * as api from "../src/lib/api";
import { AirportSearch } from "../src/components/map/AirportSearch";

vi.mock("../src/lib/api", () => ({
  searchAirports: vi.fn(),
}));

const mockSearchAirports = vi.mocked(api.searchAirports);

const EGLL: api.Airport = {
  ident: "EGLL",
  type: "large_airport",
  name: "London Heathrow Airport",
  lon: -0.461389,
  lat: 51.4775,
  elevation_ft: 83,
  iso_country: "GB",
  iso_region: "GB-ENG",
  municipality: "London",
  scheduled_service: true,
  icao_code: "EGLL",
  iata_code: "LHR",
};

const KSFO: api.Airport = {
  ident: "KSFO",
  type: "large_airport",
  name: "San Francisco International Airport",
  lon: -122.375,
  lat: 37.619,
  elevation_ft: 13,
  iso_country: "US",
  iso_region: "US-CA",
  municipality: "San Francisco",
  scheduled_service: true,
  icao_code: "KSFO",
  iata_code: "SFO",
};

beforeEach(() => {
  vi.clearAllMocks();
});

describe("AirportSearch", () => {
  it("renders a search button when closed", () => {
    render(<AirportSearch onSelect={() => undefined} />);
    expect(
      screen.getByRole("button", { name: "Search airports" }),
    ).toBeInTheDocument();
  });

  it("opens the input when the search button is clicked", () => {
    render(<AirportSearch onSelect={() => undefined} />);
    fireEvent.click(screen.getByTitle("Search airports"));
    expect(screen.getByPlaceholderText("EGLL, Heathrow…")).toBeInTheDocument();
  });

  it("shows results after typing", async () => {
    mockSearchAirports.mockResolvedValue([EGLL, KSFO]);
    render(<AirportSearch onSelect={() => undefined} />);
    fireEvent.click(screen.getByTitle("Search airports"));

    fireEvent.change(screen.getByPlaceholderText("EGLL, Heathrow…"), {
      target: { value: "heat" },
    });

    await waitFor(() => {
      expect(screen.getByText("EGLL")).toBeInTheDocument();
      expect(screen.getByText("London Heathrow Airport")).toBeInTheDocument();
      expect(screen.getByText("KSFO")).toBeInTheDocument();
    });
  });

  it("calls onSelect with airport coords when a result is clicked", async () => {
    mockSearchAirports.mockResolvedValue([EGLL]);
    const onSelect = vi.fn();
    render(<AirportSearch onSelect={onSelect} />);
    fireEvent.click(screen.getByTitle("Search airports"));
    fireEvent.change(screen.getByPlaceholderText("EGLL, Heathrow…"), {
      target: { value: "heathrow" },
    });

    await waitFor(() => screen.getByText("EGLL"));
    fireEvent.click(screen.getByText("London Heathrow Airport"));

    expect(onSelect).toHaveBeenCalledWith(51.4775, -0.461389, "EGLL");
  });

  it("closes and clears after selection", async () => {
    mockSearchAirports.mockResolvedValue([EGLL]);
    render(<AirportSearch onSelect={() => undefined} />);
    fireEvent.click(screen.getByTitle("Search airports"));
    fireEvent.change(screen.getByPlaceholderText("EGLL, Heathrow…"), {
      target: { value: "egll" },
    });

    await waitFor(() => screen.getByText("EGLL"));
    fireEvent.click(screen.getByText("London Heathrow Airport"));

    expect(
      screen.queryByPlaceholderText("EGLL, Heathrow…"),
    ).not.toBeInTheDocument();
    expect(screen.getByTitle("Search airports")).toBeInTheDocument();
  });

  it("closes on Escape key", () => {
    render(<AirportSearch onSelect={() => undefined} />);
    fireEvent.click(screen.getByTitle("Search airports"));
    const input = screen.getByPlaceholderText("EGLL, Heathrow…");
    fireEvent.keyDown(input, { key: "Escape" });
    expect(input).not.toBeInTheDocument();
  });

  it("clears the query with the × button", () => {
    render(<AirportSearch onSelect={() => undefined} />);
    fireEvent.click(screen.getByTitle("Search airports"));
    const input = screen.getByPlaceholderText("EGLL, Heathrow…");
    fireEvent.change(input, { target: { value: "EGLL" } });
    expect(input).toHaveValue("EGLL");
    fireEvent.click(screen.getByText("×"));
    expect(input).toHaveValue("");
  });

  it("does not call onSelect for empty results on Enter", () => {
    const onSelect = vi.fn();
    render(<AirportSearch onSelect={onSelect} />);
    fireEvent.click(screen.getByTitle("Search airports"));
    fireEvent.keyDown(screen.getByPlaceholderText("EGLL, Heathrow…"), {
      key: "Enter",
    });
    expect(onSelect).not.toHaveBeenCalled();
  });
});
