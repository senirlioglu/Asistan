"""MATCH STATE — what was knowable about a match before it kicked off.

The similarity engine in `models/` describes a match by its price alone: three (or five) numbers.
That is deliberately thin, and it is why "benzer maçlar" can pair a Bundesliga game with a
Brazilian one. The pattern work needs the other half of the picture — who the two teams were on
that day: their form, their goals, where they stood in the table, how strong the market thought
they were, when they last played.

This module walks the whole database once, in date order, and writes one row per match holding
that state. Everything is computed from matches played **strictly before** the match itself:

    for each match, in chronological order:
        1. read the running state of both teams   -> the feature row (pre-match)
        2. then fold this match's result into it  -> state for their next match

Step 2 comes after step 1 by construction, so a look-ahead leak would take a deliberate edit;
`tests/test_patterns.py` pins it anyway by rebuilding a prefix of the database and comparing.

TEAM STRENGTH INDEX (TSI)
-------------------------
Market-derived, as asked: an Elo rating whose target is not the result but the **market's own
pre-match expectation** (p_home + 0.5 * p_draw). Bookmakers see squads, injuries and motivation;
distilling their verdict is both less noisy than chasing results and honest about its source.
The rating is stored as it stood BEFORE the match.

Ratings only travel between teams that actually meet, so two leagues that never play each other
have incomparable scales — a 1700 in Denmark is not a 1700 in Spain. Therefore every row also
carries `tsi_pct`: the team's percentile among the teams of its own league on that date, which is
comparable across leagues. Use the percentile for cross-league work, the raw one inside a league.

Missing data is left missing: a team's first ever match in the pool has no form, and the extra-league
files carry no half-time score, so `since_rev` / `htft` stay null there rather than being invented.

`since_rev` is the count the owner's note 2 is about: the matches a team has played SINCE its last
half-time-to-full-time reversal (2/1 or 1/2), not counting the reversal itself. Today being "the
7th match after" therefore means `since_rev == 6`.
"""

from __future__ import annotations

import datetime as dt
from collections import defaultdict, deque
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

from ..config import Settings
from ..logging_setup import get_logger

log = get_logger("patterns.state")

# columns copied straight through from the match row, so the state table stands on its own: the
# research engines and the API can read it without joining the match database back in, and an
# upcoming fixture (no result yet) still carries its price
PASSTHROUGH = ("p_home", "p_draw", "p_away", "p_over25", "cons_h", "cons_d", "cons_a",
               "avgc_h", "avgc_d", "avgc_a",        # closing prices: the CLV benchmark for the cycle rows
               "ftr", "htr", "fthg", "ftag", "hthg", "htag", "total_goals", "delta_p_home", "result_code")

WINDOWS = (3, 5, 10)        # the look-back lengths every count feature is produced for
FORM_LEN = 10               # how many results the form strings keep
ELO_START = 1500.0
ELO_K = 20.0
ELO_HOME_ADV = 65.0         # in rating points; the usual football value, only used to form the expectation
ELO_SCALE = 8.0             # rating points per TSI point: 1500 -> 50, 1900 -> 100


def state_path(settings: Settings) -> Path:
    return settings.processed_dir / "match_state.parquet"


@dataclass
class TeamState:
    """The running record of one team, always as of "before the next match"."""

    elo: float = ELO_START
    results: deque = field(default_factory=lambda: deque(maxlen=FORM_LEN))        # "W"/"D"/"L", newest last
    venue_results: dict = field(default_factory=lambda: {"H": deque(maxlen=FORM_LEN), "A": deque(maxlen=FORM_LEN)})
    scored: deque = field(default_factory=lambda: deque(maxlen=max(WINDOWS)))
    conceded: deque = field(default_factory=lambda: deque(maxlen=max(WINDOWS)))
    dates: deque = field(default_factory=lambda: deque(maxlen=max(WINDOWS) + 5))
    since_rev: int | None = None     # matches played since this team's last 2/1 or 1/2 (None = never seen one)
    revs10: int = 0                  # how many of the last ten were reversals
    htft: deque = field(default_factory=lambda: deque(maxlen=FORM_LEN))     # "2/1", "1/1", ... newest last
    season: str | None = None
    played: int = 0          # this season
    points: int = 0
    gf: int = 0
    ga: int = 0

    def new_season(self, season: str) -> None:
        if self.season != season:
            self.season, self.played, self.points, self.gf, self.ga = season, 0, 0, 0, 0


