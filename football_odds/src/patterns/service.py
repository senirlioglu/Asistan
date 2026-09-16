"""What the web app is allowed to ask the research engines, and how much memory that costs.

The full state table joined to the match database is 145 columns and 223 MB in pandas — too much to
hold in a web process that also serves the site. This module loads only the columns the twin engine
and the outcome measurements actually read, narrows the numbers to float32 and the repeated strings
to categories: 40 columns, 38 MB, 0,3 s to index and about 120 ms per query over 180.000 matches.

Everything here is read-only and cached on the parquet's own modification time, so the daily job can
rewrite the table underneath a running process and the next request picks it up.
"""

from __future__ import annotations

import json
from functools import lru_cache

import pandas as pd

from ..config import Settings
from ..logging_setup import get_logger
from . import state, twins

log = get_logger("patterns.service")

COLUMNS = [
    "match_id", "date", "league", "season", "home_team", "away_team",
    "ftr", "htr", "fthg", "ftag", "hthg", "htag", "total_goals",
    "p_home", "p_draw", "p_away", "p_over25", "cons_h", "cons_d", "cons_a", "delta_p_home",
    "h_form", "a_form", "h_form_venue", "a_form_venue", "h_tsi", "a_tsi", "h_tsi_pct", "a_tsi_pct",
    "strength_gap", "h_gf5", "h_ga5", "a_gf5", "a_ga5", "h_pts5", "a_pts5", "h_pos", "a_pos",
    "h_rest_days", "a_rest_days", "h_since_rev", "a_since_rev", "h2h_n",
]
CATEGORIES = ("league", "season", "ftr", "htr", "h_form", "a_form", "h_form_venue", "a_form_venue")


def _slim(df: pd.DataFrame) -> pd.DataFrame:
    out = df[[c for c in COLUMNS if c in df.columns]].copy()
    for c in out.select_dtypes("float64").columns:
        out[c] = out[c].astype("float32")
    for c in CATEGORIES:
        if c in out:
            out[c] = out[c].astype("category")
    return out


@lru_cache(maxsize=2)
def _cached(path: str, mtime: float) -> tuple[pd.DataFrame, twins.TwinIndex, twins.TwinIndex]:
    df = _slim(pd.read_parquet(path))
    log.info("research frame: %d matches, %d MB", len(df), round(df.memory_usage(deep=True).sum() / 1e6))
    return df, twins.TwinIndex(df, "home"), twins.TwinIndex(df, "away")


def _load(settings: Settings):
    p = state.state_path(settings)
    if not p.exists():
        return None
    return _cached(str(p), p.stat().st_mtime)


def frame(settings: Settings) -> pd.DataFrame | None:
    got = _load(settings)
    return got[0] if got else None


def twins_for(settings: Settings, match_id: str, k: int = 50, side: str = "home", sample: int = 12) -> dict | None:
    """The twins of one match: the list, how close they actually are, and what they did."""
    got = _load(settings)
    if got is None:
        return None
    df, home_index, away_index = got
    hit = df[df["match_id"] == match_id]
    if hit.empty:
        return None
    row = hit.iloc[0]
    index = home_index if side == "home" else away_index
    res = index.query(row, k=k, as_of=row["date"])
    cols = ["date", "league", "home_team", "away_team", "ftr", "fthg", "ftag", "twin_score",
            "sim_market", "sim_strength", "sim_opponent", "sim_gap", "sim_form", "sim_goals", "sim_movement",
            "h_form", "a_form", "p_home", "p_draw", "p_away"]
    rows = res.rows.head(sample)[[c for c in cols if c in res.rows.columns]].copy()
    rows["date"] = rows["date"].dt.strftime("%Y-%m-%d")
    return {
        "match": {"id": match_id, "date": str(row["date"])[:10], "league": str(row["league"]),
                  "home": str(row["home_team"]), "away": str(row["away_team"]), "side": side,
                  "market": [_f(row.get("p_home")), _f(row.get("p_draw")), _f(row.get("p_away"))],
                  "h_form": _s(row.get("h_form")), "a_form": _s(row.get("a_form")),
                  "h_tsi": _f(row.get("h_tsi")), "a_tsi": _f(row.get("a_tsi")),
                  "h_tsi_pct": _f(row.get("h_tsi_pct")), "a_tsi_pct": _f(row.get("a_tsi_pct")),
                  "gap": _f(row.get("strength_gap"))},
        "k": k, "diagnostics": res.diagnostics, "weights": res.weights,
        "outcomes": res.outcomes, "twins": rows.to_dict("records"),
    }


def research_files(settings: Settings) -> dict:
    """The offline research results, as written by `cli notes / models / discover`."""
    out: dict[str, object] = {}
    for name, fname in (("notes", "notes_measured.json"), ("models", "backtest/models.json"),
                        ("discovery", "backtest/discovery.json")):
        p = settings.results_dir / fname
        try:
            out[name] = json.loads(p.read_text(encoding="utf-8")) if p.exists() else None
        except (json.JSONDecodeError, OSError) as exc:
            log.warning("could not read %s: %s", p, exc)
            out[name] = None
    return out


def _f(v):
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return None if pd.isna(f) else round(f, 4)


def _s(v):
    return "" if v is None or (isinstance(v, float) and pd.isna(v)) else str(v)
