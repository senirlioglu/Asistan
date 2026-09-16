"""JSON API over the prediction files + static frontend.

    GET  /                          frontend (src/web/static/index.html)
    GET  /api/health                liveness
    GET  /api/meta                  available dates, job status, backtest verdict
    GET  /api/day/{date}            matches of one prediction file with per-match details
    GET  /api/analogues/{date}/{id} the analogue list of one match (?k=25..500)
    POST /api/refresh               start download -> build -> today (header X-Admin-Key when FO_ADMIN_KEY is set)

Numbers that are NaN in the CSV become null in JSON; the frontend treats null as "unknown".
"""

from __future__ import annotations

import datetime as dt
import json
import math
import os
from functools import lru_cache
from pathlib import Path
from typing import Any

import pandas as pd
from fastapi import FastAPI, Header, HTTPException, Query
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from ..config import load_settings
from ..logging_setup import get_logger
from ..pipeline.jobs import is_running, read_status, start_background
from .live import ESPN_LEAGUES

log = get_logger("web.api")
STATIC = Path(__file__).resolve().parent / "static"
settings = load_settings()
RESULTS = settings.results_dir

LEAGUE_TR = {
    "E0": "İngiltere · Premier Lig", "E1": "İngiltere · Championship", "SP1": "İspanya · La Liga", "SP2": "İspanya · Segunda",
    "I1": "İtalya · Serie A", "I2": "İtalya · Serie B", "D1": "Almanya · Bundesliga", "D2": "Almanya · 2. Bundesliga",
    "F1": "Fransa · Ligue 1", "F2": "Fransa · Ligue 2", "N1": "Hollanda · Eredivisie", "P1": "Portekiz · Primeira Liga",
    "B1": "Belçika · Pro League", "T1": "Türkiye · Süper Lig", "G1": "Yunanistan · Süper Lig", "SC0": "İskoçya · Premiership",
    "E2": "İngiltere · League One", "E3": "İngiltere · League Two", "EC": "İngiltere · National League",
    "SC1": "İskoçya · Championship", "SC2": "İskoçya · League One", "SC3": "İskoçya · League Two",
    "ARG": "Arjantin · Liga Profesional", "AUT": "Avusturya · Bundesliga", "BRA": "Brezilya · Série A", "CHN": "Çin · Süper Lig",
    "DNK": "Danimarka · Superliga", "FIN": "Finlandiya · Veikkausliiga", "IRL": "İrlanda · Premier Division", "JPN": "Japonya · J1 Ligi",
    "MEX": "Meksika · Liga MX", "NOR": "Norveç · Eliteserien", "POL": "Polonya · Ekstraklasa", "ROU": "Romanya · Superliga",
    "RUS": "Rusya · Premier Lig", "SWE": "İsveç · Allsvenskan", "SWZ": "İsviçre · Süper Lig",
    "USA": "ABD · MLS",
}

app = FastAPI(title="football-odds", docs_url=None, redoc_url=None)


# --------------------------------------------------------------------------- helpers
def _num(v: Any) -> float | None:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(f) or math.isinf(f) else round(f, 3)


def _str(v: Any) -> str:
    return "" if v is None or (isinstance(v, float) and math.isnan(v)) else str(v)


def _load_table(stamp: str) -> pd.DataFrame:
    path = RESULTS / f"{stamp}_predictions.csv"
    if not path.exists():
        raise HTTPException(404, f"no predictions for {stamp}")
    return pd.read_csv(path)


@lru_cache(maxsize=4)
def _all_matches_cached(key: tuple) -> pd.DataFrame:
    """Every prediction file, one row per match. A match analysed on several run days keeps the
    newest analysis; `stamp` says which file (and therefore which analogue file) it came from."""
    frames = []
    for name, _ in key:
        df = pd.read_csv(RESULTS / f"{name}_predictions.csv")
        df["stamp"] = name
        frames.append(df)
    if not frames:
        return pd.DataFrame()
    df = pd.concat(frames, ignore_index=True)
    df = df.sort_values("stamp").drop_duplicates("match_id", keep="last").reset_index(drop=True)
    # Football-Data kick-off times are UK local time -> convert to Turkey (UTC+3); a late kick-off
    # can roll into the next Turkish calendar day, so the Turkish date is what the site groups by
    tr = [_to_turkey(_str(d), _str(t)) for d, t in zip(df["date"], df.get("time", pd.Series([""] * len(df))))]
    df["date_tr"] = [x[0] for x in tr]
    df["time_tr"] = [x[1] for x in tr]
    return df


def _to_turkey(date_str: str, time_str: str) -> tuple[str, str]:
    """('2026-09-14', '20:00' UK) -> ('2026-09-14', '22:00'). Missing time -> same date, ''."""
    import datetime as _dt
    from zoneinfo import ZoneInfo

    if not date_str or not time_str:
        return date_str, ""
    try:
        naive = _dt.datetime.strptime(f"{date_str[:10]} {time_str[:5]}", "%Y-%m-%d %H:%M")
    except ValueError:
        return date_str[:10], ""
    local = naive.replace(tzinfo=ZoneInfo("Europe/London")).astimezone(ZoneInfo("Europe/Istanbul"))
    return local.date().isoformat(), local.strftime("%H:%M")


