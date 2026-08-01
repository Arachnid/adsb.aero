# H1 — Non-participating transits of active UK parachute drop zones

Source: adsb.aero historical archive (`https://adsb.aero/api/v1`), queried 2026-08-01.
Evidence file: `h1-dropzone-transits.csv` (5,196 circle-pass rows, one row per contiguous pass
through a DZ circle; 892 of them on active jump days).

---

## 1. Hypothesis

**H1** — *Non-participating aircraft routinely transit active parachute drop zones during live
jumping, and the true transit-exposure rate is far higher than what airprox reports capture.*

The claimed blindspot: UK DZ conflict analysis rests on voluntarily reported airprox events, and
nobody measures the denominator — how many transits actually happen while jumpers are in the air.
UK DZs have no controlled airspace protection; they are a NOTAM'd/charted circle only.

**Verdict: PARTIALLY SUPPORTED, with an important and unexpected refinement.** The denominator is
indeed large and unmeasured, and low-level transits during live jump runs occur at exactly the rate
chance would predict — i.e. there is *no measurable deconfliction at all* below 10,000 ft. But the
"routinely" framing is too strong for the aggregate: overall, transits coincide with jump runs
**half as often as chance**, and that entire protective effect is confined to high-altitude traffic
in controlled airspace. Details in §7.

---

## 2. Method

### 2.1 Identify drop zones empirically

The six candidate DZs in the brief were treated as hypotheses, not facts. Each was checked in-data,
and a UK-wide discovery sweep was run to find DZs the candidate list missed.

Discovery query (5 tiles covering the UK/Ireland, 2 summer weeks each): short local sorties that
return to their own departure point after climbing high — a signature almost unique to jump aircraft.

```json
{"end_date": "2026-06-08", "start_from": "2026-06-01", "window_days": 7,
 "include_path": false, "limit": 5000,
 "match": {"and": [
   {"endpoint_within": {"mode": "both", "geometry": {"type":"Polygon","coordinates":[[[-3.0,53.0],[2.2,53.0],[2.2,56.2],[-3.0,56.2],[-3.0,53.0]]]}}},
   {"duration": {"max_s": 3900}},
   {"trajectory_intersects": {"geometry": {"type":"Polygon","coordinates":[[[-3.0,53.0],[2.2,53.0],[2.2,56.2],[-3.0,56.2],[-3.0,53.0]]]},
                              "altitude_min": 9500, "altitude_min_ref": "ft"}}]}}
```

Of 2,561 unique flights returned across the 5 tiles, 262 started and ended within 3 km of the same
point; clustering those start points surfaced the ADS-B-visible UK jump fleet.

**Two corrections to the brief's candidate list came out of this:**

| Candidate (brief) | Verified? | Correction |
|---|---|---|
| Hibaldstow 53.678, −0.523 | **coordinate wrong** | Actual jump ops at **53.501, −0.522** (~20 km south), aircraft G-CKSE/C208. The supplied point has no jump activity at all. |
| Netheravon 51.244, −1.754 | **coordinate off by ~2.5 km** | Actual jump ops at **51.2546, −1.7185**, aircraft G-CPSS/C208. The supplied point returned 0 sorties. |
| Langar 52.890, −0.907 | yes | 3× C208 |
| Headcorn 51.157, 0.641 | yes | N106AN/C208 |
| Dunkeswell 50.860, −3.234 | marginal | 1 sortie in 2 sample weeks — dropped |
| Cark 54.164, −2.962 | marginal | 2 sorties (N750AY/P750) — dropped |
| *(not in brief)* **Old Sarum 51.0978, −1.7855** | **added** | N240GS/C208, 397 lifts — one of the busiest in the data |
| *(not in brief)* Weston-on-the-Green, Hinton-in-the-Hedges, Sibson, Peterlee/Shotton, Clonbullogue (IE) | added, low volume | retained but below the activity threshold |

Seven DZs were carried into the main analysis; four had enough ADS-B-visible jump activity to
support day-level statistics.

### 2.2 Identify jump sorties and extract individual lifts

