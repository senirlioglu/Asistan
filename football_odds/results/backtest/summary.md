# Walk-forward backtest summary

Generated: 2026-09-13T20:30:58.999440+00:00

Validation seasons: 2017/18, 2018/19, 2019/20, 2020/21  
Test seasons: 2021/22, 2022/23, 2023/24, 2024/25, 2025/26  
Test matches: 27812

## Verdict

Historical similarity matched the market baseline but the difference is **not statistically significant** — historical similarity did not improve predictive performance.

## Selected configuration (chosen on validation only)

| parameter | value |
|---|---|
| feature_set | 1x2 |
| metric | cosine |
| scope | global |
| k | 500 |
| half_life_years | None |
| prior_strength | 200.0 |
| min_similarity | 97.0 |

One-standard-error rule: 48 configurations lie within SE=0.00026 of the best validation log loss (0.99261 vs market 0.99266); the largest-K / simplest one was chosen. Raw best: 1x2_ou / mahalanobis / global / K=50 / half-life=3.0 / prior=200.0 / min sim=0.0.

## Out-of-sample scores (test seasons)

| model | Brier | log loss | Brier vs market | p-value | ECE |
|---|---|---|---|---|---|
| market | 0.58988 | 0.98863 | +0.00000 | nan | 0.0132 |
| hist | 0.59025 | 0.98911 | +0.00036 | 0.201 | 0.0068 |
| adj | 0.58974 | 0.98828 | -0.00014 | 0.495 | 0.0071 |

## Validation grid (top 10 adjusted configurations by log loss)

| feature set | metric | scope | K | half-life | prior | min sim | log loss | Brier | market Brier |
|---|---|---|---|---|---|---|---|---|---|
| 1x2_ou | mahalanobis | global | 50 | 3.0 | 200 | 0 | 0.99261 | 0.59244 | 0.59248 |
| 1x2_ou | mahalanobis | global | 50 | 5.0 | 200 | 0 | 0.99262 | 0.59244 | 0.59248 |
| 1x2_ou | mahalanobis | global | 50 | 7.0 | 200 | 0 | 0.99262 | 0.59244 | 0.59248 |
| 1x2_ou | mahalanobis | global | 50 | none | 200 | 0 | 0.99265 | 0.59245 | 0.59248 |
| 1x2 | cosine | global | 500 | none | 200 | 97 | 0.99275 | 0.59250 | 0.59260 |
| 1x2_ou | mahalanobis | global | 100 | 3.0 | 200 | 0 | 0.99276 | 0.59251 | 0.59248 |
| 1x2 | cosine | global | 500 | none | 200 | 95 | 0.99277 | 0.59251 | 0.59260 |
| 1x2 | cosine | global | 500 | none | 200 | 92 | 0.99278 | 0.59252 | 0.59260 |
| 1x2 | cosine | global | 500 | 7.0 | 200 | 97 | 0.99278 | 0.59254 | 0.59260 |
| 1x2 | euclidean | global | 500 | none | 200 | 97 | 0.99278 | 0.59253 | 0.59260 |

## Stability of the adjusted model vs market (test seasons)

| group | n | Brier market | Brier adj | diff | p | adj better |
|---|---|---|---|---|---|---|
| season=2122 | 5671 | 0.59355 | 0.59343 | -0.00012 | 0.783 | yes |
| season=2223 | 5605 | 0.58868 | 0.58845 | -0.00023 | 0.613 | yes |
| season=2324 | 5602 | 0.58381 | 0.58356 | -0.00025 | 0.576 | yes |
| season=2425 | 5485 | 0.58812 | 0.58792 | -0.00020 | 0.659 | yes |
| season=2526 | 5449 | 0.59532 | 0.59543 | +0.00012 | 0.803 | no |
| league=B1 | 1547 | 0.58779 | 0.58718 | -0.00061 | 0.474 | yes |
| league=D1 | 1530 | 0.57925 | 0.57977 | +0.00052 | 0.544 | no |
| league=D2 | 1530 | 0.62261 | 0.62247 | -0.00014 | 0.873 | yes |
| league=E0 | 1900 | 0.56988 | 0.57026 | +0.00038 | 0.623 | no |
| league=E1 | 2760 | 0.62247 | 0.62399 | +0.00152 | 0.020 | no |
| league=F1 | 1678 | 0.58616 | 0.58689 | +0.00073 | 0.370 | no |
| league=F2 | 1749 | 0.62771 | 0.62919 | +0.00148 | 0.066 | no |
| league=G1 | 1189 | 0.56148 | 0.56106 | -0.00042 | 0.688 | yes |
| league=I1 | 1899 | 0.57860 | 0.57865 | +0.00005 | 0.951 | no |
| league=I2 | 1899 | 0.63005 | 0.62828 | -0.00177 | 0.020 | yes |
| league=N1 | 1530 | 0.55578 | 0.55615 | +0.00036 | 0.669 | no |
| league=P1 | 1530 | 0.53658 | 0.53436 | -0.00221 | 0.009 | yes |
| league=SC0 | 1140 | 0.55293 | 0.55179 | -0.00114 | 0.249 | yes |
| league=SP1 | 1900 | 0.57426 | 0.57313 | -0.00113 | 0.151 | yes |
| league=SP2 | 2310 | 0.62187 | 0.62204 | +0.00017 | 0.805 | no |
| league=T1 | 1721 | 0.57135 | 0.56987 | -0.00148 | 0.060 | yes |

## Flat-stake ROI simulation (test seasons, 1 unit per bet)

Bets are placed on every outcome whose adjusted probability exceeds the market by the threshold.
`avg` uses the consensus average odds, `max` the best available price (optimistic bound).

| price | threshold pp | bets | win rate | avg odds | profit | ROI % | max DD | profitable seasons |
|---|---|---|---|---|---|---|---|---|
| avg | 2.0 | 11631 | 49.3% | 2.35 | -258.1 | -2.22 | 322.0 | 1/5 |
| avg | 3.0 | 4707 | 52.1% | 2.20 | -129.4 | -2.75 | 144.6 | 1/5 |
| avg | 5.0 | 211 | 60.7% | 1.82 | -12.5 | -5.91 | 16.6 | 1/5 |
| avg | 7.5 | 0 | - | - | +0.0 | - | 0.0 | 0/0 |
| avg | 10.0 | 0 | - | - | +0.0 | - | 0.0 | 0/0 |
| max | 2.0 | 11631 | 49.3% | 2.45 | +174.0 | +1.50 | 106.4 | 4/5 |
| max | 3.0 | 4707 | 52.1% | 2.29 | +36.5 | +0.78 | 63.2 | 3/5 |
| max | 5.0 | 211 | 60.7% | 1.88 | -6.6 | -3.14 | 11.8 | 2/5 |
| max | 7.5 | 0 | - | - | +0.0 | - | 0.0 | 0/0 |
| max | 10.0 | 0 | - | - | +0.0 | - | 0.0 | 0/0 |

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
