# Walk-forward backtest summary

Generated: 2026-09-14T19:41:24.772627+00:00

Validation seasons: 2017/18, 2018/19, 2019/20, 2020/21  
Test seasons: 2021/22, 2022/23, 2023/24, 2024/25, 2025/26  
Test matches: 38732

## Verdict

**Historical similarity did not improve predictive performance** over the market baseline.

## Selected configuration (chosen on validation only)

| parameter | value |
|---|---|
| feature_set | 1x2_ou |
| metric | mahalanobis |
| scope | global |
| k | 100 |
| half_life_years | None |
| prior_strength | 200.0 |
| min_similarity | 0.0 |

One-standard-error rule: 16 configurations lie within SE=0.00016 of the best validation log loss (1.00435 vs market 1.00419); the largest-K / simplest one was chosen. Raw best: 1x2_ou / euclidean / same_league / K=25 / half-life=3.0 / prior=200.0 / min sim=0.0.

## Out-of-sample scores (test seasons)

| model | Brier | log loss | Brier vs market | p-value | ECE |
|---|---|---|---|---|---|
| market | 0.59715 | 0.99907 | +0.00000 | nan | 0.0112 |
| hist | 0.60268 | 1.00851 | +0.00553 | 0.000 | 0.0150 |
| adj | 0.59747 | 0.99946 | +0.00032 | 0.044 | 0.0079 |

## Validation grid (top 10 adjusted configurations by log loss)

| feature set | metric | scope | K | half-life | prior | min sim | log loss | Brier | market Brier |
|---|---|---|---|---|---|---|---|---|---|
| 1x2_ou | euclidean | same_league | 25 | 3.0 | 200 | 0 | 1.00435 | 0.60068 | 0.60054 |
| 1x2_ou | cosine | same_league | 25 | 3.0 | 200 | 0 | 1.00436 | 0.60069 | 0.60054 |
| 1x2_ou | euclidean | same_league | 25 | 5.0 | 200 | 0 | 1.00437 | 0.60070 | 0.60054 |
| 1x2_ou | cosine | same_league | 25 | 5.0 | 200 | 0 | 1.00437 | 0.60070 | 0.60054 |
| 1x2_ou | euclidean | same_league | 25 | 7.0 | 200 | 0 | 1.00437 | 0.60070 | 0.60054 |
| 1x2_ou | cosine | same_league | 25 | 7.0 | 200 | 0 | 1.00437 | 0.60071 | 0.60054 |
| 1x2_ou | cosine | same_league | 25 | none | 200 | 0 | 1.00438 | 0.60071 | 0.60054 |
| 1x2_ou | euclidean | same_league | 25 | none | 200 | 0 | 1.00438 | 0.60072 | 0.60054 |
| 1x2_ou | mahalanobis | global | 100 | none | 200 | 0 | 1.00443 | 0.60062 | 0.60054 |
| 1x2_ou | manhattan | same_league | 25 | 3.0 | 200 | 0 | 1.00443 | 0.60073 | 0.60054 |

## Stability of the adjusted model vs market (test seasons)

