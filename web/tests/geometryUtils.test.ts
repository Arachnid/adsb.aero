import { describe, it, expect } from "vitest";
import {
  circleAreaKm2,
  polygonAreaKm2,
  MAX_GEOMETRY_AREA_KM2,
} from "../src/lib/geometryUtils";

describe("circleAreaKm2", () => {
  it("computes area for a 1 nm radius circle", () => {
    const area = circleAreaKm2(1);
    // π × 1.852² ≈ 10.78 km²
    expect(area).toBeCloseTo(10.78, 1);
  });

  it("scales quadratically with radius", () => {
    expect(circleAreaKm2(10)).toBeCloseTo(circleAreaKm2(1) * 100, 0);
  });

  it("returns a value well under MAX for a small circle", () => {
    expect(circleAreaKm2(25)).toBeLessThan(MAX_GEOMETRY_AREA_KM2);
  });

  it("returns a value over MAX for a very large circle", () => {
    // radius 700 nm ≈ 1297 km → area ≈ 5.28M km²
    expect(circleAreaKm2(700)).toBeGreaterThan(MAX_GEOMETRY_AREA_KM2);
  });
});

describe("polygonAreaKm2", () => {
  it("returns 0 for fewer than 3 points", () => {
    expect(
      polygonAreaKm2([
        [0, 0],
        [1, 1],
      ]),
    ).toBe(0);
  });

  it("computes area of a 1°×1° square near the equator", () => {
    // Expected ≈ 111.32² ≈ 12392 km²
    const sq: [number, number][] = [
      [0, 0],
      [1, 0],
      [1, 1],
      [0, 1],
    ];
    expect(polygonAreaKm2(sq)).toBeCloseTo(12392, -2);
  });

  it("is independent of winding direction", () => {
    const cw: [number, number][] = [
      [0, 0],
      [0, 1],
      [1, 1],
      [1, 0],
    ];
    const ccw: [number, number][] = [
      [0, 0],
      [1, 0],
      [1, 1],
      [0, 1],
    ];
    expect(polygonAreaKm2(cw)).toBeCloseTo(polygonAreaKm2(ccw), 0);
  });

  it("returns a value well under MAX for a small region", () => {
    const small: [number, number][] = [
      [-2, 50],
      [2, 50],
      [2, 52],
      [-2, 52],
    ];
    expect(polygonAreaKm2(small)).toBeLessThan(MAX_GEOMETRY_AREA_KM2);
  });

  it("returns a value over MAX for a continent-sized region", () => {
    // Roughly the North Atlantic: 80° × 40° around 50°N
    const huge: [number, number][] = [
      [-60, 30],
      [20, 30],
      [20, 70],
      [-60, 70],
    ];
    expect(polygonAreaKm2(huge)).toBeGreaterThan(MAX_GEOMETRY_AREA_KM2);
  });
});
