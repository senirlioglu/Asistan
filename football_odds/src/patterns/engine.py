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

from dataclasses import dataclass, field, replace

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
    # Match-perspective targets (Pattern Lab): 1 = home, X = draw, 2 = away, whatever `side` says.
    # A reader asks "does this match end 2/1", not "does the side I happen to be describing lead".
    "ft_1": "home win", "ft_X": "draw", "ft_2": "away win",
    "ht_1": "home leads at half time", "ht_X": "level at half time", "ht_2": "away leads at half time",
    **{f"htft_{h}/{f}": f"half time {h}, full time {f}" for h in "1X2" for f in "1X2"},
}
MARKET_COLS = {"win": ("p_home", "p_away"), "draw": ("p_draw", "p_draw"),
               "loss": ("p_away", "p_home"), "over25": ("p_over25", "p_over25"),
               "ft_1": ("p_home", "p_home"), "ft_X": ("p_draw", "p_draw"), "ft_2": ("p_away", "p_away")}
GOAL_OUTCOMES = ("over15", "over25", "over35", "goals6", "btts")   # governed by the over/under price
MATCH_OUTCOMES = ("ft_1", "ft_X", "ft_2", "ht_1", "ht_X", "ht_2",
                  *[f"htft_{h}/{f}" for h in "1X2" for f in "1X2"])           # side-independent
_CODE = {"1": "H", "X": "D", "2": "A"}


@dataclass
class Pattern:
    """What to look for. Every field is optional; the empty pattern matches the whole database."""

    form: str | None = None                 # "WWW-D-WWW", "?WW" — the side's own last results
    form_venue: bool = False                # read `form` off the venue column instead of the overall one
    approx: int = 0                         # how many characters of the form may differ
    side: str = "home"                      # "home" | "away"
    # The opponent's state. `form` above describes one team; a pattern that describes BOTH is a
    # different question -- "a side on WWWWW" and "a side on WWWWW facing a side on LLLLL" are not
    # the same claim, and only the second one is about the match.
    venue_form: str | None = None           # the side's venue form, ALONGSIDE `form` rather than instead
    opp_form: str | None = None             # the opponent's overall form
    opp_venue_form: str | None = None       # the opponent's venue form
    opp_approx: int | None = None           # slack on the opponent's sequences (defaults to `approx`)
    tsi_pct: tuple[float, float] | None = None       # the side's strength percentile in its league
    opp_tsi_pct: tuple[float, float] | None = None
    gap: tuple[float, float] | None = None           # rating gap, side minus opponent
    market: tuple[float, float] | None = None        # the side's own market probability
    rest_days: tuple[float, float] | None = None
    pos: tuple[float, float] | None = None           # league position of the side
    leagues: list[str] | None = None
    team: str | None = None                 # level A: this club only
    opponent: str | None = None             # the other club, by name (the "rakibin geçmişi" layer)
    # how the side's price moved between the pre-close consensus and the closing line — the only
    # movement history the database has (2019/20 onwards). "steam" = shortened, "drift" = lengthened
    movement: str | None = None             # "steam" | "drift" | "stable"
    role: str | None = None                 # "favorite" | "underdog": the side's price against the opponent's
    extra: dict[str, tuple[float, float]] = field(default_factory=dict)   # any other numeric state column

    def label(self) -> str:
        bits = []
        slack = self.approx if self.opp_approx is None else self.opp_approx
        if self.form:
            bits.append(f"form {self.form}" + (f" (±{self.approx})" if self.approx else "") + (" [saha]" if self.form_venue else ""))
        if self.venue_form:
            bits.append(f"saha formu {self.venue_form}" + (f" (±{self.approx})" if self.approx else ""))
        if self.opp_form:
            bits.append(f"rakip {self.opp_form}" + (f" (±{slack})" if slack else ""))
        if self.opp_venue_form:
            bits.append(f"rakip saha formu {self.opp_venue_form}" + (f" (±{slack})" if slack else ""))
        for name, rng in (("TSI%", self.tsi_pct), ("rakip TSI%", self.opp_tsi_pct), ("güç farkı", self.gap),
                          ("piyasa", self.market), ("dinlenme", self.rest_days), ("sıra", self.pos)):
            if rng:
                bits.append(f"{name} {rng[0]:g}–{rng[1]:g}")
        if self.team:
            bits.append(self.team)
        if self.opponent:
            bits.append(f"rakip {self.opponent}")
        if self.role:
            bits.append("favori" if self.role == "favorite" else "sürpriz adayı")
        if self.movement:
            bits.append({"steam": "oran düştü", "drift": "oran yükseldi", "stable": "oran sabit"}.get(self.movement, self.movement))
        if self.leagues:
            bits.append("/".join(self.leagues))
        return " · ".join(bits) or "tüm maçlar"


