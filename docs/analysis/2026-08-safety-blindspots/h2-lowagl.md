# H2 — En-route low-AGL exposure over UK terrain: is the risk picture airfield-centric in the wrong way?

**Verdict: PARTIALLY SUPPORTED — but the mechanism is the opposite of the one proposed.**
Strength of evidence: moderate-to-strong for the negative parts, moderate for the positive parts.

---

## 1. Hypothesis as posed

> "A substantial share of fixed-wing GA low-height exposure (< 700 ft AGL) happens EN-ROUTE
> over terrain, far from any airfield — concentrated in specific valley corridors — whereas
> the safety system's low-flying risk picture is airfield-centric (circuits, approach,
> departure). CFIT/wire-strike exposure therefore concentrates where nobody is measuring."

Three separable claims:

| # | Claim | Result |
|---|---|---|
| C1 | A *substantial share* of fixed-wing GA low-AGL exposure is en-route, ≥ 8 km from any airfield | **NOT SUPPORTED** for civil GA: **4.7 %** of low-AGL minutes (2.2 % at 500 ft, 10.9 % at 1000 ft) |
| C2 | That exposure is *concentrated in specific valley corridors* | **SUPPORTED** — strongly, and the corridors are nameable and stable across 15 months |
| C3 | It sits *where nobody is measuring* | **NOT SUPPORTED** — the dominant en-route low corridors are the published UK military low-flying routes, the most intensively managed low-flying airspace in the country |

The headline surprise is that **the en-route low-level picture over UK uplands is not a GA
picture at all**: 90 % of fixed-wing en-route low-AGL minutes below 700 ft come from
state-operated trainers (RAF Texan T.1 / Phenom T.1 / Prefect T.1), which the premise
assumed would be invisible to ADS-B. They are not — they transmit, and they dominate.

---

## 2. Method

### 2.1 Study areas (four upland boxes, no overlap)

| key | label | bbox (W,S,E,N) | area |
|---|---|---|---|
| `W1_Snowdonia` | Snowdonia / NW Wales | −4.85, 52.60, −3.20, 53.45 | 10 578 km² |
| `W2_MidWales` | Mid Wales / Cambrian / Brecon | −4.60, 51.70, −2.90, 52.60 | 11 703 km² |
| `LK_LakeDist` | Lake District / N Pennines | −3.70, 54.20, −2.30, 54.90 | 7 003 km² |
| `SC_Highlands` | Scottish Highlands (Great Glen / Lochaber / Cairngorms W) | −6.20, 56.30, −3.40, 57.70 | 26 492 km² |

Total 55 777 km².

### 2.2 Sampling

12 whole weeks (84 sampled days), all four boxes = **48 box-weeks**:
2026-04-11, 2026-04-25, 2026-05-09, 2026-05-23, 2026-06-06, 2026-06-13, 2026-06-27,
2026-07-11, 2026-07-25; plus 2025-05-24, 2025-06-14, 2025-07-12 (each a 7-day window
starting on the date given).

Whole weeks rather than hand-picked "good VFR days" — this avoids cherry-picking; poor-weather
days simply contribute few flights. Result: **4 561 unique flights, 663 715 path segments.**

### 2.3 Exact query used (repeated per box × week)

```json
{
  "start_from": "2026-06-13",
  "end_date": "2026-06-20",
  "window_days": 7,
  "include_path": true,
  "limit": 400,
  "match": {
    "trajectory_intersects": {
      "geometry": {"type": "Polygon", "coordinates": [[[-4.85,52.60],[-3.20,52.60],[-3.20,53.45],[-4.85,53.45],[-4.85,52.60]]]},
      "agl_max_ft": 700
    }
  }
}
```

Paged on `cursor` until null. **No `emitter_category` filter was applied at query time** —
categories are classified locally, so rotorcraft (A7) and everything else come along for free
in one call instead of three.

Traffic denominator (12 extra calls, `include_path:false`, 3 matched weeks × 4 boxes):

