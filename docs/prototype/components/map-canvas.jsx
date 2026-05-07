// Leaflet-based map canvas: trajectories, airspace, drawing, picking.

const { useRef: mcUseRef, useEffect: mcUseEffect, useState: mcUseState } = React;

function altColor(alt) {
  const t = Math.min(1, Math.max(0, alt / 40000));
  const stops = [
    [0, [226, 100, 100]], [0.2, [240, 160, 77]], [0.4, [240, 224, 102]],
    [0.6, [110, 211, 163]], [0.8, [110, 168, 255]], [1, [155, 110, 240]]
  ];
  for (let i = 0; i < stops.length - 1; i++) {
    if (t <= stops[i+1][0]) {
      const [t0, c0] = stops[i];
      const [t1, c1] = stops[i+1];
      const k = (t - t0) / (t1 - t0);
      return `rgb(${Math.round(c0[0]+(c1[0]-c0[0])*k)},${Math.round(c0[1]+(c1[1]-c0[1])*k)},${Math.round(c0[2]+(c1[2]-c0[2])*k)})`;
    }
  }
  return "rgb(155,110,240)";
}

const CATEGORY_COLORS = {
  A1: "#6ed3a3", A2: "#6ea8ff", A3: "#4d8df0", A5: "#9b6ef0",
  A7: "#f0a04d", B1: "#f0e066", B2: "#d066c8", B6: "#e26464"
};

function todColor(unix) {
  const h = new Date(unix * 1000).getUTCHours();
  if (h < 6) return "#6ea8ff";
  if (h < 12) return "#f0e066";
  if (h < 18) return "#f0a04d";
  return "#9b6ef0";
}

function flightColorForCard(flight, mode) {
  if (mode === "cat") return CATEGORY_COLORS[flight.emitter] || "#6ea8ff";
  if (mode === "tod") return todColor(flight.tStart);
  return altColor(flight.maxAlt * 0.7);
}

const TILE_URLS = {
  dark: "https://tile.openstreetmap.org/{z}/{x}/{y}.png",
  light: "https://tile.openstreetmap.org/{z}/{x}/{y}.png",
  sat: "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}"
};
const TILE_FILTERS = {
  dark: "brightness(0.55) saturate(0.5) contrast(1.05) hue-rotate(180deg) invert(0.92)",
  light: "saturate(0.6) brightness(1.02)",
  sat: "none"
};