MOVE_PP = 0.02        # a closing move of two probability points or more counts as steam / drift
STABLE_PP = 0.01      # under one point either way is "stable"


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
    ("favoriye 1,20 altı", "tam 1,67"), not about a margin-free probability.

    The state table carries some of these columns already (`state.PASSTHROUGH`), and a plain merge
    then suffixes both sides into `ftr_x` / `ftr_y` — leaving no `ftr` at all and breaking every
    measurement downstream with a KeyError. The match database is the authority on what happened,
    so its copy wins and the state table's duplicate is dropped before the join."""
    cols = ["match_id", "p_home", "p_draw", "p_away", "p_over25", "ftr", "htr", "fthg", "ftag", "hthg", "htag",
            "total_goals", "cons_h", "cons_d", "cons_a", "p_under25", "result_code",
            "avgc_h", "avgc_d", "avgc_a",                     # closing prices: the CLV benchmark
            "delta_p_home", "delta_p_draw", "delta_p_away"]   # pre-close -> close, the only movement history there is
    have = [c for c in cols if c in matches.columns]
    dupes = [c for c in have if c != "match_id" and c in state.columns]
    left = state.drop(columns=dupes) if dupes else state
    out = left.merge(matches[have], on="match_id", how="inner", validate="one_to_one")
    if {"cons_h", "cons_a"} <= set(out.columns):
        out["odds_gap"] = (out["cons_h"] - out["cons_a"]).abs()
        out["fav_odds"] = out[["cons_h", "cons_a"]].min(axis=1)
        out["fav_side"] = np.where(out["cons_h"] <= out["cons_a"], "home", "away")
    return out


def gap_sign_of(side: str) -> int:
    return 1 if side == "home" else -1


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
    slack = pattern.approx if pattern.opp_approx is None else pattern.opp_approx
    for col, seq, tol in ((f"{p}form_venue" if pattern.form_venue else f"{p}form", pattern.form, pattern.approx),
                          (f"{p}form_venue", pattern.venue_form, pattern.approx),
                          (f"{o}form", pattern.opp_form, slack),
                          (f"{o}form_venue", pattern.opp_venue_form, slack)):
        if seq and col in frame:
            mask &= _form_mask(frame[col].astype("string"), seq, tol)
    if pattern.team:
        side_team = "home_team" if pattern.side == "home" else "away_team"
        mask &= (frame[side_team] == pattern.team).to_numpy()
    if pattern.opponent:
        opp_team = "away_team" if pattern.side == "home" else "home_team"
        mask &= (frame[opp_team] == pattern.opponent).to_numpy()
    if pattern.role and {"p_home", "p_away"} <= set(frame.columns):
        mine = pd.to_numeric(frame["p_home" if pattern.side == "home" else "p_away"], errors="coerce")
        theirs = pd.to_numeric(frame["p_away" if pattern.side == "home" else "p_home"], errors="coerce")
        want = (mine > theirs) if pattern.role == "favorite" else (mine < theirs)
        mask &= want.fillna(False).to_numpy(dtype=bool)
    if pattern.movement and "delta_p_home" in frame:
        d = gap_sign_of(pattern.side) * pd.to_numeric(frame["delta_p_home"], errors="coerce")
        want = {"steam": d >= MOVE_PP, "drift": d <= -MOVE_PP, "stable": d.abs() < STABLE_PP}.get(pattern.movement)
        if want is not None:
            mask &= want.fillna(False).to_numpy(dtype=bool)
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
    if outcome in MATCH_OUTCOMES:
        htr = sub["htr"].astype(str).to_numpy() if "htr" in sub else np.full(len(sub), "")
        known_ht = np.isin(htr, ["H", "D", "A"])
        if outcome.startswith("ft_"):
            hit = ftr == _CODE[outcome[3]]
        elif outcome.startswith("ht_"):
            hit = np.where(known_ht, htr == _CODE[outcome[3]], np.nan)
        else:                                   # htft_H/F
            h, f = outcome[5], outcome[7]
            hit = np.where(known_ht, (htr == _CODE[h]) & (ftr == _CODE[f]), np.nan)
    elif outcome == "win":
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


