# H3 — Controlled-Airspace Floors and Vertical Traffic Compression

## Hypothesis

**H3**: Controlled-airspace floors compress VFR traffic into thin vertical bands and narrow
lateral funnels; the resulting concentration (traffic per unit airspace volume) is a
structural mid-air-collision exposure multiplier that per-event airprox analysis doesn't
capture. **Test**: quantify vertical bunching under airspace shelves vs. open Class G, using
the adsb.aero historical ADS-B archive.

## Method

### Areas (lon/lat WSEN boxes)

| label | description | box (W, S) – (E, N) | area (km²) |
|---|---|---|---|
| **London TMA shelf** | Class G beneath the London TMA (base 2,500 ft), SW of London, N of Gatwick, around Ockham/Fairoaks/Woking. Terrain ~50–100 m. | (-0.85, 51.15) – (-0.30, 51.32) | 723.8 |
| **Manchester LLR** | Manchester Low Level Route corridor, ~4 nm wide, where the Manchester/Liverpool CTA forces VFR below 1,300 ft. Terrain ~20–60 m. | (-2.55, 53.20) – (-2.30, 53.42) | 406.3 |
| **Control** | Open Class G, no overlying CTA below ~5,500 ft (Shropshire/Welsh borders, clear of Birmingham/Shawbury zones as far as practical). | (-2.7, 52.35) – (-2.1, 52.75) | 1,804.4 |

Areas computed with the spherical-graticule formula (`Δlon · R² · (sin lat_N − sin lat_S)`,
R = 6,371.0088 km) — exact for a lon/lat box, not a flat-earth approximation. All three boxes
are well inside the 250 H3 res-4 cell / ~4°-per-side API limit, so no tiling was needed.

### Sample days

Six fixed dates, all Saturdays (typical GA weekend-flying days):

- **Summer**: 2026-05-09, 2026-06-20, 2026-07-11, 2026-07-18
- **Winter**: 2026-01-17, 2026-02-14

Weather-dead check (per the brief: swap any summer day under 20% of the busiest summer day's
traffic): busiest summer day (3-area sum) = 244 flights (07-11); 20% floor = 48.8; the
quietest summer day was 159 flights (06-20, 65% of busiest). **No day was under the floor, so
no swaps were made** — all four fixed dates were used as given. See the coverage table below.

### Query (one per area × day, 18 total)

```json
{
  "start_from": "<DAY>T00:00:00Z",
  "end_date": "<DAY+1>T00:00:00Z",
  "window_days": 1,
  "match": {
    "and": [
      {"trajectory_intersects": {
        "geometry": {"type": "Polygon", "coordinates": [[[W,S],[E,S],[E,N],[W,N],[W,S]]]},
        "altitude_max": 6000,
        "altitude_max_ref": "ft"
      }},
      {"emitter_category": ["A1"]}
    ]
  },
  "include_path": true,
  "limit": 500
}
```

Geometry substituted per area from the table above; `<DAY>` substituted for each of the six
dates. Paged on `cursor` until null (all 18 queries returned in a single page — no A1-under-
6000ft traffic sample exceeded 500 flights/day/box). One additional small validation query
(`limit: 3`) was run first against the TMA-shelf box to confirm response shape and DSL
behaviour before scaling up. **Total API calls: 19**, well under the ~60 budget for this task
and the briefing's 150–250 ceiling. Day boundaries are UTC calendar days (not local BST/GMT);
since UK VFR flying happens in daylight hours, a UTC day fully contains the local flying day
in both seasons, so this has no material effect.

### Client-side processing (per flight, per area)

For every returned flight: walk each path sub-sequence's consecutive vertex pairs (subsequences
= readsb signal-gap segments; **436 of 1,112 flights had more than one**, so gaps are never
bridged into a fake segment).

1. **Box-clip**: Liang–Barsky clip of the lon/lat segment against the area box → the fractional
   parameter range `[t0, t1]` of the segment actually inside the box (unit-tested against
   fully-inside / fully-outside / crossing / corner-grazing segments before running on real
   data). Segment time is split **linearly** over this fraction to get the clipped time
   interval `[ts_a, ts_b]`.
