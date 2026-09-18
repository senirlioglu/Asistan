"""nesine's bulletin as fixtures for the state table — so Pattern Lab can see the matches the
Football-Data fixture file has not published yet.

Football-Data lists a fixture only once the bookmakers' odds are in, usually two or three days
ahead and only for the 38 leagues it covers. nesine's pre-bulletin holds today's and tomorrow's
programme over every league it prices, cups and European ties included. The research engines need one thing to analyse a match: a row in the pre-match
state table (form, strength, goals, price), and `state.build` writes that row for any upcoming
fixture it is handed. This module hands it the bulletin — every match whose two clubs resolve to
clubs in our database — in the same shape the daily analysis table has, so the two sources merge into
one build. A tie between clubs of two leagues (a European night, a cup across divisions) is placed
under the code `CUP` and names each club's own league, so its standings come from its own table.

Nothing here predicts anything and nothing is folded into a club's history: an upcoming row has
no result, so it never moves a rating or a form string. Its price is nesine's, margin removed,
and the row says so (`source`), because nesine's margin is not the European average's.

The match id follows Football-Data's own scheme (league | date | home | away), so when Football-Data
publishes the same fixture the two rows can be told apart only by date when a late kick-off rolls
over the UK/Turkey midnight — the lab's picker dedups on (clubs, date ± 1) and prefers the analysed one.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json

import pandas as pd

from ..config import Settings, current_season_code
from ..logging_setup import get_logger

log = get_logger("nesine.fixtures")

META_NAME = "nesine_fixtures.json"
STAMP = "nesine"                         # the "run day" the bulletin's analysis is filed under
PRED_NAME = f"{STAMP}_predictions.csv"   # same shape as <date>_predictions.csv, read by /api/day and the match sheet
DETAILS_NAME = f"{STAMP}_details.json"
ANALOGUES_NAME = f"{STAMP}_analogues.parquet"
ANALYSIS_MAX_AGE_H = 12                  # a fixture's analysis is redone after this, or when its price moved
ODDS_MOVE = 0.03                         # relative move on any 1X2 price that makes the analysis stale
CUP = "CUP"          # the league code of a tie between clubs of two leagues (European cups, domestic cups across divisions)


def _novig(group: dict | None, keys: tuple[str, ...]) -> list[float | None]:
    if not group:
        return [None] * len(keys)
    try:
        odds = [float(group.get(k)) for k in keys]
    except (TypeError, ValueError):
        return [None] * len(keys)
    if any(o is None or o <= 1.0 for o in odds):
        return [None] * len(keys)
    inv = [1.0 / o for o in odds]
    tot = sum(inv)
    return [100.0 * v / tot for v in inv]


def _match_id(league: str, date: str, home: str, away: str) -> str:
    return hashlib.sha1(f"{league}|{date}|{home}|{away}".encode("utf-8")).hexdigest()[:16]


def nesine_fixture_table(settings: Settings, hist: pd.DataFrame | None = None,
                         matches: list[dict] | None = None, today: dt.date | None = None) -> tuple[pd.DataFrame, dict]:
    """The bulletin's matches that our database can analyse, in the daily table's shape, plus a
    side table {match_id: {code, time, league_name}} for the page."""
    from .bulletin import load_matches
    from .history import TeamIndex, load_history

    empty = pd.DataFrame(columns=["match_id", "date", "time", "league", "home", "away", "home_league", "away_league", "odds_h", "odds_d", "odds_a",
                                  "market_h", "market_d", "market_a", "market_over25", "odds_o25", "odds_u25"])
    if matches is None:
        try:
            matches, _ = load_matches(settings)
        except Exception as exc:  # noqa: BLE001 - no bulletin, no extra fixtures; never a failure of the job
            log.warning("nesine fixtures: bulletin unavailable (%s)", exc)
            return empty, {}
    if hist is None:
        hist = load_history(settings)
    if hist is None or hist.empty or not matches:
        return empty, {}
    index = TeamIndex(hist)
    # the league a club plays in now: its most recent match in the database
    long = pd.concat([hist[["home_team", "league", "date"]].rename(columns={"home_team": "team"}),
                      hist[["away_team", "league", "date"]].rename(columns={"away_team": "team"})], ignore_index=True)
    league_of = long.sort_values("date").groupby("team")["league"].last().astype(str).to_dict()
    today = today or dt.date.today()
    rows, meta, seen = [], {}, set()
    for m in matches:
        date = str(m.get("date") or "")
        if not date or date < today.isoformat():
            continue
        h, a = index.resolve(str(m.get("home", ""))), index.resolve(str(m.get("away", "")))
        if not h or not a or h == a:
            continue
        lg_h, lg_a = league_of.get(h), league_of.get(a)
        if not lg_h or not lg_a:
            continue
        league = lg_h if lg_h == lg_a else CUP          # a cup or a European tie: each club keeps its own table
        p_h, p_d, p_a = _novig(m.get("ms"), ("1", "X", "2"))
        if p_h is None:
            continue
        p_over, _ = _novig(m.get("o25"), ("ust", "alt"))
        mid = _match_id(league, date, h, a)
        if mid in seen:
            continue
        seen.add(mid)
        ms, o25 = m.get("ms") or {}, m.get("o25") or {}
        rows.append({"match_id": mid, "date": date, "time": str(m.get("time") or ""), "league": league, "home": h, "away": a,
                     "home_league": lg_h, "away_league": lg_a,
                     "odds_h": ms.get("1"), "odds_d": ms.get("X"), "odds_a": ms.get("2"),
                     "market_h": round(p_h, 2), "market_d": round(p_d, 2), "market_a": round(p_a, 2),
                     "market_over25": None if p_over is None else round(p_over, 2),
                     "odds_o25": o25.get("ust"), "odds_u25": o25.get("alt")})
        meta[mid] = {"code": m.get("code"), "time": str(m.get("time") or ""), "league_name": str(m.get("league") or ""),
                     "nesine_home": str(m.get("home", "")), "nesine_away": str(m.get("away", "")), "date": date}
    table = pd.DataFrame(rows) if rows else empty
    log.info("nesine fixtures: %d of %d bulletin matches resolve to our database", len(table), len(matches))
    return table, meta


def meta_path(settings: Settings):
    return settings.results_dir / META_NAME


def write_meta(settings: Settings, meta: dict) -> None:
    settings.results_dir.mkdir(parents=True, exist_ok=True)
    meta_path(settings).write_text(json.dumps({"season": current_season_code(), "written_at": dt.datetime.now(dt.timezone.utc).isoformat(),
                                               "matches": meta}, ensure_ascii=False), encoding="utf-8")


def read_meta(settings: Settings) -> dict:
    p = meta_path(settings)
    try:
        return (json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}).get("matches", {})
    except (OSError, json.JSONDecodeError):
        return {}


def merge_fixtures(table: pd.DataFrame | None, extra: pd.DataFrame) -> pd.DataFrame:
    """The analysed table first, then the bulletin's fixtures it does not already hold."""
    if table is None or not len(table):
        return extra
    if extra is None or not len(extra):
        return table
    have = set(table["match_id"].astype(str))
    pairs = {(str(h), str(a), str(d)[:10]) for h, a, d in zip(table["home"], table["away"], table["date"])}
    keep = [i for i, r in extra.iterrows()
            if r["match_id"] not in have and not any((r["home"], r["away"], _shift(r["date"], k)) in pairs for k in (-1, 0, 1))]
    return pd.concat([table, extra.loc[keep]], ignore_index=True, sort=False)


