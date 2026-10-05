# Hypothesis C — Compliance with the US hemispheric cruise-altitude rule (14 CFR 91.159)

## 1. Hypothesis restated

VFR guidance tying cruise altitude to magnetic course (above 3,000 ft AGL:
magnetic course 0–179° → odd thousands + 500 ft; 180–359° → even thousands +
500 ft) is not consistently followed. This is the principal systemic
mitigation against head-on VFR cruise conflicts, and its real-world
compliance rate is unmeasured in public literature. We test it against
1200-squawking (non-ATC-tracked-code) light single-engine (A1) traffic in
three US regions using the adsb.aero historical archive.

## 2. Method

### 2.1 Regions and days

| region | box (w,s)–(e,n) | magnetic declination used | notes |
|---|---|---|---|
| florida | (-82.5,27.5)–(-80.8,29.2) | **−7° (7°W)** | central FL, high flight-training density (Daytona/ERAU corridor) |
| texas | (-98.5,29.8)–(-96.5,31.5) | **+2° (2°E)** | Austin–Houston corridor, near the US agonic line |
| midwest | (-94.5,40.5)–(-92.5,42.0) | **+1° (1°E)** | N. Missouri / S. Iowa border, lower-density GA |

Declination sign convention verified two ways: (a) task's own formula,
`magnetic = true − declination`, declination positive-East; (b) the
pilot mnemonic "variation west, add; variation east, subtract" — for FL
(7°W ⇒ declination = −7): magnetic = true − (−7) = true + 7 (**add** for
west variation, matches). For TX (2°E ⇒ declination = +2): magnetic =
true − 2 (**subtract** for east variation, matches). Both checks agree;
used as-is, no sign flip needed.

Sample days (same 6 across all 3 regions, mixing weekday/weekend/season,
none on federal holidays): **2026-01-14 (Wed), 2026-02-21 (Sat),
2026-03-18 (Wed), 2026-04-25 (Sat), 2026-05-13 (Wed), 2026-06-20 (Sat)**.

None of the three boxes exceeded the 250-H3-cell geometry limit (each is
≈28,000–32,000 km², well under the ≈440,000 km² ceiling at res-4); no
tiling was needed.

### 2.2 Server bug discovered and workaround (read before reusing this method)

**`trajectory_intersects` returns HTTP 500 whenever `altitude_min`/
`altitude_max` (either bound, either `ft` or `fl` ref) is combined with
`squawk_codes` in the same predicate object, as soon as the combination
would actually match rows** (a range that matches zero rows short-circuits
and returns `[]`, masking the bug — this cost real time to isolate).
Isolated by systematically re-adding one constraint at a time; confirmed
reproducible (not flaky) with repeat calls. Separately discovered:
**`altitude_min_ref`/`altitude_max_ref: "fl"` expects flight-level units
(hundreds of feet — FL035 = `35`), not feet** — this is not stated in the
briefing and silently returns zero rows if you pass raw feet (e.g. `3500`
reads as FL3500 = 350,000 ft, above all traffic).

**Workaround adopted**: drop the server-side altitude bound whenever
`squawk_codes` is used; instead query on `altitude_min`/`altitude_max`
(`ft` ref, which *does* work when squawk_codes is absent) `AND
emitter_category:["A1"]` only, fetch `include_path:true`, and apply the
squawk‑1200 filter **client-side** from the returned `squawk_runs` field
(needed anyway to build point-level QNH/track/AGL series). This is a
deviation from the literal predicate given in the task prompt, forced by
the server bug — flagging per the "adapt only where data forces it"
instruction.

### 2.3 Query volume management

Central Florida in particular has very high GA/flight-training volume
(≈1,000–2,400 A1 flights/day even after the altitude filter — consistent
with the Embry-Riddle/ATP corridor). To stay within the include_path
size guidance (≤500) and the overall call budget, each region×day was
queried over a **fixed daytime UTC window** rather than the full 24 h,
sized per region's typical volume:

| region | window (UTC) | rationale |
|---|---|---|
| florida | 17:00–19:00 (2 h) | highest volume region; 2 h keeps counts 47–275/day |
| texas | 17:00–21:00 (4 h) | moderate volume; counts 109–322/day |
| midwest | 12:00–00:00 (12 h, full daytime) | lower volume; needs the full day to get 42–191/day |

