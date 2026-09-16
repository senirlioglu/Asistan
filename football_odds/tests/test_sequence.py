"""Fixture sequence engine: the shapes must be found without being asked for, and a run that is
still in progress must be compared over what it has rather than over what it will have."""

import pandas as pd
import pytest

from src.patterns import sequence as sq


def _line(team: str, opponents: list[str], season: str = "2526", start: str = "2026-01-01",
          strengths: list[float] | None = None) -> pd.DataFrame:
    """One club's season as a frame the engine can read: it always plays at home, for simplicity."""
    rows = []
    for i, opp in enumerate(opponents):
        rows.append({"match_id": f"{team}-{season}-{i}", "date": pd.Timestamp(start) + pd.Timedelta(days=7 * i),
                     "season": season, "league": "I1", "home_team": team, "away_team": opp,
                     "h_tsi_pct": 50.0, "a_tsi_pct": (strengths[i] if strengths else 50.0)})
    return pd.DataFrame(rows)


def _db(*frames) -> pd.DataFrame:
    return pd.concat(frames, ignore_index=True).sort_values(["date", "match_id"]).reset_index(drop=True)


def test_the_reverse_cycle_is_found_without_being_asked_for():
    """The Sassuolo case from the graphics, in miniature: the reader picks a team, not a search type."""
    past = _line("S", ["Juventus", "Monza", "Bologna", "Torino", "Atalanta"], "2324", "2024-01-01")
    now = _line("S", ["Atalanta", "Torino", "Bologna", "Juventus", "Monza"], "2627", "2026-08-01")
    out = sq.find_cycles(_db(past, now), "S", min_similarity=60)

    assert out["centre"]["opponent"] == "Monza"          # the latest match, reported for orientation
    assert out["centres_searched"] == 5                  # ... but every match of the season was a candidate centre
    auto = out["cycles"][0]
    assert auto["kind"] == "EXACT_REVERSE" and auto["window"] == 2 and auto["similarity"] == 100.0
    assert auto["now"]["opponents"][auto["now"]["centre"]] == "Bologna"   # found without naming the centre
    got = sq.find_cycles(_db(past, now), "S", centre_match_id="S-2627-2", min_similarity=60)
    best = got["cycles"][0]
    assert best["kind"] == "EXACT_REVERSE"
    assert best["window"] == 2 and best["n_compared"] == 5
    assert best["wing"] == 100.0                         # the same two clubs before, the same two after
    assert best["positional"] == 60.0                    # but Juventus and Monza swap inside the wing
    assert best["similarity"] == 100.0                   # the headline follows the shape's own reading


def test_positional_and_wing_are_both_reported_because_they_disagree():
    """The graphics quote the wing score and call it 100 %. Neither number is wrong; quoting one
    without the other is — so a caller can never see only the flattering one."""
    past = _line("S", ["A", "B", "C", "D", "E"], "2324", "2024-01-01")
    now = _line("S", ["E", "D", "C", "A", "B"], "2627", "2026-08-01")     # wings reversed, order swapped
    out = sq.find_cycles(_db(past, now), "S", centre_match_id="S-2627-2", min_similarity=10)
    rev = next(c for c in out["cycles"] if c["kind"] == "EXACT_REVERSE")
    assert rev["wing"] > rev["positional"]
    assert set(rev) >= {"positional", "wing", "n_compared", "similarity"}


def test_a_run_still_in_progress_is_compared_over_what_it_has():
    """The current season has no "after" side yet: the schedule knows who is coming, the database of
    played matches does not. Inventing the missing half would turn "the season just started" into a
    match, so the comparison runs over the shared offsets and says how many those were."""
    past = _line("S", ["Juventus", "Monza", "Bologna", "Torino", "Atalanta"], "2324", "2024-01-01")
    now = _line("S", ["Atalanta", "Torino", "Bologna"], "2627", "2026-08-01")      # ends at the centre
    out = sq.find_cycles(_db(past, now), "S", centre_match_id="S-2627-2", min_similarity=60)
    rev = next(c for c in out["cycles"] if c["kind"] == "EXACT_REVERSE")
    assert rev["similarity"] == 100.0
    assert rev["n_compared"] == 3                       # two before plus the centre, and it says so
    assert len(rev["now"]["opponents"]) == 3


