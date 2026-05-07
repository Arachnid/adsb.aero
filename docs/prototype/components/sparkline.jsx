// Simple altitude sparkline
function Sparkline({ points, width = 100, height = 24, color }) {
  if (!points || points.length < 2) return null;
  const max = Math.max(...points.map(p => p.alt));
  const min = 0;
  const range = max - min || 1;
  const stepX = width / (points.length - 1);

  const path = points.map((p, i) => {
    const x = i * stepX;
    const y = height - ((p.alt - min) / range) * (height - 2) - 1;
    return (i === 0 ? "M" : "L") + x.toFixed(1) + "," + y.toFixed(1);
  }).join(" ");

  // Filled area version
  const areaPath = path + ` L ${width.toFixed(1)},${height} L 0,${height} Z`;

  const stroke = color || "#6ea8ff";

  return (
    <svg className="fc-spark" viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="none">
      <defs>
        <linearGradient id={`spark-grad-${stroke.replace('#','')}`} x1="0" x2="0" y1="0" y2="1">
          <stop offset="0%" stopColor={stroke} stopOpacity="0.35" />
          <stop offset="100%" stopColor={stroke} stopOpacity="0" />
        </linearGradient>
      </defs>
      <path d={areaPath} fill={`url(#spark-grad-${stroke.replace('#','')})`} />
      <path d={path} fill="none" stroke={stroke} strokeWidth="1.25" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

window.Sparkline = Sparkline;

// Inline icons
const Icon = {
  Plus: ({ size = 14 }) => <svg width={size} height={size} viewBox="0 0 14 14" fill="none" stroke="currentColor" strokeWidth="1.5"><path d="M7 2v10M2 7h10" strokeLinecap="round"/></svg>,
  X: ({ size = 12 }) => <svg width={size} height={size} viewBox="0 0 12 12" fill="none" stroke="currentColor" strokeWidth="1.5"><path d="M3 3l6 6M9 3l-6 6" strokeLinecap="round"/></svg>,
  ChevronLeft: ({ size = 14 }) => <svg width={size} height={size} viewBox="0 0 14 14" fill="none" stroke="currentColor" strokeWidth="1.5"><path d="M9 3L5 7l4 4" strokeLinecap="round" strokeLinejoin="round"/></svg>,
  ChevronRight: ({ size = 14 }) => <svg width={size} height={size} viewBox="0 0 14 14" fill="none" stroke="currentColor" strokeWidth="1.5"><path d="M5 3l4 4-4 4" strokeLinecap="round" strokeLinejoin="round"/></svg>,
  Plane: ({ size = 14 }) => <svg width={size} height={size} viewBox="0 0 14 14" fill="none" stroke="currentColor" strokeWidth="1.3"><path d="M7 1.5L8 5.5l4.5 1.5-4.5 1.5L7 12.5 5.5 8.5 1 7l4.5-1.5z" strokeLinejoin="round"/></svg>,
  Clock: ({ size = 14 }) => <svg width={size} height={size} viewBox="0 0 14 14" fill="none" stroke="currentColor" strokeWidth="1.3"><circle cx="7" cy="7" r="5"/><path d="M7 4v3l2 1.5" strokeLinecap="round"/></svg>,
  Pin: ({ size = 14 }) => <svg width={size} height={size} viewBox="0 0 14 14" fill="none" stroke="currentColor" strokeWidth="1.3"><path d="M7 12.5C7 12.5 11 8.5 11 5.5a4 4 0 1 0-8 0c0 3 4 7 4 7z"/><circle cx="7" cy="5.5" r="1.4"/></svg>,
  Polygon: ({ size = 14 }) => <svg width={size} height={size} viewBox="0 0 14 14" fill="none" stroke="currentColor" strokeWidth="1.3"><path d="M3 4.5L7 1.5l5 3-1.5 6h-7L3 4.5z" strokeLinejoin="round"/><circle cx="3" cy="4.5" r="1" fill="currentColor"/><circle cx="7" cy="1.5" r="1" fill="currentColor"/><circle cx="12" cy="4.5" r="1" fill="currentColor"/><circle cx="10.5" cy="10.5" r="1" fill="currentColor"/><circle cx="3.5" cy="10.5" r="1" fill="currentColor"/></svg>,
  Text: ({ size = 14 }) => <svg width={size} height={size} viewBox="0 0 14 14" fill="none" stroke="currentColor" strokeWidth="1.3"><path d="M3 3h8M7 3v8M5 11h4" strokeLinecap="round"/></svg>,
  Run: ({ size = 14 }) => <svg width={size} height={size} viewBox="0 0 14 14" fill="none"><path d="M4 3l7 4-7 4V3z" fill="currentColor"/></svg>,
  Sun: ({ size = 14 }) => <svg width={size} height={size} viewBox="0 0 14 14" fill="none" stroke="currentColor" strokeWidth="1.3"><circle cx="7" cy="7" r="2.5"/><path d="M7 1v1.5M7 11.5V13M1 7h1.5M11.5 7H13M2.6 2.6l1 1M10.4 10.4l1 1M2.6 11.4l1-1M10.4 3.6l1-1" strokeLinecap="round"/></svg>,
  Moon: ({ size = 14 }) => <svg width={size} height={size} viewBox="0 0 14 14" fill="none" stroke="currentColor" strokeWidth="1.3"><path d="M11.5 8.5A4.5 4.5 0 1 1 5.5 2.5 4 4 0 0 0 11.5 8.5z" strokeLinejoin="round"/></svg>,
  Sat: ({ size = 14 }) => <svg width={size} height={size} viewBox="0 0 14 14" fill="none" stroke="currentColor" strokeWidth="1.3"><circle cx="7" cy="7" r="5.5"/><path d="M2 5c2 1 8 1 10 0M2 9c2-1 8-1 10 0M7 1.5c-2 1.5-2 9.5 0 11M7 1.5c2 1.5 2 9.5 0 11" /></svg>,
  Layers: ({ size = 14 }) => <svg width={size} height={size} viewBox="0 0 14 14" fill="none" stroke="currentColor" strokeWidth="1.3"><path d="M7 2L1.5 5 7 8l5.5-3L7 2z" strokeLinejoin="round"/><path d="M1.5 9L7 12l5.5-3" strokeLinejoin="round"/></svg>,
  Bars: ({ size = 14 }) => <svg width={size} height={size} viewBox="0 0 14 14" fill="none" stroke="currentColor" strokeWidth="1.3"><path d="M2 4h10M2 7h10M2 10h10" strokeLinecap="round"/></svg>,
};

window.Icon = Icon;
