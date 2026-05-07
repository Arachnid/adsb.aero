// Predicate cards: Aircraft, Time, Starts/Ends within, Trajectory through region, Callsign

const { useState, useRef, useEffect } = React;

function PredCard({ icon, name, onRemove, children }) {
  return (
    <div className="pred">
      <div className="pred-head">
        <span className="pred-icon">{icon}</span>
        <span className="pred-name">{name}</span>
        <button className="pred-x" onClick={onRemove} title="Remove filter"><Icon.X /></button>
      </div>
      <div className="pred-body">{children}</div>
    </div>
  );
}

function ChipMultiSelect({ label, value = [], options, onChange, placeholder = "Type to filter…", renderOpt }) {
  const [open, setOpen] = useState(false);
  const [filter, setFilter] = useState("");
  const ref = useRef(null);

  useEffect(() => {
    if (!open) return;
    const onDoc = (e) => { if (ref.current && !ref.current.contains(e.target)) setOpen(false); };
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, [open]);

  const filtered = options.filter(o => {
    const txt = (typeof o === "string" ? o : (o.code + " " + o.label)).toLowerCase();
    return txt.includes(filter.toLowerCase());
  });

  function toggle(opt) {
    const code = typeof opt === "string" ? opt : opt.code;
    if (value.includes(code)) onChange(value.filter(v => v !== code));
    else onChange([...value, code]);
  }

  return (
    <div>
      {label && <div className="field-label">{label}</div>}
      <div className="chip-group">
        {value.map(v => (
          <span key={v} className="chip">
            {v}
            <button onClick={() => onChange(value.filter(x => x !== v))} aria-label="Remove">×</button>
          </span>
        ))}
        <div style={{ position: "relative" }} ref={ref}>
          <button className="chip-add" onClick={() => setOpen(v => !v)}>
            {value.length === 0 ? "+ choose" : "+ add"}
          </button>
          {open && (
            <div className="chip-dropdown">
              <input
                autoFocus
                placeholder={placeholder}
                value={filter}
                onChange={e => setFilter(e.target.value)}
              />
              {filtered.slice(0, 50).map(opt => {
                const code = typeof opt === "string" ? opt : opt.code;
                const meta = typeof opt === "string" ? null : opt.label;
                const sel = value.includes(code);
                return (
                  <div key={code} className={"chip-opt" + (sel ? " selected" : "")} onClick={() => toggle(opt)}>
                    <span>{sel ? "✓ " : "  "}{code}</span>
                    {meta && <span className="chip-opt-meta">{meta}</span>}
                  </div>
                );
              })}
              {filtered.length === 0 && <div className="chip-opt" style={{ color: "var(--fg-3)" }}>No matches</div>}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function MiniMapPreview({ lat, lng, radiusKm }) {
  // Simple SVG mini-map: a centered dot + circle on a stylized grid
  const w = 100, h = 100;
  const r = Math.max(8, Math.min(45, radiusKm * 0.8));
  return (
    <div className="minimap">
      <svg viewBox={`0 0 ${w} ${h}`} width="100%" height="100%" preserveAspectRatio="none">
        <defs>
          <pattern id="mm-grid" width="10" height="10" patternUnits="userSpaceOnUse">
            <path d="M10 0H0V10" fill="none" stroke="var(--line-1)" strokeWidth="0.4"/>
          </pattern>
        </defs>
        <rect width={w} height={h} fill="var(--bg-1)" />
        <rect width={w} height={h} fill="url(#mm-grid)" />
        {/* fake landmass */}
        <path d="M 20 30 Q 30 22 45 28 Q 55 35 50 50 Q 60 60 55 75 Q 35 80 25 65 Q 15 50 20 30 Z"
              fill="var(--bg-3)" stroke="var(--line-2)" strokeWidth="0.6" opacity="0.7"/>
        <circle cx={w/2} cy={h/2} r={r} fill="var(--accent-soft)" stroke="var(--accent)" strokeWidth="1" strokeDasharray="2 2"/>
        <circle cx={w/2} cy={h/2} r="2" fill="var(--accent)" stroke="var(--bg-1)" strokeWidth="1"/>
      </svg>
    </div>
  );
}

function AircraftPredicate({ pred, onChange, onRemove }) {
  const types = window.MOCK_DATA.ICAO_TYPES;
  const cats = window.MOCK_DATA.EMITTER_CATEGORIES;
  return (
    <PredCard icon={<Icon.Plane />} name="Aircraft" onRemove={onRemove}>
      <ChipMultiSelect
        label="ICAO type"
        value={pred.icaoTypes || []}
        options={types}
        onChange={v => onChange({ ...pred, icaoTypes: v })}
      />
      <ChipMultiSelect
        label="Emitter category"
        value={pred.emitters || []}
        options={cats}
        onChange={v => onChange({ ...pred, emitters: v })}
      />
    </PredCard>
  );
}

function TimePredicate({ pred, onChange, onRemove }) {
  return (
    <PredCard icon={<Icon.Clock />} name="Time range" onRemove={onRemove}>
      <div>
        <div className="field-label">From</div>
        <input
          className="text-field mono"
          type="datetime-local"
          value={pred.from || ""}
          onChange={e => onChange({ ...pred, from: e.target.value })}
        />
      </div>
      <div>
        <div className="field-label">To</div>
        <input
          className="text-field mono"
          type="datetime-local"
          value={pred.to || ""}
          onChange={e => onChange({ ...pred, to: e.target.value })}
        />
      </div>
    </PredCard>
  );
}

function PointRadiusPredicate({ pred, onChange, onRemove, onArmPicker, isPicking, name, kind }) {
  return (
    <PredCard icon={<Icon.Pin />} name={name} onRemove={onRemove}>
      <MiniMapPreview lat={pred.lat || 54} lng={pred.lng || -2.5} radiusKm={pred.radiusKm || 25} />
      <div className="slider-row">
        <label>Radius</label>
        <input
          type="range"
          min="1" max="100" step="1"
          value={pred.radiusKm || 25}
          onChange={e => onChange({ ...pred, radiusKm: +e.target.value })}
        />
        <span className="val">{(pred.radiusKm || 25).toFixed(0)} km</span>
      </div>
      {pred.lat != null ? (
        <div style={{ fontFamily: "JetBrains Mono, monospace", fontSize: 10.5, color: "var(--fg-2)" }}>
          {pred.lat.toFixed(3)}°N, {Math.abs(pred.lng).toFixed(3)}°{pred.lng < 0 ? "W" : "E"}
        </div>
      ) : (
        <div style={{ fontFamily: "JetBrains Mono, monospace", fontSize: 10.5, color: "var(--fg-3)" }}>
          No point selected
        </div>
      )}
      <div className="minimap-buttons">
        <button
          className={"btn-secondary" + (isPicking ? " armed" : "")}
          onClick={() => onArmPicker(kind)}
        >
          {isPicking ? "Click on map…" : "Pick on map"}
        </button>
      </div>
    </PredCard>
  );
}

function RegionPredicate({ pred, onChange, onRemove, onArmDraw, isDrawing }) {
  return (
    <PredCard icon={<Icon.Polygon />} name="Trajectory through region" onRemove={onRemove}>
      {pred.polygon ? (
        <div style={{
          background: "var(--bg-1)",
          border: "1px solid var(--line-1)",
          padding: "6px 10px",
          borderRadius: 4,
          fontFamily: "JetBrains Mono, monospace",
          fontSize: 11,
          color: "var(--fg-1)",
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between"
        }}>
          <span>◆ {pred.regionName || "Region 1"}</span>
          <span style={{ color: "var(--fg-3)", fontSize: 10 }}>{pred.polygon.length} pts</span>
        </div>
      ) : (
        <div style={{ fontFamily: "JetBrains Mono, monospace", fontSize: 10.5, color: "var(--fg-3)" }}>
          No region defined
        </div>
      )}
      <div className="minimap-buttons">
        <button
          className={"btn-secondary" + (isDrawing ? " armed" : "")}
          onClick={onArmDraw}
        >
          {isDrawing ? "Drawing…" : (pred.polygon ? "Redraw" : "Draw on map")}
        </button>
      </div>
      {pred.polygon && (
        <>
          <div className="row" style={{ marginTop: 4 }}>
            <div>
              <div className="field-label">Alt min (ft)</div>
              <input
                className="text-field mono"
                type="number"
                placeholder="0"
                value={pred.altMin ?? ""}
                onChange={e => onChange({ ...pred, altMin: e.target.value === "" ? null : +e.target.value })}
              />
            </div>
            <div>
              <div className="field-label">Alt max (ft)</div>
              <input
                className="text-field mono"
                type="number"
                placeholder="∞"
                value={pred.altMax ?? ""}
                onChange={e => onChange({ ...pred, altMax: e.target.value === "" ? null : +e.target.value })}
              />
            </div>
          </div>
          <div>
            <div className="field-label">Min dwell (sec)</div>
            <input
              className="text-field mono"
              type="number"
              placeholder="0"
              value={pred.minDwell ?? ""}
              onChange={e => onChange({ ...pred, minDwell: e.target.value === "" ? null : +e.target.value })}
            />
          </div>
        </>
      )}
    </PredCard>
  );
}

function CallsignPredicate({ pred, onChange, onRemove }) {
  return (
    <PredCard icon={<Icon.Text />} name="Callsign" onRemove={onRemove}>
      <div>
        <div className="field-label">Regex pattern</div>
        <input
          className="text-field mono"
          placeholder="^BAW.*"
          value={pred.pattern || ""}
          onChange={e => onChange({ ...pred, pattern: e.target.value })}
        />
      </div>
    </PredCard>
  );
}

window.Predicates = { AircraftPredicate, TimePredicate, PointRadiusPredicate, RegionPredicate, CallsignPredicate };
