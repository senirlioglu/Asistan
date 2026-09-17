"""PATTERN LAB — the orchestration: a match and a target in, every engine's answer out.

The reader never picks an engine. They pick a match (mode 1), or a result and let the lab pick the
matches (mode 2), or type their own conditions (mode 3). This module turns those three questions
into calls on the engines that already exist — the pattern engine, the twin engine, the two-team
cascade, the fixture cycles — and puts the answers in one shape:

    N · gerçekleşen · piyasa beklentisi · fark · %95 aralık · kanıt durumu

Three rules hold everywhere here:

  * the market is always the reference. A 9 % hit rate for 2/1 means nothing until it stands next
    to the 10 % the price implied; where no price exists the reference is how often the same thing
    happened in matches PRICED THE SAME WAY, and the payload says which of the two it is.
  * similarity is not probability. A twin set that is 83 % similar says nothing about how likely the
    target is; the two numbers travel in different fields and are labelled differently on the page.
  * nothing found in the pool alone is "doğrulandı". A layer clearing zero is a KEŞİF; the discovery
    scan's three windows decide the rest, and the label comes from there.

The "pattern estimate" is the precision-weighted combination of the layers' market-adjusted edges,
added to today's price. The layers overlap (a twin is often also a form match), so its interval is
optimistic, and the payload says so rather than pretending the layers were independent.
"""

from __future__ import annotations

import datetime as dt
import threading
from dataclasses import replace

import numpy as np
import pandas as pd

from ..config import Settings
from ..logging_setup import get_logger
from . import cycles, engine, sequence, service, state
from .lab import EVIDENCE, MIN_EDGE, MIN_N

log = get_logger("patterns.target")

ALPHA = 0.05
EVIDENCE_TR = {**EVIDENCE, "none": "FARK YOK"}
WIDE_CI = 8.0            # a combined interval wider than this (in points) is called wide
LOW_ABS = 15.0           # a target the market prices under this (in %) is called a long shot

# --------------------------------------------------------------------------- the targets
# Only what the backend can actually measure: every key is an `engine.OUTCOMES` outcome.
TARGET_GROUPS = [
    {"key": "ms", "label": "Maç sonucu", "nesine": "ms", "targets": [
        {"key": "ft_1", "label": "1", "explain": "Maçı ev sahibi kazanır."},
        {"key": "ft_X", "label": "X", "explain": "Maç berabere biter."},
        {"key": "ft_2", "label": "2", "explain": "Maçı deplasman kazanır."}]},
    {"key": "iy", "label": "İlk yarı", "nesine": "iy", "targets": [
        {"key": "ht_1", "label": "1", "explain": "İlk yarıyı ev sahibi önde kapatır."},
        {"key": "ht_X", "label": "X", "explain": "İlk yarı berabere biter."},
        {"key": "ht_2", "label": "2", "explain": "İlk yarıyı deplasman önde kapatır."}]},
    {"key": "iyms", "label": "İY/MS", "nesine": "iyms", "targets": [
        {"key": f"htft_{h}/{f}", "label": f"{h}/{f}",
         "explain": f"İlk yarı {_w}, maç sonu {_v}."}
        for h, _w in (("1", "ev sahibi önde"), ("X", "berabere"), ("2", "deplasman önde"))
        for f, _v in (("1", "ev sahibi kazanır"), ("X", "berabere"), ("2", "deplasman kazanır"))]},
    {"key": "gol", "label": "Gol", "nesine": None, "targets": [
        {"key": "over15", "label": "1,5 üst", "explain": "Maçta en az 2 gol olur."},
        {"key": "over25", "label": "2,5 üst", "explain": "Maçta en az 3 gol olur."},
        {"key": "over35", "label": "3,5 üst", "explain": "Maçta en az 4 gol olur."},
        {"key": "btts", "label": "KG var", "explain": "İki takım da gol atar."}]},
]
TARGETS: dict[str, dict] = {t["key"]: {**t, "group": g["key"], "group_label": g["label"]}
                            for g in TARGET_GROUPS for t in g["targets"]}