All windows land within local daytime (adjusting ±1 h for DST across the
sample, noted as a caveat). This is a scope reduction versus "whole day
per region×day" that the query-volume server bug (§2.2, which prevented
a tight server-side prefilter) made necessary to stay in budget — flagged
per instructions.

### 2.4 Exact query template used (18 calls, one per region×day)

```json
{
  "end_date": "<WINDOW_END>",
  "start_from": "<WINDOW_START>",
  "window_days": 1,
  "include_path": true,
  "limit": 400,
  "match": {"and": [
    {"trajectory_intersects": {
      "geometry": <BOX>,
      "altitude_min": 3500, "altitude_min_ref": "ft",
      "altitude_max": 12500, "altitude_max_ref": "ft"
    }},
    {"emitter_category": ["A1"]}
  ]}
}
```

All 18 calls returned `cursor: null` (single page) — no pagination
workaround needed. Yield: 3,021 flights total (florida 986, texas 1,241,
midwest 794).

### 2.5 Client-side processing

For each flight, for each path subsequence (never bridging a
subsequence/coverage gap, per the Lessons file):
- Built point-level series: QNH-ft = pressure Z + stepwise
  `alt_correction_ft`; AGL from stepwise `path_agl_ft`; track from
  stepwise `path_tracks`; ground speed from stepwise `path_gs`; squawk
  from stepwise `squawk_runs`. (All these "per-subsequence" stepwise
  series were found to be safely flattenable into one flight-wide
  sorted timeline for point-time lookups — their sub-list boundaries do
  **not** align with `path`'s subsequence boundaries, e.g. one flight had
  12 path subsequences but only 5 squawk-run groups and 1
  alt-correction group; only the *segmentation* step must respect
  `path`'s own subsequence boundaries.)
- Greedy level-cruise segment extraction: extend a run while QNH stays
  within a 200 ft band (≈±100 ft), ground speed > 80 kt, squawk == "1200",
  AGL > 3,000 ft, and circular track spread ≤ 15°, point by point; accept
  runs ≥ 180 s.
- Per accepted segment: median QNH altitude, circular-median true track
  (mean-direction + median-of-unwrapped-deviations, to avoid 0°/360°
  wraparound bias), magnetic course = median track − regional declination.
- Classified: VFR-level (within ±150 ft of a x,500 ft level) →
  correct/wrong hemisphere by parity of the thousands digit vs. magnetic
  course hemisphere; IFR-level (±150 ft of a whole thousand); off-level
  (neither).
- Edge-case flags: **near_squawk_change** (any squawk transition, of any
  code, within 30 min of the segment start/end — likely
  transitioning to/from ATC flight-following) — excluded from the main
  compliance denominator, reported separately; **near_boundary**
  (magnetic course within 3° of 000°/180°) — reported for the
  declination-sensitivity discussion. Turning segments (track spread
  > 15°) are excluded **by construction** during segmentation, not as a
  post-hoc filter — no separate count is meaningful.

Result: **1,607 level-cruise segments** from 3,021 flights (most flights
contributed 0–3 segments; many short/local hops never produced a
qualifying ≥180 s level run).

## 3. Results

### 3.1 Headline compliance (VFR-level segments only, excluding the
"near a squawk change" edge case — 890 of 1,239 VFR-level segments)

| metric | value |
|---|---|
| segment-count compliance | **715/890 = 80.3%** |
| time-weighted compliance | **148.1 h / 174.7 h = 84.8%** |
| flight-deduplicated compliance (one segment/flight, longest) | 338/428 = 79.0% |
| binomial test vs. 50% baseline (segment-count) | p = 4.3×10⁻⁷⁸ |
| binomial test vs. 50% baseline (flight-deduplicated) | p = 7.4×10⁻³⁵ |

The flight-deduplicated figure (79.0%) tracks the raw segment-count figure
(80.3%) closely, so the headline number is not an artifact of a few
aircraft contributing many correlated segments (201 of 428 unique flights
did contribute >1 clean VFR segment, typically from coverage-gap
fragmentation of one long cruise, not independent legs).

### 3.2 Time-weighted breakdown of ALL cruise-segment time (excl.
near-squawk-change segments; n = 1,258 segments, 213.2 h total)

| category | hours | % of total |
|---|---|---|
| VFR-level, correct hemisphere | 148.1 h | 69.5% |
| VFR-level, wrong hemisphere | 26.5 h | 12.4% |
| IFR-level (whole thousand) while squawking 1200 | 14.6 h | 6.8% |
| off-level (neither) | 24.0 h | 11.2% |