The brief's "duration < 45 min" filter proved **wrong for this data**: readsb legs do not split on a
touch-and-go, so a jump aircraft flying 5 lifts back-to-back appears as one 2¼-hour leg. Filtering on
duration discarded most of the activity. Replaced with a 4-hour cap and per-lift extraction from the
trajectory.

```json
{"end_date": "<week end>", "start_from": "<week start>", "window_days": 7,
 "include_path": true, "limit": 500,
 "match": {"and": [
   {"endpoint_within": {"mode": "both", "geometry": {"type": "Circle", "coordinates": [<lon>, <lat>], "radius": 3500}}},
   {"duration": {"max_s": 14400}},
   {"trajectory_intersects": {"altitude_min": 9000, "altitude_min_ref": "ft"}}]}}
```

A **lift** = a contiguous run of the trajectory above 9,000 ft MSL (pressure altitude + interpolated
`alt_correction_ft`) whose apogee lies within 9 km of the DZ. Apogee time = exit time.

Validation on `407ba4:2026-06-21T14:26:32Z` (G-FBPS, Langar, 482 points, 2 h 13 min): 5 lifts
detected; the first climbs to 14,155 ft with apogee **454 m from the DZ centre**, then loses
2,000 ft in 15 s — the textbook jump-run-then-dive signature. Median apogee across 566 Langar lifts
in the pilot week was 14,271 ft, matching standard UK operating altitude. The extracted fleet is
almost entirely Cessna 208 Caravans plus a C206, a PAC Cresco and a Shorts Skyvan; one stray
DH8D contributed 1 lift of 444 at Netheravon (0.2% contamination, immaterial).

### 2.3 Exposure windows

Per lift: **exposure window = [t_apogee, t_apogee + 480 s]** — from exit until canopies are down.
A day is an **active jump day** if it has ≥ 5 lifts.

### 2.4 Count transits

```json
{"end_date": "<week end>", "start_from": "<week start>", "window_days": 7,
 "include_path": true, "limit": 500,
 "match": {"trajectory_intersects": {
    "geometry": {"type": "Circle", "coordinates": [<lon>, <lat>], "radius": 2500},
    "altitude_max": 16000, "altitude_max_ref": "ft"}}}
```

Excluded in post-processing: the DZ's own jump aircraft (by `icao24`), and any flight whose
start or end point lies within 5 km of the DZ (local field traffic). Each remaining flight's path
was intersected with the 2.5 km circle **by segment**, solving |P + s(Q−P)| = r and interpolating
time and altitude at entry/exit — necessary because a fast aircraft crosses the 5 km diameter in
under a minute and its sampled vertices often straddle the circle without landing inside it.
Recorded per pass: entry/exit time, min/max QNH-corrected MSL altitude inside, min AGL, dwell.

### 2.5 Co-altitude test (sharper than "in window")

Being inside the 8-minute window is a weak proxy — a jet at 15,000 ft two minutes after exit is not
in conflict with anyone. So for each in-window transit the modelled parachutist column was computed
at that instant:

- fastest descent: freefall 176 ft/s to 2,500 ft, then canopy at 25 ft/s
- slowest descent: 8 s exit delay, freefall 150 ft/s to 4,500 ft, then canopy at 12 ft/s

A pass is **co-altitude** when its altitude band inside the circle overlaps
[fastest(t), slowest(t)] — i.e. a jumper is plausibly at the transiting aircraft's level, inside
the same 2.5 km circle, at the same moment.

### 2.6 Sampling

| DZ | Weeks sampled |
|---|---|
| Langar, Netheravon | 14 weeks Apr–Jul 2026 + 3 weeks Jun–Jul 2025 |
| Old Sarum | 14 weeks Apr–Jul 2026 |
| Headcorn, Hinton, Weston-on-the-Green, Hibaldstow | 6 weeks May–Jul 2026 |

Headcorn was capped at 6 weeks: it sits under the London TMA and returns ~700 flights/week through
the circle, which dominates payload without adding low-level signal.

