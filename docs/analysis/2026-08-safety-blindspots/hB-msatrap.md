# Hypothesis B — the "MSA trap": does terrain clearance compress over a barrier when both endpoints are low?

## 1. Hypothesis restated

**Claim under test.** Pilots under-plan for routes where the *en-route* minimum
safe altitude is higher than the MSA at either end. On low-elevation → low-elevation
routes that cross a terrain barrier, terrain clearance compresses over the high
ground because the cruise altitude was chosen for the endpoints, not for the middle.

**Blind-spot framing.** Flight-planning guidance and airfield-centric safety focus
both attend to the *ends* of a route; the high ground in the *middle* is nobody's
checklist item. Barometric-only archives cannot see the compression at all; this
platform's per-vertex AGL can.

**Operationalisation.** For each barrier crossing by a light fixed-wing aircraft:

* **crest clearance** = minimum height above terrain (`path_agl_ft`) recorded while
  inside the barrier polygon;
* **MSA-trap ("trap") group** = both endpoint airports below 500 ft elevation *and*
  both endpoints ≥ 15 km from the barrier;
* **control group** = same crossing geometry, but at least one endpoint > 500 ft
  elevation or within 15 km of the barrier (i.e. a terrain-local pilot);
* **plan signature** = whether the aircraft was already high 20 km out, climbed
  early, climbed late, or never climbed.

## 2. Method

### 2.1 Barrier polygons

Three rectangles over high ground (crest > ~1 200 ft). Lon/lat, W,S,E,N:

| key | barrier | rectangle (W,S,E,N) | approx. size | observed crest terrain (median / p99 of `terr_max` over analysed crossings) |
|---|---|---|---|---|
| `CAMB` | Cambrian Mountains, mid-Wales (Plynlimon / Elenydd) | −3.95, 52.15, −3.30, 52.70 | 44 × 61 km | 1 716 / 2 475 ft |
| `PENN` | Pennines: Peak District + South Pennines (E–W crossings, Lancs/Manchester ↔ Yorkshire) | −2.15, 53.30, −1.70, 53.95 | 30 × 72 km | 1 464 / 2 074 ft |
| `LAKE` | Lake District / Cumbrian fells | −3.30, 54.30, −2.75, 54.70 | 36 × 45 km | 2 444 / 3 079 ft |

Great Glen was avoided per `results/coverage.md` (near-total blind spot below
~1 500 ft AGL). Highest terrain recovered from the data itself: PENN 2 266 ft
(Kinder Scout is 2 087 ft), LAKE 3 108 ft (Scafell Pike 3 209 ft), CAMB 3 391 ft
(a small number of outliers; p99 = 2 475 ft ≈ Plynlimon 2 467 ft) — an independent
sanity check that the derived terrain model is right to roughly ±200 ft.

### 2.2 Sampling and the two fetch passes

**Pass A — unfiltered base rate (9 whole weeks, 63 days).**
Weeks beginning 2025-05-19, 2025-06-16, 2025-07-14, 2025-09-15, 2025-10-13,
2026-03-16, 2026-04-13, 2026-06-15, 2026-07-13. Query per barrier-window
(PENN in 2-day chunks, LAKE 4-day, CAMB 7-day — larger windows returned HTTP 500
with `include_path:true`, exactly the pagination/payload bug flagged in the briefing):

```json
{
  "start_from": "2026-06-15",
  "end_date":   "2026-06-17",
  "window_days": 2,
  "include_path": true,
  "limit": 400,
  "match": {"and": [
    {"trajectory_intersects": {"geometry": {"type":"Polygon","coordinates":[[[-2.15,53.30],[-1.70,53.30],[-1.70,53.95],[-2.15,53.95],[-2.15,53.30]]]}}},
    {"emitter_category": ["A1","A2"]}
  ]}
}
```