NESINE_PATH = {"ft_1": ("ms", "1"), "ft_X": ("ms", "X"), "ft_2": ("ms", "2"),
               "ht_1": ("iy", "1"), "ht_X": ("iy", "X"), "ht_2": ("iy", "2"),
               "over25": ("o25", "ust"), "over35": ("o35", "ust"),
               **{f"htft_{h}/{f}": ("iyms", f"{h}/{f}") for h in "1X2" for f in "1X2"}}
# which offline discovery outcome a target corresponds to (the scan is side-based; the lab is not)
DISCOVERY_OUTCOME = {"ft_1": ("win", "home"), "ft_X": ("draw", "home"), "ft_2": ("win", "away"),
                     "over25": ("over25", "home"), "ht_X": ("ht_draw", "home"),
                     "htft_1/2": ("reversal", "home"), "htft_2/1": ("reversal", "home")}


def targets_payload() -> dict:
    return {"groups": TARGET_GROUPS, "evidence_tr": EVIDENCE_TR,
            "note": "Yalnızca arka ucun gerçekten ölçebildiği marketler listelenir."}


# --------------------------------------------------------------------------- helpers

def _layer(key: str, label: str, m: dict | None, note: str = "", kind: str = "claim") -> dict:
    """One layer in the standard shape. `edge` is against the price where one exists, else against
    the price-matched reference; `reference` says which."""
    if not m or not m.get("n"):
        return {"key": key, "label": label, "n": 0, "actual": None, "expected": None, "reference": None,
                "edge": None, "ci": [None, None], "p": None, "evidence": "thin", "evidence_tr": EVIDENCE_TR["thin"],
                "note": note or "bu katmanda ölçülecek maç yok", "kind": kind}
    priced = m.get("diff") is not None
    edge = (m.get("edge") if m.get("edge") is not None else m.get("diff")) if priced else m.get("vs_ref")
    ci = (m.get("edge_ci") or m.get("diff_ci")) if priced else m.get("vs_ref_ci")
    ci = list(ci) if ci else [None, None]
    n = int(m["n"])
    p = m.get("p")
    if n < MIN_N:
        ev = "thin"
    elif edge is not None and p is not None and p < ALPHA and abs(edge) >= MIN_EDGE:
        ev = "discovery"
    else:
        ev = "none"
    return {"key": key, "label": label, "n": n, "n_eff": m.get("n_eff"), "actual": m.get("actual"),
            "expected": m.get("market") if priced else m.get("ref"),
            "reference": "market" if priced else ("matched" if m.get("ref") is not None else None),
            "edge": None if edge is None else round(float(edge), 2),
            "ci": [None if v is None else round(float(v), 2) for v in ci],
            "p": None if p is None else round(float(p), 4), "evidence": ev, "evidence_tr": EVIDENCE_TR[ev],
            "note": note, "kind": kind}


def _combine(layers: list[dict]) -> dict:
    """Precision-weighted mean of the usable layers' edges, with an interval that is optimistic
    because the layers overlap — said in the payload, not hidden."""
    use = [l for l in layers if l.get("n", 0) >= MIN_N and l.get("edge") is not None and l["ci"][0] is not None]
    if not use:
        return {"edge": None, "ci": [None, None], "se": None, "n_layers": 0, "layers": []}
    ws, es = [], []
    for l in use:
        se = max((l["ci"][1] - l["ci"][0]) / (2 * 1.96), 1e-6)
        ws.append(1.0 / se ** 2)
        es.append(l["edge"])
    w = np.asarray(ws)
    edge = float(np.average(es, weights=w))
    se = float(np.sqrt(1.0 / w.sum()))
    return {"edge": round(edge, 2), "ci": [round(edge - 1.96 * se, 2), round(edge + 1.96 * se, 2)],
            "se": round(se, 3), "n_layers": len(use), "layers": [l["key"] for l in use]}


def _novig(group: dict | None, pick: str) -> float | None:
    """The margin-free probability of one selection inside a nesine market group."""
    if not group:
        return None
    vals = {k: float(v) for k, v in group.items() if isinstance(v, (int, float)) and float(v) > 1.0}
    if pick not in vals or len(vals) < 2:
        return None
    total = sum(1.0 / v for v in vals.values())
    return round(100.0 * (1.0 / vals[pick]) / total, 2)


