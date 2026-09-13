import numpy as np
import pandas as pd

from src.backtest.run import select_configuration


def _row(k, hl, prior, logloss, se=0.0004, fs="1x2", metric="manhattan", model="adj"):
    return {"feature_set": fs, "metric": metric, "scope": "global", "k": k, "half_life": hl, "prior_strength": prior,
            "min_similarity": 0.0, "model": model, "logloss": logloss, "brier": 0.59, "logloss_market": 0.9930,
            "logloss_diff_se": se}


def test_one_se_rule_prefers_largest_k_within_band():
    rows = [
        _row(50, 3.0, 200.0, 0.99261),   # raw best
        _row(500, 0, 200.0, 0.99278),    # within 1 SE (0.0004) -> preferred: larger K, no decay
        _row(500, 5.0, 50.0, 0.99351),   # outside the band
        _row(250, 0, 200.0, 0.99280),
    ]
    rows.append(_row(500, 0, 0.0, 0.99200, model="hist"))  # hist rows must be ignored
    sel, info = select_configuration(pd.DataFrame(rows))
    assert sel["k"] == 500 and sel["half_life_years"] is None and sel["prior_strength"] == 200.0
    assert info["best"]["k"] == 50 and info["n_candidates"] == 3


def test_without_se_column_falls_back_to_raw_best():
    rows = [_row(50, 3.0, 200.0, 0.99261), _row(500, 0, 200.0, 0.99278)]
    df = pd.DataFrame(rows).drop(columns=["logloss_diff_se"])
    sel, info = select_configuration(df)
    assert sel["k"] == 50 and info["n_candidates"] == 1


def test_nan_se_is_treated_as_zero():
    rows = [_row(50, 3.0, 200.0, 0.99261, se=np.nan), _row(500, 0, 200.0, 0.99278, se=np.nan)]
    sel, _ = select_configuration(pd.DataFrame(rows))
    assert sel["k"] == 50
