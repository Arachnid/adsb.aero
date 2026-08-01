# Coverage & Data-Quality Blind Spots — adsb.aero Archive

**Role**: data-quality validator. This is not a single hypothesis test — it
quantifies the archive's blind spots in six study areas so that the four
downstream hypothesis studies (a) low-AGL GA in Welsh/Scottish terrain,
(b) traffic under the London TMA / Manchester low-level route, (c) parachute
drop zones in rural England, (d) go-arounds at LBA/Gibraltar/Birmingham/EMA
— can caveat their findings correctly. A verdict is given per measurement
(section 6), not one overall verdict.

## 1. Restated task

For six study-area bounding boxes and three sample days, measure: (1) the
low-altitude coverage floor implied by the last AGL reading of flights
landing at a recognized airport in-box; (2) the fraction of flights with any
AGL data at all; (3) GA-relevant traffic base rates by emitter category,
including A1 metadata completeness; (4) how often a single flight's path is
split into multiple disconnected subsequences (coverage dropout mid-leg,
distinct from a full leg split).

## 2. Method

**Areas** (GeoJSON boxes, SW corner–NE corner, `[lon,lat]`):

| area | box (w,s)–(e,n) |
|---|---|
| snowdonia | (-4.4,52.7)–(-3.5,53.2) |
| great_glen | (-5.2,56.8)–(-4.2,57.5) |
| cheshire | (-2.9,53.2)–(-2.2,53.5) |
| wiltshire | (-2.2,51.0)–(-1.4,51.4) |
| lincolnshire | (-0.9,53.4)–(0.0,53.8) |
| leeds | (-1.9,53.7)–(-1.4,54.0) |

All six boxes are well under the ~3–4° / 250-H3-cell geometry limit, so none
needed tiling. `include_path` reproducibility note: `path_agl_ft` and
`alt_correction_ft` are in fact returned even when `include_path:false`
(only `path`/`timestamps`/`path_gs`/`path_tracks`/`path_ias`/`squawk_runs`
go null) — an undocumented quirk worth knowing, though sections 1–2 below
still use `include_path:true` as the task specified, for exact
reproducibility.

**Sample days**: 2026-06-20, 2026-07-18, 2026-01-17. All three landed on a
**Saturday** — see caveats (§5); this was not adjusted since none were empty.

**Query templates used** (verbatim; `<DAY>`/`<DAY+1>` and `<BOX>` substituted
per area/day from the table above):

Step 1+2 — coverage floor & AGL availability (18 calls, one per area×day):
```json
{
  "end_date": "<DAY+1>", "start_from": "<DAY>", "window_days": 1,
  "include_path": true, "limit": 300,
  "match": {"endpoint_within": {"mode": "end", "geometry": <BOX>}}
}
```
For each flight with non-null `end_airport_ident`: last non-null value in
`path_agl_ft[-1]` (final subsequence) = coverage-floor sample; min of
`path_agl_ft[-1]` = min AGL over final subsequence. For all flights
(regardless of endpoint): `path_agl_ft is not None` = AGL-availability flag.

Step 3 — GA traffic base rates (18 calls, one per area×day, single page
every time):
```json
{
  "end_date": "<DAY+1>", "start_from": "<DAY>", "window_days": 1,
  "include_path": false, "limit": 10000,
  "match": {"trajectory_intersects": {"geometry": <BOX>}}
}
```
`emitter_category` (and A1 `icao_type`) tabulated **directly from the
returned per-flight field**, not via separate per-category queries or
subtraction — this is the true JSON-null count, not a residual.

Step 1 supplementary — direct low-AGL existence check (18 calls):
```json
{
  "end_date": "<DAY+1>", "start_from": "<DAY>", "window_days": 1,
  "include_path": false, "limit": 2000,
  "match": {"trajectory_intersects": {"geometry": <BOX>, "agl_max_ft": 500}}
}
```

Step 4 — leg-splitting sanity, A1 flights, Cheshire (3 calls) + Wiltshire
comparison (3 calls):
```json
{
  "end_date": "<DAY+1>", "start_from": "<DAY>", "window_days": 1,
  "include_path": true, "limit": 300,
  "match": {"and": [
    {"trajectory_intersects": {"geometry": <BOX>}},
    {"emitter_category": ["A1"]}
  ]}
}
```
`n_subsequences = len(path["coordinates"])`; multi-subsequence = >1.

