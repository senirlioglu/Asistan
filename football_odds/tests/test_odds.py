import numpy as np
import pandas as pd
import pytest

from src.features.odds import (add_market_features, consensus_1x2, implied_probabilities, overround, remove_margin)


def test_spec_example_proportional():
    odds = np.array([[1.72, 3.80, 4.70]])
    raw = implied_probabilities(odds)
    p = remove_margin(raw, "proportional")[0]
    assert p.sum() == pytest.approx(1.0)
    assert p[0] == pytest.approx(0.550, abs=0.002)
    assert p[1] == pytest.approx(0.249, abs=0.002)
    assert p[2] == pytest.approx(0.201, abs=0.002)
    assert overround(raw)[0] == pytest.approx(1/1.72 + 1/3.8 + 1/4.7)


def test_invalid_odds_become_nan():
    raw = implied_probabilities(np.array([[1.0, 3.0, 4.0], [np.nan, 3.0, 4.0], [0.5, 3.0, 4.0], [2.0, 3.0, 4.0]]))
    assert np.isnan(raw[0, 0]) and np.isnan(raw[1, 0]) and np.isnan(raw[2, 0])
    p = remove_margin(raw)
    assert np.isnan(p[0]).all() and np.isnan(p[1]).all()
    assert p[3].sum() == pytest.approx(1.0)


@pytest.mark.parametrize("method", ["shin", "power"])
def test_alternative_methods_sum_to_one_and_favour_longshots_less(method):
    raw = implied_probabilities(np.array([[1.3, 5.5, 9.0]]))
    prop = remove_margin(raw, "proportional")[0]
    alt = remove_margin(raw, method)[0]
    assert alt.sum() == pytest.approx(1.0)
    # both Shin and power shave more margin from the longshot than proportional does
    assert alt[2] < prop[2]
    assert alt[0] > prop[0]


def test_unknown_method_raises():
    with pytest.raises(ValueError):
        remove_margin(np.array([[0.5, 0.3, 0.3]]), "magic")


def test_consensus_falls_back_to_bookmaker_mean():
    df = pd.DataFrame({
        "avg_h": [2.0, np.nan], "avg_d": [3.4, np.nan], "avg_a": [3.6, np.nan], "n_books_1x2": [30, np.nan],
        "raw__B365H": [2.1, 2.2], "raw__B365D": [3.3, 3.4], "raw__B365A": [3.5, 3.0],
        "raw__BWH": [2.0, 2.0], "raw__BWD": [3.5, 3.6], "raw__BWA": [3.7, np.nan],
    })
    out = consensus_1x2(df)
    assert list(out["consensus_source"]) == ["avg", "books_mean"]
    assert out.loc[0, "cons_h"] == 2.0
    # second row: BW quotes no away price -> only B365 counts
    assert out.loc[1, "cons_h"] == pytest.approx(2.2)
    assert out.loc[1, "n_books_used"] == 1


def test_add_market_features_flags_and_deltas():
    df = pd.DataFrame({
        "avg_h": [1.72], "avg_d": [3.8], "avg_a": [4.7], "n_books_1x2": [20],
        "avgc_h": [1.60], "avgc_d": [4.0], "avgc_a": [5.5],
        "avg_o25": [1.9], "avg_u25": [1.9], "b365_o25": [np.nan], "b365_u25": [np.nan], "p_o25": [np.nan], "p_u25": [np.nan],
        "ps_h": [np.nan], "ps_d": [np.nan], "ps_a": [np.nan], "psc_h": [np.nan], "psc_d": [np.nan], "psc_a": [np.nan],
        "avg_ahh": [np.nan], "avg_aha": [np.nan], "ah_line": [np.nan],
    })
    out = add_market_features(df)
    assert bool(out["has_1x2"][0]) and bool(out["has_ou"][0]) and bool(out["has_closing"][0]) and not bool(out["has_ah"][0])
    assert out["p_over25"][0] == pytest.approx(0.5)
    assert out["delta_p_home"][0] > 0  # 1.72 -> 1.60 means the home probability rose


def test_corrupt_overround_is_rejected():
    df = pd.DataFrame({"avg_h": [4.15], "avg_d": [1.25], "avg_a": [6.2], "n_books_1x2": [5]})
    for c in ["avgc_h", "avgc_d", "avgc_a", "avg_o25", "avg_u25", "b365_o25", "b365_u25", "p_o25", "p_u25",
              "ps_h", "ps_d", "ps_a", "psc_h", "psc_d", "psc_a", "avg_ahh", "avg_aha", "ah_line"]:
        df[c] = np.nan
    out = add_market_features(df, max_overround=1.15)
    assert not bool(out["has_1x2"][0])
