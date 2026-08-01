# Hypothesis A — Round-number altitude clustering and vertical co-occupancy in UK Class G

**Verdict: PARTIALLY SUPPORTED (moderate-to-strong evidence).** Round-number
clustering is real, statistically solid and cleanly isolated — but it is *not*
the main driver of vertical co-occupancy. The headline collision-exposure
multiplier is confirmed; the mechanism the hypothesis names accounts for only a
small part of it.

---

## 1. Hypothesis restated

> VFR traffic outside ATC control clusters at round-number altitudes,
> increasing vertical co-occupancy (collision risk) compared to a random
> altitude distribution. Blindspot framing: everyone knows pilots fly round
> numbers, but nobody quantifies the resulting collision-exposure multiplier,
> and mid-air risk models often implicitly assume vertical spread.

Two separable claims, tested separately:

- **A1 — clustering exists.** Level-cruise time concentrates near multiples of
  500 ft more than chance.
- **A2 — clustering raises co-occupancy.** The resulting vertical distribution
  makes two independent aircraft share a 100 ft slab more often than a random
  (uniform) altitude distribution would, by a multiplier **M**.

---

## 2. Method

### 2.1 Areas (UK Class G, away from major CTAs)

| area | box (w, s)–(e, n) | character |
|---|---|---|
| shropshire | (−2.7, 52.35)–(−2.1, 52.75) | hilly, terrain ~300–1700 ft |
| devon | (−4.3, 50.6)–(−3.3, 51.1) | hilly (Dartmoor/Exmoor fringes) |
| lincolnshire | (−0.9, 53.4)–(0.0, 53.8) | flat, near sea level |

All three are well under the 250-H3-cell geometry limit; no tiling needed.

### 2.2 Sample days — 24 days across Mar–Jul 2026

`2026-03-07 (Sat), 03-21 (Sat), 03-28 (Sat), 04-04 (Sat), 04-11 (Sat),
04-15 (Wed), 04-22 (Wed), 05-03 (Sun), 05-09 (Sat), 05-16 (Sat), 05-20 (Wed),
05-28 (Thu), 06-03 (Wed), 06-07 (Sun), 06-13 (Sat), 06-17 (Wed), 06-20 (Sat),
06-25 (Thu), 07-04 (Sat), 07-08 (Wed), 07-11 (Sat), 07-15 (Wed), 07-22 (Wed),
07-28 (Tue)`

14 weekend / 10 weekday. Mix chosen for the flying season; days were **not**
screened for weather after the fact (some are visibly poor — 2026-03-28 and
04-04 yielded 0.21 h and 0.22 h of qualifying cruise across all three boxes).

### 2.3 Query used — verbatim (one per area × day; 3 × 24 = **72 calls total**)

```json
{
  "end_date": "<DAY+1>",
  "start_from": "<DAY>",
  "window_days": 1,
  "include_path": true,
  "limit": 500,
  "match": {
    "and": [
      {"trajectory_intersects": {"geometry": {
        "type": "Polygon",
        "coordinates": [[[-2.7,52.35],[-2.1,52.35],[-2.1,52.75],[-2.7,52.75],[-2.7,52.35]]]
      }}},
      {"emitter_category": ["A1"]}
    ]
  }
}
```

(substitute the box per area; `devon` =
`[[-4.3,50.6],[-3.3,50.6],[-3.3,51.1],[-4.3,51.1],[-4.3,50.6]]`,
`lincolnshire` = `[[-0.9,53.4],[0.0,53.4],[0.0,53.8],[-0.9,53.8],[-0.9,53.4]]`).

**Every one of the 72 calls returned `cursor: null` on the first page** — no
pagination, so no exposure to the known cursor-500 bug. 3182 A1 flight legs
returned. All filtering below is client-side.

### 2.4 Client-side pipeline

Per flight, per path subsequence, per point:

1. Keep only points **inside the box** (297 643 points dropped as outside — the
   API returns the whole leg, not the in-box clip).
2. `path_gs > 70 kt` (28 421 points dropped).
3. **≥ 8 km from any airfield** — OurAirports `airports.csv`
   (`curl -A "x" https://davidmegginson.github.io/ourairports-data/airports.csv`),
   types `small_airport` / `medium_airport` / `large_airport`, 916 airfields in
   the UK window. 69 839 points dropped. This is the circuit-height control.
