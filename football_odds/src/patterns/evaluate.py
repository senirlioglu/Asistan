"""MODEL COMPARISON — does any of this add anything to the price?

Five models are scored on the same matches, walk-forward, each prediction using only what was
known before that match:

    A  piyasa        the margin-free consensus, exactly as the site shows it
    B  + benzerlik   the deployed system: 100 nearest matches by odds profile, shrunk to the market
    C  + pattern     the market plus the form-bucket residual measured ON THE TRAINING YEARS only
    D  + ikiz        the market plus what the twin engine's K twins did, shrunk to the market
    E  hepsi         C and D applied together

Reported for each: Brier, log loss, the paired difference against A with its p-value, calibration
error, the ROI of staking one unit on the model's own pick at the consensus price, and — where
closing odds exist (2019/20 onwards) — the closing-line value of those picks.

The question this file exists to answer is narrow and the answer is allowed to be no: does the
feature add information the price did not already have? A model that ties with A has failed, no
matter how interesting its internals are.

Walk-forward, per test season: train = every match played before that season started. Model C's
residuals are re-fitted on each train window, B and D see only matches before the match's own date.
"""

from __future__ import annotations

import datetime as dt

import numpy as np
import pandas as pd

from ..backtest.metrics import brier_per_match, logloss_per_match, paired_difference
from ..backtest.walk_forward import compute_neighbours, predict_from_neighbours
from ..config import Settings
from ..logging_setup import get_logger
from ..models.similarity import SimilarityIndex
from . import twins

log = get_logger("patterns.evaluate")

FEATURE_SET = "1x2_ou"        # the deployed configuration
METRIC, K_B, PRIOR = "mahalanobis", 100, 200.0
K_TWINS, PRIOR_TWINS = 200, 200.0
PTS_BUCKETS = [-1, 3, 7, 11, 15]      # points from the last five: poor / mixed / good / excellent
SHRINK_N = 300.0                      # a residual bucket needs this many training matches to count fully


def _pts_bucket(series: pd.Series) -> pd.Series:
    return pd.cut(pd.to_numeric(series, errors="coerce"), PTS_BUCKETS, labels=False)


def fit_pattern_residuals(train: pd.DataFrame) -> pd.DataFrame:
    """How far the outcome ran from the price, per (home form, away form) bucket, on TRAIN only.

    This is the pattern engine's finding turned into a model: if teams on a poor run lose more
    often than their price says, the residual carries it. Shrunk by the bucket's own size, so a
    thin bucket barely moves the price."""
    d = train.copy()
    d["hb"], d["ab"] = _pts_bucket(d["h_pts5"]), _pts_bucket(d["a_pts5"])
    y = np.column_stack([(d["ftr"] == "H"), (d["ftr"] == "D"), (d["ftr"] == "A")]).astype(float)
    p = d[["p_home", "p_draw", "p_away"]].to_numpy(dtype=float)
    res = pd.DataFrame(y - p, columns=["r_home", "r_draw", "r_away"], index=d.index)
    res[["hb", "ab"]] = d[["hb", "ab"]]
    g = res.dropna(subset=["hb", "ab"]).groupby(["hb", "ab"], observed=True)
    out = g[["r_home", "r_draw", "r_away"]].mean()
    out["n"] = g.size()
    for c in ("r_home", "r_draw", "r_away"):          # shrink towards "no residual"
        out[c] = out[c] * out["n"] / (out["n"] + SHRINK_N)
    return out.reset_index()


def apply_pattern_residuals(test: pd.DataFrame, residuals: pd.DataFrame, market: np.ndarray) -> np.ndarray:
    key = pd.DataFrame({"hb": _pts_bucket(test["h_pts5"]), "ab": _pts_bucket(test["a_pts5"])})
    merged = key.merge(residuals, on=["hb", "ab"], how="left")
    adj = market + merged[["r_home", "r_draw", "r_away"]].fillna(0.0).to_numpy(dtype=float)
    return _norm(adj)


def _norm(p: np.ndarray) -> np.ndarray:
    p = np.clip(p, 1e-4, 1.0)
    return p / p.sum(axis=1, keepdims=True)


def twin_probabilities(index: twins.TwinIndex, test: pd.DataFrame, market: np.ndarray, k: int = K_TWINS,
                       prior: float = PRIOR_TWINS, log_every: int = 500) -> tuple[np.ndarray, np.ndarray]:
    """What the twins did, shrunk towards the market. Returns (hist, adjusted)."""
    hist = np.zeros((len(test), 3))
    n_eff = np.zeros(len(test))
    for i, (_, row) in enumerate(test.iterrows()):
        if log_every and i and i % log_every == 0:
            log.info("twins %d / %d", i, len(test))
        res = index.query(row, k=k, as_of=row["date"])
        ftr = res.rows["ftr"].astype(str).to_numpy()
        if not len(ftr):
            hist[i], n_eff[i] = market[i], 0.0
            continue
        hist[i] = [(ftr == "H").mean(), (ftr == "D").mean(), (ftr == "A").mean()]
        n_eff[i] = len(ftr)
    adj = (n_eff[:, None] * hist + prior * market) / (n_eff[:, None] + prior)
    return hist, _norm(adj)


def _calibration_error(p_home: np.ndarray, hit: np.ndarray, bins: int = 10) -> float:
    """Mean absolute gap between the predicted home probability and how often it happened."""
    idx = np.clip((p_home * bins).astype(int), 0, bins - 1)
    err, tot = 0.0, 0
    for b in range(bins):
        m = idx == b
        if m.sum() >= 30:
            err += abs(p_home[m].mean() - hit[m].mean()) * m.sum()
            tot += int(m.sum())
    return float(err / tot) if tot else float("nan")


