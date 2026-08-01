# Aviation safety blindspots: hypothesis testing against the adsb.aero archive

**Date**: 2026-08-01. **Data**: adsb.aero live API (`/api/v1`), archive 2025-01-02 → 2026-08-01,
global coverage. **Total API usage**: ≈ 560 `POST /query` + `GET /flights/{id}` calls.

## What this is

A hypothesis-driven exploration of potential aviation-safety blindspots, using the adsb.aero
query platform as the measurement instrument, deliberately avoiding analyses that are already
done exhaustively elsewhere (generic "close-call hotspot" mining). Each hypothesis was chosen
because this platform can measure something conventional safety analysis structurally cannot:

- a **denominator** that incident reporting never captures (H1 — drop-zone transits),
- **height above terrain** rather than barometric altitude (H2 — en-route low flying),
- **structural exposure concentration** rather than event counts (H3 — airspace-floor compression),
- a **safe-outcome event rate** that nobody publishes per-airport (H4 — go-arounds).

Testing was performed by four independent analysis agents plus a data-quality validator, each
working only against the public API, with every final query JSON recorded verbatim in the
per-hypothesis reports in this directory. Headline claims were then independently re-verified
against the API (single-flight lookups; re-derivation of key aggregates from the saved
evidence files) before this synthesis was written.

| # | Hypothesis | Verdict | Report |
|---|---|---|---|
| — | Data-quality frame: coverage floors, AGL availability, path fragmentation | (measurements) | [coverage.md](coverage.md) |
| H1 | Active parachute drop zones are transited by non-participating traffic at a rate incident reporting never sees | **Partially supported** — and sharpened | [h1-dropzones.md](h1-dropzones.md) |
| H2 | Fixed-wing GA low-AGL exposure concentrates en-route in terrain corridors, away from airfield-centric measurement | **Partially supported** — inverted | [h2-lowagl.md](h2-lowagl.md) |
| H3 | Controlled-airspace floors compress VFR traffic into thin bands just under their ceilings | **Partially supported** | [h3-compression.md](h3-compression.md) |
| H4 | Go-around rates differ systematically by airport, wind-linked at terrain airports, invisible in public statistics | **Supported** | [h4-goarounds.md](h4-goarounds.md) |

## The data-quality frame (read first)

The validator's findings ([coverage.md](coverage.md)) bound everything below:

- **AGL data availability is ~100 % over UK land** — but the **receiver coverage floor varies
  enormously**: Manchester/Liverpool/Leeds Bradford are tracked to touchdown (median last-seen
  AGL ≈ 0 ft); small rural strips lose aircraft 200–900 ft AGL; the Great Glen is effectively
  blind below ~1,500–2,900 ft AGL.
- **Mid-flight coverage dropouts are normal, not exceptional**: 27 % (Cheshire) to 42 %
  (Wiltshire) of light-GA flights have fragmented multi-subsequence paths. Trajectory analyses
  must tolerate gaps; a leg's endpoints are where *coverage* started and stopped, not
  necessarily where the flight did.
- Consequence: every low-altitude count in this study is a **lower bound**, and absence of
  low-altitude data in remote Scotland is *not* evidence of absence of low flying.

## H1 — Drop-zone transits: the unmeasured denominator

**Hypothesis**: non-participating aircraft routinely transit active parachute drop zones during
live jumping; the true exposure rate is far higher than airprox reporting shows.

**Method**: jump aircraft and DZs identified *empirically* (short sorties returning to their
start point after climbing > 9,500 ft — a signature nearly unique to jump planes), individual
lifts extracted from trajectories, an 8-minute exposure window modelled after each detected
exit, and all non-participating traffic through a 2.5 km circle temporally joined against
those windows. 2,560 lifts over 161 active jump days at Langar, Headcorn, Old Sarum and
Netheravon, Apr–Jul 2026 plus a 2025 replication.

**Results**:

- 892 non-participating transits below 16,000 ft on active jump days (5.5/day); 35 inside a
  live exposure window; **14 co-altitude with the modelled parachutist column** — every one
  below 4,000 ft, in the canopy band. 8 of the 14 are unambiguously civil GA.
- **Against chance** (within-day permutation tests, two null models): in aggregate, transits
  coincide with live drops at *half* the chance rate (35 vs ~72 expected, p < 0.002) — but
  that protection is produced by ATC sequencing the *jump aircraft* at the one TMA-adjacent
  site (Headcorn). **Below 10,000 ft, coincidence runs exactly at chance** (23 vs 27.7,
  p = 0.18): where UK DZs have only a charted circle and no airspace protection, there is no
  measurable deconfliction at all. Co-altitude events sit at the ~98th percentile of the null.
