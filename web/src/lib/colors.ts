// Color utilities for flight path visualization.
// All functions return [R, G, B, A] tuples with components in 0-255.

export type RGBA = [number, number, number, number];

function lerp(a: number, b: number, t: number): number {
  return a + (b - a) * t;
}

function lerpColor(a: RGBA, b: RGBA, t: number): RGBA {
  return [
    Math.round(lerp(a[0], b[0], t)),
    Math.round(lerp(a[1], b[1], t)),
    Math.round(lerp(a[2], b[2], t)),
    Math.round(lerp(a[3], b[3], t)),
  ];
}

// Altitude gradient: red (ground) → orange → yellow → green → blue → purple (high cruise).
// Matches the legend. Evenly spaced in curved space (see altToColor).
const ALT_MAX = 40000;
const ALT_CURVE = 0.4; // exponent < 1 stretches low-altitude distinctions
const ALT_STOPS: RGBA[] = [
  [226, 100, 100, 220], // 0 ft   — red
  [240, 160, 77, 220], // ~3k ft — orange
  [240, 224, 102, 220], // ~9k ft — yellow
  [110, 211, 163, 220], // ~19k ft — green
  [110, 168, 255, 220], // ~32k ft — blue
  [155, 110, 240, 220], // 40k+ ft — purple
];

export function altToColor(altFt: number): RGBA {
  const clamped = Math.max(0, Math.min(altFt, ALT_MAX));
  // Apply power curve so low-altitude differences are visually exaggerated.
  const t = Math.pow(clamped / ALT_MAX, ALT_CURVE) * (ALT_STOPS.length - 1);
  const lo = Math.floor(t);
  const hi = Math.min(lo + 1, ALT_STOPS.length - 1);
  const frac = t - lo;
  const a = ALT_STOPS[lo];
  const b = ALT_STOPS[hi];
  if (!a || !b) return ALT_STOPS[ALT_STOPS.length - 1] ?? [155, 110, 240, 220];
  return lerpColor(a, b, frac);
}

// Squawk palette — emergency codes use warm/saturated colours; conspicuity
// codes use cool colours; ATC-assigned discrete codes fall back to gray.
const SQUAWK_COLORS: Record<string, RGBA> = {
  "7500": [255, 40, 200, 220], // hijack — magenta
  "7700": [220, 40, 40, 220], // emergency — red
  "7600": [240, 150, 0, 220], // radio failure — amber
  "7000": [0, 210, 220, 220], // VFR conspicuity EU — cyan
  "1200": [0, 210, 220, 220], // VFR conspicuity NA — same cyan
  "2000": [60, 200, 100, 220], // IFR conspicuity — soft green
};
const SQUAWK_DEFAULT: RGBA = [160, 160, 160, 220];

export function squawkToColor(code: string | null | undefined): RGBA {
  if (!code) return SQUAWK_DEFAULT;
  return SQUAWK_COLORS[code] ?? SQUAWK_DEFAULT;
}

// Emitter category palette (ADS-B category codes).
// x0 / reserved codes (A0, B0, B5, C0, C6, C7) fall through to CAT_DEFAULT.
const CAT_COLORS: Partial<Record<string, RGBA>> = {
  // A-series: powered airborne (blues → purples → warm)
  A1: [120, 180, 255, 220], // light
  A2: [60, 130, 240, 220], // small
  A3: [30, 80, 200, 220], // large
  A4: [140, 60, 220, 220], // high vortex (757-type)
  A5: [220, 60, 60, 220], // heavy
  A6: [240, 160, 20, 220], // high performance
  A7: [50, 180, 80, 220], // rotorcraft
  // B-series: special airborne
  B1: [60, 200, 190, 220], // glider / sailplane
  B2: [220, 185, 50, 220], // lighter-than-air
  B3: [180, 120, 240, 220], // parachutist
  B4: [130, 215, 150, 220], // ultralight / hang-glider
  B6: [220, 75, 175, 220], // UAV
  B7: [190, 195, 210, 220], // space / trans-atmospheric
  // C-series: surface vehicles / obstructions (all same colour)
  C1: [185, 115, 50, 220], // emergency vehicle
  C2: [185, 115, 50, 220], // service vehicle
  C3: [185, 115, 50, 220], // fixed ground obstruction
};
const CAT_DEFAULT: RGBA = [160, 160, 160, 220];