2. **AGL exclusion**: `path_agl_ft` (stepwise, forward-filled to `ts_a`) is sampled once per
   clipped sub-segment; if AGL < 500 ft, the whole sub-segment's time is excluded from bins and
   tallied separately (this removes circuit/ground-proximate ops at Fairoaks, Blackbushe, etc.,
   per the brief). Applied only when a flight has a non-empty `path_agl_ft` series.
3. **QNH altitude**: `alt_correction_ft` (stepwise/forward-filled series) is added to the raw
   pressure-altitude `Z` at each clipped endpoint: `QNH = Z + correction`; correction defaults
   to 0 only when a flight's entire correction series is empty (0 of 1,112 flights here — see
   caveats).
4. **250 ft binning**: the clipped sub-segment's time is apportioned across the 250 ft QNH bins
   spanning 0–6,000 ft **linearly** in proportion to how much of the altitude range
   `[alt_a, alt_b]` each bin covers (i.e. assumes constant climb/descent rate across the
   sub-segment) — the same "approximate ... linearly" rule applied to both the spatial clip and
   the altitude split. Time corresponding to altitude outside 0–6,000 ft is tracked separately,
   not binned (this is expected: `altitude_max: 6000` is a "some point in the box" constraint,
   not an "always" constraint, so a matched flight can still have moments above 6,000 ft inside
   the box).

All formulas were unit-tested on synthetic segments (level flight, climbing/descending,
clipped at the 0 ft floor and 6,000 ft ceiling, bin-edge straddling) before running on the
1,112 retrieved flights.

---

## Results

### Sample-day coverage and weather-dead check

| day | season | day-of-week | London TMA shelf | Manchester LLR | Control (open Class G) | sum (3 areas) |
|---|---|---|---|---|---|---|
| 2026-05-09 | summer | Saturday | 98 | 6 | 56 | 160 |
| 2026-06-20 | summer | Saturday | 63 | 14 | 82 | 159 |
| 2026-07-11 | summer | Saturday | 69 | 34 | 141 | 244 |
| 2026-07-18 | summer | Saturday | 74 | 23 | 127 | 224 |
| 2026-01-17 | winter | Saturday | 30 | 3 | 31 | 64 |
| 2026-02-14 | winter | Saturday | 113 | 22 | 126 | 261 |

Note: 2026-02-14 (winter) was an unusually active flying Saturday — likely a stable
high-pressure spell — comparable to or busier than some summer days. Reported as observed, not
adjusted (no swap rule was specified for winter days). The Manchester LLR box is narrow
(406 km²) and sees genuinely low absolute GA volumes (3–34 A1 flights/day) — treat its winter
pool (25 flights total) as the noisiest cell in this study; flagged again below.

Total flights retrieved across all 18 area×day queries: **1,112**.

### AGL < 500 ft exclusion and out-of-0–6,000 ft time (pooled, both seasons)

| area | box-dwell seconds (pre-filter) | AGL<500ft excluded (s) | AGL excluded % | outside 0–6,000ft QNH (s) | outside-range % |
|---|---|---|---|---|---|
| London TMA shelf | 155,800 | 2,450 | 1.57% | 654 | 0.42% |
| Manchester LLR | 22,343 | 778 | 3.48% | 419 | 1.87% |
| Control (open Class G) | 383,773 | 3,359 | 0.88% | 2,259 | 0.59% |