```json
{"start_from":"2026-06-13","end_date":"2026-06-20","window_days":7,"include_path":false,"limit":10000,
 "match":{"and":[{"trajectory_intersects":{"geometry":"<box polygon>"}},{"emitter_category":["A1","A2"]}]}}
```

Total API calls used: **≈ 70** (2 validation + 4 volume probes + 48 box-week fetches + 12
denominators + 2 spot-checks + 2 pagination extras). Budget was 250.

### 2.4 Per-vertex processing

* `path.coordinates` / `timestamps` give vertices; `path_agl_ft`, `path_gs`,
  `alt_correction_ft` are sparse **stepwise** series — flattened to a global time-sorted
  series and looked up with a step (hold-last) interpolation at each vertex time.
* Elementary segment = consecutive vertex pair; duration capped at 180 s (p95 raw gap is
  5.5 s, so the cap almost never binds); AGL/GS taken as the held value at the segment start.
* **Segments are clipped to the study box** (queries return the whole leg, which frequently
  extends far outside — an uncorrected version of this analysis would count low flying
  anywhere in Europe).
* Derived MSL = `path Z + alt_correction_ft`; derived terrain = MSL − AGL (indicative only,
  ±200 ft — see caveats). Server-supplied AGL is used for all thresholds.

### 2.5 Airfield set and classification

* OurAirports (downloaded 2026-08-01), `iso_country ∈ {GB, IE, IM, JE, GG}`,
  types `small_airport, medium_airport, large_airport, seaplane_base, closed`
  = **1 575 sites**. Heliports excluded from the primary definition (irrelevant to
  fixed-wing circuit/approach exposure) and tested as a sensitivity.
* **Plus 45 data-implied strips**: clusters of flight endpoints at < 250 ft AGL, ≥ 2 distinct
  `icao24`, > 2 km from any listed site. This catches farm strips missing from OurAirports and
  makes the "en-route" class *harder* to enter, i.e. conservative against the hypothesis.
* Segment classed **airfield-proximate** if its midpoint is < 8 km from any such site, else
  **en-route**.
* A low run (maximal chain of low segments, merged across ≤ 30 s excursions above threshold)
  only counts as en-route exposure if **median GS > 80 kt OR run length > 5 km** — this strips
  hovering/orbiting. Runs failing it are reported separately as `slow/short`.
* **Interior**: run starts > 120 s after and ends > 120 s before the observed leg's own
  endpoints. **Bracketed** (strongest class): the aircraft was observed ≥ 1500 ft AGL both
  *before and after* the low run within the same leg — it demonstrably descended into low
  level and climbed back out, so the low reading cannot be coverage onset.

### 2.6 Aircraft grouping (this turned out to be the crux)

| group | rule | n flights |
|---|---|---|
| `civ_ga` | A1/A2, civil registration | 1 367 |
| `mil_state` | A1/A2 with UK military serial `^[XZ][A-Z]\d{3}$` (ZM3xx Texan T.1, ZM5xx Phenom T.1, ZM3xx Prefect T.1, XE685 Hunter) **or** type `G115` (RAF Grob Tutor, civil-registered but Babcock/UAS-operated — confirmed by `UAQ/UAJ/UAX` University Air Squadron callsigns) | 1 133 |
| `rotorcraft` | A7 | 1 977 |
| `other` | A3/A4/A5/B*/unknown (incl. A400M) | 310 |

---

## 3. Results

### 3.1 Headline — low-AGL flight-minutes inside the study areas, 700 ft threshold

| group | total min | airfield-proximate | **en-route** | slow/short | **en-route %** | of which interior | of which bracketed | flights prox | flights en-route | flights bracketed |
|---|---|---|---|---|---|---|---|---|---|---|
| **civ_ga** | 1 999.8 | 1 820.1 | **94.9** | 84.8 | **4.7 %** | 65.7 | 41.3 | 1 136 | 82 | 37 |
| mil_state | 4 394.0 | 3 510.6 | 881.6 | 1.8 | 20.1 % | 437.8 | 240.6 | 902 | 386 | 142 |
| rotorcraft | 9 092.3 | 6 426.0 | 1 811.7 | 854.6 | 19.9 % | 1 030.3 | 258.2 | 1 367 | 624 | 82 |
| other | 688.4 | 454.8 | 197.7 | 35.9 | 28.7 % | 88.3 | 27.3 | 160 | 95 | 18 |

