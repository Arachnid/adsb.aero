import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { App } from "../src/App";

vi.mock("maplibre-gl");

describe("App", () => {
  it("renders without crashing", () => {
    render(<App />);
    expect(screen.getByText(/adsb\.aero/i)).toBeDefined();
  });
});
