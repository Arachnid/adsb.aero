# H4 — Go-around / baulked-approach rates differ systematically between airports

**Verdict: SUPPORTED** (strong for the airport-to-airport rate difference and for the
wind interaction; moderate for the absolute rate values, which are certainly
under-counts).

Data: adsb.aero historical ADS-B archive (`https://adsb.aero/api/v1/query`),
2026-01-01 → 2026-07-31. Weather: Open-Meteo ERA5 archive
(`archive-api.open-meteo.com/v1/archive`, `wind_gusts_10m_max`, UTC).
Total adsb.aero query calls used: **≈ 220** (156 for the final dataset, the rest
for probing/validation).

---

## 1. Hypothesis as tested

Go-arounds are individually safe non-events that nobody publishes per-airport.
If ADS-B can measure them, then airports whose approach environment is
terrain-/wind-hostile should show a *chronically elevated* go-around rate
relative to comparable airports on flat terrain — and the excess should be
concentrated on windy days and on the runway/direction most exposed to the
terrain.

Concretely, three testable claims:

- **H4a** Go-around rate per 1,000 approaches differs materially between airports.
- **H4b** The excess at "hostile" airports is wind-linked, and the same wind does
  *not* produce an excess at flat control airports (an interaction, not a main effect).
- **H4c** The excess is direction-specific (one runway end carries it).

**Airports.** Suspected-elevated: **EGNM** Leeds Bradford (hilltop, 681 ft, single
rwy 14/32), **LXGB** Gibraltar (Rock-induced rotor/turbulence, curved arrival),
**LPMA** Madeira Funchal (cliff-top, curved approach, notorious wind),
**LEBB** Bilbao (mountain-lee turbulence, added after LXGB proved thin).
Controls: **EGBB** Birmingham and **EGNX** East Midlands — flat English Midlands,
single runway each, similar/greater traffic. LOWI Innsbruck was dropped: **zero**
commercial arrivals resolved in-data for the weeks probed.

---

## 2. Method

### 2.1 Population query (one per airport-day / airport-week)

I did **not** use `endpoint_within` for the denominator. Probing showed readsb
legs are **not** reliably split at full-stop landings — e.g.
`4ca9d4:2026-06-10T04:58:47Z` is a single "flight" containing an EGNM departure,
a rotation, and an EGNM arrival 3h44m later. Counting legs would have both
under-counted arrivals and mis-assigned them. Instead I pulled **every commercial
leg that came low over the field** and segmented approaches from the trajectory:

```json
{
 "end_date": "2026-04-05", "start_from": "2026-04-04", "window_days": 1,
 "include_path": true, "limit": 300,
 "match": {"and": [
   {"trajectory_intersects": {
      "geometry": {"type": "Circle", "coordinates": [-1.66057, 53.865898], "radius": 9000},
      "altitude_max": 2681, "altitude_max_ref": "ft"}},
   {"emitter_category": ["A3", "A4", "A5"]}]}
}
```

`altitude_max` = field elevation + 2000 ft (QNH-corrected MSL). ARP coordinates and
elevations from `airports.csv`; radius 9 km. `emitter_category` A3/A4/A5 = large /
high-vortex-large / heavy — i.e. airliners and freighters.

**Server bug worked around:** cursor pagination returns **HTTP 500** for this query
shape (reproducible, with and without `include_path`). Where a single call
saturated at `limit: 300`, I re-issued it as three disjoint time slices and merged
on `flight_id`, keeping the leg-selection rule identical:

```json
{"trajectory_intersects": {"geometry": {...}, "altitude_max": 2327, "altitude_max_ref": "ft",
                           "time_from": "2026-06-12T09:00:00Z", "time_to": "2026-06-12T15:00:00Z"}}
```

Slice cut points: `[00:00, 09:00, 15:00, end_date+2d]` UTC.

### 2.2 Sampling

- **EGNM / EGBB / EGNX** — the **same 17 calendar days**, so synoptic weather is held
  common across the test airport and both controls: 8 windy + 8 calm (windiest and
  calmest day of each month Jan–Jul by EGNM gust) plus 2026-06-10.
  Windy: 01-27, 02-20, 03-13, 04-04, 05-12, 06-12, 07-02, 07-25.
  Calm: 01-18, 02-01, 03-20, 04-13, 05-24, 06-16, 07-09, 07-22.
- **LEBB** — 14 days chosen the same way from Bilbao's own gust series
  (windy 01-21, 02-13, 03-30, 04-11, 05-14, 06-25, 07-25; calm 01-17, 02-21, 03-08,
  04-10, 05-27, 06-23, 07-28). The week 2026-06-08…06-15 is a **receiver outage** at
  Bilbao (0 arrivals resolved) and was excluded from candidate days.
- **LXGB** — traffic is only ~2.6 commercial arrivals/day, so I took the **entire**
  2026-01-01 → 2026-07-31 period in 7-day windows (31 windows), not a day sample.
- **LPMA** — 2026-04-01 → 2026-07-31 in 7-day windows. Earlier months resolve almost
  no Madeira traffic. See caveats: 11 of these windows saturated at 300 in the final
  slice, so LPMA is an arbitrary ~chronological subsample rather than a census.

### 2.3 Approach segmentation and go-around detector

Per leg, `path` Z (pressure alt) + stepwise-interpolated `alt_correction_ft` −
field elevation gives **HAF** (height above field, ft); `path_tracks` and
`path_gs` interpolated the same way. An **approach** is a local minimum of HAF with:

| gate | value | purpose |
|---|---|---|
| HAF at low point | < 1500 ft | it is actually low |
| distance from ARP | < 8000 m | it is actually at this field |
| continuous descent into it | ≥ 600 ft within 900 s | rejects **departures** |
| continuity | no subsequence break, no gap > 240 s | a ground stop always breaks this |
| track at low point vs runway axis | ≤ 45° (60° at LPMA, curved approach) | rejects holds/orbits/transits |