def _all_matches() -> pd.DataFrame:
    key = tuple(sorted((p.name[:10], p.stat().st_mtime) for p in RESULTS.glob("*_predictions.csv")))
    return _all_matches_cached(key)


def _dates() -> list[str]:
    """Match dates (not run dates), ascending."""
    df = _all_matches()
    return sorted(df["date_tr"].astype(str).unique().tolist()) if not df.empty else []


def _load_details(stamp: str) -> dict:
    p = RESULTS / f"{stamp}_details.json"
    return json.loads(p.read_text()) if p.exists() else {"matches": {}}


@lru_cache(maxsize=8)
def _load_analogues(stamp: str, mtime: float) -> pd.DataFrame:
    p = RESULTS / "analogues" / f"{stamp}_analogues.parquet"
    return pd.read_parquet(p) if p.exists() else pd.DataFrame()


def _analogues(stamp: str) -> pd.DataFrame:
    p = RESULTS / "analogues" / f"{stamp}_analogues.parquet"
    return _load_analogues(stamp, p.stat().st_mtime if p.exists() else 0.0)


def _match_payload(row: pd.Series, det: dict) -> dict:
    out = {
        "id": _str(row["match_id"]), "stamp": _str(row.get("stamp")),
        "league": _str(row["league"]), "league_name": LEAGUE_TR.get(_str(row["league"]), _str(row["league"])),
        # date/time are Turkey local (converted from Football-Data's UK time); the originals stay as *_uk
        "date": _str(row.get("date_tr")) or _str(row["date"]), "time": _str(row.get("time_tr")),
        "date_uk": _str(row["date"]), "time_uk": _str(row.get("time")),
        "home": _str(row["home"]), "away": _str(row["away"]),
        "n": int(row["n"]), "n_eff": _num(row.get("n_eff")), "confidence": _str(row["confidence"]), "signal": _str(row["signal"]),
        "signal_outcome": _str(row.get("signal_outcome")) or "home",
        "avg_sim": _num(row.get("avg_similarity")), "median_sim": _num(row.get("median_similarity")), "min_sim": _num(row.get("min_similarity")),
        "over25": _num(row.get("over25")), "under25": _num(row.get("under25")), "btts": _num(row.get("btts")),
        "avg_goals": _num(row.get("avg_goals")), "market_over25": _num(row.get("market_over25")),
        "live_available": _str(row["league"]) in ESPN_LEAGUES,  # False => no in-play score source; result comes next morning
        "odds_ou": {"over": _num(row.get("odds_o25")), "under": _num(row.get("odds_u25"))},
    }
    for grp, cols in (("odds", "odds"), ("market", "market"), ("hist", "hist"), ("adj", "adj"), ("edge", "edge"), ("fair", "fair")):
        out[grp] = {k: _num(row.get(f"{cols}_{k}")) for k in ("h", "d", "a")}
    out["ci"] = {k: [_num(row.get(f"ci_{k}_lo")), _num(row.get(f"ci_{k}_hi"))] for k in ("h", "d", "a")}
    out["scorelines"] = det.get("scorelines", {})
    out["goals_dist"] = det.get("goals_dist", {})
    out["scopes"] = det.get("scopes", {})
    out["tolerance"] = det.get("tolerance", {})
    out["htft"] = det.get("htft", {})
    out["halves"] = {k: (_num(v) if k != "n" else v) for k, v in (det.get("halves") or {}).items()}
    ht = det.get("ht", {}) or {}
    out["ht"] = {k: _num(ht.get(k)) for k in ("home", "draw", "away")} | {"n": ht.get("n")}
    return out


# --------------------------------------------------------------------------- routes
@app.get("/api/health")
@app.get("/_stcore/health")  # legacy path used by the Streamlit-era Railway healthcheck
def health() -> dict:
    return {"ok": True}


@app.get("/api/meta")
def meta() -> dict:
    status = read_status(settings)
    status["running"] = bool(is_running(settings) or status.get("state") == "running")
    bt_path = RESULTS / "backtest" / "selected_params.json"
    bt = json.loads(bt_path.read_text()) if bt_path.exists() else {}
    backtest = {k: bt.get(k) for k in ("backtest_ok", "significant_improvement", "test_seasons", "n_test_matches",
                                        "brier_market", "brier_adj", "brier_adj_p_value", "k", "feature_set", "metric")}
    import datetime as _dt
    return {"dates": _dates(), "today": _dt.date.today().isoformat(), "status": status, "backtest": backtest,
            "days_ahead": int(os.environ.get("FO_DAYS_AHEAD", "7")),
            "admin_required": bool(os.environ.get("FO_ADMIN_KEY", "")), "daily_utc": os.environ.get("FO_DAILY_UTC", "06:30")}


@app.get("/api/day/{date}")
def day(date: str) -> dict:
    """All analysed matches played on `date` (a match date, not a run date)."""
    df = _all_matches()
    table = df[df["date_tr"].astype(str) == date] if not df.empty else df
    if table.empty:
        raise HTTPException(404, f"no analysed matches on {date}")
    details_by_stamp: dict[str, dict] = {}
    matches = []
    for _, row in table.iterrows():
        stamp = _str(row["stamp"])
        if stamp not in details_by_stamp:
            details_by_stamp[stamp] = _load_details(stamp).get("matches", {})
        matches.append(_match_payload(row, details_by_stamp[stamp].get(_str(row["match_id"]), {})))
    matches.sort(key=lambda m: (m["date"], m["time"], m["league_name"]))
    return {"date": date, "matches": matches}