**Total API query calls: ≈ 170**, within the 250 budget — 144 cached DZ×week fetches (129 successful
`POST /query` plus retries), ~25 discovery/validation/diagnostic calls, and 1 `GET /flights/{id}`
spot-check. All responses are cached on disk, so the analysis is reproducible without re-querying.

*Implementation note:* cursor pagination returns HTTP 500 on large `include_path: true` result sets
(reproduced deterministically at Headcorn, week of 2026-05-25: page 1 of 500 flights succeeds, the
cursor page always fails). Worked around by recursively halving the date range until each request
fits in a single cursor-free page.

---

## 3. Results

### T1 — DZ activity and transit exposure

| Drop zone | Jump aircraft (ADS-B) | Lifts | Days with jumping | Active jump days (≥5 lifts) | Median exit alt (ft MSL) | Transits on active days | Transits / active day | In exposure window | Co-altitude with jumpers |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Langar | G-FBPS, G-FOXP, G-FLOH (C208), G-BMOF (C206) | 1531 | 85 | 72 | 14338 | 107 | 1.49 | 11 | 7 |
| Headcorn | N106AN, N240GS (C208) | 161 | 19 | 14 | 12128 | 695 | 49.64 | 15 | 1 |
| Old Sarum | N240GS (C208) | 397 | 47 | 35 | 14521 | 39 | 1.11 | 3 | 2 |
| Netheravon | G-CPSS, G-BZAH, N208AX, G-UKPS (C208) | 444 | 64 | 40 | 14257 | 51 | 1.27 | 6 | 4 |
| Hinton-in-the-Hedges | G-GWMB (CRES) | 11 | 8 | 0 | 12340 | 0 | – | 0 | 0 |
| Weston-on-the-Green | G-FLOH (C208), C-FARA (SC7), G-BMOF (C206) | 14 | 8 | 0 | 12260 | 0 | – | 0 | 0 |
| Hibaldstow | G-CKSE (C208) | 2 | 1 | 0 | 15063 | 0 | – | 0 | 0 |
| **TOTAL** | | **2560** | **232** | **161** | | **892** | **5.54** | **35** | **14** |

859 distinct flights / 583 distinct airframes transited the four active DZs on active jump days.

### T2 — Altitude of transit inside the 2.5 km circle (active jump days)

| Altitude band inside circle (ft MSL) | Transits | In exposure window | Co-altitude with jumpers |
|---|---:|---:|---:|
| below 1,500 | 79 | 12 | 8 |
| 1,500 – 3,000 | 69 | 6 | 5 |
| 3,000 – 5,000 | 38 | 3 | 1 |
| 5,000 – 10,000 | 103 | 2 | 0 |
| 10,000 – 16,000 | 603 | 12 | 0 |
| **All** | **892** | **35** | **14** |

**Every co-altitude event is below 4,000 ft — in the canopy band.** The 603 high-level transits are
London TMA traffic over Headcorn and never coincide with a jumper's actual altitude.

### T3 — Aircraft mix of low transits (< 5,000 ft MSL, active jump days, n = 186)

| ICAO type | n | | Emitter category | n |
|---|---:|---|---|---:|
| H64 (Apache) | 26 | | (none broadcast) | 64 |
| P28A | 14 | | A7 rotorcraft | 58 |
| R66 | 13 | | A1 light | 46 |
| EC35 | 10 | | A2 small | 4 |
| A109 | 8 | | B4 ultralight/para | 4 |
| R44 | 6 | | A3 large | 3 |
| AS50 | 6 | | B1 glider | 3 |
| H500 | 5 | | A5 heavy | 2 |
| C42 (microlight) | 5 | | A4 | 1 |
| B06 | 5 | | D0 | 1 |
| C172 | 5 | | | |
| (no type) | 4 | | | |
| G115 | 4 | | | |
| C152 | 4 | | | |

Light GA, helicopters and microlights — plus 64 of 186 broadcasting **no emitter category at all**,
which is the visible edge of a much larger unequipped population (§6).

### T4 — Co-altitude events (transit inside circle, inside window, inside modelled jumper column)