An approach is a **go-around** if the aircraft then climbs **≥ 400 ft within 420 s of
continuously tracked flight**. Because a ground stop always produces a
subsequence break or a multi-minute gap, "landed then departed" cannot masquerade
as a climb (shortest airline turnaround ≫ 240 s).

Published runway true bearings were used (EGNM 138/318, EGBB 146/326, EGNX 88/268,
LXGB 88/268, LPMA 45/225, LEBB 117/297 + 142/322), each cross-checked against the
observed modal final-approach track (e.g. EGBB: 1616 tracks at 326°, 997 at 146°).

### 2.4 Exclusions (learned from false positives — see §6)

1. **Circuit training**: any leg with ≥ 3 approaches at the same field is dropped
   entirely (numerator *and* denominator). This removes Ryanair base training at
   EGNX — e.g. `4ca805:2026-04-13T07:14:52Z` flew **six** RWY 27 touch-and-gos
   between 07:23 and 08:13. Without this filter EGNX would score a nonsense
   75/1000.
2. **Military / state**: callsign prefixes RRR, RCH, GRZLY, BLN, CFC, ASCOT, … and
   types A400/C17/C130/K35R. These deliberately fly practice low approaches —
   e.g. `43c04e:2026-01-11T15:02:52Z` (RRR6107, C-17) departed Gibraltar, turned
   back, made a 319 ft pass over the field and left for Malta.
3. **Touch-and-go**: low point at or below field elevation (wheels down) is
   counted as an approach but **not** as a go-around.

### 2.5 Statistics

Wilson intervals are reported but go-arounds **cluster** (weather events), so the
primary interval is a **day-level cluster bootstrap** (resample airport-days with
replacement, 20 000 iterations) and the primary test is a **day-block permutation
test** on the rate difference. Fisher exact is shown alongside as the
independence-assuming (anti-conservative) comparator.

---

## 3. Results

### Table 1 — headline go-around rates

| airport | group | legs | approaches | go-arounds | rate /1000 | Wilson 95% CI | day-cluster bootstrap 95% CI | days with data |
|---|---|---|---|---|---|---|---|---|
| EGNM Leeds Bradford | suspected | 1364 | 713 | 11 | **15.4** | 8.6–27.4 | 4.4–30.1 | 26 |
| LXGB Gibraltar | suspected | 1477 | 739 | 19 | **25.7** | 16.5–39.8 | 12.5–41.3 | 187 |
| LPMA Madeira Funchal | suspected | 5236 | 1627 | 24 | **14.8** | 9.9–21.9 | 4.1–29.1 | 97 |
| LEBB Bilbao | suspected | 1812 | 942 | 14 | **14.9** | 8.9–24.8 | 0.0–37.9 | 16 |
| EGBB Birmingham | control | 3914 | 2055 | 14 | **6.8** | 4.1–11.4 | 2.8–11.0 | 32 |
| EGNX East Midlands | control | 2188 | 1132 | 4 | **3.5** | 1.4–9.1 | 0.8–6.9 | 32 |

Total: 6 703 approaches, 86 go-arounds.

### Table 2 — detectability-matched rates

Coverage floors differ, and they differ **against** the hypothesis (the suspected
airports have *worse* low-altitude coverage, so their go-arounds are harder to
see). To control for this: for threshold *T*, the denominator is approaches that
were tracked down to ≤ *T* (proving a go-around at ≥ *T* would have been visible)
plus go-arounds initiated at ≥ *T*.

| airport | median low point of a *landing* (ft AGL) — the coverage floor | T=300 ft: appr / GA / rate | T=700 ft: appr / GA / rate |
|---|---|---|---|
| EGNM | −21 | 689 / 4 / **5.8** | 694 / 0 / **0.0** |
| LXGB | **+243** | 519 / 14 / **27.0** | 668 / 11 / **16.5** |
| LPMA | **+631** | 472 / 19 / **40.3** | 1367 / 14 / **10.2** |
| LEBB | −34 | 936 / 9 / **9.6** | 934 / 6 / **6.4** |
| EGBB | −28 | 2040 / 5 / **2.5** | 2043 / 4 / **2.0** |
| EGNX | −49 | 1130 / 2 / **1.8** | 1129 / 1 / **0.9** |

EGNM, EGBB, EGNX and LEBB are tracked to the runway. **Gibraltar loses ADS-B at
~240 ft AGL and Madeira at ~630 ft AGL** — half of all Madeira approaches simply
vanish above 630 ft. Every go-around those two airports initiate below their floor
is invisible, so their true rates are higher than Table 1 says. The ordering
survives the matching at both thresholds.

### Table 3 — wind stratification (each airport's own daily max gust)

| airport | calm days (gust < 45 km/h): appr / GA / rate | windy days (≥ 45 km/h): appr / GA / rate | rate ratio | Fisher 2-sided p |
|---|---|---|---|---|
| EGNM | 385 / 1 / 2.6 | 328 / 10 / 30.5 | **11.7×** | 0.004 |
| LXGB | 464 / 5 / 10.8 | 275 / 14 / 50.9 | **4.7×** | 0.001 |
| LPMA | 815 / 2 / 2.5 | 812 / 22 / 27.1 | **11.0×** | <0.001 |
| LEBB | 460 / 1 / 2.2 | 482 / 13 / 27.0 | **12.4×** | 0.002 |
| EGBB | 1107 / 11 / 9.9 | 948 / 3 / 3.2 | 0.32× | 0.103 |
| EGNX | 616 / 2 / 3.2 | 516 / 2 / 3.9 | 1.19× | 1.000 |
| **pooled** | 3847 / 22 / 5.7 | 3361 / 64 / 19.0 | 3.33× | <0.0001 |

