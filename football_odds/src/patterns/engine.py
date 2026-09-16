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

# outcome -> (indicator from the played match, the market's own probability column)
OUTCOMES: dict[str, str] = {
    "win": "the side wins", "draw": "the match is drawn", "loss": "the side loses",
    "over25": "over 2.5 goals", "btts": "both teams score",
}
MARKET_COLS = {"win": ("p_home", "p_away"), "draw": ("p_draw", "p_draw"),
               "loss": ("p_away", "p_home"), "over25": ("p_over25", "p_over25"), "btts": (None, None)}


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
    """Join the pre-match state with what the market said and what actually happened."""
    cols = ["match_id", "p_home", "p_draw", "p_away", "p_over25", "ftr", "fthg", "ftag", "total_goals", "btts"]
    have = [c for c in cols if c in matches.columns]
    out = state.merge(matches[have], on="match_id", how="inner", validate="one_to_one")
    out["over25"] = out["total_goals"] > 2.5 if "total_goals" in out else np.nan
    if "btts" in out:
        out["btts_hit"] = out["btts"].astype(str).str.lower().isin(["yes", "true", "1"]) | (out["btts"] == 1)
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
    elif outcome == "over25":
        hit = pd.to_numeric(sub.get("total_goals"), errors="coerce").to_numpy() > 2.5
    elif outcome == "btts":
        hit = (pd.to_numeric(sub.get("fthg"), errors="coerce").to_numpy() > 0) & (pd.to_numeric(sub.get("ftag"), errors="coerce").to_numpy() > 0)
    else:
        raise ValueError(f"unknown outcome {outcome!r}")
    col = MARKET_COLS[outcome][0 if home else 1]
    market = pd.to_numeric(sub[col], errors="coerce").to_numpy() if col and col in sub else np.full(len(sub), np.nan)
    return hit.astype(float), market


def measure(sub: pd.DataFrame, side: str, outcome: str) -> dict:
    """Hit rate, the market's own average expectation, and the paired difference with its interval."""
    hit, market = outcome_columns(sub, side, outcome)
    n = int(len(hit))
    if n == 0:
        return {"n": 0, "actual": None, "market": None, "diff": None, "ci": [None, None], "diff_ci": [None, None], "n_market": 0}
    actual = float(np.mean(hit))
    lo, hi = wilson_interval(actual, n)
    ok = np.isfinite(market)
    out = {"n": n, "actual": round(100 * actual, 1), "ci": [round(100 * lo, 1), round(100 * hi, 1)],
           "market": None, "diff": None, "diff_ci": [None, None], "n_market": int(ok.sum())}
    if ok.sum() >= 2:
        d = hit[ok] - market[ok]
        se = float(np.std(d, ddof=1) / np.sqrt(ok.sum()))
        out["market"] = round(100 * float(np.mean(market[ok])), 1)
        out["diff"] = round(100 * float(np.mean(d)), 1)
        out["diff_ci"] = [round(100 * (float(np.mean(d)) - 1.96 * se), 1), round(100 * (float(np.mean(d)) + 1.96 * se), 1)]
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
        as_of: pd.Timestamp | None = None, sample: int = 0, base: dict[str, float] | None = None) -> dict:
    """One pattern over one pool: the matches it selects and every outcome measured against the market.

    `base` is the whole-pool offset from `baseline()`; pass it and each outcome also carries `edge`,
    the difference after that offset is taken out. That is the number to read."""
    sub = select(frame, pattern, as_of=as_of)
    res = {"label": pattern.label(), "side": pattern.side, "n": int(len(sub)),
           "outcomes": {o: measure(sub, pattern.side, o) for o in outcomes}}
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