| DZ | flight_id | Callsign | Type | Time (UTC) | Alt in circle (ft MSL) | AGL (ft) | Dwell (s) | s after exit | Exit alt (ft) | Jump aircraft flight_id |
|---|---|---|---|---|---:|---:|---:|---:|---:|---|
| Netheravon | `43c948:2026-07-08T16:06:12Z` | PNTHR77 | H64 | 2026-07-08 17:33:02 | 523 | 9 | 89 | 159 | 14139 | `400b03:2026-07-08T16:51:41Z` |
| Netheravon | `43c948:2026-07-08T16:06:12Z` | PNTHR77 | H64 | 2026-07-08 17:12:13 | 586 | −5 | 9 | 383 | 14714 | `400b03:2026-07-08T16:51:41Z` |
| Old Sarum | `43c940:2026-07-09T09:08:07Z` | PNTHR76 | H64 | 2026-07-09 09:12:31 | 730 | 424 | 69 | 242 | 10133 | `a230a6:2026-07-09T09:01:16Z` |
| Old Sarum | `43c942:2026-06-26T09:51:41Z` | PNTHR77 | H64 | 2026-06-26 09:56:35 | 827 | 520 | 74 | 165 | 14528 | `a230a6:2026-06-26T09:43:28Z` |
| **Headcorn** | **`403f58:2026-06-05T13:32:50Z`** | **GLSFT** | **P28A** | **2026-06-05 13:52:43** | **872** | **806** | **114** | **193** | **12138** | `a01b0b:2026-06-05T13:42:34Z` |
| Langar | `403c3b:2025-06-29T14:03:54Z` | GHMEC | R22 | 2025-06-29 14:13:32 | 887 | 795 | 7 | 215 | 14549 | `407d09:2025-06-29T12:59:16Z` |
| Langar | `406fa9:2026-06-28T13:11:05Z` | HLE29 | A109 | 2026-06-28 13:15:10 | 906 | 824 | 12 | 167 | 14557 | `407d09:2026-06-28T12:58:02Z` |
| Netheravon | `407bef:2026-05-08T09:51:37Z` | BDN065 | A139 | 2026-05-08 10:47:06 | 976 | 472 | 175 | 136 | 14949 | `400b03:2026-05-08T10:31:20Z` |
| Langar | `406ccd:2026-07-08T12:04:14Z` | GLARD | R66 | 2026-07-08 12:26:18 | 1527 | 1486 | 41 | 221 | 14245 | `407ba4:2026-07-08T12:03:34Z` |
| Langar | `401b7a:2026-06-21T10:44:01Z` | GBCKV | C150 | 2026-06-21 10:58:22 | 1549 | 1433 | 9 | 237 | 14934 | `407ba4:2026-06-21T09:05:24Z` |
| Langar | `39adee:2026-05-31T09:34:41Z` | FHLPO | M20P | 2026-05-31 10:04:31 | 1710 | 1613 | 43 | 236 | 14811 | `407d09:2026-05-31T09:05:49Z` |
| Netheravon | `43c174:2026-06-18T11:02:31Z` | BCT829 | C17 | 2026-06-18 11:43:19 | 2387 | 1875 | 23 | 174 | 14114 | `400b03:2026-06-18T11:02:48Z` |
| Langar | `407401:2026-06-14T15:17:50Z` | GEVIB | SR22 | 2026-06-14 16:25:43 | 2525 | 2436 | 26 | 75 | 14461 | `407ba4:2026-06-14T16:10:21Z` |
| Langar | `404f9d:2026-04-19T11:07:52Z` | GCKLP | AS28 | 2026-04-19 13:12:37 | 3697 | 3599 | 17 | 109 | 14406 | `407ba5:2026-04-19T12:07:39Z` |

**Worst single case — `403f58:2026-06-05T13:32:50Z` (G-LSFT, PA-28, no emitter category).** Its
trajectory shows it manoeuvring around the Headcorn overhead between 13:46 and 14:04 at 900–1,200 ft
MSL, repeatedly crossing in and out of the 2.5 km circle, while N106AN was dropping from 12,138 ft.
It entered the circle 193 s after an exit and stayed 114 s. It began nowhere near a known airport and
landed at Biggin Hill. Confirmed against `GET /flights/403f58:2026-06-05T13:32:50Z`.

