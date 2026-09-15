"""Paper trading ("Sanal oyun"): what a bettor following a fixed rule would have won or lost.

Every strategy stakes ONE unit per qualifying match at the pre-match consensus average odds
(the price Football-Data collected on Friday/Tuesday afternoon) and, when the best available
price is known, also at that maximum odds — an optimistic upper bound. İddaa's own prices are
not in the data; they carry a higher margin, so real returns there sit below both numbers.

Strategies (all flat stake, singles only):
    market_fav   the outcome the market gives the highest probability
    hist_fav     the outcome the historical analogues give the highest probability
    deviation    the outcome where history exceeds the market by >= `edge` points (largest gap)
    contrarian   the mirror image: the outcome where the market exceeds history by >= `edge`
    ou25_hist    over 2.5 when history says >= 50 %, else under (needs O/U prices)
    ou25_market  the same rule applied to the market's own O/U probability (control)
"""

from __future__ import annotations

from typing import Any

STRATEGIES = [
    ("market_fav", "Piyasa favorisi", "Her maçta piyasanın en yüksek ihtimal verdiği sonuç."),
    ("hist_fav", "Geçmiş favorisi", "Her maçta benzer maçların en yüksek ihtimal verdiği sonuç."),
    ("deviation", "Sapma", "Geçmişin piyasadan en az E puan yüksek verdiği sonuç (birden çoksa en büyük fark). Sistemin 'sapma' uyarısına göre oynamak bu."),
    ("contrarian", "Tersine", "Sapmanın aynası: piyasanın geçmişten en az E puan yüksek verdiği sonuç. Kontrol grubu."),
    ("ou25_hist", "2,5 gol · geçmiş", "Geçmiş %50 ve üzeri üst diyorsa üst, yoksa alt. Üst/alt oranı olan maçlarda."),
    ("ou25_market", "2,5 gol · piyasa", "Aynı kural piyasanın kendi üst ihtimaliyle. Kontrol grubu."),
]

OUTCOME_TR = {"h": "1", "d": "X", "a": "2", "over": "Üst", "under": "Alt"}


def _argmax(p: dict[str, float | None]) -> str | None:
    vals = {k: v for k, v in p.items() if v is not None}
    return max(vals, key=vals.get) if vals else None


def pick_for(strategy: str, row: dict, edge: float) -> tuple[str, float | None, float | None] | None:
    """(outcome, avg odds, max odds) for this strategy on this match, or None when it does not bet."""
    mk, hi = row["market"], row["adj"]
    odds, mx = row["odds"], row["odds_max"]
    if strategy == "market_fav":
        k = _argmax(mk)
    elif strategy == "hist_fav":
        k = _argmax(hi)
    elif strategy in ("deviation", "contrarian"):
        gaps = {k: (hi[k] - mk[k]) if hi.get(k) is not None and mk.get(k) is not None else None for k in ("h", "d", "a")}
        gaps = {k: (v if strategy == "deviation" else -v) for k, v in gaps.items() if v is not None}
        best = max(gaps, key=gaps.get) if gaps else None
        k = best if best is not None and gaps[best] >= edge else None
    elif strategy in ("ou25_hist", "ou25_market"):
        p = row["hist_over25"] if strategy == "ou25_hist" else row["market_over25"]
        if p is None or row["odds_o25"] is None or row["odds_u25"] is None:
            return None
        over = p >= 50
        return ("over" if over else "under", row["odds_o25"] if over else row["odds_u25"], row["odds_max_o25"] if over else row["odds_max_u25"])
    else:
        raise ValueError(strategy)
    if k is None or odds.get(k) is None:
        return None
    return (k, odds[k], mx.get(k))


def settle(pick: str, res: dict) -> bool:
    hs, as_ = res["hs"], res["as"]
    if pick in ("over", "under"):
        return (hs + as_ > 2.5) == (pick == "over")
    r = "h" if hs > as_ else "a" if hs < as_ else "d"
    return pick == r


def simulate(rows: list[dict], results: dict[str, dict], edge: float = 3.0, names: dict[str, str] | None = None) -> dict:
    """rows: prediction rows (scorecard.load_prediction_rows shape, with odds); results: id -> {hs, as}."""
    names = names or {}
    out: dict[str, Any] = {"edge": edge, "strategies": []}
    for key, label, desc in STRATEGIES:
        bets = []
        for row in rows:
            p = pick_for(key, row, edge)
            if p is None:
                continue
            pick, o_avg, o_max = p
            res = results.get(row["id"])
            bet = {"id": row["id"], "date": row["date"], "time": row["time"], "league": row["league"], "league_name": names.get(row["league"], row["league"]),
                   "home": row["home"], "away": row["away"], "pick": pick, "pick_label": OUTCOME_TR.get(pick, pick), "odds": o_avg, "odds_max": o_max,
                   "settled": res is not None}
            if res is not None:
                won = settle(pick, res)
                bet.update({"score": f"{res['hs']}-{res['as']}", "won": won, "pnl": (o_avg - 1.0) if won else -1.0,
                            "pnl_max": ((o_max - 1.0) if won else -1.0) if o_max else None})
            bets.append(bet)
        settled = [b for b in bets if b["settled"]]
        wins = sum(1 for b in settled if b["won"])
        staked = len(settled)
        profit = sum(b["pnl"] for b in settled)
        with_max = [b for b in settled if b["pnl_max"] is not None]
        profit_max = sum(b["pnl_max"] for b in with_max)
        # cumulative curve by day (average odds)
        curve, running = [], 0.0
        for d in sorted({b["date"] for b in settled}):
            running += sum(b["pnl"] for b in settled if b["date"] == d)
            curve.append({"date": d, "pnl": round(running, 3)})
        by_league = []
        for lg in sorted({b["league"] for b in settled}):
            sub = [b for b in settled if b["league"] == lg]
            by_league.append({"league": lg, "league_name": names.get(lg, lg), "n": len(sub), "wins": sum(1 for b in sub if b["won"]),
                              "pnl": round(sum(b["pnl"] for b in sub), 2)})
        drawdown, peak, run = 0.0, 0.0, 0.0
        for b in sorted(settled, key=lambda x: (x["date"], x["time"])):
            run += b["pnl"]; peak = max(peak, run); drawdown = max(drawdown, peak - run)
        out["strategies"].append({
            "key": key, "label": label, "desc": desc.replace("E puan", f"{edge:g} puan"),
            "n_bets": len(bets), "n_settled": staked, "n_pending": len(bets) - staked, "wins": wins, "losses": staked - wins,
            "hit_pct": (100 * wins / staked) if staked else None,
            "avg_odds": (sum(b["odds"] for b in settled) / staked) if staked else None,
            "profit": round(profit, 2), "roi_pct": (100 * profit / staked) if staked else None,
            "n_max": len(with_max), "profit_max": round(profit_max, 2) if with_max else None,
            "roi_max_pct": (100 * profit_max / len(with_max)) if with_max else None,
            "max_drawdown": round(drawdown, 2), "curve": curve, "by_league": by_league,
            "bets": sorted(bets, key=lambda x: (x["date"], x["time"], x["league"])),
        })
    return out
