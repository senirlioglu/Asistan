"""Probabilistic scoring: Brier score, log loss, calibration, paired significance."""

from __future__ import annotations

import numpy as np
import pandas as pd
from scipy import stats as sps

EPS = 1e-6


def one_hot(result_code: np.ndarray, n_classes: int = 3) -> np.ndarray:
    y = np.asarray(result_code, dtype=int)
    out = np.zeros((len(y), n_classes))
    out[np.arange(len(y)), y] = 1.0
    return out


def brier_per_match(probs: np.ndarray, result_code: np.ndarray) -> np.ndarray:
    """Multiclass Brier: sum_c (p_c - y_c)^2 per match (0 = perfect, 2 = worst)."""
    y = one_hot(result_code, probs.shape[1])
    return np.sum((probs - y) ** 2, axis=1)


def logloss_per_match(probs: np.ndarray, result_code: np.ndarray) -> np.ndarray:
    p = np.clip(probs[np.arange(len(result_code)), np.asarray(result_code, dtype=int)], EPS, 1.0)
    return -np.log(p)


def brier(probs: np.ndarray, result_code: np.ndarray) -> float:
    return float(np.mean(brier_per_match(probs, result_code)))


def logloss(probs: np.ndarray, result_code: np.ndarray) -> float:
    return float(np.mean(logloss_per_match(probs, result_code)))


def paired_difference(loss_a: np.ndarray, loss_b: np.ndarray) -> dict[str, float]:
    """Paired test of mean(loss_a - loss_b). Negative mean => A is better."""
    d = np.asarray(loss_a) - np.asarray(loss_b)
    n = len(d)
    if n < 2:
        return {"mean_diff": float("nan"), "se": float("nan"), "z": float("nan"), "p_value": float("nan"), "n": n}
    mean = float(d.mean())
    se = float(d.std(ddof=1) / np.sqrt(n))
    z = mean / se if se > 0 else float("nan")
    p = float(2 * (1 - sps.norm.cdf(abs(z)))) if np.isfinite(z) else float("nan")
    return {"mean_diff": mean, "se": se, "z": float(z), "p_value": p, "n": int(n)}


def score_table(prob_sets: dict[str, np.ndarray], result_code: np.ndarray, baseline: str = "market") -> pd.DataFrame:
    """Brier / log loss for several probability sets plus paired comparison against a baseline."""
    rows = []
    base_b = brier_per_match(prob_sets[baseline], result_code)
    base_l = logloss_per_match(prob_sets[baseline], result_code)
    for name, probs in prob_sets.items():
        b = brier_per_match(probs, result_code)
        ll = logloss_per_match(probs, result_code)
        pb = paired_difference(b, base_b)
        pl = paired_difference(ll, base_l)
        rows.append({
            "model": name, "n": len(result_code), "brier": float(b.mean()), "logloss": float(ll.mean()),
            "brier_vs_baseline": pb["mean_diff"], "brier_p_value": pb["p_value"],
            "logloss_vs_baseline": pl["mean_diff"], "logloss_p_value": pl["p_value"],
            "brier_skill_pct": float(100 * (1 - b.mean() / base_b.mean())) if base_b.mean() > 0 else float("nan"),
        })
    return pd.DataFrame(rows)


def calibration_table(probs: np.ndarray, result_code: np.ndarray, n_bins: int = 10, labels=("H", "D", "A")) -> pd.DataFrame:
    """Per-outcome reliability table: predicted vs realised rate per probability bin."""
    y = one_hot(result_code, probs.shape[1])
    edges = np.linspace(0, 1, n_bins + 1)
    rows = []
    for c, lab in enumerate(labels):
        p = probs[:, c]
        bins = np.clip(np.digitize(p, edges) - 1, 0, n_bins - 1)
        for b in range(n_bins):
            m = bins == b
            if m.sum() == 0:
                continue
            rows.append({"outcome": lab, "bin_lo": edges[b], "bin_hi": edges[b + 1], "n": int(m.sum()),
                         "predicted": float(p[m].mean()), "actual": float(y[m, c].mean()),
                         "gap_pp": float(100 * (y[m, c].mean() - p[m].mean()))})
    return pd.DataFrame(rows)


def expected_calibration_error(probs: np.ndarray, result_code: np.ndarray, n_bins: int = 10) -> float:
    tab = calibration_table(probs, result_code, n_bins)
    if tab.empty:
        return float("nan")
    w = tab["n"] / tab["n"].sum()
    return float(np.sum(w * np.abs(tab["actual"] - tab["predicted"])))
