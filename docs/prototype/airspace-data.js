// Mock UK airspace polygons — CTR, MATZ, danger areas
(function () {
  function circle(lat, lng, radiusKm, sides = 32) {
    const coords = [];
    const R = 6371;
    for (let i = 0; i < sides; i++) {
      const a = (i / sides) * Math.PI * 2;
      const dLat = (radiusKm / R) * (180 / Math.PI) * Math.cos(a);
      const dLng = (radiusKm / R) * (180 / Math.PI) * Math.sin(a) / Math.cos(lat * Math.PI / 180);
      coords.push([lng + dLng, lat + dLat]);
    }
    coords.push(coords[0]);
    return coords;
  }

  const airspaces = [
    // CTRs (control zones, blue)
    { id: "ctr_egll", name: "London CTR", class: "CTR", floor: 0, ceiling: 2500, coords: circle(51.4706, -0.4619, 18) },
    { id: "ctr_egkk", name: "Gatwick CTR", class: "CTR", floor: 0, ceiling: 2500, coords: circle(51.1481, -0.1903, 9) },
    { id: "ctr_egcc", name: "Manchester CTR", class: "CTR", floor: 0, ceiling: 3500, coords: circle(53.3537, -2.2750, 12) },
    { id: "ctr_egbb", name: "Birmingham CTR", class: "CTR", floor: 0, ceiling: 4500, coords: circle(52.4539, -1.7480, 8) },
    { id: "ctr_egph", name: "Edinburgh CTR", class: "CTR", floor: 0, ceiling: 6000, coords: circle(55.9500, -3.3725, 10) },
    { id: "ctr_egpf", name: "Glasgow CTR", class: "CTR", floor: 0, ceiling: 6000, coords: circle(55.8719, -4.4331, 10) },

    // MATZ (military, magenta)
    { id: "matz_brz", name: "Brize Norton MATZ", class: "MATZ", floor: 0, ceiling: 3000, coords: circle(51.7500, -1.5836, 9) },
    { id: "matz_csl", name: "Coningsby MATZ", class: "MATZ", floor: 0, ceiling: 3000, coords: circle(53.0928, -0.1664, 9) },
    { id: "matz_lkn", name: "Leeming MATZ", class: "MATZ", floor: 0, ceiling: 3000, coords: circle(54.2925, -1.5353, 9) },
    { id: "matz_lhm", name: "Lossiemouth MATZ", class: "MATZ", floor: 0, ceiling: 3000, coords: circle(57.7053, -3.3392, 9) },

    // Danger areas (red hatched)
    { id: "d201", name: "D201 Salisbury", class: "DANGER", floor: 0, ceiling: 50000, coords: circle(51.20, -1.83, 14) },
    { id: "d513", name: "D513 Holbeach", class: "DANGER", floor: 0, ceiling: 23000, coords: circle(52.93, 0.10, 11) },
    { id: "d406", name: "D406 Spadeadam", class: "DANGER", floor: 0, ceiling: 19500, coords: circle(55.05, -2.55, 13) }
  ];

  window.AIRSPACE_DATA = airspaces;
})();
