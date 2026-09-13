import numpy as np
import pandas as pd
import pytest

from src.backtest.walk_forward import compute_neighbours, evaluate_grid, predict_from_neighbours, season_test_frame
from src.models.engine import AnalysisParams, analyze_match, summaries_to_frame
from src.models.similarity import SimilarityIndex


def test_walk_forward_neighbours_never_see_the_future(history):
    idx = SimilarityIndex(history, "1x2")
    seasons = sorted(history["season"].unique())
    test_df = season_test_frame(history, seasons[-2:], "1x2")
    nm = compute_neighbours(idx, test_df, 50, "manhattan", "global")
    valid = nm.nb_idx >= 0
    nb_dates = idx.dates[np.where(valid, nm.nb_idx, 0)]
    test_dates = test_df["date"].to_numpy(dtype="datetime64[ns]")[:, None]
    assert (nb_dates[valid] < np.broadcast_to(test_dates, nb_dates.shape)[valid]).all()
    assert (nm.nb_years[valid] > 0).all()
    assert (nm.nb_result[valid] >= 0).all()


def test_predict_from_neighbours_shapes_and_shrinkage(history):
    idx = SimilarityIndex(history, "1x2")
    seasons = sorted(history["season"].unique())
    test_df = season_test_frame(history, seasons[-1:], "1x2")
    nm = compute_neighbours(idx, test_df, 100, "manhattan", "global")
    market = test_df[["p_home", "p_draw", "p_away"]].to_numpy()
    hist, adj, n_eff = predict_from_neighbours(nm, market, 100, 5.0, 50.0)
    assert hist.shape == market.shape and adj.shape == market.shape
    assert np.allclose(hist.sum(axis=1), 1.0) and np.allclose(adj.sum(axis=1), 1.0)
    assert (n_eff <= 100 + 1e-9).all() and (n_eff > 0).all()
    # adjusted lies between market and raw historical for every cell
    lo = np.minimum(hist, market) - 1e-9
    hi = np.maximum(hist, market) + 1e-9
    assert ((adj >= lo) & (adj <= hi)).all()
    # zero prior => adjusted equals the raw historical rate (same weighting)
    hist0, adj0, _ = predict_from_neighbours(nm, market, 100, None, 0.0)
    assert np.allclose(adj0, hist0)
    # unweighted vs time-weighted must differ (the pool spans ten years)
    assert not np.allclose(hist0, hist)


def test_evaluate_grid_rows(history):
    idx = SimilarityIndex(history, "1x2")
    seasons = sorted(history["season"].unique())
    test_df = season_test_frame(history, seasons[-1:], "1x2")
    nm = compute_neighbours(idx, test_df, 100, "manhattan", "global")
    market = test_df[["p_home", "p_draw", "p_away"]].to_numpy()
    res = test_df["result_code"].to_numpy(dtype=int)
    tab = evaluate_grid(nm, market, res, [25, 100], [None, 5.0], [0.0, 50.0, 1e6], [0.0, 97.0])
    assert {"hist", "adj"} == set(tab["model"])
    assert (tab["brier_market"] == tab["brier_market"].iloc[0]).all()
    # a huge prior collapses the adjusted model onto the market -> identical Brier score
    huge = tab[(tab["model"] == "adj") & (tab["prior_strength"] == 1e6)]
    assert np.allclose(huge["brier"], huge["brier_market"], atol=1e-4)
    # adaptive variants are only evaluated on the widest K
    assert (tab.loc[tab["min_similarity"] > 0, "k"] == 100).all()


def test_analyze_match_end_to_end(history, settings):
    idx = SimilarityIndex(history, "1x2")
    row = history.sort_values("date").iloc[-1]
    params = AnalysisParams(k=100, half_life_years=5, prior_strength=50)
    a = analyze_match(idx, row, row["date"], params, settings, backtest_ok=True, tolerance_levels=[0.01, 0.05])
    s = a.summary
    assert s["n"] == 100 and s["home"] == row["home_team"]
    assert s["market_h"] + s["market_d"] + s["market_a"] == pytest.approx(100.0)
    assert s["adj_h"] + s["adj_d"] + s["adj_a"] == pytest.approx(100.0)
    assert s["signal"] in {"NEUTRAL", "MODERATE HISTORICAL DEVIATION", "STRONG HISTORICAL DEVIATION", "LOW SAMPLE"}
    assert s["tol_probs_5pct"] >= s["tol_probs_1pct"]
    assert len(a.analogues) == 100
    assert (pd.to_datetime(a.analogues["date"]) < row["date"]).all()
    assert {"global", "same_league"} <= set(a.scopes)
    frame = summaries_to_frame([a])
    assert "scorelines" not in frame.columns and len(frame) == 1