This pass showed the crossing population is dominated by aircraft cruising at
FL200+ (median pre-barrier cruise ≈ 21 000 ft), for which terrain clearance is
vacuous. It is used only for the **base rate** in §3.1.

**Pass B — the at-risk (low-cruise) cohort, 28 weeks for CAMB/LAKE, 28 weeks for PENN.**
Weeks beginning every 3rd Monday from 2025-01-06 to 2026-07-27 (28 weeks,
196 days, all seasons, both years, all days of week). Identical query plus an
altitude bound so the fetch only returns traffic that is ever low inside the
barrier:

```json
{
  "start_from": "2026-06-15",
  "end_date":   "2026-06-18",
  "window_days": 3,
  "include_path": true,
  "limit": 400,
  "match": {"and": [
    {"trajectory_intersects": {
        "geometry": {"type":"Polygon","coordinates":[[[-2.15,53.30],[-1.70,53.30],[-1.70,53.95],[-2.15,53.95],[-2.15,53.30]]]},
        "altitude_max": 10000, "altitude_max_ref": "ft"}},
    {"emitter_category": ["A1","A2"]}
  ]}
}
```

Chunking: CAMB and LAKE 7-day windows (1 call/week), PENN 3-day windows
(3 calls/week). **No window ever returned a non-null cursor**, so no page was
ever retried — the halve-the-window workaround was applied up front.

**API call accounting: ≈ 210 calls** (62 pass-A window fetches + 139 pass-B window
fetches + ~9 validation/volume probes with `include_path:false`). Budget was 250.
Flights returned: 9 986 (pass A: PENN 6 227 / LAKE 2 718 / CAMB 991) and 10 267
(pass B: PENN 8 488 / CAMB 975 / LAKE 804).

### 2.3 Per-flight processing

`path_agl_ft` is the direct clearance measurement and is about as dense as the path
vertices (median ratio 1.03 samples per vertex), but its timestamps do **not**
coincide with vertex timestamps (median offset 14 s, p90 167 s). Holding the last
AGL value across a climb produces terrain errors of >1 000 ft, so:

* every quantity is evaluated **on the AGL sample grid**;
* position and pressure altitude are **linearly interpolated** between path
  vertices onto that grid; `alt_correction_ft` likewise (it varies slowly);
* `MSL = pathZ + alt_correction_ft`; **derived terrain = MSL − AGL**;
* server-supplied `path_agl_ft` is used for every clearance threshold — derived
  terrain is used only to characterise the barrier and build the DEM.

A 0.01°-cell **terrain grid was built from the archive itself** (median derived
terrain per cell, only from samples whose bracketing vertices are ≤ 30 s apart;
145 993 populated cells). It is used for the straight-line-vs-actual deviation
test (§3.6) and nowhere else.

### 2.4 Crossing definition (and what gets discarded)

A crossing is a maximal run of in-polygon AGL samples **within a single
subsequence**, requiring:

* ≥ 20 km of path inside the same subsequence **before** entry and ≥ 20 km **after**
  exit (so approaches/departures cannot masquerade as en-route crossings);
* entry→exit chord ≥ 25 km (a real traverse, not a corner graze);
* ≥ 8 in-polygon AGL samples with mean spacing ≤ 60 s.

Analysis cohort further requires: not military (`^[XZ][A-Z]\d{3}$` serial or
G115/TEX2/E50P/G12T/HUNT/TUCA/HAWK/PC21), **not aerial work** (type P68/PA31/C441/
BN2P/C208, callsign prefix PLINE/UKP/NPAS/SURVEY, or registration `G-POL*`),
`terr_max ≥ 1 200 ft` (actually overflew high ground), and **both** pre-barrier
cruise and maximum MSL over the barrier < 8 000 ft (keeps the comparison inside the
light-GA low-level regime and stops climbing airliners contaminating the control).

Classification of the altitude plan, in this order:

