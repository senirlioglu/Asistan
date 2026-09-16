"""PATTERN ENGINE — "when this had happened before, what came next?"

A pattern is a condition on the state of a match *before* it is played: a form sequence, a
strength band, a table position, a rest gap, any combination. The engine finds every historical
match that satisfied it and reports what happened in those matches.

The number that matters is never the hit rate. A team on `WWWWW` wins its next match far more
often than average — and the market knows, and prices it. So every result carries three numbers
side by side:

    gerçekleşen   the share of those matches where the outcome happened
    piyasa        what the market's own pre-match probability said, averaged over the same matches
    fark          the first minus the second, with a 95 % interval around the difference

The interval is the paired one: the standard error of the per-match difference (indicator minus
market probability), which is the correct test for "is this different from what was already
priced". A pattern whose interval straddles zero has told us nothing the market did not know,
however impressive its hit rate looks.

Levels (the three the brief asks for):

    same_team   this team's own history with the pattern — usually a handful of matches, kept
                because the owner will look for it, reported with its N so nobody over-reads it
    all         every team in the database
    similar     teams that were of comparable strength AT THAT TIME (never by name), which is
                what `tsi_pct` in the state table is for

Look-ahead: the state table is built from earlier matches only, and `as_of` drops every match
from the pool that was played on or after the day being analysed.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from ..models.stats import wilson_interval

# outcome -> what it means. Football-Data prices 1X2 and 2.5 goals; the rest have no market number,
# so those are compared against the pool's own rate instead (see `measure(ref=...)`).
OUTCOMES: dict[str, str] = {
    "win": "the side wins", "draw": "the match is drawn", "loss": "the side loses",
    "over25": "over 2.5 goals", "btts": "both teams score",
    "over15": "over 1.5 goals", "over35": "over 3.5 goals", "goals6": "6 or more goals",
    "ht_win": "the side leads at half time", "ht_draw": "the first half is level",
    "reversal": "half-time leader loses (2/1 or 1/2)", "ht_1_0": "1-0 for the side at half time",
}
MARKET_COLS = {"win": ("p_home", "p_away"), "draw": ("p_draw", "p_draw"),
               "loss": ("p_away", "p_home"), "over25": ("p_over25", "p_over25")}
GOAL_OUTCOMES = ("over15", "over25", "over35", "goals6", "btts")   # governed by the over/under price


@dataclass
class Pattern:
    """What to look for. Every field is optional; the empty pattern matches the whole database."""

    form: str | None = None                 # "WWW-D-WWW", "?WW" — the side's own last results
    form_venue: bool = False                # read the venue form (home team's home matches) instead
    approx: int = 0                         # how many characters of the form may differ
    side: str = "home"                      # "home" | "away"
    tsi_pct: tuple[float, float] | None = None       # the side's strength percentile in its league
    opp_tsi_pct: tuple[float, float] | None = None
    gap: tuple[float, float] | None = None           # rating gap, side minus opponent
    market: tuple[float, float] | None = None        # the side's own market probability
    rest_days: tuple[float, float] | None = None
    pos: tuple[float, float] | None = None           # league position of the side
    leagues: list[str] | None = None
    team: str | None = None                 # level A: this club only
    extra: dict[str, tuple[float, float]] = field(default_factory=dict)   # any other numeric state column

    def label(self) -> str:
        bits = []
        if self.form:
            bits.append(f"form {self.form}" + (f" (±{self.approx})" if self.approx else "") + (" [saha]" if self.form_venue else ""))
        for name, rng in (("TSI%", self.tsi_pct), ("rakip TSI%", self.opp_tsi_pct), ("güç farkı", self.gap),
                          ("piyasa", self.market), ("dinlenme", self.rest_days), ("sıra", self.pos)):
            if rng:
                bits.append(f"{name} {rng[0]:g}–{rng[1]:g}")
        if self.team:
            bits.append(self.team)
        if self.leagues:
            bits.append("/".join(self.leagues))
        return " · ".join(bits) or "tüm maçlar"


def form_matches(form: str, pattern: str, approx: int = 0) -> bool:
    """Does this form string END with the pattern? '-' separates, '?' matches anything."""
    pat = pattern.replace("-", "").replace(" ", "").upper()
    if not pat or len(form) < len(pat):
        return False
    tail = form[-len(pat):]
    return sum(1 for a, b in zip(tail, pat) if b != "?" and a != b) <= approx


def _form_mask(series: pd.Series, pattern: str, approx: int) -> np.ndarray:
    """Vectorised over the (few thousand) distinct form strings rather than the 180k rows."""
    uniq = series.dropna().unique()
    ok = {f: form_matches(f, pattern, approx) for f in uniq}
    return series.map(ok).fillna(False).to_numpy(dtype=bool)


def prepare(state: pd.DataFrame, matches: pd.DataFrame) -> pd.DataFrame:
    """Join the pre-match state with what the market said and what actually happened.

    The raw consensus odds ride along too: the owner's notes are written about the printed price
    ("favoriye 1,20 altı", "tam 1,67"), not about a margin-free probability."""
    cols = ["match_id", "p_home", "p_draw", "p_away", "p_over25", "ftr", "htr", "fthg", "ftag", "hthg", "htag",
            "total_goals", "cons_h", "cons_d", "cons_a"]
    have = [c for c in cols if c in matches.columns]
    out = state.merge(matches[have], on="match_id", how="inner", validate="one_to_one")
    if {"cons_h", "cons_a"} <= set(out.columns):
        out["odds_gap"] = (out["cons_h"] - out["cons_a"]).abs()
        out["fav_odds"] = out[["cons_h", "cons_a"]].min(axis=1)
        out["fav_side"] = np.where(out["cons_h"] <= out["cons_a"], "home", "away")
    return out


def _range_mask(frame: pd.DataFrame, col: str, rng: tuple[float, float] | None) -> np.ndarray | None:
    if rng is None or col not in frame:
        return None
    lo, hi = rng
    v = pd.to_numeric(frame[col], errors="coerce")
    return ((v >= lo) & (v <= hi)).to_numpy(dtype=bool)


def select(frame: pd.DataFrame, pattern: Pattern, as_of: pd.Timestamp | None = None) -> pd.DataFrame:
    """Every match in `frame` that satisfies the pattern (and was played before `as_of`)."""
    p, o = ("h_", "a_") if pattern.side == "home" else ("a_", "h_")
    mask = np.ones(len(frame), dtype=bool)
    if as_of is not None:
        mask &= (frame["date"] < pd.Timestamp(as_of)).to_numpy()
    if pattern.form:
        col = f"{p}form_venue" if pattern.form_venue else f"{p}form"
        mask &= _form_mask(frame[col].astype("string"), pattern.form, pattern.approx)
    if pattern.team:
        side_team = "home_team" if pattern.side == "home" else "away_team"
        mask &= (frame[side_team] == pattern.team).to_numpy()
    if pattern.leagues:
        mask &= frame["league"].isin(pattern.leagues).to_numpy()
    gap_sign = 1 if pattern.side == "home" else -1
    checks = [(f"{p}tsi_pct", pattern.tsi_pct), (f"{o}tsi_pct", pattern.opp_tsi_pct), (f"{p}rest_days", pattern.rest_days),
              (f"{p}pos", pattern.pos)]
    checks += [(k, v) for k, v in pattern.extra.items()]
    for col, rng in checks:
        m = _range_mask(frame, col, rng)
        if m is not None:
            mask &= m
    if pattern.gap is not None:
        gap = gap_sign * pd.to_numeric(frame["strength_gap"], errors="coerce")
        mask &= ((gap >= pattern.gap[0]) & (gap <= pattern.gap[1])).to_numpy(dtype=bool)
    if pattern.market is not None:
        col = "p_home" if pattern.side == "home" else "p_away"
        m = _range_mask(frame, col, pattern.market)
        if m is not None:
            mask &= m
    return frame.loc[mask]


def outcome_columns(sub: pd.DataFrame, side: str, outcome: str) -> tuple[np.ndarray, np.ndarray]:
    """(what happened, what the market said) for one outcome, over the matches in `sub`."""
    ftr = sub["ftr"].astype(str).to_numpy()
    home = side == "home"
    if outcome == "win":
        hit = ftr == ("H" if home else "A")
    elif outcome == "loss":
        hit = ftr == ("A" if home else "H")
    elif outcome == "draw":
        hit = ftr == "D"
    elif outcome in ("over15", "over25", "over35", "goals6"):
        line = {"over15": 1.5, "over25": 2.5, "over35": 3.5, "goals6": 5.5}[outcome]
        hit = pd.to_numeric(sub.get("total_goals"), errors="coerce").to_numpy() > line
    elif outcome == "btts":
        hit = (pd.to_numeric(sub.get("fthg"), errors="coerce").to_numpy() > 0) & (pd.to_numeric(sub.get("ftag"), errors="coerce").to_numpy() > 0)
    elif outcome in ("ht_win", "ht_draw", "reversal", "ht_1_0"):
        htr = sub["htr"].astype(str).to_numpy() if "htr" in sub else np.full(len(sub), "")
        known = np.isin(htr, ["H", "D", "A"])
        if outcome == "ht_draw":
            hit = np.where(known, htr == "D", np.nan)
        elif outcome == "ht_win":
            hit = np.where(known, htr == ("H" if home else "A"), np.nan)
        elif outcome == "reversal":     # 2/1 or 1/2 as a property of the match, either way round
            hit = np.where(known & (htr != "D") & (ftr != "D"), htr != ftr, np.nan)
        else:
            hh = pd.to_numeric(sub.get("hthg"), errors="coerce").to_numpy()
            ha = pd.to_numeric(sub.get("htag"), errors="coerce").to_numpy()
            lead, trail = (hh, ha) if home else (ha, hh)
            hit = np.where(np.isfinite(hh) & np.isfinite(ha), (lead == 1) & (trail == 0), np.nan)
    else:
        raise ValueError(f"unknown outcome {outcome!r}")
    hit = np.asarray(hit, dtype=float)
    col = MARKET_COLS.get(outcome, (None, None))[0 if home else 1]
    market = pd.to_numeric(sub[col], errors="coerce").to_numpy() if col and col in sub else np.full(len(sub), np.nan)
    return hit, market


def _two_sided(z: float) -> float:
    """Two-sided normal p-value; `math.erfc` keeps this dependency-free."""
    import math

    return float(math.erfc(abs(z) / math.sqrt(2)))


def fdr(pvals: list[float | None], q: float = 0.05) -> list[float | None]:
    """Benjamini-Hochberg adjusted p-values. Measuring thirty claims at 95 % produces one or two
    'findings' from noise alone, so every batch of claims goes through this before anything is
    called a finding."""
    idx = [i for i, v in enumerate(pvals) if v is not None]
    out: list[float | None] = [None] * len(pvals)
    if not idx:
        return out
    order = sorted(idx, key=lambda i: pvals[i])
    m = len(order)
    running = 1.0
    for rank in range(m, 0, -1):
        i = order[rank - 1]
        running = min(running, pvals[i] * m / rank)
        out[i] = round(min(1.0, running), 4)
    return out


def measure(sub: pd.DataFrame, side: str, outcome: str, ref: float | None = None) -> dict:
    """Hit rate, the market's own average expectation, and the paired difference with its interval.

    `ref` is the pool-wide rate of the same outcome, used for the markets Football-Data does not
    price (half-time results, reversals, 6+ goals). There the comparison is against how often the
    thing happens in general — weaker than a price, and labelled as such — with the one-sample
    interval around it. Matches whose half-time score is unknown (the extra-league files) drop out
    of the count rather than being guessed."""
    hit, market = outcome_columns(sub, side, outcome)
    known = np.isfinite(hit)
    hit, market = hit[known], market[known]
    n = int(len(hit))
    if n == 0:
        return {"n": 0, "actual": None, "market": None, "diff": None, "ci": [None, None], "diff_ci": [None, None],
                "n_market": 0, "ref": None, "vs_ref": None, "vs_ref_ci": [None, None], "p": None}
    actual = float(np.mean(hit))
    lo, hi = wilson_interval(actual, n)
    ok = np.isfinite(market)
    out = {"n": n, "actual": round(100 * actual, 1), "ci": [round(100 * lo, 1), round(100 * hi, 1)],
           "market": None, "diff": None, "diff_ci": [None, None], "n_market": int(ok.sum()),
           "ref": None, "vs_ref": None, "vs_ref_ci": [None, None], "p": None}
    if ref is not None and 0 < ref < 1:
        se_ref = float(np.sqrt(ref * (1 - ref) / n))
        out["ref"] = round(100 * ref, 1)
        out["vs_ref"] = round(100 * (actual - ref), 1)
        out["vs_ref_ci"] = [round(100 * (actual - ref - 1.96 * se_ref), 1), round(100 * (actual - ref + 1.96 * se_ref), 1)]
        out["p"] = _two_sided((actual - ref) / se_ref) if se_ref > 0 else None
    if ok.sum() >= 2:
        d = hit[ok] - market[ok]
        se = float(np.std(d, ddof=1) / np.sqrt(ok.sum()))
        out["market"] = round(100 * float(np.mean(market[ok])), 1)
        out["diff"] = round(100 * float(np.mean(d)), 1)
        out["diff_ci"] = [round(100 * (float(np.mean(d)) - 1.96 * se), 1), round(100 * (float(np.mean(d)) + 1.96 * se), 1)]
        out["p"] = _two_sided(float(np.mean(d)) / se) if se > 0 else None
    return out


def pool_rates(frame: pd.DataFrame, side: str, outcomes: tuple[str, ...]) -> dict[str, float]:
    """How often each outcome happens across the whole pool — the reference for the unpriced ones."""
    out = {}
    for o in outcomes:
        hit, _ = outcome_columns(frame, side, o)
        known = np.isfinite(hit)
        if known.any():
            out[o] = float(np.mean(hit[known]))
    return out


def matched_rates(frame: pd.DataFrame, sub: pd.DataFrame, side: str, outcomes: tuple[str, ...],
                  step: float = 0.025) -> dict[str, float]:
    """The rate of each outcome among matches PRICED LIKE these ones — the honest reference for the
    markets Football-Data does not quote.

    Half of the notebook's notes are conditions on the price itself ("favoriye 1,20 altı", "tam
    1,67"). Comparing those against the whole pool only rediscovers that favourites lead at half
    time and win — which the price already said. So the reference is built by matching on the
    market's own probability for the side: the pool is cut into `step`-wide probability bins, the
    outcome rate is taken in each bin over the matches OUTSIDE the pattern, and those rates are
    averaged with the pattern's own distribution over the bins as weights. The result answers
    "did these matches do it more often than other matches carrying the same price?".
    """
    side_col = "p_home" if side == "home" else "p_away"
    if side_col not in frame or not len(sub):
        return {}
    ids = set(sub["match_id"]) if "match_id" in sub else set()
    others = frame[~frame["match_id"].isin(ids)] if ids else frame
    out: dict[str, float] = {}
    for o in outcomes:
        # match on the price that governs THAT market: the goal markets belong to the over/under
        # price, not to 1X2 — an extreme favourite and a high-scoring game are different things
        col = "p_over25" if (o in GOAL_OUTCOMES and "p_over25" in frame and frame["p_over25"].notna().any()) else side_col
        b_sub = (pd.to_numeric(sub[col], errors="coerce") / step).round()
        b_oth = (pd.to_numeric(others[col], errors="coerce") / step).round()
        hit_o, _ = outcome_columns(others, side, o)
        hit_s, _ = outcome_columns(sub, side, o)
        ok_o, ok_s = np.isfinite(hit_o) & b_oth.notna().to_numpy(), np.isfinite(hit_s) & b_sub.notna().to_numpy()
        if not ok_s.any() or not ok_o.any():
            continue
        rates = pd.Series(hit_o[ok_o]).groupby(b_oth[ok_o].to_numpy()).mean()
        w = pd.Series(1.0, index=b_sub[ok_s].to_numpy()).groupby(level=0).sum()
        common = rates.index.intersection(w.index)
        if not len(common) or w[common].sum() == 0:
            continue
        out[o] = float((rates[common] * w[common]).sum() / w[common].sum())
    return out


def baseline(frame: pd.DataFrame, side: str, outcomes: tuple[str, ...]) -> dict[str, float]:
    """The same difference measured over the WHOLE pool — the offset every pattern has to clear.

    Measured on the real database it is not zero: home wins come in 0,6 points above what our
    margin-free consensus says (the well known favourite-longshot / margin-removal residual). Left
    uncorrected, every home-side pattern would look 0,6 points better than the market for free.
    The baseline is estimated on ~180.000 matches, so its own standard error is about 0,1 points —
    an order of magnitude below a typical pattern's, which is why the correction is applied to the
    estimate and the pattern's own interval is kept.
    """
    return {o: (measure(frame, side, o).get("diff") or 0.0) for o in outcomes}


def beats_market(m: dict) -> bool:
    """True when the whole 95 % interval of the baseline-corrected difference sits off zero."""
    lo, hi = m.get("edge_ci") or m.get("diff_ci") or (None, None)
    return lo is not None and hi is not None and (lo > 0 or hi < 0)


def run(frame: pd.DataFrame, pattern: Pattern, outcomes: tuple[str, ...] = ("win", "draw", "loss", "over25", "btts"),
        as_of: pd.Timestamp | None = None, sample: int = 0, base: dict[str, float] | None = None,
        refs: dict[str, float] | None = None) -> dict:
    """One pattern over one pool: the matches it selects and every outcome measured against the market.

    `base` is the whole-pool offset from `baseline()`; pass it and each outcome also carries `edge`,
    the difference after that offset is taken out. That is the number to read."""
    sub = select(frame, pattern, as_of=as_of)
    refs = refs or {}
    res = {"label": pattern.label(), "side": pattern.side, "n": int(len(sub)),
           "outcomes": {o: measure(sub, pattern.side, o, ref=refs.get(o)) for o in outcomes}}
    if base:
        for o, m in res["outcomes"].items():
            if m.get("diff") is None or o not in base:
                continue
            m["base"] = round(base[o], 1)
            m["edge"] = round(m["diff"] - base[o], 1)
            m["edge_ci"] = [round(m["diff_ci"][0] - base[o], 1), round(m["diff_ci"][1] - base[o], 1)]
    if sample and len(sub):
        cols = [c for c in ("date", "league", "home_team", "away_team", "ftr", "fthg", "ftag", "h_form", "a_form") if c in sub]
        res["sample"] = sub.sort_values("date", ascending=False).head(sample)[cols].to_dict("records")
    return res


def levels(frame: pd.DataFrame, pattern: Pattern, team: str | None, tsi_pct: float | None, band: float = 10.0,
           as_of: pd.Timestamp | None = None, **kw) -> dict:   # noqa: D417
    """The same pattern at the three levels: this club, everybody, comparable strength."""
    out = {"all": run(frame, pattern, as_of=as_of, **kw)}
    if team:
        from dataclasses import replace

        out["same_team"] = run(frame, replace(pattern, team=team), as_of=as_of, **kw)
    if tsi_pct is not None:
        from dataclasses import replace

        rng = (max(0.0, tsi_pct - band), min(100.0, tsi_pct + band))
        out["similar"] = run(frame, replace(pattern, tsi_pct=rng), as_of=as_of, **kw)
    return out