4. `alt_correction_ft` present (5 375 dropped; ~2 % of in-box points).
   **QNH ft = path Z + stepwise `alt_correction_ft`**; raw pressure ft = path Z.
5. **19 903 points retained.**

**Level-cruise segments**: maximal runs of consecutive retained points within a
**±75 ft** pressure-altitude band, consecutive gap ≤ 300 s, duration ≥ 120 s.
→ **721 segments from 514 distinct flights, 51.9 h of level cruise.**
Median segment 202 s, longest 4693 s.

**Time weighting**: each consecutive point-pair contributes its `dt` at the
pair's mean altitude. Nothing is interpolated across subsequence boundaries.

**Empirical null ("TRANSIT")**: every retained point-pair that is *not* inside a
qualifying level segment — i.e. the **same aircraft, same airspace, same
receivers, same day, same QNH correction, but climbing or descending**. This is
a far better null than "uniform", because it inherits every selection effect of
the pipeline while carrying no round-number preference. It is the workhorse
control throughout.

**Squawk**: a segment/pair is "sq7000" if the stepwise `squawk_runs` value at
that time is `"7000"` (UK VFR conspicuity). 55.8 % of below-TA level time.

**Bands**: `500–3000 ft QNH` (below transition altitude) and
`3000–5500 ft QNH`, each analysed in **both** QNH ft and raw pressure ft.

### 2.5 Metrics

- **conc500** = share of level-cruise *time* within ±50 ft of a multiple of
  500 ft. Uniform expectation **20 %**.
- **M** (headline) = `Σ pᵢ² · N` over 100 ft bins spanning the band
  (N = 25 below TA, 25 above TA). Uniform → M = 1. Reported **averaged over the
  4 bin phases (0/25/50/75 ft)** so a peak sitting on a bin edge cannot deflate
  it; the phase spread is reported.
- **M_pair** = alignment-free cross-check: P(|A−B| < 100 ft) for two independent
  draws, ÷ the same under uniform.
- **M_envelope / M_round** = M recomputed after smoothing the distribution with
  a 500 ft boxcar (= the broad cruise-band shape with all sub-500 ft structure
  erased), and `M_round = M / M_envelope` = the part attributable to
  round-number fine structure.
- **95 % CIs**: 600× bootstrap **resampling whole flights** (not points), so
  within-flight correlation cannot manufacture significance.

---

## 3. Results

### 3.1 Headline table — below transition altitude (500–3000 ft QNH)

8 km airfield mask, level cruise. Uniform reference: conc500 = 20 %, M = 1.00.

| cell | hours | conc500 (95 % CI) | M (95 % CI) | M_pair | M_env | M_round |
|---|---|---|---|---|---|---|
| **QNH, LEVEL, squawk 7000** | 13.3 | **26.3 %** (21.0–32.0) | **1.72** (1.64–2.04) | 1.70 | 1.60 | **1.08** |
| QNH, LEVEL, all A1 | 23.9 | **30.3 %** (25.6–34.3) | **1.76** (1.67–2.02) | 1.71 | 1.56 | 1.13 |
| *QNH, TRANSIT (null), sq7000* | 15.8 | *19.3 %* | *1.51* | 1.52 | 1.45 | 1.04 |
| *QNH, TRANSIT (null), all A1* | 30.2 | *20.3 %* (18.4–22.1) | *1.46* (1.39–1.58) | 1.48 | 1.42 | 1.03 |
| pressure ft, LEVEL, sq7000 | 13.3 | 19.2 % | 1.62 | 1.72 | 1.48 | 1.10 |
| pressure ft, LEVEL, all A1 | 23.9 | 22.9 % (18.8–27.1) | 1.56 (1.49–1.82) | 1.67 | 1.45 | 1.08 |
| *pressure ft, TRANSIT (null), all A1* | 30.2 | *22.5 %* | *1.34* | 1.46 | 1.33 | 1.01 |

Bin-phase spread on M is small throughout (e.g. 1.709–1.791 for the all-A1
QNH LEVEL cell), so the number is not an artifact of bin alignment.

