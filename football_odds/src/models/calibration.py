"""Market re-calibration models (research layer).

The favourite-bucket analysis showed that the average market under-prices strong home favourites
by 3-5 pp. These models ask the only question that matters: *is that pattern exploitable
out-of-sample?* They learn a monotone mapping market probability -> realised frequency on past
seasons only and are scored on later seasons against the untouched market probabilities.

* ``IsotonicCalibrator`` — one isotonic regression per outcome (H/D/A), renormalised to sum to 1.
* ``BucketCalibrator``   — piecewise-constant: realised rate per 5 pp bucket (the table itself).

Both are transparent, have essentially no capacity to overfit beyond the bucket structure, and
carry no post-match information: the only input is the margin-free market probability.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.isotonic import IsotonicRegression

MARKET_COLS = ["p_home", "p_draw", "p_away"]


class IsotonicCalibrator:
    def __init__(self, min_train: int = 2000):
        self.min_train = min_train
        self.models: list[IsotonicRegression] = []

    def fit(self, market: np.ndarray, result_code: np.ndarray) -> "IsotonicCalibrator":
        if len(market) < self.min_train:
            raise ValueError(f"need at least {self.min_train} training matches, got {len(market)}")
        self.models = []
        for c in range(3):
            iso = IsotonicRegression(y_min=0.0, y_max=1.0, out_of_bounds="clip", increasing=True)
            iso.fit(market[:, c], (result_code == c).astype(float))
            self.models.append(iso)
        return self

    def predict(self, market: np.ndarray) -> np.ndarray:
        if not self.models:
            raise RuntimeError("calibrator not fitted")
        out = np.column_stack([m.predict(market[:, c]) for c, m in enumerate(self.models)])
        out = np.clip(out, 1e-4, 1.0)
        return out / out.sum(axis=1, keepdims=True)


class BucketCalibrator:
    def __init__(self, width: float = 0.05, min_bucket: int = 200):
        self.width = width
        self.min_bucket = min_bucket
        self.tables: list[dict[int, float]] = []

    def _bucket(self, p: np.ndarray) -> np.ndarray:
        return np.floor(np.clip(p, 0, 0.9999) / self.width).astype(int)

    def fit(self, market: np.ndarray, result_code: np.ndarray) -> "BucketCalibrator":
        self.tables = []
        for c in range(3):
            b = self._bucket(market[:, c])
            y = (result_code == c).astype(float)
            table: dict[int, float] = {}
            for k in np.unique(b):
                m = b == k
                if m.sum() >= self.min_bucket:
                    # shrink the bucket rate toward the market mean of the bucket with a 200-match prior
                    n = m.sum()
                    table[int(k)] = float((n * y[m].mean() + 200 * market[m, c].mean()) / (n + 200))
            self.tables.append(table)
        return self

    def predict(self, market: np.ndarray) -> np.ndarray:
        out = market.copy()
        for c in range(3):
            b = self._bucket(market[:, c])
            table = self.tables[c]
            adj = np.array([table.get(int(k), np.nan) for k in b])
            # a bucket without enough training data keeps the market probability
            out[:, c] = np.where(np.isfinite(adj), adj, market[:, c])
        out = np.clip(out, 1e-4, 1.0)
        return out / out.sum(axis=1, keepdims=True)


CALIBRATORS = {"isotonic": IsotonicCalibrator, "bucket": BucketCalibrator}