@app.get("/api/analogues/{stamp}/{match_id}")
def analogues(stamp: str, match_id: str, k: int = Query(50, ge=1, le=500)) -> dict:
    an = _analogues(stamp)
    if an.empty:
        return {"rows": []}
    sub = an[an["fixture_id"] == match_id].sort_values("distance").head(k)
    # the fixture's own teams: analogues are chosen by odds profile only, so a row involving one of
    # these teams is a coincidence — it is flagged so the reader can see how many there are
    teams: set[str] = set()
    try:
        table = _load_table(stamp)
        hit = table[table["match_id"].astype(str) == match_id]
        if not hit.empty:
            teams = {_str(hit.iloc[0]["home"]), _str(hit.iloc[0]["away"])}
    except HTTPException:
        pass
    rows = []
    for _, r in sub.iterrows():
        home, away = _str(r["home_team"]), _str(r["away_team"])
        rows.append({
            "date": pd.Timestamp(r["date"]).strftime("%Y-%m-%d"), "league": _str(r["league"]),
            "league_name": LEAGUE_TR.get(_str(r["league"]), _str(r["league"])), "home": home, "away": away,
            "odds": [_num(r["cons_h"]), _num(r["cons_d"]), _num(r["cons_a"])], "sim": _num(r["similarity"]),
            "result": _str(r["ftr"]), "score": _str(r["score"]), "over25": _str(r["ou25"]) == "Over", "btts": _str(r["btts"]) == "Yes",
            "years_old": _num(r.get("years_old")), "same_team": bool(teams & {home, away}),
            "ht_score": _str(r.get("ht_score")), "htft": _str(r.get("htft")),
        })
    counts = sub["ftr"].value_counts(normalize=True).reindex(["H", "D", "A"]).fillna(0) * 100
    return {"rows": rows, "share": {"h": round(float(counts["H"]), 1), "d": round(float(counts["D"]), 1), "a": round(float(counts["A"]), 1)},
            "same_team_count": int(sum(r["same_team"] for r in rows)), "teams": sorted(teams)}


HISTORY_COLS = ["date", "league", "season", "home_team", "away_team", "cons_h", "cons_d", "cons_a", "p_home", "p_draw", "p_away",
                "ftr", "fthg", "ftag", "hthg", "htag", "result_code", "total_goals"]


@lru_cache(maxsize=2)
def _history_cached(mtime: float) -> pd.DataFrame:
    import pyarrow.parquet as pq

    p = settings.processed_dir / "matches.parquet"
    present = set(pq.read_schema(p).names)
    df = pd.read_parquet(p, columns=[c for c in HISTORY_COLS if c in present])
    for c in ("hthg", "htag"):
        if c not in df.columns:
            df[c] = pd.NA
    df["date"] = pd.to_datetime(df["date"])
    return df


def _history() -> pd.DataFrame | None:
    p = settings.processed_dir / "matches.parquet"
    if not p.exists():
        return None
    return _history_cached(p.stat().st_mtime)


def _wilson(p: float, n: int, z: float = 1.96) -> tuple[float, float]:
    if n <= 0:
        return (float("nan"), float("nan"))
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (max(0.0, c - h), min(1.0, c + h))


def _row_payload(r: pd.Series, perspective: str | None = None) -> dict:
    out = {"date": r["date"].strftime("%Y-%m-%d"), "league": _str(r["league"]), "league_name": LEAGUE_TR.get(_str(r["league"]), _str(r["league"])),
           "home": _str(r["home_team"]), "away": _str(r["away_team"]), "odds": [_num(r["cons_h"]), _num(r["cons_d"]), _num(r["cons_a"])],
           "result": _str(r["ftr"]), "score": f"{int(r['fthg'])}-{int(r['ftag'])}" if pd.notna(r["fthg"]) else "",
           "p": [_num(100 * r["p_home"]), _num(100 * r["p_draw"]), _num(100 * r["p_away"])]}
    if perspective:
        at_home = _str(r["home_team"]) == perspective
        res = _str(r["ftr"])
        out["venue"] = "ev" if at_home else "dep"
        out["outcome"] = "G" if res == ("H" if at_home else "A") else ("B" if res == "D" else "M")
        out["p_team"] = _num(100 * (r["p_home"] if at_home else r["p_away"]))
    return out


def _team_record(hist: pd.DataFrame, team: str, p_today: float, as_of: pd.Timestamp, tol: float = 0.05, limit: int = 15) -> dict:
    mine = hist[((hist["home_team"] == team) | (hist["away_team"] == team)) & (hist["date"] < as_of)]
    if mine.empty:
        return {"team": team, "n_total": 0, "n_similar": 0, "rows": []}
    at_home = mine["home_team"] == team
    p_team = mine["p_home"].where(at_home, mine["p_away"])
    sim = mine[(p_team - p_today).abs() <= tol].sort_values("date", ascending=False)
    res = sim["ftr"].to_numpy()
    home_mask = (sim["home_team"] == team).to_numpy()
    wins = ((res == "H") & home_mask) | ((res == "A") & ~home_mask)
    draws = res == "D"
    n = int(len(sim))
    w = float(wins.mean()) if n else float("nan")
    lo, hi = _wilson(w, n) if n else (float("nan"), float("nan"))
    return {
        "team": team, "n_total": int(len(mine)), "n_similar": n, "p_today": round(100 * p_today, 1), "tolerance_pp": round(100 * tol),
        "win_pct": _num(100 * w) if n else None, "draw_pct": _num(100 * float(draws.mean())) if n else None,
        "loss_pct": _num(100 * float(1 - wins.mean() - draws.mean())) if n else None,
        "ci": [_num(100 * lo), _num(100 * hi)] if n else None,
        "avg_goals": _num(float(sim["total_goals"].mean())) if n else None,
        "first_season": _str(mine["season"].min()), "rows": [_row_payload(r, team) for _, r in sim.head(limit).iterrows()],
    }