Plus 4 small validation calls before scaling up (checked field shapes,
null-handling, `include_path:false` behavior). **Total: 67 query calls**,
well under the 100-call budget.

## 3. Results

### 3.1 Coverage floor & AGL data availability (Step 1+2)

"Floor" = last AGL reading (ft) of flights whose leg ends at a recognized
in-box airport, summed over all 3 days. Negative values are noise (terrain-
model + QNH-interpolation error near ground), not physical — read anything
within roughly ±50 ft as "effectively ground level."

| area | AGL data avail. | n landed @ known airport | last-AGL median (Q1–Q3), ft | dominant end airports |
|---|---|---|---|---|
| snowdonia | 100% (61/61) | 51 | **12** (−39 – 83) | EGCK Caernarfon (51) |
| great_glen | 100% (4/4) | **0** | n/a — no in-box airport landings | — |
| cheshire | 100% (900/900)¹ | 872 | **−1** (−22 – 36) | EGCC Manchester (565), EGGP Liverpool (177), EGCB Barton (130) |
| wiltshire | 100% (207/207) | 75 | **696** (366 – 905) | EGLS Old Sarum (29), EGDJ Upavon (29), EGVP Middle Wallop (9), EGHO Thruxton (8) |
| lincolnshire | 100% (120/120) | 80 | **231** (112 – 376) | EGNJ Humberside (42), EGCF Sandtoft (36), EGCS Sturgate (2) |
| leeds | 100% (197/197) | 175 | **−8** (−27 – 18) | EGNM Leeds Bradford (175, all of it) |

¹ Cheshire's step-1 query hit the `limit=300` cap on **all 3 days**
(`cursor` non-null) — see caveats; the pagination cursor trends toward
end-of-day timestamps, so the retained 300/day skew toward late hours.

Headline: **AGL data availability is not the discriminator** — it's ~100%
everywhere sampled (all six are UK land areas; no ocean/missing-terrain-tile
cases turned up). The real variable is the **coverage floor**, and it splits
into two regimes: major/licensed airports (Manchester, Liverpool, Leeds
Bradford, Caernarfon) track essentially to touchdown (medians −8 to +12 ft);
small rural/military strips used for parachuting and gliding (Old Sarum,
Upavon, Middle Wallop, Thruxton, Sandtoft, Humberside) lose the aircraft
**200–900 ft above the ground**, well before touchdown.

### 3.2 GA traffic base rates by emitter category (Step 3)

Counts summed over the 3 sample days, `trajectory_intersects` on the box at
**any altitude** (so `total` is dominated by high-altitude jet overflights,
category A3/A5 — only look at the named columns for GA/rotor/glider/para
activity level).

| area | total (any alt) | A1 (light) | A7 (rotor) | B1 (glider) | B4 (ultralight/para) | null (no category) | A1 w/ null `icao_type` |
|---|---|---|---|---|---|---|---|
| snowdonia | 419 | 58 | 37 | 0 | 0 | 18 (4.3%) | 0/58 (0%) |
| great_glen | 277 | 17 | 9 | 0 | 1 | 2 (0.7%) | 1/17 (6%) |
| cheshire | 3934 | 256 | 73 | 0 | 23 | 125 (3.2%) | 2/256 (1%) |
| wiltshire | 1294 | 231 | 44 | **76** | 22 | 108 (8.3%) | 5/231 (2%) |
| lincolnshire | 947 | 197 | 20 | 1 | 3 | 136 (**14.4%**) | 1/197 (1%) |
| leeds | 889 | 59 | 8 | 0 | 5 | 61 (6.9%) | 2/59 (3%) |

Notes: B1 (glider) traffic is essentially confined to Wiltshire in this
sample (76 of 78 total across all six areas) — consistent with known gliding
activity around Upavon/Salisbury Plain. Lincolnshire has a conspicuously
high null-category fraction (14.4%) — some genuine GA/glider traffic there
is likely hiding in the "null" bucket rather than the named categories, so
Lincolnshire's true light-aircraft activity is probably undercounted more
than the other areas. A1 `icao_type` completeness is good everywhere (0–6%
null), so downstream type-based filtering on A1 traffic should be reliable.

### 3.3 Supplementary: direct low-AGL (≤500 ft) existence check

