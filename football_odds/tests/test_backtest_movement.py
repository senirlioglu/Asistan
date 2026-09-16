"""Steam vs drift is a grid — two outcomes by seven price bands — and a grid read without a
correction manufactures a finding about every twenty cells."""

import numpy as np
import pandas as pd

from src.backtest.movement import steam_vs_drift_test


def _cell(outcome, bucket, p_steam, p_drift, n=3000):
    return [{"outcome": outcome, "closing_bucket": bucket, "movement": "steam (>= +2pp)", "n": n,
             "actual_pct": 100 * p_steam, "closing_prob_pct": 100 * p_drift, "diff_pp": 0.0,
             "ci_lo_pct": 0.0, "ci_hi_pct": 0.0},
            {"outcome": outcome, "closing_bucket": bucket, "movement": "drift (<= -2pp)", "n": n,
             "actual_pct": 100 * p_drift, "closing_prob_pct": 100 * p_drift, "diff_pp": 0.0,
             "ci_lo_pct": 0.0, "ci_hi_pct": 0.0}]


def test_every_cell_carries_the_corrected_value_not_only_its_own_p():
    rng = np.random.default_rng(3)
    rows = []
    for i in range(14):                       # the real grid's size: 2 outcomes x 7 bands
        n, truth = 3000, 0.40                 # a true null: both arms are the same coin
        steam, drift = rng.binomial(n, truth) / n, rng.binomial(n, truth) / n
        rows += _cell("home" if i % 2 else "away", f"b{i}", steam, drift, n=n)
    out = steam_vs_drift_test(pd.DataFrame(rows))
    assert "q_value" in out and len(out) == 14
    assert (out["q_value"] >= out["p_value"] - 5e-5).all()          # BH never shrinks a p-value (q is stored to 4 dp)
    # a grid of noise may well produce a cell under 0.05 raw; none of them may be called a finding
    assert (out["q_value"] > 0.05).all()


def test_a_real_difference_still_survives_the_correction():
    rows = _cell("home", "0.40-0.50", 0.52, 0.40, n=4000)
    for i in range(13):
        rows += _cell("away", f"b{i}", 0.40, 0.40)
    out = steam_vs_drift_test(pd.DataFrame(rows))
    hit = out[out["closing_bucket"] == "0.40-0.50"].iloc[0]
    assert hit["q_value"] <= 0.05 and hit["diff_pp"] > 10


def test_an_empty_grid_does_not_explode():
    assert steam_vs_drift_test(pd.DataFrame(columns=["outcome", "closing_bucket", "movement", "n", "actual_pct"])).empty
