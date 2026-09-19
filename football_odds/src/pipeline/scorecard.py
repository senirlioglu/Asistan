"""Daily scorecard: for the matches that have been played, who sat closer to what happened —
the market or the historical analogues — per market (1X2, 2.5 / 1.5 goals, first- and
second-half goals), overall and per league.

Sources: every ``results/*_predictions.csv`` (newest analysis per match) + ``_details.json``
(goal distribution, half statistics); realised results from the processed database first
(Football-Data), otherwise ESPN's finished scoreboard (cached in ``results/results_cache.json``
so a score is fetched once).

"Right" for a side means the outcome it gave the highest probability to happened. "Closer"
means the side gave the realised outcome the higher probability (ties within 1 point count as
equal). Football-Data has no 1.5-goal or half-time markets, so those rows are history-only.
"""

from __future__ import annotations

import datetime as dt
import json
import math
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd

from ..config import Settings
from ..logging_setup import get_logger

log = get_logger("pipeline.scorecard")

TR = ZoneInfo("Europe/Istanbul")
UK = ZoneInfo("Europe/London")
LIVE_LOOKBACK_DAYS = 14   # ESPN is asked for finished scores only this far back
MAX_RANGE_DAYS = 92


def to_turkey(date_str: str, time_str: str) -> tuple[str, str]:
    """('2026-09-14', '20:00' UK) -> ('2026-09-14', '22:00'). Missing time -> same date, ''."""
    if not date_str or not time_str:
        return (date_str or "")[:10], ""
    try:
        naive = dt.datetime.strptime(f"{date_str[:10]} {time_str[:5]}", "%Y-%m-%d %H:%M")
    except ValueError:
        return date_str[:10], ""
    local = naive.replace(tzinfo=UK).astimezone(TR)
    return local.date().isoformat(), local.strftime("%H:%M")


def _f(v: Any) -> float | None:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(x) or math.isinf(x) else x


# --------------------------------------------------------------------------- predictions

def load_prediction_rows(results_dir: Path) -> list[dict]:
    """One row per analysed match (newest analysis wins), with Turkey date/time and the details."""
    files = sorted(results_dir.glob("*_predictions.csv"))
    if not files:
        return []
    frames = []
    for p in files:
        df = pd.read_csv(p)
        df["stamp"] = "nesine" if p.name.startswith("nesine_") else p.name[:10]   # the bulletin's analysis has no run day
        frames.append(df)
    df = pd.concat(frames, ignore_index=True).sort_values("stamp").drop_duplicates("match_id", keep="last")
    details: dict[str, dict] = {}
    rows = []
    for _, r in df.iterrows():
        stamp = str(r["stamp"])
        if stamp not in details:
            p = results_dir / f"{stamp}_details.json"
            details[stamp] = json.loads(p.read_text()).get("matches", {}) if p.exists() else {}
        det = details[stamp].get(str(r["match_id"]), {})
        date_uk, time_uk = str(r["date"])[:10], "" if pd.isna(r.get("time")) else str(r.get("time"))
        date_tr, time_tr = to_turkey(date_uk, time_uk)
        gd = det.get("goals_dist") or {}
        halves = det.get("halves") or {}
        p0, p1 = _f(gd.get("0")), _f(gd.get("1"))
        rows.append({
            "id": str(r["match_id"]), "stamp": stamp, "league": str(r["league"]),
            "date_uk": date_uk, "time_uk": time_uk, "date": date_tr, "time": time_tr,
            "home": str(r["home"]), "away": str(r["away"]),
            "market": {"h": _f(r["market_h"]), "d": _f(r["market_d"]), "a": _f(r["market_a"])},
            "adj": {"h": _f(r["adj_h"]), "d": _f(r["adj_d"]), "a": _f(r["adj_a"])},
            "odds": {"h": _f(r.get("odds_h")), "d": _f(r.get("odds_d")), "a": _f(r.get("odds_a"))},
            "odds_max": {"h": _f(r.get("odds_max_h")), "d": _f(r.get("odds_max_d")), "a": _f(r.get("odds_max_a"))},
            "odds_o25": _f(r.get("odds_o25")), "odds_u25": _f(r.get("odds_u25")),
            "odds_max_o25": _f(r.get("odds_max_o25")), "odds_max_u25": _f(r.get("odds_max_u25")),
            "market_over25": _f(r.get("market_over25")), "hist_over25": _f(r.get("over25")),
            "hist_over15": (100 * (1 - p0 - p1)) if p0 is not None and p1 is not None else None,
            "fh_over05": _f(halves.get("fh_over05")), "fh_over15": _f(halves.get("fh_over15")),
            "sh_over05": _f(halves.get("sh_over05")), "sh_over15": _f(halves.get("sh_over15")),
            "halves_n": halves.get("n"),
        })
    return rows