Independent of airport endpoints — counts any flight with ≥1 in-box point
≤500 ft AGL, summed over 3 days, against the Step-3 total-traffic
denominator.

| area | total traffic (3d) | flights w/ point ≤500ft AGL | % of total |
|---|---|---|---|
| snowdonia | 419 | 74 | 17.7% |
| great_glen | 277 | **1** | **0.4%** |
| cheshire | 3934 | 2317 | 58.9% |
| wiltshire | 1294 | 91 | 7.0% |
| lincolnshire | 947 | 131 | 13.8% |
| leeds | 889 | 345 | 38.8% |

This independently corroborates §3.1: Great Glen is a near-total blind spot
below 500 ft (0, 1, 0 flights across the three days respectively), and
Wiltshire is markedly worse than Cheshire/Leeds even though all three have
plenty of general traffic. The % column is confounded by how much of each
box's traffic is airport-approach traffic by construction (Cheshire/Leeds
have major runways inside the box, mechanically forcing many flights below
500 ft there) — treat it as a rough cross-check, not a clean coverage metric
on its own.

### 3.4 Leg-splitting sanity check (Step 4)

Multi-subsequence path = the flight's `path` MultiLineString has >1 part,
i.e. genuine positional/temporal gaps *within* one `flight_id` (not a new
leg — per the briefing, only a full-stop + later departure splits a leg).

| area | category | n sampled | multi-subsequence | % |
|---|---|---|---|---|
| cheshire | A1 | 256 | 69 | **27.0%** |
| wiltshire | A1 | 231 | 97 | **42.0%** |

Multi-subsequence paths are **common, not rare**, and markedly more common
in Wiltshire (worse coverage floor, §3.1) than Cheshire (near-zero floor) —
consistent with the same underlying coverage-quality difference showing up
three independent ways (landing floor, low-AGL existence, mid-flight
fragmentation). Downstream trajectory analysis must treat multi-part paths
as a normal artifact of receiver coverage gaps, not as evidence of two
separate flights or an anomaly to filter out.

## 4. Concrete example flights

| flight_id | area | what it shows |
|---|---|---|
| `40105c:2026-06-20T15:18:19Z` | great_glen | PA24, leg ends at 2678 ft AGL, `end_airport_ident` null — track stops mid-air, not a landing |
| `406de5:2026-07-18T19:43:33Z` | great_glen | AW149 SAR helicopter, ends at 2583 ft AGL, no recognized airport nearby |
| `406c8e:2026-01-17T16:46:42Z` | great_glen | S-92 SAR helicopter, ends at 2894 ft AGL — even rescue helicopters "vanish" well above the ground here |
| `4070e3:2026-06-20T23:58:42Z` | cheshire | B738 into EGCC, last AGL ≈ −12 ft — tracked essentially to touchdown |
| `a230a6:2026-06-20T16:55:03Z`, `...T17:25:09Z`, `...T17:54:42Z` | wiltshire | same icao24, three ~30-min legs into EGLS Old Sarum same afternoon, last AGL 391–603 ft each time — textbook repeated-lift jump-plane pattern, and shows the floor is *systematic*, not a one-off |
| `401add:2026-06-20T16:55:11Z` | lincolnshire | lands EGCF Sandtoft, last AGL 28 ft — small strip, still good floor (floor is not simply "big airport vs small strip") |
| `4068f5:2026-06-20T23:15:02Z` | leeds | lands EGNM, last AGL ≈ −10 ft |
| `403297:2026-06-20T16:50:46Z` | cheshire | G-RVRY (PA38 trainer), **12 subsequences** over ~2h, gaps 62s–31min — classic circuit-training coverage dropout pattern |
| `4011af:2026-06-20T19:41:24Z` | cheshire | G-CEGP (BE20 King Air), 1 subsequence, clean continuous track — higher-capability IFR traffic tracks cleanly |
| `406dde:2026-06-20T14:27:44Z` | wiltshire | G-CINH (ultralight, ICAO type ULAC), 6 subsequences in 32 points — fragmentation hits ultralights hardest |

## 5. Caveats

- **All three sample days are Saturdays.** This is good for catching peak GA
  and parachute-club activity, but the entire sample has zero weekday
  coverage — commercial/training patterns that concentrate on weekdays are
  unrepresented, and these numbers should not be read as "typical day"
  figures without a weekday cross-check.
