"""FIXTURE CYCLE MEASUREMENT — "bu döngü geçmişte işe yaramış mı?"

`sequence.py` finds the cycles of ONE club: the runs of opponents around a centre match that repeat
an earlier season forwards, backwards or shifted. Finding one is not evidence of anything — a
similarity is a description of the fixture list, not a probability — so this module asks the only
question that makes a cycle worth showing: across every club and every season in the database,
when a run like this repeated, did the centre result behave the way the graphics claim?

Two claims are tested, both automatically:

    REPEAT   the new centre match ended the way the old one did           (same / shifted / strength runs)
    MIRROR   the new centre match ended the opposite way (1 ↔ 2, X stays)   (reversed runs)

and, where half-time scores exist, the mirror of a half-time reversal (1/2 ↔ 2/1). Every claim is
measured against the market's price for that same outcome in the new centre match, with the paired
interval the whole package uses, at three levels: this club, every club, clubs of comparable
strength at the time. The evidence label follows the discovery rules: a claim measured on the whole
pool is a KEŞİF, it is DOĞRULANDI only when the validation window repeats it with the same sign,
and İLERİ TESTTE only when the untouched test window does too.

The pair table is expensive (a few million pairs), so it is built once per state table — inside
the daily job, or lazily on first request — and cached on disk keyed on the state table's own
modification time.
"""

from __future__ import annotations

import datetime as dt
import json
import threading
from pathlib import Path

import numpy as np
import pandas as pd

from ..config import Settings
from ..logging_setup import get_logger
from . import engine
from .discovery import DEFAULT_WINDOWS, Windows
from .sequence import KIND_TR, KINDS, STRENGTH_SCALE, WINDOWS

log = get_logger("patterns.cycles")

W_MAX = max(WINDOWS)
MIN_SIMILARITY = 60.0        # a pair below this is not stored: one shared club out of two is not a cycle
MIN_COMPARED = 3             # ... and neither is a two-slot comparison, however well it scores
MIN_N = 200
MIN_EDGE = 1.0
ALPHA = 0.05
BAND = 10.0                  # ± percentile points of strength that count as "comparable"
GROUPS_PER_CHUNK = 1500      # (team, opponent) groups scored together — bounds the pair matrices

FLIP = {"W": "L", "L": "W", "D": "D"}
HTFT_MIRROR = {"2/1": "1/2", "1/2": "2/1"}
HYPOTHESIS = {"EXACT_SAME": "repeat", "SHIFTED": "repeat", "STRENGTH": "repeat", "EXACT_REVERSE": "mirror"}
HYPOTHESIS_TR = {"repeat": "merkez maçın sonucu tekrarladı", "mirror": "merkez maçın sonucu ters döndü (1 ↔ 2)"}
EVIDENCE_TR = {"thin": "YETERSİZ VERİ", "discovery": "KEŞİF", "confirmed": "DOĞRULANDI", "tested": "İLERİ TESTTE"}


# --------------------------------------------------------------------------- the long table