**This is the strongest result in the study.** All four terrain/wind airports
show a 4.7–12.4× wind elevation. Both flat controls show **none** — and EGBB/EGNX
were sampled on *the same calendar days* as EGNM, so this is not "windy days are
worse everywhere". On the same UK gale days, Leeds Bradford's go-around rate goes
up 12× and Birmingham's and East Midlands' do not move.

### Table 4 — tests vs the controls

| comparison | rate A /1000 | rate B /1000 | ratio | Fisher 1-sided p | **day-permutation p** |
|---|---|---|---|---|---|
| EGNM vs EGBB+EGNX | 15.4 | 5.6 | 2.73× | 0.010 | **0.008** |
| LXGB vs EGBB+EGNX | 25.7 | 5.6 | 4.55× | <0.0001 | **<0.0001** |
| LPMA vs EGBB+EGNX | 14.8 | 5.6 | 2.61× | 0.0015 | **0.016** |
| LEBB vs EGBB+EGNX | 14.9 | 5.6 | 2.63× | 0.0067 | 0.092 |
| **all 4 suspected vs 2 controls** | 16.9 | 5.6 | **2.99×** | <0.00001 | **0.0065** |
| EGNM vs EGBB alone | 15.4 | 6.8 | 2.26× | 0.036 | — |

LEBB fails the cluster-robust test (p = 0.092) because *all but one* of its 14
go-arounds fall on just two days (2026-01-21 and 2026-02-13, gusts 86 and
107 km/h). That is exactly the clustering the permutation test is designed to
punish; with only 14 sampled days at Bilbao there are too few clusters. The
Bilbao *effect* is large, the Bilbao *day sample* is too small.

### Table 5 — what happened after the go-around (independent corroboration)

| airport | go-arounds | leg ended at a **different** airport | % |
|---|---|---|---|
| EGNM | 11 | 6 | 55% |
| LXGB | 19 | 10 | 53% |
| LPMA | 24 | 15 | 62% |
| LEBB | 14 | 11 | 79% |
| EGBB | 14 | **0** | **0%** |
| EGNX | 4 | **0** | **0%** |
| **4 suspected** | 68 | 42 | **62%** |
| **2 controls** | 18 | 0 | **0%** |

Fisher exact, p = **9.1 × 10⁻⁷**. This was not designed for — it falls out of
`end_airport_ident`. Every single go-around at the two flat controls was followed
by a successful landing at the same field. Nearly two-thirds of go-arounds at the
terrain airports ended somewhere else entirely. That is the signature of a
*condition* (which does not improve on the second try) rather than an *event*
(spacing, runway occupancy, a slow vacate).

### Table 6 — go-around rate by runway in use (H4c)

| airport | runway (true brg) | approaches | go-arounds | rate /1000 |
|---|---|---|---|---|
| **LPMA** | **225 (RWY 23)** | **441** | **20** | **45.4** |
| LPMA | 045 (RWY 05) | 1186 | 4 | 3.4 |
| LXGB | 268 (RWY 27) | 426 | 14 | 32.9 |
| LXGB | 088 (RWY 09) | 310 | 5 | 16.1 |
| LEBB | 322 (RWY 30) | 45 | 2 | 44.4 |
| LEBB | 117 (RWY 12) | 164 | 5 | 30.5 |
| LEBB | 297 (RWY 30) | 706 | 7 | 9.9 |
| LEBB | 142 (RWY 12) | 27 | 0 | 0.0 |
| EGNM | 318 (RWY 32) | 555 | 10 | 18.0 |
| EGNM | 138 (RWY 14) | 158 | 1 | 6.3 |
| EGBB | 326 (RWY 33) | 1285 | 10 | 7.8 |
| EGBB | 146 (RWY 15) | 769 | 4 | 5.2 |
| EGNX | 268 (RWY 27) | 963 | 4 | 4.2 |
| EGNX | 088 (RWY 09) | 169 | 0 | 0.0 |

**Madeira RWY 23 is 13× worse than Madeira RWY 05** (45.4 vs 3.4 per 1000,
Fisher p = **1.1×10⁻⁸**) — and remember RWY 23 is the *less used* direction, so
this is not a traffic-volume artefact.

The other within-airport asymmetries point the same way but are **not individually
significant** at these counts: LXGB 27 vs 09, 2.0×, p = 0.24; EGNM 32 vs 14, 2.9×,
p = 0.47. The flat controls are also flat directionally (EGBB 1.5×, p = 0.59;
EGNX 0/169 on RWY 09). So H4c is established only at LPMA; elsewhere it is a
consistent but underpowered tendency.

### Table 7 — approaches removed by the exclusion filters

| airport | military/state | circuit training | touch-and-go |
|---|---|---|---|
| EGNM | 4 | 0 | 1 |
| LXGB | 22 | 0 | 0 |
| LPMA | 4 | 3 | 0 |
| LEBB | 0 | 0 | 0 |
| EGBB | 2 | 0 | 0 |
| EGNX | 1 | **97** | 1 |

### Table 8 — detector sensitivity (rate /1000, count/denominator)

| CLIMB_MIN | LOW_HAF | NEAR_R | EGNM | LXGB | LPMA | LEBB | EGBB | EGNX |
|---|---|---|---|---|---|---|---|---|
| **400** | **1500** | **8000** | 15.4 (11/713) | 25.7 (19/739) | 14.8 (24/1627) | 14.9 (14/942) | 6.8 (14/2055) | 3.5 (4/1132) |
| 300 | 1500 | 8000 | 15.4 | 25.7 | 14.8 | 14.9 | 6.8 | 3.5 |
| 600 | 1500 | 8000 | 15.4 | 25.7 | 14.8 | 14.9 | 6.8 | 3.5 |
| 400 | 1200 | 8000 | 15.4 | 23.6 | 14.9 | 12.8 | 6.8 | 3.5 |
| 400 | 1800 | 10000 | 15.4 | 25.5 | 18.3 | 15.9 | 7.3 | 3.5 |
| 500 | 1500 | 6000 | 15.4 | 18.7 | 14.2 | 12.8 | 5.8 | 3.5 |