# --------------------------------------------------------------------------- realised results

def _cache_path(settings: Settings) -> Path:
    return settings.results_dir / "results_cache.json"


def load_cache(settings: Settings) -> dict[str, dict]:
    p = _cache_path(settings)
    try:
        return json.loads(p.read_text()) if p.exists() else {}
    except json.JSONDecodeError:
        return {}


def save_cache(settings: Settings, cache: dict[str, dict]) -> None:
    p = _cache_path(settings)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(cache, indent=0))


def _db_result(history: pd.DataFrame | None, row: dict) -> dict | None:
    if history is None or history.empty:
        return None
    same = (history["league"] == row["league"]) & (history["home_team"] == row["home"]) & (history["away_team"] == row["away"])
    days = history["date"].dt.strftime("%Y-%m-%d")
    hit = history[same & (days == row["date_uk"])]
    if hit.empty and row.get("stamp") == "nesine":       # a bulletin row is dated in Turkey time; the database in UK time
        try:
            d = dt.date.fromisoformat(row["date_uk"])
            near = {(d + dt.timedelta(days=k)).isoformat() for k in (-1, 1)}
            hit = history[same & days.isin(near)]
        except ValueError:
            pass
    if hit.empty:
        return None
    r = hit.iloc[0]
    if str(r.get("ftr")) not in ("H", "D", "A"):
        return None
    return {"hs": int(r["fthg"]), "as": int(r["ftag"]),
            "ht_h": int(r["hthg"]) if pd.notna(r.get("hthg")) else None, "ht_a": int(r["htag"]) if pd.notna(r.get("htag")) else None,
            "source": "football-data"}


def realised_results(settings: Settings, rows: list[dict], history: pd.DataFrame | None, use_live: bool = True,
                     today: dt.date | None = None) -> dict[str, dict]:
    """match id -> {hs, as, ht_h, ht_a, source} for every row whose result is known."""
    today = today or dt.datetime.now(TR).date()
    cache = load_cache(settings)
    out: dict[str, dict] = {}
    dirty = False
    for row in rows:
        res = _db_result(history, row)
        if res is None:
            res = cache.get(row["id"])
        if res is None and use_live:
            try:
                d = dt.date.fromisoformat(row["date_uk"])
            except ValueError:
                continue
            if 0 <= (today - d).days <= LIVE_LOOKBACK_DAYS:
                from ..web.live import live_for_fixture
                info = live_for_fixture(row["league"], row["date_uk"], row["home"], row["away"])
                if info and info.get("state") == "post":
                    res = {"hs": int(info["home_score"]), "as": int(info["away_score"]), "ht_h": info.get("ht_home"), "ht_a": info.get("ht_away"),
                           "source": "espn"}
                    cache[row["id"]] = res
                    dirty = True
        if res is not None:
            out[row["id"]] = res
    if dirty:
        save_cache(settings, cache)
    return out


# --------------------------------------------------------------------------- scoring

def _argmax(p: dict[str, float | None]) -> str | None:
    vals = {k: v for k, v in p.items() if v is not None}
    return max(vals, key=vals.get) if vals else None


def _closer(p_market: float | None, p_hist: float | None, margin: float = 1.0) -> str | None:
    if p_market is None or p_hist is None:
        return None
    if abs(p_market - p_hist) < margin:
        return "equal"
    return "hist" if p_hist > p_market else "market"


def _binary(expected_pct: float | None, happened: bool | None) -> dict | None:
    """One side's view of a yes/no market: pick + correctness + the probability it gave to what happened."""
    if expected_pct is None or happened is None:
        return None
    pick_yes = expected_pct >= 50
    return {"p_yes": expected_pct, "pick": "yes" if pick_yes else "no", "ok": pick_yes == happened,
            "p_realised": expected_pct if happened else 100 - expected_pct}


