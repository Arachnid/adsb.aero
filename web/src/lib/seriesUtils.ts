// Step-interpolate (forward-fill) a [[ts, value], ...] series at a given timestamp.
export function stepValueAt(
  series: number[][] | null | undefined,
  ts: number,
): number | null {
  if (!series || series.length === 0) return null;
  let val: number | null = null;
  for (const entry of series) {
    const entryTs = entry[0];
    const entryVal = entry[1];
    if (entryTs === undefined || entryVal === undefined) continue;
    if (entryTs <= ts) val = entryVal;
    else break;
  }
  return val;
}

// Linearly interpolate a [[ts, value], ...] series at a given timestamp.
// Before the first entry returns null; after the last entry returns the last value.
export function linearValueAt(
  series: number[][] | null | undefined,
  ts: number,
): number | null {
  if (!series || series.length === 0) return null;
  let lo: number[] | null = null;
  let hi: number[] | null = null;
  for (const entry of series) {
    if (entry[0] === undefined || entry[1] === undefined) continue;
    if (entry[0] <= ts) lo = entry;
    else {
      hi = entry;
      break;
    }
  }
  if (lo === null) return null;
  if (hi === null) return lo[1] ?? null;
  const loTs = lo[0] ?? 0;
  const hiTs = hi[0] ?? 0;
  const loVal = lo[1] ?? 0;
  const hiVal = hi[1] ?? 0;
  const t = hiTs > loTs ? (ts - loTs) / (hiTs - loTs) : 0;
  return loVal + t * (hiVal - loVal);
}