The ranking is invariant. The climb threshold is irrelevant because real
go-arounds climb hard — the *smallest* climb in the whole detected set is 1038 ft
and the median is ~3 500 ft.

---

## 4. Every detected go-around (86 events — individually checkable)

`flight_id` is `icao24:start_ts`; fetch with `GET /flights/{flight_id}`.
"low pt" = ft above field elevation at the bottom of the approach.

| airport | UTC | callsign | type | reg | low pt ft | dist m | trk | rwy | climb ft | leg start→end | flight_id |
|---|---|---|---|---|---|---|---|---|---|---|---|
| EGNM | 2026-02-20 21:19 | EXS26JM | B738 | G-DRTI | 95 | 1059 | 318 | 32 | 3275 | EPKK→EGNM | `40777c:2026-02-20T19:00:22Z` |
| EGNM | 2026-04-04 20:44 | RYR63GU | B738 | EI-ESS | 64 | 84 | 138 | 14 | 6700 | LEMG→**EGCC** | `4ca97a:2026-04-04T18:13:26Z` |
| EGNM | 2026-04-04 21:53 | KLM43E | E295 | PH-NXJ | 489 | 2989 | 316 | 32 | 2900 | EHAM→**EHAM** | `486493:2026-04-04T20:47:23Z` |
| EGNM | 2026-04-04 22:27 | KLM43E | E295 | PH-NXJ | 639 | 3979 | 315 | 32 | 12120 | EHAM→**EHAM** | `486493:2026-04-04T20:47:23Z` |
| EGNM | 2026-04-05 00:34 | EXS2WM | B738 | G-JZBR | 446 | 2837 | 316 | 32 | 6457 | EGNM→**EGCC** | `407630:2026-04-04T14:29:28Z` |
| EGNM | 2026-04-05 01:49 | EXS478 | B738 | G-JZHZ | 504 | 3619 | 319 | 32 | 3850 | EGNM→**EGGP** | `4070ed:2026-04-04T15:59:17Z` |
| EGNM | 2026-04-05 01:55 | EXS16M | B738 | G-JZBK | 150 | 1355 | 323 | 32 | 3225 | —→**EGCC** | `407178:2026-04-04T21:52:42Z` |
| EGNM | 2026-05-12 12:01 | TOM2JY | B738 | G-FDZY | 75 | 277 | 316 | 32 | 3275 | —→EGNM | `40660c:2026-05-12T09:45:55Z` |
| EGNM | 2026-05-24 08:29 | KLM53H | E75L | PH-EXR | 67 | 499 | 318 | 32 | 2775 | EHAM→EGNM | `485778:2026-05-24T07:43:10Z` |
| EGNM | 2026-06-12 16:16 | KLM97K | E190 | PH-EZF | 175 | 1675 | 318 | 32 | 3125 | EHAM→EGNM | `484bd1:2026-06-12T15:18:30Z` |
| EGNM | 2026-06-12 16:19 | EXS75TE | B738 | G-GDFC | 96 | 1305 | 319 | 32 | 3250 | —→EGNM | `4064bb:2026-06-12T13:44:01Z` |
| LXGB | 2026-01-21 09:23 | BAW8LX | A320 | G-EUYA | 214 | 1573 | 267 | 27 | 3775 | EGLL→LXGB | `405a49:2026-01-21T07:02:26Z` |
| LXGB | 2026-01-27 13:21 | BAW494 | A320 | G-EUYB | 1230 | 7978 | 268 | 27 | 2800 | EGLL→**LEMG** | `405a4a:2026-01-27T09:57:52Z` |
| LXGB | 2026-01-27 16:31 | BAW494 | A320 | G-EUYB | 1001 | 6125 | 274 | 27 | 3030 | LEMG→LXGB | `405a4a:2026-01-27T15:11:43Z` |
| LXGB | 2026-02-02 09:05 | EZY97WM | A20N | G-UZHL | 938 | 6205 | 267 | 27 | 3275 | EGBB→**LEMG** | `40756b:2026-02-02T06:23:25Z` |
| LXGB | 2026-02-02 13:51 | BAW494 | A320 | G-EUYE | 241 | 1763 | 312 | 27 | 3775 | LEMG→**LEMG** | `406091:2026-02-02T13:29:00Z` |
| LXGB | 2026-02-02 15:06 | BAW494 | A320 | G-EUYE | 941 | 5883 | 312 | 27 | 10905 | LEMG→**LEMG** | `406091:2026-02-02T13:29:00Z` |
| LXGB | 2026-02-10 12:18 | BAW494 | A320 | G-EUUZ | 818 | 5821 | 272 | 27 | 3205 | EGLL→**LEMG** | `405a48:2026-02-10T09:49:53Z` |
| LXGB | 2026-02-10 12:31 | BAW494 | A320 | G-EUUZ | 749 | 5472 | 271 | 27 | 9350 | EGLL→**LEMG** | `405a48:2026-02-10T09:49:53Z` |
| LXGB | 2026-02-12 18:35 | EZY42RT | A320 | G-EZWY | 875 | 6242 | 266 | 27 | 3100 | EGGD→LXGB | `406b91:2026-02-12T16:16:05Z` |
| LXGB | 2026-02-16 10:06 | EZY78KZ | A320 | G-EJCM | 188 | 1833 | 270 | 27 | 3405 | EGKK→LXGB | `4080f7:2026-02-16T07:48:55Z` |
| LXGB | 2026-03-20 09:30 | EZY53TP | A320 | G-EJCP | 1099 | 6449 | 90 | 09 | 8625 | EGKK→**LEMG** | `407f35:2026-03-20T06:40:49Z` |
| LXGB | 2026-03-20 15:58 | BAW494 | A320 | G-EUYA | 637 | 3831 | 45 | 09 | 8275 | EGLL→**LEMG** | `405a49:2026-03-20T13:06:37Z` |
| LXGB | 2026-03-26 18:23 | EZY42RT | A320 | G-EZUL | 328 | 2440 | 63 | 09 | 3675 | EGGD→LXGB | `406666:2026-03-26T16:15:07Z` |
| LXGB | 2026-04-20 07:50 | EZY85VK | A320 | G-EZUA | 1090 | 5625 | 90 | 09 | 2200 | EGCC→LXGB | `40643c:2026-04-20T05:14:42Z` |
| LXGB | 2026-04-21 11:57 | BAW492 | A320 | G-EUUO | 1457 | 7694 | 307 | 27 | 2550 | EGLL→LXGB | `400a0e:2026-04-21T09:31:18Z` |
| LXGB | 2026-04-23 18:14 | EZY37HW | A319 | G-EZGJ | 849 | 5403 | 118 | 09 | 13125 | EGKK→**LEMG** | `406539:2026-04-23T15:40:30Z` |
| LXGB | 2026-05-15 07:58 | EZY37NU | A20N | G-UZHK | 424 | 2621 | 267 | 27 | 1038 | EGKK→— | `40756a:2026-05-15T05:45:08Z` |
| LXGB | 2026-06-14 13:24 | BAW492 | A320 | G-EUYI | 48 | 847 | 267 | 27 | 3950 | EGLL→LXGB | `406250:2026-06-14T11:05:58Z` |
| LXGB | 2026-07-15 12:58 | BAW492 | A320 | G-EUUG | 84 | 920 | 269 | 27 | 3925 | EGLL→LXGB | `400982:2026-07-15T10:29:27Z` |
| LPMA | 2026-04-04 14:55 | EWG3GK | A319 | D-AGWC | 25 | 1176 | 224 | 23 | 3300 | EDDS→LPMA | `3c5ee3:2026-04-04T11:01:17Z` |
| LPMA | 2026-05-24 14:38 | AUA487 | A321 | OE-LBE | 566 | 4707 | 225 | 23 | 4275 | LOWW→LPMA | `44003a:2026-05-24T10:16:31Z` |
| LPMA | 2026-05-24 15:27 | TUI5GY | B738 | D-ATUZ | 804 | 4935 | 215 | 23 | 3042 | EDDF→LPMA | `3c0cb2:2026-05-24T11:39:05Z` |
| LPMA | 2026-05-24 15:35 | WZZ62BG | A21N | 9H-WAD | 873 | 4189 | 219 | 23 | 1964 | EPKT→LPMA | `4d2402:2026-05-24T10:54:13Z` |
| LPMA | 2026-05-24 19:11 | TUI85N | B738 | D-AHLK | 191 | 760 | 46 | 05 | 5850 | LPPS→LPMA | `3c618b:2026-05-24T18:51:55Z` |
| LPMA | 2026-06-07 07:15 | TAP1685 | A321 | CS-TJH | 763 | 6006 | 223 | 23 | 3100 | LPPT→**LPPT** | `495148:2026-06-07T05:52:08Z` |
| LPMA | 2026-06-07 17:13 | TUI56C | B738 | D-ABKI | 479 | 3863 | 345 | 05 | 3375 | EDDL→LPMA | `3c4969:2026-06-07T13:29:23Z` |
| LPMA | 2026-06-08 12:38 | RZO160 | A20N | CS-TSK | 935 | 4548 | 215 | 23 | 1925 | —→**LPPR** | `49526b:2026-06-08T10:50:51Z` |
| LPMA | 2026-06-08 17:32 | EXS28C | B738 | G-DRTC | 1424 | 6134 | 186 | 23 | 2450 | EGPF→— | `40751b:2026-06-08T13:44:15Z` |
| LPMA | 2026-06-08 18:43 | EXS34U | B738 | G-GDFY | 1047 | 5303 | 215 | 23 | 2825 | EGNX→— | `406ac3:2026-06-08T14:31:06Z` |
| LPMA | 2026-06-09 18:31 | EZY505T | A21N | G-UZMC | 634 | 4619 | 359 | 05 | 3200 | EGKK→— | `407666:2026-06-09T14:33:48Z` |
| LPMA | 2026-06-10 08:25 | EJU75FP | A20N | OE-LUE | 615 | 1690 | 223 | 23 | 14075 | LPPT→**LPPT** | `440115:2026-06-10T06:20:55Z` |
| LPMA | 2026-06-29 08:17 | EJU75FP | A320 | OE-IDS | 851 | 4360 | 212 | 23 | 2000 | LPPT→LPMA | `440da5:2026-06-29T06:34:59Z` |
| LPMA | 2026-06-30 08:36 | EAF9263 | A320 | LZ-EAN | 730 | 5372 | 227 | 23 | 3125 | LKTB→— | `452198:2026-06-30T04:25:14Z` |
| LPMA | 2026-06-30 12:14 | ENT1XJ | B38M | SP-EXB | 347 | 3311 | 221 | 23 | 2600 | EPWR→**LPPS** | `4892c1:2026-06-30T06:58:05Z` |
| LPMA | 2026-06-30 12:31 | ENT9EP | B38M | SP-EXM | 782 | 4188 | 215 | 23 | 2050 | EPWA→LPMA | `48ea00:2026-06-30T07:12:16Z` |
| LPMA | 2026-06-30 13:04 | EJU79HV | A320 | OE-ICF | 150 | 1719 | 212 | 23 | 4700 | LPPR→**LPPR** | `440019:2026-06-30T11:07:03Z` |
| LPMA | 2026-06-30 13:33 | EJU79HV | A320 | OE-ICF | 200 | 2044 | 212 | 23 | 12293 | LPPR→**LPPR** | `440019:2026-06-30T11:07:03Z` |
| LPMA | 2026-06-30 13:41 | RYR87YR | B38M | EI-IKJ | 715 | 6489 | 45 | 05 | 12614 | —→**LPPT** | `4cae8c:2026-06-30T09:35:33Z` |
| LPMA | 2026-06-30 14:42 | ENT2HG | B38M | SP-EXB | 829 | 6490 | 214 | 23 | 3025 | LPPS→— | `4892c1:2026-06-30T14:26:14Z` |
| LPMA | 2026-06-30 14:51 | EJU57QA | A20N | OE-LSP | 1051 | 6044 | 223 | 23 | 3775 | LPPT→**LPPT** | `440cc1:2026-06-30T13:23:26Z` |
| LPMA | 2026-06-30 19:05 | EJU41EH | A320 | OE-IWW | 1018 | 4988 | 225 | 23 | 1850 | LPPT→**LPPT** | `440b1e:2026-06-30T17:44:43Z` |
| LPMA | 2026-06-30 19:22 | EJU41EH | A320 | OE-IWW | 793 | 5572 | 225 | 23 | 12550 | LPPT→**LPPT** | `440b1e:2026-06-30T17:44:43Z` |
| LPMA | 2026-07-05 14:05 | CFG5AX | A321 | D-ATCB | 126 | 1950 | 225 | 23 | 3725 | EDDF→LPMA | `3c0ac6:2026-07-05T10:13:59Z` |
| LEBB | 2026-01-21 06:37 | AEA7161 | B738 | EC-NUZ | 62 | 1414 | 313 | 30 | 13445 | LEMD→**LEMD** | `347307:2026-01-21T05:59:27Z` |
| LEBB | 2026-01-21 07:04 | VLG7PX | A321 | EC-MHS | 437 | 3722 | 116 | 12 | 17309 | LEBL→**LEBL** | `345043:2026-01-21T06:09:47Z` |
| LEBB | 2026-01-21 11:09 | AFR88QA | E190 | F-HBLE | 1014 | 5099 | 287 | 30 | 6400 | —→— | `398564:2026-01-21T09:48:26Z` |
| LEBB | 2026-01-21 11:24 | PGT22YM | A20N | TC-NBO | 356 | 2846 | 120 | 12 | 5550 | —→**LEMD** | `4bb84f:2026-01-21T07:55:09Z` |
| LEBB | 2026-01-21 11:32 | BEL8XD | A319 | OO-SSL | 1216 | 7707 | 117 | 12 | 4705 | EBBR→**LEMD** | `44ce6c:2026-01-21T10:01:36Z` |
| LEBB | 2026-01-21 13:00 | VLG24TL | A320 | EC-OFU | 379 | 3133 | 116 | 12 | 16130 | LEMG→**LEMD** | `34768c:2026-01-21T11:50:35Z` |
| LEBB | 2026-01-21 16:37 | VLG8HF | A320 | EC-OFX | 76 | 1669 | 118 | 12 | 6800 | —→LEBB | `34768e:2026-01-21T13:52:58Z` |
| LEBB | 2026-02-13 11:25 | THY6CJ | B738 | TC-JVA | 38 | 1164 | 297 | 30 | 5800 | —→LEBB | `4baac1:2026-02-13T07:25:15Z` |
| LEBB | 2026-02-13 15:56 | VLG2BU | A320 | EC-JZI | 152 | 1030 | 297 | 30 | 15700 | LPPT→**LEBL** | `3424d2:2026-02-13T14:44:59Z` |
| LEBB | 2026-02-13 16:23 | VLG65XR | A321 | EC-MHB | 847 | 4697 | 353 | 30 | 14525 | LEBL→— | `345042:2026-02-13T15:12:40Z` |
| LEBB | 2026-02-13 16:46 | EZS1361 | A320 | HB-JXB | 1197 | 5957 | 298 | 30 | 14000 | LSGG→**LFBP** | `4b1a1b:2026-02-13T15:29:18Z` |
| LEBB | 2026-02-13 17:55 | WZZ6VA | — | HA-LDL | 1249 | 6767 | 296 | 30 | 4625 | LHBP→— | `471d65:2026-02-13T15:15:40Z` |
| LEBB | 2026-02-13 18:18 | WZZ6VA | — | HA-LDL | 1099 | 5841 | 297 | 30 | 7231 | LHBP→— | `471d65:2026-02-13T15:15:40Z` |
| LEBB | 2026-03-08 16:02 | VLG65XR | A321 | EC-MMU | 29 | 742 | 297 | 30 | 6875 | LEBL→LEBB | `345249:2026-03-08T15:06:10Z` |
| EGBB | 2026-02-01 12:57 | TOM5GA | B738 | G-TAWB | 659 | 4702 | 146 | 15 | 2075 | LIMF→EGBB | `40665f:2026-02-01T11:12:22Z` |
| EGBB | 2026-03-20 06:44 | WMT7JM | A321 | HA-LTK | 284 | 2253 | 328 | 33 | 3425 | —→EGBB | `471f04:2026-03-20T04:07:54Z` |
| EGBB | 2026-03-20 22:33 | TOM5ME | B738 | G-FDZY | 58 | 170 | 328 | 33 | 3625 | —→EGBB | `40660c:2026-03-20T18:59:03Z` |
| EGBB | 2026-04-04 19:49 | RYR2UF | B38M | SP-RZV | 103 | 1958 | 144 | 15 | 3600 | EPKK→EGBB | `48c2b8:2026-04-04T17:30:06Z` |
| EGBB | 2026-05-24 12:30 | SRR902 | B77L | OY-MAD | 829 | 5957 | 145 | 15 | 3850 | —→EGBB | `45b424:2026-05-24T08:15:27Z` |
| EGBB | 2026-05-24 13:17 | EXS86PF | A21N | G-SUNV | 768 | 5367 | 146 | 15 | 2900 | —→EGBB | `408260:2026-05-24T10:05:31Z` |
| EGBB | 2026-06-10 12:17 | SRR902 | B77L | OY-MAC | 111 | 1595 | 326 | 33 | 3600 | —→EGBB | `45b423:2026-06-10T07:54:10Z` |
| EGBB | 2026-06-10 12:22 | TOM1FJ | B38M | G-TUMC | 229 | 1845 | 325 | 33 | 4500 | —→EGBB | `4075f4:2026-06-10T10:10:54Z` |
| EGBB | 2026-06-10 12:51 | TOM5NG | B738 | G-TUKS | 108 | 1411 | 326 | 33 | 3625 | LEMG→EGBB | `408026:2026-06-10T10:17:27Z` |
| EGBB | 2026-07-02 13:19 | RYR1137 | B38M | EI-IGJ | 34 | 1276 | 326 | 33 | 3650 | EGSS→EGBB | `4cadbc:2026-07-02T12:50:06Z` |
| EGBB | 2026-07-09 12:15 | VLG391Y | A320 | EC-MYC | 955 | 6641 | 328 | 33 | 2725 | LEBL→EGBB | `345646:2026-07-09T10:24:21Z` |
| EGBB | 2026-07-09 16:34 | RYR8KG | B38M | EI-IFS | 1126 | 7641 | 326 | 33 | 2550 | LCPH→EGBB | `4cac89:2026-07-09T11:54:11Z` |
| EGBB | 2026-07-09 19:06 | EIN27T | A320 | EI-EDS | 28 | 918 | 326 | 33 | 3650 | EIDW→EGBB | `4ca770:2026-07-09T18:28:22Z` |
| EGBB | 2026-07-25 17:02 | EXS71MH | B738 | G-DRTJ | 86 | 1537 | 326 | 33 | 3575 | —→EGBB | `407c6d:2026-07-25T15:27:39Z` |
| EGNX | 2026-02-01 19:56 | EXS16KL | B738 | G-JZBB | 167 | 2239 | 268 | 27 | 4550 | EGNX→EGNX | `40717e:2026-02-01T10:31:46Z` |
| EGNX | 2026-04-04 22:23 | RYR6KZ | B38M | EI-HGF | 376 | 3015 | 268 | 27 | 3400 | LEBL→EGNX | `4cac84:2026-04-04T20:31:52Z` |
| EGNX | 2026-05-12 16:55 | RYR5PH | B38M | EI-HEV | 157 | 1626 | 274 | 27 | 2700 | —→EGNX | `4cad2a:2026-05-12T14:36:56Z` |
| EGNX | 2026-07-22 16:49 | DHK591 | B77L | G-DHLY | 757 | 5583 | 275 | 27 | 3925 | —→EGNX | `407c8a:2026-07-22T08:11:47Z` |