**Headline number for the hypothesis as posed (civil fixed-wing GA): 4.7 % en-route.**

All fixed-wing A1/A2 combined (civil + state): **15.3 % en-route**, but **only 9.7 % of those
en-route minutes are civil**.

### 3.2 Sensitivity to the AGL threshold

| threshold | civ_ga en-route % | mil_state | rotorcraft | all fixed-wing A1/A2 | civil share of fixed-wing en-route |
|---|---|---|---|---|---|
| **500 ft** | **2.2 %** (27.7 / 1 281 min) | 21.1 % | 13.9 % | 15.1 % | 4.5 % |
| **700 ft** | **4.7 %** (94.9 / 2 000 min) | 20.1 % | 19.9 % | 15.3 % | 9.7 % |
| **1000 ft** | **10.9 %** (441 / 4 051 min) | 15.3 % | 27.3 % | 13.8 % | 26.5 % |

The civil fraction *falls* as the threshold tightens: the lower you look, the more exclusively
airfield-related civil GA low flying becomes. The military fraction is flat-to-rising. This is
the opposite of what C1 predicts.

### 3.3 Sensitivity to the airfield definition (700 ft)

| airfield definition | civ_ga | mil_state | rotorcraft |
|---|---|---|---|
| airports + closed + implied strips, 8 km (**primary**) | 4.75 % | 20.06 % | 19.93 % |
| + heliports, 8 km | 4.20 % | 19.25 % | 17.98 % |
| airports only (drop `closed`), 8 km | 5.08 % | 20.25 % | 20.18 % |
| drop the 45 data-implied strips, 8 km | 5.58 % | 28.67 % | 31.87 % |
| radius 5 km | 6.99 % | 26.13 % | 30.83 % |
| radius 15 km | 0.71 % | 4.57 % | 4.68 % |

Civil GA never exceeds 7 % under any reasonable definition. Note the implied-strip correction
matters a lot for rotorcraft (31.9 % → 19.9 %): private helipads are systematically missing
from OurAirports.

### 3.4 The area normaliser — exposure density

Only **24.0 %** of the 55 777 km² of study terrain lies within 8 km of an airfield
(W1 29.6 %, W2 21.6 %, LK 32.8 %, SC 19.0 %), yet it carries 91 % of civil GA low-AGL minutes:

| group | proximate min / 1000 km² | en-route min / 1000 km² | concentration ratio |
|---|---|---|---|
| civ_ga | 135.8 | 2.24 | **60.6 ×** |
| mil_state | 262.0 | 20.8 | 12.6 × |
| rotorcraft | 479.5 | 42.8 | 11.2 × |

Civil GA low flying is ~60× denser near airfields than away from them. An airfield-centric
risk model is a *good* model of civil GA low-height exposure.

### 3.5 En-route ≠ transit: local-manoeuvring split

Distance from the low run to the flight's own start/end points (< 15 km = local
manoeuvring area, e.g. practice-forced-landing / general-handling training):

| group | transit (≥ 15 km from own endpoints) | local manoeuvring area |
|---|---|---|
| civ_ga | 50.4 min (48 flights) | 44.5 min (38 flights) |
| mil_state | 814.5 min (353 flights) | 67.1 min (65 flights) |
| rotorcraft | 814.4 min (287 flights) | 997.3 min (400 flights) |

**Roughly half of civil GA's already-small en-route exposure is not transiting at all** — it
is local-area manoeuvring 8–15 km from the home field (the signature of PFL / general handling
practice). True cross-country valley transiting below 700 ft amounts to **50 minutes across
84 sampled days over 56 000 km² of upland**.

### 3.6 Share of traffic (3 matched weeks, all four boxes)