def _shift(date: str, days: int) -> str:
    try:
        return (dt.date.fromisoformat(str(date)[:10]) + dt.timedelta(days=days)).isoformat()
    except ValueError:
        return str(date)


# --------------------------------------------------------------------------- the bulletin, analysed

def _jsonable(v):
    """numpy scalars, NaN and timestamps into what json.dumps accepts."""
    if isinstance(v, dict):
        return {str(k): _jsonable(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [_jsonable(x) for x in v]
    if hasattr(v, "item") and not isinstance(v, (str, bytes)):
        try:
            v = v.item()
        except (ValueError, TypeError):
            pass
    if isinstance(v, float) and v != v:
        return None
    if isinstance(v, (pd.Timestamp, dt.datetime, dt.date)):
        return v.isoformat()
    return v


def _stale(prev: pd.Series, ms: dict, now: dt.datetime, max_age_h: float) -> bool:
    try:
        at = dt.datetime.fromisoformat(str(prev.get("analysed_at")))
        if at.tzinfo is None:
            at = at.replace(tzinfo=dt.timezone.utc)
    except (TypeError, ValueError):
        return True
    if (now - at).total_seconds() > max_age_h * 3600:
        return True
    for col, key in (("odds_h", "1"), ("odds_d", "X"), ("odds_a", "2")):
        try:
            a, b = float(prev.get(col)), float(ms.get(key))
        except (TypeError, ValueError):
            return True
        if a <= 0 or abs(a - b) / a > ODDS_MOVE:
            return True
    return False


def analyse_bulletin(settings: Settings, table: pd.DataFrame | None, meta: dict, matches: list[dict] | None = None,
                     now: dt.datetime | None = None, max_age_h: float = ANALYSIS_MAX_AGE_H) -> int:
    """Our own analogue analysis (the one behind the Maçlar tab) for every bulletin fixture in `table`,
    written under the stamp "nesine" in the prediction files' shape: `nesine_predictions.csv`,
    `nesine_details.json` and `analogues/nesine_analogues.parquet`. /api/day merges these rows into a
    day when Football-Data has not published that day yet, and the match sheet reads analogues and team
    records through the same endpoints as an analysed day. A fixture keeps its analysis for
    `max_age_h` hours unless its price moved; the rest is redone. Returns the number analysed afresh."""
    from .analyze import analyse
    from .bulletin import load_matches

    if table is None or not len(table):
        return 0
    if matches is None:
        matches, _ = load_matches(settings)
    by_code = {m.get("code"): m for m in matches}
    now = now or dt.datetime.now(dt.timezone.utc)
    rd = settings.results_dir
    pred_p, det_p, an_p = rd / PRED_NAME, rd / DETAILS_NAME, rd / "analogues" / ANALOGUES_NAME
    old = pd.read_csv(pred_p) if pred_p.exists() else pd.DataFrame()
    old_by_id = {str(r["match_id"]): r for _, r in old.iterrows()} if len(old) else {}
    old_details = read_details(settings)
    old_an = pd.read_parquet(an_p) if an_p.exists() else pd.DataFrame()
    rows, details, frames, n_new, n_kept = [], {}, [], 0, 0
    for _, fx in table.iterrows():
        mid = str(fx["match_id"])
        info = meta.get(mid) or {}
        hit = by_code.get(info.get("code"))
        if hit is None:
            continue
        ms = hit.get("ms") or {}
        prev = old_by_id.get(mid)
        if prev is not None and not _stale(prev, ms, now, max_age_h):
            rows.append(prev.to_dict())
            details[mid] = old_details.get(mid, {})
            if len(old_an):
                frames.append(old_an[old_an["fixture_id"].astype(str) == mid])
            n_kept += 1
            continue
        try:
            res = analyse(settings, hit)
        except Exception as exc:  # noqa: BLE001 - one bad fixture must not lose the rest
            log.warning("nesine analysis failed for %s: %s", mid, exc)
            continue
        if res is None:
            continue
        s = {k: v for k, v in res["summary"].to_dict().items() if not isinstance(v, (dict, list))}
        o25 = hit.get("o25") or {}
        s.update({"match_id": mid, "date": str(fx["date"])[:10], "time": str(info.get("time") or fx.get("time") or ""),
                  "league": str(fx["league"]), "home": str(fx["home"]), "away": str(fx["away"]),
                  "nesine_code": info.get("code"), "league_name": str(info.get("league_name") or ""), "source": STAMP,
                  "analysed_at": now.isoformat(timespec="seconds"),
                  "odds_h": ms.get("1"), "odds_d": ms.get("X"), "odds_a": ms.get("2"), "odds_o25": o25.get("ust"), "odds_u25": o25.get("alt")})
        rows.append(s)
        details[mid] = _jsonable(res["details"])
        an = res["analogues"].copy()
        an["fixture_id"] = mid
        frames.append(an)
        n_new += 1
    rd.mkdir(parents=True, exist_ok=True)
    an_p.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(pred_p, index=False)
    det_p.write_text(json.dumps({"written_at": now.isoformat(timespec="seconds"), "matches": details}, ensure_ascii=False), encoding="utf-8")
    if frames:
        pd.concat(frames, ignore_index=True).to_parquet(an_p, index=False)
    elif an_p.exists():
        an_p.unlink()
    log.info("nesine bulletin analysed: %d fresh, %d kept, %d rows -> %s", n_new, n_kept, len(rows), pred_p)
    return n_new


def read_details(settings: Settings) -> dict:
    p = settings.results_dir / DETAILS_NAME
    try:
        return (json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}).get("matches", {})
    except (OSError, json.JSONDecodeError):
        return {}