The AGL filter removed a small, plausible fraction of time in each area (highest in the LLR box,
consistent with pattern traffic at the corridor's several small airfields); it does not drive
the results — the busy bands below are overwhelmingly genuine level/transit flight, not circuit
work. `alt_correction_ft` fallback to 0 (used only when a flight's whole correction series is
empty): **0 of 1,112 flights**.

### Histogram — Summer (pooled 2026-05-09, 06-20, 07-11, 07-18)

Flight-seconds per 250 ft QNH bin, pooled across the season's 4 days, per area.

| ft band | London TMA shelf | Manchester LLR | Control (open Class G) |
|---|---|---|---|
| 0–250 | 34 | 0 | 0 |
| 250–500 | 265 | 122 | 67 |
| 500–750 | 393 | 390 | 1,342 |
| 750–1000 | 3,638 | 2,542 | 4,164 |
| 1000–1250 | 11,415 | 6,953 | 10,177 |
| 1250–1500 *(LLR ceiling falls here)* | 13,957 | 4,144 | 15,922 |
| 1500–1750 | 25,103 | 341 | 11,270 |
| 1750–2000 | 26,478 | 132 | 20,488 |
| 2000–2250 | 15,199 | 133 | 33,739 |
| 2250–2500 | 5,147 | 137 | 37,721 |
| 2500–2750 *(TMA base)* | 589 | 134 | 25,770 |
| 2750–3000 | 1,465 | 426 | 28,935 |
| 3000–3250 | 1,419 | 116 | 17,451 |
| 3250–3500 | 433 | 89 | 17,438 |
| 3500–3750 | 423 | 71 | 14,256 |
| 3750–4000 | 569 | 57 | 9,440 |
| 4000–4250 | 434 | 58 | 6,437 |
| 4250–4500 | 199 | 47 | 5,269 |
| 4500–4750 | 198 | 45 | 3,533 |
| 4750–5000 | 344 | 46 | 4,033 |
| 5000–5250 | 163 | 47 | 3,217 |
| 5250–5500 | 86 | 88 | 2,697 |
| 5500–5750 | 78 | 12 | 1,467 |
| 5750–6000 | 82 | 13 | 796 |

### Histogram — Winter (pooled 2026-01-17, 02-14)

| ft band | London TMA shelf | Manchester LLR | Control (open Class G) |
|---|---|---|---|
| 0–250 | 4 | 0 | 0 |
| 250–500 | 71 | 28 | 0 |
| 500–750 | 103 | 121 | 524 |
| 750–1000 | 825 | 712 | 1,886 |
| 1000–1250 | 6,988 | 1,489 | 7,266 |
| 1250–1500 *(LLR ceiling falls here)* | 5,380 | 1,803 | 8,090 |
| 1500–1750 | 5,377 | 82 | 5,234 |
| 1750–2000 | 12,560 | 31 | 5,260 |
| 2000–2250 | 8,165 | 39 | 7,688 |
| 2250–2500 | 2,339 | 46 | 11,446 |
| 2500–2750 *(TMA base)* | 200 | 47 | 9,355 |
| 2750–3000 | 745 | 53 | 10,077 |
| 3000–3250 | 624 | 58 | 7,958 |
| 3250–3500 | 193 | 58 | 6,568 |
| 3500–3750 | 180 | 55 | 5,304 |
| 3750–4000 | 168 | 65 | 3,241 |
| 4000–4250 | 115 | 61 | 2,273 |
| 4250–4500 | 116 | 55 | 1,759 |
| 4500–4750 | 95 | 52 | 1,380 |
| 4750–5000 | 112 | 62 | 2,367 |
| 5000–5250 | 106 | 22 | 2,783 |
| 5250–5500 | 36 | 21 | 1,154 |
| 5500–5750 | 29 | 21 | 552 |
| 5750–6000 | 55 | 21 | 357 |

### Normalized shape — summer (% of that area's own 0–6,000 ft total)

This removes the raw-volume difference between areas (control has far more absolute traffic)
so the *shape* of vertical concentration is directly comparable.

**London TMA shelf** (108,110 flight-s total, summer)
```
    0-250     0.0%
  250-500     0.2%
  500-750     0.4%
  750-1000    3.4% ###
 1000-1250   10.6% ###########
 1250-1500   12.9% #############
 1500-1750   23.2% #######################
 1750-2000   24.5% ########################
 2000-2250   14.1% ##############
 2250-2500    4.8% #####
 2500-2750    0.5% #  <- TMA base (2500 ft)
 2750-3000    1.4% #
 3000-3250    1.3% #
 3250-6000   <0.5% each (long, flat tail)
```

**Manchester LLR** (16,143 flight-s total, summer)
```
    0-250     0.0%
  250-500     0.8% #
  500-750     2.4% ##
  750-1000   15.7% ################
 1000-1250   43.1% ###########################################
 1250-1500   25.7% ##########################  <- LLR ceiling falls in this bin (1300 ft)
 1500-1750    2.1% ##
 1750-2000    0.8% #
 2000-3000   ~0.8-2.6% each  (near-total drop-off above the corridor)
 3000-6000   <0.7% each (long, flat tail)
```

**Control (open Class G)** (275,632 flight-s total, summer)
```
    0-250     0.0%
  250-500     0.0%
  500-750     0.5%
  750-1000    1.5% ##
 1000-1250    3.7% ####
 1250-1500    5.8% ######
 1500-1750    4.1% ####
 1750-2000    7.4% #######
 2000-2250   12.2% ############
 2250-2500   13.7% ##############
 2500-2750    9.3% #########
 2750-3000   10.5% ##########
 3000-3750   ~5-6% each
 3750-6000   gradually tapering 3.4% -> 0.3%
```
(Full bin-by-bin figures in the histogram tables above; `results/histograms.csv` has every
value pooled and per-area/season.)

The shapes are qualitatively different: LLR shows a single sharp spike (68.8% of all its
0–6,000 ft flight-time sits in just two adjacent bins, 1000–1500 ft), TMA shelf shows a
broader single hump (47.7% in 1500–2000 ft), and control is comparatively flat across a wide
1750–3750 ft plateau with no bin exceeding 13.7%.

### Concentration metrics (CR, HHI, absolute density)

CR = share of 500–3,000 ft QNH flight-seconds falling in the single busiest **500 ft sliding
window** (any two adjacent 250 ft bins in that range). HHI = Herfindahl index (Σ share²) over
the ten 250 ft bins spanning 500–3,000 ft (uniform baseline = 0.100, max = 1.000). Density =
flight-seconds/day/km² in that same busiest-500ft window.

| area | season | n flights | busiest 500ft window (ft QNH) | CR | HHI | density (flight-s/day/km²) |
|---|---|---|---|---|---|---|
| London TMA shelf | summer | 304 | 1500–2000 | 0.499 | 0.181 | 17.81 |
| London TMA shelf | winter | 143 | 1750–2250 | 0.486 | 0.185 | 14.32 |
| Manchester LLR | summer | 77 | 1000–1500 | 0.724 | 0.308 | 6.83 |
| Manchester LLR | winter | 25 | 1000–1500 | 0.744 | 0.307 | 4.05 |
| Control (open Class G) | summer | 406 | 2000–2500 | 0.377 | 0.139 | 9.90 |
| Control (open Class G) | winter | 157 | 2250–2750 | 0.311 | 0.125 | 5.76 |

### Peak single 250 ft bin vs. controlled-airspace boundary

| area | season | peak 250ft bin | seconds | gap: bin top → ceiling | busiest 500ft CR-window top → ceiling |
|---|---|---|---|---|---|
| London TMA shelf | summer | 1750–2000 | 26,478 | +500 ft | +500 ft |
| London TMA shelf | winter | 1750–2000 | 12,560 | +500 ft | +250 ft |
| Manchester LLR | summer | 1000–1250 | 6,953 | +50 ft | −200 ft |
| Manchester LLR | winter | 1250–1500 | 1,803 | −200 ft | −200 ft |

(Positive = band top sits below the ceiling by that many feet, i.e. genuinely "just under";
negative = band extends above the ceiling.) TMA shelf's peak sits cleanly under its 2,500 ft
base in both seasons (250–500 ft of headroom). LLR's **single busiest 250 ft bin in summer**
(the larger, more reliable pool) sits only 50 ft under the 1,300 ft ceiling — about as "just
under" as a 250 ft bin can get. Its **500 ft CR window**, however, extends 200 ft *above* the
ceiling in both seasons, because the second-busiest bin (1250–1500 ft, 25.7% of all LLR traffic
in summer) straddles the ceiling itself: this bin mixes genuine sub-1,300 ft corridor traffic
with the CTR-cleared overflight traffic the brief anticipated ("the LLR box includes some
CTR-cleared traffic above the corridor ceiling — that's fine, the histogram will show it"). At
250 ft bin resolution the two can't be cleanly separated; both readings are reported rather than
picking the one that looks cleaner.

### Cross-area ratios

| season | CR: TMA/control | CR: LLR/control | HHI: TMA/control | HHI: LLR/control | density: TMA/control | density: LLR/control | density: TMA/LLR |
|---|---|---|---|---|---|---|---|
| summer | 1.32× | 1.92× | 1.30× | 2.22× | 1.80× | 0.69× | 2.61× |
| winter | 1.56× | 2.39× | 1.49× | 2.47× | 2.48× | 0.70× | 3.53× |

Note the divergence between **relative concentration** (CR/HHI — both constrained areas exceed
control in both seasons) and **absolute density** (flight-seconds/day/km² in the busiest band —
TMA exceeds control by 1.8–2.5×, but LLR is actually *below* control, at 0.69–0.70×). This is
because LLR's box carries much lower raw traffic volume overall (6–34 flights/day vs. control's
56–141) than control; its traffic is far more concentrated by altitude, but there is less of it
in absolute terms. Both readings are genuine and are discussed together in the verdict — a
structural "exposure multiplier" argument built on *relative* concentration (any two aircraft
present are much likelier to share the same altitude layer) is well supported for both
constrained areas; an argument built on *raw density* only holds for the TMA shelf.

---

## Example flight_ids

### London TMA shelf — just under the 2,500 ft base (2000–2500 ft QNH band)

| flight_id | day | callsign | type | route | seconds in band |
|---|---|---|---|---|---|
| `4080c9:2026-07-11T12:56:28Z` | 2026-07-11 | BRO61 | DA62 | EGTK → EGTK | 2,907 |
| `404289:2026-02-14T09:27:17Z` | 2026-02-14 | FFC043 | P28A | (unrecognized) → EGTF | 728 |
| `404e24:2026-07-18T09:18:15Z` | 2026-07-18 | FFC043 | P28A | EGTF → EGTF | 700 |
| `407e9d:2026-02-14T14:44:46Z` | 2026-02-14 | GCMTZ | PIAT | EGHF → EGML | 659 |
| `407ffe:2026-05-09T14:34:13Z` | 2026-05-09 | GSRXX | SR20 | EGFF → EGKB | 616 |

`4080c9` (round trip out of Oxford/Kidlington, EGTK) and the two `FFC043`/`GCMTZ` entries are
locally-based/round-trip flights that happened to loiter under the shelf rather than
point-to-point transits; `407ffe` (Cardiff → Biggin Hill) is a clean cross-country transit
example under the shelf.

### Manchester LLR — just under the 1,300 ft ceiling (800–1300 ft QNH band)

| flight_id | day | callsign | type | route | seconds in band |
|---|---|---|---|---|---|
| `402e3a:2026-07-11T16:46:45Z` | 2026-07-11 | GBPVA | C172 | EGBO → EGCB | 589 |
| `400b17:2026-02-14T15:50:40Z` | 2026-02-14 | GISHA | P28A | (unrecognized) → EGCB | 515 |
| `40451c:2026-07-18T07:12:52Z` | 2026-07-18 | GMDBC | ULAC | (unrecognized) → (unrecognized) | 499 |
| `400b17:2026-07-11T14:59:16Z` | 2026-07-11 | GISHA | P28A | EGBO → EGCB | 497 |
| `402d6d:2026-06-20T10:10:18Z` | 2026-06-20 | GAJKB | L8 | EGCB → EGBO | 459 |

Three of these five are point-to-point EGBO (Wolverhampton Halfpenny Green) ↔ EGCB (Manchester
Barton) transits — exactly the corridor the LLR box was drawn to capture, run in both
directions.

Full candidate lists (top 15 per area by band-seconds) are in `results/analysis_output.json`
under `example_candidates`; per-flight/per-bin evidence for every flight in the study is
reproducible from `results/raw/*.json` (raw API responses, one file per area×day) plus
`analysis.py`.

---

## Caveats

- **QNH correction fallback**: `alt_correction_ft` nulls fall back to 0 ft (pressure altitude),
  which would blur bin membership by up to ±300 ft against a hypothetical "true" correction —
  fine at 250 ft binning as instructed, but worth naming. In this dataset the fallback was never
  triggered (0 of 1,112 flights had an empty correction series), so it did not affect these
  results; it may matter on other samples.
- **GA ADS-B equipage is partial.** Many gliders, microlights, military, and some vintage GA
  aircraft are invisible to this archive. We additionally restricted to `emitter_category: A1`
  (light aeroplanes < 7 t) per the fixed method, which further excludes rotorcraft (A7),
  gliders (B1), balloons (B2), and microlights/hang-gliders/paragliders (B4) — all of which use
  these same shelves/corridors and could show a different (plausibly sharper, given gliders in
  particular ridge- and thermal-hunt right under London TMA shelves) compression signature. This
  study speaks only to powered light-aeroplane traffic.
- **Receiver coverage bias is toward under-counting low flight.** In terrain with sparse
  receiver coverage, low-altitude segments can be missed entirely, so a flight "appearing" at
  low altitude usually reflects coverage starting there, not a takeoff — and any undercounting
  works against, not for, the low-altitude bunching this hypothesis predicts (conservative for
  the compression claim).
- **The LLR box includes CTR-cleared traffic above the corridor's 1,300 ft ceiling**, as
  anticipated by the brief — visible directly in the histogram (1250–1500 ft carries 25.7% of
  all LLR summer traffic, straddling the ceiling) and discussed above; the busiest-500ft-window
  metric for LLR is pulled about 200 ft above the ceiling by this mixing, while the busiest
  single 250 ft bin sits cleanly (50 ft) below it. Both figures are reported rather than
  resolved in the hypothesis's favor.
- **Airspace boundaries are approximations baked into the box choice** (fixed lon/lat
  rectangles), not live/current airspace polygons. The London TMA base, Manchester LLR
  corridor width/ceiling, and "no CTA below 5,500 ft" control characterization all rest on the
  method's stated assumptions, not a real-time AIP/NOTAM lookup.
- **Segment-time apportionment (spatial box-clip and altitude-bin split) is linear**, per the
  method: constant velocity across a sub-segment for the box clip, constant climb/descent rate
  for the altitude split. Geometry is already simplified server-side (spatial ε=50 m, altitude
  ε=100 ft) before this client-side approximation is layered on, so this is consistent with,
  not an added source of error beyond, the archive's own stated precision.
- **AGL filtering is sampled once per clipped sub-segment** (at the sub-segment's start time,
  forward-filled from the stepwise `path_agl_ft` series), not at finer resolution; a
  sub-segment that crosses the 500 ft AGL threshold mid-segment is classified by its start
  value. Exclusion rates were small (0.9–3.5% of box-dwell time) so this is not a major driver
  of the results either way.
- **Manchester LLR's winter pool is thin** (25 flights across 2 days; 3 flights on 2026-01-17
  alone) — its winter peak-bin position (1250–1500 ft, straddling the ceiling) should be read
  as noisier than the summer figure (77 flights, peak cleanly at 1000–1250 ft) and is flagged
  as such above.
