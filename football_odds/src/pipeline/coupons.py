"""User coupons ("Oyun"): the user picks matches and outcomes; the system's own picks on the same
matches (history and market, frozen at creation time) ride along, and every pick is settled as
results arrive — so one coupon compares three players: you, the analogues, the market.

Markets: ms (1/X/2), o25 and o15 (over/under total goals), fh05/fh15/sh05/sh15 (at least 1 / 2
goals in the first / second half). Odds exist only for ms and o25 (Football-Data prices); the
others are counted right/wrong without money.

Storage: <results_dir>/coupons.json (on Railway that is the mounted volume).
"""

from __future__ import annotations

import datetime as dt
import json
import secrets
from pathlib import Path
from typing import Any

from ..config import Settings

HTFT = ("1/1", "1/X", "1/2", "X/1", "X/X", "X/2", "2/1", "2/X", "2/2")
MARKETS = {
    "ms": "Maç sonucu", "iy": "İlk yarı sonucu", "iyms": "İY/MS", "o25": "2,5 gol", "o15": "1,5 gol",
    "fh05": "İlk yarı 0,5 üst", "fh15": "İlk yarı 1,5 üst", "sh05": "İkinci yarı 0,5 üst", "sh15": "İkinci yarı 1,5 üst",
}
PICKS = {"ms": ("h", "d", "a"), "iy": ("h", "d", "a"), "iyms": HTFT, "o25": ("over", "under"), "o15": ("over", "under"),
         "fh05": ("over", "under"), "fh15": ("over", "under"), "sh05": ("over", "under"), "sh15": ("over", "under")}
PICK_TR = {"h": "1", "d": "X", "a": "2", "over": "Üst", "under": "Alt", **{k: k for k in HTFT}}
LAB_KEYS = ("target", "target_label", "market_p", "estimate_p", "difference", "evidence", "why", "source")   # what a pick remembers of the lab
MAX_PICKS = 40


def _path(settings: Settings) -> Path:
    return settings.results_dir / "coupons.json"


def load(settings: Settings) -> list[dict]:
    p = _path(settings)
    try:
        return json.loads(p.read_text()) if p.exists() else []
    except json.JSONDecodeError:
        return []


def save(settings: Settings, coupons: list[dict]) -> None:
    p = _path(settings)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(coupons, ensure_ascii=False, indent=1))
    tmp.replace(p)


# --------------------------------------------------------------------------- system picks

def _yes_no(p: float | None) -> str | None:
    return None if p is None else ("over" if p >= 50 else "under")


def _argmax(p: dict[str, float | None]) -> str | None:
    vals = {k: v for k, v in p.items() if v is not None}
    return max(vals, key=vals.get) if vals else None


def system_picks(row: dict, market: str) -> dict[str, Any]:
    """{'hist': pick, 'market': pick, 'p_hist': %, 'p_market': %} for one market of one prediction row."""
    pct = lambda frac: None if frac is None else 100 * frac  # noqa: E731
    if market == "ms":
        h, m = _argmax(row["adj"]), _argmax(row["market"])
        return {"hist": h, "market": m, "p_hist": row["adj"].get(h) if h else None, "p_market": row["market"].get(m) if m else None}
    if market in ("iy", "iyms"):                      # neither the analogues nor Football-Data price these
        return {"hist": None, "market": None, "p_hist": None, "p_market": None}
    prob = {"o25": (row.get("hist_over25"), row.get("market_over25")), "o15": (row.get("hist_over15"), None),
            "fh05": (pct(row.get("fh_over05")), None), "fh15": (pct(row.get("fh_over15")), None),
            "sh05": (pct(row.get("sh_over05")), None), "sh15": (pct(row.get("sh_over15")), None)}[market]
    return {"hist": _yes_no(prob[0]), "market": _yes_no(prob[1]), "p_hist": prob[0], "p_market": prob[1]}


def odds_for(row: dict, market: str, pick: str) -> float | None:
    if market == "ms":
        return row["odds"].get(pick)
    if market == "o25":
        return row.get("odds_o25") if pick == "over" else row.get("odds_u25")
    return None


# --------------------------------------------------------------------------- create / settle

def build_coupon(picks: list[dict], rows_by_id: dict[str, dict], label: str = "") -> dict:
    """Validate the user's picks against the analysed matches and freeze the system's picks next to them."""
    if not picks:
        raise ValueError("kupon boş")
    if len(picks) > MAX_PICKS:
        raise ValueError(f"en fazla {MAX_PICKS} seçim")
    out = []
    seen = set()
    for p in picks:
        mid, market, pick = str(p.get("match_id", "")), str(p.get("market", "")), str(p.get("pick", ""))
        row = rows_by_id.get(mid)
        if row is None:
            raise ValueError(f"maç bulunamadı: {mid}")
        if market not in MARKETS or pick not in PICKS[market]:
            raise ValueError(f"geçersiz seçim: {market}/{pick}")
        if (mid, market) in seen:
            raise ValueError("aynı maç ve piyasa iki kez seçilmiş")
        seen.add((mid, market))
        item = {"match_id": mid, "league": row["league"], "home": row["home"], "away": row["away"], "date": row["date"], "time": row["time"],
                "market": market, "pick": pick, "odds": odds_for(row, market, pick), "system": system_picks(row, market)}
        # a pick made from the page may carry the price it was made at (nesine's, frozen now — the bulletin
        # moves) and what Pattern Lab said about it at that moment, so the lab can be scored later on real picks
        try:
            given = float(p["odds"]) if p.get("odds") is not None else None
        except (TypeError, ValueError):
            given = None
        if given is not None and given > 1.0:
            item["odds"] = round(given, 2)
            item["odds_source"] = str(p.get("odds_source") or "nesine")[:20]
        if p.get("nesine_code") is not None:
            item["nesine_code"] = p["nesine_code"]
        if isinstance(p.get("lab"), dict):
            item["lab"] = {k: p["lab"][k] for k in LAB_KEYS if k in p["lab"]}
        out.append(item)
    out.sort(key=lambda x: (x["date"], x["time"], x["home"], x["market"]))
    return {"id": secrets.token_hex(6), "created_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
            "label": str(label or "")[:60], "picks": out}