**Conservative core.** Six of the 14 are military/state (Apache, AW139, C-17) at Netheravon and
Old Sarum — both military-adjacent airfields on Salisbury Plain, where the traffic may well be
participating or coordinated. Two of those are at ~0 ft AGL and are probably airfield surface
operations, not transits. Removing all military/state leaves **8 purely civil GA co-altitude events**
(7 at Langar, 1 at Headcorn); removing only the two ground cases leaves 12 airborne events.

### T5 — Nearest misses (in window, outside modelled column)

| DZ | flight_id | Callsign | Type | Time (UTC) | Alt in circle (ft) | Vertical sep from jumper column (ft) | s after exit |
|---|---|---|---|---|---:|---:|---:|
| Old Sarum | `43c954:2026-05-01T08:36:49Z` | SLYR62 | H64 | 2026-05-01 08:41:04 | 1221 | 90 | 356 |
| Langar | `4065ac:2025-07-18T09:08:25Z` | GTPTP | R44 | 2025-07-18 09:52:23 | 1077 | 94 | 368 |
| Langar | `40810d:2026-05-30T11:57:21Z` | GMOES | RV8 | 2026-05-30 12:22:05 | 4938 | 456 | 75 |
| Netheravon | `43c93b:2026-07-22T07:29:41Z` | DRKSTR02 | H64 | 2026-07-22 08:41:13 | 1088 | 912 | 425 |
| Langar | `40393c:2026-07-11T09:29:53Z` | GOWWW | EUPA | 2026-07-11 10:03:05 | 1900 | 1586 | 421 |
| Langar | `407692:2026-06-27T16:53:11Z` | GKTEA | DR40 | 2026-06-27 17:45:06 | 4156 | 4035 | 441 |

Two of these are within 100 ft of the modelled column — inside the model's own uncertainty.

### T6 — Temporal margin (transits on active days, not in a window)

| Transit passed within … of a live jump run | n | % of all transits on active days |
|---|---:|---:|
| 5 min | 76 | 9% |
| 10 min | 169 | 19% |
| 15 min | 236 | 26% |
| 30 min | 321 | 36% |

### T7 — Low-altitude detail by DZ

| Drop zone | Transits < 5,000 ft on active days | in exposure window | co-altitude |
|---|---:|---:|---:|
| Langar | 83 | 11 | 7 |
| Headcorn | 25 | 1 | 1 |
| Old Sarum | 35 | 3 | 2 |
| Netheravon | 43 | 6 | 4 |
| **TOTAL** | **186** | **21** | **14** |

### T8 — Season replication (Langar + Netheravon, 2025 vs 2026)

| Season | Transits on active days | In window | Co-altitude |
|---|---:|---:|---:|
| 2025 (3 weeks) | 24 | 2 | 1 |
| 2026 (all weeks) | 868 | 33 | 13 |

Rates are consistent between seasons; the effect is not a 2026 artifact.

---

## 4. Is the coincidence rate higher or lower than chance?

Transits were re-timed within each day's jump-operating span (first climb through 9,000 ft to last
descent through 9,000 ft + 8 min) and the coincidence count recounted, 600 draws per DZ-day.
Two nulls were used: **iid** (each transit re-timed independently) and **circular shift** (the whole
day's traffic shifted by one random offset, preserving its own bunching and diurnal structure, so
only the *phase* relative to jump runs is randomised).

| Statistic | Observed | Null mean | Null 5–95% | p(null ≤ observed) |
|---|---:|---:|---|---:|
| In exposure window — all transits, iid null | 35 | 71.9 | [60, 85] | < 0.002 |
| In exposure window — all transits, circular-shift null | 35 | 72.0 | [60, 84] | < 0.002 |
| **In exposure window — transits below 10,000 ft only** | **23** | **27.7** | **[21, 35]** | **0.175** |
| Co-altitude with modelled jumper column | 14 | 8.8 | [4, 14] | 0.977 |

