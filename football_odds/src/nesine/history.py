"""What the database says about the notes.

Two jobs:

* ``team_hits`` — the notes that depend on a team's recent half-time/full-time history (2 and 14) are
  evaluated from the processed database (main divisions carry half-time results), after matching
  nesine's team spelling to Football-Data's.
* ``backtest`` — the notes that can be phrased with the odds we store (match-result consensus, so
  Football-Data's average, not nesine's price) are counted over the whole database: how often the
  outcome the note promises actually happened, next to the base rate. The page shows these numbers
  beside the note; they are descriptive, not a verdict on nesine prices.
"""

from __future__ import annotations

import datetime as dt
import json
import re
from pathlib import Path

import numpy as np
import pandas as pd

from ..config import Settings
from ..web.live import name_score, norm

REVERSAL = {("H", "A"), ("A", "H")}
# nesine marks women's, youth and reserve teams with a suffix; those are different clubs from the ones
# we store, and "EC Bahia BA (K)" must not resolve to Bahia
_NOT_THE_SAME_CLUB = re.compile(r"\((k|kad[ıi]n)\)|\b(u\s?1[5-9]|u\s?2[0-3]|kad[ıi]n|women|res\.?|reserve|b\s?tak[ıi]m|ii)\b", re.IGNORECASE)
COLS = ["league", "date", "home_team", "away_team", "fthg", "ftag", "ftr", "hthg", "htag", "htr", "cons_h", "cons_d", "cons_a", "season"]


def load_history(settings: Settings) -> pd.DataFrame | None:
    p = settings.processed_dir / "matches.parquet"
    if not p.exists():
        return None
    import pyarrow.parquet as pq

    present = set(pq.read_schema(p).names)
    df = pd.read_parquet(p, columns=[c for c in COLS if c in present])
    df["date"] = pd.to_datetime(df["date"])
    return df


# --------------------------------------------------------------------------- team history (notes 2, 14)

class TeamIndex:
    """Per team: its matches in date order with (htr, ftr); plus a name resolver for nesine spellings."""

    def __init__(self, df: pd.DataFrame, recent_days: int = 400):
        d = df[df["htr"].isin(["H", "D", "A"]) & df["ftr"].isin(["H", "D", "A"])].sort_values("date")
        self.rows: dict[str, list[tuple[pd.Timestamp, str, str, int]]] = {}
        for r in d.itertuples(index=False):
            goals = int(r.fthg + r.ftag) if pd.notna(r.fthg) and pd.notna(r.ftag) else -1
            for team in (r.home_team, r.away_team):
                self.rows.setdefault(str(team), []).append((r.date, str(r.htr), str(r.ftr), goals))
        # "currently playing" = seen in the last ~13 months; season codes sort badly (Y2025 vs 2627)
        cutoff = df["date"].max() - pd.Timedelta(days=recent_days)
        active = df[df["date"] >= cutoff]
        self.active = sorted(set(active["home_team"].astype(str)) | set(active["away_team"].astype(str)))
        self._norm = {t: norm(t) for t in self.active}
        self._by_norm: dict[str, str] = {}
        self._by_token: dict[str, list[str]] = {}
        for team, tn in self._norm.items():
            self._by_norm.setdefault(tn, team)
            for tok in tn.split():
                self._by_token.setdefault(tok, []).append(team)
        self._cache: dict[str, str | None] = {}

    def resolve(self, name: str, min_score: float = 0.8) -> str | None:
        """nesine spelling -> our team name, or None. Exact normalised match first, then fuzzy over the
        teams that share a word with it (a full scan over 700 teams per name is too slow for a page load)."""
        if name in self._cache:
            return self._cache[name]
        if _NOT_THE_SAME_CLUB.search(name or ""):
            self._cache[name] = None
            return None
        n = norm(name)
        out = self._by_norm.get(n)
        if out is None and n:
            cands = {t for tok in n.split() for t in self._by_token.get(tok, [])}
            best, best_s = None, 0.0
            for team in cands:
                s = name_score(name, team)
                if s > best_s:
                    best, best_s = team, s
            out = best if best_s >= min_score else None
        self._cache[name] = out
        return out

    def recent(self, team: str, before: pd.Timestamp, n: int = 8) -> list[tuple[pd.Timestamp, str, str, int]]:
        rows = [r for r in self.rows.get(team, []) if r[0] < before]
        return rows[-n:]


