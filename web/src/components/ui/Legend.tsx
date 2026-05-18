import type { ColorMode } from "../map/MapView";

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
        {colorMode === "alt"
          ? "Altitude (ft)"
          : colorMode === "cat"
            ? "Category"
            : colorMode === "sqk"
              ? "Squawk"
              : colorMode === "vs"
                ? "Vert. speed (fpm)"
                : colorMode === "gs"
                  ? "Ground speed (kt)"
                  : "Indicated AS (kt)"}
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
          <LegendRow swatch="#78b4ff">A1 Light</LegendRow>
          <LegendRow swatch="#3c82f0">A2 Small</LegendRow>
          <LegendRow swatch="#1e50c8">A3 Large</LegendRow>
          <LegendRow swatch="#8c3cdc">A4 Hi-vortex</LegendRow>
          <LegendRow swatch="#dc3c3c">A5 Heavy</LegendRow>
          <LegendRow swatch="#f0a014">A6 Hi-perf</LegendRow>
          <LegendRow swatch="#32b450">A7 Rotorcraft</LegendRow>
          <LegendRow swatch="#3cc8be">B1 Glider</LegendRow>
          <LegendRow swatch="#dcb932">B2 Airship</LegendRow>
          <LegendRow swatch="#b478f0">B3 Parachutist</LegendRow>
          <LegendRow swatch="#82d796">B4 Ultralight</LegendRow>
          <LegendRow swatch="#dc4baf">B6 UAV</LegendRow>
          <LegendRow swatch="#bec3d2">B7 Space</LegendRow>
          <LegendRow swatch="#b97332">C Surface</LegendRow>
          <LegendRow swatch="#a0a0a0">Other</LegendRow>
        </>
      )}

      {colorMode === "sqk" && (
        <>
          <LegendRow swatch="#ff28c8">7500 Hijack</LegendRow>
          <LegendRow swatch="#dc2828">7700 Emergency</LegendRow>
          <LegendRow swatch="#f09600">7600 Radio fail</LegendRow>
          <LegendRow swatch="#00d2dc">7000 / 1200 VFR</LegendRow>
          <LegendRow swatch="#3cc864">2000 IFR</LegendRow>
          <LegendRow swatch="#a0a0a0">Discrete / none</LegendRow>
        </>
      )}

      {colorMode === "vs" && (
        <>
          {/* 7 stops evenly spaced in sqrt space ≈ −3000, −1300, −300, 0, +300, +1300, +3000 fpm */}
          <GradientBar gradient="linear-gradient(to right, #dc3232 0%, #f56e3c 16.7%, #c8afa5 33.3%, #aaaaaa 50%, #a5afcd 66.7%, #5a8cf0 83.3%, #325adc 100%)" />
          <GradientLabels left="−3000" center="0" right="+3000" />
          <LegendRow swatch="#969696">No data</LegendRow>
        </>
      )}

      {colorMode === "gs" && (
        <>
          {/* 6 stops evenly spaced in sqrt space ≈ 0, 24, 96, 216, 384, 600 kt */}
          <GradientBar gradient="linear-gradient(to right, #323250 0%, #3c5aa0 20%, #50a5e6 40%, #50cd82 60%, #e6c846 80%, #dc3232 100%)" />
          <GradientLabels left="0" center="~215" right="600" />
          <LegendRow swatch="#969696">No data</LegendRow>
        </>
      )}

      {colorMode === "ias" && (
        <>
          {/* 6 stops evenly spaced in sqrt space ≈ 0, 18, 72, 162, 288, 450 kt */}
          <GradientBar gradient="linear-gradient(to right, #323250 0%, #3c5aa0 20%, #50a5e6 40%, #50cd82 60%, #e6c846 80%, #dc3232 100%)" />
          <GradientLabels left="0" center="~160" right="450" />
          <LegendRow swatch="#969696">No data</LegendRow>
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

function GradientBar({ gradient }: { gradient: string }): React.ReactElement {
  return <div style={{ height: 8, borderRadius: 2, background: gradient, marginBottom: 4 }} />;
}

function GradientLabels({
  left,
  center,
  right,
}: {
  left: string;
  center: string;
  right: string;
}): React.ReactElement {
  return (
    <div
      style={{
        display: "flex",
        justifyContent: "space-between",
        fontFamily: "'JetBrains Mono', monospace",
        fontSize: 9.5,
        color: "var(--fg-3)",
        marginBottom: 4,
      }}
    >
      <span>{left}</span>
      <span>{center}</span>
      <span>{right}</span>
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
