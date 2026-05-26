import { describe, it, expect } from "vitest";
import {
  altToColor,
  aglToColor,
  squawkToColor,
  catToColor,
  vsToColor,
  gsToColor,
  iasToColor,
  GRAY,
} from "../src/lib/colors";

describe("altToColor", () => {
  it("returns the first stop color at 0 ft", () => {
    expect(altToColor(0)).toEqual([220, 50, 50, 220]);
  });

  it("returns the last stop color at 40000 ft", () => {
    expect(altToColor(40000)).toEqual([155, 50, 230, 220]);
  });

  it("clamps negative altitudes to 0 ft", () => {
    expect(altToColor(-1000)).toEqual(altToColor(0));
  });

  it("clamps values above 40000 ft to the max stop", () => {
    expect(altToColor(50000)).toEqual(altToColor(40000));
  });

  it("returns a valid RGBA tuple for mid-altitude", () => {
    const color = altToColor(10000);
    expect(color).toHaveLength(4);
    expect(color[3]).toBe(220);
  });

  it("returns distinct colors at 1000 ft, 3000 ft, 20000 ft, and 30000 ft", () => {
    const c1k = altToColor(1000);
    const c3k = altToColor(3000);
    const c20k = altToColor(20000);
    const c30k = altToColor(30000);
    expect(c1k).not.toEqual(c3k);
    expect(c20k).not.toEqual(c30k);
  });

  it("returns a value between the first and last stops for intermediate altitudes", () => {
    const low = altToColor(0);
    const mid = altToColor(20000);
    const high = altToColor(40000);
    expect(mid).not.toEqual(low);
    expect(mid).not.toEqual(high);
  });
});

describe("aglToColor", () => {
  it("returns the same color as altToColor at the same height", () => {
    expect(aglToColor(0)).toEqual(altToColor(0));
    expect(aglToColor(10000)).toEqual(altToColor(10000));
    expect(aglToColor(40000)).toEqual(altToColor(40000));
  });

  it("returns gray for null", () => {
    expect(aglToColor(null)).toEqual(GRAY);
  });

  it("returns gray for undefined", () => {
    expect(aglToColor(undefined)).toEqual(GRAY);
  });

  it("clamps negative values to 0 ft", () => {
    expect(aglToColor(-100)).toEqual(aglToColor(0));
  });

  it("clamps values above AGL_MAX to the max stop", () => {
    expect(aglToColor(50000)).toEqual(aglToColor(40000));
  });

  it("returns distinct colors for low AGL values", () => {
    expect(aglToColor(100)).not.toEqual(aglToColor(1000));
    expect(aglToColor(1000)).not.toEqual(aglToColor(5000));
  });
});

describe("squawkToColor", () => {
  it("returns magenta for 7500 (hijack)", () => {
    expect(squawkToColor("7500")).toEqual([255, 40, 200, 220]);
  });

  it("returns red for 7700 (emergency)", () => {
    expect(squawkToColor("7700")).toEqual([220, 40, 40, 220]);
  });

  it("returns amber for 7600 (radio failure)", () => {
    expect(squawkToColor("7600")).toEqual([240, 150, 0, 220]);
  });

  it("returns cyan for 7000 (VFR EU)", () => {
    expect(squawkToColor("7000")).toEqual([0, 210, 220, 220]);
  });

  it("returns cyan for 1200 (VFR NA)", () => {
    expect(squawkToColor("1200")).toEqual([0, 210, 220, 220]);
  });

  it("returns green for 2000 (IFR)", () => {
    expect(squawkToColor("2000")).toEqual([60, 200, 100, 220]);
  });

  it("returns default gray for an unknown discrete code", () => {
    expect(squawkToColor("1234")).toEqual([160, 160, 160, 220]);
  });

  it("returns default gray for null", () => {
    expect(squawkToColor(null)).toEqual([160, 160, 160, 220]);
  });

  it("returns default gray for undefined", () => {
    expect(squawkToColor(undefined)).toEqual([160, 160, 160, 220]);
  });

  it("returns default gray for empty string", () => {
    expect(squawkToColor("")).toEqual([160, 160, 160, 220]);
  });
});