**A1 (clustering exists): SUPPORTED.** Level cruise sits within ±50 ft of a
500 ft multiple **30.3 %** of the time (all A1) / **26.3 %** (squawk 7000)
against a matched empirical null of **20.3 %** / **19.3 %** — a null that lands
essentially exactly on the 20 % uniform expectation, which is itself a strong
validation of the whole pipeline. Flight-level bootstrap CIs exclude the null.

**A2 (co-occupancy is raised): SUPPORTED as a total, but mis-attributed.**
M = **1.72** for the VFR subset (CI 1.64–2.04, excludes 1.0 comfortably). But
the decomposition is the real story: **M_envelope = 1.60, M_round = 1.08.**
Roughly **1.6 of the 1.72 comes from the broad cruise-band envelope** — GA
concentrating in a narrow 1900–3000 ft slice of the 500–3000 ft band — and only
**×1.08 from round-number preference**. The same decomposition on the empirical
null gives M = 1.46–1.51 with M_round = 1.03–1.04, confirming the envelope is
shared by climbing/descending traffic and the fine structure is not.

### 3.2 The mod-500 shape — one bin does all the work

Time share per 50 ft bin of (QNH ft mod 500). Uniform = 10.0 % per bin.

| offset ft | 0–50 | 50 | 100 | 150 | 200 | 250 | 300 | 350 | 400 | **450–500** |
|---|---|---|---|---|---|---|---|---|---|---|
| **QNH, LEVEL (all A1)** | 10.7 | 8.2 | 9.2 | 8.9 | 7.9 | 8.1 | 9.7 | 7.0 | 10.7 | **19.5** |
| QNH, LEVEL (sq7000) | 9.7 | 7.3 | 8.7 | 8.3 | 9.1 | 10.2 | 11.8 | 8.0 | 10.3 | **16.5** |
| *QNH, TRANSIT (null)* | 8.4 | 9.4 | 8.5 | 8.6 | 11.6 | 10.0 | 9.7 | 11.7 | 10.2 | *11.8* |
| pressure ft, LEVEL | 9.2 | 10.8 | 8.3 | 9.4 | 8.9 | 9.7 | 14.1 | 9.7 | 10.6 | *9.2* |
| *pressure ft, TRANSIT (null)* | 8.5 | 9.6 | 10.2 | 9.2 | 11.8 | 10.0 | 10.6 | 9.8 | 10.4 | *10.0* |

The entire effect is a **single spike in the 450–500 bin** — i.e. 0–50 ft
*below* the round number — with every other bin flat. The null is flat
everywhere. The pressure-ft rows are flat everywhere including at the round
numbers (the 14.1 at offset 300 is isolated and not reproduced in any other
cell — noise, not a level). This is about as clean as a real-data signal gets.

### 3.3 Sharpness check — QNH vs pressure altitude (the internal validation)

Excess of level-cruise conc500 over its own matched TRANSIT null, in the same
altitude reference (this cancels the 25 ft ADS-B quantization, which otherwise
inflates the pressure-ft baseline to ~22–25 %):

| band | reference | LEVEL | null | **excess** | ratio |
|---|---|---|---|---|---|
| 500–3000 ft | **QNH ft** | 30.3 % | 20.3 % | **+10.0 pts** | **1.49×** |
| 500–3000 ft | pressure ft | 22.9 % | 22.5 % | +0.4 pts | 1.02× |
| 3000–5500 ft | **QNH ft** | 36.6 % | 23.4 % | **+13.2 pts** | **1.57×** |
| 3000–5500 ft | pressure ft | 23.8 % | 22.1 % | +1.7 pts | 1.08× |

**Applying `alt_correction_ft` does not merely sharpen the peaks — it *creates*
them.** In raw pressure altitude there is no mod-500 structure at all
(1.02×); in QNH-corrected altitude the same segments show a strong peak. This
is (a) direct confirmation that pilots below the TA hold the altimeter, and
(b) an independent validation that `alt_correction_ft` is accurate to well
inside 100 ft — a scrambled correction could not manufacture a coherent peak.

**And the same holds at 3000–5500 ft** (1.57× QNH vs 1.08× pressure). The
task anticipated pilots switching to pressure altitude above the TA; **they do
not**. UK GA in Class G at 3000–5500 ft is flying QNH/RPS altitudes, not
flight levels. (Caveat: driven by the all-A1 set — see §3.6.)

