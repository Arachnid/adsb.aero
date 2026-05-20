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
