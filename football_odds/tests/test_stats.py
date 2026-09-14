import numpy as np
import pandas as pd
import pytest

from src.models.stats import (confidence_label, fair_odds, market_outside_ci, outcome_stats, shrink, wilson_interval)
from src.models.time_weights import effective_n, time_weights


def test_wilson_interval_spec_example():
    lo, hi = wilson_interval(0.618, 327)
    assert lo == pytest.approx(0.564, abs=0.005)
    assert hi == pytest.approx(0.669, abs=0.005)
    assert wilson_interval(0.5, 0) == (pytest.approx(float("nan"), nan_ok=True), pytest.approx(float("nan"), nan_ok=True))


def test_shrinkage_pulls_small_samples_to_market():
    market = np.array([0.55, 0.25, 0.20])
    hist = np.array([14 / 18, 2 / 18, 2 / 18])
    adj = shrink(hist, 18, market, 50)
    assert adj.sum() == pytest.approx(1.0)
    assert market[0] < adj[0] < hist[0]
    # 18/(18+50) of the way from market to hist
    assert adj[0] == pytest.approx(market[0] + 18 / 68 * (hist[0] - market[0]))
    assert np.allclose(shrink(hist, 0, market, 50), market)
    assert np.allclose(shrink(hist, 1000, market, 0), hist)


def test_confidence_labels():
    assert confidence_label(10) == "VERY LOW"
    assert confidence_label(50) == "LOW"
    assert confidence_label(150) == "MEDIUM"
    assert confidence_label(300) == "HIGH"


def test_time_weights_half_life():
    w = time_weights(np.array([0.0, 5.0, 10.0]), 5)
    assert w[0] == pytest.approx(1.0) and w[1] == pytest.approx(0.5) and w[2] == pytest.approx(0.25)
    assert (time_weights(np.array([0.0, 7.0]), None) == 1).all()
    assert effective_n(np.ones(40)) == pytest.approx(40)
    assert effective_n(np.array([1.0, 0.0, 0.0])) == pytest.approx(1.0)


def test_outcome_stats_basic():
    neigh = pd.DataFrame({
        "result_code": [0, 0, 1, 2], "fthg": [2, 1, 1, 0], "ftag": [0, 0, 1, 3],
    })
    st = outcome_stats(neigh)
    assert st.n == 4 and st.n_eff == pytest.approx(4)
    assert st.home == pytest.approx(0.5) and st.draw == pytest.approx(0.25) and st.away == pytest.approx(0.25)
    assert st.over25 == pytest.approx(0.25)
    assert st.btts_yes == pytest.approx(0.25)
    assert st.avg_goals == pytest.approx(2.0)
    assert st.scorelines["1-1"] == pytest.approx(0.25)
    assert st.goals_dist["2"] == pytest.approx(0.5)
    # weighting: only the first match counts
    st_w = outcome_stats(neigh, np.array([1.0, 0, 0, 0]))
    assert st_w.home == pytest.approx(1.0) and st_w.n_eff == pytest.approx(1.0)


def test_half_time_layer():
    from src.models.stats import htft_label

    neigh = pd.DataFrame({
        "result_code": [0, 2, 1, 0], "fthg": [2, 0, 1, 1], "ftag": [1, 1, 1, 0], "ftr": ["H", "A", "D", "H"],
        "htr": ["D", "A", "D", None],  # last row: half-time unknown -> excluded from the HT layer only
        "hthg": [0, 0, 1, None], "htag": [0, 1, 1, None],
    })
    st = outcome_stats(neigh)
    assert st.n == 4 and st.n_ht == 3
    # halves: first-half goals 0, 1, 2 ; second-half goals 3, 0, 0
    h = st.halves
    assert h["n"] == 3
    assert h["fh_avg"] == pytest.approx(1.0) and h["sh_avg"] == pytest.approx(1.0)
    assert h["fh_over05"] == pytest.approx(2 / 3) and h["fh_over15"] == pytest.approx(1 / 3)
    assert h["sh_over05"] == pytest.approx(1 / 3) and h["sh_over15"] == pytest.approx(1 / 3)
    assert h["more_goals_2h"] == pytest.approx(1 / 3) and h["equal_halves"] == pytest.approx(0.0)
    assert st.ht_draw == pytest.approx(2 / 3) and st.ht_away == pytest.approx(1 / 3) and st.ht_home == pytest.approx(0.0)
    assert st.htft["X/1"] == pytest.approx(1 / 3) and st.htft["2/2"] == pytest.approx(1 / 3) and st.htft["X/X"] == pytest.approx(1 / 3)
    assert sum(st.htft.values()) == pytest.approx(1.0)
    assert htft_label("H", "A") == "1/2" and htft_label("D", "D") == "X/X" and htft_label(None, "H") == ""


def test_fair_odds_and_ci_check():
    assert fair_odds(0.618) == pytest.approx(1.618, abs=1e-3)
    assert market_outside_ci(0.55, (0.564, 0.669))
    assert not market_outside_ci(0.60, (0.564, 0.669))
