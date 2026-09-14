"""Odds movement research layer (seasons with closing odds, 2019/20+).

Question: among matches that reach the *same closing probability*, does the direction of the
opening -> closing move (steam vs drift) change the realised outcome distribution?

Δ = closing margin-free probability - pre-closing margin-free probability (percentage points).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from ..models.stats import wilson_interval
from .metrics import brier, logloss, paired_difference, brier_per_match

MOVE_CATEGORIES = [("drift (<= -2pp)", -np.inf, -2.0), ("stable", -2.0, 2.0), ("steam (>= +2pp)", 2.0, np.inf)]


def movement_frame(df: pd.DataFrame) -> pd.DataFrame:
    d = df[df["has_1x2"] & df["has_closing"] & df["result_code"].notna()].copy()
    for o in ("home", "draw", "away"):
        d[f"delta_pp_{o}"] = 100 * d[f"delta_p_{o}"]
    return d


def opening_vs_closing_scores(d: pd.DataFrame) -> pd.DataFrame:
    res = d["result_code"].to_numpy(dtype=int)
    open_p = d[["p_home", "p_draw", "p_away"]].to_numpy(dtype=float)
    close_p = d[["pc_home", "pc_draw", "pc_away"]].to_numpy(dtype=float)
    diff = paired_difference(brier_per_match(close_p, res), brier_per_match(open_p, res))
    return pd.DataFrame([
        {"probabilities": "pre-closing (Fri/Tue collection)", "n": len(d), "brier": brier(open_p, res), "logloss": logloss(open_p, res)},
        {"probabilities": "closing", "n": len(d), "brier": brier(close_p, res), "logloss": logloss(close_p, res),
         "brier_diff_vs_opening": diff["mean_diff"], "p_value": diff["p_value"]},
    ])


def movement_by_bucket(d: pd.DataFrame, outcome: str = "home", edges: list[float] | None = None) -> pd.DataFrame:
    """Realised rate per closing-probability bucket x movement category."""
    edges = edges or [0.20, 0.30, 0.40, 0.50, 0.60, 0.70, 0.80, 1.01]
    code = {"home": 0, "draw": 1, "away": 2}[outcome]
    pc = d[f"pc_{outcome}"].to_numpy(dtype=float)
    delta = d[f"delta_pp_{outcome}"].to_numpy(dtype=float)
    res = d["result_code"].to_numpy(dtype=int)
    bins = np.digitize(pc, edges) - 1
    rows = []
    for b in range(len(edges) - 1):
        bm = bins == b
        for name, lo, hi in MOVE_CATEGORIES:
            m = bm & (delta > lo) & (delta <= hi) if np.isfinite(lo) else bm & (delta <= hi)
            if np.isfinite(lo) and not np.isfinite(hi):
                m = bm & (delta >= lo)
            n = int(m.sum())
            if n == 0:
                continue
            actual = float((res[m] == code).mean())
            ci = wilson_interval(actual, n)
            rows.append({"outcome": outcome, "closing_bucket": f"{edges[b]:.2f}-{min(edges[b+1],1):.2f}", "movement": name,
                         "n": n, "closing_prob_pct": 100 * float(pc[m].mean()), "actual_pct": 100 * actual,
                         "diff_pp": 100 * (actual - float(pc[m].mean())), "ci_lo_pct": 100 * ci[0], "ci_hi_pct": 100 * ci[1]})
    return pd.DataFrame(rows)


def steam_vs_drift_test(table: pd.DataFrame) -> pd.DataFrame:
    """Two-proportion z-test steam vs drift inside each closing bucket."""
    rows = []
    for (outcome, bucket), g in table.groupby(["outcome", "closing_bucket"]):
        s = g[g["movement"].str.startswith("steam")]
        dr = g[g["movement"].str.startswith("drift")]
        if s.empty or dr.empty:
            continue
        p1, n1 = s["actual_pct"].iloc[0] / 100, int(s["n"].iloc[0])
        p2, n2 = dr["actual_pct"].iloc[0] / 100, int(dr["n"].iloc[0])
        pool = (p1 * n1 + p2 * n2) / (n1 + n2)
        se = np.sqrt(pool * (1 - pool) * (1 / n1 + 1 / n2)) if 0 < pool < 1 else np.nan
        z = (p1 - p2) / se if se and se > 0 else np.nan
        from scipy import stats as sps
        p = 2 * (1 - sps.norm.cdf(abs(z))) if np.isfinite(z) else np.nan
        rows.append({"outcome": outcome, "closing_bucket": bucket, "steam_n": n1, "steam_actual_pct": 100 * p1,
                     "drift_n": n2, "drift_actual_pct": 100 * p2, "diff_pp": 100 * (p1 - p2), "z": z, "p_value": p})
    return pd.DataFrame(rows)
