import numpy as np
import pytest

from src.backtest.metrics import brier, calibration_table, logloss, paired_difference, score_table
from src.backtest.roi import max_drawdown, simulate
import pandas as pd


def test_brier_and_logloss_bounds():
    probs = np.array([[1.0, 0.0, 0.0], [0.5, 0.25, 0.25]])
    res = np.array([0, 2])
    assert brier(probs[:1], res[:1]) == pytest.approx(0.0)
    assert brier(probs[1:], res[1:]) == pytest.approx(0.25 + 0.0625 + 0.5625)
    assert logloss(probs[1:], res[1:]) == pytest.approx(-np.log(0.25))


def test_paired_difference_sign():
    a = np.array([0.5, 0.6, 0.55, 0.52, 0.58, 0.61])
    b = a + np.array([0.09, 0.11, 0.10, 0.12, 0.08, 0.10])
    d = paired_difference(a, b)
    assert d["mean_diff"] == pytest.approx(-0.1)
    assert d["p_value"] < 0.01
    # identical losses -> zero difference, undefined z (no variance) but no crash
    same = paired_difference(a, a)
    assert same["mean_diff"] == 0.0 and np.isnan(same["p_value"])


def test_score_table_baseline_row_is_zero_diff():
    rng = np.random.default_rng(0)
    p = rng.dirichlet([2, 1, 1], 500)
    res = np.array([rng.choice(3, p=row) for row in p])
    tab = score_table({"market": p, "other": np.full_like(p, 1 / 3)}, res)
    assert tab.loc[tab["model"] == "market", "brier_vs_baseline"].iloc[0] == pytest.approx(0.0)
    assert tab.loc[tab["model"] == "other", "brier"].iloc[0] > tab.loc[tab["model"] == "market", "brier"].iloc[0]


def test_calibration_table_shape():
    rng = np.random.default_rng(1)
    p = rng.dirichlet([2, 1, 1], 2000)
    res = np.array([rng.choice(3, p=row) for row in p])
    tab = calibration_table(p, res, 10)
    assert set(tab["outcome"]) == {"H", "D", "A"}
    assert tab["n"].sum() == 3 * 2000
    # calibrated by construction -> gaps small on well-populated bins
    big = tab[tab["n"] > 200]
    assert (big["gap_pp"].abs() < 8).all()


def test_max_drawdown():
    assert max_drawdown(np.array([1, -1, -1, -1, 2])) == pytest.approx(3.0)
    assert max_drawdown(np.array([])) == 0.0


def test_simulate_flat_stake():
    df = pd.DataFrame({"date": pd.to_datetime(["2022-01-01", "2022-01-02"]), "season": ["2122", "2122"],
                       "result_code": [0, 2], "cons_h": [2.0, 2.0], "cons_d": [3.5, 3.5], "cons_a": [3.6, 3.6],
                       "max_h": [2.1, 2.1], "max_d": [3.7, 3.7], "max_a": [3.8, 3.8]})
    market = np.array([[0.5, 0.28, 0.22], [0.5, 0.28, 0.22]])
    adj = np.array([[0.56, 0.24, 0.20], [0.56, 0.24, 0.20]])  # +6 pp on home both times
    r = simulate(df, adj, market, 5.0, "avg")
    assert r["n_bets"] == 2 and r["wins"] == 1 and r["profit"] == pytest.approx(1.0 - 1.0)
    assert r["roi_pct"] == pytest.approx(0.0)
    assert simulate(df, adj, market, 10.0)["n_bets"] == 0
