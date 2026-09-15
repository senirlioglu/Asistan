"""Run our own analogue analysis on ANY nesine match, using nesine's odds as the market.

Football-Data's ``fixtures.csv`` only lists the coming fixtures of the 38 leagues we store, and only
after it is published (Tuesday/Friday), so the Maçlar tab can be nearly empty on other days. The
analysis itself, though, needs nothing but a price: the analogues are chosen by the market's
probability profile, not by league or team. So any match nesine quotes can be analysed against the
same 179k-match pool.

Two honest differences from the Maçlar tab, stated on the page:

* the market here is nesine's price (higher margin than the European average we store), so the
  margin-free probabilities sit a little differently;
* the match itself may be from a league outside our database (a cup, an Asian league, a youth game);
  the analogues are still matches with the same price profile, which is what the method uses.
"""

from __future__ import annotations

import datetime as dt
from functools import lru_cache

import pandas as pd

from ..config import Settings, current_season_code
from ..data.football_data import normalise_frame
from ..data.providers import ParquetHistoricalProvider
from ..features.odds import add_market_features
from ..features.vectors import feature_mask
from ..models.engine import AnalysisParams, analyze_match, summaries_to_frame
from ..models.similarity import SimilarityIndex
from ..backtest.buckets import load_league_groups
from ..pipeline.today import load_selected_params

PSEUDO_LEAGUE = "NES"  # not one of our division codes: same_league scope finds nothing, global is used
MAX_OVERROUND = 1.60   # nesine quotes ~1.20 on football; the config's 1.15 ceiling is for European averages


def to_raw_row(m: dict) -> dict:
    """One nesine match -> a Football-Data style raw row (only the columns we price on)."""
    ms, ou = m.get("ms") or {}, m.get("o25") or {}
    try:
        d = dt.date.fromisoformat(m["date"]).strftime("%d/%m/%Y")
    except (ValueError, KeyError, TypeError):
        d = ""
    return {"Div": PSEUDO_LEAGUE, "Date": d, "Time": str(m.get("time") or ""),
            "HomeTeam": str(m.get("home") or ""), "AwayTeam": str(m.get("away") or ""),
            "AvgH": ms.get("1"), "AvgD": ms.get("X"), "AvgA": ms.get("2"),
            "Avg>2.5": ou.get("ust"), "Avg<2.5": ou.get("alt")}


def priced_row(settings: Settings, m: dict) -> pd.Series | None:
    """Margin-free market features for one nesine match, or None when 1X2 is incomplete/corrupt."""
    raw = pd.DataFrame([to_raw_row(m)])
    df = normalise_frame(raw, current_season_code(), PSEUDO_LEAGUE)
    if df.empty:
        return None
    cfg = settings.section("odds")
    # nesine's margin is far above the European average we store (~1.20 vs ~1.065), so the config's
    # corrupt-market ceiling would reject every match; the real overround is reported to the page
    df = add_market_features(df, cfg.get("normalization", "proportional"), float(cfg.get("min_valid_odds", 1.01)),
                             float(cfg.get("max_valid_odds", 200.0)), MAX_OVERROUND)
    return df.iloc[0] if bool(df.iloc[0]["has_1x2"]) else None


@lru_cache(maxsize=2)
def _index_cached(mtime: float, feature_set: str) -> tuple[SimilarityIndex, pd.DataFrame]:
    settings = _index_cached.settings  # type: ignore[attr-defined]
    hist = ParquetHistoricalProvider(settings).load()
    return SimilarityIndex(hist, feature_set), hist


def similarity_index(settings: Settings, feature_set: str) -> tuple[SimilarityIndex, pd.DataFrame]:
    p = settings.processed_dir / "matches.parquet"
    _index_cached.settings = settings  # type: ignore[attr-defined]
    return _index_cached(p.stat().st_mtime, feature_set)


def analyse(settings: Settings, m: dict, as_of: dt.date | None = None) -> dict | None:
    """{'summary': Series, 'analogues': DataFrame, 'details': dict, 'params': ...} or None when unpriceable."""
    row = priced_row(settings, m)
    if row is None:
        return None
    params, backtest_ok, selected = load_selected_params(settings)
    fs = params.feature_set
    if not feature_mask(row.to_frame().T, fs)[0]:
        fs = "1x2"  # nesine did not quote over/under for this match
        params = AnalysisParams(**{**params.to_dict(), "feature_set": fs})
    if not feature_mask(row.to_frame().T, fs)[0]:
        return None
    index, _ = similarity_index(settings, fs)
    as_of = as_of or dt.date.today()
    groups = load_league_groups(settings.results_dir / "league_groups.json")
    tol = [float(t) for t in settings.get("similarity.tolerance_levels", [0.01, 0.02, 0.03, 0.05])]
    a = analyze_match(index, row, pd.Timestamp(as_of), params, settings, backtest_ok, groups, tol)
    table = summaries_to_frame([a])
    details = {
        "scorelines": a.summary["scorelines"], "goals_dist": a.summary["goals_dist"],
        "htft": a.summary.get("htft", {}), "halves": a.summary.get("halves", {}),
        "ht": {"home": a.summary.get("ht_h"), "draw": a.summary.get("ht_d"), "away": a.summary.get("ht_a"), "n": a.summary.get("n_ht")},
        "tolerance": {mode: {str(k): v for k, v in lv.items()} for mode, lv in a.tolerance.items()},
        "scopes": {name: {"n": sr.stats.n, "hist": sr.stats.probs().tolist(), "adj": sr.adjusted.tolist(),
                          "avg_similarity": sr.avg_similarity} for name, sr in a.scopes.items()},
        "signal_reasons": a.signal.reasons if a.signal else [],
    }
    return {"summary": table.iloc[0], "analogues": a.analogues, "details": details,
            "params": params.to_dict(), "backtest_ok": backtest_ok, "feature_set": fs,
            "overround": float(row.get("overround_1x2")) if pd.notna(row.get("overround_1x2")) else None}
