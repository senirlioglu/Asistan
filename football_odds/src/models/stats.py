"""Outcome statistics over a set of historical analogues.

Everything here works with optional per-match weights (time decay). Rates are weighted means,
intervals use the effective sample size, and shrinkage is empirical-Bayes toward the market.

Shrinkage (adjusted probability)::

    adj_i = (n_eff * hist_i + m * market_i) / (n_eff + m)

``m`` is a pseudo-count ("prior strength"): with m=50, a set of 18 analogues moves only
18/68 = 26 % of the way from the market probability to the raw historical rate.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd
from scipy import stats as sps

from .time_weights import effective_n

OUTCOMES = ("home", "draw", "away")
SCORELINES = [(0, 0), (1, 0), (0, 1), (1, 1), (2, 0), (0, 2), (2, 1), (1, 2), (2, 2), (3, 0), (0, 3), (3, 1), (1, 3), (3, 2), (2, 3), (3, 3)]


def wilson_interval(p: float, n: float, z: float = 1.96) -> tuple[float, float]:
    """Wilson score interval for a proportion p observed on n (possibly effective) trials."""
    if n <= 0 or not np.isfinite(p):
        return (float("nan"), float("nan"))
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * np.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return (max(0.0, centre - half), min(1.0, centre + half))


def shrink(hist: np.ndarray, n_eff: float, market: np.ndarray, prior_strength: float) -> np.ndarray:
    hist = np.asarray(hist, dtype=float)
    market = np.asarray(market, dtype=float)
    if n_eff <= 0:
        return market.copy()
    adj = (n_eff * hist + prior_strength * market) / (n_eff + prior_strength)
    s = adj.sum()
    return adj / s if s > 0 else adj


def confidence_label(n_eff: float, thresholds: dict | None = None) -> str:
    t = thresholds or {"very_low_below": 30, "low_below": 100, "medium_below": 250}
    if n_eff < t["very_low_below"]:
        return "VERY LOW"
    if n_eff < t["low_below"]:
        return "LOW"
    if n_eff < t["medium_below"]:
        return "MEDIUM"
    return "HIGH"


def weighted_rate(mask: np.ndarray, weights: np.ndarray) -> float:
    w = weights.sum()
    return float(np.sum(weights * mask) / w) if w > 0 else float("nan")


def weighted_median(values: np.ndarray, weights: np.ndarray) -> float:
    if len(values) == 0:
        return float("nan")
    order = np.argsort(values)
    v, w = values[order], weights[order]
    cum = np.cumsum(w)
    return float(v[np.searchsorted(cum, 0.5 * cum[-1])])


@dataclass
class OutcomeStats:
    n: int
    n_eff: float
    home: float
    draw: float
    away: float
    ci_home: tuple[float, float]
    ci_draw: tuple[float, float]
    ci_away: tuple[float, float]
    over25: float
    under25: float
    btts_yes: float
    btts_no: float
    avg_goals: float
    median_goals: float
    home_goals_avg: float
    away_goals_avg: float
    scorelines: dict[str, float] = field(default_factory=dict)
    goals_dist: dict[str, float] = field(default_factory=dict)
    # half-time layer (rows without a half-time result are excluded from these rates)
    ht_home: float = float("nan")
    ht_draw: float = float("nan")
    ht_away: float = float("nan")
    htft: dict[str, float] = field(default_factory=dict)   # "1/1", "X/2", ... -> share
    n_ht: int = 0

    def probs(self) -> np.ndarray:
        return np.array([self.home, self.draw, self.away])


HTFT_ORDER = ["1/1", "1/X", "1/2", "X/1", "X/X", "X/2", "2/1", "2/X", "2/2"]
_RES_SYMBOL = {"H": "1", "D": "X", "A": "2"}


def htft_label(htr: str | None, ftr: str | None) -> str:
    """'H','A' -> '1/2'; empty when the half-time result is unknown."""
    if htr not in _RES_SYMBOL or ftr not in _RES_SYMBOL:
        return ""
    return f"{_RES_SYMBOL[htr]}/{_RES_SYMBOL[ftr]}"


def outcome_stats(neigh: pd.DataFrame, weights: np.ndarray | None = None) -> OutcomeStats:
    """Weighted realised-outcome statistics for a set of analogue matches."""
    n = len(neigh)
    w = np.ones(n) if weights is None else np.asarray(weights, dtype=float)
    if n == 0:
        nan = float("nan")
        return OutcomeStats(0, 0.0, nan, nan, nan, (nan, nan), (nan, nan), (nan, nan), nan, nan, nan, nan, nan, nan, nan, nan)
    res = neigh["result_code"].to_numpy(dtype=float)
    fthg = neigh["fthg"].to_numpy(dtype=float)
    ftag = neigh["ftag"].to_numpy(dtype=float)
    total = fthg + ftag
    n_eff = effective_n(w)
    home, draw, away = (weighted_rate(res == code, w) for code in (0, 1, 2))
    over = weighted_rate(total > 2.5, w)
    btts = weighted_rate((fthg > 0) & (ftag > 0), w)
    sl = {f"{h}-{a}": weighted_rate((fthg == h) & (ftag == a), w) for h, a in SCORELINES}
    sl["other"] = max(0.0, 1.0 - sum(sl.values()))
    gd = {str(g): weighted_rate(total == g, w) for g in range(5)}
    gd["5+"] = weighted_rate(total >= 5, w)

    # half-time layer
    ht_home = ht_draw = ht_away = float("nan")
    htft: dict[str, float] = {}
    n_ht = 0
    if "htr" in neigh.columns:
        htr = neigh["htr"].astype("string").fillna("").to_numpy()
        ftr = neigh["ftr"].astype("string").fillna("").to_numpy()
        has = np.isin(htr, ["H", "D", "A"]) & np.isin(ftr, ["H", "D", "A"])
        n_ht = int(has.sum())
        if n_ht:
            w_ht = np.where(has, w, 0.0)
            ht_home, ht_draw, ht_away = (weighted_rate(htr == c, w_ht) for c in ("H", "D", "A"))
            labels = np.array([htft_label(a, b) for a, b in zip(htr, ftr)])
            htft = {k: weighted_rate(labels == k, w_ht) for k in HTFT_ORDER}

    return OutcomeStats(
        n=n, n_eff=n_eff, home=home, draw=draw, away=away,
        ci_home=wilson_interval(home, n_eff), ci_draw=wilson_interval(draw, n_eff), ci_away=wilson_interval(away, n_eff),
        over25=over, under25=1 - over, btts_yes=btts, btts_no=1 - btts,
        avg_goals=float(np.sum(w * total) / w.sum()), median_goals=weighted_median(total, w),
        home_goals_avg=float(np.sum(w * fthg) / w.sum()), away_goals_avg=float(np.sum(w * ftag) / w.sum()),
        scorelines=sl, goals_dist=gd, ht_home=ht_home, ht_draw=ht_draw, ht_away=ht_away, htft=htft, n_ht=n_ht,
    )


def fair_odds(prob: float) -> float:
    return float(1.0 / prob) if prob and prob > 0 else float("nan")


def market_outside_ci(market_p: float, ci: tuple[float, float]) -> bool:
    lo, hi = ci
    if not (np.isfinite(lo) and np.isfinite(hi)):
        return False
    return bool(market_p < lo or market_p > hi)


def two_proportion_z(p_hist: float, n_eff: float, p_market: float) -> float:
    """z-statistic of the historical rate against the market probability (one-sample test)."""
    if n_eff <= 0 or not (0 < p_market < 1):
        return float("nan")
    se = np.sqrt(p_market * (1 - p_market) / n_eff)
    return float((p_hist - p_market) / se) if se > 0 else float("nan")


def p_value_from_z(z: float) -> float:
    if not np.isfinite(z):
        return float("nan")
    return float(2 * (1 - sps.norm.cdf(abs(z))))