def long_table(df: pd.DataFrame) -> pd.DataFrame:
    """Two rows per match — one from each club's view — with the opponents ±4 around it.

    Everything the pairing needs is on the row, vectorised over the whole database: who came before
    and after (clipped to the season, so a run never crosses into the previous one), how strong
    they were, what the club did in the centre match, and what the market said it would do."""
    cols = {c: df[c].to_numpy() for c in ("match_id", "date", "league", "season", "home_team", "away_team",
                                            "ftr", "htr", "p_home", "p_draw", "p_away") if c in df}
    n = len(df)
    num = lambda c: pd.to_numeric(df[c], errors="coerce").to_numpy(dtype=float) if c in df else np.full(n, np.nan)  # noqa: E731
    H, A = df["home_team"].astype(str).to_numpy(), df["away_team"].astype(str).to_numpy()
    ftr, htr = df["ftr"].astype(str).to_numpy(), (df["htr"].astype(str).to_numpy() if "htr" in df else np.full(n, ""))
    code = {"H": "1", "D": "X", "A": "2"}
    ht_known = np.isin(htr, ["H", "D", "A"])
    ft_known = np.isin(ftr, ["H", "D", "A"])

    def side(is_home: bool) -> pd.DataFrame:
        team, opp = (H, A) if is_home else (A, H)
        win, loss = ("H", "A") if is_home else ("A", "H")
        res = np.where(ftr == win, "W", np.where(ftr == "D", "D", np.where(ftr == loss, "L", "")))
        htft = np.array([f"{code[h]}/{code[f]}" if k and kf else "" for h, f, k, kf in zip(htr, ftr, ht_known, ft_known)], dtype=object)
        if not is_home:                           # the same combination read from the away side
            flip = {"1": "2", "2": "1", "X": "X"}
            htft = np.array([f"{flip[x[0]]}/{flip[x[2]]}" if x else "" for x in htft], dtype=object)
        p_w, p_l = (num("p_home"), num("p_away")) if is_home else (num("p_away"), num("p_home"))
        o_w, o_l = (num("cons_h"), num("cons_a")) if is_home else (num("cons_a"), num("cons_h"))
        c_w, c_l = (num("avgc_h"), num("avgc_a")) if is_home else (num("avgc_a"), num("avgc_h"))
        tsi, opp_tsi = (num("h_tsi_pct"), num("a_tsi_pct")) if is_home else (num("a_tsi_pct"), num("h_tsi_pct"))
        return pd.DataFrame({
            "team": team, "opp": opp, "match_id": cols["match_id"], "date": pd.to_datetime(cols["date"]),
            "league": df["league"].astype(str).to_numpy(), "season": df["season"].astype(str).to_numpy(),
            "venue": "home" if is_home else "away", "res": res, "htft": htft,
            "p_win": p_w, "p_draw": num("p_draw"), "p_loss": p_l,
            "odds_win": o_w, "odds_draw": num("cons_d"), "odds_loss": o_l,
            "close_win": c_w, "close_draw": num("avgc_d"), "close_loss": c_l,
            "tsi": tsi, "opp_tsi": opp_tsi,
        })

    out = pd.concat([side(True), side(False)], ignore_index=True)
    out = out.sort_values(["team", "date", "match_id"], kind="mergesort").reset_index(drop=True)
    out["opp_code"] = pd.factorize(out["opp"])[0]
    g = out.groupby("team", sort=False)
    season = out["season"].to_numpy()
    for k in range(1, W_MAX + 1):
        for name, sh in (("prev", k), ("next", -k)):
            same = (g["season"].shift(sh).to_numpy() == season)
            oc = g["opp_code"].shift(sh).to_numpy()
            out[f"{name}{k}"] = np.where(same & np.isfinite(oc), oc, -1).astype(np.int32)
            st = g["opp_tsi"].shift(sh).to_numpy()
            out[f"{name}{k}_tsi"] = np.where(same, st, np.nan).astype(np.float32)
    return out


SLOT_COLS = [f"prev{k}" for k in range(W_MAX, 0, -1)] + ["opp_code"] + [f"next{k}" for k in range(1, W_MAX + 1)]
TSI_COLS = [f"prev{k}_tsi" for k in range(W_MAX, 0, -1)] + ["opp_tsi"] + [f"next{k}_tsi" for k in range(1, W_MAX + 1)]


# --------------------------------------------------------------------------- pairing and scoring

