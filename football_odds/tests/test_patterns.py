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
    empty = engine.measure(pool.head(0), "home", "win")
    assert empty["n"] == 0 and empty["actual"] is None and empty["diff"] is None
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


def test_half_time_outcomes_read_the_break_and_skip_the_matches_without_one():
    pool = _pool([
        {"date": "2026-01-01", "home_team": "A", "away_team": "B", "htr": "H", "ftr": "A", "hthg": 1, "htag": 0},   # 1/2
        {"date": "2026-01-02", "home_team": "A", "away_team": "B", "htr": "A", "ftr": "H", "hthg": 0, "htag": 2},   # 2/1
        {"date": "2026-01-03", "home_team": "A", "away_team": "B", "htr": "D", "ftr": "H", "hthg": 1, "htag": 1},
        {"date": "2026-01-04", "home_team": "A", "away_team": "B", "htr": "H", "ftr": "H", "hthg": 1, "htag": 0},
        {"date": "2026-01-05", "home_team": "A", "away_team": "B", "htr": None, "ftr": "H"},                        # no half-time
    ])
    assert engine.measure(pool, "home", "reversal") == {**engine.measure(pool, "home", "reversal"), "n": 3, "actual": 66.7}
    assert engine.measure(pool, "home", "ht_win")["n"] == 4 and engine.measure(pool, "home", "ht_win")["actual"] == 50.0
    assert engine.measure(pool, "home", "ht_draw")["actual"] == 25.0
    assert engine.measure(pool, "home", "ht_1_0")["actual"] == 50.0          # 1-0 twice out of the four known
    assert engine.measure(pool, "away", "ht_win")["actual"] == 25.0