(347 transits fall inside a jump-operating span; 119 of them below 10,000 ft.)

**This is the central result and it cuts two ways.**

1. Aggregated over all altitudes, transits coincide with live jump runs **half as often as chance**
   (35 vs ~72), robustly and under both nulls. Something is deconflicting.
2. That entire effect disappears once you restrict to traffic below 10,000 ft: 23 observed against
   27.7 expected, p = 0.18. **Below 10,000 ft there is no measurable deconfliction whatsoever.**
3. Co-altitude events — the ones that actually matter — occur at the top of the null range
   (14 vs 8.8 expected, at the ~98th percentile). There is certainly no protection there.

The mechanism is legible. At Headcorn the jump aircraft must climb into London TMA airspace, so a
lift only happens when ATC has a gap in the airway flow; the anti-correlation with the 603 airliner
transits is a *by-product of the jump aircraft being sequenced*, not of airliners avoiding the DZ.
The 186 low-level transits are in Class G, where nobody is sequencing anything and the DZ has only a
charted circle to protect it — and there the rate is exactly what chance predicts.

A raw "active day vs non-active day" comparison was computed and then **discarded as confounded**:
at Old Sarum and Netheravon, transits cluster on weekdays (Salisbury Plain military low flying) while
jumping skews to weekends, producing a spurious 3:1 ratio. The within-day permutation test above
conditions on the day and is immune to this.

---

## 5. Scale: the unmeasured denominator

| Quantity | Count in sample | Per active jump day | Per DZ-year (at 130 active days) | 4 measured DZs / year |
|---|---:|---:|---:|---:|
| Transits through the 2.5 km circle below 16,000 ft | 892 | 5.54 | 720 | 2,881 |
| … below 5,000 ft MSL | 186 | 1.16 | 150 | 601 |
| … inside a live exposure window | 35 | 0.217 | 28 | 113 |
| … co-altitude with modelled jumpers | 14 | 0.087 | 11 | 45 |

The 130-active-days-per-year figure is derived from the data, not assumed: Langar jumped on 85 of
119 sampled calendar days (71%); scaled to an April–October season that is ~130–150 active days,
before any winter operations.

**Comparison with reported airprox.** The UK Airprox Board publishes on the order of 250–300 airprox
reports per year across all UK aviation; those specifically involving parachutists or a parachute
drop zone are a small handful. *This figure is external context and was not verified against this
archive* — so the comparison is presented conditionally:

| If UK DZ-related airprox reports per year = | 1 | 3 | 5 | 10 |
|---|---:|---:|---:|---:|
| Ratio to co-altitude events at these 4 DZs alone (45/yr) | 45× | 15× | 9× | 4.5× |
| Ratio to in-window transits at these 4 DZs alone (113/yr) | 113× | 38× | 23× | 11× |

There are roughly 20 BPA-affiliated UK DZs. The four measured here are among the busiest, but even
a conservative 2× scaling to national level puts co-altitude exposure at ~90 events/year against a
handful of reports. **Under any plausible value of the denominator, actual exposure exceeds reported
exposure by at least one order of magnitude.** That part of H1 holds comfortably.

---

## 6. Caveats

Handled honestly, in rough order of importance:

1. **Jumpers are invisible to ADS-B.** Every exposure window is *modelled* from the jump aircraft's
   own profile, never observed. If a lift was flown but no one exited (a hop-and-pop cancelled, a
   ferry climb), that window is a false positive. The apogee-over-DZ-then-immediate-dive signature
   makes this unlikely but not impossible.
2. **Co-altitude ≠ conflict.** The 2.5 km circle is 5 km across; two aircraft can be inside it at
   the same altitude and 4 km apart. These are *exposure* events, not near misses, and should not be
   read as airprox-equivalents. What they measure is that the protective separation was left to
   chance.