def _roi(probs: np.ndarray, test: pd.DataFrame) -> dict:
    """One unit on the model's own pick at the consensus price, and its closing-line value."""
    pick = probs.argmax(axis=1)
    odds = test[["cons_h", "cons_d", "cons_a"]].to_numpy(dtype=float)[np.arange(len(test)), pick]
    won = test["result_code"].to_numpy(dtype=int) == pick
    ok = np.isfinite(odds)
    pnl = np.where(won[ok], odds[ok] - 1.0, -1.0)
    out = {"n_bets": int(ok.sum()), "roi": round(100 * float(pnl.mean()), 2) if ok.any() else None,
           "hit_rate": round(100 * float(won[ok].mean()), 1) if ok.any() else None, "clv": None, "n_clv": 0}
    close_cols = [c for c in ("avgc_h", "avgc_d", "avgc_a") if c in test.columns]
    if len(close_cols) == 3:
        closing = test[close_cols].to_numpy(dtype=float)[np.arange(len(test)), pick]
        both = ok & np.isfinite(closing) & (closing > 1.0)
        if both.any():
            out["clv"] = round(100 * float(np.mean(odds[both] / closing[both] - 1.0)), 2)
            out["n_clv"] = int(both.sum())
    return out


def score(name: str, probs: np.ndarray, test: pd.DataFrame, base: np.ndarray | None) -> dict:
    y = test["result_code"].to_numpy(dtype=int)
    b, ll = brier_per_match(probs, y), logloss_per_match(probs, y)
    row = {"model": name, "n": int(len(y)), "brier": round(float(b.mean()), 5), "logloss": round(float(ll.mean()), 5),
           "calib_err": round(_calibration_error(probs[:, 0], (y == 0).astype(float)), 4), **_roi(probs, test)}
    if base is not None:
        d = paired_difference(b, brier_per_match(base, y))
        row["brier_diff"] = round(d["mean_diff"], 5)          # negative = better than the market
        row["p_value"] = round(d["p_value"], 4)
    return row


def run(settings: Settings, frame: pd.DataFrame, test_seasons: list[str] | None = None, sample: int = 1000,
        seed: int = 7, k_twins: int = K_TWINS) -> pd.DataFrame:
    """Walk-forward comparison of the five models. `frame` is `engine.prepare(state, matches)`."""
    from ..features.vectors import feature_mask

    pool = frame[frame["result_code"].notna() if "result_code" in frame else frame["ftr"].notna()].copy()
    if "result_code" not in pool:
        pool["result_code"] = pool["ftr"].map({"H": 0, "D": 1, "A": 2})
    seasons = test_seasons or sorted(pool["season"].dropna().unique())[-5:]
    usable = feature_mask(pool, FEATURE_SET) & pool["h_pts5"].notna() & pool["a_pts5"].notna()
    rng = np.random.default_rng(seed)
    rows: list[dict] = []
    started = dt.datetime.now()
    for season in seasons:
        mask = usable & (pool["season"] == season)
        cand = pool.loc[mask]
        if cand.empty:
            continue
        take = cand.sample(n=min(sample, len(cand)), random_state=int(rng.integers(1e6))).sort_values(["date", "match_id"])
        train = pool[pool["date"] < take["date"].min()]
        log.info("season %s: %d test matches, %d in the training window", season, len(take), len(train))
        market = take[["p_home", "p_draw", "p_away"]].to_numpy(dtype=float)

        index = SimilarityIndex(pool, FEATURE_SET)                     # look-ahead is handled by as_of
        nm = compute_neighbours(index, take, k_max=K_B, metric=METRIC, scope="global")
        _, adj_b, _ = predict_from_neighbours(nm, market, K_B, None, PRIOR)

        probs_c = apply_pattern_residuals(take, fit_pattern_residuals(train), market)
        _, adj_d = twin_probabilities(twins.TwinIndex(pool), take, market, k=k_twins)
        probs_e = _norm(market + (probs_c - market) + (adj_d - market))

        for name, probs in (("A piyasa", market), ("B benzerlik", adj_b), ("C pattern", probs_c),
                            ("D ikiz", adj_d), ("E hepsi", probs_e)):
            rows.append({"season": season, **score(name, probs, take, None if name.startswith("A") else market)})
    log.info("model comparison finished in %.0f s", (dt.datetime.now() - started).total_seconds())
    return pd.DataFrame(rows)


def summarise(per_season: pd.DataFrame) -> pd.DataFrame:
    """Pool the seasons: one row per model, weighted by how many matches each season contributed."""
    out = []
    for name, g in per_season.groupby("model", sort=False):
        n = g["n"].sum()
        w = g["n"] / n
        out.append({"model": name, "n": int(n), "brier": round(float((g["brier"] * w).sum()), 5),
                    "logloss": round(float((g["logloss"] * w).sum()), 5),
                    "calib_err": round(float((g["calib_err"] * w).sum()), 4),
                    "brier_diff": round(float((g["brier_diff"] * w).sum()), 5) if g["brier_diff"].notna().any() else None,
                    "roi": round(float((g["roi"] * w).sum()), 2), "hit_rate": round(float((g["hit_rate"] * w).sum()), 1),
                    "clv": round(float((g["clv"] * w).sum()), 2) if g["clv"].notna().any() else None,
                    "seasons_better": int((g["brier_diff"] < 0).sum()) if g["brier_diff"].notna().any() else None})
    return pd.DataFrame(out)
