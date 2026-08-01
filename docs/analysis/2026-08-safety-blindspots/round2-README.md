# Round 2 — three operator-posed hypotheses (2026-08-01)

Same method as round 1 (independent analysis agents against the live API, verbatim
queries in each report, headline claims independently re-verified afterwards).
~360 additional API calls. Reports: [hA-roundalt.md](hA-roundalt.md),
[hB-msatrap.md](hB-msatrap.md), [hC-hemispheric.md](hC-hemispheric.md); per-event
evidence in [`evidence/`](evidence/).

## A — "VFR traffic outside ATC control clusters at round-number altitudes, raising collision risk vs a random distribution" — PARTIALLY SUPPORTED

- Clustering is real and cleanly isolated: 26.3 % of squawk-7000 level-cruise time
  sits within ±50 ft of a 500 ft multiple vs 19.3 % for a matched null (same
  aircraft climbing/descending in the same airspace). The whole effect is a single
  spike 0–50 ft below the round number.
- **The internal validation is decisive**: the mod-500 peak exists only in
  QNH-corrected altitude (1.49× excess) and vanishes in raw pressure altitude
  (1.02×) — pilots demonstrably hold the altimeter, and the platform's GFS-derived
  `alt_correction_ft` is thereby validated to ~35–40 ft. Same result at
  3,000–5,500 ft: UK GA does *not* switch to pressure altitude above the TA.
- Vertical co-occupancy is elevated — M ≈ 1.7× uniform (mask-invariant form
  M/M_null = 1.21–1.36) — **but round numbers contribute only ~8 % of it**
  (M_round = 1.08 vs M_envelope = 1.60). The dominant mechanism is that GA all
  cruises in the same 1,900–3,000 ft slice; over hilly terrain that slice narrows
  and M rises to 2.1–2.2 precisely where round-number preference is weakest.
- 2,000 ft QNH is the single dominant UK Class-G cruising level (10–14 % of all
  level time in one 100 ft slab). Suggestive (thin cell, 84 flights): above
  3,000 ft, squawk-7000 traffic uses the VFR +500 semicircular levels at 0.95×
  chance — the rule's separation intent is not being realised.

## B — "Pilots under-plan routes whose enroute MSA exceeds both endpoints' MSA" — PARTIALLY SUPPORTED

- Trap cohort (both endpoints < 500 ft elevation and ≥ 15 km from the barrier,
  n = 292 crossings over 196 sampled days): **33.9 % cross the crest with
  < 1,000 ft clearance** (median 1,229 ft, minimum 272 ft) vs 10.0 % for
  terrain-local-endpoint controls (p = 5.7×10⁻⁴).
- **Entirely a Pennines effect** (42.7 % < 1,000 ft, odds ratio 6.1 vs control;
  dominant route Barton ↔ Sherburn): the Cambrians and Lake District showed zero
  sub-1,300 ft trap crossings and 100 % pre-planned-high profiles — and the
  Cambrian null is not a coverage artefact.
- Behavioural signature: 35.3 % of Pennine trap crossings show reactive-or-no
  climb vs 10.8 % of controls, rising to 59.6 % among sub-1,000 ft crossings; a
  random shuffle of cohort altitudes reproduces the observed clearance
  distribution, i.e. chosen altitude carries almost no information about the
  specific crest. Not weather-driven (effect is stronger on the best-VFR days).
- **A competing structural cause is live**: 77 % of Pennine trap crossings top out
  at 2,000–3,500 ft with a hard ceiling above, and the worst-clearance band is
  exactly where the Manchester TMA base is lowest over the highest terrain — a
  terrain–airspace *sandwich* (connecting directly to round 1's H3 compression
  finding). The under-planning and the sandwich are confounded; disentangling
  them needs airspace polygons.

## C — "Compass-direction VFR cruise-altitude guidance is not consistently used" — SUPPORTED

- US hemispheric rule (14 CFR 91.159), applied with its actual > 3,000 ft AGL
  condition via the per-vertex AGL series: **80.3 % of clean squawk-1200
  level-cruise segments (84.8 % time-weighted) hold the correct parity** —
  far above the 50 % chance baseline (p ≈ 10⁻⁷⁸), far below universal.
- **Strong density gradient**: central Florida 65 % vs Texas 85 % vs rural
  Midwest 93–96 % — compliance is weakest exactly where GA density (and head-on
  risk) is highest.
- 12.4 % of cruise time is at wrong-hemisphere +500 levels, 6.8 % at IFR whole
  thousands while squawking 1200, 11.2 % off-level entirely.
- Under a stated simple model (both aircraft must comply: c², scaled by
  participation f²), the rule as practiced removes ~72 % of head-on same-level
  exposure among participants and **~51 % across all sampled cruise traffic —
  ranging from ~28 % (Florida) to ~66 % (Midwest)**.

## Cross-cutting

1. Both round-1 and round-2 findings converge on **airspace floors as a hidden
   risk-shaping force**: H3 measured vertical bunching under shelves; B finds the
   same lids implicated in terrain-clearance compression over the Pennines.
2. The round-altitude folklore (A) and the hemispheric rule (C) are two sides of
   one result: vertical conventions are real but partial — strong enough to
   concentrate traffic, too weakly followed to deliver their theoretical
   separation benefit, and least followed where traffic is densest.
3. Verification note: agent C reported a "deterministic" 500 when combining
   `squawk_codes` with altitude bounds; post-hoc reproduction attempts (including
   the exact query shape) all returned 200 OK, so this is recorded as
   **unconfirmed** — plausibly transient load from concurrent agents. Its
   client-side workaround makes its results independent of the issue either way.
   The round-1 cursor-pagination 500 remains reproduced (again hit by agent B,
   worked around with pre-narrowed windows).