- Annualised: ~113 in-window transits and ~45 co-altitude exposure events/year at these four
  sites alone, vs a small handful of DZ-related airprox reports nationally — an
  under-measurement ratio of **10–50×**, as a lower bound (a third of low transits broadcast
  no emitter category; gliders and most microlights are invisible to ADS-B).

**Blindspot statement**: the deconfliction that exists protects the controlled-airspace
interface, not the drop zone. A risk picture built from incident reports (few reports → low
risk) is measuring reporting behaviour, not exposure. The exposure denominator is directly
recoverable from ADS-B and nobody appears to be computing it.

## H2 — En-route low-AGL over terrain: hypothesis inverted

**Hypothesis**: a substantial share of fixed-wing GA low-height exposure (< 700 ft AGL) is
en-route over terrain, concentrated in valley corridors, where airfield-centric risk models
don't look.

**Results** (56,000 km² of UK upland, 84 sampled days, 4,561 flights, 663,715 path segments):

- **Refuted for civil GA**: only **4.7 %** of civil fixed-wing low-AGL minutes occur ≥ 8 km
  from an airfield (2.2 % at a 500 ft threshold); civil GA low flying is **60× denser** near
  airfields than away; only 0.38 % of fixed-wing traffic crossing these uplands produces any
  qualifying en-route low exposure. The airfield-centric risk model is a *good* model of
  civil-GA low-height exposure.
- **Corridor concentration confirmed — but the occupants are military trainers**: RAF
  Texan/Phenom/Prefect trainers (which do transmit ADS-B, contrary to the working assumption)
  generate 90 % of fixed-wing en-route low-AGL minutes, 78 % of it in three nameable corridors
  (Upper Wye, Conwy valley, Caernarfon/Menai) that are the *published MOD low-flying system* —
  the most measured low airspace in the UK, not a blindspot.
- **The genuinely under-measured population is rotary**: HEMS/SAR helicopters (AW139, S-92,
  H145, H135, AW189, AW149) accumulate **1,812 en-route low-AGL minutes — 1.9× all fixed-wing
  combined** — median AGL down to 286 ft, in a distinct corridor set (Menai/Anglesey,
  Ogwen–Conwy, Brecon Beacons, Loch Ness, Thirlmere–Kirkstone), flown by operational necessity
  in weather and darkness the trainers avoid.
- Individual civil outliers exist and are verifiable — e.g. `407f8f:2025-06-18T13:15:57Z`, a
  Sky Ranger microlight crossing the Clwydian ridge at a server-verified **154 ft AGL**,
  110 km from either endpoint — but they are a residue: ~50 minutes of true cross-country
  valley transiting below 700 ft across 84 days.

**Blindspot statement**: if anyone should worry about unmeasured mountain low-flying, it is
HEMS/SAR rotary operations — not touring GA, and not the trainers (already counted by the
MOD). Redirecting the CFIT/wire-strike exposure question at that population is the productive
follow-up.

## H3 — Vertical compression under airspace floors

**Hypothesis**: controlled-airspace floors compress VFR traffic into thin bands just below
their ceilings — a structural collision-exposure multiplier invisible to per-event analysis.

**Results** (1,112 flights, 6 sample days summer + winter, three areas):

- **Manchester Low-Level Route** (1,300 ft ceiling): **69 % of all light-GA flight-time packed
  into 1,000–1,500 ft**; concentration ratio 1.9–2.4× the open-Class-G control; the busiest
  250 ft bin tops out 50 ft under the ceiling. Sharp, ceiling-anchored, replicated across
  seasons.
- **London TMA shelf, 2,500 ft base** (Ockham/Fairoaks area): peak band 1,750–2,000 ft
  (250–500 ft below the base), concentration 1.3–1.6× control — and **absolute traffic density
  in the peak band 1.8–2.5× control**: under the TMA shelf, concentration and volume compound.
- Control (Shropshire open Class G): flat plateau, no 250 ft band exceeding 14 %.
- A clean severity gradient: the lower/tighter the ceiling, the sharper the bunching. For the
  LLR, relative concentration is extreme while absolute density stays below control (its raw
  volume is small) — both readings reported, not reconciled into one number.

**Blindspot statement**: airspace design displaces rather than removes mid-air-collision
exposure, and the displaced exposure concentrates just under shelf bases. The effect is
directly and cheaply measurable (19 API calls); airspace-change impact assessments currently
argue about it qualitatively.

## H4 — Go-around clusters: a recoverable rate nobody publishes

**Hypothesis**: go-around rates differ chronically between airports in ways public statistics
don't show, with terrain/wind airports elevated, wind-linked, and runway-direction-specific.

**Results** (6,703 approaches, 86 individually-listed go-arounds; Jan–Jul 2026; ERA5 wind):