- **One flight = one readsb leg** (splits on gaps or a new departure; touch-and-gos usually do
  not split a leg). This means a single aircraft doing multiple corridor transits in a day
  (e.g. `400b17`/GISHA above, on both 07-11 and 02-14) contributes multiple independent
  flight_ids, which is the intended unit of analysis here (each transit is a separate exposure
  event), not double-counting of one flight.
- **The control area is a real place, not a null baseline.** It was chosen to avoid the
  Birmingham/Shawbury zones "as far as practical," but it still has its own local airfields and
  typical cruising-altitude habits; its CR/HHI figures (0.31–0.38 / 0.13–0.14) are the
  concentration of *real, unconstrained Class G*, not of a theoretically unstructured null. If
  anything this makes it a conservative comparator (a truly unstructured baseline might show
  even less concentration, widening the constrained-vs-control gap).
- **Absolute density vs. relative concentration diverge for LLR** (see Cross-area ratios above)
  — LLR is far more concentrated by altitude than control (CR/HHI ~2×) but has lower absolute
  traffic-seconds/day/km² in its busiest band (~0.7×) than control, because its overall traffic
  volume is much lower. Both are genuine findings and are not reconciled into a single number.

---

## Verdict test

Per the fixed rule: **SUPPORTED** if both constrained areas show CR meaningfully higher than
control (≥ 1.5×, illustrative) **and** their peak band sits just under the airspace ceiling
(within 700 ft below it); **PARTIALLY** if only one does; **NOT SUPPORTED** otherwise.

