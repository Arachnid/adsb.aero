// Results sidebar: pager + flight cards

function fmtTime(unix) {
  const d = new Date(unix * 1000);
  return d.toLocaleString('en-GB', {
    month: 'short', day: '2-digit',
    hour: '2-digit', minute: '2-digit',
    hour12: false
  });
}

function fmtDur(sec) {
  const h = Math.floor(sec / 3600);
  const m = Math.floor((sec % 3600) / 60);
  return h > 0 ? `${h}h ${m.toString().padStart(2,'0')}m` : `${m}m`;
}

function FlightCard({ flight, selected, onClick, onDoubleClick, color }) {
  return (
    <div
      className={"flight-card" + (selected ? " selected" : "")}
      onClick={onClick}
      onDoubleClick={onDoubleClick}
    >
      <div className="fc-row">
        <span className="fc-callsign">{flight.callsign}</span>
        <span className="fc-type">{flight.icaoType}</span>
      </div>
      <div className="fc-times">
        {fmtTime(flight.tStart)} → {fmtTime(flight.tEnd)} <span style={{color: "var(--fg-3)"}}>· {fmtDur(flight.tEnd - flight.tStart)}</span>
      </div>
      <div className="fc-route">
        <span>{flight.origin.airport.icao}</span>
        <span className="dist">({flight.origin.distance.toFixed(1)} km)</span>
        <span className="arrow">→</span>
        <span>{flight.destination.airport.icao}</span>
        <span className="dist">({flight.destination.distance.toFixed(1)} km)</span>
      </div>
      <Sparkline points={flight.points} color={color} />
    </div>
  );
}

function Pager({ page, totalPages, onPrev, onNext }) {
  return (
    <div className="pager">
      <div className="pager-info">{totalPages > 0 ? `Page ${page+1} / ${totalPages}` : 'No results'}</div>
      <div style={{ display: 'flex', gap: 4 }}>
        <button onClick={onPrev} disabled={page === 0}><Icon.ChevronLeft /></button>
        <button onClick={onNext} disabled={page >= totalPages - 1}><Icon.ChevronRight /></button>
      </div>
    </div>
  );
}

window.Results = { FlightCard, Pager };
