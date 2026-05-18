import { describe, it, expect } from "vitest";
import {
  stepValueAt,
  projectOntoSegment,
  trackToCompass,
  squawkAt,
} from "../src/components/map/MapView";

vi.mock("maplibre-gl");

describe("stepValueAt", () => {
  it("returns null for null series", () => {
    expect(stepValueAt(null, 1000)).toBeNull();
  });

  it("returns null for undefined series", () => {
    expect(stepValueAt(undefined, 1000)).toBeNull();
  });

  it("returns null for empty series", () => {
    expect(stepValueAt([], 1000)).toBeNull();
  });

  it("returns null when timestamp is before all entries", () => {
    expect(
      stepValueAt(
        [
          [1000, 100],
          [2000, 200],
        ],
        500,
      ),
    ).toBeNull();
  });

  it("returns the last value at or before the timestamp", () => {
    const series = [
      [1000, 100],
      [2000, 200],
      [3000, 300],
    ];
    expect(stepValueAt(series, 1000)).toBe(100);
    expect(stepValueAt(series, 1500)).toBe(100);
    expect(stepValueAt(series, 2000)).toBe(200);
    expect(stepValueAt(series, 2999)).toBe(200);
    expect(stepValueAt(series, 3000)).toBe(300);
  });

  it("returns the last value when timestamp is after all entries", () => {
    const series = [
      [1000, 42],
      [2000, 99],
    ];
    expect(stepValueAt(series, 9999)).toBe(99);
  });

  it("stops early when it finds an entry past the timestamp (break path)", () => {
    const series = [
      [1000, 10],
      [2000, 20],
      [3000, 30],
    ];
    expect(stepValueAt(series, 1500)).toBe(10);
  });
});

describe("projectOntoSegment", () => {
  it("returns 0 for a zero-length segment", () => {
    expect(projectOntoSegment([0, 0], [0, 0], [1, 1])).toBe(0);
  });

  it("returns 0 when cursor projects before segment start", () => {
    expect(projectOntoSegment([1, 0], [2, 0], [0, 0])).toBe(0);
  });

  it("returns 1 when cursor projects past segment end", () => {
    expect(projectOntoSegment([0, 0], [1, 0], [2, 0])).toBe(1);
  });

  it("returns 0.5 for cursor at midpoint of a horizontal segment", () => {
    expect(projectOntoSegment([0, 0], [2, 0], [1, 5])).toBeCloseTo(0.5);
  });

  it("returns the exact projection parameter for a diagonal segment", () => {
    // Segment from (0,0) to (4,4), cursor at (2,2) → t = 0.5
    expect(projectOntoSegment([0, 0], [4, 4], [2, 2])).toBeCloseTo(0.5);
  });

  it("returns t in [0, 1] for any cursor position", () => {
    const t = projectOntoSegment([0, 0], [1, 1], [5, -3]);
    expect(t).toBeGreaterThanOrEqual(0);
    expect(t).toBeLessThanOrEqual(1);
  });
});

describe("trackToCompass", () => {
  it("returns N for 0°", () => {
    expect(trackToCompass(0)).toBe("N");
  });

  it("returns N for 360°", () => {
    expect(trackToCompass(360)).toBe("N");
  });

  it("returns E for 90°", () => {
    expect(trackToCompass(90)).toBe("E");
  });

  it("returns S for 180°", () => {
    expect(trackToCompass(180)).toBe("S");
  });

  it("returns W for 270°", () => {
    expect(trackToCompass(270)).toBe("W");
  });

  it("returns NE for 45°", () => {
    expect(trackToCompass(45)).toBe("NE");
  });

  it("returns NNE for 22.5°", () => {
    expect(trackToCompass(22.5)).toBe("NNE");
  });

  it("returns SW for 225°", () => {
    expect(trackToCompass(225)).toBe("SW");
  });
});

describe("squawkAt", () => {
  it("returns null for empty runs", () => {
    expect(squawkAt([], 1000)).toBeNull();
  });

  it("returns null when timestamp is before all runs", () => {
    expect(squawkAt([[2000, "7700"]], 1000)).toBeNull();
  });

  it("returns the code when timestamp exactly matches a run start", () => {
    expect(squawkAt([[1000, "1200"]], 1000)).toBe("1200");
  });

  it("returns the last code at or before the timestamp", () => {
    const runs: [number, string][] = [
      [1000, "1200"],
      [2000, "7700"],
      [3000, "0000"],
    ];
    expect(squawkAt(runs, 1500)).toBe("1200");
    expect(squawkAt(runs, 2000)).toBe("7700");
    expect(squawkAt(runs, 9999)).toBe("0000");
  });

  it("stops searching after finding a future run (break path)", () => {
    const runs: [number, string][] = [
      [1000, "1200"],
      [3000, "7700"],
    ];
    expect(squawkAt(runs, 2000)).toBe("1200");
  });
});