Bold destinations are diversions. `—` = endpoint not near a recognised airport
(coverage lost), not "nowhere".

---

## 5. Three worked example profiles

### 5.1 EGNM — KLM43E, two go-arounds then home to Amsterdam
`486493:2026-04-04T20:47:23Z` — E195-E2 PH-NXJ, EHAM→EHAM, 2026-04-04 (EGNM peak
gust 90 km/h, the windiest day of the sample). Held ~30 min at 3 400 ft between
attempts (omitted below).

```
     UTC dist_ARP_km  ft_AGL  trk gs_kt   profile (each # = 100 ft)
--- approach 1 ---
21:51:43       12.16    2014  320   172  ####################
21:52:12        9.83    1614  320   172  ################
21:52:40        7.70    1239  320   134  ############
21:53:40        3.83     614  320   128  ######
21:53:52        2.99     489  316   144  #####     <-- GO-AROUND (489 ft, 3.0 km)
21:54:09        1.71    1039  316   144  ##########
21:54:33        0.17    2489  316   151  #########################
21:54:53        1.80    3214  322   151  ################################
--- 30 min holding at ~3400 ft omitted ---
--- approach 2 ---
22:25:34       10.90    1814  320   173  ##################
22:26:02        8.77    1439  320   140  ##############
22:26:57        5.00     764  315   128  ########
22:27:12        3.98     639  315   134  ######    <-- GO-AROUND #2 (639 ft, 4.0 km)
22:27:41        1.77    2364  325   167  ########################
22:27:59        0.36    3139  325   197  ###############################
22:29:41       10.70    4214  313   217  ##########################################
```
Leg ends back at EHAM 23:33Z. Two baulked RWY 32 approaches, then gave up.