def team_hits(match: dict, index: TeamIndex) -> dict[str, dict]:
    """{'n14': hit, 'n2': hit} from the two teams' recent history; empty when neither team is known."""
    hits: dict[str, dict] = {}
    try:
        before = pd.Timestamp(match["date"])
    except (ValueError, TypeError):
        return hits
    for side in ("home", "away"):
        team = index.resolve(match[side])
        if not team:
            continue
        rec = index.recent(team, before, 8)
        if not rec:
            continue
        last = rec[-1]
        if (last[1], last[2]) in REVERSAL:
            hits.setdefault("n14", {"evidence": {}, "expect": "İlk yarı berabere (%80–90 diyor not)."})
            hits["n14"]["evidence"][f"{match[side]} son maçı"] = f"{last[0].date()} İY {last[1]} / MS {last[2]}"
        if len(rec) >= 6:
            sixth = rec[-6]  # today's match is the 7th after it
            if (sixth[1], sixth[2]) in REVERSAL:
                hits.setdefault("n2", {"evidence": {}, "expect": "Yine 2/1 veya 1/2; bazen 6+ gol."})
                hits["n2"]["evidence"][f"{match[side]} 6 maç önce"] = f"{sixth[0].date()} İY {sixth[1]} / MS {sixth[2]}"
    return hits


# --------------------------------------------------------------------------- backtest of the testable notes

def _rate(mask: np.ndarray, cond: np.ndarray) -> dict:
    n = int(mask.sum())
    return {"n": n, "pct": (100.0 * float((mask & cond).sum()) / n) if n else None}


