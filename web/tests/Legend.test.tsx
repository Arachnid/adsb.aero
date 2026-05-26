import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { Legend } from "../src/components/ui/Legend";

describe("Legend", () => {
  it("shows 'Altitude (ft)' title and gradient labels in alt mode", () => {
    render(<Legend colorMode="alt" />);
    expect(screen.getByText("Altitude (ft)")).toBeInTheDocument();
    expect(screen.getByText("0")).toBeInTheDocument();
    expect(screen.getByText("~11k")).toBeInTheDocument();
    expect(screen.getByText("40k+")).toBeInTheDocument();
  });

  it("shows 'Category' title and aircraft category rows in cat mode", () => {
    render(<Legend colorMode="cat" />);
    expect(screen.getByText("Category")).toBeInTheDocument();
    expect(screen.getByText("A1 Light")).toBeInTheDocument();
    expect(screen.getByText("A5 Heavy")).toBeInTheDocument();
    expect(screen.getByText("A7 Rotorcraft")).toBeInTheDocument();
    expect(screen.getByText("B6 UAV")).toBeInTheDocument();
    expect(screen.getByText(/C\s+Surface/)).toBeInTheDocument();
    expect(screen.getByText("Other")).toBeInTheDocument();
  });

  it("shows 'Squawk' title and squawk code rows in sqk mode", () => {
    render(<Legend colorMode="sqk" />);
    expect(screen.getByText("Squawk")).toBeInTheDocument();
    expect(screen.getByText("7500 Hijack")).toBeInTheDocument();
    expect(screen.getByText("7700 Emergency")).toBeInTheDocument();
    expect(screen.getByText("7600 Radio fail")).toBeInTheDocument();
    expect(screen.getByText("7000 / 1200 VFR")).toBeInTheDocument();
    expect(screen.getByText("2000 IFR")).toBeInTheDocument();
    expect(screen.getByText("Discrete / none")).toBeInTheDocument();
  });

  it("shows 'Vert. speed (fpm)' title and diverging gradient in vs mode", () => {
    render(<Legend colorMode="vs" />);
    expect(screen.getByText("Vert. speed (fpm)")).toBeInTheDocument();
    // GradientLabels left/center/right
    expect(screen.getByText("−1000")).toBeInTheDocument();
    expect(screen.getByText("0")).toBeInTheDocument();
    expect(screen.getByText("+1000")).toBeInTheDocument();
    expect(screen.getByText("No data")).toBeInTheDocument();
  });

  it("shows 'Ground speed (kt)' title and gradient in gs mode", () => {
    render(<Legend colorMode="gs" />);
    expect(screen.getByText("Ground speed (kt)")).toBeInTheDocument();
    expect(screen.getByText("~215")).toBeInTheDocument();
    expect(screen.getByText("600")).toBeInTheDocument();
    expect(screen.getByText("No data")).toBeInTheDocument();
  });

  it("shows 'Indicated AS (kt)' title and gradient in ias mode", () => {
    render(<Legend colorMode="ias" />);
    expect(screen.getByText("Indicated AS (kt)")).toBeInTheDocument();
    expect(screen.getByText("~160")).toBeInTheDocument();
    expect(screen.getByText("450")).toBeInTheDocument();
    expect(screen.getByText("No data")).toBeInTheDocument();
  });

  it("does not render cat rows when not in cat mode", () => {
    render(<Legend colorMode="alt" />);
    expect(screen.queryByText("A1 Light")).not.toBeInTheDocument();
  });

  it("does not render squawk rows when not in sqk mode", () => {
    render(<Legend colorMode="gs" />);
    expect(screen.queryByText("7700 Emergency")).not.toBeInTheDocument();
  });
});