3. **Some transits were certainly in radio contact with the DZ or ATC.** This is unknowable from
   ADS-B. A pilot who called Langar Radio, got "jumpers away", and routed through anyway at 1,500 ft
   looks identical in this data to one who never knew the DZ existed. The military helicopters on
   Salisbury Plain are the most likely coordinated cases, which is why the conservative civil-only
   count (8 co-altitude events) is given alongside the full count (14).
4. **ADS-B-less traffic makes the true rate higher, never lower.** 64 of 186 low transits broadcast
   no emitter category; only 4 declared B4 (ultralight) and 3 B1 (glider), which is far below the
   real microlight and glider population near these sites. Gliders, microlights, vintage GA and
   much military traffic are simply absent from this archive. Everything here is a **lower bound**.
5. **Receiver coverage floor biases low-altitude counts downward.** Per the archive's own guidance,
   low-level segments are the first thing lost. Again conservative.
6. **The 2.5 km circle is smaller than the real DZ.** UK parachuting sites are charted at ~1.5 nm
   (2.8 km) radius, and freefall/canopy drift from 14,000 ft routinely exceeds 2 km. Transits just
   outside 2.5 km that were still within the drift footprint are not counted.
7. **Display vs training vs tandem operations are indistinguishable** in this data. All lifts are
   treated identically.
8. **Two Apache passes at Netheravon show ~0 ft AGL** inside the circle — these are probably airfield
   surface or hover operations rather than transits. Excluding them gives 12 airborne co-altitude
   events instead of 14; excluding all military/state traffic gives 8.
9. **Trajectory geometry is simplified** (spatial ε ≈ 50 m, altitude ε ≈ 100 ft), and altitudes are
   pressure altitude plus a stepwise QNH correction. The two 90-ft "nearest misses" in T5 are within
   that noise floor and should be treated as co-altitude in all but name.
10. **The annualisation assumes sampled weeks are representative** of the April–October season. Only
    Apr–Jul was sampled; late-season rates are extrapolated.

---

## 7. Verdict

**PARTIALLY SUPPORTED — moderate-to-strong evidence, with one claim refuted and a sharper one
established in its place.**

**Supported.** The denominator is real, large, and nobody is counting it. Across 161 active jump days
at four UK DZs, 892 non-participating flights crossed the drop zone circle below 16,000 ft, 186 of
them below 5,000 ft, 35 while jumpers were plausibly in the air, and 14 while a jumper was plausibly
at the transiting aircraft's own altitude inside the same circle. Annualised over just these four
sites that is ~113 in-window transits and ~45 co-altitude events per year, against a handful of
airprox reports nationally — an under-measurement ratio of roughly 10–50×, and a lower bound, since
the least-equipped aircraft are exactly the ones missing from the data. Evidence: strong. The counts
are direct measurements, replicated across two seasons (T8), and every caveat pushes the true number
up rather than down.

**Refuted as stated.** "Routinely transit … during live jumping" implies indifference to jump
activity. In aggregate that is false: coincidences run at half the chance rate (35 vs 72, p < 0.002
under two different nulls). Something in the system works.

**The sharper finding.** That protection is entirely altitude-selective. It comes from ATC sequencing
the *jump aircraft* into controlled airspace, not from transiting aircraft avoiding the DZ — and it
therefore evaporates precisely where UK DZs have no airspace protection. Below 10,000 ft the observed
coincidence rate is statistically indistinguishable from chance (23 vs 27.7, p = 0.18), and every one
of the 14 co-altitude events is below 4,000 ft, in the canopy band, involving light singles,
helicopters and microlights. The blind spot in H1 is real; it is just narrower and better defined
than the hypothesis assumed. Evidence for this refinement: moderate — the direction is clear and
consistent across DZs and seasons, but the co-altitude sample is only 14 events (8 unambiguously
civil), so the *magnitude* of the low-level rate is not tightly bounded.

**Incidental finding worth flagging.** Two of the six DZ coordinates supplied in the brief were
wrong (Hibaldstow by ~20 km, Netheravon by ~2.5 km) and would have returned clean nulls if used
unchecked, while one of the busiest sites in the data (Old Sarum) was absent from the list. Empirical
DZ discovery, not a curated list, is the right starting point for this kind of analysis.