| class | rule |
|---|---|
| **pre-planned high** | MSL 20 km before the barrier already ≥ 1 000 ft above the crest actually overflown |
| **no climb** | total MSL gain from the 20-km point to barrier exit < 250 ft, or no sustained climb found |
| **proactive climb** | first sustained climb (≥ 250 ft gain within ≤ 7 min at > 300 fpm) starts ≥ 10 km before the barrier boundary |
| **reactive climb** | that climb starts < 10 km before, or inside, the barrier |

**Discard accounting (pass B).** Of flights that touched a barrier polygon,
those yielding no clean crossing:

| barrier | flights fetched | touched polygon | no clean crossing | graze (chord < 25 km) | insufficient 20 km margin | **run touched a subsequence end (fragmentation)** |
|---|---|---|---|---|---|---|
| CAMB | 975 | 956 | 810 | 949 | 40 | **133** |
| PENN | 8 488 | 8 470 | 6 456 | 5 528 | 1 812 | **79** |
| LAKE | 804 | 771 | 634 | 685 | 91 | **91** |

(A flight can contribute several rejection reasons; counts are per in-polygon run.)
The fragmentation loss — crossings split by a readsb/coverage gap and therefore
excluded — is **303 runs in total**, i.e. of order 3–14 % of the touched
population per barrier. 22.3 % of the *analysed* crossings still come from
multi-subsequence flights (their crossing simply lay wholly inside one part).

## 3. Results

### 3.1 How much of the crossing traffic is even in the at-risk regime?

From pass A (unfiltered, 9 weeks), among crossings that overflew ≥ 1 200 ft terrain:

| barrier | clean crossings | with pre-barrier cruise < 8 000 ft | % |
|---|---|---|---|
| CAMB | 237 | 19 | 8.0 % |
| PENN | 1 359 | 165 | **12.1 %** |
| LAKE | 684 | 12 | 1.8 % |

The MSA trap can only bite the ~2–12 % of barrier traffic that crosses low.
Everything below is that population.

### 3.2 Headline: crest-clearance distributions, trap vs control

Cohort as defined in §2.4. Clearance in ft AGL at the lowest point inside the barrier.

| barrier / group | n | min | p05 | p10 | p25 | **p50** | p75 | p90 | **% < 1 000 ft** (95 % CI) | **% < 500 ft** (95 % CI) |
|---|---|---|---|---|---|---|---|---|---|---|
| **PENN trap** | **232** | 272 | 546 | 646 | 822 | **1 093** | 1 420 | 1 739 | **42.7 %** (36.5–49.1) | **3.9 %** (2.1–7.2) |
| PENN control | 37 | 610 | 723 | 947 | 1 250 | **1 587** | 3 184 | 4 941 | 10.8 % (4.3–24.7) | 0.0 % (0–9.4) |
| CAMB trap | 34 | 1 900 | 1 971 | 2 102 | 2 434 | **3 443** | 4 293 | 4 684 | **0.0 %** (0–10.2) | 0.0 % |
| CAMB control | 0 | — | — | — | — | — | — | — | — | — |
| LAKE trap | 26 | 1 362 | 1 984 | 2 201 | 2 459 | **3 722** | 3 983 | 5 077 | **0.0 %** (0–12.9) | 0.0 % |
| LAKE control | 3 | 3 108 | — | — | 3 702 | 4 295 | 4 713 | — | 0.0 % | 0.0 % |
| **ALL trap** | **292** | 272 | 587 | 669 | 909 | **1 229** | 1 873 | 3 919 | **33.9 %** (28.7–39.5) | **3.1 %** (1.6–5.8) |
| **ALL control** | **40** | 610 | 728 | 1 027 | 1 251 | **1 702** | 3 353 | 5 000 | **10.0 %** (4.0–23.1) | 0.0 % (0–8.8) |

**Significance (Mann–Whitney U, two-sided, tie-corrected normal approximation):**