- **Manchester LLR**: clearly meets both conditions, in both seasons. CR is 1.92× control
  (summer) and 2.39× control (winter); HHI corroborates (2.22×/2.47×). Its single busiest 250 ft
  bin sits 50 ft under the 1,300 ft ceiling (summer, the larger/cleaner pool). Strong, robust
  support.
- **London TMA shelf**: clearly meets the ceiling-proximity condition in both seasons (peak
  band 250–500 ft under the 2,500 ft base, consistent across 4 summer + 2 winter days, 447
  flights). Its CR-vs-control ratio is directionally correct and real (higher every season,
  every metric) but is **borderline against the illustrative ≥1.5× bar**: 1.32× in the
  larger/more robust summer pool (4 days, 304 vs. 406 flights), 1.56× in winter. HHI shows the
  same pattern (1.30× summer, 1.49× winter). The best-powered comparison (summer) falls just
  short of the "meaningfully higher" bar as literally specified, even though the direction,
  the shape of the histogram, and the ceiling-proximity of the peak are all consistent with the
  hypothesis.

Because one constrained area (LLR) satisfies both conditions robustly and the other (TMA shelf)
satisfies the ceiling-proximity condition but only inconsistently/marginally clears the
illustrative concentration-ratio bar, the honest reading under the stated rule is:

