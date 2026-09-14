"""Walk-forward neighbour search and vectorised evaluation of the parameter grid.

For every test match the admissible pool is *every match played strictly before that match's
date* (all earlier seasons + earlier rounds of the same season). Neighbours are computed once
per (feature_set, metric, scope) at ``k_max`` and every (K, half-life, prior strength,
similarity floor) variant is then evaluated on the stored neighbour matrix — the cheap part.

Note on the adaptive neighbourhood: the "min similarity" variants are evaluated *within* the
``k_max`` nearest neighbours, i.e. "all matches with similarity >= 97 % among the 500 nearest".
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass

import numpy as np
import pandas as pd

from ..features.vectors import feature_columns, feature_mask
from ..logging_setup import get_logger
from ..models.similarity import SimilarityIndex
from .metrics import brier_per_match, logloss_per_match, paired_difference

log = get_logger("backtest.walk_forward")


@dataclass
class NeighbourMatrix:
    feature_set: str
    metric: str
    scope: str
    test_index: np.ndarray       # positions of test rows in the frame passed in
    nb_idx: np.ndarray           # (n_test, k_max) positions in index.df, -1 = padding
    nb_sim: np.ndarray           # (n_test, k_max)
    nb_years: np.ndarray         # (n_test, k_max) age of the neighbour relative to the test match
    nb_result: np.ndarray        # (n_test, k_max) result code of the neighbour, -1 = padding


def compute_neighbours(index: SimilarityIndex, test_df: pd.DataFrame, k_max: int, metric: str, scope: str,
                       league_groups: dict[str, list[str]] | None = None) -> NeighbourMatrix:
    cols = feature_columns(index.feature_set)
    n = len(test_df)
    nb_idx = np.full((n, k_max), -1, dtype=int)
    nb_sim = np.full((n, k_max), np.nan)
    X = test_df[cols].to_numpy(dtype=float)
    dates = test_df["date"].to_numpy(dtype="datetime64[ns]")
    leagues = test_df["league"].to_numpy()
    if scope in ("same_league", "league_group"):
        groups = pd.DataFrame({"d": dates, "l": leagues}).groupby(["d", "l"], sort=True).indices
    else:
        groups = pd.DataFrame({"d": dates}).groupby("d", sort=True).indices
    for key, rows in groups.items():
        rows = np.asarray(rows)
        as_of = key[0] if isinstance(key, tuple) else key
        league = key[1] if isinstance(key, tuple) else None
        q_scope = scope
        if scope == "league_group":
            members = (league_groups or {}).get(str(league))
            if members and len(members) > 1:
                league = members
            else:  # no group for this league -> fall back to global
                q_scope = "global"
        idx, _, sim = index.query_batch(X[rows], pd.Timestamp(as_of), k_max, metric, q_scope, league)
        nb_idx[rows] = idx
        nb_sim[rows] = sim
    valid = nb_idx >= 0
    nb_years = np.full((n, k_max), np.nan)
    nb_result = np.full((n, k_max), -1, dtype=int)
    safe = np.where(valid, nb_idx, 0)
    nb_dates = index.dates[safe]
    nb_years[valid] = ((dates[:, None] - nb_dates).astype("timedelta64[D]").astype(float) / 365.25)[valid]
    res = index.df["result_code"].to_numpy(dtype=int)
    nb_result[valid] = res[safe][valid]
    return NeighbourMatrix(index.feature_set, metric, scope, np.arange(n), nb_idx, nb_sim, nb_years, nb_result)


def predict_from_neighbours(nm: NeighbourMatrix, market: np.ndarray, k: int, half_life: float | None,
                            prior_strength: float, min_similarity: float = 0.0) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Vectorised historical + adjusted probabilities. Returns (hist, adj, n_eff)."""
    idx = nm.nb_idx[:, :k]
    sim = nm.nb_sim[:, :k]
    years = nm.nb_years[:, :k]
    res = nm.nb_result[:, :k]
    valid = idx >= 0
    if min_similarity > 0:
        valid &= sim >= min_similarity
    if half_life:
        w = np.exp(-np.log(2.0) / half_life * np.clip(np.nan_to_num(years, nan=0.0), 0, None))
    else:
        w = np.ones_like(sim)
    w = np.where(valid, w, 0.0)
    wsum = w.sum(axis=1)
    n_eff = np.where(wsum > 0, wsum ** 2 / np.maximum(np.sum(w * w, axis=1), 1e-12), 0.0)
    hist = np.stack([np.sum(w * (res == c), axis=1) for c in range(3)], axis=1)
    with np.errstate(invalid="ignore", divide="ignore"):
        hist = hist / wsum[:, None]
    have = wsum > 0
    hist = np.where(have[:, None], hist, market)
    denom = n_eff[:, None] + prior_strength
    with np.errstate(invalid="ignore", divide="ignore"):
        adj = (n_eff[:, None] * hist + prior_strength * market) / denom
    adj = np.where(denom > 0, adj, market)  # no analogues and no prior -> fall back to the market
    adj = adj / adj.sum(axis=1, keepdims=True)
    return hist, adj, n_eff


def evaluate_grid(nm: NeighbourMatrix, market: np.ndarray, result_code: np.ndarray, ks: list[int],
                  half_lives: list[float | None], prior_strengths: list[float], min_sims: list[float]) -> pd.DataFrame:
    """Score every (K, half-life, prior, min-sim) combination on one neighbour matrix."""
    base_b = brier_per_match(market, result_code)
    base_l = logloss_per_match(market, result_code)
    rows = []
    for k, hl, m, ms in itertools.product(ks, half_lives, prior_strengths, min_sims):
        if ms > 0 and k != max(ks):
            continue  # adaptive variants are defined on the widest neighbourhood only
        hist, adj, n_eff = predict_from_neighbours(nm, market, k, hl, m, ms)
        for name, probs in (("hist", hist), ("adj", adj)):
            if name == "hist" and m != prior_strengths[0]:
                continue  # raw historical rate does not depend on the prior
            b = brier_per_match(probs, result_code)
            ll = logloss_per_match(probs, result_code)
            pb = paired_difference(b, base_b)
            pl = paired_difference(ll, base_l)
            rows.append({
                "feature_set": nm.feature_set, "metric": nm.metric, "scope": nm.scope, "k": k,
                "half_life": hl if hl is not None else 0, "prior_strength": m if name == "adj" else np.nan,
                "min_similarity": ms, "model": name, "n": len(result_code),
                "brier": float(b.mean()), "logloss": float(ll.mean()),
                "brier_market": float(base_b.mean()), "logloss_market": float(base_l.mean()),
                "brier_diff": pb["mean_diff"], "brier_p_value": pb["p_value"],
                "logloss_diff": pl["mean_diff"], "logloss_diff_se": pl["se"], "logloss_p_value": pl["p_value"],
                "n_eff_median": float(np.median(n_eff)), "n_eff_p10": float(np.percentile(n_eff, 10)),
                "share_low_sample": float(np.mean(n_eff < 100)),
            })
    return pd.DataFrame(rows)


def season_test_frame(df: pd.DataFrame, seasons: list[str], feature_set: str, leagues: list[str] | None = None) -> pd.DataFrame:
    mask = df["season"].isin(seasons) & feature_mask(df, feature_set) & df["result_code"].notna()
    if leagues:
        mask &= df["league"].isin(leagues)
    return df.loc[mask].sort_values(["date", "match_id"]).reset_index(drop=True)