| comparison | n trap / n control | z | p | P(trap < control) | odds ratio for clearance < 1 000 ft |
|---|---|---|---|---|---|
| PENN trap vs control | 232 / 37 | −4.97 | **6.7 × 10⁻⁷** | 0.246 | **6.14** (p = 2.1 × 10⁻⁴) |
| PENN, point-to-point only | 185 / 34 | −5.12 | **3.0 × 10⁻⁷** | 0.224 | — |
| ALL trap vs control | 292 / 40 | −3.44 | **5.7 × 10⁻⁴** | 0.332 | 4.62 (p = 2.2 × 10⁻³) |

**The effect is entirely a Pennines effect.** Over the Cambrians and the Lake
District, not one qualifying low-cruise crossing came within 1 300 ft of the
ground; median clearances are 3 400–3 700 ft. Over the Pennines the median
MSA-trap crossing clears the high ground by 1 093 ft and **43 % clear it by less
than 1 000 ft**.

### 3.3 Plan signature (classification mix)

| group | pre-planned high | proactive climb | reactive climb | no climb | **reactive + no climb** |
|---|---|---|---|---|---|
| **PENN trap** (n = 232) | 49.1 % | 15.5 % | **19.8 %** | **15.5 %** | **35.3 %** |
| PENN control (n = 37) | 75.7 % | 13.5 % | 5.4 % | 5.4 % | **10.8 %** |
| ALL trap (n = 292) | 59.6 % | 12.3 % | 15.8 % | 12.3 % | 28.1 % |
| ALL control (n = 40) | 77.5 % | 12.5 % | 5.0 % | 5.0 % | 10.0 % |
| CAMB / LAKE trap | 100 % | 0 | 0 | 0 | 0 % |
| **PENN trap, clearance < 1 000 ft (n = 99)** | 21.2 % | 19.2 % | **30.3 %** | **29.3 %** | **59.6 %** |

Among the crossings that actually ended up under 1 000 ft, **60 % show a
reactive-or-absent climb** — the aircraft was not high when it needed to be and
either fixed it late or not at all. Terrain-local (control) pilots are
"pre-planned high" three-quarters of the time and essentially never react late.

### 3.4 Control 1 — the no-climb counterfactual (was the climb doing any work?)

Counterfactual clearance = MSL 20 km before the barrier − crest actually overflown,
i.e. what the pilot would have got had they simply held the endpoint-driven cruise
altitude across the barrier.

| PENN trap (n = 232) | % < 1 000 ft | % < 500 ft | median |
|---|---|---|---|
| counterfactual (hold cruise) | 50.9 % | **29.7 %** | 992 ft |
| **actual** | 42.7 % | **3.9 %** | 1 093 ft |

Median "climb credit" (actual − counterfactual) = **55 ft**; 42 % of trap crossings
gained ≥ 200 ft. So pilots are *not* blind — the late climb removes most of the
truly dangerous cases (< 500 ft falls from 30 % to 4 %) — but it buys almost
nothing at the 1 000 ft level: the compression is only partially mitigated, and it
is mitigated by a reaction rather than by the plan.

### 3.5 Control 2 — is the chosen altitude coupled to the terrain at all? (geometric control)

Shuffle the observed maximum MSL over the barrier randomly among the crossings in
the same barrier (200 permutations), then recompute clearance against each
crossing's own crest. If altitude choice were terrain-coupled, the real assignment
would beat the shuffle.

| PENN trap | % clearance < 1 000 ft | median |
|---|---|---|
| observed altitude, own crest | 20.3 % | 1 332 ft |
| **shuffled altitudes** | **19.4 %** | 1 350 ft |

They are statistically indistinguishable. Spearman correlation between crest
height and the altitude actually flown over it is weak in the trap group
(PENN ρ = 0.268, n = 232, p = 4.7 × 10⁻⁵; pooled ρ = 0.455 — but pooling mixes
three barriers of very different height, which manufactures the correlation) and
absent in the control group (PENN ρ = −0.09, p = 0.58; the control group is high
enough everywhere that terrain does not constrain it).

