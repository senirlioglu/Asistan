"""Match analysis orchestration: market -> analogues -> statistics -> edges -> signal.

`analyze_match` is used unchanged by the backtest (with `as_of` = the historical match date) and
by the today pipeline (with `as_of` = today), which is what guarantees that the live system and
the backtested system are the same code path.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

import numpy as np
import pandas as pd

from ..features.vectors import feature_columns
from .signal import Signal, classify_signal
from .similarity import NeighbourResult, SimilarityIndex
from .stats import (OUTCOMES, OutcomeStats, confidence_label, fair_odds, htft_label, market_outside_ci, outcome_stats,
                    p_value_from_z, shrink, two_proportion_z)
from .time_weights import time_weights, years_between


@dataclass
class AnalysisParams:
    feature_set: str = "1x2"
    metric: str = "manhattan"
    k: int = 250
    half_life_years: float | None = 5.0
    min_similarity: float = 0.0
    scope: str = "global"
    prior_strength: float = 50.0

    @classmethod
    def from_settings(cls, settings, **overrides) -> "AnalysisParams":
        sim = settings.section("similarity")
        p = cls(
            feature_set=sim.get("feature_set", "1x2"), metric=sim.get("metric", "manhattan"), k=int(sim.get("k", 250)),
            half_life_years=sim.get("half_life_years", 5), min_similarity=float(sim.get("min_similarity", 0.0)),
            scope="global", prior_strength=float(settings.get("shrinkage.prior_strength", 50)),
        )
        for key, value in overrides.items():
            setattr(p, key, value)
        return p

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ScopeResult:
    scope: str
    stats: OutcomeStats
    adjusted: np.ndarray
    avg_similarity: float
    median_similarity: float
    min_similarity: float
    n_candidates: int


@dataclass
class MatchAnalysis:
    summary: dict[str, Any]
    analogues: pd.DataFrame
    scopes: dict[str, ScopeResult] = field(default_factory=dict)
    tolerance: dict[str, dict[float, int]] = field(default_factory=dict)
    signal: Signal | None = None


ANALOGUE_COLUMNS = ["date", "league", "season", "home_team", "away_team", "cons_h", "cons_d", "cons_a",
                    "p_home", "p_draw", "p_away", "ftr", "fthg", "ftag", "total_goals", "btts", "over25",
                    "hthg", "htag", "htr"]


def _weights(index: SimilarityIndex, res: NeighbourResult, as_of, half_life: float | None) -> np.ndarray:
    years = years_between(pd.Timestamp(as_of), index.dates[res.indices])
    return time_weights(years, half_life)


def analogue_frame(index: SimilarityIndex, res: NeighbourResult, weights: np.ndarray, as_of) -> pd.DataFrame:
    cols = [c for c in ANALOGUE_COLUMNS if c in index.df.columns]
    out = index.df.iloc[res.indices][cols + ["match_id"]].copy()
    out["similarity"] = np.round(res.similarity, 2)
    out["distance"] = res.distances
    out["weight"] = weights
    out["years_old"] = np.round(years_between(pd.Timestamp(as_of), index.dates[res.indices]), 2)
    out["score"] = out["fthg"].astype("Int64").astype(str) + "-" + out["ftag"].astype("Int64").astype(str)
    out["ou25"] = np.where(out["total_goals"] > 2.5, "Over", "Under")
    out["btts"] = np.where(out["btts"].astype(bool), "Yes", "No")
    if "hthg" in out.columns:
        has_ht = out["hthg"].notna() & out["htag"].notna()
        out["ht_score"] = np.where(has_ht, out["hthg"].astype("Int64").astype(str) + "-" + out["htag"].astype("Int64").astype(str), "")
        out["htft"] = [htft_label(h if isinstance(h, str) else None, f if isinstance(f, str) else None)
                       for h, f in zip(out["htr"], out["ftr"])]
    return out.reset_index(drop=True)


def scope_result(index: SimilarityIndex, vec: np.ndarray, market: np.ndarray, as_of, params: AnalysisParams,
                 scope: str, league) -> tuple[ScopeResult, NeighbourResult, np.ndarray]:
    res = index.query(vec, as_of, k=params.k, metric=params.metric, scope=scope, league=league,
                      min_similarity=params.min_similarity)
    w = _weights(index, res, as_of, params.half_life_years)
    st = outcome_stats(index.df.iloc[res.indices], w) if len(res.indices) else outcome_stats(index.df.iloc[[]])
    adj = shrink(st.probs(), st.n_eff, market, params.prior_strength) if st.n > 0 else market.copy()
    sim = res.similarity
    sr = ScopeResult(scope, st, adj, float(np.mean(sim)) if len(sim) else float("nan"),
                     float(np.median(sim)) if len(sim) else float("nan"),
                     float(np.min(sim)) if len(sim) else float("nan"), res.n_candidates)
    return sr, res, w


def analyze_match(index: SimilarityIndex, row: pd.Series, as_of, params: AnalysisParams, settings=None,
                  backtest_ok: bool = True, league_groups: dict[str, list[str]] | None = None,
                  tolerance_levels: list[float] | None = None, include_analogues: bool = True) -> MatchAnalysis:
    cols = feature_columns(params.feature_set)
    vec = np.array([row[c] for c in cols], dtype=float)
    market = np.array([row["p_home"], row["p_draw"], row["p_away"]], dtype=float)
    league = row["league"]
    conf_cfg = settings.section("confidence") if settings is not None else {}
    sig_cfg = settings.section("signal") if settings is not None else {}

    scopes: dict[str, ScopeResult] = {}
    primary, primary_res, primary_w = scope_result(index, vec, market, as_of, params, params.scope, league)
    scopes[params.scope] = primary
    for extra in ("global", "same_league"):
        if extra not in scopes:
            scopes[extra], _, _ = scope_result(index, vec, market, as_of, params, extra, league)
    if league_groups and league in league_groups and len(league_groups[league]) > 1:
        scopes["similar_leagues"], _, _ = scope_result(index, vec, market, as_of, params, "league_group", league_groups[league])

    st = primary.stats
    hist = st.probs()
    adj = primary.adjusted
    edges = {o: float((adj[i] - market[i]) * 100) for i, o in enumerate(OUTCOMES)}
    raw_edges = {o: float((hist[i] - market[i]) * 100) for i, o in enumerate(OUTCOMES)}
    cis = {"home": st.ci_home, "draw": st.ci_draw, "away": st.ci_away}
    outside = {o: market_outside_ci(market[i], cis[o]) for i, o in enumerate(OUTCOMES)}
    conf = confidence_label(st.n_eff, conf_cfg or None)
    signal = classify_signal(edges, st.n_eff, outside, primary.avg_similarity, backtest_ok, sig_cfg, conf_cfg)

    summary: dict[str, Any] = {
        "match_id": row.get("match_id"), "date": pd.Timestamp(row["date"]).date().isoformat(),
        "time": row.get("time") if isinstance(row.get("time"), str) else "",
        "league": league, "home": row["home_team"], "away": row["away_team"],
        "odds_h": row["cons_h"], "odds_d": row["cons_d"], "odds_a": row["cons_a"],
        "market_h": market[0] * 100, "market_d": market[1] * 100, "market_a": market[2] * 100,
        "n": st.n, "n_eff": st.n_eff, "n_candidates": primary.n_candidates,
        "hist_h": hist[0] * 100, "hist_d": hist[1] * 100, "hist_a": hist[2] * 100,
        "adj_h": adj[0] * 100, "adj_d": adj[1] * 100, "adj_a": adj[2] * 100,
        "edge_h": edges["home"], "edge_d": edges["draw"], "edge_a": edges["away"],
        "raw_edge_h": raw_edges["home"], "raw_edge_d": raw_edges["draw"], "raw_edge_a": raw_edges["away"],
        "ci_h_lo": st.ci_home[0] * 100, "ci_h_hi": st.ci_home[1] * 100,
        "ci_d_lo": st.ci_draw[0] * 100, "ci_d_hi": st.ci_draw[1] * 100,
        "ci_a_lo": st.ci_away[0] * 100, "ci_a_hi": st.ci_away[1] * 100,
        "fair_h": fair_odds(adj[0]), "fair_d": fair_odds(adj[1]), "fair_a": fair_odds(adj[2]),
        "over25": st.over25 * 100, "under25": st.under25 * 100, "btts": st.btts_yes * 100,
        "avg_goals": st.avg_goals, "median_goals": st.median_goals,
        "home_goals_avg": st.home_goals_avg, "away_goals_avg": st.away_goals_avg,
        "market_over25": row["p_over25"] * 100 if pd.notna(row.get("p_over25")) else np.nan,
        "avg_similarity": primary.avg_similarity, "median_similarity": primary.median_similarity,
        "min_similarity": primary.min_similarity,
        "confidence": conf, "signal": signal.label, "signal_outcome": signal.outcome, "signal_reason": signal.as_text(),
        "z_h": two_proportion_z(hist[0], st.n_eff, market[0]), "z_d": two_proportion_z(hist[1], st.n_eff, market[1]),
        "z_a": two_proportion_z(hist[2], st.n_eff, market[2]),
        "scope": params.scope, "feature_set": params.feature_set, "metric": params.metric, "k": params.k,
        "half_life": params.half_life_years, "prior_strength": params.prior_strength,
    }
    summary["p_value_min"] = min(p_value_from_z(summary[k]) for k in ("z_h", "z_d", "z_a"))
    for name, sr in scopes.items():
        summary[f"{name}_n"] = sr.stats.n
        summary[f"{name}_hist_h"] = sr.stats.home * 100
        summary[f"{name}_hist_d"] = sr.stats.draw * 100
        summary[f"{name}_hist_a"] = sr.stats.away * 100
        summary[f"{name}_adj_h"] = sr.adjusted[0] * 100
        summary[f"{name}_adj_d"] = sr.adjusted[1] * 100
        summary[f"{name}_adj_a"] = sr.adjusted[2] * 100
        summary[f"{name}_avg_sim"] = sr.avg_similarity
    summary["scorelines"] = st.scorelines
    summary["goals_dist"] = st.goals_dist
    summary["ht_h"], summary["ht_d"], summary["ht_a"], summary["n_ht"] = st.ht_home * 100, st.ht_draw * 100, st.ht_away * 100, st.n_ht
    summary["htft"] = st.htft
    summary["halves"] = st.halves

    tolerance: dict[str, dict[float, int]] = {}
    if tolerance_levels:
        odds = np.array([row["cons_h"], row["cons_d"], row["cons_a"]], dtype=float)
        tm = index.tolerance_match(odds, market, as_of, tolerance_levels, scope=params.scope, league=league)
        tolerance = {mode: {tol: int(len(ix)) for tol, ix in levels.items()} for mode, levels in tm.items()}
        for mode, levels in tolerance.items():
            for tol, cnt in levels.items():
                summary[f"tol_{mode}_{int(round(tol * 100))}pct"] = cnt

    analogues = analogue_frame(index, primary_res, primary_w, as_of) if include_analogues else pd.DataFrame()
    return MatchAnalysis(summary=summary, analogues=analogues, scopes=scopes, tolerance=tolerance, signal=signal)


def summaries_to_frame(analyses: list[MatchAnalysis]) -> pd.DataFrame:
    rows = []
    for a in analyses:
        s = {k: v for k, v in a.summary.items() if k not in ("scorelines", "goals_dist", "htft", "halves")}
        rows.append(s)
    return pd.DataFrame(rows)
