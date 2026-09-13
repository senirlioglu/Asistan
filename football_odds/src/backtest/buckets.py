"""Market calibration analyses that do not need a similarity model.

* favourite-bucket analysis: expected vs actual rate per market-probability bucket (H / D / A)
* league calibration: the same table per league
* time stability: per period (2012-2015, 2016-2019, ...)
* league grouping: data-driven "similar leagues" via hierarchical clustering of league profiles
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.cluster.hierarchy import fcluster, linkage

from ..models.stats import wilson_interval

OUTCOME_COLS = {"H": ("p_home", 0), "D": ("p_draw", 1), "A": ("p_away", 2)}


def bucket_table(df: pd.DataFrame, edges: list[float], group_col: str | None = None) -> pd.DataFrame:
    """Expected (market) vs actual rate per probability bucket, per outcome, optionally per group."""
    rows = []
    res = df["result_code"].to_numpy(dtype=int)
    groups = df[group_col].to_numpy() if group_col else np.array(["all"] * len(df))
    for lab, (col, code) in OUTCOME_COLS.items():
        p = df[col].to_numpy(dtype=float)
        bins = np.digitize(p, edges) - 1
        for g in np.unique(groups):
            gm = groups == g
            for b in range(len(edges) - 1):
                m = gm & (bins == b)
                n = int(m.sum())
                if n == 0:
                    continue
                actual = float((res[m] == code).mean())
                expected = float(p[m].mean())
                lo, hi = wilson_interval(actual, n)
                rows.append({"group": g, "outcome": lab, "bucket": f"{edges[b]:.2f}-{min(edges[b + 1], 1.0):.2f}",
                             "n": n, "expected_pct": 100 * expected, "actual_pct": 100 * actual,
                             "diff_pp": 100 * (actual - expected), "ci_lo_pct": 100 * lo, "ci_hi_pct": 100 * hi,
                             "significant": bool(expected < lo or expected > hi)})
    out = pd.DataFrame(rows)
    if group_col is None and not out.empty:
        out = out.drop(columns=["group"])
    return out


def favourite_bucket_analysis(df: pd.DataFrame, edges: list[float]) -> pd.DataFrame:
    d = df[df["has_1x2"] & df["result_code"].notna()]
    return bucket_table(d, edges)


def league_calibration(df: pd.DataFrame, edges: list[float]) -> pd.DataFrame:
    d = df[df["has_1x2"] & df["result_code"].notna()]
    return bucket_table(d, edges, group_col="league")


def time_stability(df: pd.DataFrame, edges: list[float], periods: dict[str, list[str]]) -> pd.DataFrame:
    d = df[df["has_1x2"] & df["result_code"].notna()].copy()
    period_of = {s: name for name, seasons in periods.items() for s in seasons}
    d["period"] = d["season"].map(period_of)
    d = d[d["period"].notna()]
    return bucket_table(d, edges, group_col="period")


def league_profiles(df: pd.DataFrame) -> pd.DataFrame:
    d = df[df["has_1x2"] & df["result_code"].notna()]
    res = d["result_code"].to_numpy(dtype=int)
    prof = d.assign(home_win=(res == 0), draw=(res == 1)).groupby("league").agg(
        n=("match_id", "size"), p_home_mean=("p_home", "mean"), p_draw_mean=("p_draw", "mean"),
        home_rate=("home_win", "mean"), draw_rate=("draw", "mean"), avg_goals=("total_goals", "mean"),
        overround=("overround_1x2", "mean"), n_books=("n_books_used", "mean"))
    prof["home_bias_pp"] = 100 * (prof["home_rate"] - prof["p_home_mean"])
    prof["draw_bias_pp"] = 100 * (prof["draw_rate"] - prof["p_draw_mean"])
    return prof.reset_index()


def cluster_leagues(profiles: pd.DataFrame, n_groups: int = 3, min_matches: int = 2000) -> dict[str, list[str]]:
    """Group leagues by market behaviour (favourite strength, biases, goals, margin).

    Returns {league: [leagues in the same group]}; empty when there is not enough data.
    Groups are only kept when every group has at least two leagues — otherwise the feature is
    disabled rather than forced.
    """
    prof = profiles[profiles["n"] >= min_matches]
    if len(prof) < 4:
        return {}
    feats = prof[["p_home_mean", "home_bias_pp", "draw_bias_pp", "avg_goals", "overround"]].to_numpy(dtype=float)
    z = (feats - feats.mean(axis=0)) / (feats.std(axis=0) + 1e-9)
    labels = fcluster(linkage(z, method="ward"), t=n_groups, criterion="maxclust")
    groups: dict[int, list[str]] = {}
    for lg, lab in zip(prof["league"], labels):
        groups.setdefault(int(lab), []).append(str(lg))
    if any(len(v) < 2 for v in groups.values()):
        return {}
    return {lg: members for members in groups.values() for lg in members}


def write_league_groups(groups: dict[str, list[str]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(groups, indent=2))


def load_league_groups(path: Path) -> dict[str, list[str]]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError:
        return {}