**Conclusion: the altitude flown over a Pennine crest carries almost no
information about how high that particular crest is.** That is the behavioural
signature the hypothesis predicts.

### 3.6 Control 3 — did anyone route around the high ground?

Comparing the DEM maximum along the actual track with the DEM maximum along the
straight line between the same entry and exit points (identical measure, same
grid, so the comparison is fair):

| group | n | median (straight-line − actual) | % ≥ 300 ft lower than straight line |
|---|---|---|---|
| trap (all barriers) | 292 | **0 ft** | **1.4 %** |
| control | 40 | 0 ft | 2.5 % |

Essentially **nobody deviates to follow lower terrain.** Crossings are flown as
straight lines; the vertical dimension is the only one being used, and only
partially.

### 3.7 Weather confound

Barrier-days were split at the 75th percentile of that barrier's daily A1/A2
low-cruise traffic ("busiest quartile" = good VFR days).

| trap crossings | n | median | % < 1 000 ft | % < 500 ft |
|---|---|---|---|---|
| busiest quartile (good-weather days) | 115 | 1 110 ft | **38.3 %** | 3.5 % |
| remaining days | 177 | 1 299 ft | 31.1 % | 2.8 % |
| Apr–Sep | 178 | 1 215 ft | 34.8 % | 2.8 % |
| Oct–Mar | 114 | 1 272 ft | 32.5 % | 3.5 % |

The compression is **at least as strong on the busiest (best-weather) days** and
shows no seasonal signature. Low cloudbase is therefore not the driver: if it
were, the effect would concentrate on quiet, poor-weather days. The corresponding
busy-day control (n = 11) sits at 9.1 % < 1 000 ft, unchanged.

### 3.8 The alternative explanation the data forces on us: a controlled-airspace lid

Maximum MSL over the barrier, PENN trap crossings (500 ft bins):

| bin (ft MSL) | 1 500 | 2 000 | 2 500 | 3 000 | 3 500 | 4 000 | 4 500 | 6 000+ |
|---|---|---|---|---|---|---|---|---|
| crossings | 3 | 29 | **114** | **66** | 11 | 2 | 1 | 6 |

77 % of crossings top out between 2 000 and 3 500 ft, with a **hard cliff above
3 500 ft**. That is not what an unconstrained altitude choice looks like — it is
the signature of a controlled-airspace base (the Manchester TMA / Peak District
CTA sectors sit at 3 500 ft over much of this box). Splitting by latitude:

| crest latitude band | n | median clearance | % < 1 000 ft | median crest terrain | median MSL flown |
|---|---|---|---|---|---|
| 53.30–53.55 (Peak District, deepest under the TMA) | 53 | **904 ft** | **62.3 %** | 1 877 ft | 3 005 ft |
| 53.55–53.75 (South Pennines) | 160 | 1 156 ft | 37.5 % | 1 456 ft | 2 824 ft |
| 53.75–53.95 (Calderdale / Ilkley) | 19 | 1 261 ft | 31.6 % | 1 464 ft | 2 896 ft |

The worst clearances sit exactly where the terrain is highest *and* the airspace
lid is lowest, and the flown altitude is essentially constant (2 800–3 000 ft)
across all three bands while terrain varies by 400 ft. This is a genuine
alternative causal story: over the Peak District the squeeze may be **airspace
above and terrain below**, not planning inattention. It does not weaken the
*safety* finding (clearance really is compressed) but it materially weakens the
attribution to "the pilot chose cruise altitude for the endpoints". It also
explains why CAMB and LAKE — no low-level CAS lid — show none of the effect.

### 3.9 Coverage floor per barrier (bias direction)

Fraction of pass-B flights whose minimum in-box AGL falls below a threshold:

| barrier | flights with in-box AGL | < 200 ft | < 500 ft | < 1 000 ft | < 1 500 ft |
|---|---|---|---|---|---|
| CAMB | 921 | 10.9 % | **25.4 %** | 28.4 % | 34.6 % |
| PENN | 8 448 | 2.2 % | 7.8 % | 18.0 % | 28.8 % |
| LAKE | 764 | 1.3 % | **4.3 %** | 11.5 % | 17.4 % |

Receivers over the **Cambrians see plenty of sub-500 ft traffic** (25 %, mostly
military low flying excluded from the cohort), so the CAMB null result is **not a
coverage artefact** — the archive would have shown low civil crossings there had
they existed. The **Lake District floor is the weakest** (4.3 %), so its null is
the least trustworthy of the three. The PENN positive result is, as always,
conservative: any low segments the receivers missed would have pushed the
distribution lower still.

## 4. Concrete evidence — the ten lowest MSA-trap crossings

All PENN; all civil, non-military, non-aerial-work; all single-subsequence
(`n_sub = 1`), so none is an artefact of a fragmented leg.

| flight_id | type / reg | route (elev ft) | crest clearance | crest terrain | MSL 20 km out | MSL over crest | class |
|---|---|---|---|---|---|---|---|
| `402924:2026-07-11T14:48:49Z` | P28A / G-BNOP | EGNH→EGNH (34→34) | **272 ft** | 2 021 ft | 2 434 | 2 428 | **no climb** |
| `406534:2026-07-31T17:35:52Z` | EV97 / G-CGVT | EGCB→EGCB (73→73) | **302 ft** | 1 953 ft | 1 666 | 2 331 | **no climb** |
| `4046ad:2025-12-11T12:40:53Z` | P28A / G-GURU | EGCJ→EGCB (26→73) | **367 ft** | 1 344 ft | 2 124 | 2 588 | **reactive climb** |
| `407891:2026-07-10T14:28:26Z` | C42 / G-WKDB | EGCJ→EGCB (26→73) | **370 ft** | 1 367 ft | 1 941 | 2 276 | **reactive climb** |
| `aa3b8b:2025-09-19T08:37:55Z` | C182 / N759AU | EGCB→EGNG (73→161) | **403 ft** | 1 506 ft | 1 513 | 2 108 | **reactive climb** |
| `402ab6:2026-01-04T10:37:40Z` | C172 / G-BOIL | EGCB→EGCB (73→73) | **429 ft** | 1 920 ft | 2 806 | 2 710 | **no climb** |
| `404cdc:2025-03-15T09:08:20Z` | E200 / G-TWOO | EGCB→EGNW (73→63) | **453 ft** | 1 444 ft | 1 328 | 1 909 | **no climb** |
| `4065e1:2026-03-04T14:54:38Z` | EUPA / G-MLXP | EGCB→EGCS (73→58) | **465 ft** | 1 830 ft | 700 | 2 733 | proactive climb |
| `ac6db6:2026-06-19T14:14:29Z` | SR22 / N90KB | EGBG→EGCB (469→73) | **490 ft** | 1 511 ft | 2 010 | 2 655 | proactive climb |
| `4046ad:2025-12-11T11:26:45Z` | P28A / G-GURU | EGCB→EGCJ (73→26) | **509 ft** | 1 518 ft | 1 646 | 2 160 | proactive climb |

Note `4046ad` (G-GURU) appears twice on 2025-12-11 — outbound Barton→Sherburn at
509 ft and the return at 367 ft, the same pilot repeating the same profile in both
directions on the same winter day.

**The dominant MSA-trap route is Manchester Barton (EGCB, 73 ft) ↔ Sherburn-in-Elmet
(EGCJ, 26 ft)**: 38 of the 292 trap crossings and 29 of the 99 sub-1 000 ft
crossings. It is a textbook trap geometry — 100 km between two sea-level airfields
with the 1 300–2 000 ft South Pennines exactly in the middle.