### 5.2 LXGB — BAW494, go-around then back to Malaga
`406091:2026-02-02T13:29:00Z` — A320 G-EUYE, LEMG→LEMG. It had already been
diverted to Malaga; this leg is the *retry*, which also failed.

```
     UTC dist_ARP_km  ft_AGL  trk gs_kt   profile (each # = 100 ft)
13:48:14       16.54    1891  312   157  ###################
13:48:57       13.44    1541  312   135  ###############
13:49:54        9.23    1491  312   140  ###############
13:50:57        4.98     791  312   133  ########
13:51:43        1.76     241  312   133  ##        <-- GO-AROUND (241 ft, 1.8 km)
13:52:34        1.86    1241  312   140  ############
13:53:04        3.80    3316  312   131  #################################
13:53:49        6.62    4016  312   195  ########################################
--- 40 min later, second attempt, aborted higher, then LEMG ---
```

### 5.3 EGBB — TOM5NG, control-airport go-around, lands 13 min later
`408026:2026-06-10T10:17:27Z` — B737-800 G-TUKS, LEMG→EGBB. One of three EGBB
go-arounds inside 35 minutes on a *calm* day (gust 37 km/h) — a transient local
event, not a wind condition. Note it lands on the second try.

```
     UTC dist_ARP_km  ft_AGL  trk gs_kt   profile
12:48:50       12.69    2108  326   156   descending RWY 33 final
12:49:07       11.35    1858  326   156
12:51:19        1.41     108  326   156   <-- GO-AROUND (108 ft, 1.4 km)
12:51:34        0.21     183  326   156
12:52:13        3.09    1558  326   156
12:53:43       12.04    3708  326   156   levels 3708 ft, repositions
13:00:59       14.90    1908  326   156   second approach
13:02:04       10.02    1633  326   156
13:03:51        1.46     106  326   156   lands
```

