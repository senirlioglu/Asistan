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
from dataclasses import replace
from functools import lru_cache
from pathlib import Path

import numpy as np
import pandas as pd

from ..config import Settings
from ..logging_setup import get_logger
from . import engine as _engine
from . import state, twins

log = get_logger("patterns.service")

COLUMNS = [
    "match_id", "date", "league", "season", "home_team", "away_team",
    "ftr", "htr", "fthg", "ftag", "hthg", "htag", "total_goals",
    "p_home", "p_draw", "p_away", "p_over25", "cons_h", "cons_d", "cons_a", "delta_p_home",
    "h_form", "a_form", "h_form_venue", "a_form_venue", "h_tsi", "a_tsi", "h_tsi_pct", "a_tsi_pct",
    "strength_gap", "h_gf5", "h_ga5", "a_gf5", "a_ga5", "h_pts5", "a_pts5", "h_pos", "a_pos",
    "h_rest_days", "a_rest_days", "h_since_rev", "a_since_rev", "h2h_n",
    # the goal-pattern conditions Pattern Lab's own-pattern mode filters on (counts over the last five)
    "h_btts5", "a_btts5", "h_ov15_5", "a_ov15_5", "h_ov25_5", "a_ov25_5", "h_ov35_5", "a_ov35_5",
    "avgc_h", "avgc_d", "avgc_a",           # closing prices (2019/20 on): CLV for the cycle rows
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


def _fixture_context(df: pd.DataFrame) -> pd.DataFrame:
    """Each side's previous and next opponent — the "fikstür bağlamı" the pattern graphics are about.

    The previous opponent is history. The NEXT opponent is knowable before kick-off too, because
    league schedules are published in advance; the next match's *result* is not, and is never read.

    This deliberately does not live in `match_state.parquet`. That table is protected by a test that
    rebuilds every row from the prefix of the database preceding it and demands identical features —
    a column naming a match that has not happened yet would fail it, and that invariant is worth more
    than the convenience. So the context is derived here, once per frame, and kept out of the state."""
    order: dict[str, list[int]] = {}
    H, A = df["home_team"].astype(str).to_numpy(), df["away_team"].astype(str).to_numpy()
    for i in range(len(df)):
        order.setdefault(H[i], []).append(i)
        order.setdefault(A[i], []).append(i)
    cols = {k: [None] * len(df) for k in ("h_prev_opp", "h_next_opp", "a_prev_opp", "a_next_opp")}
    for team, idxs in order.items():
        for k, i in enumerate(idxs):
            prev = (A[idxs[k - 1]] if H[idxs[k - 1]] == team else H[idxs[k - 1]]) if k else None
            nxt = (A[idxs[k + 1]] if H[idxs[k + 1]] == team else H[idxs[k + 1]]) if k + 1 < len(idxs) else None
            side = "h_" if H[i] == team else "a_"
            cols[f"{side}prev_opp"][i], cols[f"{side}next_opp"][i] = prev, nxt
    return pd.DataFrame(cols, index=df.index)


@lru_cache(maxsize=2)
def _cached(path: str, mtime: float, results_dir: str) -> tuple[pd.DataFrame, twins.TwinIndex, twins.TwinIndex, dict]:
    df = _slim(pd.read_parquet(path))
    df = df.sort_values(["date", "match_id"]).reset_index(drop=True)
    df = pd.concat([df, _fixture_context(df)], axis=1)
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


def twin_query(settings: Settings, match_id: str, k: int = 50, side: str = "home") -> tuple[pd.Series, twins.TwinResult, dict] | None:
    """The raw twin query for one match: (the match row, the TwinResult with every twin row and its
    decay weight, the engine configuration). Pattern Lab measures its own targets on these rows."""
    got = _load(settings)
    if got is None:
        return None
    df, home_index, away_index, cfg = got
    hit = df[df["match_id"] == match_id]
    if hit.empty:
        return None
    row = hit.iloc[0]
    index = home_index if side == "home" else away_index
    return row, index.query(row, k=k, as_of=row["date"]), cfg


def twins_for(settings: Settings, match_id: str, k: int = 50, side: str = "home", sample: int = 12) -> dict | None:
    """The twins of one match: the list, how close they actually are, and what they did."""
    got = twin_query(settings, match_id, k=k, side=side)
    if got is None:
        return None
    row, res, cfg = got
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
# Pattern Lab's targets are match-perspective (1 / X / 2, İY, İY/MS); the pool offsets and the
# price-matched references are cached for both families at once so a target costs no extra scan
LAB_OUTCOMES = PATTERN_OUTCOMES + _engine.MATCH_OUTCOMES


_POOL_STATS: dict[tuple, tuple[dict, dict]] = {}


def _pool_stats(df: pd.DataFrame, key: tuple, side: str, year: int) -> tuple[dict, dict]:
    """The whole-pool offset for matches before `year`, and the pool's own rate per outcome.

    The offset is a ~180.000-match estimate that costs three seconds to recompute and is the same
    for every match in a season, so it is cached per year. Cutting the pool at 1 January keeps the
    cache honest: a match in September is never measured against an offset its own season helped
    produce.

    The second value is the naive pool rate, kept only as a fallback. It must NOT be used as the
    reference for a selected group: a team on WWW leads at half time more often than the pool
    average because it is a better team, and comparing it to that average turns "this side is
    good" into a discovery. `_refs` below does the comparison properly."""
    from . import engine

    ck = (*key, side, year)
    if ck not in _POOL_STATS:
        if len(_POOL_STATS) > 64:
            _POOL_STATS.clear()
        pool = df[df["date"] < pd.Timestamp(year=year, month=1, day=1)]
        _POOL_STATS[ck] = (engine.baseline(pool, side, LAB_OUTCOMES),
                           engine.pool_rates(pool, side, LAB_OUTCOMES))
    return _POOL_STATS[ck]


_OUT_CACHE: dict[tuple, dict] = {}


def _cache_for(df: pd.DataFrame, key: tuple, side: str) -> dict:
    from . import engine

    # the pool differs by as-of date (matches before the day analysed) and the explorer uses the whole
    # frame: a cache built on one and read with the other's mask is a shape error, so the size is in the key
    ck = (*key, side, len(df))
    if ck not in _OUT_CACHE:
        if len(_OUT_CACHE) > 8:
            _OUT_CACHE.clear()
        _OUT_CACHE[ck] = engine.outcome_cache(df, side, LAB_OUTCOMES)
    return _OUT_CACHE[ck]


def _refs_fast(df: pd.DataFrame, sub: pd.DataFrame, side: str, key: tuple, fallback: dict) -> dict:
    """Price-matched references off the cached arrays — the same answer, without the scan."""
    from . import engine

    if sub is None or not len(sub):
        return dict(fallback)
    mask = np.zeros(len(df), dtype=bool)
    mask[df.index.get_indexer(sub.index)] = True
    return {**fallback, **engine.matched_rates_cached(_cache_for(df, key, side), mask)}


def _refs(frame: pd.DataFrame, sub: pd.DataFrame, side: str, fallback: dict) -> dict:
    """Price-matched reference rates for the outcomes the market does not quote.

    Half-time results, reversals and 6+ goals carry no price, so they are compared with how often
    the same thing happened in matches that were priced the same way. Comparing them with the pool
    average instead is the oldest trap in this project: every pattern that selects good teams then
    "beats" a baseline built from all teams."""
    from . import engine

    if sub is None or not len(sub):
        return dict(fallback)
    matched = engine.matched_rates(frame, sub, side, PATTERN_OUTCOMES)
    return {**fallback, **matched}


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
    base, naive = _pool_stats(df, (str(p_), p_.stat().st_mtime), side, int(pd.Timestamp(as_of).year))
    pattern = engine.Pattern(form=form, side=side, approx=approx)
    refs = _refs_fast(pool, engine.select(pool, pattern, as_of=as_of), side, (str(p_), p_.stat().st_mtime), naive)
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


COMBINED_LENGTH, COMBINED_APPROX = 3, 1


def combined_for(settings: Settings, match_id: str, side: str = "home", approx: int = COMBINED_APPROX,
                 length: int = COMBINED_LENGTH, band: float = 10.0, gap_band: float = 60.0,
                 outcomes: tuple[str, ...] = PATTERN_OUTCOMES) -> dict | None:
    """TEAM A x TEAM B: this match's two states at once, one condition at a time.

    The pattern engine has always been able to describe one side. A match is two sides, and the
    claim "a team on WWWWW wins 67 %" is a different claim from "a team on WWWWW hosting a team on
    LLLLL wins 67 %" — only the second one is about a fixture. The cascade adds the conditions in
    the order they get specific and reports every row against the market, so the reader can see
    which condition actually moved the number and which merely shrank the sample.

    Strength is always a band around this match's own value, never a team name: a 2014 side at the
    81st percentile of its league belongs in the same bucket as a 2026 side at the 84th, and asking
    for "teams like Galatasaray" would instead ask for a name that meant something different in
    every season it appears.

    The defaults are three results with one allowed to differ, and they were measured rather than
    chosen. Over 180.000 matches, the median sample surviving each condition is:

        length 5 exact    881 ->    10 ->     0 ->    0
        length 5, ±1     9368 ->   767 ->    46 ->    5
        length 4 exact   2465 ->    49 ->     1 ->    0
        length 3 exact   6578 ->   527 ->    27 ->    3
        length 3, ±1    46111 -> 18124 ->  4686 -> 2066

    Only the last row still holds a measurable sample once both teams are described, so anything
    stricter answers "no such match has ever been played" — which is true, and useless. The tighter
    settings stay available because watching the count collapse is itself the finding: two exact
    five-match sequences are very nearly a unique key, and a pattern that identifies one historical
    fixture predicts nothing.
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
    form, venue = _tail(row.get(f"{p}form"), length), _tail(row.get(f"{p}form_venue"), length)
    opp_form, opp_venue = _tail(row.get(f"{o}form"), length), _tail(row.get(f"{o}form_venue"), length)
    if not form:
        return None
    tsi, opp_tsi = _f(row.get(f"{p}tsi_pct")), _f(row.get(f"{o}tsi_pct"))
    gap = _f(row.get("strength_gap"))
    sign = 1 if side == "home" else -1
    as_of = row["date"]
    pool = df[df["date"] < as_of]
    sp = state.state_path(settings)
    base, naive = _pool_stats(df, (str(sp), sp.stat().st_mtime), side, int(pd.Timestamp(as_of).year))

    at = engine.Pattern(form=form, side=side, approx=approx)
    steps: list[tuple[str, object]] = [(f"{_who(side)} formu {form}", at)]
    if venue:
        at = replace(at, venue_form=venue)
        steps.append((f"+ {'ev' if side == 'home' else 'deplasman'} formu {venue}", at))
    if tsi is not None:
        at = replace(at, tsi_pct=(max(0.0, tsi - band), min(100.0, tsi + band)))
        steps.append((f"+ benzer güç (%{tsi:g} ± {band:g})", at))
    n_team_steps = len(steps)                 # everything after this describes the opponent or the pair
    if opp_form:
        at = replace(at, opp_form=opp_form)
        steps.append((f"+ rakip formu {opp_form}", at))
    if opp_venue:
        at = replace(at, opp_venue_form=opp_venue)
        steps.append((f"+ rakip saha formu {opp_venue}", at))
    if opp_tsi is not None:
        at = replace(at, opp_tsi_pct=(max(0.0, opp_tsi - band), min(100.0, opp_tsi + band)))
        steps.append((f"+ benzer rakip gücü (%{opp_tsi:g} ± {band:g})", at))
    if gap is not None:
        lo, hi = sign * gap - gap_band, sign * gap + gap_band
        at = replace(at, gap=(round(lo, 1), round(hi, 1)))
        steps.append((f"+ güç farkı {sign * gap:+.0f} ± {gap_band:g}", at))

    refs = _refs_fast(pool, engine.select(pool, steps[0][1], as_of=as_of), side, (str(sp), sp.stat().st_mtime), naive)
    rows = engine.cascade(pool, steps, as_of=as_of, outcomes=outcomes, base=base, refs=refs)
    return {
        "match": {"id": match_id, "date": str(row["date"])[:10], "league": str(row["league"]),
                  "home": str(row["home_team"]), "away": str(row["away_team"]), "side": side,
                  "team": str(row["home_team" if side == "home" else "away_team"]),
                  "opponent": str(row["away_team" if side == "home" else "home_team"]),
                  "form": form, "venue_form": venue, "opp_form": opp_form, "opp_venue_form": opp_venue,
                  "tsi_pct": tsi, "opp_tsi_pct": opp_tsi, "gap": gap,
                  "gf5": _f(row.get(f"{p}gf5")), "ga5": _f(row.get(f"{p}ga5")),
                  "opp_gf5": _f(row.get(f"{o}gf5")), "opp_ga5": _f(row.get(f"{o}ga5")),
                  "band": band, "gap_band": gap_band},
        "approx": approx, "length": length, "outcomes": list(outcomes), "rows": rows,
        "n_team_steps": n_team_steps,
    }


def _who(side: str) -> str:
    return "Ev sahibi" if side == "home" else "Deplasman"


def _tail(v, n: int = 5) -> str:
    return "" if v is None or (isinstance(v, float) and pd.isna(v)) else str(v)[-n:]


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


def explore(settings: Settings, form: str = "", side: str = "home", approx: int = 0,
            form_venue: bool = False, opp_form: str = "", tsi: tuple[float, float] | None = None,
            opp_tsi: tuple[float, float] | None = None, market: tuple[float, float] | None = None,
            leagues: list[str] | None = None, sample: int = 10) -> dict | None:
    """Ask the pattern engine a question of your own, over the whole database.

    The research tab has always claimed you can test an idea in seconds against 180.000 matches, and
    until now there was no control that did it: every pattern query was derived from a match rather
    than typed by a reader. This is that control.

    It is also, unavoidably, a p-hacking machine. Ask twenty questions and one of them comes back
    with an interval that clears zero, because that is what a 95 % interval means. So the answer
    carries `n_tests_note` and the caller is expected to say so: an idea that survives here has
    earned a run through `discovery.py`'s three windows, not a bet.
    """
    from . import engine

    got = _load(settings)
    if got is None:
        return None
    df = got[0]
    pattern = engine.Pattern(
        form=(form or None), side=side, approx=approx, form_venue=form_venue,
        opp_form=(opp_form or None),
        tsi_pct=tsi, opp_tsi_pct=opp_tsi, market=market,
        leagues=[x for x in (leagues or []) if x] or None,
    )
    sp = state.state_path(settings)
    year = int(pd.Timestamp(df["date"].max()).year) + 1          # the whole pool: nothing is held back
    base, naive = _pool_stats(df, (str(sp), sp.stat().st_mtime), side, year)
    sub = engine.select(df, pattern)
    res = engine.run(df, pattern, outcomes=PATTERN_OUTCOMES, sample=sample, base=base,
                     refs=_refs_fast(df, sub, side, (str(sp), sp.stat().st_mtime), naive))
    exact = pattern if not approx else engine.Pattern(**{**pattern.__dict__, "approx": 0})
    res["n_exact"] = int(len(engine.select(df, exact))) if form else res["n"]
    res["pool"] = int(len(df))
    res["span"] = [str(df["date"].min())[:10], str(df["date"].max())[:10]]
    res["outcomes_order"] = list(PATTERN_OUTCOMES)
    return res



# What the whole database says about the claim these graphics make, measured once rather than
# re-derived per request. "The result repeats" is compared with what the price said about that same
# outcome, so the number is an edge and not a hit rate.
FIXTURE_VERDICT = {
    "full": {"n": 3901, "actual": 38.6, "market": 39.0, "edge": -0.36, "ci": [-1.79, 1.07]},
    "prev_only": {"n": 26239, "actual": 39.5, "market": 38.9, "edge": 0.58, "ci": [0.03, 1.13]},
    "none": {"n": 141054, "actual": 39.2, "market": 38.8, "edge": 0.43, "ci": [0.19, 0.67]},
}


def fixture_context(settings: Settings, match_id: str, sample: int = 12) -> dict | None:
    """Every earlier meeting of these two clubs, each with the opponents around it.

    This is the "aynı fikstür sırası tekrarlıyor" pattern, made checkable: the previous meetings are
    listed with who each side played before and after, and the rows whose context matches today's
    are marked. The verdict travels with it, because the measurement says the context is what kills
    the effect rather than what creates it — narrowing 141.054 plain repeats to 3.901 context
    matches takes the edge from +0,43 to -0,36."""
    got = _load(settings)
    if got is None:
        return None
    df = got[0]
    hit = df[df["match_id"] == match_id]
    if hit.empty:
        return None
    row = hit.iloc[0]
    home, away = str(row["home_team"]), str(row["away_team"])
    past = df[(df["home_team"].astype(str) == home) & (df["away_team"].astype(str) == away)
              & (df["date"] < row["date"])].sort_values("date", ascending=False)
    ctx = {k: _s(row.get(k)) for k in ("h_prev_opp", "h_next_opp", "a_prev_opp", "a_next_opp")}
    rows = []
    for _, r in past.head(sample).iterrows():
        same = {k: bool(ctx[k] and _s(r.get(k)) == ctx[k]) for k in ctx}
        rows.append({"date": str(r["date"])[:10], "league": str(r["league"]),
                     "ftr": _s(r.get("ftr")), "score": f"{_i(r.get('fthg'))}-{_i(r.get('ftag'))}",
                     "htr": _s(r.get("htr")),
                     **{k: _s(r.get(k)) for k in ctx}, "same": same,
                     "same_full": same["h_prev_opp"] and same["h_next_opp"],
                     "n_same": sum(same.values())})
    return {
        "match": {"id": match_id, "date": str(row["date"])[:10], "league": str(row["league"]),
                  "home": home, "away": away, **ctx},
        "meetings": int(len(past)), "shown": rows,
        "with_same_context": int(sum(1 for r in rows if r["same_full"])),
        "verdict": FIXTURE_VERDICT,
    }


def _i(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        return "?"