@app.get("/api/teams/{stamp}/{match_id}")
def teams(stamp: str, match_id: str) -> dict:
    """The fixture's own teams: head-to-head history and each team's record when priced like today."""
    hist = _history()
    if hist is None:
        raise HTTPException(503, "veritabanı henüz kurulmadı")
    table = _load_table(stamp)
    hit = table[table["match_id"].astype(str) == match_id]
    if hit.empty:
        raise HTTPException(404, "maç bulunamadı")
    row = hit.iloc[0]
    home, away = _str(row["home"]), _str(row["away"])
    as_of = pd.Timestamp(stamp)
    h2h = hist[(((hist["home_team"] == home) & (hist["away_team"] == away)) | ((hist["home_team"] == away) & (hist["away_team"] == home)))
               & (hist["date"] < as_of)].sort_values("date", ascending=False)
    h2h_rows = [_row_payload(r, home) for _, r in h2h.head(12).iterrows()]
    n_h2h = int(len(h2h))
    home_wins = sum(1 for r in h2h_rows if r["outcome"] == "G")
    return {
        "home": _team_record(hist, home, float(row["market_h"]) / 100, as_of),
        "away": _team_record(hist, away, float(row["market_a"]) / 100, as_of),
        "h2h": {"n": n_h2h, "rows": h2h_rows, "home_wins": home_wins, "draws": sum(1 for r in h2h_rows if r["outcome"] == "B"),
                "away_wins": sum(1 for r in h2h_rows if r["outcome"] == "M"), "shown": len(h2h_rows)},
    }


@app.get("/api/live/{date}")
def live(date: str) -> dict:
    """Live minute/score (ESPN, best effort) or the final result from the database, per match id."""
    from .live import live_for_fixture, status_label_tr

    df = _all_matches()
    table = df[df["date_tr"].astype(str) == date] if not df.empty else df
    if table.empty:
        return {"date": date, "live": {}, "any_live": False}
    hist = _history()
    out: dict[str, dict] = {}
    any_live = False
    for _, row in table.iterrows():
        mid = _str(row["match_id"])
        info: dict | None = None
        # 1) result already in the processed database (Football-Data published it)
        if hist is not None:
            hit = hist[(hist["league"] == _str(row["league"])) & (hist["home_team"] == _str(row["home"])) & (hist["away_team"] == _str(row["away"]))
                       & (hist["date"].dt.strftime("%Y-%m-%d") == _str(row["date"])[:10])]
            if not hit.empty and hit.iloc[0]["result_code"] is not None and str(hit.iloc[0]["ftr"]) in ("H", "D", "A"):
                r = hit.iloc[0]
                info = {"home_score": int(r["fthg"]), "away_score": int(r["ftag"]), "state": "post", "detail": "FT", "clock": "", "period": 2,
                        "ht_home": int(r["hthg"]) if pd.notna(r.get("hthg")) else None, "ht_away": int(r["htag"]) if pd.notna(r.get("htag")) else None,
                        "source": "football-data"}
        # 2) otherwise ESPN (today's and recent matches)
        if info is None:
            info = live_for_fixture(_str(row["league"]), _str(row["date"])[:10], _str(row["home"]), _str(row["away"]))
        if info:
            info["label"] = status_label_tr(info)
            any_live = any_live or info.get("state") == "in"
            out[mid] = info
    return {"date": date, "live": out, "any_live": any_live, "fetched_at": dt.datetime.now(dt.timezone.utc).isoformat()}


@app.get("/api/scorecard")
def scorecard(from_: str | None = Query(default=None, alias="from"), to: str | None = None, leagues: str | None = None) -> dict:
    """Who sat closer to what happened, market or history, for the played matches of a date range (Turkey dates)."""
    from ..pipeline.scorecard import MAX_RANGE_DAYS, TR, build_scorecard, load_prediction_rows, realised_results

    yesterday = (dt.datetime.now(TR).date() - dt.timedelta(days=1)).isoformat()
    date_from, date_to = from_ or yesterday, to or from_ or yesterday
    try:
        d0, d1 = dt.date.fromisoformat(date_from), dt.date.fromisoformat(date_to)
    except ValueError:
        raise HTTPException(400, "tarih biçimi YYYY-AA-GG olmalı")
    if d1 < d0:
        d0, d1 = d1, d0
    if (d1 - d0).days > MAX_RANGE_DAYS:
        raise HTTPException(400, f"en fazla {MAX_RANGE_DAYS} günlük aralık")
    wanted = {x.strip() for x in leagues.split(",") if x.strip()} if leagues else None
    rows = load_prediction_rows(RESULTS)
    rows = [r for r in rows if d0.isoformat() <= r["date"] <= d1.isoformat()]
    results = realised_results(settings, rows, _history())
    return build_scorecard(rows, results, d0.isoformat(), d1.isoformat(), wanted, LEAGUE_TR)