| group | n | Brier market | Brier adj | diff | p | adj better |
|---|---|---|---|---|---|---|
| season=2122 | 7821 | 0.59756 | 0.59752 | -0.00003 | 0.926 | yes |
| season=2223 | 7800 | 0.59531 | 0.59548 | +0.00017 | 0.637 | no |
| season=2324 | 7797 | 0.59475 | 0.59503 | +0.00028 | 0.427 | no |
| season=2425 | 7681 | 0.59816 | 0.59901 | +0.00085 | 0.017 | no |
| season=2526 | 7633 | 0.60004 | 0.60038 | +0.00034 | 0.342 | no |
| league=B1 | 1547 | 0.58779 | 0.58796 | +0.00018 | 0.835 | no |
| league=D1 | 1530 | 0.57925 | 0.57979 | +0.00054 | 0.482 | no |
| league=D2 | 1530 | 0.62261 | 0.62263 | +0.00002 | 0.985 | no |
| league=E0 | 1900 | 0.56988 | 0.57101 | +0.00113 | 0.117 | no |
| league=E1 | 2760 | 0.62247 | 0.62358 | +0.00111 | 0.073 | no |
| league=E2 | 2760 | 0.60626 | 0.60684 | +0.00058 | 0.322 | no |
| league=E3 | 2759 | 0.63030 | 0.63079 | +0.00049 | 0.425 | no |
| league=EC | 2701 | 0.60325 | 0.60316 | -0.00009 | 0.884 | yes |
| league=F1 | 1678 | 0.58616 | 0.58718 | +0.00102 | 0.183 | no |
| league=F2 | 1749 | 0.62771 | 0.62859 | +0.00088 | 0.235 | no |
| league=G1 | 1189 | 0.56148 | 0.56216 | +0.00068 | 0.451 | no |
| league=I1 | 1899 | 0.57860 | 0.57947 | +0.00087 | 0.231 | no |
| league=I2 | 1899 | 0.63005 | 0.62872 | -0.00133 | 0.065 | yes |
| league=N1 | 1530 | 0.55578 | 0.55729 | +0.00151 | 0.050 | no |
| league=P1 | 1530 | 0.53658 | 0.53455 | -0.00202 | 0.008 | yes |
| league=SC0 | 1140 | 0.55293 | 0.55348 | +0.00055 | 0.549 | no |
| league=SC1 | 900 | 0.63142 | 0.63322 | +0.00180 | 0.084 | no |
| league=SC2 | 900 | 0.59979 | 0.59895 | -0.00084 | 0.441 | yes |
| league=SC3 | 900 | 0.63690 | 0.63692 | +0.00002 | 0.985 | no |
| league=SP1 | 1900 | 0.57426 | 0.57462 | +0.00036 | 0.604 | no |
| league=SP2 | 2310 | 0.62187 | 0.62188 | +0.00000 | 0.996 | no |
| league=T1 | 1721 | 0.57135 | 0.57067 | -0.00069 | 0.347 | yes |

## Flat-stake ROI simulation (test seasons, 1 unit per bet)

Bets are placed on every outcome whose adjusted probability exceeds the market by the threshold.
`avg` uses the consensus average odds, `max` the best available price (optimistic bound).

| price | threshold pp | bets | win rate | avg odds | profit | ROI % | max DD | profitable seasons |
|---|---|---|---|---|---|---|---|---|
| avg | 2.0 | 12711 | 43.8% | 2.54 | -327.3 | -2.57 | 380.7 | 1/5 |
| avg | 3.0 | 4116 | 45.4% | 2.39 | -191.6 | -4.65 | 230.2 | 1/5 |
| avg | 5.0 | 188 | 53.7% | 2.45 | +34.7 | +18.47 | 6.8 | 5/5 |
| avg | 7.5 | 2 | 0.0% | 6.56 | -2.0 | -100.00 | 2.0 | 0/2 |
| avg | 10.0 | 0 | - | - | +0.0 | - | 0.0 | 0/0 |
| max | 2.0 | 12711 | 43.8% | 2.66 | +196.3 | +1.54 | 133.0 | 4/5 |
| max | 3.0 | 4116 | 45.4% | 2.50 | -32.4 | -0.79 | 146.6 | 3/5 |
| max | 5.0 | 188 | 53.7% | 2.56 | +44.1 | +23.47 | 6.7 | 5/5 |
| max | 7.5 | 2 | 0.0% | 7.38 | -2.0 | -100.00 | 2.0 | 0/2 |
| max | 10.0 | 0 | - | - | +0.0 | - | 0.0 | 0/0 |

## Similar-league groups (hierarchical clustering of league profiles)

- ARG, BRA, F2, G1, I2, ROU, SC1, SP2
- AUT, B1, CHN, D1, D2, DNK, E0, E1, F1, I1, MEX, N1, NOR, SP1, SWE, SWZ, T1, USA
- E2, E3, EC, FIN, IRL, JPN, P1, POL, RUS, SC0, SC2, SC3

## Odds movement

Matches with closing odds: 54125. Closing-probability buckets where steam vs drift realised rates differ at p < 0.05: 1 of 14.
See movement_by_bucket.csv and movement_steam_vs_drift.csv.

## Reading these numbers

- A negative *Brier vs market* means the model is better calibrated than the consensus odds out-of-sample.
- Correlation ≠ exploitable edge: the ROI table uses pre-closing average odds without accounting for limits,
  line movement after collection or bookmaker restrictions.
- Parameters were chosen on the validation seasons only; every number above is from unseen test seasons.
