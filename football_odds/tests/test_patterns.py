"""Match state: the features must describe the past only, and describe it correctly."""

import pandas as pd
import pytest

from src.patterns import state


def _frame(rows: list[dict]) -> pd.DataFrame:
    """A minimal processed-schema frame: the builder only needs these columns."""
    df = pd.DataFrame(rows)
    df["date"] = pd.to_datetime(df["date"])
    df["match_id"] = [f"m{i}" for i in range(len(df))]
    df["league"] = df.get("league", "E0")
    df["season"] = df.get("season", "2526")
    df["ftr"] = ["H" if h > a else "D" if h == a else "A" for h, a in zip(df["fthg"], df["ftag"])]
    for col in ("p_home", "p_draw", "p_away"):
        if col not in df:
            df[col] = float("nan")
    return df


def _m(date, home, away, hg, ag, **kw):
    return {"date": date, "home_team": home, "away_team": away, "fthg": hg, "ftag": ag, **kw}


def test_form_goals_table_and_h2h_are_read_off_the_earlier_matches():
    df = _frame([
        _m("2026-01-01", "A", "B", 4, 0),
        _m("2026-01-04", "C", "A", 1, 1),
        _m("2026-01-08", "A", "C", 5, 1),
        _m("2026-01-11", "B", "A", 2, 0),
        _m("2026-01-14", "A", "B", 4, 1),     # A's last three: 5-1, 0-2 (away), 4-1
        _m("2026-01-17", "A", "C", 0, 0),     # <- the row under test
    ])
    row = state.build_state(df).iloc[-1]
    assert row["h_form"] == "WDWLW" and row["h_form_venue"] == "WWW"      # B's win came away from A
    assert state.seq(row["h_form"]) == [1, 0, 1, -1, 1]
    assert row["h_gf3"] == 9 and row["h_ga3"] == 4                         # 5+0+4 scored, 1+2+1 conceded
    assert row["h_cs3"] == 0 and row["h_fts3"] == 1 and row["h_btts3"] == 2
    assert row["h_rest_days"] == 3 and row["h_games7"] == 2 and row["h_games14"] == 4
    assert row["h_played"] == 5 and row["h_pts"] == 10 and row["h_gd"] == 9
    assert row["a_form"] == "DL" and row["a_played"] == 2                  # C drew, then lost 1-5
    assert row["h_pos"] == 1                                               # A leads the table on points
    # H2H is counted from TODAY'S home team's view: A drew 1-1 at C, then beat C 5-1
    assert (row["h2h_n"], row["h2h_home_wins"], row["h2h_draws"], row["h2h_away_wins"]) == (2, 1, 1, 0)