@app.get("/api/paper")
def paper(from_: str | None = Query(default=None, alias="from"), to: str | None = None, leagues: str | None = None,
          edge: float = Query(default=3.0, ge=0.5, le=15.0)) -> dict:
    """Paper trading: flat-stake results of fixed strategies over a date range (Turkey dates)."""
    from ..pipeline.paper import simulate
    from ..pipeline.scorecard import MAX_RANGE_DAYS, TR, load_prediction_rows, realised_results

    yesterday = (dt.datetime.now(TR).date() - dt.timedelta(days=1)).isoformat()
    date_from, date_to = from_ or yesterday, to or from_ or yesterday
    try:
        d0, d1 = dt.date.fromisoformat(date_from), dt.date.fromisoformat(date_to)
    except ValueError:
        raise HTTPException(400, "tarih biçimi YYYY-AA-GG olmalı")
    if d1 < d0:
        d0, d1 = d1, d0
    if (d1 - d0).days > MAX_RANGE_DAYS:
        raise HTTPException(400, f"en fazla {MAX_RANGE_DAYS} günlük aralık")
    wanted = {x.strip() for x in leagues.split(",") if x.strip()} if leagues else None
    rows = [r for r in load_prediction_rows(RESULTS) if d0.isoformat() <= r["date"] <= d1.isoformat()]
    all_leagues = sorted({r["league"] for r in rows})
    if wanted:
        rows = [r for r in rows if r["league"] in wanted]
    results = realised_results(settings, rows, _history())
    out = simulate(rows, results, edge, LEAGUE_TR)
    out.update({"from": d0.isoformat(), "to": d1.isoformat(), "n_matches": len(rows), "n_finished": sum(1 for r in rows if r["id"] in results),
                "leagues": [{"code": lg, "name": LEAGUE_TR.get(lg, lg)} for lg in all_leagues]})
    return out


# --------------------------------------------------------------------------- coupons (Oyun)
def _rows_by_id(date_from: str | None = None, date_to: str | None = None) -> dict[str, dict]:
    from ..pipeline.scorecard import load_prediction_rows

    rows = load_prediction_rows(RESULTS)
    if date_from:
        rows = [r for r in rows if r["date"] >= date_from]
    if date_to:
        rows = [r for r in rows if r["date"] <= date_to]
    return {r["id"]: r for r in rows}


@app.get("/api/coupons")
def coupons_list() -> dict:
    from ..pipeline import coupons as cp
    from ..pipeline.scorecard import realised_results

    items = cp.load(settings)
    if not items:
        return {"coupons": []}
    by_id = _rows_by_id()
    needed = {p["match_id"] for c in items for p in c["picks"]}
    rows = [by_id[m] for m in needed if m in by_id]
    results = realised_results(settings, rows, _history())
    out = [cp.evaluate(c, results) for c in items]
    out.sort(key=lambda c: c["created_at"], reverse=True)
    return {"coupons": out}


@app.post("/api/coupons")
def coupons_create(payload: dict) -> dict:
    from ..pipeline import coupons as cp

    picks = payload.get("picks") or []
    by_id = _rows_by_id()
    try:
        coupon = cp.build_coupon(picks, by_id, str(payload.get("label") or ""))
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    cp.attach_prices(coupon, by_id)
    items = cp.load(settings)
    items.append(coupon)
    cp.save(settings, items)
    return {"ok": True, "coupon": cp.evaluate(coupon, {})}


@app.delete("/api/coupons/{coupon_id}")
def coupons_delete(coupon_id: str) -> dict:
    from ..pipeline import coupons as cp

    items = cp.load(settings)
    keep = [c for c in items if c["id"] != coupon_id]
    if len(keep) == len(items):
        raise HTTPException(404, "kupon bulunamadı")
    cp.save(settings, keep)
    return {"ok": True}


# --------------------------------------------------------------------------- notes over nesine odds (Notlar)
_NOTES_INDEX: dict[str, Any] = {"mtime": None, "index": None}


def _team_index():
    from ..nesine.history import TeamIndex, load_history

    p = settings.processed_dir / "matches.parquet"
    if not p.exists():
        return None
    mtime = p.stat().st_mtime
    if _NOTES_INDEX["index"] is None or _NOTES_INDEX["mtime"] != mtime:
        df = load_history(settings)
        _NOTES_INDEX.update(mtime=mtime, index=TeamIndex(df) if df is not None else None)
    return _NOTES_INDEX["index"]