**Residual bias in `alt_correction_ft`**: scanning a global offset δ, the
mod-500 concentration peaks at **δ = +35 ft** (all A1) / **+40 ft** (sq7000),
raising conc500 from 30.3 %→32.0 % and 26.3 %→27.9 %. So the GFS-derived
correction reads ~35–40 ft **low**, consistent with the peak sitting in the
450–500 bin rather than straddling 0. Correcting it changes M by <1 %
(1.762 → 1.754), so the "M is a lower bound because of QNH blur" caveat is
real but **numerically negligible here**.

### 3.4 Which round levels dominate

Share of level-cruise time within ±50 ft of each level (uniform ≈ 2 % per
level below TA, 2 % above):

| below TA | all A1 | squawk 7000 | | above TA | all A1 | squawk 7000 |
|---|---|---|---|---|---|---|
| 1000 ft | 0.6 % | 0.4 % | | 3000 ft | 4.6 % | 6.9 % |
| 1500 ft | 2.7 % | 2.8 % | | 3500 ft | 5.5 % | 6.1 % |
| **2000 ft** | **14.0 %** | **10.2 %** | | **4000 ft** | **7.9 %** | **8.5 %** |
| 2500 ft | 7.1 % | 8.3 % | | 4500 ft | 3.8 % | 3.2 % |
| 3000 ft | 5.9 % | 4.6 % | | 5000 ft | 7.0 % | 1.8 % |
| — | — | — | | 5500 ft | 7.9 % | 0.2 % |
| **total** | **30.3 %** | **26.3 %** | | **total** | **36.6 %** | **26.7 %** |

**2000 ft QNH is the single dominant UK Class-G VFR cruising level**, holding
10–14 % of all level-cruise time in a 100 ft slab. The full 100 ft histogram
below TA (all A1, % of level time) shows the cruise envelope clearly:

```
 600:0.5  900:0.5 1000:0.8 1200:1.3 1300:1.5 1400:2.0 1500:2.3 1600:1.6
1700:1.5 1800:3.5 1900:12.0 2000:8.8 2100:7.0 2200:7.7 2300:7.3 2400:6.7
2500:6.9 2600:8.6 2700:5.5 2800:4.4 2900:9.1
```

(The `1900` bin = 1900–1999 ft, which is where "2000 ft minus 0–50" lands given
the +35 ft correction bias — same spike as §3.2.)

### 3.5 Whole thousands vs +500s (the VFR semicircular question)

Share of time within ±50 ft of a whole thousand vs a thousand-plus-500.
Uniform = 10 % for each.

| band | subset | whole thousands | thousand + 500 |
|---|---|---|---|
| 500–3000 ft (no rule applies) | all A1 | **20.5 %** (2.05×) | 9.8 % (0.98×) |
| 500–3000 ft | squawk 7000 | **15.2 %** (1.52×) | 11.1 % (1.11×) |
| 3000–5500 ft (VFR +500 levels prescribed) | all A1 | **19.5 %** (1.95×) | 17.1 % (1.71×) |
| 3000–5500 ft | **squawk 7000** | **17.2 %** (1.72×) | **9.5 % (0.95×)** |

**Below 3000 ft, where no cruising-level rule applies, whole thousands are
used ~2× more than chance and the +500s sit at exactly chance.** Pilots
default to 2000/3000, not 2500.

**Above 3000 ft the result inverts the intent of the rule.** For genuine VFR
conspicuity traffic (squawk 7000) the +500 levels — which exist *specifically*
to vertically separate opposing VFR traffic — are used at **0.95× chance**,
i.e. not at all, while whole thousands run at 1.72×. Opposing VFR traffic
above the TA is therefore converging on the *same* whole thousands rather than
being split onto the ±500 offsets. (The all-A1 row's high +500 figure comes
from the non-7000 traffic, which does use +500s.) **This is the most directly
actionable safety finding in the study** — but it rests on 5.9 h / 84 flights
and needs replication before being leaned on.

### 3.6 Where the effect is and is not — squawk resolves an apparent conflict

Below TA, per area:

| area | subset | hours | conc500 | null | M | M_env |
|---|---|---|---|---|---|---|
| shropshire | all A1 | 4.8 | 22.6 % | 19.3 % | 2.14 | 1.90 |
| shropshire | **sq7000** | 3.4 | **26.9 %** | 20.9 % | 2.19 | 1.90 |
| devon | all A1 | 5.0 | 21.3 % | 20.3 % | 2.01 | 1.73 |
| devon | **sq7000** | 1.8 | **24.1 %** | 16.5 % | 2.09 | 1.61 |
| lincolnshire | all A1 | 14.2 | 36.0 % | 20.9 % | 1.93 | 1.47 |
| lincolnshire | **sq7000** | 8.1 | **26.5 %** | 18.2 % | 1.73 | 1.52 |

On **all A1** the areas look wildly inconsistent (22.6 / 21.3 / **36.0 %**) —
Lincolnshire appearing to carry the whole aggregate effect. Restricting to
**squawk 7000 they converge to 24–27 %** with nulls at 16–21 %. The
heterogeneity was a *traffic-mix* artifact: Lincolnshire's non-7000 A1 traffic
(military Grob Tutors, King Air/DA42 survey and multi-engine training —
e.g. `43c8c1:2026-06-17T09:51:40Z` ZM314 G12T, `40800d:2026-05-28T12:34:02Z`
G-HMGH B350 BRO93, `407936:2026-06-13T09:18:29Z` G-LHXA DA42 ADV39) flies
ATC/procedurally-assigned round levels, which is a *different* phenomenon from
VFR self-selection. **The squawk-7000 restriction was load-bearing, not
cosmetic**, and the sq7000 row is the correct answer to the hypothesis.

Note the M column runs the other way: Shropshire/Devon (hilly) have the
*highest* M (2.1–2.2) despite the weakest round-number effect, because terrain
compresses everyone into a narrow band (M_env 1.6–1.9). Over flat Lincolnshire
the envelope is wider (M_env 1.5) and more of M comes from round numbers.
**Two independent mechanisms concentrate GA vertically, and they trade off
against each other by terrain.**

### 3.7 Robustness

| variation | conc500 | M |
|---|---|---|
| **primary** (8 km mask, ±75 ft, ≥120 s, all A1) | 30.3 % | 1.76 |
| per-flight equal weight (no long-flight dominance) | 31.8 % | 1.80 |
| airfield mask 0 km | 29.5 % | 1.39 (null M 1.02) |
| airfield mask 3 km | 29.2 % | 1.46 (null M 1.11) |
| airfield mask 5 km | 30.5 % | 1.56 (null M 1.29) |
| airfield mask 12 km | 27.0 % | 2.09 (null M 1.73) |
| level band ±50 ft | 31.7 % | 1.77 |
| level band ±75 ft, ≥240 s | 30.5 % | 1.92 |
| level band ±100 ft, ≥180 s | 28.9 % | 1.77 |
| `path_agl_ft` ≥ 1000 ft | 30.6 % | 1.82 |
| weekend only | 28.5 % | 1.74 |
| weekday only | 32.6 % | 1.90 |
| span narrowed to 1500–3000 ft (N=15 bins) | 30.4 % | 1.21 |

Two things to read off this:

- **conc500 is extremely stable (27–32 %) under every variation**, including
  removing the airfield mask entirely. The clustering result does not depend on
  any tuning choice.
- **M is sensitive to the airfield mask and to the assumed span** (1.39 → 2.09
  as the mask widens 0 → 12 km; 1.21 if the span is 1500–3000 instead of
  500–3000). M is a ratio against a *stated* uniform reference, so it inherits
  whatever you declare the "available" altitude band to be. Quote it with its
  span. The mask-invariant quantity is **M ÷ M_null**, which sits at
  **1.21–1.36** across all mask radii.
- No single flight or day dominates: top flight = 1.9 % of below-TA level time,
  top 5 flights = 7.1 %; busiest day = 5.3 h of 51.9 h.

### 3.8 Example flights (evidence)

Long squawk-7000 level runs parked on round levels:

| flight_id | reg / type | area, day | dur | mean QNH ft | band held |
|---|---|---|---|---|---|
| `402fff:2026-06-20T11:13:28Z` | G-BRPV C152 | shropshire 06-20 | 522 s | 2974 | 100 ft |
| `407b7f:2026-07-11T09:19:43Z` | G-CLYP C42 | devon 07-11 | 468 s | 2976 | 150 ft |
| `408084:2026-07-22T09:55:41Z` | G-CMTG PA-28 | shropshire 07-22 | 445 s | 1994 | 125 ft |
| `4021f7:2026-05-09T09:50:09Z` | G-HULL C150 | lincolnshire 05-09 | 401 s | 2017 | 125 ft |
| `402002:2026-06-20T15:55:10Z` | G-WACU C152 | shropshire 06-20 | 394 s | 2467 | 100 ft |
| `401d6c:2026-07-08T15:32:33Z` | G-BGBI C150 | lincolnshire 07-08 | 393 s | 2027 | 150 ft |
| `401ed9:2026-07-11T15:24:05Z` | G-BIDH C152 | lincolnshire 07-11 | 317 s | 1475 | 150 ft |

Equally long squawk-7000 level runs held just as precisely at **non**-round
levels — the counter-evidence that keeps this a *preference*, not a constraint:

| flight_id | reg / type | area, day | dur | mean QNH ft | band held |
|---|---|---|---|---|---|
| `402b0f:2026-07-22T10:14:43Z` | G-BOMP PA-28 | lincolnshire 07-22 | 608 s | 2727 | 150 ft |
| `4073dd:2026-06-13T17:10:20Z` | G-RKID RV-6 | devon 06-13 | 601 s | 2786 | **50 ft** |
| `40818f:2026-07-15T08:32:35Z` | G-CMVT EFOX | lincolnshire 07-15 | 538 s | 1282 | 75 ft |
| `401669:2026-05-09T10:12:54Z` | G-IMIK PA-28 | lincolnshire 05-09 | 511 s | 2213 | 150 ft |

`4073dd` is the sharpest single counter-example: 10 minutes held inside a 50 ft
band at 2786 ft. Pilots who want a non-round level fly it just as accurately.

Full segment inventory: `results/hA-level-runs.csv` (721 rows).
Metrics: `results/hA-metrics.json`, `hA-bootstrap.json`, `hA-sensitivity.json`.

---

## 4. Caveats

- **The headline M is not mostly a round-number effect.** M ≈ 1.7 is real, but
  M_round ≈ 1.08–1.13. Anyone quoting "round numbers multiply collision
  exposure by 1.7×" from this study would be misreading it. The correct claim is
  "GA vertical distribution in Class G is ~1.7× more concentrated than uniform;
  ~1.6 of that is the cruise-band envelope and ~1.1 is round numbers."
- **M depends on the declared span and the airfield mask** (1.21–2.09 across
  reasonable choices; see §3.7). It is a ratio against an assumed uniform
  reference, not an absolute. `M / M_null` (1.21–1.36) is the stable form.
- **ADS-B equipage bias.** Only ADS-B-equipped aircraft appear. Gliders,
  most microlights, most vintage GA and much military traffic are invisible.
  Per `results/coverage.md`, Lincolnshire in particular has a 14.4 % null
  `emitter_category` rate, so its A1 set understates true light traffic.
  Un-equipped traffic is *also* flying these levels and is *also* collision-
  relevant, so the real co-occupancy is understated by an unknown factor.
- **Altitude simplification (ε = 100 ft)** means a "level" run defined by
  retained points could contain unretained ±100 ft excursions. This inflates
  how much time is classified level and blurs the histogram. Retained altitude
  *values* are genuine measurements, so the peak locations are trustworthy;
  the peak *heights* are conservative.
- **GFS-derived QNH correction error.** Measured here at ~35–40 ft systematic
  (§3.3) plus unmeasured per-day scatter. Direction of bias is toward
  understating clustering; the measured magnitude of the effect on M is <1 %.
  `alt_correction_ft` spanned −234 to +353 ft (5th–95th pct) across the sample.
- **Mis-set altimeters add real spread that IS collision-relevant.** The
  measured distribution is the operationally true one — a pilot who intends
  2000 ft but flies 2060 ft because the subscale is wrong is genuinely at
  2060 ft, and this study counts them there. No correction is warranted or
  applied.
- **The airfield mask uses OurAirports only** (916 UK entries). Hundreds of UK
  farm strips and private sites are absent, so some circuit traffic at
  unlisted strips survives the mask. Mitigation: results are stable from 0 to
  12 km mask radius (§3.7), so residual circuit contamination is not driving
  the clustering result.