def measure(sub: pd.DataFrame, side: str, outcome: str, ref: float | None = None,
            w: np.ndarray | None = None) -> dict:
    """Hit rate, the market's own average expectation, and the paired difference with its interval.

    `ref` is the pool-wide rate of the same outcome, used for the markets Football-Data does not
    price (half-time results, reversals, 6+ goals). There the comparison is against how often the
    thing happens in general — weaker than a price, and labelled as such — with the one-sample
    interval around it. Matches whose half-time score is unknown (the extra-league files) drop out
    of the count rather than being guessed.

    `w` is an optional per-match weight (the twin engine's time decay). Rates become weighted means
    and every interval is computed from Kish's effective sample size rather than the raw count, so
    ten half-weighted matches cannot buy the confidence of ten full ones. `n` stays the raw count —
    it is what the reader counts — and `n_eff` carries what the statistics actually used."""
    hit, market = outcome_columns(sub, side, outcome)
    return paired_measure(hit, market, ref=ref, w=w)


def paired_measure(hit: np.ndarray, market: np.ndarray, ref: float | None = None,
                   w: np.ndarray | None = None) -> dict:
    """`measure` on plain arrays: what happened (1/0/NaN) next to what the market said (p or NaN).

    Split out so that a claim which is not an outcome column of a match frame — "the centre result
    of a fixture cycle repeated" is one — is measured by exactly the same arithmetic, and reports the
    same fields, as every other claim in this package."""
    hit = np.asarray(hit, dtype=float)
    market = np.asarray(market, dtype=float)
    known = np.isfinite(hit)
    hit, market = hit[known], market[known]
    ws = np.ones(len(hit)) if w is None else np.asarray(w, dtype=float)[known]
    n = int(len(hit))
    if n == 0 or ws.sum() <= 0:
        return {"n": 0, "n_eff": 0.0, "actual": None, "market": None, "diff": None, "ci": [None, None],
                "diff_ci": [None, None], "n_market": 0, "ref": None, "vs_ref": None,
                "vs_ref_ci": [None, None], "p": None}
    n_eff = float(ws.sum() ** 2 / np.sum(ws ** 2))
    actual = float(np.average(hit, weights=ws))
    lo, hi = wilson_interval(actual, n_eff)
    ok = np.isfinite(market)
    out = {"n": n, "n_eff": round(n_eff, 1), "actual": round(100 * actual, 1),
           "ci": [round(100 * lo, 1), round(100 * hi, 1)],
           "market": None, "diff": None, "diff_ci": [None, None], "n_market": int(ok.sum()),
           "ref": None, "vs_ref": None, "vs_ref_ci": [None, None], "p": None}
    if ref is not None and 0 < ref < 1:
        se_ref = float(np.sqrt(ref * (1 - ref) / n_eff))
        out["ref"] = round(100 * ref, 1)
        out["vs_ref"] = round(100 * (actual - ref), 1)
        out["vs_ref_ci"] = [round(100 * (actual - ref - 1.96 * se_ref), 1), round(100 * (actual - ref + 1.96 * se_ref), 1)]
        out["p"] = _two_sided((actual - ref) / se_ref) if se_ref > 0 else None
    if ok.sum() >= 2:
        d, wd = hit[ok] - market[ok], ws[ok]
        mean = float(np.average(d, weights=wd))
        eff = float(wd.sum() ** 2 / np.sum(wd ** 2))
        var = float(np.average((d - mean) ** 2, weights=wd)) * (eff / max(eff - 1.0, 1e-9))
        se = float(np.sqrt(var / eff))
        out["market"] = round(100 * float(np.average(market[ok], weights=wd)), 1)
        out["diff"] = round(100 * mean, 1)
        out["diff_ci"] = [round(100 * (mean - 1.96 * se), 1), round(100 * (mean + 1.96 * se), 1)]
        out["p"] = _two_sided(mean / se) if se > 0 else None
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