def _ours_lookup(matches: list[dict]) -> dict[int, dict]:
    """nesine match code -> our analysed fixture (same Turkey date, closest team names)."""
    from ..web.live import name_score

    df = _all_matches()
    if df.empty:
        return {}
    by_date: dict[str, list] = {}
    for _, r in df.iterrows():
        by_date.setdefault(str(r["date_tr"]), []).append(r)
    out: dict[int, dict] = {}
    for m in matches:
        best, best_s = None, 0.0
        for r in by_date.get(m["date"], []):
            s = (name_score(m["home"], str(r["home"])) + name_score(m["away"], str(r["away"]))) / 2
            if s > best_s:
                best, best_s = r, s
        if best is not None and best_s >= 0.6:
            out[m["code"]] = {"id": _str(best["match_id"]), "stamp": _str(best.get("stamp")), "league_name": LEAGUE_TR.get(_str(best["league"]), _str(best["league"])),
                              "market": {k: _num(best.get(f"market_{k}")) for k in ("h", "d", "a")}, "adj": {k: _num(best.get(f"adj_{k}")) for k in ("h", "d", "a")},
                              "over25": _num(best.get("over25")), "n": int(best["n"]), "signal": _str(best["signal"])}
    return out


def _nesine_payload(m: dict, hits: list, store: dict) -> dict:
    """One bulletin match as the page consumes it: odds, the notes it fires, and how its prices moved."""
    from ..nesine import watcher

    return {**{k: v for k, v in m.items() if k != "korner"}, "korner_n": len(m.get("korner") or {}),
            "hits": hits, "moves": watcher.movement(store, m["code"], changed_only=True)}


def _nesine_brief(date_tr: str, home: str, away: str) -> dict | None:
    """The bulletin entry for one of OUR fixtures (reverse of `_ours_lookup`), or None when it is not quoted."""
    from ..nesine import watcher
    from ..nesine.bulletin import load_matches
    from ..nesine.history import team_hits
    from ..nesine.rules import evaluate
    from .live import name_score

    try:
        matches, meta = load_matches(settings)
    except Exception as exc:  # noqa: BLE001 - the analysis must open even when nesine is unreachable
        return {"error": str(exc)}
    best, best_s = None, 0.0
    for m in matches:
        if m["date"] != date_tr:
            continue
        s = (name_score(home, m["home"]) + name_score(away, m["away"])) / 2
        if s > best_s:
            best, best_s = m, s
    if best is None or best_s < 0.6:
        return None
    index = _team_index()
    hits = evaluate(best, team_hits(best, index) if index is not None else {})
    out = _nesine_payload(best, hits, watcher.load_store(settings))
    return {**out, "name_score": round(best_s, 2), "fetched_at": meta.get("fetched_at"), "watch": watcher.status()}


@app.get("/api/match/{match_id}")
def match_detail(match_id: str) -> dict:
    """Everything the site can say about one analysed fixture: our analysis plus its nesine odds and notes.

    The Oyun tab opens this from a coupon row, where only the match id is at hand."""
    df = _all_matches()
    sub = df[df["match_id"].astype(str) == match_id] if not df.empty else df
    if sub.empty:
        raise HTTPException(404, "maç bulunamadı")
    row = sub.iloc[-1]
    det = _load_details(_str(row["stamp"])).get("matches", {}).get(match_id, {})
    payload = _match_payload(row, det)
    return {"match": payload, "nesine": _nesine_brief(payload["date"], payload["home"], payload["away"])}


@app.get("/api/twins/{match_id}")
def twins(match_id: str, k: int = Query(50, ge=5, le=500), side: str = Query("home", pattern="^(home|away)$")) -> dict:
    """The matches most like this one on form, strength and price — the research engine, not a tip.

    Everything it reports is paired with what the market said about those same twins; the model
    comparison (`results/backtest/models.json`) found that turning this into a prediction does not
    beat the price, and the page says so."""
    from ..patterns import service

    out = service.twins_for(settings, match_id, k=k, side=side)
    if out is None:
        raise HTTPException(404, "bu maç için durum tablosu hazır değil (günlük iş henüz işlemedi)")
    return out


@app.get("/api/hareket/{code}")
def hareket(code: int, paths: str = Query("ms.1,ms.X,ms.2"), days: int = Query(4, ge=1, le=14)) -> dict:
    """What one nesine match's price did on the way to kick-off, in margin-free probability.

    Answers only about matches the archive was running for — it started on 15 September 2026 — and
    reports how much of the run-up it actually saw next to every verdict, so a STABLE produced
    during an outage can be read as one."""
    from ..nesine import movement

    want = tuple(p.strip() for p in paths.split(",") if p.strip())[:8]
    return movement.for_match(settings, code, paths=want, cfg=movement.config_from_env(), days=days)


@app.get("/api/patterns/{match_id}")
def patterns(match_id: str, side: str = Query("home", pattern="^(home|away)$"),
             approx: int = Query(0, ge=0, le=2)) -> dict:
    """What happened after this same form pattern — for this club, for everybody, and for teams that
    were of comparable strength at the time. `approx` lets that many of the five results differ, so
    the exact and the near count can be read next to each other."""
    from ..patterns import service

    out = service.patterns_for(settings, match_id, side=side, approx=approx)
    if out is None:
        raise HTTPException(404, "bu maç için durum tablosu ya da form dizisi hazır değil")
    return out