def _pairs_in_groups(long: pd.DataFrame, starts: np.ndarray, ends: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """(past index, now index) for every pair inside each (team, opponent) group of the batch."""
    ps, ns = [], []
    for s, e in zip(starts, ends):
        k = e - s
        if k < 2:
            continue
        i, j = np.triu_indices(k, 1)
        ps.append(s + i)
        ns.append(s + j)
    if not ps:
        return np.array([], dtype=int), np.array([], dtype=int)
    return np.concatenate(ps), np.concatenate(ns)


def _positional(now: np.ndarray, past: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Share of the offsets both runs have where the opponent is the same, and how many those were."""
    shared = (now >= 0) & (past >= 0)
    hit = shared & (now == past)
    n = shared.sum(axis=1)
    return np.where(n > 0, 100.0 * hit.sum(axis=1) / np.maximum(n, 1), 0.0), n


def _wing(now: np.ndarray, past: np.ndarray, centre: int) -> np.ndarray:
    """The same clubs before and the same clubs after, order inside each wing ignored (0-100)."""
    shared = (now >= 0) & (past >= 0)
    n = shared.sum(axis=1)
    hits = np.zeros(len(now))
    for lo, hi in ((0, centre), (centre + 1, now.shape[1])):
        a, b = np.where(shared[:, lo:hi], now[:, lo:hi], -1), np.where(shared[:, lo:hi], past[:, lo:hi], -2)
        hits += ((a[:, :, None] == b[:, None, :]) & (a[:, :, None] >= 0)).any(axis=2).sum(axis=1)
    hits += (shared[:, centre] & (now[:, centre] == past[:, centre]))
    return np.where(n > 0, 100.0 * hits / np.maximum(n, 1), 0.0)


def _score_batch(long: pd.DataFrame, pi: np.ndarray, ni: np.ndarray) -> pd.DataFrame:
    """Every window and every shape for a batch of (past, now) pairs, vectorised."""
    S = long[SLOT_COLS].to_numpy(dtype=np.int32)
    T = long[TSI_COLS].to_numpy(dtype=float)
    past_all, now_all = S[pi], S[ni]
    tp_all, tn_all = T[pi], T[ni]
    rows = []
    for w in WINDOWS:
        lo, hi = W_MAX - w, W_MAX + w + 1
        past, now = past_all[:, lo:hi], now_all[:, lo:hi]
        centre = w
        pos, n_same = _positional(now, past)
        wing = _wing(now, past, centre)
        flipped = past[:, ::-1]
        rpos, n_rev = _positional(now, flipped)
        rwing = _wing(now, flipped, centre)
        best, n_best = np.zeros(len(pi)), np.zeros(len(pi), dtype=int)
        for k in range(-w, w + 1):
            if k == 0:
                continue
            rolled = np.full_like(past, -1)
            if k > 0:
                rolled[:, :-k] = past[:, k:]
            else:
                rolled[:, -k:] = past[:, :k]
            sc, sn = _positional(now, rolled)
            better = (sn > 0) & (sc > best)
            best, n_best = np.where(better, sc, best), np.where(better, sn, n_best)
        tp, tn = tp_all[:, lo:hi], tn_all[:, lo:hi]
        ok = np.isfinite(tp) & np.isfinite(tn)
        ok[:, centre] = False                     # the centre opponent is the same club by construction
        n_st = ok.sum(axis=1)
        diff = np.where(ok, np.abs(tp - tn), 0.0).sum(axis=1) / np.maximum(n_st, 1)
        st = np.where(n_st >= 2, 100.0 * np.maximum(0.0, 1.0 - diff / STRENGTH_SCALE), np.nan)
        for kind, sim, p, wg, n in (("EXACT_SAME", pos, pos, wing, n_same),
                                    ("EXACT_REVERSE", np.maximum(rpos, rwing), rpos, rwing, n_rev),
                                    ("SHIFTED", best, best, wing, n_best),
                                    ("STRENGTH", st, pos, wing, n_st)):
            keep = np.isfinite(sim) & (sim >= MIN_SIMILARITY) & (n >= MIN_COMPARED)
            if not keep.any():
                continue
            rows.append(pd.DataFrame({"pi": pi[keep], "ni": ni[keep], "kind": kind, "window": w,
                                      "similarity": np.round(sim[keep], 1), "positional": np.round(p[keep], 1),
                                      "wing": np.round(wg[keep], 1), "n_compared": n[keep]}))
    return pd.concat(rows, ignore_index=True) if rows else pd.DataFrame(
        columns=["pi", "ni", "kind", "window", "similarity", "positional", "wing", "n_compared"])


def pair_table(df: pd.DataFrame, log_every: int = 20) -> pd.DataFrame:
    """Every (past run, current run) pair of the same club around the same opponent, in different
    seasons, scored for every window and shape, kept when it resembles a cycle at all."""
    long = long_table(df)
    played = long["res"].isin(["W", "D", "L"]).to_numpy()
    order = np.lexsort((long["date"].to_numpy(), long["opp_code"].to_numpy(), long["team"].to_numpy()))
    long = long.iloc[order].reset_index(drop=True)
    played = played[order]
    key = long["team"].astype(str).to_numpy() + "\x00" + long["opp_code"].astype(str).to_numpy()
    change = np.flatnonzero(np.r_[True, key[1:] != key[:-1]])
    starts, ends = change, np.r_[change[1:], len(long)]
    season, date = long["season"].to_numpy(), long["date"].to_numpy()
    out = []
    n_chunks = int(np.ceil(len(starts) / GROUPS_PER_CHUNK))
    for c in range(n_chunks):
        if log_every and c and c % log_every == 0:
            log.info("cycle pairs: chunk %d / %d", c, n_chunks)
        sl = slice(c * GROUPS_PER_CHUNK, (c + 1) * GROUPS_PER_CHUNK)
        pi, ni = _pairs_in_groups(long, starts[sl], ends[sl])
        if not len(pi):
            continue
        ok = (season[pi] != season[ni]) & (date[pi] < date[ni]) & played[pi]
        pi, ni = pi[ok], ni[ok]
        if not len(pi):
            continue
        out.append(_score_batch(long, pi, ni))
    pairs = pd.concat(out, ignore_index=True) if out else _score_batch(long, np.array([], int), np.array([], int))
    return _attach(long, pairs)


def _attach(long: pd.DataFrame, pairs: pd.DataFrame) -> pd.DataFrame:
    """Add what each claim needs: both centre results, the market's price for the claimed outcome."""
    p, n = long.iloc[pairs["pi"].to_numpy()], long.iloc[pairs["ni"].to_numpy()]
    out = pairs.drop(columns=["pi", "ni"]).copy()
    out["team"], out["opp"], out["league"] = p["team"].to_numpy(), p["opp"].to_numpy(), n["league"].to_numpy()
    out["past_match_id"], out["now_match_id"] = p["match_id"].to_numpy(), n["match_id"].to_numpy()
    out["past_season"], out["now_season"] = p["season"].to_numpy(), n["season"].to_numpy()
    out["past_date"], out["now_date"] = p["date"].to_numpy(), n["date"].to_numpy()
    out["past_res"], out["now_res"] = p["res"].to_numpy(), n["res"].to_numpy()
    out["past_htft"], out["now_htft"] = p["htft"].to_numpy(), n["htft"].to_numpy()
    out["now_venue"], out["tsi"] = n["venue"].to_numpy(), n["tsi"].to_numpy()
    played = np.isin(out["now_res"].to_numpy(), ["W", "D", "L"])
    past_res = out["past_res"].to_numpy()
    mirror_res = np.array([FLIP.get(r, "") for r in past_res])

    def price(which: np.ndarray, col: str) -> np.ndarray:
        sel = {"W": n[f"{col}_win"].to_numpy(dtype=float), "D": n[f"{col}_draw"].to_numpy(dtype=float),
               "L": n[f"{col}_loss"].to_numpy(dtype=float)}
        return np.select([which == "W", which == "D", which == "L"], [sel["W"], sel["D"], sel["L"]], np.nan)

    now_res = out["now_res"].to_numpy()
    out["repeat_hit"] = np.where(played, (now_res == past_res).astype(float), np.nan)
    out["repeat_p"] = price(past_res, "p")
    out["repeat_odds"], out["repeat_close"] = price(past_res, "odds"), price(past_res, "close")
    out["mirror_hit"] = np.where(played, (now_res == mirror_res).astype(float), np.nan)
    out["mirror_p"] = price(mirror_res, "p")
    out["mirror_odds"], out["mirror_close"] = price(mirror_res, "odds"), price(mirror_res, "close")
    past_ht, now_ht = out["past_htft"].to_numpy(), out["now_htft"].to_numpy()
    rev = np.isin(past_ht, list(HTFT_MIRROR)) & (now_ht != "")
    out["ht_mirror_hit"] = np.where(rev, (now_ht == np.array([HTFT_MIRROR.get(x, "") for x in past_ht])).astype(float), np.nan)
    for c in ("similarity", "positional", "wing", "repeat_p", "mirror_p", "tsi",
              "repeat_odds", "repeat_close", "mirror_odds", "mirror_close", "repeat_hit", "mirror_hit", "ht_mirror_hit"):
        out[c] = out[c].astype(np.float32)
    out["window"], out["n_compared"] = out["window"].astype(np.int8), out["n_compared"].astype(np.int8)
    # two million rows of repeated strings: categories cut the table to a fraction of its object size
    for c in ("kind", "team", "opp", "league", "past_match_id", "now_match_id", "past_season", "now_season",
              "past_res", "now_res", "past_htft", "now_htft", "now_venue"):
        out[c] = out[c].astype("category")
    return out.reset_index(drop=True)


# --------------------------------------------------------------------------- the cache

_MEM: dict = {"key": None, "pairs": None, "ht_ref": None}
_BUILD_LOCK = threading.Lock()


def cache_path(settings: Settings) -> Path:
    return settings.results_dir / "backtest" / "cycle_pairs.parquet"


def build(settings: Settings, df: pd.DataFrame | None = None) -> pd.DataFrame:
    """Compute the pair table for the current state table and write it next to the research files."""
    from . import service, state

    if df is None:
        df = service.frame(settings)
    if df is None:
        raise FileNotFoundError("durum tablosu yok")
    sp = state.state_path(settings)
    started = dt.datetime.now()
    pairs = pair_table(df)
    p = cache_path(settings)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + ".tmp")      # atomic: the lab reads this table while the job rewrites it
    pairs.to_parquet(tmp, index=False)
    tmp.replace(p)
    meta = {"state_mtime": sp.stat().st_mtime if sp.exists() else None, "n_pairs": int(len(pairs)),
            "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
            "seconds": round((dt.datetime.now() - started).total_seconds(), 1)}
    p.with_suffix(".json").write_text(json.dumps(meta), encoding="utf-8")
    log.info("cycle pairs: %d rows in %.0fs -> %s", len(pairs), meta["seconds"], p)
    _MEM.update(key=meta["state_mtime"], pairs=pairs, ht_ref=_ht_reference(df))
    return pairs


def pairs_for(settings: Settings, build_if_missing: bool = True) -> pd.DataFrame | None:
    """The cached pair table for the current state table, or None when it is not ready yet."""
    from . import service, state

    sp = state.state_path(settings)
    if not sp.exists():
        return None
    key = sp.stat().st_mtime
    if _MEM["key"] == key and _MEM["pairs"] is not None:
        return _MEM["pairs"]
    p = cache_path(settings)
    meta_p = p.with_suffix(".json")
    if p.exists() and meta_p.exists():
        try:
            meta = json.loads(meta_p.read_text(encoding="utf-8"))
            if meta.get("state_mtime") == key:
                df = service.frame(settings)
                _MEM.update(key=key, pairs=pd.read_parquet(p), ht_ref=_ht_reference(df) if df is not None else None)
                return _MEM["pairs"]
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            log.warning("cycle pairs cache unreadable: %s", exc)
    if not build_if_missing:
        return None
    with _BUILD_LOCK:
        if _MEM["key"] == key and _MEM["pairs"] is not None:
            return _MEM["pairs"]
        return build(settings)


def status(settings: Settings) -> dict:
    p = cache_path(settings).with_suffix(".json")
    try:
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {"n_pairs": 0}
    except (OSError, json.JSONDecodeError):
        return {"n_pairs": 0}


def _ht_reference(df: pd.DataFrame) -> dict[str, float]:
    """How often a club's centre match is a half-time reversal at all — the reference for the HT/FT
    mirror claim, which has no price of its own."""
    if df is None or "htr" not in df:
        return {}
    htr, ftr = df["htr"].astype(str).to_numpy(), df["ftr"].astype(str).to_numpy()
    known = np.isin(htr, ["H", "D", "A"]) & np.isin(ftr, ["H", "D", "A"])
    if not known.any():
        return {}
    rev = known & (htr != "D") & (ftr != "D") & (htr != ftr)
    # one direction, from one club's view: a 2/1 for the home side is a 1/2 for the away side
    return {"one_direction": float(rev.sum() / known.sum()) / 2.0, "n": int(known.sum())}


# --------------------------------------------------------------------------- the measurement

def _claim(sub: pd.DataFrame, hypothesis: str, ht_ref: dict | None = None) -> dict:
    """One claim over a set of pairs, in the package's standard shape (actual / market / edge / CI)."""
    if hypothesis == "ht_mirror":
        m = engine.paired_measure(sub["ht_mirror_hit"].to_numpy(), np.full(len(sub), np.nan),
                                  ref=(ht_ref or {}).get("one_direction"))
    else:
        m = engine.paired_measure(sub[f"{hypothesis}_hit"].to_numpy(), sub[f"{hypothesis}_p"].to_numpy(dtype=float))
    edge = m.get("diff") if m.get("diff") is not None else m.get("vs_ref")
    ci = m.get("diff_ci") if m.get("diff") is not None else m.get("vs_ref_ci")
    return {"n": m["n"], "actual": m.get("actual"), "market": m.get("market"), "ref": m.get("ref"),
            "edge": edge, "ci": ci, "p": m.get("p"), "n_market": m.get("n_market")}


def evidence(full: dict, train: dict, val: dict, test: dict, min_n: int = MIN_N, alpha: float = ALPHA,
             min_edge: float = MIN_EDGE) -> str:
    """KEŞİF / DOĞRULANDI / İLERİ TESTTE / YETERSİZ VERİ, by the discovery rules.

    A claim that clears zero on the whole pool is a discovery and nothing more. It is confirmed when
    the validation window repeats it with the same sign, and tested when the untouched test window
    does too — never before, however good the pooled number looks."""
    def clears(m: dict) -> bool:
        return bool(m and m.get("n", 0) >= min_n and m.get("p") is not None and m["p"] < alpha
                    and m.get("edge") is not None and abs(m["edge"]) >= min_edge)

    def same_sign(a: dict, b: dict) -> bool:
        return bool(a.get("edge") is not None and b.get("edge") is not None and np.sign(a["edge"]) == np.sign(b["edge"]))

    if not full or full.get("n", 0) < min_n:
        return "thin"
    if not clears(full):
        return "none"
    if clears(train) and clears(val) and same_sign(train, val):
        if clears(test) and same_sign(val, test):
            return "tested"
        return "confirmed"
    return "discovery"


def measure(pairs: pd.DataFrame, kind: str, window: int, min_similarity: float, team: str | None = None,
            tsi: float | None = None, hypothesis: str | None = None, windows: Windows = DEFAULT_WINDOWS,
            ht_ref: dict | None = None, sample: int = 30) -> dict:
    """Did runs like this one predict the centre match? Three layers, every claim priced."""
    hypothesis = hypothesis or HYPOTHESIS.get(kind, "repeat")
    base = pairs[(pairs["kind"] == kind) & (pairs["window"] == window) & (pairs["similarity"] >= min_similarity)
                 & pairs["now_res"].isin(["W", "D", "L"])]
    layers = []
    specs = [("all", "Tüm takımlar", np.ones(len(base), dtype=bool))]
    if team:
        specs.insert(0, ("same_team", "Aynı takım", (base["team"].to_numpy() == team)))
    if tsi is not None and np.isfinite(tsi):
        t = base["tsi"].to_numpy(dtype=float)
        specs.append(("similar", "Benzer güçteki takımlar", np.isfinite(t) & (np.abs(t - tsi) <= BAND)))
    now_date = base["now_date"].to_numpy()

    def in_window(which: str) -> np.ndarray:
        lo, hi = getattr(windows, which)
        return (now_date >= np.datetime64(lo)) & (now_date < np.datetime64(hi))

    for key, tr, mask in specs:
        sub = base[mask]
        full = _claim(sub, hypothesis, ht_ref)
        parts = {w: _claim(sub[in_window(w)[mask]] if len(sub) else sub, hypothesis, ht_ref) for w in ("train", "validation", "test")}
        ev = evidence(full, parts["train"], parts["validation"], parts["test"])
        layers.append({"key": key, "label": tr, **full, "evidence": ev, "evidence_tr": EVIDENCE_TR.get(ev, "fark yok"),
                       "windows": {w: {k: v for k, v in m.items() if k in ("n", "edge", "p", "ci")} for w, m in parts.items()}})
    ht = None
    if hypothesis == "mirror" and "ht_mirror_hit" in base and base["ht_mirror_hit"].notna().any():
        ht = _claim(base, "ht_mirror", ht_ref)
        ht["hypothesis_tr"] = "ilk yarı/maç sonu tersi de döndü (1/2 ↔ 2/1)"
    return {"kind": kind, "kind_tr": KIND_TR.get(kind, kind), "window": window, "min_similarity": min_similarity,
            "hypothesis": hypothesis, "hypothesis_tr": HYPOTHESIS_TR.get(hypothesis, hypothesis),
            "n_pairs": int(len(base)), "layers": layers, "ht_mirror": ht,
            "examples": _examples(base, hypothesis, team, sample),
            "note": "benzerlik bir olasılık değildir: %100 benzeyen bir döngü, merkez maçın sonucu hakkında ancak bu "
                    "tablonun söylediği kadar şey söyler"}


def _examples(base: pd.DataFrame, hypothesis: str, team: str | None, sample: int) -> list[dict]:
    """Real instances of the cycle, this club's first, newest first, with the price and the CLV of the
    outcome the hypothesis names."""
    if base.empty:
        return []
    own = base[base["team"] == team] if team else base.iloc[0:0]
    rest = base.drop(own.index).sort_values("now_date", ascending=False)
    show = pd.concat([own.sort_values("now_date", ascending=False), rest]).head(sample)
    out = []
    for _, r in show.iterrows():
        odds, close = r.get(f"{hypothesis}_odds"), r.get(f"{hypothesis}_close")
        clv = None
        if odds is not None and close is not None and np.isfinite(odds) and np.isfinite(close) and close > 1:
            clv = round(100.0 * (float(odds) / float(close) - 1.0), 2)
        hit = r.get(f"{hypothesis}_hit")
        out.append({"date": str(r["now_date"])[:10], "team": str(r["team"]), "opponent": str(r["opp"]),
                    "league": str(r["league"]), "season_a": str(r["past_season"]), "season_b": str(r["now_season"]),
                    "kind": str(r["kind"]), "kind_tr": KIND_TR.get(str(r["kind"]), str(r["kind"])),
                    "window": int(r["window"]), "similarity": float(r["similarity"]),
                    "past_result": str(r["past_res"]), "new_result": str(r["now_res"]),
                    "past_htft": str(r["past_htft"] or ""), "new_htft": str(r["now_htft"] or ""),
                    "market_p": None if pd.isna(r.get(f"{hypothesis}_p")) else round(100 * float(r[f"{hypothesis}_p"]), 1),
                    "held": None if hit is None or pd.isna(hit) else bool(hit), "clv": clv,
                    "now_match_id": str(r["now_match_id"]), "past_match_id": str(r["past_match_id"]),
                    "own": bool(team and r["team"] == team)})
    return out


def measure_for(settings: Settings, kind: str, window: int, similarity: float, team: str | None = None,
                tsi: float | None = None, hypothesis: str | None = None) -> dict | None:
    """The measurement for one found cycle, at the found similarity and at two looser bands."""
    pairs = pairs_for(settings)
    if pairs is None:
        return None
    bands = sorted({max(MIN_SIMILARITY, float(similarity)), 75.0, MIN_SIMILARITY}, reverse=True)
    bands = [b for b in bands if b <= max(MIN_SIMILARITY, float(similarity))]
    out = {"bands": [measure(pairs, kind, window, b, team=team, tsi=tsi, hypothesis=hypothesis, ht_ref=_MEM.get("ht_ref"))
                     for b in bands],
           "cache": status(settings), "hypotheses": HYPOTHESIS_TR, "evidence_tr": EVIDENCE_TR}
    return out


def target_layer(settings: Settings, df: pd.DataFrame, kind: str, window: int, similarity: float,
                 outcome: str, side: str = "home", ref: float | None = None) -> dict | None:
    """How often `outcome` happened in the centre matches of cycles like this one — Pattern Lab's
    fixture-sequence layer once a target is chosen. Runs from the centre club's own view."""
    pairs = pairs_for(settings, build_if_missing=False)
    if pairs is None:
        return None
    sel = pairs[(pairs["kind"] == kind) & (pairs["window"] == window) & (pairs["similarity"] >= similarity)
                & (pairs["now_venue"] == side)]
    ids = sel["now_match_id"].unique()
    sub = df[df["match_id"].isin(ids)]
    if sub.empty:
        return {"n": 0}
    m = engine.measure(sub, side, outcome, ref=ref)
    m["label"] = f"{KIND_TR.get(kind, kind)} · ±{window} · benzerlik ≥ %{similarity:g}"
    return m
