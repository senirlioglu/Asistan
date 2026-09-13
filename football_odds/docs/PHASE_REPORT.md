# Phase report — football odds historical-analogue system

Build date: 2026-09-13. Every number below comes from `results/` files produced by the commands in
the README; nothing was hand-edited.

## PHASE 1 — Data audit

**Done:** `python -m src.cli download` (256 files, 16 leagues × 16 seasons, 0 missing) and
`python -m src.cli audit` → `results/audit/{column_availability.csv, market_availability_by_season.csv, raw_headers.json, data_dictionary.csv, audit_summary.md}`.

**Findings**

| topic | finding | consequence |
|---|---|---|
| Aggregates | 2011/12–2018/19 use Betbrain `BbAvH/BbMxH/BbAv>2.5/BbAHh`; from 2019/20 `AvgH/MaxH/Avg>2.5/AHh` | automatic column mapping (`src/data/schema.py`), first candidate present wins |
| Closing odds | `AvgCH`, `PSCH`, `AvgC>2.5`, `AHCh` exist **only from 2019/20** (46.8 % of matches) | odds-movement layer restricted to those seasons |
| Pinnacle | `PSH` from 2012/13; absent in the 2026/27 files so far | Pinnacle benchmark on a subset only |
| Kick-off time | `Time` from 2019/20 | older matches have date only; dashboard shows blank time |
| BTTS odds | **never published** | BTTS is a realised-score statistic (`fthg>0 & ftag>0`), not a feature |
| Date format | `dd/mm/yy` until ~2017, `dd/mm/yyyy` after | two-pass parser |
| Trailing commas / BOM / latin-1 | present in several files | `read_raw_csv` handles all three (`index_col=False`) |
| Post-match columns | shots, cards, referee, and `HxG/AxG` (2026/27) | mapped out of the feature frame entirely |
| Odds collection | Friday afternoon (weekend) / Tuesday afternoon (midweek) | "market" = pre-closing consensus, i.e. the price actually available |

## PHASE 2 — Historical database

**Done:** `python -m src.cli build` → `data/processed/matches.parquet` (84 073 matches, 2011-07-15 → 2026-09-10) and
`results/data_quality_report.md`.

| metric | value |
|---|---|
| matches | 84 073 (3 rows without result dropped) |
| missing 1X2 consensus | 0.1 % |
| missing O/U 2.5 | 0.2 % |
| missing closing odds | 53.2 % (all pre-2019/20) |
| duplicates | 0 |
| invalid odds values (≤ 1.00) | 3 |
| mean 1X2 overround | 1.065 |
| consensus source | Avg 83 973 · bookmaker mean 14 · none 86 |

Corrupt markets (e.g. Greece 2013/14 draw at 1.25 with a 20 % overround, one O/U market summing to 0.79) are rejected by the
`[0.98, 1.15]` overround gate rather than silently normalised.

## PHASE 3 — Probability normalisation

Proportional margin removal is the reference (spec §4); Shin and power are implemented and unit-tested as alternatives.
Sanity check on the full pool: mean market `p_home` 0.437 vs realised home rate 0.442 — the consensus is well calibrated on
average, which is the benchmark the similarity model has to beat.

## PHASE 4 — Similarity engine

* `SimilarityIndex` (date-sorted pool, `date < as_of` strict) with Model A (tolerance, odds-relative and probability-absolute)
  and Model B (top-K by euclidean / manhattan / cosine / mahalanobis, adaptive similarity floor, scopes global / same league /
  data-driven league groups).
* Similarity % ≡ 100 × (1 − total variation distance), averaged over markets for the 1X2+O/U vector.
* Unit tests assert that no neighbour is ever dated on or after the analysed match, in single and batch mode.

## PHASE 5 — Statistical analysis

Weighted outcome rates, Wilson 95 % intervals on Kish's effective N, over/under, BTTS, goal averages and medians, scoreline and
total-goal distributions, empirical-Bayes shrinkage toward the market, fair odds, one-sample z / p-values, confidence labels and
a rule-based signal whose reasons are stored per match.

