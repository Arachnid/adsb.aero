// Main app: orchestrates predicates, query execution, map and sidebars.

const { useState: aUseState, useEffect: aUseEffect, useMemo: aUseMemo, useCallback: aUseCallback } = React;

const PAGE_SIZE = 100;

function makeId() { return Math.random().toString(36).slice(2, 8); }

function App() {
  const [theme, setTheme] = aUseState("dark");
  const [basemap, setBasemap] = aUseState("dark");
  const [colorMode, setColorMode] = aUseState("alt");
  const [airspaceOn, setAirspaceOn] = aUseState(true);
  const [leftCollapsed, setLeftCollapsed] = aUseState(false);
  const [rightCollapsed, setRightCollapsed] = aUseState(false);

  const [predicates, setPredicates] = aUseState([
    { id: makeId(), kind: "time", from: "2026-05-01T00:00", to: "2026-05-08T00:00" }
  ]);
  const [matchMode, setMatchMode] = aUseState("AND");

  const [pickMode, setPickMode] = aUseState(null); // predicate id being edited
  const [drawMode, setDrawMode] = aUseState(null); // predicate id

  const [page, setPage] = aUseState(0);
  const [selectedId, setSelectedId] = aUseState(null);
  const [isolatedId, setIsolatedId] = aUseState(null);

  const [addMenuOpen, setAddMenuOpen] = aUseState(false);

  aUseEffect(() => { document.documentElement.dataset.theme = theme; }, [theme]);

  const allFlights = window.MOCK_DATA.flights;

  // Filtering logic
  const filtered = aUseMemo(() => {
    const tests = predicates.map(p => makeTest(p)).filter(Boolean);
    if (tests.length === 0) return allFlights;
    return allFlights.filter(f => {
      if (matchMode === "AND") return tests.every(t => t(f));
      return tests.some(t => t(f));
    });
  }, [predicates, matchMode, allFlights]);

  const totalPages = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE));
  const pageStart = page * PAGE_SIZE;
  const pageFlights = filtered.slice(pageStart, pageStart + PAGE_SIZE);

  aUseEffect(() => { if (page >= totalPages) setPage(0); }, [totalPages, page]);

  // Predicate add/remove/update
  const addPredicate = (kind) => {
    const base = { id: makeId(), kind };
    if (kind === "starts_within" || kind === "ends_within") {
      base.lat = 51.5; base.lng = -0.1; base.radiusKm = 25;
    } else if (kind === "region") {
      base.regionName = `Region ${predicates.filter(p=>p.kind==="region").length + 1}`;
    } else if (kind === "time") {
      base.from = "2026-05-01T00:00"; base.to = "2026-05-08T00:00";
    }
    setPredicates(p => [...p, base]);
    setAddMenuOpen(false);
  };
  const updatePredicate = (id, next) => {
    setPredicates(p => p.map(x => x.id === id ? { ...next, id } : x));
  };
  const removePredicate = (id) => {
    setPredicates(p => p.filter(x => x.id !== id));
    if (pickMode === id) setPickMode(null);
    if (drawMode === id) setDrawMode(null);
  };

  // Map: arm point picker
  const armPicker = (predId) => {
    setDrawMode(null);
    setPickMode(prev => prev === predId ? null : predId);
  };
  const onPicked = (predId, latlng) => {
    setPredicates(p => p.map(x => x.id === predId ? { ...x, lat: latlng.lat, lng: latlng.lng } : x));
    setPickMode(null);
  };

  // Map: arm region drawing
  const armDraw = (predId) => {
    setPickMode(null);
    setDrawMode(prev => prev === predId ? null : predId);
  };
  const onDrawn = (polygon) => {
    if (drawMode && polygon) {
      setPredicates(p => p.map(x => x.id === drawMode ? { ...x, polygon } : x));
    }
    setDrawMode(null);
  };

  // Esc key cancels draw / pick
  aUseEffect(() => {
    const onKey = (e) => {
      if (e.key === "Escape") { setPickMode(null); setDrawMode(null); }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  // Airspace click → add region predicate using its polygon
  aUseEffect(() => {
    const onAirspaceClick = (e) => {
      const a = window.AIRSPACE_DATA.find(x => x.id === e.detail.id);
      if (!a) return;
      const ring = [...a.coords]; // already closed
      const id = makeId();
      const regionCount = predicates.filter(p => p.kind === "region").length + 1;
      setPredicates(p => [...p, {
        id, kind: "region", regionName: `${a.name} (Region ${regionCount})`, polygon: ring
      }]);
    };
    window.addEventListener("airspace-click", onAirspaceClick);
    return () => window.removeEventListener("airspace-click", onAirspaceClick);
  }, [predicates]);

  // Adapt basemap to theme on toggle
  const handleTheme = () => {
    setTheme(t => {
      const next = t === "dark" ? "light" : "dark";
      // also flip basemap if in dark/light
      if (basemap === "dark" && next === "light") setBasemap("light");
      else if (basemap === "light" && next === "dark") setBasemap("dark");
      return next;
    });
  };

  const onIsolateOrEvent = (e) => {
    if (e?.type === "isolate") {
      setIsolatedId(prev => prev === e.id ? null : e.id);
    }
  };

  const pointPredicates = predicates.filter(p => p.kind === "starts_within" || p.kind === "ends_within");
  const regionPredicates = predicates.filter(p => p.kind === "region");

  return (
    <div className="app">
      <MapCanvas
        flights={pageFlights}
        selectedId={selectedId}
        onSelect={(id) => setSelectedId(id)}
        colorMode={colorMode}
        airspaceOn={airspaceOn}
        basemap={basemap}
        pickMode={pickMode}
        onPicked={onPicked}
        drawMode={drawMode}
        onDrawn={onDrawn}
        isolatedId={isolatedId}
        onAirspaceClick={onIsolateOrEvent}
        pointPredicates={pointPredicates}
        regionPredicates={regionPredicates}
      />

      <Topbar
        basemap={basemap} onBasemap={setBasemap}
        airspaceOn={airspaceOn} onToggleAirspace={() => setAirspaceOn(v => !v)}
        colorMode={colorMode} onColorMode={setColorMode}
        theme={theme} onTheme={handleTheme}
      />

      {/* Left sidebar: query builder */}
      <div className={"sidebar left" + (leftCollapsed ? " collapsed" : "")}>
        <div className="sb-header">
          <span className="sb-title">Query Builder</span>
          <span className="sb-meta">{predicates.length} filter{predicates.length !== 1 ? 's' : ''}</span>
        </div>
        <div className="sb-body">
          {predicates.length > 1 && (
            <div className="match-mode">
              <span>Match</span>
              <div className="match-mode-toggle">
                <button className={matchMode==="AND" ? "active" : ""} onClick={() => setMatchMode("AND")}>ALL (AND)</button>
                <button className={matchMode==="OR" ? "active" : ""} onClick={() => setMatchMode("OR")}>ANY (OR)</button>
              </div>
            </div>
          )}
          {predicates.map(p => (
            <PredicateRenderer
              key={p.id}
              pred={p}
              onChange={(next) => updatePredicate(p.id, next)}
              onRemove={() => removePredicate(p.id)}
              onArmPicker={() => armPicker(p.id)}
              isPicking={pickMode === p.id}
              onArmDraw={() => armDraw(p.id)}
              isDrawing={drawMode === p.id}
            />
          ))}
          <AddFilterButton open={addMenuOpen} onOpen={setAddMenuOpen} onAdd={addPredicate} />
        </div>
        <div className="sb-footer">
          <button className="run-btn" onClick={() => setPage(0)}>
            <Icon.Run /> Run query
            <span className="est">~{filtered.length} flights</span>
          </button>
        </div>
      </div>

      <button
        className={"sidebar-toggle left" + (!leftCollapsed ? " with-sidebar" : "")}
        onClick={() => setLeftCollapsed(v => !v)}
        title={leftCollapsed ? "Show query builder" : "Hide query builder"}
      >
        {leftCollapsed ? <Icon.ChevronRight /> : <Icon.ChevronLeft />}
      </button>

      {/* Right sidebar: results */}
      <div className={"sidebar right" + (rightCollapsed ? " collapsed" : "")}>
        <div className="sb-header">
          <span className="sb-title">Results</span>
          <span className="sb-meta">{filtered.length} match{filtered.length !== 1 ? 'es' : ''}</span>
        </div>
        {totalPages > 1 && (
          <Results.Pager
            page={page}
            totalPages={totalPages}
            onPrev={() => setPage(p => Math.max(0, p-1))}
            onNext={() => setPage(p => Math.min(totalPages-1, p+1))}
          />
        )}
        <div className="sb-body">
          {pageFlights.length === 0 ? (
            <div className="empty-state">
              <div className="icon"><Icon.Plane size={32}/></div>
              <div>No flights match the current filters.</div>
            </div>
          ) : pageFlights.map(f => (
            <Results.FlightCard
              key={f.id}
              flight={f}
              selected={selectedId === f.id}
              color={window.flightColorForCard(f, colorMode)}
              onClick={() => setSelectedId(f.id)}
              onDoubleClick={() => {
                setSelectedId(f.id);
                if (window.__map) {
                  const lats = f.points.map(p => p.lat), lngs = f.points.map(p => p.lng);
                  const bounds = [[Math.min(...lats), Math.min(...lngs)], [Math.max(...lats), Math.max(...lngs)]];
                  window.__map.flyToBounds(bounds, { padding: [80, 80], duration: 0.8 });
                }
              }}
            />
          ))}
        </div>
        {isolatedId && (
          <div className="sb-footer">
            <button className="btn-secondary armed" onClick={() => setIsolatedId(null)} style={{ width: "100%" }}>
              Clear isolation ({allFlights.find(f => f.id === isolatedId)?.callsign})
            </button>
          </div>
        )}
      </div>

      <button
        className={"sidebar-toggle right" + (!rightCollapsed ? " with-sidebar" : "")}
        onClick={() => setRightCollapsed(v => !v)}
        title={rightCollapsed ? "Show results" : "Hide results"}
      >
        {rightCollapsed ? <Icon.ChevronLeft /> : <Icon.ChevronRight />}
      </button>

      {/* Bottom-right legend */}
      <Legend mode={colorMode} airspaceOn={airspaceOn} />
    </div>
  );
}

function Legend({ mode, airspaceOn }) {
  return (
    <div className="legend">
      <div className="legend-title">{mode === "alt" ? "Altitude (ft)" : mode === "cat" ? "Category" : "Time of day"}</div>
      {mode === "alt" && (
        <>
          <div className="legend-gradient"></div>
          <div className="legend-scale">
            <span>0</span><span>20k</span><span>40k+</span>
          </div>
        </>
      )}
      {mode === "cat" && (
        <>
          <div className="legend-row"><span className="legend-swatch" style={{background:"#6ed3a3"}}></span>A1 Light</div>
          <div className="legend-row"><span className="legend-swatch" style={{background:"#4d8df0"}}></span>A3 Large</div>
          <div className="legend-row"><span className="legend-swatch" style={{background:"#9b6ef0"}}></span>A5 Heavy</div>
          <div className="legend-row"><span className="legend-swatch" style={{background:"#f0a04d"}}></span>A7 Rotor</div>
        </>
      )}
      {mode === "tod" && (
        <>
          <div className="legend-row"><span className="legend-swatch" style={{background:"#6ea8ff"}}></span>00–06</div>
          <div className="legend-row"><span className="legend-swatch" style={{background:"#f0e066"}}></span>06–12</div>
          <div className="legend-row"><span className="legend-swatch" style={{background:"#f0a04d"}}></span>12–18</div>
          <div className="legend-row"><span className="legend-swatch" style={{background:"#9b6ef0"}}></span>18–24</div>
        </>
      )}
      {airspaceOn && (
        <>
          <div className="legend-title" style={{marginTop: 8}}>Airspace</div>
          <div className="legend-row"><span className="legend-swatch" style={{background:"#6ea8ff"}}></span>CTR</div>
          <div className="legend-row"><span className="legend-swatch" style={{background:"#d066c8"}}></span>MATZ</div>
          <div className="legend-row"><span className="legend-swatch" style={{background:"#e26464"}}></span>Danger</div>
        </>
      )}
    </div>
  );
}

function AddFilterButton({ open, onOpen, onAdd }) {
  const ref = React.useRef(null);
  React.useEffect(() => {
    if (!open) return;
    const onDoc = (e) => { if (ref.current && !ref.current.contains(e.target)) onOpen(false); };
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, [open]);
  const opts = [
    { kind: "aircraft", icon: <Icon.Plane />, label: "Aircraft", desc: "Type, emitter category" },
    { kind: "time", icon: <Icon.Clock />, label: "Time range", desc: "From / to" },
    { kind: "starts_within", icon: <Icon.Pin />, label: "Starts within", desc: "Point + radius" },
    { kind: "ends_within", icon: <Icon.Pin />, label: "Ends within", desc: "Point + radius" },
    { kind: "region", icon: <Icon.Polygon />, label: "Trajectory through region", desc: "Draw polygon" },
    { kind: "callsign", icon: <Icon.Text />, label: "Callsign", desc: "Regex match" }
  ];
  return (
    <div ref={ref} style={{ position: "relative" }}>
      <button className="add-filter" onClick={() => onOpen(!open)}>
        <Icon.Plus /> Add filter
      </button>
      {open && (
        <div className="add-filter-menu">
          {opts.map(o => (
            <button key={o.kind} onClick={() => onAdd(o.kind)}>
              <span style={{ color: "var(--accent)" }}>{o.icon}</span>
              <span>
                <div>{o.label}</div>
                <div className="desc">{o.desc}</div>
              </span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

function PredicateRenderer({ pred, onChange, onRemove, onArmPicker, isPicking, onArmDraw, isDrawing }) {
  const P = window.Predicates;
  switch (pred.kind) {
    case "aircraft": return <P.AircraftPredicate pred={pred} onChange={onChange} onRemove={onRemove} />;
    case "time": return <P.TimePredicate pred={pred} onChange={onChange} onRemove={onRemove} />;
    case "starts_within": return <P.PointRadiusPredicate pred={pred} onChange={onChange} onRemove={onRemove} onArmPicker={onArmPicker} isPicking={isPicking} name="Starts within" kind="starts_within" />;
    case "ends_within": return <P.PointRadiusPredicate pred={pred} onChange={onChange} onRemove={onRemove} onArmPicker={onArmPicker} isPicking={isPicking} name="Ends within" kind="ends_within" />;
    case "region": return <P.RegionPredicate pred={pred} onChange={onChange} onRemove={onRemove} onArmDraw={onArmDraw} isDrawing={isDrawing} />;
    case "callsign": return <P.CallsignPredicate pred={pred} onChange={onChange} onRemove={onRemove} />;
    default: return null;
  }
}

// ===== Predicate test functions =====
function makeTest(p) {
  switch (p.kind) {
    case "aircraft":
      return (f) => {
        const types = p.icaoTypes || [];
        const cats = p.emitters || [];
        if (types.length === 0 && cats.length === 0) return true;
        const okType = types.length === 0 || types.includes(f.icaoType);
        const okCat = cats.length === 0 || cats.includes(f.emitter);
        return okType && okCat;
      };
    case "time":
      return (f) => {
        const from = p.from ? new Date(p.from).getTime()/1000 : -Infinity;
        const to = p.to ? new Date(p.to).getTime()/1000 : Infinity;
        return f.tStart < to && f.tEnd > from;
      };
    case "starts_within":
      return (f) => {
        if (p.lat == null) return true;
        return window.MOCK_DATA.distance(f.points[0], { lat: p.lat, lng: p.lng }) <= p.radiusKm;
      };
    case "ends_within":
      return (f) => {
        if (p.lat == null) return true;
        const last = f.points[f.points.length - 1];
        return window.MOCK_DATA.distance(last, { lat: p.lat, lng: p.lng }) <= p.radiusKm;
      };
    case "region":
      return (f) => {
        if (!p.polygon) return true;
        const poly = p.polygon;
        let dwellSec = 0;
        let lastT = null;
        for (const pt of f.points) {
          const inside = pointInPoly(pt.lng, pt.lat, poly);
          const altOk = (p.altMin == null || pt.alt >= p.altMin) && (p.altMax == null || pt.alt <= p.altMax);
          if (inside && altOk) {
            if (lastT != null) dwellSec += (pt.t - lastT);
            lastT = pt.t;
          } else {
            lastT = null;
          }
        }
        const minDwell = p.minDwell || 0;
        return dwellSec >= minDwell && (dwellSec > 0 || minDwell === 0 ? f.points.some(pt => pointInPoly(pt.lng, pt.lat, poly) && (p.altMin == null || pt.alt >= p.altMin) && (p.altMax == null || pt.alt <= p.altMax)) : false);
      };
    case "callsign":
      return (f) => {
        if (!p.pattern) return true;
        try { return new RegExp(p.pattern, 'i').test(f.callsign); }
        catch { return true; }
      };
    default: return null;
  }
}

function pointInPoly(x, y, ring) {
  let inside = false;
  for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
    const xi = ring[i][0], yi = ring[i][1];
    const xj = ring[j][0], yj = ring[j][1];
    const intersect = ((yi > y) !== (yj > y)) && (x < (xj - xi) * (y - yi) / (yj - yi + 1e-12) + xi);
    if (intersect) inside = !inside;
  }
  return inside;
}

ReactDOM.createRoot(document.getElementById("root")).render(<App />);
