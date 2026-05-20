import { useEffect } from "react";
import { X } from "../Icons";

interface Props {
  open: boolean;
  onClose: () => void;
}

export function AboutDialog({
  open,
  onClose,
}: Props): React.ReactElement | null {
  useEffect(() => {
    if (!open) return;
    const handler = (e: KeyboardEvent): void => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", handler);
    return (): void => {
      document.removeEventListener("keydown", handler);
    };
  }, [open, onClose]);

  if (!open) return null;

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label="About adsb.aero"
      onClick={onClose}
      style={{
        position: "fixed",
        inset: 0,
        zIndex: 200,
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        background: "rgba(0,0,0,0.45)",
        backdropFilter: "blur(4px)",
        WebkitBackdropFilter: "blur(4px)",
      }}
    >
      <div
        onClick={(e) => {
          e.stopPropagation();
        }}
        style={{
          background: "var(--bg-1)",
          border: "1px solid var(--line-1)",
          borderRadius: "var(--radius-3)",
          boxShadow: "var(--shadow-3)",
          maxWidth: 500,
          width: "calc(100% - 48px)",
          maxHeight: "calc(100svh - 80px)",
          overflowY: "auto",
          padding: "28px 32px 32px",
          position: "relative",
        }}
      >
        {/* Close */}
        <button
          onClick={onClose}
          aria-label="Close"
          style={{
            position: "absolute",
            top: 16,
            right: 16,
            background: "var(--bg-2)",
            border: "1px solid var(--line-1)",
            borderRadius: 6,
            width: 28,
            height: 28,
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            cursor: "pointer",
            color: "var(--fg-2)",
          }}
        >
          <X size={14} />
        </button>

        {/* Header */}
        <div style={{ textAlign: "center", marginBottom: 20 }}>
          <img
            src="/logo.png"
            alt=""
            width={64}
            height={64}
            style={{
              borderRadius: "50%",
              objectFit: "cover",
              display: "inline-block",
              boxShadow: "0 2px 12px rgba(0,0,0,0.18)",
              marginBottom: 12,
            }}
          />
          <div
            style={{ fontWeight: 700, fontSize: 20, letterSpacing: "-0.02em" }}
          >
            adsb.aero
          </div>
          <div style={{ fontSize: 12, color: "var(--fg-3)", marginTop: 3 }}>
            Historical flight explorer
          </div>
        </div>

        <p
          style={{
            fontSize: 13,
            lineHeight: 1.65,
            color: "var(--fg-1)",
            margin: "0 0 16px",
          }}
        >
          A free, open-source tool for exploring historical flight trajectories
          from the <Ln href="https://adsb.lol">adsb.lol</Ln> community ADS-B
          archive — crowdsourced receiver data covering commercial and general
          aviation worldwide, updated daily.
        </p>

        <Section label="Features">
          <Feature title="Pressure-corrected altitude">
            Most ADS-B history sites display raw barometric altitude, which
            drifts with atmospheric pressure and can be hundreds of feet off.
            adsb.aero corrects every flight using NOAA GFS mean sea-level
            pressure data, so the altitude you see matches what the crew
            actually flew.
          </Feature>
          <Feature title="Flexible queries">
            Filter by date range, geographic region, airspace boundary,
            callsign, registration, ICAO24 address, or aircraft type. Chain
            conditions with AND / OR logic and draw custom polygons directly on
            the map.
          </Feature>
          <Feature title="Rich visualisation">
            Colour trajectories by altitude, vertical speed, ground speed,
            indicated airspeed, or squawk code. Click any flight for details.
          </Feature>
          <Feature title="Airspace overlay">
            Toggle OpenAIP airspace boundaries and use them as spatial filters
            in queries — pick an airspace by clicking on the map.
          </Feature>
        </Section>

        <Section label="Data sources">
          <Source
            name="adsb.lol"
            href="https://adsb.lol"
            desc="Open community ADS-B archive — the primary flight trajectory dataset"
          />
          <Source
            name="NOAA GFS"
            href="https://www.ncei.noaa.gov/products/weather-climate-models/global-forecast"
            desc="Global Forecast System mean sea-level pressure, fetched via Herbie, used to correct barometric altitude"
          />
          <Source
            name="OpenAIP"
            href="https://www.openaip.net"
            desc="Airspace boundaries, classifications, and the in-app airspace overlay"
          />
          <Source
            name="OpenFreeMap"
            href="https://openfreemap.org"
            desc="Light and dark basemap tiles"
          />
          <Source
            name="Esri World Imagery"
            href="https://www.esri.com"
            desc="Satellite basemap tiles"
          />
          <Source
            name="Mictronics / tar1090-db"
            href="https://github.com/Mictronics/tar1090-db"
            desc="Aircraft registration and type lookup table"
          />
        </Section>

        <Section label="Source code">
          <p style={{ margin: 0, fontSize: 12.5, color: "var(--fg-2)" }}>
            <Ln href="https://github.com/Arachnid/adsb.aero">
              github.com/Arachnid/adsb.aero
            </Ln>
            {" — "}open source under the MIT licence
          </p>
        </Section>
      </div>
    </div>
  );
}

function Section({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}): React.ReactElement {
  return (
    <div style={{ marginBottom: 20 }}>
      <div
        style={{
          fontSize: 10.5,
          fontWeight: 600,
          textTransform: "uppercase",
          letterSpacing: "0.07em",
          color: "var(--fg-3)",
          marginBottom: 10,
        }}
      >
        {label}
      </div>
      {children}
    </div>
  );
}

function Source({
  name,
  href,
  desc,
}: {
  name: string;
  href: string;
  desc: string;
}): React.ReactElement {
  return (
    <div
      style={{
        display: "flex",
        gap: 10,
        padding: "7px 0",
        borderTop: "1px solid var(--line-0)",
        alignItems: "baseline",
      }}
    >
      <a
        href={href}
        target="_blank"
        rel="noopener noreferrer"
        style={{
          fontSize: 12.5,
          fontWeight: 600,
          color: "var(--accent)",
          textDecoration: "none",
          flexShrink: 0,
          minWidth: 140,
        }}
      >
        {name}
      </a>
      <span style={{ fontSize: 12, color: "var(--fg-2)", lineHeight: 1.5 }}>
        {desc}
      </span>
    </div>
  );
}

function Feature({
  title,
  children,
}: {
  title: string;
  children: React.ReactNode;
}): React.ReactElement {
  return (
    <div
      style={{
        padding: "8px 0",
        borderTop: "1px solid var(--line-0)",
      }}
    >
      <div
        style={{
          fontSize: 12.5,
          fontWeight: 600,
          color: "var(--fg-1)",
          marginBottom: 3,
        }}
      >
        {title}
      </div>
      <div style={{ fontSize: 12, color: "var(--fg-2)", lineHeight: 1.6 }}>
        {children}
      </div>
    </div>
  );
}

function Ln({
  href,
  children,
}: {
  href: string;
  children: React.ReactNode;
}): React.ReactElement {
  return (
    <a
      href={href}
      target="_blank"
      rel="noopener noreferrer"
      style={{ color: "var(--accent)", textDecoration: "none" }}
    >
      {children}
    </a>
  );
}
