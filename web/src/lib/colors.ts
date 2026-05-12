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

// Altitude gradient: blue (ground) → cyan → green → yellow → red (high cruise).
const ALT_STOPS: [number, RGBA][] = [
  [0, [30, 120, 255, 220]],
  [10000, [0, 200, 220, 220]],
  [20000, [40, 190, 40, 220]],
  [30000, [230, 190, 0, 220]],
  [40000, [220, 50, 30, 220]],
];

export function altToColor(altFt: number): RGBA {
  const last = ALT_STOPS.at(-1);
  const clamped = Math.max(0, Math.min(altFt, last?.[0] ?? 40000));
  for (let i = 0; i < ALT_STOPS.length - 1; i++) {
    const entry = ALT_STOPS[i];
    const next = ALT_STOPS[i + 1];
    if (!entry || !next) continue;
    const [lo, ca] = entry;
    const [hi, cb] = next;
    if (clamped <= hi) return lerpColor(ca, cb, (clamped - lo) / (hi - lo));
  }
  return last?.[1] ?? [220, 50, 30, 220];
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