### 3.3 By region (VFR-level, clean)

| region | n segments | seg-compliance | time-compliance | p (binomial) |
|---|---|---|---|---|
| florida | 315 | 65.1% | 65.2% | 9.5×10⁻⁸ |
| texas | 307 | 84.7% | 88.3% | 6.9×10⁻³⁷ |
| midwest | 268 | 93.3% | 95.9% | 2.0×10⁻⁵³ |

All three regions individually reject the 50%-chance null, but with a
**large and consistent gradient**: central Florida (busiest, most
training/pattern traffic, most Class B/C-adjacent airspace) is markedly
less compliant than Texas, which is markedly less compliant than the
lower-density Midwest box. This is the most striking substantive finding:
compliance appears to correlate inversely with local traffic
density/complexity, not to be a uniform national behavior.

### 3.4 By altitude band (VFR-level, clean)

| band | n segments | seg-compliance | time-compliance |
|---|---|---|---|
| 3,500–5,500 ft | 413 | 79.2% | 84.3% |
| 5,500–9,500 ft | 344 | 84.9% | 88.4% |
| ≥9,500 ft | 133 | 72.2% | 74.9% |

Compliance is fairly flat across the low two bands and dips somewhat in
the highest band (fewer, longer cross-country legs — but also the
smallest sample, 133 segments, so this dip should be read cautiously).

### 3.5 Non-VFR-level activity while squawking 1200

- **IFR-level (whole thousands) while squawking 1200**: 150 segments,
  19.1 h. This does not necessarily mean non-compliance — 1200 + whole
  thousand is a legitimate combination for e.g. a VFR flight below 3,000
  AGL transitioning (though our AGL gate should exclude that), practice
  IFR training VFR-squawking, or simply climbing/descending through a
  thousand that happened to plateau briefly under our 180 s/±100 ft
  gates. Reported as a distinct bucket, not folded into "non-compliant."