---

## 6. Caveats — read these before quoting any number

1. **Cause is not identifiable.** A go-around forced by ATC spacing, a slow
   runway vacate, a runway inspection, an unstable approach or windshear look
   *identical* in ADS-B. The claim here is about **rate differences between
   airports**, not about why any individual go-around happened. The wind
   stratification (Table 3), the runway asymmetry (Table 6) and the diversion
   pattern (Table 5) are consistent with weather/terrain causation but do not
   prove it for any single event. Note also that spacing-driven go-arounds should
   be *more* common at the busier controls, which works against the finding.
2. **All rates are under-counts, unequally.** Detection needs the aircraft to be
   tracked through the low point. Coverage floors: EGNM/EGBB/EGNX/LEBB ≈ runway
   level; **LXGB ≈ 240 ft AGL; LPMA ≈ 630 ft AGL**. A go-around below an airport's
   floor is invisible. This biases *against* the hypothesis at the two most
   suspect airports; Table 2 is the attempt to correct for it.
3. **LPMA is exploratory, not a census.** 11 of 18 weekly windows saturated at
   `limit: 300` in the final time slice (a consequence of the pagination-500 bug
   plus my slice cut-points being tuned for day windows), so Madeira is an
   arbitrary ~chronological subsample. The *rate* should still be estimable since
   truncation is uncorrelated with go-around status, but the effective sample is
   smaller than the 1 627 approaches suggest. Also 10 of 24 LPMA go-arounds fall on
   a single day (2026-06-30) — the cluster bootstrap CI (4.1–29.1) reflects this.
