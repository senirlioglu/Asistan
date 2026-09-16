"""FIXTURE SEQUENCE ENGINE — "aynı fikstür dizisi tekrarlıyor mu?"

The graphics that circulate about football patterns are usually about this: a team played the same
run of opponents in some past season, and the run is now repeating — forwards, backwards or
shifted. This module finds those runs instead of leaving them to be spotted by eye.

    2023/24   Juventus → Monza → BOLOGNA → Torino → Atalanta
    2026/27   Atalanta → Torino → BOLOGNA → Juventus → Monza

A run is described by the opponents around a **centre** match, out to a window of ±w, and compared
with the same team's runs in earlier seasons around a match against the same opponent. Four shapes
are searched, all of them automatically — the reader picks a team, not a search type:

    EXACT_SAME      the same opponents in the same order
    EXACT_REVERSE   the same opponents in the opposite order
    SHIFTED         the same opponents, rotated
    STRENGTH        different clubs, comparable strength profile at the time

**Positional and wing scores are both reported, because they disagree and the difference matters.**
In the run above the two matches before the centre reverse exactly, but Juventus and Monza swap
inside the wing: read position by position it is 3 of 5, read as "the same two clubs before and the
same two after" it is 5 of 5. The graphics quote the second and call it 100 %. Neither number is
wrong; quoting one without the other is.

Nothing here predicts anything, and the module says so in its own vocabulary: a `Cycle` carries a
similarity, never a probability. Whether a repeating run tells you anything about the centre match
is a separate question with its own measurement (`measure_cycles`), and the answer so far is no.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from ..logging_setup import get_logger

log = get_logger("patterns.sequence")

WINDOWS = (2, 3, 4)
KINDS = ("EXACT_SAME", "EXACT_REVERSE", "SHIFTED", "STRENGTH")
KIND_TR = {
    "EXACT_SAME": "Aynı sıra",
    "EXACT_REVERSE": "Ters sıra",
    "SHIFTED": "Kaymış sıra",
    "STRENGTH": "Benzer güç dizisi",
}
STRENGTH_SCALE = 25.0     # percentile points of opponent strength that count as "completely different"
MIN_SIDE = 1              # a run needs at least this many matches on each side of the centre


@dataclass
class Run:
    """One team's opponents around a centre match, in the order they were played."""

    team: str
    season: str
    centre_index: int
    centre_opponent: str
    centre_match_id: str
    centre_date: pd.Timestamp
    before: list[str] = field(default_factory=list)      # oldest first
    after: list[str] = field(default_factory=list)
    before_strength: list[float] = field(default_factory=list)
    after_strength: list[float] = field(default_factory=list)

    @property
    def opponents(self) -> list[str]:
        return [*self.before, self.centre_opponent, *self.after]

    @property
    def strengths(self) -> list[float]:
        return [*self.before_strength, float("nan"), *self.after_strength]

    def slots(self, w: int) -> dict[int, str]:
        """Opponent by offset from the centre, for the offsets this run actually has.

        A run in progress has no "after" side yet — the schedule knows who is coming, the database
        of played matches does not. Comparing over the offsets both runs have is the honest move;
        inventing the missing ones would turn "the season just started" into a match."""
        out = {0: self.centre_opponent}
        for i, name in enumerate(self.before):
            out[i - len(self.before)] = name
        for i, name in enumerate(self.after):
            out[i + 1] = name
        return out

    def strength_slots(self, w: int) -> dict[int, float]:
        out = {}
        for i, v in enumerate(self.before_strength):
            out[i - len(self.before_strength)] = v
        for i, v in enumerate(self.after_strength):
            out[i + 1] = v
        return out


@dataclass
class Cycle:
    """A past run that resembles the current one, and how exactly it resembles it."""

    kind: str
    window: int
    similarity: float           # the headline score, 0-100, of the shape named by `kind`
    positional: float           # position by position
    wing: float                 # "the same clubs before, the same clubs after", order inside ignored
    n_compared: int             # how many offsets both runs had — a 2-of-2 is not a 5-of-5
    past: Run
    now: Run

    def as_dict(self) -> dict:
        return {
            "kind": self.kind, "kind_tr": KIND_TR.get(self.kind, self.kind), "window": self.window,
            "similarity": round(self.similarity, 1), "positional": round(self.positional, 1),
            "wing": round(self.wing, 1), "n_compared": self.n_compared,
            # `centre_at` is the index of the centre inside `opponents`: a run in progress has fewer
            # matches after the centre than before it, so the middle of the list is not the centre
            "past": {"season": self.past.season, "date": str(self.past.centre_date)[:10],
                     "match_id": self.past.centre_match_id, "opponents": self.past.opponents,
                     "centre": len(self.past.before), "centre_at": len(self.past.before)},
            "now": {"season": self.now.season, "date": str(self.now.centre_date)[:10],
                    "match_id": self.now.centre_match_id, "opponents": self.now.opponents,
                    "centre": len(self.now.before), "centre_at": len(self.now.before)},
        }