- **Off-level** (neither convention): 218 segments, 27.0 h — plausibly
  ATC-requested altitudes even while squawking 1200 transponder-wise
  (code doesn't always update instantly), terrain/weather deviations, or
  genuinely idiosyncratic flying.

### 3.6 Edge cases excluded/flagged

| edge case | n segments | share |
|---|---|---|
| within 30 min of *any* squawk transition | 434 / 1,607 | 27.0% of all segments |
| magnetic course within 3° of 000°/180° boundary (VFR clean only) | 52 / 890 | 5.8% (5.4% of clean VFR time) |

The 30-min-squawk-change exclusion rate is substantial (27%) — consistent
with the briefing's note that 1200 + flight-following churn is common;
these segments are excluded from all compliance tallies above but were
not separately re-classified (no assumption is made about their true
compliance either way).

### 3.7 Magnetic-declination sensitivity (±3°)

| perturbation | segments flipping classification | new overall compliance |
|---|---|---|
| declination +3° | 27 / 890 (3.0%) | 80.0% |
| declination −3° | 19 / 890 (2.1%) | 80.0% |
| nominal | — | 80.3% (seg-count) |

Only 5.8% of VFR-clean segment-time sits within 3° of the 000°/180°
parity boundary in magnetic course (§3.6), and flipping the declination
assumption by ±3° changes the headline compliance figure by well under
1 percentage point. **The regional declination approximations used are
not a material source of error for this study's conclusions.**

### 3.8 Head-on-exposure-removal estimate

Model (stated plainly): consider two aircraft on opposite (≈180°-apart)
courses, both at a VFR half-level, both drawn at random from the observed
population. Under **perfect** compliance, opposite-direction VFR
half-level traffic is *always* separated by parity (different
odd/even-thousand class ⇒ ≥1,000 ft apart), i.e. the rule removes
~100% of same-level head-on exposure among that subpopulation. Under
**measured compliance c** (probability a random VFR-half-level flyer is
on the correct parity for their course), a random opposite-direction pair
is correctly separated only if *both* comply, so the fraction of
same-level head-on exposure removed (relative to a no-rule/50%-chance
baseline) ≈ **c²**. Scaling to *all* cruise traffic in the sampled
altitude band requires both aircraft in the pair to be VFR-half-level
participants in the first place — multiply by **f_vfr²**, where f_vfr is
the observed time-share of cruise-segment time spent at a VFR half-level
at all (vs. IFR-level or off-level).

| region | c (time-weighted) | c² | f_vfr | f_vfr²·c² |
|---|---|---|---|---|
| florida | 0.652 | 0.426 | 0.813 | 0.281 |
| texas | 0.883 | 0.781 | 0.853 | 0.567 |
| midwest | 0.959 | 0.919 | 0.847 | 0.659 |
| **all regions combined** | **0.848** | **0.719** | **0.839** | **0.506** |

Reading: among VFR-half-level flyers only, the rule as actually practiced
removes an estimated **72%** of the head-on same-level exposure it would
remove under perfect compliance. Across *all* sampled cruise traffic in
this altitude band (including flights that don't use the convention at
all), the rule is estimated to remove roughly **51%** of head-on
same-level pair-exposure versus a hypothetical world with no altitude
convention. The regional spread is large (28% Florida to 66% Midwest),
tracking the compliance gradient in §3.3 — i.e. **the rule's real-world
protective value appears to be substantially lower exactly where GA
traffic density is highest**, which is also where the head-on risk itself
is presumably greatest. This is the most safety-relevant single number
this study produces, and it should be read as an order-of-magnitude
estimate under a simple, explicitly stated model, not a validated risk
figure.

## 4. Example flight_ids

**Clean compliant cruises** (VFR-level, correct hemisphere, ≥300 s, not
near a squawk change):
- `a41023:2026-06-20T15:10:29Z` — RV12, midwest, 8,500 s at 8,487 ft QNH, track 244° (mag 243°, needs even ✓, level 8,500 = even-thousand base ✓)
- `a350a9:2026-03-18T18:30:06Z` — P32T (Piper Saratoga), florida, 8,312 s at 10,562 ft, track 341° (mag 348°, needs even ✓, level 10,500 ✓)
- `a56279:2026-05-13T21:34:15Z` — DA40, midwest, 7,263 s at 13,460 ft, track 86° (mag 85°, needs odd ✓, level 13,500 ✓)
- `a085ba:2026-05-13T13:34:20Z` — C172, midwest, 6,627 s at 5,496 ft, track 98° (mag 97°, needs odd ✓, level 5,500 ✓)

**Clean wrong-hemisphere cruises** (VFR-level, incorrect parity for
course):
- `ac9688:2026-05-13T17:28:48Z` — BE33 (Bonanza), texas, 4,039 s at 10,471 ft, track 88° (mag 86°, needs odd, flying even 10,500 ✗)
- `a053ff:2026-02-21T18:49:44Z` — BE36 (Bonanza), florida, 3,683 s at 9,460 ft, track 331° (mag 338°, needs even, flying odd 9,500 ✗)
- `aa13dc:2026-01-14T17:52:53Z` — C172, florida, 3,052 s at 4,469 ft, track 11° (mag 18°, needs odd, flying even 4,500 ✗)
- `a920ed:2026-03-18T17:07:05Z` — C152, florida, 2,980 s at 4,532 ft, track 1° (mag 8°, needs odd, flying even 4,500 ✗) — not a boundary artifact (8° from 000°, outside the ±3° sensitivity band)

**1200-squawking whole-thousand cruisers** (IFR-level while VFR-code):
- `a56279:2026-05-13T15:53:30Z` — DA40, midwest, 4,960 s at 13,917 ft (≈FL140), same aircraft as a compliant example above on a different leg that day
- `a41023:2026-06-20T18:38:41Z` — RV12, midwest, 4,110 s at 8,856 ft (≈9,000)
- `a0a02b:2026-03-18T20:10:14Z` — PA27, texas, 2,677 s at 8,005 ft (≈8,000)

## 5. Caveats

- **Server bug forced a method deviation** (§2.2): the literal query DSL
  given in the task prompt (`squawk_codes` + `altitude_min`/`altitude_max`
  in one `trajectory_intersects`) 500s on the live server whenever it
  would match real data. Worked around by filtering altitude via the
  server (works fine without squawk) and squawk-1200 client-side from
  `squawk_runs`. This is functionally equivalent (same final filter set)
  but cost extra diagnostic calls and is worth fixing server-side.
- **Time-window subsampling, not full-day coverage** (§2.3): each
  region×day used a fixed daytime window (2–12 h depending on regional
  traffic volume) rather than the full 24 h, to stay within
  `include_path` size guidance and the call budget. This is a
  representative daytime slice, not exhaustive; night/early-morning
  cruise traffic (a small fraction of GA activity) is essentially
  unsampled. DST shifts the exact local time of the UTC window by ±1 h
  across the 6 sample days — all windows remain within daytime regardless.
- **QNH-correction interpolation is stepwise-hold**, per the briefing;
  this slightly blurs the ±150 ft level-band test and biases *toward*
  undercounting clean level-keeping (segments that are truly level get
  occasionally kicked out of the ±100 ft band by correction-lag noise
  near a QNH-update boundary) — this makes the compliance estimate, if
  anything, a **conservative** (slightly low) figure, not inflated.
- **Squawk 1200 as a "no ATC service" proxy is imperfect**: VFR flight
  following keeps 1200 (or a discrete code, in which case it drops out of
  our filter entirely) — most flights we see squawking 1200 mid-cruise
  are plausibly *not* receiving active ATC altitude direction, which is
  the population the rule is meant to govern, but this is not guaranteed
  for every segment.
- **The 30-min-near-squawk-change exclusion (27% of all segments) is a
  meaningful chunk of data set aside** — we make no compliance claim
  about it either way; if these segments compliance-skew differently
  from the retained sample (plausible, since transitioning to/from
  flight following could correlate with ATC-assigned altitudes), the
  headline figure could shift in either direction. Not quantified here.
- **Track-spread turning exclusion is baked into segmentation**, not
  measured separately — we cannot report "how many candidate segments
  were rejected for turning" as a standalone count without re-running a
  parallel, unconstrained segmentation pass, which was out of scope.
- **Mountainous AGL ambiguity**: not relevant — all three regions
  (central FL, TX Gulf coastal plain, Iowa/Missouri border) are flat;
  AGL-vs-terrain-model error is not expected to materially affect the
  3,000 ft AGL gate here (unlike UK Highland studies in this session's
  other work).
- **Declination approximations** (§2.1, sensitivity §3.7): fixed,
  single-value-per-region declinations were used rather than a
  location/date-exact IGRF lookup. Sensitivity analysis (±3°) shows this
  matters little for the headline number (<1 pt), because only ~5.8% of
  VFR cruise time sits within 3° of a parity boundary.
- **Coverage/absence caveats from the briefing apply**: ADS-B-only
  (no gliders/vintage/some military — largely moot here since we filter
  to A1/light-aircraft anyway); geometry/altitude simplification (ε=50 m,
  100 ft) is well below our ±150 ft classification tolerance and 180 s
  duration gate, so it should not materially affect classification.
- **Sample is 3 US regions, 6 days, ~200 h of qualifying cruise time out
  of a 19-month global archive** — chosen for "good GA volume, mostly
  outside Class B/C cores" per the task, but Florida in particular turned
  out to be busier/more complex than a typical "outside Class B/C"
  assumption would suggest (Daytona/ERAU training corridor). Findings
  should not be read as a national compliance rate; the regional spread
  (65–95%) itself is the headline finding, more than any single pooled
  number.
- **Canada/Mexico border areas and non-US airspace were not sampled** —
  irrelevant here since 91.159 is a US-specific rule, but noted per
  briefing template.

## 6. Verdict

**SUPPORTED**, with meaningful evidence quality caveats.

The hypothesis — that hemispheric-rule compliance is *not* uniformly
followed — is clearly supported: overall clean-segment compliance among
VFR-half-level 1200-squawking A1 traffic is **80–85%**, reliably above
chance (p ≪ 10⁻³⁰ by multiple estimators) but **far from universal**.
Roughly 1 in 5 VFR-level cruise segments (and ~15% of VFR-level cruise
time) is at the wrong-hemisphere level. Compliance varies substantially
by region (65% Florida to 93–96% Midwest), which is itself a novel,
actionable finding: the rule's real-world protective value is weakest
exactly where traffic density (and plausibly conflict risk) is highest.
The estimated head-on-exposure-removal fraction (~51% pooled, ~28–66% by
region, under a simple stated model) quantifies the safety-relevant gap
directly. Evidence strength: **moderate-to-strong** — large sample
(1,607 segments / 3,021 flights, 3 regions × 6 days), multiple
independent robustness checks (segment-count vs. time-weighted vs.
flight-deduplicated compliance all agree within ~5 points; declination
sensitivity negligible), but bounded by daytime-window subsampling (not
full-day coverage), the imperfect 1200-as-no-ATC-service proxy, and the
27% of segments excluded near squawk transitions whose true compliance
is unknown.