@app.get("/api/kombine/{match_id}")
def kombine(match_id: str, side: str = Query("home", pattern="^(home|away)$"),
            approx: int = Query(1, ge=0, le=2), length: int = Query(3, ge=2, le=5)) -> dict:
    """TEAM A x TEAM B: both teams' states at once, one condition at a time.

    Each row adds a condition to the row above it and reports the outcome against what the market
    charged for those same matches, so the reader can see which condition moved the number and which
    only shrank the sample. The defaults (three results, one allowed to differ) were measured: with
    exact five-match sequences on both sides the median sample reaches zero before the opponent is
    even described."""
    from ..patterns import service

    out = service.combined_for(settings, match_id, side=side, approx=approx, length=length)
    if out is None:
        raise HTTPException(404, "bu maç için durum tablosu ya da form dizisi hazır değil")
    return out


@app.get("/api/research")
def research() -> dict:
    """The offline research results: the notebook notes, the model comparison, the pattern scan."""
    from ..patterns import service

    from ..nesine import forward

    files = service.research_files(settings)
    df = service.frame(settings)
    try:
        files["forward"] = forward.summary(settings)
    except Exception as exc:  # noqa: BLE001 - a young forward test must not take the tab down
        log.warning("forward summary failed: %s", exc)
        files["forward"] = None
    files["state"] = {"matches": int(len(df)) if df is not None else 0,
                      "from": str(df["date"].min())[:10] if df is not None and len(df) else None,
                      "to": str(df["date"].max())[:10] if df is not None and len(df) else None}
    return files


@app.get("/api/notlar")
def notlar(date: str | None = None, refresh: bool = False) -> dict:
    """nesine.com bulletin filtered by the user's notes: every football match with the notes it satisfies."""
    from ..nesine import watcher
    from ..nesine.bulletin import load_matches
    from ..nesine.history import cached_backtest, team_hits
    from ..nesine.rules import RULES, evaluate

    watcher.start_if_enabled(settings)     # odds drift towards kick-off: keep a refresher running
    try:
        matches, meta = watcher.refresh_once(settings) if refresh else load_matches(settings)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(502, f"nesine bülteni alınamadı: {exc}")
    meta = {**meta, "watch": watcher.status()}
    dates = sorted({m["date"] for m in matches if m["date"]})
    today = dt.date.today().isoformat()
    date = date or (today if today in dates else (dates[0] if dates else None))
    if date:
        matches = [m for m in matches if m["date"] == date]
    index = _team_index()
    ours = _ours_lookup(matches)
    store = watcher.load_store(settings)
    out_matches = []
    for m in matches:
        hh = team_hits(m, index) if index is not None else {}
        out_matches.append({**_nesine_payload(m, evaluate(m, hh), store), "ours": ours.get(m["code"])})
    rules = [{k: v for k, v in r.items() if k != "fn"} | {"applied": r.get("applied", True) and (r.get("fn") is not None or r["id"] in ("n2", "n14"))} for r in RULES]
    return {"meta": meta, "dates": dates, "date": date, "rules": rules, "history": cached_backtest(settings),
            "matches": out_matches, "n_hits": sum(1 for m in out_matches if m["hits"])}


def _analogue_rows(an: pd.DataFrame, teams: set[str], k: int) -> dict:
    sub = an.sort_values("distance").head(k)
    rows = []
    for _, r in sub.iterrows():
        home, away = _str(r["home_team"]), _str(r["away_team"])
        rows.append({
            "date": pd.Timestamp(r["date"]).strftime("%Y-%m-%d"), "league": _str(r["league"]),
            "league_name": LEAGUE_TR.get(_str(r["league"]), _str(r["league"])), "home": home, "away": away,
            "odds": [_num(r["cons_h"]), _num(r["cons_d"]), _num(r["cons_a"])], "sim": _num(r["similarity"]),
            "result": _str(r["ftr"]), "score": _str(r["score"]), "over25": _str(r["ou25"]) == "Over", "btts": _str(r["btts"]) == "Yes",
            "years_old": _num(r.get("years_old")), "same_team": bool(teams & {home, away}),
            "ht_score": _str(r.get("ht_score")), "htft": _str(r.get("htft")),
        })
    counts = sub["ftr"].value_counts(normalize=True).reindex(["H", "D", "A"]).fillna(0) * 100
    return {"rows": rows, "share": {"h": round(float(counts["H"]), 1), "d": round(float(counts["D"]), 1), "a": round(float(counts["A"]), 1)},
            "same_team_count": int(sum(r["same_team"] for r in rows)), "teams": sorted(teams)}