def score_match(row: dict, res: dict) -> dict:
    hs, as_ = res["hs"], res["as"]
    r = "h" if hs > as_ else "a" if hs < as_ else "d"
    total = hs + as_
    mk, hi = row["market"], row["adj"]
    m_pick, h_pick = _argmax(mk), _argmax(hi)
    p_m, p_h = mk.get(r), hi.get(r)
    out = {
        "id": row["id"], "date": row["date"], "time": row["time"], "league": row["league"], "home": row["home"], "away": row["away"],
        "score": f"{hs}-{as_}", "result": r, "total": total, "source": res.get("source"),
        "ms": {"market": {"pick": m_pick, "ok": m_pick == r, "p_realised": p_m, "brier": _brier(mk, r)},
               "hist": {"pick": h_pick, "ok": h_pick == r, "p_realised": p_h, "brier": _brier(hi, r)},
               "closer": _closer(p_m, p_h)},
        "o25": {"market": _binary(row["market_over25"], total > 2.5), "hist": _binary(row["hist_over25"], total > 2.5), "happened": total > 2.5},
        "o15": {"market": None, "hist": _binary(row["hist_over15"], total > 1.5), "happened": total > 1.5},
    }
    for key in ("o25", "o15"):
        m, h = out[key]["market"], out[key]["hist"]
        out[key]["closer"] = _closer(m["p_realised"], h["p_realised"]) if m and h else None
    ht_h, ht_a = res.get("ht_h"), res.get("ht_a")
    if ht_h is not None and ht_a is not None:
        fh = int(ht_h) + int(ht_a)
        sh = total - fh
        out["ht_score"] = f"{ht_h}-{ht_a}"
        out["fh05"] = {"market": None, "hist": _binary(_pct(row["fh_over05"]), fh > 0.5), "happened": fh > 0.5, "closer": None}
        out["fh15"] = {"market": None, "hist": _binary(_pct(row["fh_over15"]), fh > 1.5), "happened": fh > 1.5, "closer": None}
        out["sh05"] = {"market": None, "hist": _binary(_pct(row["sh_over05"]), sh > 0.5), "happened": sh > 0.5, "closer": None}
        out["sh15"] = {"market": None, "hist": _binary(_pct(row["sh_over15"]), sh > 1.5), "happened": sh > 1.5, "closer": None}
    else:
        out["ht_score"] = ""
    return out


def _pct(frac: float | None) -> float | None:
    return None if frac is None else 100 * frac


def _brier(p: dict[str, float | None], r: str) -> float | None:
    if any(p.get(k) is None for k in ("h", "d", "a")):
        return None
    return sum(((p[k] or 0) / 100 - (1.0 if k == r else 0.0)) ** 2 for k in ("h", "d", "a"))


MARKETS = [
    ("ms", "Maç sonucu", "Favoriyi (en yüksek ihtimal verilen sonucu) tutturma"),
    ("o25", "2,5 gol üst/alt", "Toplam gol 2,5 üstü mü altı mı"),
    ("o15", "1,5 gol üst/alt", "Toplam gol 1,5 üstü mü altı mı (piyasada bu oran yok; yalnızca geçmiş)"),
    ("fh05", "İlk yarı 0,5 üst", "İlk yarıda en az 1 gol (yalnızca geçmiş; ilk yarı skoru bilinen maçlar)"),
    ("fh15", "İlk yarı 1,5 üst", "İlk yarıda en az 2 gol (yalnızca geçmiş)"),
    ("sh05", "İkinci yarı 0,5 üst", "İkinci yarıda en az 1 gol (yalnızca geçmiş)"),
    ("sh15", "İkinci yarı 1,5 üst", "İkinci yarıda en az 2 gol (yalnızca geçmiş)"),
]


def _side_summary(entries: list[dict], binary: bool) -> dict | None:
    if not entries:
        return None
    n = len(entries)
    ok = sum(1 for e in entries if e["ok"])
    out: dict[str, Any] = {"n": n, "ok": ok, "wrong": n - ok, "ok_pct": 100 * ok / n}
    if binary:
        out["expected_pct"] = sum(e["p_yes"] for e in entries) / n
    else:
        bs = [e["brier"] for e in entries if e.get("brier") is not None]
        out["brier"] = sum(bs) / len(bs) if bs else None
        out["p_realised_avg"] = sum(e["p_realised"] for e in entries if e["p_realised"] is not None) / n
    return out