Aircraft-type mix of the trap cohort (P28A 52, C172 27, RV7 17, DA42 16, C42 13,
C150 12, C182 11, DA40 11, DA62 10, DR40 10) is ordinary club/touring GA; 95 %
emitter category A1. Aerial-work airframes were removed: the P68 fleet
(G-RVNR "PLINE33" pipeline patrol; G-POLV/G-POLZ "UKP155/UKP152" police) accounted
for 25 crossings — 24 P68 plus one PA31 — and **18 of the 117 sub-1 000 ft
crossings** before exclusion. Leaving them in would have reported 36.9 % below
1 000 ft instead of 33.9 %.

Full per-crossing evidence: `results/hB-crossings.csv` (332 rows, trap + control).

## 5. Sensitivity: how much is short-hop geometry?

Manchester Barton is only ~16 km from the barrier — just past the 15 km exclusion —
so some "trap" flights are still climbing out when they reach the high ground.
Re-running with a **stricter geometry** (both endpoints ≥ 25 km from the barrier
*and* ≥ 30 km of clean path before entry):

| PENN | n | median | % < 1 000 ft | % < 500 ft | reactive + no climb |
|---|---|---|---|---|---|
| trap, standard (15 km / 20 km) | 232 | 1 093 ft | 42.7 % | 3.9 % | 35.3 % |
| trap, strict (25 km / 30 km) | 130 | 1 290 ft | **26.2 %** | 0.8 % | 25.4 % |
| trap, strict + point-to-point only | 100 | 1 264 ft | 27.0 % | 0.0 % | 28.0 % |

The effect **attenuates but does not disappear**: with a clean 30 km cruise run
before the barrier, a quarter of MSA-trap crossings still clear the crest by under
1 000 ft. The matched strict control collapses to n = 2, so no significance test
is possible at that setting (the pooled strict comparison gives z = −1.85,
p = 0.064, n = 185 vs 5 — under-powered, not evidence of absence).
Round-trip flights (same start and end airfield, 47 of 232 PENN trap crossings)
behave the same as point-to-point ones (38.3 % vs 43.8 % below 1 000 ft), so the
result is not an artefact of local pleasure flying.

## 6. Caveats

* **The control group is small and imperfectly matched.** Only 40 crossings
  qualify across all three barriers (5 "high endpoint", 35 "endpoint within 15 km").
  The UK simply has very few ADS-B-equipped GA movements to/from airfields above
  500 ft near these ranges. The `max MSL < 8 000 ft` filter was added specifically
  because an earlier, unfiltered control was contaminated by ATR-72/E145/Citation
  departures out of Manchester climbing through the box — those made the control
  look artificially safe. Even after filtering, the control still contains 10
  category-A2 airframes against 278 A1 in the trap group; the groups are similar
  but not identical populations.
* **The controlled-airspace lid (§3.8) is a live alternative explanation** for the
  Pennine result and cannot be separated from planning behaviour with this data
  alone. Airspace boundaries are not in the archive; the inference is from the
  altitude histogram and geography. A follow-up overlaying UK AIP CAS bases would
  settle it.
* **Coverage floor biases clearance upward** (missed low segments), so all positive
  findings are conservative. But the Lake District's floor (4.3 % of flights ever
  below 500 ft in-box) is weak enough that its null result should be treated as
  "not demonstrated", not "demonstrated absent".
* **Individual clearances carry roughly ±200 ft of DEM + QNH-interpolation error**,
  and the archive's stated simplification tolerances are ε = 50 m spatial /
  100 ft altitude. Rankings in the worst-10 table should not be read to the foot.
* **Leg fragmentation removed 303 in-polygon runs** (§2.4) whose crossing straddled
  a subsequence boundary. These are not random: fragmentation correlates with poor
  low-altitude coverage, so the discarded set is plausibly *lower*-flying than the
  retained set — again conservative.