@app.get("/api/nesine-analiz")
def nesine_analiz(code: int, k: int = Query(25, ge=1, le=500)) -> dict:
    """Our own analogue analysis of one nesine match, priced with nesine's odds."""
    from ..nesine.analyze import analyse
    from ..nesine.bulletin import load_matches

    matches, meta = load_matches(settings)
    hit = next((m for m in matches if m.get("code") == code), None)
    if hit is None:
        raise HTTPException(404, "maç bültende yok (oynanmış ya da kaldırılmış olabilir)")
    try:
        res = analyse(settings, hit)
    except FileNotFoundError:
        raise HTTPException(503, "veritabanı henüz kurulmadı")
    if res is None:
        raise HTTPException(422, "bu maçın maç sonucu oranları eksik, analiz edilemiyor")
    row = res["summary"].copy()
    row["stamp"] = ""
    row["date_tr"], row["time_tr"] = hit["date"], hit["time"]
    payload = _match_payload(row, res["details"])
    payload.update({"home": hit["home"], "away": hit["away"], "league": "NES", "league_name": hit["league"],
                    "live_available": False, "nesine_code": hit["code"], "source": "nesine",
                    "feature_set": res["feature_set"], "overround": _num(res["overround"]),
                    "odds": {k2: _num(v) for k2, v in zip(("h", "d", "a"), (hit["ms"].get("1"), hit["ms"].get("X"), hit["ms"].get("2")))},
                    "odds_ou": {"over": _num((hit.get("o25") or {}).get("ust")), "under": _num((hit.get("o25") or {}).get("alt"))}})
    # our teams' own history, when nesine's spelling resolves to a team we store
    teams_payload = None
    index = _team_index()
    hist = _history()
    if index is not None and hist is not None:
        h, a = index.resolve(hit["home"]), index.resolve(hit["away"])
        if h and a:
            as_of = pd.Timestamp(hit["date"]) if hit["date"] else pd.Timestamp(dt.date.today())
            h2h = hist[(((hist["home_team"] == h) & (hist["away_team"] == a)) | ((hist["home_team"] == a) & (hist["away_team"] == h)))
                       & (hist["date"] < as_of)].sort_values("date", ascending=False)
            h2h_rows = [_row_payload(r, h) for _, r in h2h.head(12).iterrows()]
            teams_payload = {
                "home": _team_record(hist, h, float(payload["market"]["h"]) / 100, as_of),
                "away": _team_record(hist, a, float(payload["market"]["a"]) / 100, as_of),
                "h2h": {"n": int(len(h2h)), "rows": h2h_rows, "home_wins": sum(1 for r in h2h_rows if r["outcome"] == "G"),
                        "draws": sum(1 for r in h2h_rows if r["outcome"] == "B"), "away_wins": sum(1 for r in h2h_rows if r["outcome"] == "M"),
                        "shown": len(h2h_rows)},
                "resolved": {"home": h, "away": a},
            }
    from ..nesine import watcher
    from ..nesine.history import team_hits
    from ..nesine.rules import evaluate

    hits = evaluate(hit, team_hits(hit, index) if index is not None else {})
    nesine = {**_nesine_payload(hit, hits, watcher.load_store(settings)), "fetched_at": meta.get("fetched_at"), "watch": watcher.status()}
    return {"match": payload, "analogues": _analogue_rows(res["analogues"], {hit["home"], hit["away"]}, k), "teams": teams_payload,
            "nesine": nesine, "meta": meta}


@app.get("/robots.txt", include_in_schema=False)
def robots() -> Any:
    from fastapi.responses import PlainTextResponse

    return PlainTextResponse("User-agent: *\nDisallow: /\n")


@app.middleware("http")
async def no_index(request, call_next):
    """Private research tool: tell every crawler to stay away (the page also carries a robots meta tag)."""
    response = await call_next(request)
    response.headers["X-Robots-Tag"] = "noindex, nofollow, noarchive"
    return response


@app.get("/api/live-debug/{date}")
def live_debug(date: str) -> dict:
    """What ESPN answers for each league of the day and which fixtures matched (for diagnosing missing badges)."""
    from .live import debug_day

    df = _all_matches()
    table = df[df["date_tr"].astype(str) == date] if not df.empty else df
    if table.empty:
        raise HTTPException(404, f"no analysed matches on {date}")
    fixtures = [{"league": _str(r["league"]), "date_uk": _str(r["date"])[:10], "home": _str(r["home"]), "away": _str(r["away"])} for _, r in table.iterrows()]
    return {"date": date, "leagues": debug_day(fixtures)}


@app.get("/api/espn-raw")
def espn_raw(path: str = Query(..., description="path under site.api.espn.com/apis/site/v2/sports/soccer/ or, with host=core, sports.core.api.espn.com/v2/sports/soccer/"),
             host: str = "site", dates: str | None = None, limit: int | None = None) -> dict:
    """Read-only pass-through to ESPN's public JSON (diagnostics: which league slugs exist, what a scoreboard returns)."""
    import requests as _rq
    from .live import USER_AGENTS

    base = "https://sports.core.api.espn.com/v2/sports/soccer/" if host == "core" else "https://site.api.espn.com/apis/site/v2/sports/soccer/"
    params = {k: v for k, v in (("dates", dates), ("limit", limit)) if v is not None}
    last = None
    for ua in USER_AGENTS:
        try:
            r = _rq.get(base + path.lstrip("/"), params=params, timeout=15, headers={"User-Agent": ua})
            if r.status_code == 403:
                last = "403"
                continue
            return {"status": r.status_code, "url": r.url, "json": r.json() if r.ok else r.text[:500]}
        except Exception as exc:  # noqa: BLE001
            last = str(exc)
    raise HTTPException(502, f"espn: {last}")


@app.post("/api/refresh")
def refresh(x_admin_key: str | None = Header(default=None)) -> dict:
    required = os.environ.get("FO_ADMIN_KEY", "")
    if required and x_admin_key != required:
        raise HTTPException(401, "yönetici anahtarı yanlış")
    days = int(os.environ.get("FO_DAYS_AHEAD", "7"))
    started = start_background(settings, days=days, full_download=not (settings.processed_dir / "matches.parquet").exists())
    return {"started": started is not None, "running": True}


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC / "index.html", headers={"Cache-Control": "no-cache"})


app.mount("/static", StaticFiles(directory=str(STATIC)), name="static")
