# Market re-calibration backtest

Test seasons: 2021/22, 2022/23, 2023/24, 2024/25, 2025/26 · 27812 matches · training = all seasons strictly before each test season.

## Verdict

Re-calibrating the market on past seasons **improved** out-of-sample Brier (p < 0.05): best model `isotonic` Brier 0.58941 vs market 0.58988 (-0.00047, p=0.017); better in 4/5 test seasons.

## Scores

| model | Brier | log loss | Brier vs market | p |
|---|---|---|---|---|
| market | 0.58988 | 0.98863 | +0.00000 | nan |
| isotonic | 0.58941 | 0.98830 | -0.00047 | 0.017 |
| bucket | 0.58960 | 0.98813 | -0.00028 | 0.174 |

## Per season

| season | model | n | Brier market | Brier model | diff | p |
|---|---|---|---|---|---|---|
| 2021/22 | isotonic | 5671 | 0.59355 | 0.59358 | +0.00004 | 0.935 |
| 2021/22 | bucket | 5671 | 0.59355 | 0.59351 | -0.00004 | 0.932 |
| 2022/23 | isotonic | 5605 | 0.58868 | 0.58808 | -0.00060 | 0.161 |
| 2022/23 | bucket | 5605 | 0.58868 | 0.58870 | +0.00002 | 0.965 |
| 2023/24 | isotonic | 5602 | 0.58381 | 0.58271 | -0.00110 | 0.013 |
| 2023/24 | bucket | 5602 | 0.58381 | 0.58300 | -0.00081 | 0.076 |
| 2024/25 | isotonic | 5485 | 0.58812 | 0.58801 | -0.00012 | 0.794 |
| 2024/25 | bucket | 5485 | 0.58812 | 0.58813 | +0.00001 | 0.981 |
| 2025/26 | isotonic | 5449 | 0.59532 | 0.59475 | -0.00056 | 0.187 |
| 2025/26 | bucket | 5449 | 0.59532 | 0.59474 | -0.00058 | 0.216 |

## Flat-stake ROI (1 unit, thresholds on model − market probability)

| model | price | threshold pp | bets | win rate | avg odds | profit | ROI % | max DD | profitable seasons |
|---|---|---|---|---|---|---|---|---|---|
| isotonic | avg | 2.0 | 10246 | 59.7% | 1.81 | -205.9 | -2.01 | 216.4 | 1/5 |
| isotonic | avg | 3.0 | 4746 | 70.5% | 1.47 | -46.6 | -0.98 | 68.7 | 2/5 |
| isotonic | avg | 5.0 | 874 | 79.9% | 1.26 | -4.9 | -0.56 | 15.6 | 2/5 |
| isotonic | avg | 7.5 | 15 | 73.3% | 1.08 | -3.2 | -21.07 | 3.4 | 2/4 |
| isotonic | avg | 10.0 | 0 | - | - | +0.0 | - | 0.0 | 0/0 |
| isotonic | max | 2.0 | 10246 | 59.7% | 1.87 | +116.6 | +1.14 | 70.6 | 3/5 |
| isotonic | max | 3.0 | 4746 | 70.5% | 1.51 | +85.4 | +1.80 | 34.8 | 4/5 |
| isotonic | max | 5.0 | 874 | 79.9% | 1.29 | +17.1 | +1.95 | 10.7 | 4/5 |
| isotonic | max | 7.5 | 15 | 73.3% | 1.10 | -2.9 | -19.67 | 3.2 | 2/4 |
| isotonic | max | 10.0 | 0 | - | - | +0.0 | - | 0.0 | 0/0 |
| bucket | avg | 2.0 | 10716 | 50.3% | 2.35 | -67.8 | -0.63 | 131.3 | 2/5 |
| bucket | avg | 3.0 | 3948 | 63.3% | 1.76 | +24.0 | +0.61 | 40.3 | 3/5 |
| bucket | avg | 5.0 | 644 | 72.5% | 1.40 | +1.7 | +0.27 | 21.3 | 4/5 |
| bucket | avg | 7.5 | 22 | 81.8% | 1.40 | +3.3 | +14.82 | 1.0 | 4/5 |
| bucket | avg | 10.0 | 0 | - | - | +0.0 | - | 0.0 | 0/0 |
| bucket | max | 2.0 | 10716 | 50.3% | 2.46 | +340.0 | +3.17 | 73.4 | 5/5 |
| bucket | max | 3.0 | 3948 | 63.3% | 1.83 | +148.1 | +3.75 | 25.6 | 5/5 |
| bucket | max | 5.0 | 644 | 72.5% | 1.44 | +19.1 | +2.96 | 19.3 | 4/5 |
| bucket | max | 7.5 | 22 | 81.8% | 1.44 | +4.0 | +18.00 | 1.0 | 4/5 |
| bucket | max | 10.0 | 0 | - | - | +0.0 | - | 0.0 | 0/0 |

The calibrators see only the margin-free market probability; the favourite-longshot pattern in
`favourite_buckets.csv` is exactly what they try to exploit. A negative *Brier vs market* with p < 0.05 and
most seasons better is the minimum bar before any of this is used live.