def _form_string(results: deque, n: int) -> str:
    return "".join(list(results)[-n:])


def seq(form: str) -> list[int]:
    """W=1, D=0, L=-1 — the machine-readable form, oldest first. Derived on demand: the string is
    the storage format, this is what the matchers and any model read."""
    return [1 if c == "W" else 0 if c == "D" else -1 for c in form]


def _side_features(st: TeamState, venue: str, date: pd.Timestamp, table: dict) -> dict:
    """The pre-match state of one team, as a flat dict (prefixed by the caller)."""
    out: dict[str, object] = {}
    form = _form_string(st.results, FORM_LEN)
    out["form"] = form
    out["form_venue"] = _form_string(st.venue_results[venue], FORM_LEN)
    for n in WINDOWS:
        last = list(st.results)[-n:]
        if len(last) == n:
            out[f"w{n}"] = last.count("W")
            out[f"d{n}"] = last.count("D")
            out[f"l{n}"] = last.count("L")
            out[f"pts{n}"] = 3 * last.count("W") + last.count("D")
        gf, ga = list(st.scored)[-n:], list(st.conceded)[-n:]
        if len(gf) == n:
            out[f"gf{n}"] = sum(gf)
            out[f"ga{n}"] = sum(ga)
            out[f"gd{n}"] = sum(gf) - sum(ga)
            out[f"cs{n}"] = sum(1 for x in ga if x == 0)          # clean sheets
            out[f"fts{n}"] = sum(1 for x in gf if x == 0)         # failed to score
            out[f"btts{n}"] = sum(1 for a, b in zip(gf, ga) if a > 0 and b > 0)
            out[f"ov15_{n}"] = sum(1 for a, b in zip(gf, ga) if a + b > 1.5)
            out[f"ov25_{n}"] = sum(1 for a, b in zip(gf, ga) if a + b > 2.5)
            out[f"ov35_{n}"] = sum(1 for a, b in zip(gf, ga) if a + b > 3.5)
    if st.dates:
        out["rest_days"] = int((date - st.dates[-1]).days)
        out["games7"] = sum(1 for d in st.dates if 0 <= (date - d).days <= 7)
        out["games14"] = sum(1 for d in st.dates if 0 <= (date - d).days <= 14)
    out["last_gf"] = int(st.scored[-1]) if st.scored else None      # note 19: "son maçını 2-3 kaybeden"
    out["last_ga"] = int(st.conceded[-1]) if st.conceded else None
    out["since_rev"] = st.since_rev          # note 2 reads this: today is the 7th match after == 6
    out["revs10"] = st.revs10
    out["htft"] = st.htft[-1] if st.htft else None
    out["elo"] = round(st.elo, 1)
    out["tsi"] = round(min(100.0, max(0.0, 50.0 + (st.elo - ELO_START) / ELO_SCALE)), 1)
    out["tsi_pct"] = table.get("pct")
    out["pos"] = table.get("pos")
    out["played"] = st.played
    out["pts"] = st.points
    out["gd"] = st.gf - st.ga
    return out


def _table_positions(states: dict[str, TeamState], league_teams: set[str], season: str | None) -> dict[str, dict]:
    """League position (points, then goal difference) and TSI percentile, for the teams of one league."""
    rows = [(t, states[t]) for t in league_teams if t in states]
    ranked = sorted(rows, key=lambda r: (-r[1].points, -(r[1].gf - r[1].ga), -r[1].gf))
    pos = {t: i + 1 for i, (t, s) in enumerate(ranked) if s.season == season}
    elos = sorted(s.elo for _, s in rows)
    out = {}
    for team, st in rows:
        pct = 100.0 * (np.searchsorted(elos, st.elo, side="right") / len(elos)) if elos else None
        out[team] = {"pos": pos.get(team), "pct": round(pct, 1) if pct is not None else None}
    return out