## PHASE 6/7 — Walk-forward backtest and model comparison

`python -m src.cli backtest` (full grid: 2 feature sets × 4 metrics × 2 scopes × 5 K × 4 half-lives × 6 priors × 5 similarity
floors; ~30 min). Validation seasons 2017/18–2020/21 (21 989 matches), test seasons 2021/22–2025/26 (27 812 matches).
Files: `results/backtest/*.csv`, `summary.md`, `selected_params.json`.

**Selection.** The raw validation optimum (1X2+O/U, Mahalanobis, K=50, half-life 3 y, prior 200) beat the market by
0.00006 log loss — pure noise: 48 configurations lay within one standard error (0.00026). The one-standard-error rule
therefore picked the largest/simplest candidate: **1X2, cosine, global, K=500, no time weighting, prior 200, similarity
floor 97 %**. Without that rule the raw optimum was *worse* than the market on the test seasons (Brier +0.00030, p=0.027) —
a textbook validation overfit that the rule avoided.

**Headline (unseen test seasons)**

| model | Brier | log loss | Brier vs market | p | ECE |
|---|---|---|---|---|---|
| market (consensus avg) | 0.58988 | 0.98863 | — | — | 0.0132 |
| raw historical rate (K=500) | 0.59025 | 0.98911 | +0.00036 | 0.20 | 0.0068 |
| adjusted (shrunk) | 0.58974 | 0.98828 | −0.00014 | 0.50 | 0.0071 |
| Pinnacle (subset n=24 608) | 0.58876 | — | −0.00044 | <1e-8 | — |

Closing-line benchmarks on the 24 637 test matches with closing odds (`test_scores_closing_subset.csv`): closing average
−0.00223 and Pinnacle closing −0.00271 Brier vs the pre-closing average (both p≈0), while the adjusted analogue model
sits at −0.00019 (p=0.37). The information hierarchy is therefore: Pinnacle closing > closing average > pre-closing
average ≈ analogue model > raw analogue rate.

**Verdict: historical similarity did not improve predictive performance.** The adjusted model is indistinguishable from the
market (p=0.50); the raw analogue rate is slightly worse; Pinnacle alone beats the average market significantly, i.e. the
bar that matters is even higher than the one used here. `backtest_ok` is therefore **false** and the live system can never
emit a STRONG signal until a future backtest changes that.

**Ablations (test set, Brier vs market, adjusted model)** — every raw-rate variant (prior 0) is worse than the market, badly so
for small K (K=25: +0.0277). Shrinkage and large K repair the damage but never create an advantage:

| K \ prior | 0 | 25 | 50 | 100 | 200 |
|---|---|---|---|---|---|
| 25 | +0.0277 | +0.0053 | +0.0021 | +0.0006 | +0.0001 |
| 100 | +0.0065 | +0.0035 | +0.0022 | +0.0010 | +0.0003 |
| 500 | +0.0006 | +0.0004 | +0.0003 | +0.0001 | −0.0001 |

* **Model 1 vs Model 2** (common subset): 1X2 −0.00014 (p=0.50) vs 1X2+O/U −0.00012 (p=0.56) — adding the O/U profile does
  not help.
* **Scopes**: global −0.00014, same league +0.00002 (median n_eff 324), similar-league groups −0.00020 (p=0.32). League groups
  found by clustering: {D1, E0, F1, I1, N1, SP1}, {B1, E1, G1, P1, SC0, SP2, T1}, {D2, F2, I2} — sensible (top-5 leagues /
  smaller first divisions & Championship / second divisions), but no measurable gain.
* **Stability**: no test season is significantly different; per league, P1 (−0.0022, p=0.009) and I2 (−0.0018, p=0.02) favour
  the model while E1 (+0.0015, p=0.02) favours the market — with 16 leagues, three hits at p≈0.02 are what chance produces.