def market_today(row: pd.Series, target: str, nesine: dict | None) -> dict:
    """What the market says about the target in THIS match, and where that number came from.

    Football-Data prices 1X2 and 2.5 goals; half-time and İY/MS prices exist only when the match is
    on nesine's bulletin. No price, no number: the payload says "piyasa karşılaştırması mevcut değil"."""
    col = {"ft_1": "p_home", "ft_X": "p_draw", "ft_2": "p_away", "over25": "p_over25"}.get(target)
    if col is not None:
        v = service._f(row.get(col))
        if v is not None:
            odds = service._f(row.get({"ft_1": "cons_h", "ft_X": "cons_d", "ft_2": "cons_a"}.get(target, "")))
            return {"p": round(100 * v, 2), "source": "football-data", "odds": odds}
    path = NESINE_PATH.get(target)
    if path and nesine and not nesine.get("error"):
        grp, pick = path
        p = _novig(nesine.get(grp), pick)
        if p is not None:
            return {"p": p, "source": "nesine", "odds": float(nesine[grp][pick]), "code": nesine.get("code")}
    return {"p": None, "source": None, "odds": None, "note": "Piyasa karşılaştırması mevcut değil."}


# --------------------------------------------------------------------------- the analysis

def analyse(settings: Settings, match_id: str, target: str, side: str = "home", light: bool = False,
            nesine: dict | None = None, k_twins: int = 100) -> dict | None:
    """Every layer, for one match and one target."""
    if target not in TARGETS:
        raise ValueError(f"bilinmeyen hedef: {target}")
    got = service._load(settings)
    if got is None:
        return None
    df = got[0]
    hit = df[df["match_id"] == match_id]
    if hit.empty:
        return None
    row = hit.iloc[0]
    home, away = str(row["home_team"]), str(row["away_team"])
    as_of = row["date"]
    pool = df[df["date"] < as_of]
    sp = state.state_path(settings)
    key = (str(sp), sp.stat().st_mtime)
    base, naive = service._pool_stats(df, key, side, int(pd.Timestamp(as_of).year))
    outcomes = (target,)

    def run(pattern: engine.Pattern) -> dict:
        sub = engine.select(pool, pattern, as_of=as_of)
        refs = service._refs_fast(pool, sub, side, key, naive)
        return engine.run(pool, pattern, outcomes=outcomes, as_of=as_of, base=base, refs=refs)["outcomes"].get(target)

    layers: list[dict] = []
    # 1-2: the two clubs' own history, at this venue
    layers.append(_layer("team", f"{home} · ev sahibi olarak", run(engine.Pattern(team=home, side="home")),
                         note="bu kulübün kendi ev maçları — çoğu zaman birkaç yüz maç, dar bir kanıt"))
    layers.append(_layer("opponent", f"{away} · deplasmanda", run(engine.Pattern(team=away, side="away")),
                         note="rakibin kendi deplasman maçları"))
    # 3-4: the cascade — form + venue + strength, then the opponent described too
    comb = service.combined_for(settings, match_id, side=side, outcomes=outcomes)
    rows = (comb or {}).get("rows") or []
    if rows:
        k = int((comb or {}).get("n_team_steps") or 1)
        team_rows, pair_rows = rows[:k], rows[k:]
        ok_team = [r for r in team_rows if (r["outcomes"].get(target) or {}).get("n", 0) >= MIN_N] or team_rows
        third = ok_team[-1]
        layers.append(_layer("similar", "Tüm benzer durumlar", third["outcomes"].get(target),
                             note=third.get("label", "")))
        ok_pair = [r for r in pair_rows if (r["outcomes"].get(target) or {}).get("n", 0) >= MIN_N]
        if ok_pair:
            last = ok_pair[-1]
            layers.append(_layer("both", "Benzer takım × benzer rakip", last["outcomes"].get(target),
                                 note=last.get("label", "")))
        elif pair_rows:
            last = pair_rows[0]
            layers.append(_layer("both", "Benzer takım × benzer rakip", last["outcomes"].get(target),
                                 note=f"{last.get('label', '')} · rakip tarif edilince örneklem {MIN_N}'ün altına düşüyor"))
    # 5: the twins, with their decay weights and a price-matched reference of their own
    similarity = None
    tq = service.twin_query(settings, match_id, k=k_twins, side=side)
    if tq is not None:
        _, res, _ = tq
        tw = res.rows["twin_weight"].to_numpy(dtype=float) if "twin_weight" in res.rows else None
        refs = service._refs_fast(df, res.rows, side, key, naive)
        m = engine.measure(res.rows, side, target, ref=refs.get(target), w=tw)
        if m.get("diff") is not None and target in base:
            m["edge"] = round(m["diff"] - base[target], 1)
            m["edge_ci"] = [round(m["diff_ci"][0] - base[target], 1), round(m["diff_ci"][1] - base[target], 1)]
            m["p"] = engine.p_from_ci(m["diff"] - base[target], [m["diff_ci"][0] - base[target], m["diff_ci"][1] - base[target]])
        similarity = {"median": res.diagnostics.get("median"), "best": res.diagnostics.get("best"),
                      "worst": res.diagnostics.get("worst"), "k": res.diagnostics.get("k"),
                      "n_above_90": res.diagnostics.get("n_above_90")}
        layers.append(_layer("twins", f"Historical twins · K={res.diagnostics.get('k')}", m,
                             note=f"ortanca benzerlik %{res.diagnostics.get('median')} — benzerlik, olasılık değildir"))
    # 6: the fixture cycle around this match, if the pair table is ready and a cycle exists
    seq_ctx = None
    if not light:
        cyc = sequence.find_cycles(df, home if side == "home" else away, centre_match_id=match_id, min_similarity=60.0)
        best = (cyc.get("cycles") or [None])[0]
        if best:
            seq_ctx = best
            m = cycles.target_layer(settings, df, best["kind"], best["window"], best["similarity"], target, side=side,
                                    ref=naive.get(target))
            if m is None:
                layers.append(_layer("sequence", f"Fikstür döngüsü · {best['kind_tr']} ±{best['window']}", None,
                                     note="döngü çiftleri henüz hazır değil (günlük iş kuruyor)", kind="pending"))
            else:
                layers.append(_layer("sequence", f"Fikstür döngüsü · {best['kind_tr']} ±{best['window']} · %{best['similarity']:g}",
                                     m, note="bu şekle uyan bütün döngülerin merkez maçları"))
    # 7: odds movement, context only
    movement = None if light else _movement(settings, row, target)

    market = market_today(row, target, nesine)
    combined = _combine(layers)
    estimate = None
    if combined["edge"] is not None:
        if market["p"] is not None:
            estimate = {"p": round(market["p"] + combined["edge"], 2),
                        "ci": [round(market["p"] + combined["ci"][0], 2), round(market["p"] + combined["ci"][1], 2)],
                        "basis": "piyasa + katmanların fiyata göre farkı"}
        else:
            use = [l for l in layers if l["key"] in combined["layers"] and l.get("actual") is not None]
            if use:
                est = float(np.mean([l["actual"] for l in use]))
                estimate = {"p": round(est, 2), "ci": [round(est + combined["ci"][0] - combined["edge"], 2),
                                                     round(est + combined["ci"][1] - combined["edge"], 2)],
                            "basis": "katmanların gerçekleşme oranı (fiyat yok; kıyas benzer fiyatlı maçlar)"}
    t = TARGETS[target]
    out = {
        "match": {"id": match_id, "date": str(row["date"])[:10], "league": str(row["league"]),
                  "home": home, "away": away, "side": side},
        "target": {"key": target, "label": t["label"], "group": t["group"], "group_label": t["group_label"],
                   "explain": t["explain"]},
        "market": market, "estimate": estimate, "difference": combined["edge"],
        "difference_ci": combined["ci"], "combined": combined, "similarity": similarity,
        "layers": layers, "movement": movement, "sequence": seq_ctx,
        "discovery": _discovery_context(settings, target),
        "reasons": _reasons(layers, market, combined, similarity, movement, seq_ctx),
        "notes": ["Benzerlik, maçın geçmiş koşullara ne kadar benzediğini gösterir; sonucun gerçekleşme olasılığı değildir.",
                  "Katmanlar birbirinden bağımsız değildir (bir ikiz çoğu zaman aynı form desenine de uyar); "
                  "birleşik aralık bu yüzden iyimserdir.",
                  "Havuzda bulunan bir fark KEŞİF'tir; DOĞRULANDI ve İLERİ TESTTE etiketleri yalnızca üç pencereli "
                  "taramadan gelir."],
    }
    out["evidence"] = _overall_evidence(layers, out["discovery"])
    return out