def settle_pick(market: str, pick: str, res: dict) -> bool | None:
    """True/False, or None when the result does not carry what the market needs (half-time score)."""
    hs, as_ = res["hs"], res["as"]
    total = hs + as_
    if market == "ms":
        r = "h" if hs > as_ else "a" if hs < as_ else "d"
        return pick == r
    if market in ("o25", "o15"):
        line = 2.5 if market == "o25" else 1.5
        return (total > line) == (pick == "over")
    ht_h, ht_a = res.get("ht_h"), res.get("ht_a")
    if ht_h is None or ht_a is None:
        return None
    if market in ("iy", "iyms"):
        code = {"h": "1", "d": "X", "a": "2"}
        ht = "h" if int(ht_h) > int(ht_a) else "a" if int(ht_h) < int(ht_a) else "d"
        ft = "h" if hs > as_ else "a" if hs < as_ else "d"
        return pick == (ht if market == "iy" else f"{code[ht]}/{code[ft]}")
    fh = int(ht_h) + int(ht_a)
    goals = fh if market.startswith("fh") else total - fh
    line = 0.5 if market.endswith("05") else 1.5
    return (goals > line) == (pick == "over")


def evaluate(coupon: dict, results: dict[str, dict]) -> dict:
    """Coupon + per-pick outcomes for you / history / market and the tallies."""
    picks = []
    tally = {"user": {"ok": 0, "wrong": 0, "pending": 0, "pnl": 0.0, "n_odds": 0},
             "hist": {"ok": 0, "wrong": 0, "pending": 0, "pnl": 0.0, "n_odds": 0},
             "market": {"ok": 0, "wrong": 0, "pending": 0, "pnl": 0.0, "n_odds": 0}}
    for p in coupon["picks"]:
        res = results.get(p["match_id"])
        item = {**p, "market_label": MARKETS[p["market"]], "pick_label": PICK_TR[p["pick"]],
                "score": f"{res['hs']}-{res['as']}" if res else "", "ht_score": f"{res['ht_h']}-{res['ht_a']}" if res and res.get("ht_h") is not None else "",
                "user_ok": None, "hist_ok": None, "market_ok": None, "pnl": None}
        sides = {"user": p["pick"], "hist": p["system"].get("hist"), "market": p["system"].get("market")}
        for side, pick in sides.items():
            if pick is None:
                continue  # that side has no opinion on this market (e.g. market on half goals)
            ok = settle_pick(p["market"], pick, res) if res else None
            if ok is None:
                tally[side]["pending"] += 1
            else:
                tally[side]["ok" if ok else "wrong"] += 1
                # the user's pick is priced whenever it carried a price (Football-Data's or nesine's, frozen);
                # the system's picks only on ms / o25, at the price of ITS pick, not the user's
                odds = p.get("odds") if side == "user" else (_odds_from_pick(p, pick) if p["market"] in ("ms", "o25") else None)
                if odds:
                    tally[side]["pnl"] += (odds - 1.0) if ok else -1.0
                    tally[side]["n_odds"] += 1
                    if side == "user":
                        item["pnl"] = (odds - 1.0) if ok else -1.0
            item[f"{side}_ok"] = ok
            item[f"{side}_pick"] = pick
        picks.append(item)
    n_settled_user = tally["user"]["ok"] + tally["user"]["wrong"]
    status = "pending" if n_settled_user < len(coupon["picks"]) else ("won" if tally["user"]["wrong"] == 0 else "lost")
    for t in tally.values():
        t["pnl"] = round(t["pnl"], 2)
    return {**coupon, "picks": picks, "tally": tally, "status": status, "n_picks": len(coupon["picks"]),
            "all_settled": n_settled_user == len(coupon["picks"])}


def _odds_from_pick(p: dict, pick: str) -> float | None:
    """Price of the system's pick, stored alongside the user's; only ms and o25 carry prices."""
    prices = p.get("prices") or {}
    return prices.get(pick)


def attach_prices(coupon: dict, rows_by_id: dict[str, dict]) -> dict:
    """Store every price of ms / o25 markets so the system's picks can be settled with money too."""
    for p in coupon["picks"]:
        row = rows_by_id.get(p["match_id"])
        if row is None:
            continue
        if p["market"] == "ms":
            p["prices"] = {k: row["odds"].get(k) for k in ("h", "d", "a")}
        elif p["market"] == "o25":
            p["prices"] = {"over": row.get("odds_o25"), "under": row.get("odds_u25")}
    return coupon