export function catToColor(cat: string | null | undefined): RGBA {
  return (cat !== null && cat !== undefined && CAT_COLORS[cat]) || CAT_DEFAULT;
}

export const GRAY: RGBA = [150, 150, 150, 180];

// Interpolate through an evenly-spaced stop array at t ∈ [0, 1].
function piecewiseLerp(stops: RGBA[], t: number): RGBA {
  const n = stops.length;
  const idx = Math.max(0, Math.min(t, 1)) * (n - 1);
  const lo = Math.min(Math.floor(idx), n - 2);
  const c0 = stops[lo];
  const c1 = stops[lo + 1];
  if (!c0 || !c1) return GRAY;
  return lerpColor(c0, c1, idx - lo);
}

// Vertical speed: diverging red (descending) → gray (level) → blue (climbing).
// Stops are evenly spaced in sqrt-curved space; physical breakpoints ≈ ±3000,
// ±1300, ±300, 0 fpm. This keeps ±500 fpm visually distinct from level.
const VS_STOPS: RGBA[] = [
  [220, 50, 50, 220], // ≈ −3000 fpm — deep red
  [245, 110, 60, 220], // ≈ −1300 fpm — orange-red
  [200, 175, 165, 220], // ≈ −  300 fpm — warm gray
  [170, 170, 170, 220], //      0 fpm — neutral gray
  [165, 175, 205, 220], // ≈ +  300 fpm — cool gray
  [90, 140, 240, 220], // ≈ +1300 fpm — medium blue
  [50, 90, 220, 220], // ≈ +3000 fpm — deep blue
];

export function vsToColor(vsFpm: number | null | undefined): RGBA {
  if (vsFpm == null) return GRAY;
  const clamped = Math.max(-3000, Math.min(vsFpm, 3000));
  // Signed sqrt: maps ±500 fpm to ±41% of full scale (vs ±17% linearly).
  const sign = clamped >= 0 ? 1 : -1;
  const curved = sign * Math.sqrt(Math.abs(clamped) / 3000); // [-1, 1]
  return piecewiseLerp(VS_STOPS, (curved + 1) / 2);
}

// Ground speed and IAS: dark navy → blue → green → yellow → red.
// Stops evenly spaced in sqrt-curved space; physical breakpoints for GS ≈
// 0, 24, 96, 216, 384, 600 kt — GA cruise (120–200 kt) lands in the
// blue-green range, clearly distinct from jet cruise (450+ kt, yellow-red).
const SPEED_STOPS: RGBA[] = [
  [50, 50, 80, 220], //   0 kt — dark navy
  [60, 90, 160, 220], // ≈  25 kt — navy blue
  [80, 165, 230, 220], // ≈  95 kt — light blue
  [80, 205, 130, 220], // ≈ 215 kt — green
  [230, 200, 70, 220], // ≈ 385 kt — yellow
  [220, 50, 50, 220], // max kt — red
];

export function gsToColor(gsKt: number | null | undefined): RGBA {
  if (gsKt == null) return GRAY;
  return piecewiseLerp(
    SPEED_STOPS,
    Math.sqrt(Math.max(0, Math.min(gsKt, 600)) / 600),
  );
}

export function iasToColor(iasKt: number | null | undefined): RGBA {
  if (iasKt == null) return GRAY;
  return piecewiseLerp(
    SPEED_STOPS,
    Math.sqrt(Math.max(0, Math.min(iasKt, 450)) / 450),
  );
}