def _movement(settings: Settings, row: pd.Series, target: str) -> dict | None:
    """The odds-movement class on the selection the target belongs to, when the archive saw it."""
    try:
        from ..web.api import _nesine_brief                # noqa: PLC0415
        brief = _nesine_brief(str(row["date"])[:10], str(row["home_team"]), str(row["away_team"]))
    except Exception:                                       # noqa: BLE001 - context is never load-bearing
        return None
    code = (brief or {}).get("code")
    if not code:
        return None
    from ..nesine import movement as mv

    path = {"ft_1": "ms.1", "ft_X": "ms.X", "ft_2": "ms.2"}.get(target)
    try:
        out = mv.for_match(settings, int(code), cfg=mv.config_from_env())
    except Exception:                                       # noqa: BLE001
        return None
    sel = (out.get("selections") or {}).get(path or "ms.1") or {}
    v = sel.get("movement") or {}
    if not v.get("type"):
        return None
    support = None
    if path:
        support = v["type"] in ("STEAM",) and v.get("confidence") != "low"
    return {"path": path or "ms.1", "type": v["type"], "total_pp": v.get("total_pp"), "confidence": v.get("confidence"),
            "tags": v.get("tags"), "support": support,
            "note": "hareket sınıfı bir şekildir, oran değil" if path else "bu hedef için oran hareketi ölçülmüyor; maç sonucu (1) gösteriliyor"}


