interface IconProps {
  size?: number;
  className?: string;
}

function icon(path: string, viewBox = "0 0 24 24") {
  return function SvgIcon({ size = 16, className }: IconProps) {
    return (
      <svg
        width={size}
        height={size}
        viewBox={viewBox}
        fill="none"
        stroke="currentColor"
        strokeWidth="1.75"
        strokeLinecap="round"
        strokeLinejoin="round"
        className={className}
        aria-hidden
      >
        <path d={path} />
      </svg>
    );
  };
}

export const ChevronLeft = icon("M15 18l-6-6 6-6");
export const ChevronRight = icon("M9 18l6-6-6-6");
export const Moon = icon("M21 12.79A9 9 0 1111.21 3 7 7 0 0021 12.79z");
export const Sun = icon(
  "M12 1v2M12 21v2M4.22 4.22l1.42 1.42M18.36 18.36l1.42 1.42M1 12h2M21 12h2M4.22 19.78l1.42-1.42M18.36 5.64l1.42-1.42",
);
export const Layers = icon(
  "M12 2L2 7l10 5 10-5-10-5zM2 17l10 5 10-5M2 12l10 5 10-5",
);
export const Plane = icon(
  "M21 16v-2l-8-5V3.5a1.5 1.5 0 00-3 0V9l-8 5v2l8-2.5V19l-2 1.5V22l3.5-1 3.5 1v-1.5L13 19v-5.5l8 2.5z",
);
export const Clock = icon(
  "M12 22c5.523 0 10-4.477 10-10S17.523 2 12 2 2 6.477 2 12s4.477 10 10 10zM12 6v6l4 2",
);
export const Pin = icon(
  "M21 10c0 7-9 13-9 13s-9-6-9-13a9 9 0 0118 0zM12 13a3 3 0 100-6 3 3 0 000 6z",
);
export const Polygon = icon("M3 3h4v4H3zM17 3h4v4h-4zM3 17h4v4H3zM17 17h4v4h-4zM5 5l14 0M5 19l14 0M5 5l0 14M19 5l0 14");
export const Plus = icon("M12 5v14M5 12h14");
export const Play = icon("M5 3l14 9-14 9V3z", "0 0 24 24");
export const Satellite = ({ size = 16, className }: IconProps) => (
  <svg
    width={size}
    height={size}
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    strokeWidth="1.75"
    strokeLinecap="round"
    strokeLinejoin="round"
    className={className}
    aria-hidden
  >
    <path d="M13 7L17 3M3 17l4-4M6.343 17.657l-3.536 3.536M17.657 6.343l-3.536-3.536" />
    <path d="M9 15l-4-4 8-8 4 4-8 8z" />
    <path d="M16 22l6-6" strokeDasharray="2 2" />
  </svg>
);
