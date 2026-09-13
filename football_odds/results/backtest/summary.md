# Walk-forward backtest summary

Generated: 2026-09-13T18:50:53.851192+00:00

Validation seasons: 2017/18, 2018/19, 2019/20, 2020/21  
Test seasons: 2021/22, 2022/23, 2023/24, 2024/25, 2025/26  
Test matches: 27812

## Verdict

**Historical similarity did not improve predictive performance** over the market baseline.

## Selected configuration (chosen on validation only)

| parameter | value |
|---|---|
| feature_set | 1x2 |
| metric | euclidean |
| scope | global |
| k | 500 |
| half_life_years | None |
| prior_strength | 50.0 |
| min_similarity | 97.0 |

## Out-of-sample scores (test seasons)

| model | Brier | log loss | Brier vs market | p-value | ECE |
|---|---|---|---|---|---|
| market | 0.58988 | 0.98863 | +0.00000 | nan | 0.0132 |
| hist | 0.59025 | 0.98915 | +0.00037 | 0.200 | 0.0064 |
| adj | 0.59004 | 0.98880 | +0.00016 | 0.535 | 0.0063 |

## Validation grid (top 10 adjusted configurations by log loss)

| feature set | metric | scope | K | half-life | prior | min sim | log loss | Brier | market Brier |
|---|---|---|---|---|---|---|---|---|---|
| 1x2 | euclidean | global | 500 | none | 50 | 97 | 0.99344 | 0.59285 | 0.59260 |
| 1x2 | manhattan | global | 500 | none | 50 | 97 | 0.99344 | 0.59288 | 0.59260 |
| 1x2 | manhattan | global | 500 | none | 50 | 0 | 0.99351 | 0.59291 | 0.59260 |
| 1x2 | euclidean | global | 500 | none | 50 | 0 | 0.99352 | 0.59289 | 0.59260 |
| 1x2 | manhattan | global | 500 | 5.0 | 50 | 97 | 0.99359 | 0.59298 | 0.59260 |
| 1x2 | euclidean | global | 500 | 5.0 | 50 | 97 | 0.99361 | 0.59296 | 0.59260 |
| 1x2 | manhattan | global | 500 | 5.0 | 50 | 0 | 0.99366 | 0.59302 | 0.59260 |
| 1x2 | euclidean | global | 500 | 5.0 | 50 | 0 | 0.99368 | 0.59300 | 0.59260 |
| 1x2_ou | manhattan | global | 500 | 5.0 | 50 | 0 | 0.99380 | 0.59308 | 0.59248 |
| 1x2_ou | manhattan | global | 500 | none | 50 | 0 | 0.99387 | 0.59309 | 0.59248 |

## Stability of the adjusted model vs market (test seasons)

| group | n | Brier market | Brier adj | diff | p | adj better |
|---|---|---|---|---|---|---|
| season=2122 | 5671 | 0.59355 | 0.59361 | +0.00006 | 0.914 | no |
| season=2223 | 5605 | 0.58868 | 0.58874 | +0.00006 | 0.913 | no |
| season=2324 | 5602 | 0.58381 | 0.58385 | +0.00004 | 0.938 | no |
| season=2425 | 5485 | 0.58812 | 0.58821 | +0.00009 | 0.883 | no |
| season=2526 | 5449 | 0.59532 | 0.59587 | +0.00056 | 0.351 | no |
| league=B1 | 1547 | 0.58779 | 0.58732 | -0.00047 | 0.666 | yes |
| league=D1 | 1530 | 0.57925 | 0.58040 | +0.00115 | 0.296 | no |
| league=D2 | 1530 | 0.62261 | 0.62278 | +0.00016 | 0.884 | no |
| league=E0 | 1900 | 0.56988 | 0.57085 | +0.00097 | 0.331 | no |
| league=E1 | 2760 | 0.62247 | 0.62477 | +0.00230 | 0.006 | no |
| league=F1 | 1678 | 0.58616 | 0.58752 | +0.00137 | 0.189 | no |
| league=F2 | 1749 | 0.62771 | 0.62986 | +0.00215 | 0.036 | no |
| league=G1 | 1189 | 0.56148 | 0.56114 | -0.00034 | 0.798 | yes |
| league=I1 | 1899 | 0.57860 | 0.57885 | +0.00025 | 0.809 | no |
| league=I2 | 1899 | 0.63005 | 0.62810 | -0.00195 | 0.043 | yes |
| league=N1 | 1530 | 0.55578 | 0.55674 | +0.00095 | 0.383 | no |
| league=P1 | 1530 | 0.53658 | 0.53404 | -0.00253 | 0.019 | yes |
| league=SC0 | 1140 | 0.55293 | 0.55186 | -0.00107 | 0.399 | yes |
| league=SP1 | 1900 | 0.57426 | 0.57325 | -0.00101 | 0.314 | yes |
| league=SP2 | 2310 | 0.62187 | 0.62225 | +0.00037 | 0.666 | no |
| league=T1 | 1721 | 0.57135 | 0.56976 | -0.00159 | 0.113 | yes |

## Flat-stake ROI simulation (test seasons, 1 unit per bet)

Bets are placed on every outcome whose adjusted probability exceeds the market by the threshold.
`avg` uses the consensus average odds, `max` the best available price (optimistic bound).

| price | threshold pp | bets | win rate | avg odds | profit | ROI % | max DD | profitable seasons |
|---|---|---|---|---|---|---|---|---|
| avg | 2.0 | 16136 | 46.7% | 2.46 | -513.2 | -3.18 | 561.9 | 0/5 |
| avg | 3.0 | 8660 | 51.0% | 2.28 | -172.4 | -1.99 | 219.2 | 1/5 |
| avg | 5.0 | 1458 | 54.5% | 2.11 | -6.1 | -0.42 | 45.0 | 2/5 |
| avg | 7.5 | 33 | 60.6% | 1.91 | -2.2 | -6.73 | 6.4 | 3/5 |
| avg | 10.0 | 1 | 100.0% | 1.81 | +0.8 | +81.00 | 0.0 | 1/1 |
| max | 2.0 | 16136 | 46.7% | 2.57 | +96.2 | +0.60 | 157.3 | 4/5 |
| max | 3.0 | 8660 | 51.0% | 2.38 | +143.1 | +1.65 | 77.0 | 4/5 |
| max | 5.0 | 1458 | 54.5% | 2.20 | +44.4 | +3.04 | 26.1 | 4/5 |
| max | 7.5 | 33 | 60.6% | 1.98 | -1.3 | -4.03 | 5.8 | 3/5 |
| max | 10.0 | 1 | 100.0% | 1.88 | +0.9 | +88.00 | 0.0 | 1/1 |

## Similar-league groups (hierarchical clustering of league profiles)

- B1, E1, G1, P1, SC0, SP2, T1
- D1, E0, F1, I1, N1, SP1
- D2, F2, I2

## Odds movement

Matches with closing odds: 39300. Closing-probability buckets where steam vs drift realised rates differ at p < 0.05: 0 of 14.
See movement_by_bucket.csv and movement_steam_vs_drift.csv.

## Reading these numbers

- A negative *Brier vs market* means the model is better calibrated than the consensus odds out-of-sample.
- Correlation ≠ exploitable edge: the ROI table uses pre-closing average odds without accounting for limits,
  line movement after collection or bookmaker restrictions.
- Parameters were chosen on the validation seasons only; every number above is from unseen test seasons.
