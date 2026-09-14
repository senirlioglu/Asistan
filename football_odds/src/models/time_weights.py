"""Exponential time decay.

    weight = exp(-lambda * years_old),   lambda = ln(2) / half_life

``half_life=None`` returns uniform weights (the UNWEIGHTED variant). The effective sample
size of a weighted set is Kish's n_eff = (sum w)^2 / sum w^2, which is what the confidence
intervals and the shrinkage use instead of the raw count.
"""

from __future__ import annotations

import numpy as np


def years_between(as_of: np.datetime64 | "pd.Timestamp", dates: np.ndarray) -> np.ndarray:
    delta = (np.datetime64(as_of) - np.asarray(dates, dtype="datetime64[ns]")).astype("timedelta64[D]").astype(float)
    return delta / 365.25


def time_weights(years_old: np.ndarray, half_life: float | None) -> np.ndarray:
    years_old = np.asarray(years_old, dtype=float)
    if half_life is None or half_life <= 0:
        return np.ones_like(years_old)
    lam = np.log(2.0) / half_life
    return np.exp(-lam * np.clip(years_old, 0.0, None))


def effective_n(weights: np.ndarray) -> float:
    w = np.asarray(weights, dtype=float)
    s = w.sum()
    if s <= 0:
        return 0.0
    return float(s * s / np.sum(w * w))