* **Time weighting**: half-life 3/5/7 y never beats unweighted within the SE band.

**ROI simulation** (flat 1 unit, test seasons): at the pre-closing *average* price every threshold loses (−2.2 % to −5.9 %
ROI, 1/5 profitable seasons). At the market *maximum* price the 2 pp threshold shows +1.5 % over 11 631 bets (4/5 seasons) —
which is the well-known "best-price vs average-price" gap (≈ +3.5 pp), not model information. Prediction accuracy and
profitability were kept separate on purpose: there is no accuracy edge, so the ROI at best price is a price-shopping
artefact.

**Market-only findings (all 84k matches, `favourite_buckets.csv`)** — a genuine favourite-longshot pattern in the average
market: home favourites priced 65–70 % won 72.6 % (n=2 857, +5.2 pp, CI excludes market), 75–80 % won 82.5 % (+5.0 pp),
80 %+ won 88.6 % (+4.7 pp); underdogs at 30–40 % win slightly less than priced (−0.8 to −0.9 pp). This is visible in the
descriptive bucket tables but is small relative to the margin and does not translate into a Brier gain once shrinkage is
applied. `league_calibration.csv` and `time_stability.csv` split the same table by league and by period.

**Odds movement (39 300 matches with closing odds)**: closing probabilities are better than the Friday/Tuesday snapshot
(Brier −0.0024, p≈0), confirming the collection timing. Steam vs drift within the same closing bucket: 0 of 14 buckets
differ at p<0.05 — once the closing price is known, the direction of the move carries no extra information in this data.

### Follow-up: is the favourite-longshot bias exploitable? (`python -m src.cli backtest-calibration`)

Two transparent re-calibration models see only the margin-free market probability, are fitted on seasons strictly
before each test season, and are scored on the same 27 812 test matches (`market_calibration_*.csv/.md`):

| model | Brier | vs market | p | seasons better |
|---|---|---|---|---|
| market | 0.58988 | — | — | — |
| isotonic (per outcome) | 0.58941 | −0.00047 | 0.017 | 4/5 |
| 5 pp bucket table | 0.58960 | −0.00028 | 0.174 | 3/5 |

The bias is real and *statistically* exploitable in the scoring sense: isotonic re-calibration beats the average market
significantly, in 4 of 5 seasons (only 2023/24 is significant on its own). It is **not economically** exploitable at the
average price: flat-stake ROI is negative at every threshold (−0.6 % to −2.0 %), because a ~0.5 pp calibration gain is far
below the ~6.5 % margin. It is also smaller than the Pinnacle-vs-average gap, i.e. a sharp bookmaker already prices it in.
Conclusion: the recalibrated probability is a better *estimate* than the average market, the similarity analogues are not,
and neither is a betting edge.

## PHASE 8 — Current matches pipeline

`python -m src.cli today --date 2026-09-13 --days 2` on the live `fixtures.csv`: 54 matches with 1X2 odds in 15 leagues.
Outputs `results/2026-09-13_predictions.{csv,xlsx}`, `_details.json` and `analogues/2026-09-13_analogues.parquet`.
Provider interface: `FootballDataFixturesProvider` (default) and `TheOddsApiProvider` (drop-in, same canonical frame).

## PHASE 9 — Dashboard

Streamlit app (`python -m src.cli dashboard`): filters (date, league, minimum N, minimum similarity, deviation-only, minimum
edge), the main table in the spec's column order, CSV/Excel export, and a detail view with market/historical/adjusted bars,
goal and scoreline distributions, scope comparison, tolerance counts, signal reasoning and the top-25/50/100/250/500 analogues.

## PHASE 10 — Documentation and tests

README (installation, download, build, backtest, today, dashboard), this report, 50 unit tests covering odds normalisation,
column mapping, similarity and look-ahead, statistics, metrics, ROI, signal, walk-forward evaluation and parameter selection.
