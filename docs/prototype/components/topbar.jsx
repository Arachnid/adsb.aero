// Topbar: brand, basemap toggle, airspace overlay, theme toggle

function Topbar({ basemap, onBasemap, airspaceOn, onToggleAirspace, colorMode, onColorMode, theme, onTheme }) {
  return (
    <div className="topbar">
      <div className="brand">
        <span className="dot"></span>
        adsb.aero
        <span className="pill">HISTORICAL</span>
      </div>
      <div className="sep"></div>
      <span className="seg-label">Basemap</span>
      <div className="seg">
        <button className={basemap === "dark" ? "active" : ""} onClick={() => onBasemap("dark")} title="Dark"><Icon.Moon /></button>
        <button className={basemap === "light" ? "active" : ""} onClick={() => onBasemap("light")} title="Light"><Icon.Sun /></button>
        <button className={basemap === "sat" ? "active" : ""} onClick={() => onBasemap("sat")} title="Satellite"><Icon.Sat /></button>
      </div>
      <div className="sep"></div>
      <span className="seg-label">Color by</span>
      <div className="seg">
        <button className={colorMode === "alt" ? "active" : ""} onClick={() => onColorMode("alt")}>Altitude</button>
        <button className={colorMode === "cat" ? "active" : ""} onClick={() => onColorMode("cat")}>Category</button>
        <button className={colorMode === "tod" ? "active" : ""} onClick={() => onColorMode("tod")}>Time</button>
      </div>
      <div className="sep"></div>
      <button
        className={"icon-btn" + (airspaceOn ? " active" : "")}
        onClick={onToggleAirspace}
        title="Toggle airspace overlay"
      >
        <Icon.Layers />
      </button>
      <button className="icon-btn" onClick={onTheme} title="Toggle theme">
        {theme === "dark" ? <Icon.Sun /> : <Icon.Moon />}
      </button>
    </div>
  );
}

window.Topbar = Topbar;