def build_state(df: pd.DataFrame, progress_every: int = 40000) -> pd.DataFrame:
    """One row per match with both teams' pre-match state. `df` must hold the processed schema."""
    need = {"match_id", "date", "league", "season", "home_team", "away_team", "fthg", "ftag", "ftr"}
    missing = need - set(df.columns)
    if missing:
        raise ValueError(f"match state needs columns {sorted(missing)}")
    df = df.sort_values(["date", "league", "home_team"], kind="mergesort").reset_index(drop=True)
    passthrough = {c for c in PASSTHROUGH if c in df.columns}
    states: dict[str, TeamState] = defaultdict(TeamState)
    league_teams: dict[str, set[str]] = defaultdict(set)
    h2h: dict[tuple[str, str], list[str]] = defaultdict(list)     # (a,b) sorted -> results seen from a's view
    tables: dict[tuple[str, pd.Timestamp], dict] = {}
    rows: list[dict] = []

    for i, r in enumerate(df.itertuples(index=False)):
        if progress_every and i and i % progress_every == 0:
            log.info("match state: %d / %d", i, len(df))
        home, away, league, season, date = r.home_team, r.away_team, r.league, r.season, r.date
        hs, as_ = states[home], states[away]
        hs.new_season(season)
        as_.new_season(season)
        # a cup or European tie names each club's own league (home_league / away_league): the clubs stay
        # in their domestic tables and their standings come from there, not from a two-club "league"
        lg_h = getattr(r, "home_league", None) or league
        lg_a = getattr(r, "away_league", None) or league
        lg_h = league if not isinstance(lg_h, str) else lg_h
        lg_a = league if not isinstance(lg_a, str) else lg_a
        league_teams[lg_h].add(home)
        league_teams[lg_a].add(away)
        if tables and next(iter(tables))[1] != date:
            tables.clear()                       # only the current day is ever needed
        for lg in (lg_h, lg_a):
            if (lg, date) not in tables:
                tables[(lg, date)] = _table_positions(states, league_teams[lg], season)
        table_h, table_a = tables[(lg_h, date)], tables[(lg_a, date)]

        row: dict[str, object] = {"match_id": r.match_id, "date": date, "league": league, "season": season,
                                  "home_team": home, "away_team": away}
        for col in PASSTHROUGH:
            if col in passthrough:
                row[col] = getattr(r, col, None)
        for prefix, st, venue, table, team in (("h_", hs, "H", table_h, home), ("a_", as_, "A", table_a, away)):
            for k, v in _side_features(st, venue, date, table.get(team, {})).items():
                row[prefix + k] = v
        row["strength_gap"] = round(hs.elo - as_.elo, 1)
        if row["h_tsi_pct"] is not None and row["a_tsi_pct"] is not None:
            row["tsi_pct_gap"] = round(row["h_tsi_pct"] - row["a_tsi_pct"], 1)
        pair = tuple(sorted((home, away)))
        seen = h2h[pair]
        row["h2h_n"] = len(seen)
        if seen:
            first = pair[0]
            row["h2h_home_wins"] = sum(1 for x in seen if x == ("W" if first == home else "L"))
            row["h2h_draws"] = seen.count("D")
            row["h2h_away_wins"] = row["h2h_n"] - row["h2h_home_wins"] - row["h2h_draws"]
        rows.append(row)

        # ---- only now may this match's own result be folded in ----
        gh, ga = r.fthg, r.ftag
        if pd.isna(gh) or pd.isna(ga):
            continue
        gh, ga = int(gh), int(ga)
        res_home = "W" if gh > ga else "D" if gh == ga else "L"
        res_away = {"W": "L", "L": "W", "D": "D"}[res_home]
        # half-time -> full-time, from each side's own view: "2/1" means trailed at the break, won the match
        ht_home = getattr(r, "htr", None)
        htft_home = htft_away = None
        if isinstance(ht_home, str) and ht_home in ("H", "D", "A"):
            code = {"H": "1", "D": "X", "A": "2"}
            htft_home = f"{code[ht_home]}/{code[r.ftr]}"
            flip = {"1": "2", "2": "1", "X": "X"}
            htft_away = f"{flip[htft_home[0]]}/{flip[htft_home[2]]}"
        for st, res, scored, conceded, venue, hf in ((hs, res_home, gh, ga, "H", htft_home), (as_, res_away, ga, gh, "A", htft_away)):
            if hf is not None:
                st.htft.append(hf)
                reversed_ = hf in ("1/2", "2/1")
                st.since_rev = 0 if reversed_ else (None if st.since_rev is None else st.since_rev + 1)
                st.revs10 = sum(1 for x in st.htft if x in ("1/2", "2/1"))
            st.results.append(res)
            st.venue_results[venue].append(res)
            st.scored.append(scored)
            st.conceded.append(conceded)
            st.dates.append(date)
            st.played += 1
            st.points += 3 if res == "W" else 1 if res == "D" else 0
        hs.gf += gh; hs.ga += ga
        as_.gf += ga; as_.ga += gh
        h2h[pair].append(res_home if pair[0] == home else res_away)
        # the market's verdict drives the rating, not the scoreline
        mkt = getattr(r, "p_home", np.nan)
        mkt_draw = getattr(r, "p_draw", np.nan)
        target = (mkt + 0.5 * mkt_draw) if pd.notna(mkt) and pd.notna(mkt_draw) else None
        if target is not None:
            exp_home = 1.0 / (1.0 + 10 ** ((as_.elo - hs.elo - ELO_HOME_ADV) / 400.0))
            delta = ELO_K * (float(target) - exp_home)
            hs.elo += delta
            as_.elo -= delta

    out = pd.DataFrame(rows)
    log.info("match state: %d rows, %d columns", len(out), len(out.columns))
    return out