def _discovery_context(settings: Settings, target: str) -> dict | None:
    """Which offline discovery claims are about this target, and how far each got — target-aware
    discovery without re-running the scan per request."""
    want = DISCOVERY_OUTCOME.get(target)
    files = service.research_files(settings)
    claims = ((files.get("discovery") or {}).get("claims")) or []
    if not want or not claims:
        return None
    o, s = want
    mine = [c for c in claims if c.get("outcome") == o and c.get("side") == s]
    surv = [c for c in mine if c.get("stage") == "survived"]
    return {"outcome": o, "side": s, "n_claims": len(mine), "survived": [
        {"label": c.get("label"), "edge": c.get("edge_test"), "n": c.get("n_test"), "q": c.get("q_test")} for c in surv],
        "stages": {k: sum(1 for c in mine if c.get("stage") == k) for k in sorted({c.get("stage") for c in mine})}}


def _overall_evidence(layers: list[dict], disc: dict | None) -> dict:
    keys = [l["evidence"] for l in layers if l.get("kind") == "claim"]
    if disc and disc.get("survived"):
        ev = "tested"
    elif "discovery" in keys:
        ev = "discovery"
    elif all(k == "thin" for k in keys) or not keys:
        ev = "thin"
    else:
        ev = "none"
    return {"key": ev, "label": EVIDENCE_TR[ev],
            "why": {"tested": "üç pencereli taramada bu hedefle ilgili en az bir desen sağ kaldı",
                    "discovery": "en az bir katman havuzda sıfırı dışlıyor — bu bir keşiftir, doğrulama değil",
                    "thin": "hiçbir katman 200 maça ulaşmıyor", "none": "hiçbir katman fiyattan ayrılmıyor"}[ev]}