describe("catToColor", () => {
  it("returns light blue for A1 (light aircraft)", () => {
    expect(catToColor("A1")).toEqual([120, 180, 255, 220]);
  });

  it("returns red for A5 (heavy)", () => {
    expect(catToColor("A5")).toEqual([220, 60, 60, 220]);
  });

  it("returns magenta for B6 (UAV)", () => {
    expect(catToColor("B6")).toEqual([220, 75, 175, 220]);
  });

  it("returns brown for C1 (surface vehicle)", () => {
    expect(catToColor("C1")).toEqual([185, 115, 50, 220]);
  });

  it("returns default gray for reserved code A0", () => {
    expect(catToColor("A0")).toEqual([160, 160, 160, 220]);
  });

  it("returns default gray for unknown code", () => {
    expect(catToColor("Z9")).toEqual([160, 160, 160, 220]);
  });

  it("returns default gray for null", () => {
    expect(catToColor(null)).toEqual([160, 160, 160, 220]);
  });

  it("returns default gray for undefined", () => {
    expect(catToColor(undefined)).toEqual([160, 160, 160, 220]);
  });
});

describe("vsToColor", () => {
  it("returns GRAY for null", () => {
    expect(vsToColor(null)).toEqual(GRAY);
  });

  it("returns GRAY for undefined", () => {
    expect(vsToColor(undefined)).toEqual(GRAY);
  });

  it("returns neutral gray at 0 fpm (level)", () => {
    expect(vsToColor(0)).toEqual([170, 170, 170, 220]);
  });

  it("returns deep blue at +3000 fpm (max climb)", () => {
    expect(vsToColor(3000)).toEqual([50, 90, 220, 220]);
  });

  it("returns deep red at -3000 fpm (max descent)", () => {
    expect(vsToColor(-3000)).toEqual([220, 50, 50, 220]);
  });

  it("clamps values above +3000 fpm", () => {
    expect(vsToColor(5000)).toEqual(vsToColor(3000));
  });

  it("clamps values below -3000 fpm", () => {
    expect(vsToColor(-5000)).toEqual(vsToColor(-3000));
  });

  it("returns a warm color for descending flight", () => {
    const color = vsToColor(-1000);
    // Should lean red/orange — R channel dominates
    expect(color[0]).toBeGreaterThan(color[2]);
  });

  it("returns a cool color for climbing flight", () => {
    const color = vsToColor(1000);
    // Should lean blue — B channel dominates
    expect(color[2]).toBeGreaterThan(color[0]);
  });
});

describe("gsToColor", () => {
  it("returns GRAY for null", () => {
    expect(gsToColor(null)).toEqual(GRAY);
  });

  it("returns GRAY for undefined", () => {
    expect(gsToColor(undefined)).toEqual(GRAY);
  });

  it("returns dark navy at 0 kt", () => {
    expect(gsToColor(0)).toEqual([50, 50, 80, 220]);
  });

  it("returns red at 600 kt (max)", () => {
    expect(gsToColor(600)).toEqual([220, 50, 50, 220]);
  });

  it("clamps negative speeds to 0", () => {
    expect(gsToColor(-10)).toEqual(gsToColor(0));
  });

  it("clamps speeds above 600 kt", () => {
    expect(gsToColor(800)).toEqual(gsToColor(600));
  });

  it("returns a valid RGBA tuple for typical GA cruise speed", () => {
    const color = gsToColor(120);
    expect(color).toHaveLength(4);
    expect(color[3]).toBe(220);
  });
});

describe("iasToColor", () => {
  it("returns GRAY for null", () => {
    expect(iasToColor(null)).toEqual(GRAY);
  });

  it("returns GRAY for undefined", () => {
    expect(iasToColor(undefined)).toEqual(GRAY);
  });

  it("returns dark navy at 0 kt", () => {
    expect(iasToColor(0)).toEqual([50, 50, 80, 220]);
  });

  it("returns red at 450 kt (max IAS)", () => {
    expect(iasToColor(450)).toEqual([220, 50, 50, 220]);
  });

  it("clamps speeds above 450 kt", () => {
    expect(iasToColor(600)).toEqual(iasToColor(450));
  });

  it("clamps negative speeds to 0", () => {
    expect(iasToColor(-5)).toEqual(iasToColor(0));
  });
});