* **"Reactive climb" is a behavioural signature, not proof of intent.** A pilot
  deliberately flying VFR-on-top or staying low for airspace/visibility reasons and
  then climbing over the crest produces the same trace as one who forgot the
  terrain. The classification thresholds (250 ft / 300 fpm / 10 km) are defensible
  but arbitrary.
* **Only ADS-B-equipped aircraft appear**; gliders, many microlights and most
  military are invisible or excluded. The trap cohort is club/touring GA and should
  not be generalised to the whole low-flying population.
* **Endpoint classification needs both airports recognised.** Crossings with a null
  `start_airport_ident` or `end_airport_ident` (about a quarter of clean crossings)
  are dropped from both groups entirely.
* **Three barriers, chosen for coverage, in one country.** Nothing here supports
  extrapolation to other terrain or other regulatory environments. The pooled
  "ALL" rows mix barriers with very different terrain heights and should be read
  as a summary, not as a homogeneous population.

## 7. Verdict

**PARTIALLY SUPPORTED — strong evidence for the phenomenon over one of three
barriers, weak evidence for the proposed mechanism.**

What is solidly established (moderate-to-strong evidence):

1. Over the Pennines, low-cruise MSA-trap crossings are dramatically more
   compressed than terrain-local control crossings: median 1 093 ft vs 1 587 ft,
   **42.7 % vs 10.8 % below 1 000 ft** (MW p = 6.7 × 10⁻⁷, OR = 6.1), and the
   effect survives a strict-geometry sensitivity at 26 %.
2. The plan signature matches the hypothesis: **35 % of trap crossings are
   reactive-or-no-climb vs 11 % of controls**, rising to **60 % among the
   sub-1 000 ft crossings**.
3. Altitude choice is essentially **not coupled to the specific crest overflown** —
   a random reassignment of the cohort's altitudes gives the same clearance
   distribution (19.4 % vs 20.3 % below 1 000 ft).
4. **Nobody routes around it**: 1.4 % of crossings follow terrain more than 300 ft
   lower than the straight line.
5. The result is **not a weather artefact** — it is if anything stronger on the
   busiest, best-weather days, and has no seasonal signature.

What is not established, and why the verdict is not SUPPORTED:

6. **The phenomenon did not replicate on the other two barriers.** Over the
   Cambrians (34 crossings) and the Lake District (26), *zero* qualifying
   low-cruise crossings came within 1 300 ft of the ground, and 100 % were
   classified "pre-planned high". The Cambrian null is credible (its low-altitude
   coverage is the best of the three); the Lake District null is under-powered.
   A hypothesis about generic "low-to-low across a barrier" geometry predicts the
   effect everywhere; it appears in one place.
7. **A controlled-airspace lid is a competing explanation** for exactly where the
   effect appears: 77 % of Pennine trap crossings top out between 2 000 and
   3 500 ft with a hard cliff above, and the worst clearances (62 % below 1 000 ft)
   are in the Peak District band where the CAS base is lowest and the terrain
   highest. Under that reading, pilots are not ignoring the middle of the route —
   they are boxed in from above.
8. The counterfactual test shows pilots **do** respond: holding the endpoint cruise
   altitude would have put 30 % of trap crossings below 500 ft; the observed figure
   is 3.9 %. The trap is real but it is being caught late, not missed entirely.

**Practical reading.** The "MSA trap" is a real and measurable safety signature on
short low-to-low GA routes across the South Pennines — most concretely the
Barton ↔ Sherburn run, which contributed 29 of the 99 sub-1 000 ft crossings — but
on this evidence it is a *Pennines-specific* phenomenon whose cause is at least
partly the terrain-plus-airspace squeeze rather than pure planning inattention.
The next experiment worth running is the one this study cannot: overlay AIP
controlled-airspace bases and re-test on barriers with and without a low CAS lid.