def test_state_never_looks_at_the_match_itself_or_later_ones():
    """Rebuild each row from the prefix of the database that precedes it: the features must match."""
    rows = []
    teams = ["A", "B", "C", "D"]
    for i in range(40):
        h, a = teams[i % 4], teams[(i + 1 + i // 4) % 4]
        if h == a:
            a = teams[(i + 2) % 4]
        rows.append(_m(f"2026-{1 + i // 20:02d}-{1 + i % 20:02d}", h, a, i % 4, (i + 1) % 3,
                       p_home=0.4 + (i % 5) / 20, p_draw=0.25, p_away=0.35 - (i % 5) / 20))
    df = _frame(rows)
    full = state.build_state(df).set_index("match_id")
    for mid in ("m20", "m31", "m39"):
        target = df[df["match_id"] == mid]
        earlier = df[df["date"] < target["date"].iloc[0]]
        # the same match, but with every later match (and every same-day one) removed from the pool
        partial = state.build_state(pd.concat([earlier, target], ignore_index=True)).set_index("match_id")
        a, b = full.loc[mid], partial.loc[mid]
        same = [c for c in full.columns if c not in ("date",)]
        pd.testing.assert_series_equal(a[same], b[same], check_names=False, obj=f"{mid} rebuilt from its own past")


def test_tsi_follows_the_market_not_the_scoreline():
    """The rating distils what bookmakers thought, so a heavy favourite that keeps losing keeps its rating."""
    rows = [_m(f"2026-01-{d:02d}", "Fav", "Dog", 0, 1, p_home=0.80, p_draw=0.12, p_away=0.08) for d in range(1, 11)]
    out = state.build_state(_frame(rows))
    assert out["h_elo"].iloc[0] == state.ELO_START
    assert out["h_elo"].iloc[-1] > out["h_elo"].iloc[0] + 30      # ten losses, still rated up: the market said so
    assert out["strength_gap"].iloc[-1] > 60
    # ... and with no odds at all the rating cannot move
    flat = state.build_state(_frame([_m(f"2026-02-{d:02d}", "X", "Y", 3, 0) for d in range(1, 6)]))
    assert flat["h_elo"].nunique() == 1 == flat["a_elo"].nunique()


def test_build_writes_next_to_the_database(settings, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "raw", settings.with_overrides(**{"data.processed_dir": str(tmp_path)}).raw)
    df = _frame([_m("2026-01-01", "A", "B", 1, 0), _m("2026-01-05", "B", "A", 2, 2)])
    out = state.build(settings, df)
    assert state.state_path(settings).exists() and len(state.load(settings)) == len(out) == 2
    with pytest.raises(ValueError, match="match state needs columns"):
        state.build_state(df.drop(columns=["fthg"]))


# --------------------------------------------------------------------------- the pattern engine
from src.patterns import engine  # noqa: E402


def _pool(rows: list[dict]) -> pd.DataFrame:
    """A prepared frame (state + market + result), built by hand so every number below is arithmetic."""
    df = pd.DataFrame(rows)
    df["date"] = pd.to_datetime(df["date"])
    df["league"] = df.get("league", "E0")
    df["fthg"] = df.get("fthg", 1)
    df["ftag"] = df.get("ftag", 0)
    for col, default in (("h_form_venue", ""), ("a_form_venue", ""), ("h_tsi_pct", 50.0), ("a_tsi_pct", 50.0),
                         ("strength_gap", 0.0), ("p_draw", 0.25), ("p_over25", 0.5), ("total_goals", 2.0),
                         ("h_rest_days", 7), ("h_pos", 5), ("a_form", ""), ("h_form", "")):
        if col not in df:
            df[col] = default
    return df


def test_form_matcher_reads_the_tail_with_wildcards_and_slack():
    assert engine.form_matches("LLWWWWW", "WWWWW")               # the last five
    assert not engine.form_matches("WWWWWLL", "WWWWW")           # the pattern must END the form
    assert engine.form_matches("WWWDWWW", "WWW-D-WWW")           # dashes are only separators
    assert engine.form_matches("DWLWW", "?WW") and engine.form_matches("DWLWW", "??W")
    assert engine.form_matches("WWDWW", "WWWWW", approx=1) and not engine.form_matches("WWDWW", "WWWWW")
    assert not engine.form_matches("WW", "WWWWW") and not engine.form_matches("WWWWW", "")


def test_select_applies_every_filter_and_the_as_of_cutoff():
    pool = _pool([
        {"date": "2026-01-01", "home_team": "A", "away_team": "B", "h_form": "WWWWW", "ftr": "H", "p_home": 0.5, "p_away": 0.25},
        {"date": "2026-01-02", "home_team": "C", "away_team": "D", "h_form": "LLLLL", "ftr": "A", "p_home": 0.3, "p_away": 0.45},
        {"date": "2026-01-03", "home_team": "A", "away_team": "D", "h_form": "WWWWW", "ftr": "D", "p_home": 0.6, "p_away": 0.2,
         "league": "SP1", "h_tsi_pct": 90.0, "strength_gap": 120.0},
    ])
    assert len(engine.select(pool, engine.Pattern(form="WWWWW"))) == 2
    assert len(engine.select(pool, engine.Pattern(form="WWWWW", team="A"))) == 2
    assert len(engine.select(pool, engine.Pattern(form="WWWWW", leagues=["SP1"]))) == 1
    assert len(engine.select(pool, engine.Pattern(form="WWWWW", tsi_pct=(80, 100)))) == 1
    assert len(engine.select(pool, engine.Pattern(gap=(100, 200)))) == 1
    assert len(engine.select(pool, engine.Pattern(market=(0.55, 0.7)))) == 1
    assert len(engine.select(pool, engine.Pattern(extra={"h_rest_days": (0, 3)}))) == 0
    # as_of keeps the pool strictly in the past, same-day matches included
    assert len(engine.select(pool, engine.Pattern(), as_of=pd.Timestamp("2026-01-03"))) == 2
    # the away side reads the away team's columns and flips the gap
    assert len(engine.select(pool, engine.Pattern(side="away", gap=(-200, -100)))) == 1


def test_measure_compares_against_what_the_market_said():
    rows = []
    for i in range(10):                       # six home wins, the market said 50 % every time
        rows.append({"date": f"2026-01-{i + 1:02d}", "home_team": "A", "away_team": "B", "h_form": "WWWWW",
                     "ftr": "H" if i < 6 else "A", "p_home": 0.5, "p_away": 0.25})
    pool = _pool(rows)
    m = engine.measure(pool, "home", "win")
    assert m["n"] == 10 and m["actual"] == 60.0 and m["market"] == 50.0 and m["diff"] == 10.0
    assert m["ci"][0] < 60.0 < m["ci"][1] and m["diff_ci"][0] < 10.0 < m["diff_ci"][1]
    assert engine.measure(pool, "home", "loss")["actual"] == 40.0
    assert engine.measure(pool.head(0), "home", "win") == {"n": 0, "actual": None, "market": None, "diff": None,
                                                           "ci": [None, None], "diff_ci": [None, None], "n_market": 0}
    # a market that is right on average leaves no difference to report
    even = _pool([{"date": "2026-02-01", "home_team": "A", "away_team": "B", "ftr": "H", "p_home": 1.0, "p_away": 0.0},
                  {"date": "2026-02-02", "home_team": "A", "away_team": "B", "ftr": "A", "p_home": 0.0, "p_away": 1.0}])
    assert engine.measure(even, "home", "win")["diff"] == 0.0


def test_the_pool_wide_offset_is_taken_out_before_anything_is_called_an_edge():
    """Our margin-free consensus runs ~0,6 points low on home wins; uncorrected, every pattern
    would inherit that for free. `baseline()` measures it and `run(base=...)` subtracts it."""
    rows = []
    for i in range(200):                      # the market is 5 points too low on EVERY match
        rows.append({"date": f"2026-0{1 + i // 100}-{1 + i % 28:02d}", "home_team": "A", "away_team": "B",
                     # i % 4 < 2 wins half the matches in BOTH form groups: the pattern is average
                     "h_form": "WWWWW" if i % 2 else "LLLLL", "ftr": "H" if i % 4 < 2 else "A",
                     "p_home": 0.45, "p_away": 0.3})
    pool = _pool(rows)
    base = engine.baseline(pool, "home", ("win",))
    assert round(base["win"], 1) == 5.0
    res = engine.run(pool, engine.Pattern(form="WWWWW"), outcomes=("win",), base=base)
    m = res["outcomes"]["win"]
    assert m["diff"] == 5.0 and m["edge"] == 0.0            # average pattern, no edge left
    assert not engine.beats_market(m)                       # ... and it is not reported as one
    assert m["edge_ci"][0] < 0 < m["edge_ci"][1]


def test_levels_splits_into_this_club_everybody_and_comparable_strength():
    rows = [{"date": f"2026-01-{i + 1:02d}", "home_team": "A" if i < 5 else "Z", "away_team": "B", "h_form": "WWW",
             "ftr": "H", "p_home": 0.5, "p_away": 0.25, "h_tsi_pct": 90.0 if i < 5 else 20.0} for i in range(10)]
    out = engine.levels(_pool(rows), engine.Pattern(form="WWW"), team="A", tsi_pct=90.0, outcomes=("win",))
    assert out["all"]["n"] == 10 and out["same_team"]["n"] == 5 and out["similar"]["n"] == 5
    assert "A" in out["same_team"]["label"]