| quantity | value |
|---|---|
| A1/A2 flights crossing the study areas at any altitude | **7 559** |
| …of which civil GA descending < 700 ft AGL anywhere in box | 395 (5.2 %) |
| …of which state trainers descending < 700 ft AGL in box | 311 (4.1 %) |
| civil GA flights with *qualifying en-route* low exposure | **29 (0.38 % of all fixed-wing traffic; 7.3 % of the low-flying civil cohort)** |
| state trainers with qualifying en-route low exposure | 128 (41 % of their low-flying cohort) |

### 3.7 Corridors — where the en-route low flying actually is

Connected-component clustering of 0.05° cells (≥ 0.5 min each), 700 ft, over all 84 sampled days.

**Fixed-wing, state trainers (`mil_state`) — 77.6 % of their en-route minutes in the top 3:**

| rank | corridor | min | flights | active days | median AGL | 10th-pct AGL | terrain | dominant types |
|---|---|---|---|---|---|---|---|---|
| 1 | **Upper Wye valley — Builth Wells ↔ Rhayader** (52.27, −3.43) | 344.5 | 116 | 41 / 84 | 386 ft | 237 ft | ~840 ft | TEX2, E50P |
| 2 | **Conwy valley — Llanrwst ↔ Betws-y-Coed ↔ Llangollen/Berwyn** (53.12, −3.68) | 290.7 | 184 | 47 / 84 | 423 ft | 257 ft | ~900 ft | TEX2, E50P |
| 3 | **Caernarfon / Menai Strait** (53.02, −4.48) | 49.0 | 55 | 30 / 84 | 445 ft | 293 ft | ~0 ft (coastal) | TEX2, E50P |
| 4 | Kirkstone Pass / Ullswater (54.52, −2.94) | 37.5 | 29 | 19 / 84 | 539 ft | 290 ft | ~860 ft | E50P, G12T, G115 |
| 5 | Brecon Beacons / Llanwrtyd (51.99, −3.42) | 20.4 | 11 | 9 / 84 | 409 ft | 264 ft | ~830 ft | TEX2, E50P |
| 6 | Black Mountain / Devil's Bridge (51.99, −4.23) | 17.4 | 12 | 9 / 84 | 435 ft | 267 ft | ~550 ft | TEX2, E50P |

Corridors 1, 2, 5 and 6 lie inside the published UK Military Low Flying System area over
Wales (LFA 7); corridor 4 is the Lake District low-flying route. (Geographic identification is
mine, from coordinates — it is not a field in the data.) These are the routes the MOD
publishes, books, deconflicts and counts. **This is the single most-measured low-flying
activity in the UK, not a blindspot.**

**Fixed-wing, civil GA (`civ_ga`) — 48.3 % of their en-route minutes in the top 3:**

| rank | corridor | min | flights | active days | median AGL | 10th-pct AGL | types |
|---|---|---|---|---|---|---|---|
| 1 | **Strathtay / Loch Tay E — Aberfeldy ↔ Dunkeld** (56.47, −3.54) | 26.8 | 20 | 17 / 84 | 439 ft | 195 ft | P28R, P28A, SIRA, C152 |
| 2 | **Vale of Clwyd / Clwydian range** (53.16, −3.25) | 12.5 | 10 | 9 / 84 | 617 ft | 261 ft | SKRA, P68, HUSK |
| 3 | **Upper Wye valley (Builth)** (52.27, −3.27) | 6.5 | 3 | 2 / 84 | 632 ft | 483 ft | C172 |
| 4 | Loch Ness NE / Strathglass–Beauly (57.45, −4.38) | 4.3 | 4 | 3 / 84 | 549 ft | 334 ft | DA62, P28A |
| 5 | Black Mountains / Crickhowell (51.81, −3.17) | 2.6 | 4 | 4 / 84 | 450 ft | −318 ft¹ | BE20, RV12, ECHO |

¹ negative value = DEM/QNH artifact, see caveats.

Civil corridor 1 is dominated by **one aircraft**, G-EPTR (Piper Arrow, Perth/Scone EGPT),
which contributes 17 of the 56 civil en-route runs across 8 separate days — repeated
local-area low work, ~8–15 km from its home field, not a corridor phenomenon.