# --------------------------------------------------------------------------- building the runs

def team_line(df: pd.DataFrame, team: str) -> pd.DataFrame:
    """Every match this club played, in order, with the opponent and that opponent's strength."""
    home = df["home_team"].astype(str) == team
    away = df["away_team"].astype(str) == team
    sub = df[home | away].sort_values(["date", "match_id"]).copy()
    is_home = sub["home_team"].astype(str) == team
    sub["opponent"] = np.where(is_home, sub["away_team"].astype(str), sub["home_team"].astype(str))
    sub["venue"] = np.where(is_home, "home", "away")
    opp_tsi = np.where(is_home, pd.to_numeric(sub.get("a_tsi_pct"), errors="coerce"),
                       pd.to_numeric(sub.get("h_tsi_pct"), errors="coerce"))
    sub["opp_strength"] = opp_tsi
    return sub.reset_index(drop=True)


def runs_for(line: pd.DataFrame, team: str, w: int) -> list[Run]:
    """Every centre match of this club with the opponents around it, out to ±w where they exist.

    A run is kept even when one side is short: the current season's latest match has no "after" and
    a club's first match has no "before", and both are still comparable over what they do have.

    A run never crosses a season boundary. Without that clip a ±3 window around the first match of a
    new season reaches back into the last one, and the engine then "finds" a reversed sequence made
    half of one season and half of another — which is not a fixture sequence in any sense a reader
    means by the word."""
    out = []
    seasons = line["season"].astype(str).to_numpy()
    for i in range(len(line)):
        lo, hi = max(0, i - w), min(len(line) - 1, i + w)
        while lo < i and seasons[lo] != seasons[i]:
            lo += 1
        while hi > i and seasons[hi] != seasons[i]:
            hi -= 1
        if (i - lo) < MIN_SIDE and (hi - i) < MIN_SIDE:
            continue                                   # nothing either side: not a run
        r = line.iloc[i]
        out.append(Run(
            team=team, season=str(r.get("season", "")), centre_index=i,
            centre_opponent=str(r["opponent"]), centre_match_id=str(r.get("match_id", "")),
            centre_date=r["date"],
            before=[str(x) for x in line["opponent"].iloc[lo:i]],
            after=[str(x) for x in line["opponent"].iloc[i + 1:hi + 1]],
            before_strength=[float(x) for x in line["opp_strength"].iloc[lo:i]],
            after_strength=[float(x) for x in line["opp_strength"].iloc[i + 1:hi + 1]],
        ))
    return out


# --------------------------------------------------------------------------- comparing two runs

def _score(mine: dict[int, str], theirs: dict[int, str]) -> tuple[float, int]:
    """Share of the offsets BOTH runs have where the opponent is the same, and how many those were."""
    shared = [k for k in mine if k in theirs]
    if not shared:
        return 0.0, 0
    hit = sum(1 for k in shared if mine[k] == theirs[k])
    return 100.0 * hit / len(shared), len(shared)


def _wing_score(mine: dict[int, str], theirs: dict[int, str]) -> tuple[float, int]:
    """The same clubs before and the same clubs after, order inside each wing ignored.

    This is what the pattern graphics mean when they say 100 %, and it is a weaker claim than the
    positional one — so it travels next to it rather than instead of it."""
    shared = [k for k in mine if k in theirs]
    if not shared:
        return 0.0, 0
    hit = 0
    for group in ((k for k in shared if k < 0), (k for k in shared if k > 0)):
        ks = list(group)
        a, b = [mine[k] for k in ks], [theirs[k] for k in ks]
        left = list(b)
        for x in a:
            if x in left:
                left.remove(x)
                hit += 1
    if 0 in shared:
        hit += 1 if mine[0] == theirs[0] else 0
    return 100.0 * hit / len(shared), len(shared)


def _flip(slots: dict[int, str]) -> dict[int, str]:
    """The same run read backwards: offset k becomes offset -k."""
    return {-k: v for k, v in slots.items()}


def _roll(slots: dict[int, str], by: int) -> dict[int, str]:
    return {k - by: v for k, v in slots.items()}