4. **Clustering is severe everywhere.** 6/11 EGNM events are one night; 13/14 LEBB
   events are two days; 3/14 EGBB events are 35 minutes. Wilson intervals are
   therefore too narrow; use the bootstrap column. LEBB's cluster-robust
   permutation p = 0.092 is the honest answer for Bilbao: big effect, too few days.
5. **Only ADS-B-equipped aircraft, only A3/A4/A5.** Regional turboprops squawking
   A2, GA, and anything non-equipped are excluded by design.
6. **Denominator = detected approaches, not scheduled arrivals.** An approach only
   enters the denominator if the leg was captured and the trajectory shows a
   ≥600 ft continuous descent into a low point near the field. Approaches whose
   descent is fragmented by coverage gaps are silently dropped from both
   numerator and denominator.
7. **A go-around plus its re-approach counts as two approaches, one go-around** —
   so the rate is per approach, not per arriving aircraft. Rates per *aircraft*
   would be very slightly higher.
8. **Circuit-training exclusion is a blunt instrument.** Dropping legs with ≥3
   approaches removed 97 EGNX approaches. If any real airport had a genuine
   3-go-around flight it would be wrongly dropped; none of the retained events
   came from a leg with more than 2.
9. **Wind is ERA5 reanalysis at 10 m at the ARP, daily maximum** — not METAR, not
   the actual gust at the actual approach time, and it says nothing about
   direction relative to the runway or about turbulence aloft. It is a proxy.
10. **Geometry is simplified** (ε = 50 m, 100 ft). Immaterial here: the smallest
    detected climb is 1 038 ft.
11. Two LXGB detections have low points at 1 230 and 1 457 ft at 7.7–8.0 km, which
    is close to a nominal 3° glidepath — they are approach abandonments initiated
    early rather than at minima. Dropping the LOW_HAF gate to 1 200 ft removes
    them and LXGB still scores 23.6/1000 (Table 8).

---

## 7. Verdict

**SUPPORTED.**

- **H4a (rates differ between airports): SUPPORTED, strong.** 16.9 vs 5.6 per
  1 000 approaches, suspected vs control, 2.99× (day-block permutation
  p = 0.0065; Fisher p < 10⁻⁵). Individually EGNM (p = 0.008), LXGB (p < 10⁻⁴) and
  LPMA (p = 0.016) each beat the pooled controls under the cluster-robust test;
  LEBB does not (p = 0.092) purely for lack of sampled days. Robust to every
  detector threshold tried.
- **H4b (wind interaction): SUPPORTED, strong — this is the headline.** On the
  *same* calendar days, gale-force days multiply the go-around rate by 11.7× at
  Leeds Bradford and by 0.32× / 1.19× at Birmingham / East Midlands. All four
  terrain airports show 4.7–12.4×; neither flat control shows any effect. Backed
  by a completely independent signal: **62% of terrain-airport go-arounds ended in
  a diversion versus 0 of 18 at the controls** (p = 9×10⁻⁷).
- **H4c (direction-specific): PARTIALLY SUPPORTED.** Conclusive at Madeira only:
  RWY 23 is 45.4/1000 against RWY 05's 3.4/1000, a 13× within-airport asymmetry on
  the *less-used* direction (p = 1.1×10⁻⁸). Gibraltar (2.0×, p = 0.24) and Leeds
  Bradford (2.9×, p = 0.47) lean the same way but are underpowered; the flat
  controls are directionally flat as expected.
- **The public-statistics premise is not tested here** — I did not attempt to
  confirm that no per-airport go-around statistics are published. What is shown
  is that the quantity is *recoverable from ADS-B alone*, at ~220 API calls per
  six-airport study, with individually auditable events.

The absolute numbers (roughly 4–7 per 1 000 at a flat English airport, 15–26 per
1 000 at a terrain/wind airport) should be read as **lower bounds**, and the
Gibraltar and Madeira figures as substantially larger lower bounds than the
others because of their coverage floors.