def test_a_cycle_never_matches_a_different_centre_opponent():
    past = _line("S", ["A", "B", "Bologna", "C", "D"], "2324", "2024-01-01")
    now = _line("S", ["D", "C", "Inter", "B", "A"], "2627", "2026-08-01")
    out = sq.find_cycles(_db(past, now), "S", centre_match_id="S-2627-2", min_similarity=10)
    assert out["cycles"] == []                          # the run reverses, but it is a different fixture


def test_a_run_never_crosses_a_season_boundary():
    """Without the clip, a wide window around an early match reaches back into the previous season
    and the engine "finds" a sequence made half of one season and half of another."""
    prev = _line("S", ["P1", "P2", "P3", "P4", "P5"], "2526", "2025-08-01")
    now = _line("S", ["A", "B", "Bologna"], "2627", "2026-08-01")
    line = sq.team_line(_db(prev, now), "S")
    runs = {r.centre_match_id: r for r in sq.runs_for(line, "S", 4)}
    centre = runs["S-2627-2"]
    assert centre.before == ["A", "B"] and centre.after == []      # never P4, P5
    assert set(centre.slots(4)) == {-2, -1, 0}


def test_the_same_season_is_never_its_own_cycle():
    line = _line("S", ["A", "B", "Bologna", "B", "A"], "2627", "2026-08-01")
    out = sq.find_cycles(_db(line), "S", centre_match_id="S-2627-2", min_similarity=10)
    assert out["cycles"] == []


def test_a_strength_sequence_matches_without_the_names_matching():
    """Spec 4.3: the clubs need not be the same, the strength profile at the time must be."""
    past = _line("S", ["A", "B", "Bologna", "C", "D"], "2324", "2024-01-01",
                 strengths=[80.0, 30.0, 50.0, 80.0, 30.0])
    now = _line("S", ["X", "Y", "Bologna", "Z", "W"], "2627", "2026-08-01",
                strengths=[82.0, 28.0, 50.0, 79.0, 31.0])
    out = sq.find_cycles(_db(past, now), "S", centre_match_id="S-2627-2", min_similarity=50)
    kinds = {c["kind"] for c in out["cycles"]}
    assert "STRENGTH" in kinds and "EXACT_SAME" not in kinds     # nothing shares a name
    st = next(c for c in out["cycles"] if c["kind"] == "STRENGTH")
    # the centre opponent is the same by construction, so one of the five positions always matches
    assert st["similarity"] > 85 and st["positional"] == 20.0


def test_every_window_and_every_past_season_is_searched_automatically():
    """Spec 4.1 and 4.2: no season picker, no window picker, no search-type picker."""
    frames = [_line("S", ["A", "B", "Bologna", "C", "D"], f"{y}{y + 1}", f"20{y}-01-01") for y in (20, 21, 22)]
    frames.append(_line("S", ["D", "C", "Bologna", "B", "A"], "2627", "2026-08-01"))
    out = sq.find_cycles(_db(*frames), "S", centre_match_id="S-2627-2", min_similarity=60)
    assert out["windows"] == [2, 3, 4] and out["searched"] > 3
    assert any(c["kind"] == "EXACT_REVERSE" and c["similarity"] == 100.0 for c in out["cycles"])


def test_an_unknown_team_says_so_rather_than_returning_nothing_quietly():
    out = sq.find_cycles(_db(_line("S", ["A", "B", "C"])), "Yok", min_similarity=10)
    assert out["cycles"] == [] and "veritabanında maçı yok" in out["note"]
