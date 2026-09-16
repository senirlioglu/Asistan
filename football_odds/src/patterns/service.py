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
from pathlib import Path

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
def _cached(path: str, mtime: float, results_dir: str) -> tuple[pd.DataFrame, twins.TwinIndex, twins.TwinIndex, dict]:
    df = _slim(pd.read_parquet(path))
    w, half_life, meta = twins.load_weights(Path(results_dir))
    log.info("research frame: %d matches, %d MB, twin weights %s (yarı ömür %s)",
             len(df), round(df.memory_usage(deep=True).sum() / 1e6), meta["source"], half_life)
    return (df, twins.TwinIndex(df, "home", w, half_life), twins.TwinIndex(df, "away", w, half_life),
            {**meta, "half_life": half_life, "weights": w.as_dict()})


def _load(settings: Settings):
    p = state.state_path(settings)
    if not p.exists():
        return None
    return _cached(str(p), p.stat().st_mtime, str(settings.results_dir))


def frame(settings: Settings) -> pd.DataFrame | None:
    got = _load(settings)
    return got[0] if got else None


def twin_config(settings: Settings) -> dict | None:
    """Which weights and half life the live twin engine is actually running, and why."""
    got = _load(settings)
    return got[3] if got else None


def twins_for(settings: Settings, match_id: str, k: int = 50, side: str = "home", sample: int = 12) -> dict | None:
    """The twins of one match: the list, how close they actually are, and what they did."""
    got = _load(settings)
    if got is None:
        return None
    df, home_index, away_index, cfg = got
    hit = df[df["match_id"] == match_id]
    if hit.empty:
        return None
    row = hit.iloc[0]
    index = home_index if side == "home" else away_index
    res = index.query(row, k=k, as_of=row["date"])
    cols = ["date", "league", "home_team", "away_team", "ftr", "fthg", "ftag", "twin_score", "twin_weight",
            "sim_market", "sim_strength", "sim_opponent", "sim_gap", "sim_form", "sim_goals", "sim_movement",
            "h_form", "a_form", "p_home", "p_draw", "p_away"]
    rows = res.rows.head(sample)[[c for c in cols if c in res.rows.columns]].copy()
    rows["date"] = rows["date"].dt.strftime("%Y-%m-%d")
    return {
        # the state table's own reading of the match, carried out in full: these are the inputs both
        # engines run on and they were being computed and then thrown away
        "match": {"id": match_id, "date": str(row["date"])[:10], "league": str(row["league"]),
                  "home": str(row["home_team"]), "away": str(row["away_team"]), "side": side,
                  "market": [_f(row.get("p_home")), _f(row.get("p_draw")), _f(row.get("p_away"))],
                  "h_form": _s(row.get("h_form")), "a_form": _s(row.get("a_form")),
                  "h_form_venue": _s(row.get("h_form_venue")), "a_form_venue": _s(row.get("a_form_venue")),
                  "h_tsi": _f(row.get("h_tsi")), "a_tsi": _f(row.get("a_tsi")),
                  "h_tsi_pct": _f(row.get("h_tsi_pct")), "a_tsi_pct": _f(row.get("a_tsi_pct")),
                  "h_gf5": _f(row.get("h_gf5")), "h_ga5": _f(row.get("h_ga5")),
                  "a_gf5": _f(row.get("a_gf5")), "a_ga5": _f(row.get("a_ga5")),
                  "h_rest_days": _f(row.get("h_rest_days")), "a_rest_days": _f(row.get("a_rest_days")),
                  "h_pos": _f(row.get("h_pos")), "a_pos": _f(row.get("a_pos")),
                  "h2h_n": _f(row.get("h2h_n")), "delta_p_home": _f(row.get("delta_p_home")),
                  "gap": _f(row.get("strength_gap"))},
        "k": k, "diagnostics": res.diagnostics, "weights": res.weights, "config": cfg,
        "outcomes": res.outcomes, "twins": rows.to_dict("records"),
    }


PATTERN_OUTCOMES = ("win", "draw", "loss", "over25", "btts", "over15", "over35", "ht_draw", "ht_win")


_POOL_STATS: dict[tuple, tuple[dict, dict]] = {}


def _pool_stats(df: pd.DataFrame, key: tuple, side: str, year: int) -> tuple[dict, dict]:
    """The whole-pool offset and the unpriced markets' base rates, for matches before `year`.

    Both are ~180.000-match estimates that cost three seconds to recompute, and both are the same
    for every match in a season — so they are cached per year rather than per request. Cutting the
    pool at 1 January keeps the cache honest: a match in September is never measured against an
    offset that its own season helped produce."""
    from . import engine

    ck = (*key, side, year)
    if ck not in _POOL_STATS:
        if len(_POOL_STATS) > 64:
            _POOL_STATS.clear()
        pool = df[df["date"] < pd.Timestamp(year=year, month=1, day=1)]
        _POOL_STATS[ck] = (engine.baseline(pool, side, PATTERN_OUTCOMES),
                           engine.pool_rates(pool, side, PATTERN_OUTCOMES))
    return _POOL_STATS[ck]


def patterns_for(settings: Settings, match_id: str, side: str = "home", approx: int = 0,
                 sample: int = 8, band: float = 10.0) -> dict | None:
    """This match's own form pattern, measured at the three levels the brief asks for.

    Level 1 is the club's own history with the pattern (usually a handful of matches — reported with
    its N so nobody over-reads it), level 2 is every team in the database, level 3 is teams that were
    of comparable strength *at the time*, never by name. `approx` allows that many mismatched slots,
    which is the exact-vs-near question: both counts come back so the two can be read side by side.
    """
    from . import engine

    got = _load(settings)
    if got is None:
        return None
    df = got[0]
    hit = df[df["match_id"] == match_id]
    if hit.empty:
        return None
    row = hit.iloc[0]
    p, o = ("h_", "a_") if side == "home" else ("a_", "h_")
    form = str(row.get(f"{p}form") or "")[-5:]
    if not form:
        return None
    team = str(row.get("home_team" if side == "home" else "away_team"))
    tsi = _f(row.get(f"{p}tsi_pct"))
    as_of = row["date"]
    pool = df[df["date"] < as_of]
    p_ = state.state_path(settings)
    base, refs = _pool_stats(df, (str(p_), p_.stat().st_mtime), side, int(pd.Timestamp(as_of).year))
    pattern = engine.Pattern(form=form, side=side, approx=approx)
    out = engine.levels(pool, pattern, team=team, tsi_pct=tsi, band=band, as_of=as_of,
                        outcomes=PATTERN_OUTCOMES, sample=sample, base=base, refs=refs)
    exact = engine.select(pool, engine.Pattern(form=form, side=side, approx=0), as_of=as_of)
    return {
        "match": {"id": match_id, "date": str(row["date"])[:10], "league": str(row["league"]),
                  "home": str(row["home_team"]), "away": str(row["away_team"]), "side": side,
                  "team": team, "form": form, "opponent_form": str(row.get(f"{o}form") or "")[-5:],
                  "tsi_pct": tsi, "opp_tsi_pct": _f(row.get(f"{o}tsi_pct")), "band": band},
        "approx": approx, "n_exact": int(len(exact)),
        "levels": out, "outcomes": list(PATTERN_OUTCOMES),
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
