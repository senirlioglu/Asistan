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
from ..pipeline.jobs import is_running, read_status, start_background

STATIC = Path(__file__).resolve().parent / "static"
settings = load_settings()
RESULTS = settings.results_dir

LEAGUE_TR = {
    "E0": "İngiltere · Premier Lig", "E1": "İngiltere · Championship", "SP1": "İspanya · La Liga", "SP2": "İspanya · Segunda",
    "I1": "İtalya · Serie A", "I2": "İtalya · Serie B", "D1": "Almanya · Bundesliga", "D2": "Almanya · 2. Bundesliga",
    "F1": "Fransa · Ligue 1", "F2": "Fransa · Ligue 2", "N1": "Hollanda · Eredivisie", "P1": "Portekiz · Primeira Liga",
    "B1": "Belçika · Pro League", "T1": "Türkiye · Süper Lig", "G1": "Yunanistan · Süper Lig", "SC0": "İskoçya · Premiership",
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


def _dates() -> list[str]:
    return sorted({p.name[:10] for p in RESULTS.glob("*_predictions.csv")}, reverse=True)


def _load_table(stamp: str) -> pd.DataFrame:
    path = RESULTS / f"{stamp}_predictions.csv"
    if not path.exists():
        raise HTTPException(404, f"no predictions for {stamp}")
    return pd.read_csv(path)


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
        "id": _str(row["match_id"]), "league": _str(row["league"]), "league_name": LEAGUE_TR.get(_str(row["league"]), _str(row["league"])),
        "date": _str(row["date"]), "time": _str(row.get("time")), "home": _str(row["home"]), "away": _str(row["away"]),
        "n": int(row["n"]), "n_eff": _num(row.get("n_eff")), "confidence": _str(row["confidence"]), "signal": _str(row["signal"]),
        "signal_outcome": _str(row.get("signal_outcome")) or "home",
        "avg_sim": _num(row.get("avg_similarity")), "median_sim": _num(row.get("median_similarity")), "min_sim": _num(row.get("min_similarity")),
        "over25": _num(row.get("over25")), "under25": _num(row.get("under25")), "btts": _num(row.get("btts")),
        "avg_goals": _num(row.get("avg_goals")), "market_over25": _num(row.get("market_over25")),
    }
    for grp, cols in (("odds", "odds"), ("market", "market"), ("hist", "hist"), ("adj", "adj"), ("edge", "edge"), ("fair", "fair")):
        out[grp] = {k: _num(row.get(f"{cols}_{k}")) for k in ("h", "d", "a")}
    out["ci"] = {k: [_num(row.get(f"ci_{k}_lo")), _num(row.get(f"ci_{k}_hi"))] for k in ("h", "d", "a")}
    out["scorelines"] = det.get("scorelines", {})
    out["goals_dist"] = det.get("goals_dist", {})
    out["scopes"] = det.get("scopes", {})
    out["tolerance"] = det.get("tolerance", {})
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
    return {"dates": _dates(), "status": status, "backtest": backtest, "days_ahead": int(os.environ.get("FO_DAYS_AHEAD", "2")),
            "admin_required": bool(os.environ.get("FO_ADMIN_KEY", "")), "daily_utc": os.environ.get("FO_DAILY_UTC", "06:30")}


@app.get("/api/day/{stamp}")
def day(stamp: str) -> dict:
    table = _load_table(stamp)
    details = _load_details(stamp).get("matches", {})
    matches = [_match_payload(row, details.get(_str(row["match_id"]), {})) for _, row in table.iterrows()]
    matches.sort(key=lambda m: (m["date"], m["time"], m["league_name"]))
    return {"date": stamp, "matches": matches}


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
        })
    counts = sub["ftr"].value_counts(normalize=True).reindex(["H", "D", "A"]).fillna(0) * 100
    return {"rows": rows, "share": {"h": round(float(counts["H"]), 1), "d": round(float(counts["D"]), 1), "a": round(float(counts["A"]), 1)},
            "same_team_count": int(sum(r["same_team"] for r in rows)), "teams": sorted(teams)}


HISTORY_COLS = ["date", "league", "season", "home_team", "away_team", "cons_h", "cons_d", "cons_a", "p_home", "p_draw", "p_away",
                "ftr", "fthg", "ftag", "result_code", "total_goals"]


@lru_cache(maxsize=2)
def _history_cached(mtime: float) -> pd.DataFrame:
    p = settings.processed_dir / "matches.parquet"
    df = pd.read_parquet(p, columns=HISTORY_COLS)
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


@app.post("/api/refresh")
def refresh(x_admin_key: str | None = Header(default=None)) -> dict:
    required = os.environ.get("FO_ADMIN_KEY", "")
    if required and x_admin_key != required:
        raise HTTPException(401, "yönetici anahtarı yanlış")
    days = int(os.environ.get("FO_DAYS_AHEAD", "2"))
    started = start_background(settings, days=days, full_download=not (settings.processed_dir / "matches.parquet").exists())
    return {"started": started is not None, "running": True}


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC / "index.html", headers={"Cache-Control": "no-cache"})


app.mount("/static", StaticFiles(directory=str(STATIC)), name="static")
