# Football odds — historical analogue analysis

> "Piyasanın bu maça verdiği olasılık profiline tarihsel olarak benzeyen maçlarda gerçekte ne olmuş?"

A research system that compares today's bookmaker odds with 15 seasons of Football-Data.co.uk
matches, finds the most similar historical market profiles, measures what actually happened in
those matches, and reports the deviation from today's market **together with its uncertainty and
its out-of-sample track record**. It is explicitly *not* a tipster: the walk-forward backtest is
the product, and when the similarity model does not beat the market the report says so.

```
today's odds ─► remove margin ─► [p_home, p_draw, p_away] ─► K nearest historical matches
              (played strictly before the analysed date)
           ─► realised H/D/A, O/U 2.5, BTTS, goals, scorelines (time-weighted, Wilson CI)
           ─► empirical-Bayes shrinkage toward the market ─► deviation (pp) ─► signal
```

## Contents

- [Installation](#installation)
- [Commands](#commands)
- [Data source and audit findings](#data-source-and-audit-findings)
- [Database schema](#database-schema)
- [Methodology](#methodology)
- [Backtest design](#backtest-design)
- [Output files](#output-files)
- [Project layout](#project-layout)
- [Assumptions and limitations](#assumptions-and-limitations)

## Installation

```bash
cd football_odds
python -m venv .venv && source .venv/bin/activate      # optional
pip install -r requirements.txt
```

Python 3.11+. Everything is configured in `config/settings.yaml` (leagues, seasons, model
parameters, backtest splits). Set `FO_CONFIG=/path/to/other.yaml` to use another file.

## Commands

All commands run from the `football_odds/` directory.

| step | command | what it does |
|---|---|---|
| data download | `python -m src.cli download` | fetches `mmz4281/<season>/<div>.csv` for every configured league/season into `data/raw/`; completed seasons are cached forever, the current season is refreshed when older than `data.refresh_hours` |
| data audit | `python -m src.cli audit` | PHASE 1: which markets exist in which season → `results/audit/` |
| historical build | `python -m src.cli build` | canonical column mapping → consensus odds → margin-free probabilities → `data/processed/matches.parquet` + `results/data_quality_report.md` |
| backtest | `python -m src.cli backtest [--quick]` | walk-forward validation grid → parameter choice → unseen test seasons → calibration, ROI, buckets, league groups, odds movement → `results/backtest/` |
| calibration backtest | `python -m src.cli backtest-calibration` | fast (seconds) walk-forward test of the market re-calibration models (isotonic / bucket) → `results/backtest/market_calibration_*` |
| today analysis | `python -m src.cli today [--date YYYY-MM-DD] [--days N] [--update] [--refresh]` | fixtures with odds → analysis → `results/YYYY-MM-DD_predictions.csv/.xlsx`, `_details.json`, `analogues/…parquet` |
| web app | `python -m src.cli web [--port 8000]` | FastAPI JSON API + hand-built Turkish, mobile-first HTML frontend (`src/web/`), with the daily scheduler — this is what the hosted deployment runs |
| dashboard | `python -m src.cli dashboard` | legacy Streamlit UI over the same prediction files |
| tests | `python -m pytest` | unit tests for every module (odds, mapping, similarity, statistics, metrics, signal, walk-forward look-ahead) |

Typical daily run:

```bash
python -m src.cli today --update --days 7     # refresh current season results, rebuild, analyse the next 7 days
python -m src.cli dashboard
```

`--update` only re-downloads the current season's files; `python -m src.cli backtest` should be
re-run occasionally (e.g. once a season) because its `selected_params.json` drives the live model.

## Data source and audit findings

Source: [Football-Data.co.uk](https://www.football-data.co.uk) (`notes.txt` documents the columns).
38 leagues × up to 16 seasons (2011/12 → 2026/27) are configured, in two file families:

* **22 main divisions** (`mmz4281/<season>/<div>.csv`, one file per season, pre-closing consensus
  odds, half-time score, O/U 2.5): 8 `core` (Premier League, Championship, La Liga, Serie A,
  Bundesliga, Ligue 1, Eredivisie, Primeira Liga) + Belgium, Turkey, Greece, Scottish Premiership,
  Segunda, Serie B, 2. Bundesliga, Ligue 2, League One, League Two, National League, Scottish
  Championship / League One / League Two. Fixtures: `fixtures.csv`.
* **16 extra leagues** (`new/<COUNTRY>.csv`, ONE file per country holding every season since 2012):
  Argentina, Austria, Brazil, China, Denmark, Finland, Ireland, Japan, Mexico, Norway, Poland,
  Romania, Russia, Sweden, Switzerland, USA. These files publish **closing odds only**
  (`AvgCH/MaxCH/PSCH/B365CH`), no half-time score and no O/U market, so for them "market" is the
  closing consensus (`consensus_source = avg_closing`) and the closing-vs-pre-closing benchmarks
  skip them. Calendar-year seasons get the codes `Y2015`, split seasons the usual `1617`.
  Fixtures: `new_league_fixtures.csv` (pre-closing `AvgH`), matched on Country + League.
  Switzerland's Challenge League has two rows on Football-Data and is not configured.

That is the whole football coverage of Football-Data. Leagues İddaa lists but Football-Data does
not carry (Czechia, Ukraine, Croatia, Serbia, Hungary, Bulgaria, South Korea, Australia, Saudi
Arabia, second divisions outside the list above, the UEFA and domestic cups, national teams)
would need another odds source with 10+ seasons of history.

Audit results (`results/audit/audit_summary.md`, 256/256 files present):

| market | availability |
|---|---|
| 1X2 market average / maximum | every season. 2011/12–2018/19 as Betbrain `BbAvH/BbMxH`, from 2019/20 as `AvgH/MaxH` |
| Bet365 1X2 | every season |
| Pinnacle 1X2 (`PSH`) | from 2012/13; not yet in the 2026/27 files |
| **closing odds** (`AvgCH`, `PSCH`, `AvgC>2.5`, `AHCh`) | **2019/20 onwards only** (≈47 % of matches) |
| O/U 2.5 average | every season (`BbAv>2.5` → `Avg>2.5`) |
| Asian handicap line + average odds | every season (`BbAHh` → `AHh`) |
| kick-off `Time` | 2019/20 onwards |
| **BTTS odds** | **never published** → BTTS is derived from the final score only |
| `HxG/AxG` | 2026/27 only, post-match expected goals → excluded from every feature |

Data quality (`results/data_quality_report.md`): 179 545 matches (84 073 before the 22 leagues
added on 2026-09-14), 0.1 % without 1X2 odds, 0 duplicates, mean 1X2 overround 1.065 for the
main divisions. The extra leagues have no O/U market, so the O/U-based layers (`1x2_ou` feature
set, goal-market comparison) simply skip them.
A handful of rows carry corrupt odds (e.g. draw at 1.25 with a 20 % overround); consensus
markets with overround outside `[0.98, odds.max_overround]` are treated as missing.

Bookmaker odds on Football-Data are **collected Friday afternoon (weekend games) and Tuesday
afternoon (midweek games)** — they are pre-closing prices, so "market" in this project means the
pre-closing consensus, which is also the price that was actually available to bet at.

## Database schema

`data/processed/matches.parquet`, one row per match (`results/audit/data_dictionary.csv` has every column):

| group | columns |
|---|---|
| identity | `match_id` (sha1 of league/date/home/away), `league`, `season`, `date`, `time`, `home_team`, `away_team` |
| targets (never features) | `fthg`, `ftag`, `ftr`, `hthg`, `htag`, `htr`, `total_goals`, `btts`, `over25`, `result_code` |
| raw odds | `b365_*`, `ps_*`, `max_*`, `avg_*`, `bfe_*`, closing `*c_*`, O/U `*_o25/_u25`, AH `ah_line`, `avg_ahh/aha` … |
| consensus | `cons_h/d/a` (AvgH or mean of listed bookmakers), `consensus_source`, `n_books_used` |
| market probabilities | `raw_p_*` (1/odds), `p_home/p_draw/p_away` (margin-free), `overround_1x2`, `p_over25/p_under25`, `overround_ou`, `p_ah_home` |
| closing / movement | `pc_home/draw/away`, `delta_p_*` = closing − pre-closing, `has_closing` |
| benchmarks | `pin_p_*`, `pinc_p_*` (Pinnacle pre-closing / closing, margin-free) |
| flags | `has_1x2`, `has_ou`, `has_closing`, `has_ah` |

## Methodology

### Margin removal (`src/features/odds.py`)

```
raw_i = 1 / odds_i,   total = Σ raw_i  (= overround),   p_i = raw_i / total
```

Proportional normalisation is the reference method (as specified). Shin (1993) and the power
method are implemented for research (`odds.normalization`). Odds ≤ 1.00 are invalid; a market
whose implied probabilities sum to < 0.98 or > `max_overround` is discarded as a data error.

### Consensus (`consensus_1x2`)

`AvgH/AvgD/AvgA` (Betbrain average before 2019/20) when present, otherwise the row-wise mean of
the individual bookmakers that quote all three outcomes. Betfair Exchange is excluded from the
consensus (different margin structure) but kept as a column.

### Feature vectors (`src/features/vectors.py`)

* Model 1 `1x2`: `[p_home, p_draw, p_away]`
* Model 2 `1x2_ou`: `[p_home, p_draw, p_away, p_over25, p_under25]`

### Similarity % — definition

Independently of the ranking metric,

```
TV_market    = ½ Σ_i |p_i − q_i|            (total variation distance, in [0, 1])
TV           = mean of TV_market over the markets in the feature set
Similarity % = 100 × (1 − TV)
```

98 % similarity therefore means the two probability profiles differ by exactly 2 percentage
points of probability mass (e.g. home 55 vs 57 %, away 20 vs 18 %). It is bounded, metric-free
and directly readable.

### Model A — tolerance matching

All historical matches within ±1/2/3/5 % of the query on **every** outcome, in two variants:
relative odds (`|o_hist − o| / o ≤ tol`) and absolute probability (`|p_hist − p| ≤ tol`). Reported
as counts per level (`tol_odds_2pct`, `tol_probs_2pct`, …).

### Model B — nearest neighbours (main model)

Top-K (25 / 50 / 100 / 250 / 500) by Euclidean, Manhattan, cosine or Mahalanobis distance
(pseudo-inverse covariance because the simplex is degenerate), optionally with an adaptive floor
(`min_similarity` ≥ 98 / 97 / 95 / 92 %, evaluated within the 500 nearest). Three scopes:
`global`, `same_league`, and `similar_leagues` (data-driven: Ward clustering of league profiles —
favourite strength, home/draw bias, goals, margin — only enabled when every cluster has ≥ 2
leagues with ≥ 2000 matches; see `results/league_groups.json`).

### Time weighting

`w = exp(−ln2 · years_old / half_life)`, half-life ∈ {none, 3, 5, 7} years, chosen on the
validation seasons. Effective sample size `n_eff = (Σw)² / Σw²` replaces N in every interval and
in the shrinkage.

### Statistics per analogue set (`src/models/stats.py`)

Weighted H/D/A rates with **Wilson 95 % intervals** on `n_eff`, over/under 2.5, BTTS, mean and
median goals, home/away goal averages, 16 scorelines + "other", total-goals distribution 0–5+.
Confidence label: `n_eff` < 30 VERY LOW, < 100 LOW, < 250 MEDIUM, else HIGH.

### Shrinkage (adjusted probability)

```
adj_i = (n_eff · hist_i + m · market_i) / (n_eff + m)
```

Empirical-Bayes pseudo-count `m` (prior strength), chosen on validation from
{0, 10, 25, 50, 100, 200}. With `m = 50`, 18 analogues move 18/68 = 26 % of the way from the
market toward the raw rate. Edges and fair odds use the **adjusted** probability.

### Edge, fair odds

`edge = adj − market` in percentage points; `fair odds = 1 / adj`. The word *edge* means a
historical deviation, **not** a profitable bet — margin, sampling error and market efficiency are
reported next to it, never hidden.

### Signal (`src/models/signal.py`)

Rule based and fully explained in `signal_reason`:

| label | rule |
|---|---|
| LOW SAMPLE | `n_eff` < 100 |
| STRONG HISTORICAL DEVIATION | \|edge\| ≥ 5 pp **and** market outside the raw 95 % CI **and** avg similarity ≥ 95 % **and** backtest showed adjusted ≥ market |
| MODERATE HISTORICAL DEVIATION | \|edge\| ≥ 3 pp and market outside the CI and avg similarity ≥ 90 % (or a STRONG candidate that failed the backtest/similarity gate) |
| NEUTRAL | everything else |

### Look-ahead protection

* Features are only margin-free odds, league and date; `schema.POST_MATCH_COLUMNS` guards the
  feature sets (unit tested).
* `SimilarityIndex.candidates()` returns pool rows with `date < as_of` (strict), so an analysed
  match — live or backtested — only sees matches finished before its day. Same-day matches are
  excluded as well because Football-Data odds are collected before the round.
* `HxG/AxG`, referee, shots etc. are never mapped into the feature frame.

## Backtest design

Walk-forward by season, three tiers:

| tier | seasons | use |
|---|---|---|
| pool | 2011/12 → | every match before the analysed date |
| validation | 2017/18, 2018/19, 2019/20, 2020/21 | parameter grid (feature set × metric × scope × K × half-life × prior × similarity floor); best **adjusted** log loss wins |
| test | 2021/22 … 2025/26 | reported once with the chosen parameters; never used for selection |

Scores: multiclass **Brier**, **log loss**, reliability tables (10 bins), expected calibration
error, paired z-test of per-match Brier differences against the market baseline, plus a Pinnacle
benchmark on the subset where Pinnacle prices exist. Stability is reported per test season and
per league; ablations over K / half-life / prior on the test set are written for transparency
only. Model 1 vs Model 2 are compared on the common subset with O/U odds; scopes are compared
with the other parameters fixed.

**ROI simulation** (separate from accuracy): flat 1 unit on every outcome whose adjusted
probability exceeds the market by ≥ 2 / 3 / 5 / 7.5 / 10 pp, settled at the pre-closing average
odds (and at the market maximum as an optimistic bound). Bets, win rate, average odds, profit,
ROI, maximum drawdown, and how many test seasons were profitable.

Market-only analyses (no similarity model): favourite-bucket calibration (5 pp buckets, H/D/A),
the same per league and per period (2012–15, 2016–19, 2020–22, 2023–), and the odds-movement layer
(2019/20+): opening vs closing Brier, realised rates per closing-probability bucket × steam/drift,
two-proportion tests.

The headline verdict is written to `results/backtest/summary.md` and to
`selected_params.json → backtest_ok`. When `backtest_ok` is false the dashboard shows
"historical similarity did not improve on the market" and no STRONG signal can be produced.

## Results so far (full backtest, 2026-09-13)

Details in `docs/PHASE_REPORT.md` and `results/backtest/summary.md`.

| model (test seasons 2021/22–2025/26, n=27 812) | Brier | vs market | p |
|---|---|---|---|
| market (consensus average) | 0.58988 | — | — |
| raw analogue rate (K=500) | 0.59025 | +0.00036 | 0.20 |
| adjusted (shrinkage, prior 200) | 0.58974 | −0.00014 | 0.50 |
| Pinnacle (subset) | 0.58876 | −0.00044 | <1e-8 |

**Historical similarity did not improve predictive performance over the market.** The adjusted model is statistically
indistinguishable from the consensus, the raw analogue rate is slightly worse, and the ROI simulation at average prices is
negative at every threshold. The dashboard therefore reports deviations as descriptive statistics with intervals and never
emits a STRONG signal (`backtest_ok = false`). The one real, repeatable pattern is a favourite-longshot bias in the average
market (home favourites ≥ 65 % win 3–5 pp more often than priced), documented in `favourite_buckets.csv`.

Follow-up (`python -m src.cli backtest-calibration`): a walk-forward isotonic re-calibration of the market probability
does beat the average market on Brier (−0.00047, p=0.017, 4/5 seasons) — but the gain is ~0.5 pp against a ~6.5 % margin,
so flat-stake ROI stays negative at every threshold. Better estimate, no betting edge. Details in `docs/PHASE_REPORT.md`.

### Rerun on 38 leagues (2026-09-14)

Same protocol on the enlarged pool (179 545 matches, 38 732 test matches): selected `1x2_ou / mahalanobis / global /
K=100 / prior 200`; Brier market 0.59715 vs adjusted 0.59747, **p = 0.044 in the market's favour**. The verdict is the
same as before and slightly firmer: the analogue model does not beat the market; with more data it is measurably a
little worse. Details and per-league table in `docs/PHASE_REPORT.md` and `results/backtest/summary.md`.

## Hosted deployment (Railway / any container host)

`serve.py` is a single-process entry point: it serves the web app (FastAPI + `src/web/static/`) on `$PORT`, bootstraps
the data when the container is empty (download → build → today, in a background thread), and re-runs that job every day
at `FO_DAILY_UTC`. The status pill in the top bar starts a refresh (`POST /api/refresh`, protected by `FO_ADMIN_KEY` when
set). Set `FO_UI=streamlit` to serve the legacy Streamlit dashboard instead.

API: `GET /api/meta`, `GET /api/day/{YYYY-MM-DD}`, `GET /api/analogues/{date}/{match_id}?k=50`,
`GET /api/teams/{date}/{match_id}`, `GET /api/live/{YYYY-MM-DD}`, `GET /api/health`.

Live scores (`src/web/live.py`) come from ESPN's public scoreboard JSON (unofficial, best effort, 45 s cache); finished
matches already in the database are answered from there. The page re-polls every minute while a match is in play.

**Commentary** (`commentary()` in `src/web/static/app.js`) is generated in the browser from the numbers already on the
card, so it is rule-based text, not a model: before kick-off it states the market favourite, the analogue frequency and
whether the two agree (within 2 points = agree), the 2.5-goal view of both, and the first-half shares; in play it
conditions the 9-way HT/FT distribution of the analogues on the current half-time state and reports how many goals are
still needed for over 2.5 against the second-half goal counts; after the final whistle it says which of the two views
(market or history) sat closer to the actual result and total goals, and the day summary tallies that over every
finished match. The tally is descriptive: a good day does not overturn the blind backtest, which is stated next to it.

Railway, second service from the same repository:

1. New service → GitHub repo `senirlioglu/Asistan`, branch of your choice.
2. Settings → **Root Directory** = `football_odds` (so `Procfile` / `railway.json` / `requirements.txt` here are used).
3. Variables (all optional): `FO_DAILY_UTC=06:30`, `FO_DAYS_AHEAD=7`, `FO_ADMIN_KEY=<secret>`, `LOG_LEVEL=INFO`.
4. Generate a domain. First boot downloads 256 Football-Data files and builds the database (3–5 min); the page shows the
   progress in the status panel until the first prediction file exists.

The filesystem is ephemeral: every redeploy re-downloads the data (cached copies are not kept). Mount a volume at
`/app/football_odds/data` to keep them. The backtest results in `results/backtest/` ship with the repository, so the
30-minute backtest never runs on the server.

Streamlit Cloud works too (main file `football_odds/src/dashboard/app.py`), but it has no scheduler and sleeps when idle:
use the *Refresh now* button, or trigger the GitHub Actions workflow and read its artifacts.

## Daily automation

`.github/workflows/football-odds-daily.yml` runs `download → build → today --days 7` every morning (06:30 UTC) or on demand
(`workflow_dispatch`), caches the raw Football-Data files between runs and uploads the prediction files as a workflow
artifact (30 days). Locally the equivalent is a cron line:

```
30 6 * * *  cd /path/to/football_odds && python -m src.cli today --update --days 7 >> results/daily.log 2>&1
```

## Output files

```
results/
  audit/                       column_availability.csv, market_availability_by_season.csv, data_dictionary.csv, audit_summary.md
  data_quality_report.md/.json
  backtest/                    summary.md, selected_params.json, validation_grid.csv, test_scores.csv,
                               test_scores_pinnacle_subset.csv, calibration.csv, test_stability.csv, test_ablation.csv,
                               feature_set_comparison.csv, scope_comparison.csv, roi.csv, favourite_buckets.csv,
                               league_calibration.csv, time_stability.csv, league_profiles.csv,
                               movement_opening_vs_closing.csv, movement_by_bucket.csv, movement_steam_vs_drift.csv
  league_groups.json
  YYYY-MM-DD_predictions.csv / .xlsx     main table (date, time, league, teams, odds, market %, N, hist %, adj %, edges,
                                         O/U %, BTTS %, avg goals, confidence, signal, CIs, fair odds, similarity quality)
  YYYY-MM-DD_details.json                scorelines, goal distribution, per-scope results, tolerance counts, signal reasons
  analogues/YYYY-MM-DD_analogues.parquet every analogue of every fixture (for the dashboard detail view)
```

## Project layout

```
football_odds/
  config/settings.yaml
  data/raw/<season>/<div>.csv        cached Football-Data files (+ .meta.json)
  data/processed/matches.parquet
  results/                           see above
  notebooks/
  src/
    cli.py                           command-line entry point
    config.py, logging_setup.py
    data/    schema.py (column map)  football_data.py (download/cache/parse)  providers.py (interfaces)
             build.py (parquet)      quality.py (report)                      audit.py (PHASE 1)
    features/ odds.py (margin, consensus, market features)  vectors.py (feature sets, Similarity %)
    models/   similarity.py (Model A/B, no-look-ahead pool)  stats.py (rates, Wilson, shrinkage)
              time_weights.py  signal.py  engine.py (analyze_match)
    backtest/ walk_forward.py  metrics.py  roi.py  buckets.py  movement.py  run.py
    pipeline/ today.py
    dashboard/ app.py
  tests/
```

### Providers

`HistoricalDataProvider` (`ParquetHistoricalProvider`) and `CurrentOddsProvider`
(`FootballDataFixturesProvider`, default; `TheOddsApiProvider` for
[the-odds-api.com](https://the-odds-api.com) with `THE_ODDS_API_KEY`, `current.provider: the_odds_api`).
Both return the same canonical frame, so the engine never changes when the source does.

## Assumptions and limitations

* Football-Data odds are pre-closing snapshots (Friday/Tuesday). Closing lines exist only from 2019/20.
* BTTS odds do not exist in the source; BTTS is a realised-score statistic only.
* The "market" baseline is the consensus average. Pinnacle is reported as a sharper benchmark
  where available; beating the average is a lower bar than beating Pinnacle closing.
* Adaptive neighbourhoods are evaluated inside the 500 nearest neighbours.
* The ROI simulation ignores stake limits, account restrictions and line movement after the
  Friday/Tuesday snapshot; it is an upper bound on what the signal could have earned.
* Correlation ≠ exploitable edge. Every number is reported with N, interval, out-of-sample
  score and the market benchmark, and the system is designed to output
  "NO STATISTICALLY MEANINGFUL DEVIATION" on ordinary days.