def fixture_rows(table: pd.DataFrame) -> pd.DataFrame:
    """Today's analysed fixtures in the shape the builder reads, so upcoming matches get a state row.

    They carry no result, so they never move a team's form or rating — `build_state` folds a match in
    only when it has a score — but they do get the two teams' state as it stands today, which is what
    the research tab needs to find a fixture's twins."""
    if table is None or not len(table):
        return pd.DataFrame()
    from ..config import current_season_code

    out = pd.DataFrame({
        "match_id": table["match_id"], "date": pd.to_datetime(table["date"]), "league": table["league"],
        "season": current_season_code(), "home_team": table["home"], "away_team": table["away"],
        "fthg": np.nan, "ftag": np.nan, "ftr": None,
        "p_home": pd.to_numeric(table["market_h"], errors="coerce") / 100,
        "p_draw": pd.to_numeric(table["market_d"], errors="coerce") / 100,
        "p_away": pd.to_numeric(table["market_a"], errors="coerce") / 100,
        "cons_h": table.get("odds_h"), "cons_d": table.get("odds_d"), "cons_a": table.get("odds_a"),
        "p_over25": pd.to_numeric(table.get("market_over25"), errors="coerce") / 100,
    })
    for col in ("home_league", "away_league"):     # a cup tie: each club's own league for its standings
        if col in table.columns:
            out[col] = table[col]
    return out[~out["match_id"].isna()]


def build(settings: Settings, df: pd.DataFrame | None = None, write: bool = True,
          fixtures: pd.DataFrame | None = None) -> pd.DataFrame:
    """Build the state table from the processed database and (by default) write it next to it."""
    if df is None:
        df = pd.read_parquet(settings.processed_dir / "matches.parquet")
    if fixtures is not None and len(fixtures):
        extra = fixture_rows(fixtures)
        if len(extra):
            df = pd.concat([df, extra[~extra["match_id"].isin(df["match_id"])]], ignore_index=True)
    started = dt.datetime.now()
    out = build_state(df)
    if write:
        p = state_path(settings)
        p.parent.mkdir(parents=True, exist_ok=True)
        out.to_parquet(p, index=False)
        log.info("wrote %s in %.0fs", p, (dt.datetime.now() - started).total_seconds())
    return out


def load(settings: Settings) -> pd.DataFrame | None:
    p = state_path(settings)
    return pd.read_parquet(p) if p.exists() else None