def outcome_cache(frame: pd.DataFrame, side: str, outcomes: tuple[str, ...],
                  step: float = 0.025) -> dict:
    """Everything `matched_rates` recomputes on every call, computed once for a whole frame.

    Pattern Lab asks for price-matched references several times per match, and each ask was walking
    all 180.000 rows nine times to rebuild the same two arrays: what happened, and which price bin
    the match sat in. Cached, a reference costs a groupby instead of a scan."""
    side_col = "p_home" if side == "home" else "p_away"
    if side_col not in frame:
        return {}
    has_ou = "p_over25" in frame and frame["p_over25"].notna().any()
    cache: dict = {"side": side, "step": step, "n": len(frame), "outcomes": {}}
    for o in outcomes:
        col = "p_over25" if (o in GOAL_OUTCOMES and has_ou) else side_col
        hit, _ = outcome_columns(frame, side, o)
        bins = (pd.to_numeric(frame[col], errors="coerce") / step).round().to_numpy()
        cache["outcomes"][o] = {"hit": np.asarray(hit, dtype=float), "bin": bins}
    return cache


def matched_rates_cached(cache: dict, mask: np.ndarray) -> dict[str, float]:
    """The price-matched reference for the rows `mask` selects, read off a cache.

    Identical in meaning to `matched_rates`: the selected matches are excluded from the reference so
    a group is never compared with itself, and the reference is the selection's own price mix."""
    out: dict[str, float] = {}
    if not cache or not mask.any():
        return out
    for o, arr in cache["outcomes"].items():
        hit, bins = arr["hit"], arr["bin"]
        ok = np.isfinite(hit) & np.isfinite(bins)
        oth = ok & ~mask
        sel = ok & mask
        if not oth.any() or not sel.any():
            continue
        rates = pd.Series(hit[oth]).groupby(bins[oth]).mean()
        w = pd.Series(1.0, index=bins[sel]).groupby(level=0).sum()
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


def cascade(frame: pd.DataFrame, steps: list[tuple[str, Pattern]], as_of: pd.Timestamp | None = None,
            **kw) -> list[dict]:
    """The same measurement under a widening set of conditions, one row per condition added.

    A single number ("this pattern wins 69 %") hides the only thing worth knowing: which condition
    moved it. Adding the opponent's form and watching the edge go from +3.3 to +4.2 while N falls
    from 394 to 218 is the shape of the evidence; the last row on its own is not.

    Rows carry `n_lost`, how many matches the condition removed, because a step that halves the
    sample to move the edge by 0.1 points has told us nothing except that the sample got smaller.

    The steps MUST be nested — each one may only add constraints to the one before it — because
    that is what lets every step after the first run on the previous step's matches instead of on
    the whole database. Over 180.000 rows and seven steps that is the difference between six
    seconds and one.
    """
    out, previous, pool = [], None, frame
    for label, pattern in steps:
        sub = select(pool, pattern, as_of=as_of)
        res = run(sub, replace(pattern, form=None, venue_form=None, opp_form=None, opp_venue_form=None,
                               tsi_pct=None, opp_tsi_pct=None, gap=None, market=None, rest_days=None,
                               pos=None, team=None, opponent=None, movement=None, role=None, leagues=None, extra={}),
                  as_of=as_of, **kw)
        res["label"] = pattern.label()
        res["step"] = label
        res["n_lost"] = None if previous is None else previous - res["n"]
        res["n_before"] = previous
        previous, pool = res["n"], sub
        out.append(res)
    return out


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