def _reasons(layers, market, combined, similarity, movement, seq) -> dict:
    """DESTEKLEYENLER / DİKKAT EDİLMESİ GEREKENLER, from the numbers only."""
    pro, con = [], []
    for l in layers:
        if l.get("kind") != "claim":
            continue
        lo, hi = l["ci"]
        if l["n"] < MIN_N:
            con.append(f"{l['label']}: örneklem küçük (N = {l['n']})")
        elif lo is not None and lo > 0:
            pro.append(f"{l['label']}: hedef fiyatın {l['edge']:+.1f} puan üstünde (N = {l['n']}, aralık sıfırı dışlıyor)")
        elif hi is not None and hi < 0:
            con.append(f"{l['label']}: hedef fiyatın {l['edge']:+.1f} puan altında (N = {l['n']})")
        elif l["reference"] == "matched":
            con.append(f"{l['label']}: fiyat yok, kıyas benzer fiyatlı maçlar (fark {l['edge']:+.1f})")
    if combined.get("ci") and combined["ci"][0] is not None and (combined["ci"][1] - combined["ci"][0]) > WIDE_CI:
        con.append(f"Birleşik aralık geniş ({combined['ci'][0]:+.1f} … {combined['ci'][1]:+.1f} puan)")
    if market.get("p") is None:
        con.append("Piyasa karşılaştırması mevcut değil")
    elif market["p"] < LOW_ABS:
        con.append(f"Hedef düşük mutlak olasılıklı (piyasa %{market['p']:.1f})")
    if movement is None:
        con.append("Oran hareketi desteği yok (arşivde kayıt yok)")
    elif movement.get("support"):
        pro.append(f"Oran hareketi hedef yönünde ({movement['type']}, {movement.get('total_pp')} puan)")
    elif movement.get("support") is False:
        con.append(f"Oran hareketi hedefi desteklemiyor ({movement['type']})")
    if similarity and similarity.get("median") is not None and similarity["median"] < 70:
        con.append(f"İkizlerin ortanca benzerliği düşük (%{similarity['median']})")
    if seq:
        pro.append(f"Fikstür döngüsü var: {seq['kind_tr']} ±{seq['window']} %{seq['similarity']:g} — benzerlik, olasılık değil")
    return {"pro": pro, "con": con}


# --------------------------------------------------------------------------- mode 2: the day scan

_JOBS: dict[tuple, dict] = {}
_JOBS_LOCK = threading.Lock()
RELEVANCE_NOTE = ("Sıralama bir bahis skoru değildir: |fark| / standart hata, kullanılabilir katman payı ve keşif "
                  "taramasında sağ kalan desen varlığıyla çarpılır — yani 'araştırmaya değer' sırasıdır.")


def _relevance(a: dict) -> dict:
    c = a.get("combined") or {}
    z = 0.0 if c.get("se") in (None, 0) or c.get("edge") is None else abs(c["edge"]) / c["se"]
    claims = [l for l in a["layers"] if l.get("kind") == "claim"]
    quality = (sum(1 for l in claims if l["n"] >= MIN_N) / len(claims)) if claims else 0.0
    tested = 1.25 if a.get("evidence", {}).get("key") == "tested" else 1.0
    score = z * (0.5 + 0.5 * quality) * tested
    return {"score": round(score, 2), "z": round(z, 2), "quality": round(quality, 2), "tested": tested > 1}


def _summary_row(m: dict, a: dict) -> dict:
    return {"id": m["id"], "home": m["home"], "away": m["away"], "league": m.get("league"),
            "league_name": m.get("league_name"), "date": m.get("date"), "time": m.get("time"),
            "market": a["market"], "estimate": a["estimate"], "difference": a["difference"],
            "difference_ci": a["difference_ci"], "similarity": (a.get("similarity") or {}).get("median"),
            "evidence": a["evidence"], "n_layers": (a.get("combined") or {}).get("n_layers", 0),
            "layers": [{"key": l["key"], "n": l["n"], "edge": l["edge"], "evidence": l["evidence"]} for l in a["layers"]],
            "relevance": _relevance(a)}


def start_day_scan(settings: Settings, date: str, target: str, matches: list[dict], nesine_by_id: dict | None = None) -> dict:
    """Start (or return) the background scan of one day's matches for one target."""
    sp = state.state_path(settings)
    key = (date, target, sp.stat().st_mtime if sp.exists() else 0)
    with _JOBS_LOCK:
        job = _JOBS.get(key)
        if job and (job["state"] == "running" or job["state"] == "done"):
            return job
        job = {"date": date, "target": target, "state": "running", "total": len(matches), "done": 0, "rows": [],
               "errors": 0, "started_at": dt.datetime.now(dt.timezone.utc).isoformat(), "finished_at": None,
               "note": RELEVANCE_NOTE}
        if len(_JOBS) > 12:
            for k in list(_JOBS)[:-6]:
                _JOBS.pop(k, None)
        _JOBS[key] = job

    def work():
        for m in matches:
            try:
                a = analyse(settings, m["id"], target, light=True, nesine=(nesine_by_id or {}).get(m["id"]))
                if a is not None:
                    job["rows"].append(_summary_row(m, a))
            except Exception as exc:                        # noqa: BLE001 - one match must not stop the day
                job["errors"] += 1
                log.warning("day scan %s %s: %s", m.get("id"), target, exc)
            job["done"] += 1
        job["rows"].sort(key=lambda r: -r["relevance"]["score"])
        job["state"] = "done"
        job["finished_at"] = dt.datetime.now(dt.timezone.utc).isoformat()

    threading.Thread(target=work, name=f"lab-scan-{date}-{target}", daemon=True).start()
    return job