- **The above-TA squawk-7000 cell is thin** — 5.9 h, 84 flights, conc500 CI
  17.6–37.4 %. The §3.5 semicircular-rule finding is suggestive, not
  established.
- **Coverage floor.** Per `results/coverage.md`, Lincolnshire's low-altitude
  coverage floor is ~231 ft median at rural strips. Cruise at 1500–3000 ft is
  well above any floor, so this study is not floor-limited — unlike the
  low-AGL studies.
- **3 boxes, 24 days, Mar–Jul 2026 only.** No winter, no autumn, no Scotland,
  no southeast England. Days were not weather-screened. Generalization beyond
  UK lowland/upland Class G in the flying season is unsupported.
- **`emitter_category: A1` is not "VFR GA"** — it is "light aircraft <7 t",
  which sweeps in military trainers, survey aircraft and IFR light twins.
  §3.6 shows this materially changes the answer. Only the squawk-7000 rows
  address the hypothesis as stated.
- **Squawk 7000 is a proxy for "outside ATC control", not a guarantee.** A
  7000 squawk is compatible with receiving a Basic Service (advisory only, no
  level assignment), which is the intended population; but conversely some
  genuinely uncontrolled traffic squawks a listening squawk or a local conspicuity
  code and is excluded here.

---

## 5. Verdict

**PARTIALLY SUPPORTED — moderate-to-strong evidence.**

| claim | verdict | strength |
|---|---|---|
| VFR level cruise clusters at round-number altitudes | **SUPPORTED** | **Strong.** 26.3 % of squawk-7000 level-cruise time within ±50 ft of a 500 ft multiple vs 19.3 % for a matched empirical null of the same aircraft climbing/descending in the same airspace. Flight-level bootstrap CI (21.0–32.0 %) excludes the null. Effect is confined to a single mod-500 bin with all others flat, is consistent across all three areas once squawk-filtered, and survives every sensitivity tested. |
| The effect is in QNH, not pressure altitude | **SUPPORTED** | **Strong.** 1.49× excess in QNH ft vs 1.02× in raw pressure ft below TA; 1.57× vs 1.08× at 3000–5500 ft. Applying `alt_correction_ft` creates the peak rather than sharpening it — a clean internal validation of both the pilot-behaviour claim and the correction's accuracy. Also refutes the assumption that pilots switch to pressure altitude above the TA. |
| Vertical co-occupancy exceeds a random altitude distribution | **SUPPORTED** | **Moderate-to-strong.** M = 1.72 (CI 1.64–2.04) for squawk-7000 level cruise, 500–3000 ft QNH, ≥8 km from an airfield. CI excludes 1.0. But M is span- and mask-dependent (1.21–2.09); the mask-invariant M/M_null is 1.21–1.36. |
| …*because of* round-number clustering | **NOT SUPPORTED** | **The decomposition contradicts it.** M_envelope = 1.60 vs M_round = 1.08: the dominant driver is the narrow cruise-altitude envelope (GA concentrating in 1900–3000 ft), not round-number preference. Round numbers add only ~8 %. |
| VFR semicircular +500 levels split opposing traffic above 3000 ft | **NOT SUPPORTED** | **Weak-to-moderate** (thin cell). Squawk-7000 traffic at 3000–5500 ft uses +500 levels at 0.95× chance and whole thousands at 1.72× — the rule's separation intent is not being realised. |

**Net.** The blindspot framing is half right in a more interesting way than
proposed. Mid-air risk models that assume vertical spread across the Class G
band *are* wrong, by ~1.7×, and that number is now quantified. But the reason
is not the folklore one. Round numbers are a real, cleanly measurable,
statistically solid preference that contributes only ~8 % extra exposure. The
thing that actually stacks light aircraft on top of each other is that they all
cruise in the same 1100 ft slice of sky (1900–3000 ft) — and over hilly terrain
that slice narrows further, pushing M to 2.1–2.2 in Shropshire and Devon
*precisely where the round-number effect is weakest*. A risk model that fixed
only the round-number assumption would capture the smaller half of the problem.

**Budget used: 72 of ≤200 query calls.** All single-page, no cursor pagination.
