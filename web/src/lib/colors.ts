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
  [240, 160,  77, 220], // ~3k ft — orange
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

// Emitter category palette (ADS-B category codes).
const CAT_COLORS: Partial<Record<string, RGBA>> = {
  A1: [120, 180, 255, 220], // light aircraft
  A2: [60, 130, 240, 220], // small
  A3: [30, 80, 200, 220], // large
  A4: [140, 60, 220, 220], // high vortex large
  A5: [220, 60, 60, 220], // heavy
  A6: [240, 160, 20, 220], // high performance
  A7: [50, 180, 80, 220], // rotorcraft
};
const CAT_DEFAULT: RGBA = [160, 160, 160, 220];

export function catToColor(cat: string | null | undefined): RGBA {
  return (cat !== null && cat !== undefined && CAT_COLORS[cat]) || CAT_DEFAULT;
}

// Time-of-day: hue rotates through the day.
// 00:00 → blue, 06:00 → red/orange, 12:00 → yellow, 18:00 → purple.
function hslToRgb(hDeg: number, s: number, l: number): [number, number, number] {
  const h = ((hDeg % 360) + 360) % 360;
  const a = s * Math.min(l, 1 - l);
  const f = (n: number): number => {
    const k = (n + h / 30) % 12;
    return l - a * Math.max(Math.min(k - 3, 9 - k, 1), -1);
  };
  return [Math.round(f(0) * 255), Math.round(f(8) * 255), Math.round(f(4) * 255)];
}

export function todToColor(startTs: string): RGBA {
  const d = new Date(startTs);
  const hour = d.getUTCHours() + d.getUTCMinutes() / 60;
  const hue = ((hour / 24) * 360 + 240) % 360;
  const [r, g, b] = hslToRgb(hue, 0.85, 0.55);
  return [r, g, b, 220];
}