def backtest(df: pd.DataFrame) -> dict:
    d = df[df["ftr"].isin(["H", "D", "A"])].copy()
    d = d[d["cons_h"].notna() & d["cons_a"].notna()]
    fav_odds = np.minimum(d["cons_h"], d["cons_a"]).to_numpy()
    fav_home = (d["cons_h"] <= d["cons_a"]).to_numpy()
    total = (d["fthg"] + d["ftag"]).to_numpy(dtype=float)
    htr = d["htr"].astype("string").fillna("").to_numpy(dtype=str)
    ftr = d["ftr"].astype("string").fillna("").to_numpy(dtype=str)
    has_ht = np.isin(htr, ["H", "D", "A"])
    hthg, htag = d["hthg"].to_numpy(dtype=float), d["htag"].to_numpy(dtype=float)
    fh_goals = hthg + htag
    reversal = np.array([(a, b) in REVERSAL for a, b in zip(htr, ftr)])
    ht_fav = np.where(fav_home, htr == "H", htr == "A")
    ht_score_10 = np.where(fav_home, (hthg == 1) & (htag == 0), (hthg == 0) & (htag == 1))
    underdog_fh = np.where(fav_home, htag >= 1, hthg >= 1)
    out: dict[str, dict] = {"n_matches": int(len(d))}
    base_all = np.ones(len(d), dtype=bool)

    m4 = fav_odds <= 1.20
    out["n4"] = {"label": "Favori ≤ 1,20", "n": int(m4.sum()), "rows": [
        {"what": "2,5 üst", "note": "%99,9", "rule": _rate(m4, total > 2.5), "base": _rate(base_all, total > 2.5)},
        {"what": "3,5 üst", "note": "%80", "rule": _rate(m4, total > 3.5), "base": _rate(base_all, total > 3.5)},
        {"what": "6+ gol", "note": "%70", "rule": _rate(m4, total >= 6), "base": _rate(base_all, total >= 6)},
        {"what": "İY 1,5 üst", "note": "denenebilir", "rule": _rate(m4 & has_ht, fh_goals > 1.5), "base": _rate(has_ht, fh_goals > 1.5)},
    ]}
    m10 = (fav_odds >= 1.65) & (fav_odds <= 1.69)
    out["n10"] = {"label": "Favori 1,65–1,69 (not: tam 1,67)", "n": int(m10.sum()), "rows": [
        {"what": "İlk yarıyı favori önde bitirir", "note": "%85", "rule": _rate(m10 & has_ht, ht_fav), "base": _rate(has_ht, ht_fav)},
        {"what": "İlk yarı skoru favori lehine 1-0", "note": "1/0", "rule": _rate(m10 & has_ht, ht_score_10), "base": _rate(has_ht, ht_score_10)},
    ]}
    diff = np.abs(d["cons_h"].to_numpy() - d["cons_a"].to_numpy())
    m11 = diff <= 0.0101
    lower_home = d["cons_h"].to_numpy() < d["cons_a"].to_numpy()
    dir_rev = np.where(lower_home, (htr == "A") & (ftr == "H"), (htr == "H") & (ftr == "A"))
    out["n11"] = {"label": "MS1 ile MS2 farkı ≤ 0,01", "n": int(m11.sum()), "rows": [
        {"what": "2/1 veya 1/2 (herhangi yön)", "note": "%100", "rule": _rate(m11 & has_ht, reversal), "base": _rate(has_ht, reversal)},
        {"what": "Notun dediği yönde ters çevirme", "note": "%100", "rule": _rate(m11 & has_ht & (diff > 0.0001), dir_rev), "base": _rate(has_ht, (htr == "A") & (ftr == "H"))},
    ]}
    m16 = (fav_odds >= 1.63) & (fav_odds <= 1.77)
    out["n16"] = {"label": "Favori 1,63–1,77 (not: 1,65 / 1,67 / 1,75)", "n": int(m16.sum()), "rows": [
        {"what": "İlk yarıyı favori önde bitirir", "note": "gönül rahatlığıyla", "rule": _rate(m16 & has_ht, ht_fav), "base": _rate(has_ht, ht_fav)},
        {"what": "Açılan takım ilk yarıda gol atar", "note": "mutlaka", "rule": _rate(m16 & has_ht, underdog_fh), "base": _rate(has_ht, underdog_fh)},
    ]}

    # notes 2 and 14 need each team's sequence
    seq = d[has_ht].sort_values("date")
    prev_rev_ht_draw, prev_rev_n = 0, 0
    seventh_rev, seventh_n, seventh_six = 0, 0, 0
    per_team: dict[str, list[tuple[str, str, float]]] = {}
    for r in seq.itertuples(index=False):
        for team in (r.home_team, r.away_team):
            hist = per_team.setdefault(str(team), [])
            if hist:
                if (hist[-1][0], hist[-1][1]) in REVERSAL:
                    prev_rev_n += 1
                    prev_rev_ht_draw += int(r.htr == "D")
            if len(hist) >= 6 and (hist[-6][0], hist[-6][1]) in REVERSAL:
                seventh_n += 1
                seventh_rev += int((r.htr, r.ftr) in REVERSAL)
                seventh_six += int((r.fthg + r.ftag) >= 6)
            hist.append((str(r.htr), str(r.ftr), float(r.fthg + r.ftag)))
    base_ht_draw = _rate(has_ht, htr == "D")
    base_rev = _rate(has_ht, reversal)
    base_six = _rate(base_all, total >= 6)
    out["n14"] = {"label": "Bir önceki maçı 2/1 ya da 1/2 biten takım", "n": prev_rev_n, "rows": [
        {"what": "Sonraki maçın ilk yarısı berabere", "note": "%80–90", "rule": {"n": prev_rev_n, "pct": 100.0 * prev_rev_ht_draw / prev_rev_n if prev_rev_n else None}, "base": base_ht_draw}]}
    out["n2"] = {"label": "Ters çevirmeden sonraki 7. maç", "n": seventh_n, "rows": [
        {"what": "Yine 2/1 veya 1/2", "note": "yapar", "rule": {"n": seventh_n, "pct": 100.0 * seventh_rev / seventh_n if seventh_n else None}, "base": base_rev},
        {"what": "6+ gol", "note": "bazen", "rule": {"n": seventh_n, "pct": 100.0 * seventh_six / seventh_n if seventh_n else None}, "base": base_six}]}
    out["generated_at"] = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    out["note"] = ("Oranlar Football-Data'nın maç öncesi ortalama oranı, nesine oranı değil; 'tam 1,67' gibi şartlar dar bir aralıkla "
                   "temsil edildi. Yarı sonuçları ana liglerde var; 16 ek ülkede yok.")
    return out


def cached_backtest(settings: Settings, df: pd.DataFrame | None = None) -> dict:
    """results/notes_history.json, recomputed when the database is newer than the file."""
    p = settings.processed_dir / "matches.parquet"
    out = settings.results_dir / "notes_history.json"
    if out.exists() and p.exists() and out.stat().st_mtime >= p.stat().st_mtime:
        try:
            return json.loads(out.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass
    if df is None:
        df = load_history(settings)
    if df is None:
        return {}
    res = backtest(df)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    return res