def _strength_similarity(now: Run, past: Run, w: int) -> tuple[float, int]:
    """How close the two runs' opponents were in strength, position by position, ignoring names."""
    a, b = now.strength_slots(w), past.strength_slots(w)
    shared = [k for k in a if k in b and np.isfinite(a[k]) and np.isfinite(b[k])]
    if len(shared) < 2:
        return float("nan"), 0
    diff = float(np.mean([abs(a[k] - b[k]) for k in shared]))
    return float(100.0 * max(0.0, 1.0 - diff / STRENGTH_SCALE)), len(shared)


def compare(now: Run, past: Run, w: int) -> list[Cycle]:
    """Every shape this past run could be, scored over the offsets both runs actually have."""
    if past.centre_opponent != now.centre_opponent:
        return []
    mine, theirs = now.slots(w), past.slots(w)
    out: list[Cycle] = []

    pos, n = _score(mine, theirs)
    wing, _ = _wing_score(mine, theirs)
    if n:
        out.append(Cycle("EXACT_SAME", w, pos, pos, wing, n, past, now))

    flipped = _flip(theirs)
    rpos, rn = _score(mine, flipped)
    rwing, _ = _wing_score(mine, flipped)
    if rn:
        out.append(Cycle("EXACT_REVERSE", w, max(rpos, rwing), rpos, rwing, rn, past, now))

    best = None
    for k in range(-w, w + 1):
        if k == 0:
            continue
        sc, sn = _score(mine, _roll(theirs, k))
        if sn and (best is None or sc > best[0]):
            best = (sc, sn, k)
    if best:
        out.append(Cycle("SHIFTED", w, best[0], best[0], wing, best[1], past, now))

    st, sn = _strength_similarity(now, past, w)
    if np.isfinite(st):
        out.append(Cycle("STRENGTH", w, st, pos, wing, sn, past, now))
    return [c for c in out if c.similarity > 0 and c.n_compared >= 2]


# --------------------------------------------------------------------------- the search

def find_cycles(df: pd.DataFrame, team: str, centre_match_id: str | None = None,
                windows: tuple[int, ...] = WINDOWS, min_similarity: float = 50.0,
                per_kind: int = 3) -> dict:
    """Search every window and every past season automatically — the reader picks a team, not a
    search type. Returns the best cycles per shape, plus what was searched to find them."""
    line = team_line(df, team)
    if line.empty:
        return {"team": team, "cycles": [], "searched": 0, "note": "bu takımın veritabanında maçı yok"}

    if centre_match_id:
        centres = line.index[line["match_id"].astype(str) == str(centre_match_id)].tolist()
    else:
        # No centre given: every match of the club's current season is a candidate centre. The
        # graphics are never about the club's LAST match in particular — the Sassuolo run reverses
        # around the Bologna fixture, three matches back — so a reader who only names the club must
        # still be shown it. The cost is a few hundred extra comparisons per window.
        seasons = line["season"].astype(str)
        centres = line.index[seasons == seasons.iloc[-1]].tolist() or [len(line) - 1]
    if not centres:
        return {"team": team, "cycles": [], "searched": 0, "note": "merkez maç bulunamadı"}

    # More compared positions beats a wider search radius, and among equals the tighter window wins:
    # "±2 matched, over 5 positions" describes the same finding as "±4" more accurately, because the
    # extra slots a wider window asked for simply were not there.
    found: list[Cycle] = []
    searched = 0
    for w in windows:
        all_runs = runs_for(line, team, w)
        by_index = {r.centre_index: r for r in all_runs}
        for ci in centres:
            now = by_index.get(ci)
            if now is None:
                continue
            for past in all_runs:
                if past.centre_index >= now.centre_index or past.season == now.season:
                    continue                            # only earlier seasons, never the same one
                searched += 1
                found.extend(compare(now, past, w))

    best: dict[str, list[Cycle]] = {}
    for c in sorted(found, key=lambda x: (-x.similarity, -x.n_compared, x.window)):
        if c.similarity < min_similarity:
            continue
        seen = best.setdefault(c.kind, [])
        if any(s.past.centre_match_id == c.past.centre_match_id and s.now.centre_match_id == c.now.centre_match_id
               for s in seen):
            continue                                    # the same pair of matches, at a narrower window
        if len(seen) < per_kind:
            seen.append(c)

    order = {k: i for i, k in enumerate(KINDS)}
    cycles = sorted((c for v in best.values() for c in v),
                    key=lambda c: (-c.similarity, -c.n_compared, order.get(c.kind, 9), c.window))
    last = centres[-1]
    return {"team": team, "centre": {
        "match_id": str(line["match_id"].iloc[last]),
        "date": str(line["date"].iloc[last])[:10],
        "opponent": str(line["opponent"].iloc[last]),
        "season": str(line["season"].iloc[last]),
    }, "centres_searched": len(centres), "searched": searched, "windows": list(windows),
        "cycles": [c.as_dict() for c in cycles]}
