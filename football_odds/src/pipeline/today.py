"""Today's matches pipeline.

    fixtures (CurrentOddsProvider) -> analyze_match for each -> results/YYYY-MM-DD_predictions.csv/.xlsx
                                                            -> results/analogues/YYYY-MM-DD_analogues.parquet
                                                            -> results/YYYY-MM-DD_details.json (scorelines, goal dist, scopes)

The analysis parameters come from results/backtest/selected_params.json when a backtest has been
run (validated choice), otherwise from config/settings.yaml. The pool for every fixture is every
match played before the run date, so nothing from the fixture day itself can leak in.
"""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

import numpy as np
import pandas as pd

from ..config import Settings, current_season_code
from ..data.build import build_processed
from ..data.football_data import download_all
from ..data.providers import ParquetHistoricalProvider, make_current_provider
from ..features.vectors import feature_mask
from ..logging_setup import get_logger
from ..models.engine import AnalysisParams, MatchAnalysis, analyze_match, summaries_to_frame
from ..models.similarity import SimilarityIndex
from ..backtest.buckets import load_league_groups

log = get_logger("pipeline.today")

TABLE_COLUMNS = [
    "date", "time", "league", "home", "away", "odds_h", "odds_d", "odds_a",
    "market_h", "market_d", "market_a", "n", "hist_h", "hist_d", "hist_a", "adj_h", "adj_d", "adj_a",
    "edge_h", "edge_d", "edge_a", "over25", "under25", "btts", "avg_goals", "confidence", "signal",
    "avg_similarity", "median_similarity", "min_similarity", "n_eff",
    "ci_h_lo", "ci_h_hi", "ci_d_lo", "ci_d_hi", "ci_a_lo", "ci_a_hi", "fair_h", "fair_d", "fair_a",
    "market_over25", "signal_outcome", "signal_reason", "match_id",
    "odds_max_h", "odds_max_d", "odds_max_a", "odds_o25", "odds_u25", "odds_max_o25", "odds_max_u25",
]


def load_selected_params(settings: Settings) -> tuple[AnalysisParams, bool, dict]:
    path = settings.results_dir / "backtest" / "selected_params.json"
    if path.exists():
        sel = json.loads(path.read_text())
        params = AnalysisParams(feature_set=sel["feature_set"], metric=sel["metric"], k=int(sel["k"]),
                                half_life_years=sel.get("half_life_years"), min_similarity=float(sel.get("min_similarity", 0)),
                                scope=sel.get("scope", "global"), prior_strength=float(sel.get("prior_strength", 50)))
        return params, bool(sel.get("backtest_ok", False)), sel
    log.warning("no backtest results found — using config defaults and backtest_ok=False")
    return AnalysisParams.from_settings(settings), False, {}


def update_history(settings: Settings) -> None:
    """Refresh the current season's raw files and rebuild the processed database."""
    download_all(settings, seasons=[current_season_code()])
    build_processed(settings)


