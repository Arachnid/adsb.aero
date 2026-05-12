type ColorMode = "alt" | "cat" | "tod";

interface LegendProps {
  colorMode: ColorMode;
}

export function Legend({ colorMode }: LegendProps): React.ReactElement {
  return (
    <div
      style={{
        position: "absolute",
        bottom: 12,
        right: 364,
        zIndex: 9,
        background: "color-mix(in oklab, var(--bg-1) 92%, transparent)",
        backdropFilter: "blur(12px)",
        WebkitBackdropFilter: "blur(12px)",
        border: "1px solid var(--line-1)",
        borderRadius: "var(--radius-3)",
        boxShadow: "var(--shadow-2)",
        padding: "10px 12px",
        fontSize: 10.5,
        color: "var(--fg-1)",
        minWidth: 130,
      }}
    >
      <LegendTitle>
        {colorMode === "alt" ? "Altitude (ft)" : colorMode === "cat" ? "Category" : "Time of day"}
      </LegendTitle>

      {colorMode === "alt" && (
        <>
          <div
            style={{
              height: 8,
              borderRadius: 2,
              // Stop positions reflect the power-curve mapping (ALT_CURVE=0.4):
              // each colour stop's actual altitude as % of 40 000 ft.
              background:
                "linear-gradient(to right," +
                " #e26464 0%," +
                " #f0a04d 1.8%," +
                " #f0e066 10.1%," +
                " #6ed3a3 27.9%," +
                " #6ea8ff 57.2%," +
                " #9b6ef0 100%)",
              marginBottom: 4,
            }}
          />
          <div
            style={{
              display: "flex",
              justifyContent: "space-between",
              fontFamily: "'JetBrains Mono', monospace",
              fontSize: 9.5,
              color: "var(--fg-3)",
            }}
          >
            <span>0</span>
            <span>20k</span>
            <span>40k+</span>
          </div>
        </>
      )}

      {colorMode === "cat" && (
        <>
          <LegendRow swatch="#6ed3a3">A1 Light</LegendRow>
          <LegendRow swatch="#4d8df0">A3 Large</LegendRow>
          <LegendRow swatch="#9b6ef0">A5 Heavy</LegendRow>
          <LegendRow swatch="#f0a04d">A7 Rotor</LegendRow>
        </>
      )}

      {colorMode === "tod" && (
        <>
          <LegendRow swatch="#6ea8ff">00–06</LegendRow>
          <LegendRow swatch="#f0e066">06–12</LegendRow>
          <LegendRow swatch="#f0a04d">12–18</LegendRow>
          <LegendRow swatch="#9b6ef0">18–24</LegendRow>
        </>
      )}
    </div>
  );
}

function LegendTitle({
  children,
  style,
}: {
  children: string;
  style?: React.CSSProperties;
}): React.ReactElement {
  return (
    <div
      style={{
        fontSize: 10,
        textTransform: "uppercase",
        letterSpacing: "0.06em",
        color: "var(--fg-3)",
        fontWeight: 500,
        marginBottom: 6,
        ...style,
      }}
    >
      {children}
    </div>
  );
}

function LegendRow({ swatch, children }: { swatch: string; children: string }): React.ReactElement {
  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        gap: 6,
        fontFamily: "'JetBrains Mono', monospace",
        fontSize: 10.5,
        color: "var(--fg-1)",
        marginTop: 3,
      }}
    >
      <span style={{ width: 10, height: 10, borderRadius: 2, background: swatch, flexShrink: 0 }} />
      {children}
    </div>
  );
}
