"""Feature vectors for the similarity search and the Similarity % definition.

Feature sets
------------
* ``1x2``    : [p_home, p_draw, p_away]                       (margin-free consensus probabilities)
* ``1x2_ou`` : [p_home, p_draw, p_away, p_over25, p_under25]

Only pre-kick-off information is allowed here (see ``schema.POST_MATCH_COLUMNS``).

Similarity %
------------
Independently of the metric used for *ranking* neighbours, the reported similarity is::

    TV_market = 0.5 * sum_i |p_i - q_i|          (total variation distance, in [0, 1])
    TV        = mean over the markets in the feature set
    Similarity % = 100 * (1 - TV)

So 98 % similarity means the two probability profiles differ by 2 percentage points of total
variation (e.g. home 55 % vs 57 % and away 20 % vs 18 %). It is metric-independent,
bounded, and directly readable as "percentage points of probability mass that differ".
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from ..data.schema import POST_MATCH_COLUMNS

FEATURE_SETS: dict[str, list[str]] = {
    "1x2": ["p_home", "p_draw", "p_away"],
    "1x2_ou": ["p_home", "p_draw", "p_away", "p_over25", "p_under25"],
}

# how the columns of each feature set group into markets (for the TV average)
MARKET_SLICES: dict[str, list[slice]] = {
    "1x2": [slice(0, 3)],
    "1x2_ou": [slice(0, 3), slice(3, 5)],
}


def feature_columns(feature_set: str) -> list[str]:
    try:
        cols = FEATURE_SETS[feature_set]
    except KeyError as exc:
        raise ValueError(f"unknown feature set {feature_set!r}; expected one of {list(FEATURE_SETS)}") from exc
    leaked = set(cols) & POST_MATCH_COLUMNS
    if leaked:  # pragma: no cover - guards future edits
        raise RuntimeError(f"post-match columns in feature set: {leaked}")
    return cols


def feature_matrix(df: pd.DataFrame, feature_set: str) -> np.ndarray:
    return df[feature_columns(feature_set)].to_numpy(dtype=float)


def feature_mask(df: pd.DataFrame, feature_set: str) -> np.ndarray:
    """True for rows where every feature of the set is available."""
    return np.all(np.isfinite(feature_matrix(df, feature_set)), axis=1)


def total_variation(query: np.ndarray, pool: np.ndarray, feature_set: str) -> np.ndarray:
    """Average total-variation distance between one query vector and each pool row."""
    query = np.asarray(query, dtype=float).reshape(1, -1)
    pool = np.asarray(pool, dtype=float)
    if pool.ndim == 1:
        pool = pool[None, :]
    tvs = [0.5 * np.abs(pool[:, s] - query[:, s]).sum(axis=1) for s in MARKET_SLICES[feature_set]]
    return np.mean(tvs, axis=0)


def similarity_pct(query: np.ndarray, pool: np.ndarray, feature_set: str) -> np.ndarray:
    return 100.0 * (1.0 - total_variation(query, pool, feature_set))


def similarity_to_tv(similarity_pct_value: float) -> float:
    """Inverse of similarity_pct for a single value (e.g. 98 -> 0.02)."""
    return 1.0 - similarity_pct_value / 100.0
