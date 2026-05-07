// Flight detail popup: anchored to map, full metadata + altitude/speed chart

function fmtTimeFull(unix) {
  const d = new Date(unix * 1000);
  return d.toLocaleString('en-GB', { hour12: false });
}

function AltSpeedChart({ points, width = 290, height = 72 }) {
  if (!points || points.length < 2) return null;
  const maxAlt = Math.max(...points.map(p => p.alt));
  const maxSpd = Math.max(...points.map(p => p.spd));
  const altPath = points.map((p, i) => {
    const x = (i / (points.length - 1)) * width;
    const y = height - (p.alt / (maxAlt || 1)) * (height - 4) - 2;
    return (i === 0 ? "M" : "L") + x.toFixed(1) + "," + y.toFixed(1);
  }).join(" ");
  const spdPath = points.map((p, i) => {
    const x = (i / (points.length - 1)) * width;
    const y = height - (p.spd / (maxSpd || 1)) * (height - 4) - 2;
    return (i === 0 ? "M" : "L") + x.toFixed(1) + "," + y.toFixed(1);
  }).join(" ");

  return (
    <svg className="dp-chart" viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="none">
      <defs>
        <linearGradient id="alt-grad" x1="0" x2="0" y1="0" y2="1">
          <stop offset="0%" stopColor="#6ea8ff" stopOpacity="0.4"/>
          <stop offset="100%" stopColor="#6ea8ff" stopOpacity="0"/>
        </linearGradient>
      </defs>
      {/* gridlines */}
      {[0.25, 0.5, 0.75].map(t => (
        <line key={t} x1="0" x2={width} y1={height*t} y2={height*t} stroke="var(--line-1)" strokeWidth="0.5" strokeDasharray="2 3"/>
      ))}
      <path d={altPath + ` L ${width},${height} L 0,${height} Z`} fill="url(#alt-grad)" />
      <path d={altPath} fill="none" stroke="#6ea8ff" strokeWidth="1.4" />
      <path d={spdPath} fill="none" stroke="#f0a04d" strokeWidth="1.2" strokeDasharray="3 2" opacity="0.85" />
      <text x="6" y="11" fontSize="9" fill="#6ea8ff" fontFamily="JetBrains Mono">ALT {Math.round(maxAlt).toLocaleString()} ft</text>
      <text x={width - 6} y="11" fontSize="9" fill="#f0a04d" fontFamily="JetBrains Mono" textAnchor="end">SPD {Math.round(maxSpd)} kt</text>
    </svg>
  );
}

function FlightDetailPopup({ flight, screenPos, onClose, onIsolate }) {
  if (!flight) return null;
  const dur = flight.tEnd - flight.tStart;
  const distKm = window.MOCK_DATA.distance(flight.points[0], flight.points[flight.points.length - 1]);
  return (
    <div className="detail-popup" style={{ left: screenPos.x, top: screenPos.y }}>
      <div className="dp-head">
        <div className="dp-title">
          <span className="cs">{flight.callsign}</span>
          <span className="sub">{flight.icaoType} · {flight.emitter}</span>
        </div>
        <button className="pred-x" onClick={onClose}><Icon.X size={14} /></button>
      </div>
      <div className="dp-body">
        <AltSpeedChart points={flight.points} />
        <div className="dp-grid">
          <div className="dp-item">
            <div className="lbl">Origin</div>
            <div className="val">{flight.origin.airport.icao} ({flight.origin.distance.toFixed(1)} km)</div>
          </div>
          <div className="dp-item">
            <div className="lbl">Destination</div>
            <div className="val">{flight.destination.airport.icao} ({flight.destination.distance.toFixed(1)} km)</div>
          </div>
          <div className="dp-item">
            <div className="lbl">Start</div>
            <div className="val">{fmtTimeFull(flight.tStart)}</div>
          </div>
          <div className="dp-item">
            <div className="lbl">End</div>
            <div className="val">{fmtTimeFull(flight.tEnd)}</div>
          </div>
          <div className="dp-item">
            <div className="lbl">Duration</div>
            <div className="val">{Math.floor(dur/3600)}h {Math.floor((dur%3600)/60)}m</div>
          </div>
          <div className="dp-item">
            <div className="lbl">Distance</div>
            <div className="val">{distKm.toFixed(0)} km</div>
          </div>
          <div className="dp-item">
            <div className="lbl">Max altitude</div>
            <div className="val">{flight.maxAlt.toLocaleString()} ft</div>
          </div>
          <div className="dp-item">
            <div className="lbl">Samples</div>
            <div className="val">{flight.points.length}</div>
          </div>
        </div>
        <div className="dp-actions">
          <button className="primary" onClick={onIsolate}>Show only this flight</button>
        </div>
      </div>
    </div>
  );
}

window.FlightDetail = { FlightDetailPopup };