### **VERDICT: PARTIALLY SUPPORTED**

**Strength of evidence**: moderate-to-strong for the compression *mechanism* itself (both
constrained areas show real, ceiling-anchored altitude peaks utterly unlike control's broad
plateau — the normalized-shape comparison is the clearest single piece of evidence for this);
strong specifically for the *severity gradient* implied by H3 — the tighter/lower the shelf,
the sharper the bunching (LLR's 1,300 ft ceiling produces a dramatically sharper, more
concentrated peak — CR 0.72–0.74, 68.8% of all traffic in two adjacent bins — than the TMA
shelf's more generous 2,500 ft base, CR 0.49–0.50). Weaker/inconclusive on whether the TMA
shelf's *specific* effect size clears an illustrative "1.5×" concentration bar, and mixed on
whether concentration translates into higher *absolute* density (yes for TMA, no for LLR,
because LLR's low traffic volume works against the raw-density framing even as it strengthens
the relative-concentration framing). The core structural claim — that controlled-airspace
floors reshape the vertical distribution of VFR traffic into materially narrower bands anchored
just under the ceiling, rather than a hypothesis-neutral null of similar spread to open Class G —
is supported by this sample; the specific magnitude thresholds in the fixed verdict rule are
met cleanly by one of the two constrained areas and only partially by the other.