def aggregate(scored: list[dict]) -> list[dict]:
    blocks = []
    for key, label, desc in MARKETS:
        items = [s[key] for s in scored if key in s]
        if not items:
            blocks.append({"key": key, "label": label, "desc": desc, "n": 0, "market": None, "hist": None, "closer": None})
            continue
        binary = key != "ms"
        m_entries = [it["market"] for it in items if it.get("market")]
        h_entries = [it["hist"] for it in items if it.get("hist")]
        closer = {"market": 0, "hist": 0, "equal": 0}
        for it in items:
            if it.get("closer"):
                closer[it["closer"]] += 1
        block = {"key": key, "label": label, "desc": desc, "n": len(items),
                 "market": _side_summary(m_entries, binary), "hist": _side_summary(h_entries, binary),
                 "closer": closer if sum(closer.values()) else None}
        if binary:
            block["actual_pct"] = 100 * sum(1 for it in items if it["happened"]) / len(items)
        blocks.append(block)
    return blocks


def per_league(scored: list[dict], names: dict[str, str] | None = None) -> list[dict]:
    names = names or {}
    out = []
    for lg in sorted({s["league"] for s in scored}):
        rows = [s for s in scored if s["league"] == lg]
        ms = [r["ms"] for r in rows]
        closer = {"market": 0, "hist": 0, "equal": 0}
        for m in ms:
            if m["closer"]:
                closer[m["closer"]] += 1
        o = [r["o25"] for r in rows if r["o25"].get("hist")]
        out.append({"league": lg, "league_name": names.get(lg, lg), "n": len(rows),
                    "market_ok": sum(1 for m in ms if m["market"]["ok"]), "hist_ok": sum(1 for m in ms if m["hist"]["ok"]),
                    "closer": closer,
                    "o25_n": len(o), "o25_hist_ok": sum(1 for x in o if x["hist"]["ok"]),
                    "o25_market_ok": sum(1 for x in o if x.get("market") and x["market"]["ok"]),
                    "o25_market_n": sum(1 for x in o if x.get("market"))})
    return out


def build_scorecard(rows: list[dict], results: dict[str, dict], date_from: str, date_to: str,
                    leagues: set[str] | None = None, names: dict[str, str] | None = None) -> dict:
    """Scorecard for the matches whose Turkey date lies in [date_from, date_to]."""
    in_range = [r for r in rows if date_from <= r["date"] <= date_to and (not leagues or r["league"] in leagues)]
    scored = [score_match(r, results[r["id"]]) for r in in_range if r["id"] in results]
    pending = [{"id": r["id"], "league": r["league"], "home": r["home"], "away": r["away"], "date": r["date"], "time": r["time"]}
               for r in in_range if r["id"] not in results]
    scored.sort(key=lambda s: (s["date"], s["time"], s["league"]))
    all_leagues = sorted({r["league"] for r in rows if date_from <= r["date"] <= date_to})
    return {
        "from": date_from, "to": date_to, "n_matches": len(in_range), "n_finished": len(scored), "n_pending": len(pending),
        "leagues": [{"code": lg, "name": (names or {}).get(lg, lg)} for lg in all_leagues],
        "markets": aggregate(scored), "by_league": per_league(scored, names), "matches": scored, "pending": pending,
    }


# --------------------------------------------------------------------------- job

def run_scorecard_job(settings: Settings, history: pd.DataFrame | None = None, day: dt.date | None = None) -> dict:
    """Write results/scorecard/<day>.json for `day` (default: yesterday, Turkey time) and warm the result cache."""
    day = day or (dt.datetime.now(TR).date() - dt.timedelta(days=1))
    if history is None:
        p = settings.processed_dir / "matches.parquet"
        history = pd.read_parquet(p, columns=["league", "date", "home_team", "away_team", "fthg", "ftag", "ftr", "hthg", "htag"]) if p.exists() else None
        if history is not None:
            history["date"] = pd.to_datetime(history["date"])
    rows = load_prediction_rows(settings.results_dir)
    stamp = day.isoformat()
    rows = [r for r in rows if r["date"] == stamp]
    results = realised_results(settings, rows, history)
    card = build_scorecard(rows, results, stamp, stamp)
    out = settings.results_dir / "scorecard"
    out.mkdir(parents=True, exist_ok=True)
    (out / f"{stamp}.json").write_text(json.dumps(card, ensure_ascii=False, indent=1))
    log.info("scorecard %s: %d matches, %d finished", stamp, card["n_matches"], card["n_finished"])
    return card