def day_scan_status(settings: Settings, date: str, target: str) -> dict | None:
    sp = state.state_path(settings)
    key = (date, target, sp.stat().st_mtime if sp.exists() else 0)
    return _JOBS.get(key)


# --------------------------------------------------------------------------- mode 3: your own pattern

STRENGTH_BANDS = {"weak": (0.0, 25.0), "mid": (25.0, 50.0), "strong": (50.0, 80.0), "top": (80.0, 100.0)}
STRENGTH_TR = {"weak": "zayıf", "mid": "orta", "strong": "güçlü", "top": "çok güçlü"}
GOAL_COLS = {"gf5": "gf5", "ga5": "ga5", "btts5": "btts5", "ov15_5": "ov15_5", "ov25_5": "ov25_5", "ov35_5": "ov35_5"}
GOAL_TR = {"gf5": "son 5'te attığı gol", "ga5": "son 5'te yediği gol", "btts5": "son 5'te KG olan maç",
           "ov15_5": "son 5'te 1,5 üst maç", "ov25_5": "son 5'te 2,5 üst maç", "ov35_5": "son 5'te 3,5 üst maç"}


def _band(v) -> tuple[float, float] | None:
    if v is None:
        return None
    if isinstance(v, str) and v in STRENGTH_BANDS:
        return STRENGTH_BANDS[v]
    if isinstance(v, (list, tuple)) and len(v) == 2 and v[0] is not None and v[1] is not None:
        return (float(v[0]), float(v[1]))
    return None