**Rotorcraft (context only — excluded from the GA claim, different risk model):**

| rank | corridor | min | flights | days | median AGL | dominant types |
|---|---|---|---|---|---|---|
| 1 | Caernarfon / Menai Strait / Anglesey (53.13, −4.54) | 548.1 | 104 | 61 / 84 | 445 ft | A139, S92, EC45 |
| 2 | Nant Ffrancon–Ogwen / Conwy valley (53.30, −4.00) | 215.4 | 82 | 45 / 84 | 381 ft | EC35, EC45, A139 |
| 3 | Brecon Beacons / Black Mountains (51.85, −3.38) | 203.2 | 72 | 38 / 84 | 469 ft | A139, R44, EC45 |
| 4 | Inverness / Loch Ness NE (57.34, −4.25) | 183.3 | 91 | 50 / 84 | 521 ft | A189, A149, EC45 |
| 5 | Thirlmere / Kirkstone Pass (54.51, −2.96) | 107.2 | 22 | 17 / 84 | 286 ft | A149, A189, EC35 |

Rotorcraft carry **1 812 en-route low-AGL minutes — nearly twice all fixed-wing types
combined (976)** — and the type mix (AW139, S-92, H145/EC45, H135/EC35, AW189, AW149) is
overwhelmingly SAR and HEMS. If there is an under-measured mountain low-flying population in
this dataset, it is rotary, not fixed-wing.

### 3.8 Deliberate low-level activity vs transiting GA

Within the 56 civil en-route runs, a large share is *purposeful* low flying rather than a
transit choice:

* **G-RVNR** (Partenavia P-68 Observer, Liverpool EGGP-based, 2.3–3.4 h legs, EGGP→EGPT):
  the classic UK survey / pipeline-patrol airframe. 4 en-route runs.
* **G-CBME** (Cessna 172, legs of 4.4 h and 6.4 h): duration is diagnostic of aerial work,
  not touring. 15 en-route runs — the second-highest of any registration.
* **G-SHMB** (Let L-39 Albatros jet warbird, Blackpool EGNH, 45–77 min local sorties):
  5 en-route runs in the Lake District. Deliberate low-level display/experience flying.
* **G-EPTR** (Piper Arrow, Perth): 17 runs, all 8–21 km from EGPT — training manoeuvres.

Genuine long-range transiting GA that chose to fly a valley low is a small residue —
best exemplified by the flights listed in §4.

---

## 4. Evidence — concrete flight_ids

Full machine-readable list of all 2 131 qualifying en-route runs:
`results/h2-enroute-runs.csv` (columns include `flight_id, grp, type, reg, minutes, km,
agl_med, agl_min, gs_med, interior, bracketed, lat, lon, d_own`).
Aggregates: `results/h2-summary.json`.

### (a) Civil GA valley transits below 500 ft AGL, en-route, interior **and** bracketed

| flight_id | type / reg | run | median / min AGL | dist. from own endpoints | where |
|---|---|---|---|---|---|
| `407edf:2026-06-29T15:52:53Z` | unknown, callsign **GOBLR** → EGBJ | 2.67 min / 11.3 km | 612 / **466 ft** | 59.8 km | Upper Wye valley, Builth |
| `407f8f:2025-06-18T13:15:57Z` | SKRA / **G-CMNL** (Best Off Sky Ranger) | 2.41 min / 7.4 km | 251 / **154 ft** | 110.3 km | Berwyn → Clwydian range |
| `402f2f:2026-06-17T10:56:11Z` | P28A / **G-XAVI** | 2.01 min / 6.1 km | 581 / **237 ft** | 41.5 km | Bala lake E / Dee headwaters |
| `4031ce:2026-07-25T14:53:57Z` | P28A / **G-BSLT** | 3.18 min / 6.4 km | 475 / **246 ft** | 12.2 km | Loch Tay E / Kenmore |
| `403faf:2025-07-18T12:01:35Z` | P28R / **G-EPTR** | 1.96 min / 5.3 km | 271 / **108 ft** | 11.5 km | Strathtay |
| `4046d6:2026-07-15T12:43:52Z` | C172 / **G-CBME** | 1.32 min / 2.7 km | 614 / 483 ft | 27.4 km | Colwyn Bay / N Wales coast |

