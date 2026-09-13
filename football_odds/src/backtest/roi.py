"""Flat-stake betting simulation on out-of-sample test matches.

Prediction accuracy and profitability are different questions; this module answers the second
one *only* with odds that were available before kick-off (the consensus average that produced
the feature vector, and the market maximum as an optimistic bound). Stake = 1 unit per bet,
no Kelly, no compounding.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

OUTCOME_ODDS = {0: "cons_h", 1: "cons_d", 2: "cons_a"}
OUTCOME_MAX = {0: "max_h", 1: "max_d", 2: "max_a"}


def max_drawdown(profits: np.ndarray) -> float:
    if len(profits) == 0:
        return 0.0
    cum = np.cumsum(profits)
    peak = np.maximum.accumulate(np.concatenate([[0.0], cum]))[1:]
    return float(np.max(peak - cum))


def simulate(test_df: pd.DataFrame, adj: np.ndarray, market: np.ndarray, threshold_pp: float,
             price: str = "avg") -> dict:
    """Bet every outcome whose adjusted probability exceeds the market by >= threshold_pp."""
    edge = (adj - market) * 100
    res = test_df["result_code"].to_numpy(dtype=int)
    order = np.argsort(test_df["date"].to_numpy(), kind="stable")
    bets = []
    for i in order:
        for c in range(3):
            if edge[i, c] >= threshold_pp:
                col = OUTCOME_ODDS[c] if price == "avg" else OUTCOME_MAX[c]
                odds = test_df[col].iloc[i]
                if not np.isfinite(odds) or odds <= 1.0:
                    odds = test_df[OUTCOME_ODDS[c]].iloc[i]
                if not np.isfinite(odds) or odds <= 1.0:
                    continue
                won = res[i] == c
                bets.append((test_df["season"].iloc[i], odds, won, odds - 1.0 if won else -1.0))
    n = len(bets)
    if n == 0:
        return {"threshold_pp": threshold_pp, "price": price, "n_bets": 0, "wins": 0, "losses": 0, "win_rate": np.nan,
                "avg_odds": np.nan, "total_stake": 0.0, "total_return": 0.0, "profit": 0.0, "roi_pct": np.nan,
                "max_drawdown": 0.0, "by_season": {}}
    arr = pd.DataFrame(bets, columns=["season", "odds", "won", "profit"])
    by_season = arr.groupby("season")["profit"].agg(["size", "sum"])
    by_season["roi_pct"] = 100 * by_season["sum"] / by_season["size"]
    return {
        "threshold_pp": threshold_pp, "price": price, "n_bets": n, "wins": int(arr["won"].sum()),
        "losses": int((~arr["won"]).sum()), "win_rate": float(arr["won"].mean()), "avg_odds": float(arr["odds"].mean()),
        "total_stake": float(n), "total_return": float(n + arr["profit"].sum()), "profit": float(arr["profit"].sum()),
        "roi_pct": float(100 * arr["profit"].sum() / n), "max_drawdown": max_drawdown(arr["profit"].to_numpy()),
        "by_season": {str(s): {"bets": int(r["size"]), "profit": float(r["sum"]), "roi_pct": float(r["roi_pct"])}
                      for s, r in by_season.iterrows()},
    }


def roi_table(test_df: pd.DataFrame, adj: np.ndarray, market: np.ndarray, thresholds: list[float]) -> pd.DataFrame:
    rows = []
    for price in ("avg", "max"):
        for t in thresholds:
            r = simulate(test_df, adj, market, t, price)
            seasons = r.pop("by_season")
            r["seasons_profitable"] = sum(1 for v in seasons.values() if v["profit"] > 0)
            r["seasons_total"] = len(seasons)
            rows.append(r)
    return pd.DataFrame(rows)