def own_pattern(settings: Settings, spec: dict, outcomes: tuple[str, ...] | None = None, sample: int = 25) -> dict | None:
    """The reader's own conditions, added one at a time, each row measured against the price.

    `spec` keys (all optional): side, form, venue_form, approx, strength, opp_form, opp_venue_form,
    opp_strength, gap [lo, hi], leagues, goals {gf5: [lo,hi], ...}, role, market [lo, hi] (probability),
    movement. The order the conditions are added is the order a reader thinks: the team, then the
    opponent, then the match, then the goals, then the market."""
    got = service._load(settings)
    if got is None:
        return None
    df = got[0]
    side = spec.get("side") or "home"
    p = "h_" if side == "home" else "a_"
    approx = int(spec.get("approx") or 0)
    outcomes = outcomes or service.PATTERN_OUTCOMES
    steps: list[tuple[str, engine.Pattern]] = []
    at = engine.Pattern(side=side, approx=approx, form=(spec.get("form") or None))
    who = "Ev sahibi" if side == "home" else "Deplasman"
    steps.append((f"{who}" + (f" formu {at.form}" if at.form else " · bütün maçlar"), at))
    if spec.get("venue_form"):
        at = replace(at, venue_form=str(spec["venue_form"]).upper())
        steps.append((f"+ {'ev' if side == 'home' else 'deplasman'} formu {at.venue_form}", at))
    if (b := _band(spec.get("strength"))):
        at = replace(at, tsi_pct=b)
        steps.append((f"+ takım gücü {STRENGTH_TR.get(spec.get('strength'), '')} (%{b[0]:g}–%{b[1]:g})".replace("  ", " "), at))
    if spec.get("opp_form"):
        at = replace(at, opp_form=str(spec["opp_form"]).upper())
        steps.append((f"+ rakip formu {at.opp_form}", at))
    if spec.get("opp_venue_form"):
        at = replace(at, opp_venue_form=str(spec["opp_venue_form"]).upper())
        steps.append((f"+ rakip saha formu {at.opp_venue_form}", at))
    if (b := _band(spec.get("opp_strength"))):
        at = replace(at, opp_tsi_pct=b)
        steps.append((f"+ rakip gücü {STRENGTH_TR.get(spec.get('opp_strength'), '')} (%{b[0]:g}–%{b[1]:g})".replace("  ", " "), at))
    if (b := _band(spec.get("gap"))):
        at = replace(at, gap=b)
        steps.append((f"+ güç farkı {b[0]:+g} … {b[1]:+g}", at))
    if spec.get("leagues"):
        lg = [x for x in spec["leagues"] if x]
        if lg:
            at = replace(at, leagues=lg)
            steps.append((f"+ lig {'/'.join(lg)}", at))
    for gk, rng in (spec.get("goals") or {}).items():
        b = _band(rng)
        if gk in GOAL_COLS and b:
            at = replace(at, extra={**at.extra, f"{p}{GOAL_COLS[gk]}": b})
            steps.append((f"+ {GOAL_TR[gk]} {b[0]:g}–{b[1]:g}", at))
    if spec.get("role") in ("favorite", "underdog"):
        at = replace(at, role=spec["role"])
        steps.append(("+ favori" if spec["role"] == "favorite" else "+ sürpriz adayı", at))
    if (b := _band(spec.get("market"))):
        at = replace(at, market=b)
        steps.append((f"+ oranı {1 / b[1]:.2f}–{1 / b[0]:.2f} (olasılık %{100 * b[0]:.0f}–%{100 * b[1]:.0f})", at))
    if spec.get("movement") in ("steam", "drift", "stable"):
        at = replace(at, movement=spec["movement"])
        steps.append(("+ " + {"steam": "oran kapanışa doğru düştü", "drift": "oran kapanışa doğru yükseldi",
                              "stable": "oran sabit kaldı"}[spec["movement"]], at))

    sp = state.state_path(settings)
    key = (str(sp), sp.stat().st_mtime)
    year = int(pd.Timestamp(df["date"].max()).year) + 1
    base, naive = service._pool_stats(df, key, side, year)
    refs = service._refs_fast(df, engine.select(df, steps[0][1]), side, key, naive)
    rows = engine.cascade(df, steps, outcomes=outcomes, base=base, refs=refs)
    final = rows[-1] if rows else None
    if final is not None and sample:
        sub = engine.select(df, steps[-1][1])
        cols = [c for c in ("date", "league", "home_team", "away_team", "ftr", "fthg", "ftag", "h_form", "a_form") if c in sub]
        smp = sub.sort_values("date", ascending=False).head(sample)[cols].copy()
        if "date" in smp:
            smp["date"] = smp["date"].astype(str).str[:10]
        final["sample"] = smp.to_dict("records")
    return {"side": side, "label": steps[-1][1].label(), "steps": [s for s, _ in steps], "rows": rows,
            "outcomes": list(outcomes), "pool": int(len(df)),
            "span": [str(df["date"].min())[:10], str(df["date"].max())[:10]],
            "n_tests": len(rows) * len(outcomes),
            "note": "Her satır bir öncekinin alt kümesi. Farkı hangi koşulun yarattığını satırlar arasında oku; "
                    "N düşerken fark büyümüyorsa koşul bilgi değil belirsizlik eklemiştir."}


# --------------------------------------------------------------------------- team search

_TEAMS: dict = {"key": None, "rows": None}


def teams(settings: Settings, q: str = "", limit: int = 20) -> list[dict]:
    """Clubs in the database, with their league and last season — for the cycle mode's picker."""
    df = service.frame(settings)
    if df is None:
        return []
    sp = state.state_path(settings)
    key = sp.stat().st_mtime
    if _TEAMS["key"] != key:
        h = df[["home_team", "league", "season", "date"]].rename(columns={"home_team": "team"})
        a = df[["away_team", "league", "season", "date"]].rename(columns={"away_team": "team"})
        both = pd.concat([h, a], ignore_index=True)
        both["team"] = both["team"].astype(str)
        g = both.sort_values("date").groupby("team", sort=False)
        rows = pd.DataFrame({"league": g["league"].last().astype(str), "season": g["season"].last().astype(str),
                             "n": g.size(), "last": g["date"].last().astype(str).str[:10]}).reset_index()
        _TEAMS.update(key=key, rows=rows)
    rows = _TEAMS["rows"]
    if q:
        ql = q.strip().casefold()
        rows = rows[rows["team"].str.casefold().str.contains(ql, regex=False)]
    rows = rows.sort_values(["last", "n"], ascending=[False, False]).head(limit)
    return rows.to_dict("records")