`407edf` is the cleanest single case: a 64-minute leg into Gloucestershire (EGBJ) that cruised
at 2 500–2 900 ft AGL, descended into the Wye valley at t+30.8 min, ran 11 km at
466–612 ft AGL over terrain of ~500–650 ft, then climbed back to 800–1 200 ft AGL and
continued. Not coverage onset — it is bracketed by high-altitude observation on both sides.

`407f8f` (G-CMNL) is a 126-minute microlight cross-country from South Wales to Lancashire; the
server's own `path_agl_ft` minimum (verified independently via `GET /flights/407f8f:2025-06-18T13:15:57Z`)
is **154.2 ft**, reached crossing the Clwydian ridge at 53.154, −3.254.

### (b) Ridge crossings with minimal clearance (AGL < 600 ft over terrain > 1 200 ft)

98 civil GA flights and 347 state-trainer flights had at least one such segment. Civil examples:

| flight_id | type / reg | AGL | derived terrain | position | feature |
|---|---|---|---|---|---|
| `3d29e0:2025-06-20T08:30:47Z` | P28A / D-EOCM | 380 ft | ~2 998 ft | 56.333, −4.239 | Crianlarich / Glen Falloch |
| `402aa0:2025-07-12T10:06:03Z` | P28A / G-BODD | 397 ft | ~3 652 ft | 56.543, −4.213 | Glen Lyon / Loch Tay |
| `401b48:2026-05-25T14:51:11Z` | PA18 / G-PIPR | 584 ft | ~2 233 ft | 54.247, −2.463 | Howgill Fells / Lune gorge |
| `4078b9:2026-04-13T08:49:53Z` | L39 / G-SHMB | 580 ft | ~1 422 ft | 54.274, −3.320 | Eskdale / Ravenglass |
| `40296f:2025-06-19T15:29:49Z` | P28A / G-OZJX | 513 ft | ~1 380 ft | 54.514, −2.910 | Kirkstone Pass |
| `400a75:2025-07-12T12:49:03Z` | BE20 / G-RAFK | 396 ft | ~1 516 ft | 57.481, −5.364 | Loch Alsh / Kyle |

### (c) The corridors that actually dominate (state trainers)

`ZM3xx` Texan T.1 examples are abundant in `h2-enroute-runs.csv`; the Conwy-valley cluster
alone has 184 flights on 47 of 84 sampled days, median 423 ft AGL, 10th percentile 257 ft.

---

## 5. Caveats — read before quoting any number

1. **Receiver-coverage floor biases *against* the hypothesis-supporting direction.** In remote
   terrain, low segments are the first thing lost. Every en-route low number here is a
   **lower bound**; the airfield-proximate share is correspondingly an upper bound. A stronger
   receiver network would move the fraction up, not down. How far is unknown — but note that
   the state trainers *are* being seen at 250–400 ft AGL in exactly the valleys where
   coverage is worst, which suggests the floor is not catastrophic in these corridors.
2. **Coverage onset masquerading as low flying** is handled by the *interior* and *bracketed*
   tests. Only 43 % of civil en-route minutes (41.3 / 94.9) survive the bracketed test.
   Where the report makes a strong claim about a specific flight, that flight is bracketed.
3. **90 m DEM error in steep terrain is ±100–200 ft**, and the derived terrain elevation used
   for the "ridge crossing" table is MSL−AGL where MSL itself is reconstructed from
   ε=100 ft-compressed pressure altitude plus a coarse QNH correction — call it ±200 ft.
   Treat individual clearance figures as indicative; 0.17 % of segments returned physically
   impossible AGL (< −50 ft), which is the visible tail of that error. The negative
   10th-percentile AGL in civil corridor 5 is such an artifact.