def run_today(settings: Settings, date: dt.date | None = None, days: int = 1, provider_name: str | None = None,
              refresh: bool = False, update: bool = False, out_dir: Path | None = None) -> pd.DataFrame:
    date = date or dt.date.today()
    date_to = date + dt.timedelta(days=max(days, 1) - 1)
    out_dir = out_dir or settings.results_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    if update:
        update_history(settings)

    history = ParquetHistoricalProvider(settings).load()
    history = history[history["date"] < pd.Timestamp(date)]
    params, backtest_ok, selected = load_selected_params(settings)
    groups = load_league_groups(settings.results_dir / "league_groups.json")
    provider_kwargs = {"force_refresh": refresh} if (provider_name or settings.get("current.provider")) == "football_data_fixtures" else {}
    provider = make_current_provider(settings, provider_name, **provider_kwargs)
    fixtures = provider.fetch(date_from=date, date_to=date_to)
    if fixtures.empty:
        log.warning("no fixtures with odds between %s and %s", date, date_to)
        return pd.DataFrame(columns=TABLE_COLUMNS)

    indexes = {params.feature_set: SimilarityIndex(history, params.feature_set)}
    if params.feature_set != "1x2":
        indexes["1x2"] = SimilarityIndex(history, "1x2")
    tol_levels = [float(t) for t in settings.get("similarity.tolerance_levels", [0.01, 0.02, 0.03, 0.05])]

    analyses: list[MatchAnalysis] = []
    analogues: list[pd.DataFrame] = []
    details: dict[str, dict] = {}
    for _, row in fixtures.iterrows():
        p = params
        fs = params.feature_set
        if not feature_mask(row.to_frame().T, fs)[0]:
            fs = "1x2"  # fixture lacks O/U odds -> fall back to the 1X2 model
            p = AnalysisParams(**{**params.to_dict(), "feature_set": fs})
        if not feature_mask(row.to_frame().T, fs)[0]:
            continue
        a = analyze_match(indexes[fs], row, pd.Timestamp(date), p, settings, backtest_ok, groups, tol_levels)
        analyses.append(a)
        frame = a.analogues.copy()
        frame.insert(0, "fixture_id", a.summary["match_id"])
        analogues.append(frame)
        details[a.summary["match_id"]] = {
            "scorelines": a.summary["scorelines"], "goals_dist": a.summary["goals_dist"],
            "htft": a.summary.get("htft", {}),
            "halves": a.summary.get("halves", {}),
            "ht": {"home": a.summary.get("ht_h"), "draw": a.summary.get("ht_d"), "away": a.summary.get("ht_a"), "n": a.summary.get("n_ht")},
            "tolerance": {mode: {str(k): v for k, v in lv.items()} for mode, lv in a.tolerance.items()},
            "scopes": {name: {"n": sr.stats.n, "hist": sr.stats.probs().tolist(), "adj": sr.adjusted.tolist(),
                              "avg_similarity": sr.avg_similarity} for name, sr in a.scopes.items()},
            "signal_reasons": a.signal.reasons if a.signal else [],
        }

    table = summaries_to_frame(analyses)
    if table.empty:
        log.warning("no analysable fixtures")
        return table
    ordered = [c for c in TABLE_COLUMNS if c in table.columns] + [c for c in table.columns if c not in TABLE_COLUMNS]
    table = table[ordered].sort_values(["date", "time", "league"]).reset_index(drop=True)

    stamp = date.isoformat()
    csv_path = out_dir / f"{stamp}_predictions.csv"
    table.round(3).to_csv(csv_path, index=False)
    try:
        table.round(3).to_excel(out_dir / f"{stamp}_predictions.xlsx", index=False)
    except Exception as exc:  # noqa: BLE001 - openpyxl missing is not fatal
        log.warning("xlsx export skipped: %s", exc)
    (out_dir / "analogues").mkdir(exist_ok=True)
    if analogues:
        pd.concat(analogues, ignore_index=True).to_parquet(out_dir / "analogues" / f"{stamp}_analogues.parquet", index=False)
    (out_dir / f"{stamp}_details.json").write_text(json.dumps({
        "date": stamp, "params": params.to_dict(), "backtest_ok": backtest_ok, "backtest": {k: selected.get(k) for k in
        ("brier_market", "brier_adj", "brier_adj_p_value", "significant_improvement", "test_seasons")}, "matches": details,
    }, indent=1, default=str))
    log.info("wrote %s (%d matches)", csv_path, len(table))
    print_report(table, backtest_ok)
    return table


def print_report(table: pd.DataFrame, backtest_ok: bool, top: int = 10) -> None:
    """Readable console summary."""
    n_dev = int(table["signal"].str.contains("DEVIATION").sum())
    print(f"\n=== {table['date'].iloc[0]}  {len(table)} matches analysed  |  backtest_ok={backtest_ok} ===")
    if n_dev == 0:
        print("NO STATISTICALLY MEANINGFUL DEVIATION today.\n")
    ranked = table.assign(_e=table[["edge_h", "edge_d", "edge_a"]].abs().max(axis=1)).sort_values("_e", ascending=False)
    for _, r in ranked.head(top).iterrows():
        print(f"{r['league']:4} {r['home']} – {r['away']}   {r['odds_h']:.2f} / {r['odds_d']:.2f} / {r['odds_a']:.2f}")
        print(f"     market {r['market_h']:.1f} / {r['market_d']:.1f} / {r['market_a']:.1f}   "
              f"hist(N={int(r['n'])}) {r['hist_h']:.1f} / {r['hist_d']:.1f} / {r['hist_a']:.1f}   "
              f"adj {r['adj_h']:.1f} / {r['adj_d']:.1f} / {r['adj_a']:.1f}")
        print(f"     edge H {r['edge_h']:+.1f}  D {r['edge_d']:+.1f}  A {r['edge_a']:+.1f} pp | avg sim {r['avg_similarity']:.1f}% | "
              f"O2.5 {r['over25']:.1f}% BTTS {r['btts']:.1f}% goals {r['avg_goals']:.2f} | {r['confidence']} | {r['signal']}")
    print()
