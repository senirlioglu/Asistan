"""Similarity engine.

Two models are provided on top of one date-sorted pool:

* **Model A — tolerance matching**: every historical match whose odds (relative) or
  probabilities (absolute pp) are within ±tol of the query on all outcomes.
* **Model B — nearest neighbours** (main model): top-K by distance (euclidean / manhattan /
  cosine / mahalanobis) with an optional adaptive Similarity % floor.

Look-ahead protection is structural: `candidates()` only ever returns pool rows whose date is
strictly **before** the query date (`as_of`), so a backtest query for a 2021 match can only see
matches played before that day — including earlier matches of the same season, never later ones.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from scipy.spatial.distance import cdist

from ..features.vectors import feature_columns, feature_mask, feature_matrix, similarity_pct

METRICS = {
    "euclidean": "euclidean",
    "manhattan": "cityblock",
    "cosine": "cosine",
    "mahalanobis": "mahalanobis",
}


@dataclass
class NeighbourResult:
    indices: np.ndarray      # positions in SimilarityIndex.df
    distances: np.ndarray
    similarity: np.ndarray   # Similarity % (metric independent)
    n_candidates: int        # size of the admissible pool before top-K


class SimilarityIndex:
    """A date-sorted pool of historical matches with pre-computed feature vectors."""

    def __init__(self, pool: pd.DataFrame, feature_set: str = "1x2"):
        self.feature_set = feature_set
        cols = feature_columns(feature_set)
        mask = feature_mask(pool, feature_set) & pool["result_code"].notna().to_numpy()
        df = pool.loc[mask].sort_values(["date", "match_id"], kind="mergesort").reset_index(drop=True)
        self.df = df
        self.X = df[cols].to_numpy(dtype=float)
        self.dates = df["date"].to_numpy(dtype="datetime64[ns]")
        self.leagues = df["league"].to_numpy()
        self._vi: np.ndarray | None = None

    # ------------------------------------------------------------------ helpers
    def __len__(self) -> int:
        return len(self.df)

    @property
    def vi(self) -> np.ndarray:
        """Pseudo-inverse covariance for Mahalanobis (the simplex makes cov singular)."""
        if self._vi is None:
            cov = np.cov(self.X, rowvar=False) if len(self.X) > 2 else np.eye(self.X.shape[1])
            self._vi = np.linalg.pinv(np.atleast_2d(cov))
        return self._vi

    def candidates(self, as_of, scope: str = "global", league: str | None = None,
                   exclude_match_ids: set[str] | None = None) -> np.ndarray:
        """Positions of admissible pool rows: date < as_of (strict), optionally same league."""
        end = int(np.searchsorted(self.dates, np.datetime64(pd.Timestamp(as_of)), side="left"))
        idx = np.arange(end)
        if scope == "same_league":
            if league is None:
                raise ValueError("scope='same_league' needs a league")
            idx = idx[self.leagues[:end] == league]
        elif scope == "league_group":
            if league is None:
                raise ValueError("scope='league_group' needs a league list in `league`")
            idx = idx[np.isin(self.leagues[:end], list(league))]
        elif scope != "global":
            raise ValueError(f"unknown scope {scope!r}")
        if exclude_match_ids:
            keep = ~self.df["match_id"].iloc[idx].isin(exclude_match_ids).to_numpy()
            idx = idx[keep]
        return idx

    def distances(self, queries: np.ndarray, idx: np.ndarray, metric: str) -> np.ndarray:
        queries = np.atleast_2d(np.asarray(queries, dtype=float))
        if len(idx) == 0:
            return np.empty((len(queries), 0))
        name = METRICS.get(metric)
        if name is None:
            raise ValueError(f"unknown metric {metric!r}; expected one of {list(METRICS)}")
        if name == "mahalanobis":
            return cdist(queries, self.X[idx], metric=name, VI=self.vi)
        return cdist(queries, self.X[idx], metric=name)

    # ------------------------------------------------------------------ Model B
    def query(self, vec: np.ndarray, as_of, k: int = 250, metric: str = "manhattan", scope: str = "global",
              league: str | None = None, min_similarity: float = 0.0,
              exclude_match_ids: set[str] | None = None) -> NeighbourResult:
        idx = self.candidates(as_of, scope, league, exclude_match_ids)
        if len(idx) == 0:
            return NeighbourResult(np.array([], dtype=int), np.array([]), np.array([]), 0)
        d = self.distances(vec, idx, metric)[0]
        sim = similarity_pct(vec, self.X[idx], self.feature_set)
        if min_similarity > 0:
            keep = sim >= min_similarity
            idx, d, sim = idx[keep], d[keep], sim[keep]
        if k and len(idx) > k:
            part = np.argpartition(d, k - 1)[:k]
            idx, d, sim = idx[part], d[part], sim[part]
        order = np.argsort(d, kind="stable")
        return NeighbourResult(idx[order], d[order], sim[order], int(len(self.candidates(as_of, scope, league))))

    def query_batch(self, vecs: np.ndarray, as_of, k: int, metric: str, scope: str = "global",
                    league: str | None = None) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """Top-K for many queries that share the same as_of/scope (backtest fast path).

        Returns (indices, distances, similarity) arrays of shape (n_queries, k); rows are padded
        with -1 / NaN when fewer than k candidates exist.
        """
        vecs = np.atleast_2d(np.asarray(vecs, dtype=float))
        idx = self.candidates(as_of, scope, league)
        nq = len(vecs)
        out_idx = np.full((nq, k), -1, dtype=int)
        out_d = np.full((nq, k), np.nan)
        out_s = np.full((nq, k), np.nan)
        if len(idx) == 0:
            return out_idx, out_d, out_s
        d = self.distances(vecs, idx, metric)
        kk = min(k, len(idx))
        part = np.argpartition(d, kk - 1, axis=1)[:, :kk] if len(idx) > kk else np.tile(np.arange(kk), (nq, 1))
        rows = np.arange(nq)[:, None]
        dpart = d[rows, part]
        order = np.argsort(dpart, axis=1, kind="stable")
        part = part[rows, order]
        out_idx[:, :kk] = idx[part]
        out_d[:, :kk] = d[rows, part]
        for i in range(nq):
            out_s[i, :kk] = similarity_pct(vecs[i], self.X[out_idx[i, :kk]], self.feature_set)
        return out_idx, out_d, out_s

    # ------------------------------------------------------------------ Model A
    def tolerance_match(self, query_odds: np.ndarray | None, query_probs: np.ndarray, as_of, levels: list[float],
                        scope: str = "global", league: str | None = None) -> dict[str, dict[float, np.ndarray]]:
        """Matches within ±tol on every outcome.

        ``odds`` mode: |odds_hist - odds_q| / odds_q <= tol (relative, needs cons_h/d/a in the pool).
        ``probs`` mode: |p_hist - p_q| <= tol (absolute probability, i.e. tol=0.02 -> 2 pp).
        """
        idx = self.candidates(as_of, scope, league)
        result: dict[str, dict[float, np.ndarray]] = {"probs": {}, "odds": {}}
        probs = self.X[idx][:, :3]
        q = np.asarray(query_probs, dtype=float)[:3]
        for tol in levels:
            result["probs"][tol] = idx[np.all(np.abs(probs - q) <= tol, axis=1)]
        if query_odds is not None and all(c in self.df.columns for c in ("cons_h", "cons_d", "cons_a")):
            odds = self.df[["cons_h", "cons_d", "cons_a"]].to_numpy(dtype=float)[idx]
            qo = np.asarray(query_odds, dtype=float)
            with np.errstate(invalid="ignore"):
                rel = np.abs(odds - qo) / qo
            for tol in levels:
                result["odds"][tol] = idx[np.all(rel <= tol, axis=1)]
        return result