function MapCanvas({
  flights, selectedId, onSelect, colorMode,
  airspaceOn, basemap,
  pickMode, onPicked,
  drawMode, onDrawn,
  isolatedId,
  onAirspaceClick,
  pointPredicates,
  regionPredicates
}) {
  const mapRef = mcUseRef(null);
  const containerRef = mcUseRef(null);
  const layersRef = mcUseRef({
    tile: null, traj: null, hl: null, airspace: null,
    queryPts: null, queryRegions: null, drawPreview: null
  });
  const drawStateRef = mcUseRef({ points: [], cursorMarker: null });
  const propsRef = mcUseRef({ pickMode, drawMode, onPicked, onDrawn });
  const [tooltip, setTooltip] = mcUseState(null);
  const [popupAnchor, setPopupAnchor] = mcUseState(null);
  const [popupScreen, setPopupScreen] = mcUseState(null);

  mcUseEffect(() => { propsRef.current = { pickMode, drawMode, onPicked, onDrawn }; });

  // Init map once
  mcUseEffect(() => {
    const map = L.map(containerRef.current, {
      zoomControl: false,
      attributionControl: true,
      preferCanvas: true,
      doubleClickZoom: false
    }).setView([54.5, -2.5], 6);
    mapRef.current = map;
    window.__map = map;

    // Ensure canvas measures correctly after layout
    setTimeout(() => map.invalidateSize(), 0);

    L.control.zoom({ position: "bottomright" }).addTo(map);

    // Tile layer
    layersRef.current.tile = L.tileLayer(TILE_URLS[basemap], {
      attribution: "© OpenStreetMap",
      maxZoom: 18,
      className: "tile-" + basemap
    }).addTo(map);

    // Layer groups
    layersRef.current.airspace = L.layerGroup().addTo(map);
    layersRef.current.queryRegions = L.layerGroup().addTo(map);
    layersRef.current.queryPts = L.layerGroup().addTo(map);
    layersRef.current.traj = L.layerGroup().addTo(map);
    layersRef.current.hl = L.layerGroup().addTo(map);
    layersRef.current.drawPreview = L.layerGroup().addTo(map);

    // Click handler
    map.on("click", (e) => {
      const { pickMode, drawMode, onPicked } = propsRef.current;
      if (pickMode) {
        onPicked(pickMode, { lat: e.latlng.lat, lng: e.latlng.lng });
        return;
      }
      if (drawMode) {
        drawStateRef.current.points.push([e.latlng.lng, e.latlng.lat]);
        renderDrawPreview();
        return;
      }
      setPopupAnchor(null);
      onSelect && onSelect(null);
    });

    map.on("dblclick", (e) => {
      if (propsRef.current.drawMode) {
        L.DomEvent.preventDefault(e);
        finishDraw();
      }
    });

    map.on("mousemove", (e) => {
      if (propsRef.current.drawMode && drawStateRef.current.points.length > 0) {
        renderDrawPreview([e.latlng.lng, e.latlng.lat]);
      }
    });

    const onKey = (ev) => {
      if (ev.key === "Escape") {
        if (propsRef.current.drawMode) cancelDraw();
      }
    };
    window.addEventListener("keydown", onKey);

    function renderDrawPreview(cursorPt) {
      const lg = layersRef.current.drawPreview;
      lg.clearLayers();
      const pts = drawStateRef.current.points;
      pts.forEach(p => {
        L.circleMarker([p[1], p[0]], {
          radius: 4, color: "#0b0f14", weight: 1.5,
          fillColor: "#6ea8ff", fillOpacity: 1
        }).addTo(lg);
      });
      const lineLat = pts.map(p => [p[1], p[0]]);
      if (cursorPt && lineLat.length > 0) lineLat.push([cursorPt[1], cursorPt[0]]);
      if (lineLat.length >= 2) {
        L.polyline(lineLat, { color: "#6ea8ff", weight: 1.5, dashArray: "4 3" }).addTo(lg);
      }
      if (pts.length >= 3) {
        L.polygon(pts.map(p => [p[1], p[0]]), {
          color: "#6ea8ff", weight: 1.5, fillColor: "#6ea8ff", fillOpacity: 0.15
        }).addTo(lg);
      }
    }

    function finishDraw() {
      const pts = drawStateRef.current.points;
      if (pts.length < 3) return;
      const polygon = [...pts, pts[0]];
      drawStateRef.current.points = [];
      layersRef.current.drawPreview.clearLayers();
      const { onDrawn } = propsRef.current;
      onDrawn && onDrawn(polygon);
    }

    function cancelDraw() {
      drawStateRef.current.points = [];
      layersRef.current.drawPreview.clearLayers();
      const { onDrawn } = propsRef.current;
      onDrawn && onDrawn(null);
    }

    return () => {
      window.removeEventListener("keydown", onKey);
      map.remove();
    };
  }, []);

  // Swap tile layer when basemap changes
  mcUseEffect(() => {
    if (!mapRef.current) return;
    if (layersRef.current.tile) {
      mapRef.current.removeLayer(layersRef.current.tile);
    }
    layersRef.current.tile = L.tileLayer(TILE_URLS[basemap], {
      attribution: "© " + (basemap === "sat" ? "Esri" : "OpenStreetMap"),
      maxZoom: 18,
      className: "tile-" + basemap
    }).addTo(mapRef.current);
    // Apply filter via CSS class on tiles container
    const pane = mapRef.current.getPanes().tilePane;
    pane.style.filter = TILE_FILTERS[basemap];
  }, [basemap]);

  // Render trajectories
  mcUseEffect(() => {
    if (!mapRef.current) return;
    mapRef.current.invalidateSize();
    const lg = layersRef.current.traj;
    const hlg = layersRef.current.hl;
    if (!lg || !hlg) return;
    lg.clearLayers();
    hlg.clearLayers();

    const visible = isolatedId
      ? flights.filter(f => f.id === isolatedId)
      : flights;

    visible.forEach(flight => {
      const pts = flight.points;
      // Per-segment polyline group, colored by mode
      for (let i = 0; i < pts.length - 1; i++) {
        let color;
        if (colorMode === "alt") color = altColor((pts[i].alt + pts[i+1].alt)/2);
        else if (colorMode === "cat") color = CATEGORY_COLORS[flight.emitter] || "#6ea8ff";
        else color = todColor(pts[i].t);
        const seg = L.polyline(
          [[pts[i].lat, pts[i].lng], [pts[i+1].lat, pts[i+1].lng]],
          { color, weight: 1.5, opacity: 0.8, interactive: false }
        );
        seg.addTo(lg);
      }
      // Invisible thick polyline for hover/click events
      const fullLine = L.polyline(pts.map(p => [p.lat, p.lng]), {
        color: "#000", weight: 14, opacity: 0, interactive: true
      });
      fullLine.on("mouseover", (e) => {
        const layerPt = mapRef.current.latLngToContainerPoint(e.latlng);
        setTooltip({
          x: layerPt.x, y: layerPt.y,
          callsign: flight.callsign, type: flight.icaoType, maxAlt: flight.maxAlt
        });
      });
      fullLine.on("mousemove", (e) => {
        const layerPt = mapRef.current.latLngToContainerPoint(e.latlng);
        setTooltip({
          x: layerPt.x, y: layerPt.y,
          callsign: flight.callsign, type: flight.icaoType, maxAlt: flight.maxAlt
        });
      });
      fullLine.on("mouseout", () => setTooltip(null));
      fullLine.on("click", (e) => {
        L.DomEvent.stopPropagation(e);
        onSelect && onSelect(flight.id);
        setPopupAnchor({ id: flight.id, latlng: e.latlng });
      });
      fullLine.addTo(lg);
    });

    // Selected highlight
    if (selectedId) {
      const f = visible.find(x => x.id === selectedId);
      if (f) {
        const coords = f.points.map(p => [p.lat, p.lng]);
        L.polyline(coords, { color: "#ffffff", weight: 6, opacity: 0.25 }).addTo(hlg);
        L.polyline(coords, { color: "#ffffff", weight: 2.5, opacity: 1 }).addTo(hlg);
      }
    }
  }, [flights, colorMode, selectedId, isolatedId]);

  // Render airspace
  mcUseEffect(() => {
    if (!mapRef.current || !layersRef.current.airspace) return;
    const lg = layersRef.current.airspace;
    lg.clearLayers();
    if (!airspaceOn) return;
    window.AIRSPACE_DATA.forEach(a => {
      const color = a.class === "CTR" ? "#6ea8ff" : a.class === "MATZ" ? "#d066c8" : "#e26464";
      const opts = {
        color, weight: 1.2, fillColor: color, fillOpacity: 0.08,
        dashArray: a.class === "DANGER" ? "6 4" : null
      };
      const poly = L.polygon(a.coords.map(c => [c[1], c[0]]), opts);
      poly.on("click", (e) => {
        L.DomEvent.stopPropagation(e);
        window.dispatchEvent(new CustomEvent("airspace-click", { detail: { id: a.id, name: a.name } }));
      });
      poly.bindTooltip(`<b>${a.name}</b><br><span style="color:#7d8a9b">${a.class} · ${a.floor}-${a.ceiling} ft</span>`, {
        sticky: true, className: "leaflet-tooltip-dark"
      });
      poly.addTo(lg);
    });
  }, [airspaceOn]);

  // Render query points (radii)
  mcUseEffect(() => {
    if (!mapRef.current || !layersRef.current.queryPts) return;
    const lg = layersRef.current.queryPts;
    lg.clearLayers();
    (pointPredicates || []).forEach(p => {
      if (p.lat == null) return;
      L.circle([p.lat, p.lng], {
        radius: (p.radiusKm || 25) * 1000,
        color: "#6ea8ff", weight: 1, dashArray: "4 3",
        fillColor: "#6ea8ff", fillOpacity: 0.08
      }).addTo(lg);
      L.circleMarker([p.lat, p.lng], {
        radius: 5, color: "#0b0f14", weight: 2,
        fillColor: "#6ea8ff", fillOpacity: 1
      }).addTo(lg);
    });
  }, [pointPredicates]);

  // Render query regions
  mcUseEffect(() => {
    if (!mapRef.current || !layersRef.current.queryRegions) return;
    const lg = layersRef.current.queryRegions;
    lg.clearLayers();
    (regionPredicates || []).forEach(r => {
      if (!r.polygon) return;
      L.polygon(r.polygon.map(c => [c[1], c[0]]), {
        color: "#6ea8ff", weight: 1.5, dashArray: "4 3",
        fillColor: "#6ea8ff", fillOpacity: 0.10
      }).bindTooltip(r.regionName || "Region", { sticky: true }).addTo(lg);
    });
  }, [regionPredicates]);

  // Cursor for picker / draw
  mcUseEffect(() => {
    if (!mapRef.current) return;
    const c = mapRef.current.getContainer();
    c.style.cursor = (pickMode || drawMode) ? "crosshair" : "";
  }, [pickMode, drawMode]);

  // Track popup screen position
  mcUseEffect(() => {
    if (!popupAnchor || !mapRef.current) { setPopupScreen(null); return; }
    const map = mapRef.current;
    const update = () => {
      const p = map.latLngToContainerPoint(popupAnchor.latlng);
      setPopupScreen({ x: p.x, y: p.y });
    };
    update();
    map.on("move zoom", update);
    return () => map.off("move zoom", update);
  }, [popupAnchor]);

  // Clear popup if isolated/selected changes invalidate
  mcUseEffect(() => {
    if (popupAnchor && !flights.find(f => f.id === popupAnchor.id)) {
      setPopupAnchor(null);
    }
  }, [flights, popupAnchor]);

  return (
    <>
      <div id="map" ref={containerRef}></div>
      {tooltip && (
        <div className="map-tooltip" style={{ left: tooltip.x + 14, top: tooltip.y + 14 }}>
          <div className="tt-head">{tooltip.callsign}</div>
          <div className="tt-meta">{tooltip.type} · max {tooltip.maxAlt.toLocaleString()} ft</div>
        </div>
      )}
      {drawMode && (
        <div className="drawing-hint">
          <span className="dot"></span>
          Click to place vertices · Double-click to close · <kbd>Esc</kbd> to cancel
        </div>
      )}
      {pickMode && (
        <div className="drawing-hint">
          <span className="dot"></span>
          Click on the map to place point · <kbd>Esc</kbd> to cancel
        </div>
      )}
      {popupAnchor && popupScreen && (() => {
        const f = flights.find(x => x.id === popupAnchor.id);
        if (!f) return null;
        return (
          <FlightDetail.FlightDetailPopup
            flight={f}
            screenPos={{
              x: Math.min(window.innerWidth - 340, Math.max(20, popupScreen.x + 14)),
              y: Math.max(70, Math.min(window.innerHeight - 320, popupScreen.y - 100))
            }}
            onClose={() => { setPopupAnchor(null); onSelect && onSelect(null); }}
            onIsolate={() => onAirspaceClick && onAirspaceClick({ type: "isolate", id: f.id })}
          />
        );
      })()}
    </>
  );
}

window.MapCanvas = MapCanvas;
window.flightColorForCard = flightColorForCard;