- **Rates per 1,000 approaches**: Gibraltar 25.7, Leeds Bradford 15.4, Bilbao 14.9, Madeira
  14.8 vs flat controls Birmingham 6.8 and East Midlands 3.5 — pooled 2.99×, day-block
  permutation p = 0.0065. Robust to every detector-threshold variation tried.
- **The wind interaction is the headline**: on the *same calendar days*, gale days (gust
  ≥ 45 km/h) multiply Leeds Bradford's rate **11.7×** while Birmingham moves 0.32× and East
  Midlands 1.19×. All four terrain airports show 4.7–12.4×; neither flat control moves
  (pooled p < 0.0001). Same-synoptic-weather sampling makes this an interaction, not "windy
  days are bad everywhere".
- **Independent corroboration not designed for**: 62 % of terrain-airport go-arounds ended in
  a diversion vs **0 of 18** at the controls (p = 9×10⁻⁷) — the signature of a *condition*
  that persists on the retry, not a one-off spacing event.
- **Runway asymmetry**: Madeira RWY 23 runs 45.4/1,000 vs RWY 05's 3.4/1,000 (13×,
  p = 1.1×10⁻⁸), on the *less-used* direction. Gibraltar and Leeds Bradford lean the same way
  but are underpowered at these counts.
- Detectability was explicitly controlled: Gibraltar loses ADS-B ~240 ft AGL and Madeira
  ~630 ft AGL (coverage floors measured per-airport), which biases *against* the finding at
  the two most-affected airports; the ordering survives detectability matching.

**Blindspot statement**: a chronically elevated, wind-multiplied, direction-specific go-around
rate is a leading indicator of approach instability that current public statistics do not
expose at per-airport granularity — and it is recoverable from ADS-B alone at ~220 API calls
per six-airport study, with every event individually auditable.

## Cross-cutting conclusions

1. **The denominators are the blindspot.** All four studies reduce to the same structural gap:
   safety systems count *events* (airprox reports, accident reports) but not *exposure*
   (transits during live drops, flight-seconds per altitude band, approaches per go-around).
   ADS-B archives with temporal-join and AGL capability make the denominators cheap.
2. **Two hypotheses survived contact with data in modified form.** H1's "no deconfliction"
   framing was wrong (there is deconfliction — in controlled airspace); H2's "GA valley
   transits" framing was wrong (it's HEMS/SAR and already-counted military trainers). The
   corrections are more useful than the originals — both redirect attention to a sharper
   target population.
3. **Coverage floors are the limiting instrument error.** Per-airport/per-area last-seen-AGL
   distributions should accompany any low-altitude claim from this archive; the validator's
   method (median last AGL of flights ending at a recognised airport) is cheap and repeatable.
4. **Every quantitative claim here is a lower bound** on the underlying activity: non-equipped
   aircraft (gliders, many microlights, most military fast jets) are structurally invisible,
   and receiver floors clip the low-altitude tail.

## Platform observations (adsb.aero itself)

Incidental findings from ~560 API calls, possibly worth fixing:

1. **Cursor pagination returns HTTP 500** on large `include_path: true` result sets,
   deterministically (reproduced independently by two agents: Headcorn DZ circle, week of
   2026-05-25; and the H4 approach queries). Workaround used: subdivide the time range until
   a single page suffices.
2. `include_path: false` still returns `path_agl_ft` and `alt_correction_ft` (only
   `path`/`timestamps`/scalar series are nulled) — undocumented; useful for cheap AGL
   screening but presumably an unintended payload cost.
3. Default-UA requests from Python urllib receive 403 (edge UA filtering); any custom
   User-Agent passes.
4. The 250-H3-cell geometry cap surfaces as a clear 422; a ~3–4° box is the practical limit.
5. Pagination cursors stay non-null through empty windows until the window floor is reached —
   harmless once `start_from` is set tightly, surprising otherwise.
6. Emitter-category null rates vary regionally (14.4 % in Lincolnshire vs 0.7–8 % elsewhere) —
   may be worth a look at the Doc 8643 synthesis coverage for types common there.

## Reproducibility

Every per-hypothesis report records its final query JSONs verbatim; each cited flight resolves
via `GET /api/v1/flights/{flight_id}`. Small evidence aggregates are committed under
[`evidence/`](evidence/); bulky per-event CSVs (5,196 DZ circle-passes, 7,208 approach
records, 2,131 low-AGL runs) were kept out of the repo but are regenerable from the documented
queries. Key aggregates (H3's concentration histogram, H1's worst-case transit, H2's minimum-AGL
outlier, H4's double go-around) were re-derived or re-fetched independently of the original
analyses before publication.