4. **ADS-B carriage bias.** Gliders, most hang-gliders/paragliders, many microlights and some
   vintage GA are invisible. Glider ridge-soaring and hill-soaring are *the* classic UK
   low-level-over-terrain activities and are essentially absent from this dataset. Absence of
   data ≠ absence of traffic — this is the largest unquantified gap in the analysis and it
   cuts *for* the hypothesis.
5. **The military premise in the task brief is wrong for this dataset.** UK state trainers
   (Texan T.1, Phenom T.1, Prefect T.1, Grob Tutor) transmit ADS-B and appear throughout.
   Fast-jet low flying (Typhoon, F-35, Hawk) is still largely absent, so the true military
   en-route low-level total is *understated* here, which strengthens the C3 rebuttal.
6. **Denominator sensitivity.** The airfield-proximate bucket is inflated by circuit training:
   an hour of circuits accrues ~50 low-AGL minutes, whereas a valley transit accrues 2–3. A
   minutes-weighted comparison therefore structurally favours the airfield class. This is why
   §3.4 (area-normalised density, 60×) and §3.6 (share of flights, 0.38 %) are given — both
   are free of that artifact and both point the same way.
7. **OurAirports is incomplete for UK farm strips**, which would inflate "en-route". The 45
   data-implied strips partially fix this; §3.3 shows the effect is ~0.8 pp for civil GA.
8. **Coastal low flying is not valley low flying.** Two of the top corridors (Caernarfon/Menai
   for both trainers and rotorcraft) are over water/coast, where the DEM is ~0 and "AGL"
   means height above sea. These are real low flights but not CFIT-relevant in the
   terrain sense.
9. Four boxes over UK uplands only; 84 sampled days concentrated in spring/summer. Nothing
   here generalises to winter, to lowland GA, or outside the UK.

---

## 6. Verdict

**PARTIALLY SUPPORTED.**

* **C2 (corridor concentration) — SUPPORTED, strongly.** En-route low-AGL exposure over UK
  uplands is emphatically not diffuse. 77.6 % of state-trainer en-route minutes fall in three
  nameable corridors (Upper Wye, Conwy valley, Caernarfon/Menai); 48.3 % of the much smaller
  civil total falls in three (Strathtay, Vale of Clwyd, Upper Wye). The corridor structure is
  stable across 15 months and repeats on 40–47 of 84 sampled days. The per-vertex AGL data
  does exactly what the hypothesis hoped it would: it makes valley-following visible in a way
  barometric altitude cannot.
* **C1 (substantial share for GA) — NOT SUPPORTED.** Civil fixed-wing GA puts 4.7 % of its
  sub-700 ft minutes ≥ 8 km from an airfield (2.2 % at 500 ft), on 24 % of the land area,
  at a 60× lower density than near airfields, and roughly half of that residue is local-area
  training manoeuvring rather than transiting. Only 0.38 % of fixed-wing traffic crossing
  these mountains generates any qualifying en-route low exposure at all. No plausible
  variation of the airfield definition takes civil GA above 7 %.
* **C3 (nobody is measuring) — NOT SUPPORTED, and inverted.** The en-route low-level corridors
  that dominate the data are the published military low-flying routes over Wales and the Lake
  District — booked, deconflicted and counted by the MOD. Where the exposure is, measurement
  already is.

**The genuinely under-appreciated finding is a different one:** rotorcraft — overwhelmingly
HEMS and SAR (AW139, S-92, H145, H135, AW189, AW149) — accumulate **1 812 en-route low-AGL
minutes, ~1.9× all fixed-wing types combined**, in a distinct corridor set (Menai/Anglesey,
Ogwen–Conwy, Brecon Beacons, Loch Ness, Thirlmere–Kirkstone) with median AGL as low as 286 ft.
That population flies low over terrain by operational necessity, at night and in marginal
weather, and it is the one the data says carries the most en-route low-height exposure over
British mountains. Redirecting the hypothesis at rotary-wing HEMS/SAR would be the productive
next step.