def test_the_reference_is_matches_at_the_same_price_not_the_whole_pool():
    """The trap the notes fall into: a pattern that selects favourites beats the pool average by
    construction. Priced-matched against other favourites, the same pattern must come out flat."""
    rows = []
    for i in range(400):
        fav = i % 2 == 0                                   # half the pool are favourites...
        flagged = i % 4 == 0                               # ... and half of THOSE carry the pattern
        # the win cycle runs on i // 4 so it is identical inside and outside the flagged half
        won = ((i // 4) % 4 != 3) if fav else ((i // 4) % 4 == 0)     # favourites 75 %, the rest 25 %
        rows.append({"date": f"2026-0{1 + i // 200}-{1 + i % 28:02d}", "home_team": "A", "away_team": "B",
                     "htr": "H" if won else "A", "ftr": "H" if won else "A", "hthg": 1 if won else 0,
                     "htag": 0 if won else 1, "p_home": 0.75 if fav else 0.35, "p_away": 0.2 if fav else 0.6,
                     "h_form": "WWWWW" if flagged else "LLLLL"})
    pool = _pool(rows)
    pool["match_id"] = [f"m{i}" for i in range(len(pool))]
    sub = engine.select(pool, engine.Pattern(form="WWWWW"))
    assert len(sub) == 100
    naive = engine.pool_rates(pool, "home", ("ht_win",))["ht_win"]
    matched = engine.matched_rates(pool, sub, "home", ("ht_win",))["ht_win"]
    assert round(naive, 2) == 0.50 and round(matched, 2) == 0.75   # the pool says 50 %, their own price says 75 %
    m = engine.measure(sub, "home", "ht_win", ref=matched)
    assert m["actual"] == 75.0 and m["vs_ref"] == 0.0              # against matches priced alike: nothing
    assert engine.measure(sub, "home", "ht_win", ref=naive)["vs_ref"] == 25.0   # the misleading version


def test_benjamini_hochberg_holds_the_noise_back():
    assert engine.fdr([]) == [] and engine.fdr([None, None]) == [None, None]
    # one real effect among twenty coin flips: only the real one survives
    q = engine.fdr([0.0001] + [0.2 + 0.04 * i for i in range(19)])
    assert q[0] <= 0.05 and all(x > 0.05 for x in q[1:])
    # the smallest p of a batch of "significant-looking" results does not survive on its own
    assert all(x > 0.05 for x in engine.fdr([0.04, 0.06, 0.2, 0.5, 0.9]))
    assert engine.fdr([0.5, None, 0.01])[1] is None


def test_the_notebook_notes_are_measured_with_their_caveats(settings):
    from src.patterns import notes

    rows = []
    for i in range(300):                       # every match has a home favourite at 1.67
        rows.append({"date": f"2026-0{1 + i // 150}-{1 + i % 28:02d}", "home_team": "A", "away_team": "B",
                     "htr": "H" if i % 3 else "D", "ftr": "H" if i % 3 else "D", "hthg": 1 if i % 3 else 0,
                     "htag": 0, "p_home": 0.56, "p_draw": 0.25, "p_away": 0.19, "p_over25": 0.5,
                     "cons_h": 1.67, "cons_a": 5.0, "total_goals": 2.0})
    pool = _pool(rows)
    pool["match_id"] = [f"m{i}" for i in range(len(pool))]
    pool["odds_gap"] = (pool["cons_h"] - pool["cons_a"]).abs()
    pool["fav_odds"] = pool[["cons_h", "cons_a"]].min(axis=1)
    pool["h_since_rev"] = 6
    pool["a_since_rev"] = 0
    out = notes.measure_notes(pool)
    by = {(r["id"], r["side"]): r for r in out}
    assert by[("n10", "ev sahibi")]["n"] == 300                # every match matches "exactly 1.67"
    assert by[("n2", "ev sahibi")]["n"] == 300                 # ... and every one is a 7th match after
    assert all("q" in c for r in out for c in r["claims"])     # every claim carries its corrected p
    assert notes.verdict({"n": 0}) == "ölçülemedi"
    assert "N=" in notes.report(out)


# --------------------------------------------------------------------------- the twin engine
from src.patterns import twins  # noqa: E402


def _twin_pool(rows: list[dict]) -> pd.DataFrame:
    pool = _pool(rows)
    pool["match_id"] = [f"t{i}" for i in range(len(pool))]
    for col, default in (("h_gf5", 7.0), ("h_ga5", 5.0), ("a_gf5", 6.0), ("a_ga5", 6.0), ("delta_p_home", 0.0)):
        if col not in pool:
            pool[col] = default
    return pool


def _twin_row(date, hf, af, p_home=0.5, **kw):
    return {"date": date, "home_team": "H", "away_team": "A", "h_form": hf, "a_form": af, "ftr": "H",
            "p_home": p_home, "p_draw": 0.25, "p_away": 0.95 - p_home - 0.25,
            "h_tsi_pct": 60.0, "a_tsi_pct": 40.0, "strength_gap": 80.0, **kw}


def test_a_twin_of_itself_scores_a_hundred_everywhere():
    pool = _twin_pool([_twin_row("2026-01-01", "WWDLW", "LDWDL"), _twin_row("2026-01-02", "WWDLW", "LDWDL")])
    res = twins.TwinIndex(pool).query(pool.iloc[1], k=5)
    assert list(res.rows["match_id"]) == ["t0"]                      # itself is never its own twin
    top = res.rows.iloc[0]
    assert top["twin_score"] == 100.0
    assert all(top[f"sim_{c}"] == 100.0 for c in ("market", "strength", "opponent", "gap", "form", "goals"))


def test_a_team_with_two_matches_played_is_not_a_perfect_form_match():
    """The bug this pins: NaN slots were skipped, so half a history matched everything."""
    pool = _twin_pool([_twin_row("2026-01-01", "DW", "LDWDL"),            # only two results known
                       _twin_row("2026-01-02", "WWDDW", "LDWDL"),         # four of five slots agree
                       _twin_row("2026-01-03", "WWDLW", "LDWDL")])        # the query itself
    idx = twins.TwinIndex(pool)
    res = idx.query(pool.iloc[2], k=5)
    by = res.rows.set_index("match_id")
    assert pd.isna(by.loc["t0", "sim_form"])                              # not comparable, not 100
    assert 0 < by.loc["t1", "sim_form"] < 100                             # comparable, imperfect
    assert by.loc["t1", "twin_score"] > by.loc["t0", "twin_score"]


def test_weights_decide_what_similar_means():
    pool = _twin_pool([
        _twin_row("2026-01-01", "LLLLL", "WWWWW", p_home=0.50),           # same price, opposite form
        _twin_row("2026-01-02", "WWDLW", "LDWDL", p_home=0.20),           # same form, different price
        _twin_row("2026-01-03", "WWDLW", "LDWDL", p_home=0.50),           # the query
    ])
    q = pool.iloc[2]
    by_market = twins.TwinIndex(pool, weights=twins.Weights(market=10, strength=0, opponent=0, gap=0, form=0, goals=0, movement=0))
    by_form = twins.TwinIndex(pool, weights=twins.Weights(market=0, strength=0, opponent=0, gap=0, form=10, goals=0, movement=0))
    assert by_market.query(q, k=2).rows.iloc[0]["match_id"] == "t0"
    assert by_form.query(q, k=2).rows.iloc[0]["match_id"] == "t1"


def test_the_query_only_sees_earlier_matches_and_reports_how_far_the_last_twin_is():
    rows = [_twin_row(f"2026-01-{d:02d}", "WWDLW", "LDWDL", p_home=0.3 + d / 100) for d in range(1, 21)]
    pool = _twin_pool(rows)
    idx = twins.TwinIndex(pool)
    res = idx.query(pool.iloc[10], k=5, as_of=pool.iloc[10]["date"])
    assert len(res.rows) == 5 and (res.rows["date"] < pool.iloc[10]["date"]).all()
    d = res.diagnostics
    assert d["k"] == 5 and d["asked"] == 5 and d["n_candidates"] == 10
    assert d["best"] >= d["median"] >= d["worst"]                          # the K-th twin's own score is reported
    assert set(d["categories"]) == set(res.weights)
    # what the twins did, always next to what their own prices said
    assert res.outcomes["win"]["n"] == 5 and res.outcomes["win"]["market"] is not None


def test_k_sweep_shows_what_widening_the_neighbourhood_costs():
    rows = [_twin_row(f"2026-0{1 + d // 28}-{1 + d % 28:02d}", "WWDLW", "LDWDL", p_home=0.3 + (d % 30) / 100)
            for d in range(60)]
    pool = _twin_pool(rows)
    sweep = twins.k_sweep(twins.TwinIndex(pool), pool.iloc[-1], ks=(5, 10, 25), as_of=pool.iloc[-1]["date"])
    assert list(sweep["k"]) == [5, 10, 25] and (sweep["n"] <= sweep["k"]).all()
    assert (sweep["worst"].diff().dropna() <= 0).all()                     # a wider K can only reach further out
    assert sweep["win_market"].notna().all()
