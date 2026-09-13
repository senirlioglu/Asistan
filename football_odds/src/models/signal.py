"""Transparent model signal.

The signal is a rule set, not a score. Every rule is reported in ``reasons`` so a user can see
exactly why a match was classified the way it was.

Inputs per match:
    edge_pp       : adjusted historical probability - market probability, per outcome (pp)
    n_eff         : effective sample size of the analogue set
    outside_ci    : is the market probability outside the 95 % Wilson interval of the raw rate?
    avg_similarity: mean Similarity % of the analogue set
    backtest_ok   : did the walk-forward backtest show the adjusted model beating the market
                    baseline out-of-sample at p < 0.05? (results/backtest/selected_params.json;
                    "not worse but indistinguishable" counts as False)

Rules (evaluated in order):
    LOW SAMPLE                    n_eff < low_below (default 100)
    STRONG HISTORICAL DEVIATION   |edge| >= strong_edge_pp AND outside CI AND avg_sim >= strong sim
                                  AND backtest_ok
    MODERATE HISTORICAL DEVIATION |edge| >= moderate_edge_pp AND outside CI AND avg_sim >= moderate sim
                                  (or a STRONG candidate that failed backtest_ok / similarity)
    NEUTRAL                       otherwise
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

OUTCOME_NAMES = {"home": "HOME", "draw": "DRAW", "away": "AWAY"}


@dataclass
class Signal:
    label: str
    outcome: str | None
    edge_pp: float
    reasons: list[str]

    def as_text(self) -> str:
        return "; ".join(self.reasons)


def classify_signal(edges_pp: dict[str, float], n_eff: float, outside_ci: dict[str, bool], avg_similarity: float,
                    backtest_ok: bool, cfg: dict | None = None, conf_cfg: dict | None = None) -> Signal:
    cfg = cfg or {}
    conf_cfg = conf_cfg or {}
    strong_edge = float(cfg.get("strong_edge_pp", 5.0))
    moderate_edge = float(cfg.get("moderate_edge_pp", 3.0))
    sim_strong = float(cfg.get("min_avg_similarity_strong", 95.0))
    sim_moderate = float(cfg.get("min_avg_similarity_moderate", 90.0))
    low_below = float(conf_cfg.get("low_below", 100))

    reasons: list[str] = []
    finite = {k: v for k, v in edges_pp.items() if np.isfinite(v)}
    if not finite or n_eff <= 0:
        return Signal("LOW SAMPLE", None, float("nan"), ["no analogues"])
    outcome = max(finite, key=lambda k: abs(finite[k]))
    edge = finite[outcome]
    reasons.append(f"largest deviation {OUTCOME_NAMES[outcome]} {edge:+.1f} pp")
    reasons.append(f"n_eff={n_eff:.0f}")

    if n_eff < low_below:
        reasons.append(f"n_eff below {low_below:.0f} -> LOW SAMPLE")
        return Signal("LOW SAMPLE", outcome, edge, reasons)

    ci_flag = bool(outside_ci.get(outcome, False))
    reasons.append("market outside 95% CI" if ci_flag else "market inside 95% CI")
    reasons.append(f"avg similarity {avg_similarity:.1f}%")
    reasons.append("backtest: adjusted model beat market (p<0.05)" if backtest_ok
                   else "backtest: no significant improvement over market")

    strong_candidate = abs(edge) >= strong_edge and ci_flag and avg_similarity >= sim_moderate
    if strong_candidate and avg_similarity >= sim_strong and backtest_ok:
        return Signal("STRONG HISTORICAL DEVIATION", outcome, edge, reasons)
    if strong_candidate:
        reasons.append("downgraded to MODERATE (backtest or similarity gate)")
        return Signal("MODERATE HISTORICAL DEVIATION", outcome, edge, reasons)
    if abs(edge) >= moderate_edge and ci_flag and avg_similarity >= sim_moderate:
        return Signal("MODERATE HISTORICAL DEVIATION", outcome, edge, reasons)
    return Signal("NEUTRAL", outcome, edge, reasons)