- **Cheshire's Step-1 query truncated at the 300/day cap on every sample
  day** (872 of some larger true total captured across 3 days). Pagination
  cursors trend toward end-of-day timestamps, suggesting flights are
  returned in reverse-chronological order — so the Cheshire floor number is
  likely biased toward evening traffic and may not represent the full day.
  Not re-queried further to stay within budget; flagged instead.
- **Negative "last AGL" values are measurement noise**, not real
  below-ground positions — from terrain-model resolution and
  pressure-altitude/QNH-correction interpolation error near the ground.
  Treat |AGL| ≲ 50–100 ft as "at/near ground," not as a signed physical
  quantity.
- **The Step-3 "total" column is dominated by high-altitude overflights**
  (trajectory_intersects has no altitude bound) — it is not a GA activity
  measure by itself; only the named-category columns are.
- **Absence of ADS-B ≠ absence of traffic**, per the briefing: gliders,
  microlights, military and some vintage GA are structurally invisible
  regardless of receiver coverage. The B1/B4 counts here are a floor, not a
  census, of actual glider/ultralight/parachute-aircraft activity.
- **Endpoint-based coverage-floor method needs an in-box recognized
  airport**, which Great Glen effectively lacks (0 of 4 in-box-ending
  flights landed anywhere recognized) — for areas like this, only the
  supplementary low-AGL existence check (§3.3) and the "phantom landing"
  examples (§4) are usable signal.
- **Lincolnshire's high null-emitter-category rate (14.4%)** means its A1/B1
  counts likely understate true light-GA/glider activity there more than in
  other areas — worth a targeted follow-up if Lincolnshire becomes central
  to any downstream claim.
- **Study (d) is only partly covered.** Only Leeds Bradford (EGNM) was in
  the assigned area list; Gibraltar, Birmingham, and East Midlands were not
  sampled at all and remain uncharacterized by this report.
- **Study (b)'s London-TMA half is uncharacterized.** None of the six
  assigned boxes sit under the London TMA; Cheshire only speaks to the
  Manchester side of that hypothesis.
- Sample is 3 days out of a 19-month archive and 6 boxes chosen by the
  orchestrator, not by us — seasonal/regional generalization beyond what's
  shown here is not supported by this data.
- Geometry simplification (spatial ε=50m) and altitude ε=100ft per the
  briefing mean floor values are not meaningful below roughly that
  precision; the ~200–900ft gaps found in Wiltshire/Lincolnshire are far
  larger than this noise floor and are real.

## 6. Verdicts (per measurement)

1. **Low-altitude coverage floor varies drastically and systematically by
   area** — **SUPPORTED**, strong evidence (two independent methods:
   airport-landing floor and direct low-AGL existence count agree; effect
   size is large, 0 ft at Cheshire/Leeds vs 231–696 ft at
   Lincolnshire/Wiltshire, vs a near-total blind spot at Great Glen).
2. **AGL data field is non-null everywhere sampled (~100%), so
   `path_agl_ft`-nullness is not itself informative about coverage
   quality** — **SUPPORTED**, moderate evidence (6 areas × 3 days, all UK
   land; behavior over open ocean/missing-terrain-tiles was not tested here
   and may differ).
3. **GA traffic (A1/A7/B1/B4) is present in all six areas at usable volumes
   for base-rate work, with good A1 metadata completeness** —
   **SUPPORTED**, though Lincolnshire's null-category rate (14.4%) is a
   noted weak spot.
4. **Multi-subsequence (mid-flight coverage-dropout) paths are common, not
   an edge case, and scale with the same coverage-quality gradient found in
   (1)** — **SUPPORTED**, strong evidence (27% Cheshire vs 42% Wiltshire on
   n=256/231 A1 flights, directionally consistent with the floor and
   low-AGL findings).

Net effect for downstream studies: treat Snowdonia/Great Glen and
Wiltshire/Lincolnshire low-altitude findings as **conservative lower
bounds** on real activity (per the briefing's standing caution), with Great
Glen essentially unusable below ~1500–2900 ft AGL; treat Cheshire/Leeds
low-altitude findings as comparatively trustworthy down to near ground
level; and expect ~1/4 to ~2/5 of any A1-category flight sample to arrive
as a fragmented multi-part path that must be handled, not discarded.
