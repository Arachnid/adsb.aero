// Mock ADS-B flight data — ~50 flights over UK across one week
// All trajectories generated procedurally with great-circle-ish interpolation + altitude profiles

(function () {
  const ICAO_TYPES = [
    "B738", "A320", "A321", "B737", "A319", "A20N", "B77W", "B789", "A359",
    "C172", "C152", "PA28", "DA42", "SR22", "P28A", "BE36",
    "E190", "E195", "AT76", "DH8D", "CRJ9",
    "EC35", "AS50", "R44", "EC30",
    "GLF6", "F2TH", "C56X", "C25A", "BE40"
  ];

  const EMITTER_CATEGORIES = [
    { code: "A1", label: "Light (<15500 lbs)" },
    { code: "A2", label: "Small (15500-75000 lbs)" },
    { code: "A3", label: "Large (75000-300000 lbs)" },
    { code: "A5", label: "Heavy (>300000 lbs)" },
    { code: "A7", label: "Rotorcraft" },
    { code: "B1", label: "Glider/Sailplane" },
    { code: "B2", label: "Lighter-than-air" },
    { code: "B6", label: "UAV" }
  ];

  // UK airports with rough lat/lng
  const AIRPORTS = [
    { icao: "EGLL", name: "Heathrow", lat: 51.4706, lng: -0.4619 },
    { icao: "EGKK", name: "Gatwick", lat: 51.1481, lng: -0.1903 },
    { icao: "EGSS", name: "Stansted", lat: 51.8849, lng: 0.2350 },
    { icao: "EGGW", name: "Luton", lat: 51.8747, lng: -0.3683 },
    { icao: "EGLC", name: "London City", lat: 51.5053, lng: 0.0553 },
    { icao: "EGCC", name: "Manchester", lat: 53.3537, lng: -2.2750 },
    { icao: "EGBB", name: "Birmingham", lat: 52.4539, lng: -1.7480 },
    { icao: "EGPH", name: "Edinburgh", lat: 55.9500, lng: -3.3725 },
    { icao: "EGPF", name: "Glasgow", lat: 55.8719, lng: -4.4331 },
    { icao: "EGGD", name: "Bristol", lat: 51.3827, lng: -2.7191 },
    { icao: "EGNX", name: "East Midlands", lat: 52.8311, lng: -1.3281 },
    { icao: "EGNT", name: "Newcastle", lat: 55.0375, lng: -1.6917 },
    { icao: "EGFF", name: "Cardiff", lat: 51.3967, lng: -3.3433 },
    { icao: "EGAA", name: "Belfast Intl", lat: 54.6575, lng: -6.2158 },
    { icao: "EGHI", name: "Southampton", lat: 50.9503, lng: -1.3568 },
    { icao: "EGHH", name: "Bournemouth", lat: 50.7800, lng: -1.8425 },
    { icao: "EGHQ", name: "Cornwall Newquay", lat: 50.4406, lng: -4.9954 },
    { icao: "EGTK", name: "Oxford", lat: 51.8369, lng: -1.3200 },
    { icao: "EGHN", name: "Sandown", lat: 50.6533, lng: -1.1842 },
    { icao: "EGKA", name: "Shoreham", lat: 50.8356, lng: -0.2972 },
    { icao: "EGTC", name: "Cranfield", lat: 52.0722, lng: -0.6164 },
    { icao: "EGBE", name: "Coventry", lat: 52.3697, lng: -1.4797 },
    { icao: "EGNM", name: "Leeds Bradford", lat: 53.8659, lng: -1.6606 },
    { icao: "EGPK", name: "Prestwick", lat: 55.5094, lng: -4.5867 },
    { icao: "EGPE", name: "Inverness", lat: 57.5425, lng: -4.0475 }
  ];

  // International outbound destinations for top-of-descent / climb-out flights
  const INTL = [
    { icao: "LFPG", name: "Paris CDG", lat: 49.0097, lng: 2.5479 },
    { icao: "EHAM", name: "Amsterdam", lat: 52.3086, lng: 4.7639 },
    { icao: "EDDF", name: "Frankfurt", lat: 50.0379, lng: 8.5622 },
    { icao: "LEMD", name: "Madrid", lat: 40.4719, lng: -3.5626 },
    { icao: "LIRF", name: "Rome FCO", lat: 41.8003, lng: 12.2389 },
    { icao: "EIDW", name: "Dublin", lat: 53.4213, lng: -6.2701 },
    { icao: "BIKF", name: "Reykjavik", lat: 63.985, lng: -22.6056 },
    { icao: "KJFK", name: "New York JFK", lat: 40.6413, lng: -73.7781 }
  ];

  const AIRLINES = ["BAW", "EZY", "RYR", "TOM", "VIR", "EXS", "TAY", "BMR", "LOG", "FLE"];

  function rand(seed) {
    let s = seed | 0;
    return function () {
      s = (s * 1664525 + 1013904223) | 0;
      return ((s >>> 0) % 1000000) / 1000000;
    };
  }

  function pick(rnd, arr) { return arr[Math.floor(rnd() * arr.length)]; }

  function distance(a, b) {
    const R = 6371;
    const dLat = (b.lat - a.lat) * Math.PI / 180;
    const dLng = (b.lng - a.lng) * Math.PI / 180;
    const lat1 = a.lat * Math.PI / 180;
    const lat2 = b.lat * Math.PI / 180;
    const x = Math.sin(dLat/2)**2 + Math.cos(lat1)*Math.cos(lat2)*Math.sin(dLng/2)**2;
    return 2 * R * Math.asin(Math.sqrt(x));
  }

  function nearestAirport(lat, lng) {
    let best = null, bestD = Infinity;
    for (const a of AIRPORTS) {
      const d = distance({lat, lng}, a);
      if (d < bestD) { bestD = d; best = a; }
    }
    return { airport: best, distance: bestD };
  }

  // Generate a procedural trajectory between two points with realistic altitude profile
  function buildTrajectory(rnd, from, to, type, t0) {
    const totalDist = distance(from, to);
    const isLightAircraft = ["C172","C152","PA28","DA42","SR22","P28A","BE36"].includes(type);
    const isHeli = ["EC35","AS50","R44","EC30"].includes(type);
    const isJet = !isLightAircraft && !isHeli;

    const cruiseAlt = isHeli ? 1500 + rnd() * 1500
      : isLightAircraft ? 3000 + rnd() * 4000
      : 28000 + rnd() * 12000;
    const cruiseSpeed = isHeli ? 110 : isLightAircraft ? 130 : 460; // knots
    const durationHrs = totalDist / 1.852 / cruiseSpeed; // rough
    const durationSec = Math.max(600, durationHrs * 3600);
    const stepSec = 30;
    const steps = Math.max(20, Math.floor(durationSec / stepSec));

    const points = [];
    // Add slight along-route perturbation for organic curvature
    const perturbAmpLat = (rnd() - 0.5) * 0.6;
    const perturbAmpLng = (rnd() - 0.5) * 0.6;

    for (let i = 0; i <= steps; i++) {
      const t = i / steps;
      const lat = from.lat + (to.lat - from.lat) * t + Math.sin(t * Math.PI) * perturbAmpLat;
      const lng = from.lng + (to.lng - from.lng) * t + Math.sin(t * Math.PI) * perturbAmpLng;

      // Altitude profile: climb (0-15%), cruise (15-85%), descent (85-100%)
      let alt;
      if (t < 0.15) alt = (t / 0.15) * cruiseAlt;
      else if (t < 0.85) {
        // small variations during cruise
        const wobble = Math.sin(t * 23) * (isJet ? 200 : 100);
        alt = cruiseAlt + wobble;
      } else alt = cruiseAlt * (1 - (t - 0.85) / 0.15);
      alt = Math.max(0, alt);

      const speed = t < 0.1 ? cruiseSpeed * (t/0.1) :
                    t > 0.9 ? cruiseSpeed * ((1-t)/0.1) :
                    cruiseSpeed * (0.95 + Math.sin(t*7)*0.05);

      points.push({
        t: t0 + i * stepSec,
        lat, lng,
        alt: Math.round(alt),
        spd: Math.round(speed),
        hdg: 0 // not used
      });
    }
    return points;
  }

  function fmtCallsign(rnd, type) {
    const isLight = ["C172","C152","PA28","DA42","SR22","P28A","BE36"].includes(type);
    const isHeli = ["EC35","AS50","R44","EC30"].includes(type);
    if (isLight) {
      // G-XXXX UK reg
      const letters = "ABCDEFGHJKLMNOPRSTUVWXYZ";
      let s = "G-";
      for (let i = 0; i < 4; i++) s += letters[Math.floor(rnd()*letters.length)];
      return s;
    }
    if (isHeli) {
      const letters = "ABCDEFGHJKLMNOPRSTUVWXYZ";
      let s = "G-";
      for (let i = 0; i < 4; i++) s += letters[Math.floor(rnd()*letters.length)];
      return s;
    }
    return pick(rnd, AIRLINES) + Math.floor(rnd()*9000 + 100);
  }

  function emitterFor(type) {
    if (["C172","C152","PA28","DA42","SR22","P28A","BE36"].includes(type)) return "A1";
    if (["EC35","AS50","R44","EC30"].includes(type)) return "A7";
    if (["B77W","B789","A359"].includes(type)) return "A5";
    if (["A320","A321","B737","B738","A319","A20N","E190","E195","AT76","DH8D","CRJ9"].includes(type)) return "A3";
    if (["GLF6","F2TH","C56X","C25A","BE40"].includes(type)) return "A2";
    return "A3";
  }

  const flights = [];
  const rnd = rand(42);
  const WEEK_START = Date.UTC(2026, 4, 1, 0, 0, 0) / 1000; // May 1 2026
  const WEEK_LEN = 7 * 86400;

  for (let i = 0; i < 52; i++) {
    const type = pick(rnd, ICAO_TYPES);
    const isLight = ["C172","C152","PA28","DA42","SR22","P28A","BE36"].includes(type);
    const isHeli = ["EC35","AS50","R44","EC30"].includes(type);

    // Origin always UK; destination sometimes intl for jets
    const origin = pick(rnd, AIRPORTS);
    let dest;
    if (isLight || isHeli) {
      // short hops within UK
      do { dest = pick(rnd, AIRPORTS); } while (dest === origin);
    } else if (rnd() < 0.45) {
      dest = pick(rnd, INTL);
    } else {
      do { dest = pick(rnd, AIRPORTS); } while (dest === origin);
    }

    const t0 = Math.floor(WEEK_START + rnd() * WEEK_LEN);
    const traj = buildTrajectory(rnd, origin, dest, type, t0);

    // Truncate trajectory at UK bounding box edge so it terminates near coast for intl flights
    const ukBox = { minLat: 49.5, maxLat: 60.0, minLng: -8.5, maxLng: 2.5 };
    const filtered = traj.filter(p => p.lat >= ukBox.minLat && p.lat <= ukBox.maxLat && p.lng >= ukBox.minLng && p.lng <= ukBox.maxLng);
    if (filtered.length < 5) continue; // skip if barely in UK

    const callsign = fmtCallsign(rnd, type);
    const maxAlt = filtered.reduce((m,p) => Math.max(m, p.alt), 0);
    const startNear = nearestAirport(filtered[0].lat, filtered[0].lng);
    const endNear = nearestAirport(filtered[filtered.length-1].lat, filtered[filtered.length-1].lng);

    flights.push({
      id: "f" + i.toString().padStart(3, "0"),
      callsign,
      icaoType: type,
      emitter: emitterFor(type),
      tStart: filtered[0].t,
      tEnd: filtered[filtered.length-1].t,
      points: filtered,
      maxAlt,
      origin: { ...startNear, intended: origin },
      destination: { ...endNear, intended: dest }
    });
  }

  window.MOCK_DATA = {
    flights,
    AIRPORTS,
    EMITTER_CATEGORIES,
    ICAO_TYPES,
    nearestAirport,
    distance
  };
})();
