"""Match state: the features must describe the past only, and describe it correctly."""

import numpy as np
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


# --------------------------------------------------------------------------- the model comparison
from src.patterns import evaluate  # noqa: E402


def test_pattern_residuals_are_learned_and_shrunk():
    """Teams on a good run winning more than their price says must show up as a positive residual,
    scaled down by how thin the bucket is."""
    rows = []
    for i in range(1200):
        good = i % 2 == 0
        # the price says 50 % everywhere; the good-form home sides actually win 60 %, the others 40 %
        won = (i % 10 < 6) if good else (i % 10 < 4)
        rows.append({"date": f"2026-0{1 + i // 600}-{1 + i % 28:02d}", "home_team": "H", "away_team": "A",
                     "ftr": "H" if won else "A", "p_home": 0.5, "p_draw": 0.0, "p_away": 0.5,
                     "h_pts5": 13 if good else 1, "a_pts5": 7})
    train = _pool(rows)
    res = evaluate.fit_pattern_residuals(train).set_index(["hb", "ab"])
    good_r = res.loc[(3, 1), "r_home"]                       # top points bucket, mid away bucket
    poor_r = res.loc[(0, 1), "r_home"]
    assert good_r > 0.02 and poor_r < -0.02                  # direction
    raw = 0.10                                                # 60 % vs a 50 % price
    assert good_r < raw                                       # ... but shrunk towards zero
    assert abs(good_r - raw * 600 / (600 + evaluate.SHRINK_N)) < 0.01

    test = _pool([{"date": "2026-03-01", "home_team": "H", "away_team": "A", "ftr": "H",
                   "p_home": 0.5, "p_draw": 0.0, "p_away": 0.5, "h_pts5": 13, "a_pts5": 7},
                  {"date": "2026-03-02", "home_team": "H", "away_team": "A", "ftr": "H",
                   "p_home": 0.5, "p_draw": 0.0, "p_away": 0.5, "h_pts5": None, "a_pts5": None}])
    market = test[["p_home", "p_draw", "p_away"]].to_numpy(dtype=float)
    out = evaluate.apply_pattern_residuals(test, evaluate.fit_pattern_residuals(train), market)
    assert out[0][0] > market[0][0]                           # the bucket moves the price up
    assert abs(out[1][0] - 0.5) < 0.01                        # an unknown bucket leaves it alone
    assert np.allclose(out.sum(axis=1), 1.0)


def test_score_reports_loss_roi_and_closing_line_value():
    test = _pool([
        {"date": "2026-01-01", "home_team": "H", "away_team": "A", "ftr": "H", "cons_h": 2.0, "cons_d": 3.5,
         "cons_a": 4.0, "avgc_h": 1.8, "avgc_d": 3.5, "avgc_a": 4.5},
        {"date": "2026-01-02", "home_team": "H", "away_team": "A", "ftr": "A", "cons_h": 2.0, "cons_d": 3.5,
         "cons_a": 4.0, "avgc_h": 2.2, "avgc_d": 3.5, "avgc_a": 3.6},
    ])
    test["result_code"] = [0, 2]
    probs = np.array([[0.6, 0.2, 0.2], [0.6, 0.2, 0.2]])      # always picks the home side
    row = evaluate.score("test", probs, test, base=None)
    assert row["n"] == 2 and row["n_bets"] == 2 and row["hit_rate"] == 50.0
    assert row["roi"] == 0.0                                   # +1.0 then -1.0 at odds 2.00
    # taken 2.00 against closing 1.80 and 2.20: +11,1 % and -9,1 %, so about +1 % on average
    assert row["clv"] == round(100 * ((2 / 1.8 - 1) + (2 / 2.2 - 1)) / 2, 2) and row["n_clv"] == 2
    beaten = evaluate.score("worse", np.array([[0.2, 0.2, 0.6], [0.6, 0.2, 0.2]]), test, base=probs)
    assert "brier_diff" in beaten and "p_value" in beaten


def test_summarise_weights_the_seasons_by_their_size():
    per = pd.DataFrame([
        {"season": "2324", "model": "A", "n": 100, "brier": 0.60, "logloss": 1.0, "calib_err": 0.02,
         "brier_diff": None, "roi": -10.0, "hit_rate": 50.0, "clv": 0.0},
        {"season": "2425", "model": "A", "n": 300, "brier": 0.50, "logloss": 0.9, "calib_err": 0.04,
         "brier_diff": None, "roi": 2.0, "hit_rate": 54.0, "clv": 1.0},
    ])
    out = evaluate.summarise(per).iloc[0]
    assert out["n"] == 400 and out["brier"] == 0.525 and out["roi"] == -1.0   # 0.25 / 0.75 weights


# --------------------------------------------------------------------------- pattern discovery
from src.patterns import discovery  # noqa: E402


def test_the_candidate_grid_is_countable_and_every_name_is_unique():
    cands = discovery.candidates()
    assert len(cands) == len(discovery.FORMS) * 2 * len(discovery.PRICE_BANDS) * len(discovery.REST_BANDS)
    # two candidates differing only by their rest band must not print the same label (they did once)
    names = [(c.side, c.label()) for c in cands]
    assert len(set(names)) == len(names)
    keys = [discovery._key(c) for c in cands]
    assert len(set(keys)) == len(keys)


def test_windows_are_time_based_and_never_overlap():
    w = discovery.DEFAULT_WINDOWS
    frame = _pool([{"date": d, "home_team": "H", "away_team": "A", "ftr": "H", "p_home": 0.5, "p_away": 0.25}
                   for d in ("2015-01-01", "2019-01-01", "2023-01-01")])
    assert len(w.slice(frame, "train")) == 1 and len(w.slice(frame, "validation")) == 1
    assert len(w.slice(frame, "test")) == 1
    assert w.train[1] == w.validation[0] and w.validation[1] == w.test[0]     # contiguous, no gap, no overlap


def _discovery_pool(real_edge: float, train_only_edge: float) -> pd.DataFrame:
    """A pool where one pattern holds in all three windows, one only in the first, and the rest is
    background priced correctly — so the pool's own baseline stays at zero, as in real data."""
    rows, counter = [], {}
    for window, year0, n_years in (("train", 2012, 7), ("validation", 2019, 3), ("test", 2022, 3)):
        for yr in range(n_years):
            for month in range(1, 5):
                for day in range(1, 29):
                    groups = [("WWWWW", real_edge), ("LLL", train_only_edge if window == "train" else 0.0)]
                    # the background outnumbers the patterns ten to one, as in the real pool, so one
                    # strong pattern cannot drag the pool's own baseline with it
                    groups += [(f, 0.0) for f in ("DDD", "WDWDW", "WLWLW", "DD")] * 5
                    for form, edge in groups:
                        # count per group, so each group's rate is exactly what it is meant to be
                        c = counter[form] = counter.get(form, 0) + 1
                        p_home = 0.45
                        won = (c % 100) < (100 * (p_home + edge))       # the price is right except for `edge`
                        rows.append({"date": f"{year0 + yr}-{month:02d}-{day:02d}",
                                     "home_team": "H", "away_team": "A", "h_form": form, "a_form": "WDWDW",
                                     # no draws in this toy world, and the price says so too: otherwise
                                     # every group would carry a huge permanent edge on the away side
                                     "ftr": "H" if won else "A", "p_home": p_home, "p_draw": 0.0,
                                     "p_away": 1.0 - p_home,
                                     "htr": "H" if won else "A", "hthg": 1, "htag": 0, "total_goals": 2.0,
                                     "p_over25": 0.5})
    pool = _pool(rows)
    pool["match_id"] = [f"d{j}" for j in range(len(pool))]
    return pool


def test_a_pattern_that_only_works_in_the_discovery_window_is_thrown_out():
    pool = _discovery_pool(real_edge=0.15, train_only_edge=0.15)
    pats = [engine.Pattern(form=f, side="home") for f in ("WWWWW", "LLL", "DDD")]
    res = discovery.discover(pool, min_n=100, patterns=pats)
    s = res["stages"]
    assert s["candidates"] == 3 and s["claims_scanned"] > 0
    names = {(r["form"], r["outcome"]) for _, r in res["survivors"].iterrows()} if len(res["survivors"]) else set()
    assert ("WWWWW", "win") in names                       # real in all three windows -> survives
    assert not any(f == "LLL" for f, _ in names)           # only real in the first -> dies
    assert not any(f == "DDD" for f, _ in names)           # never real -> never even enters
    # the report says how many died where, and never claims more than the survivors
    text = discovery.report(res)
    assert "SAĞ KALANLAR" in text and "aday desen: 3" in text


def test_nothing_survives_when_the_price_is_always_right():
    pool = _discovery_pool(real_edge=0.0, train_only_edge=0.0)
    res = discovery.discover(pool, min_n=100, patterns=[engine.Pattern(form=f, side="home") for f in ("WWWWW", "LLL")])
    assert res["stages"]["survived_test"] == 0
    assert "Hiçbir desen üç pencereden de geçemedi." in discovery.report(res)


# --------------------------------------------------------------------------- time decay and tuning
from src.patterns import tune  # noqa: E402


def test_time_decay_makes_an_old_twin_count_for_less():
    """A twin from twelve years ago is still a twin; its evidence is simply worth less."""
    old, new = np.datetime64("2014-01-01"), np.datetime64("2025-01-01")
    w = twins.decay_weights(np.array([old, new]), pd.Timestamp("2026-01-01"), half_life=5.0)
    assert w[1] > w[0] > 0
    assert round(float(w[0] / w[1]), 3) == round(float(0.5 ** (11 / 5)), 3)   # eleven years apart
    flat = twins.decay_weights(np.array([old, new]), pd.Timestamp("2026-01-01"), half_life=None)
    assert list(flat) == [1.0, 1.0]                                          # the pre-decay behaviour


def test_decayed_outcomes_move_towards_the_recent_twins_and_shrink_the_sample():
    """Half the twins say one thing in 2013 and the other half the opposite in 2025."""
    rows = []
    for d, ftr in [("2013-01-01", "H"), ("2013-02-01", "H"), ("2025-01-01", "A"), ("2025-02-01", "A")]:
        rows.append({**_twin_row(d, "WWDLW", "LDWDL"), "ftr": ftr})
    rows.append(_twin_row("2026-01-01", "WWDLW", "LDWDL"))
    pool = _twin_pool(rows)
    q, as_of = pool.iloc[4], pool.iloc[4]["date"]

    flat = twins.TwinIndex(pool).query(q, k=4, as_of=as_of)
    decayed = twins.TwinIndex(pool, half_life=3.0).query(q, k=4, as_of=as_of)

    assert flat.outcomes["win"]["actual"] == 50.0                            # two of four, unweighted
    assert decayed.outcomes["win"]["actual"] < 20.0                          # the 2013 pair barely counts
    assert decayed.diagnostics["n_eff"] < flat.diagnostics["n_eff"] == 4.0   # and it says so
    assert decayed.outcomes["win"]["n"] == 4                                 # the raw count is unchanged
    assert decayed.outcomes["win"]["n_eff"] < 4.0


def test_a_decayed_sample_carries_a_wider_interval_at_the_same_rate():
    """Compared at an unchanged rate — otherwise the interval moves because p moved, not because the
    evidence thinned."""
    rows = [{**_twin_row(d, "WWDLW", "LDWDL"), "ftr": "H"}
            for d in ("2013-01-01", "2013-02-01", "2025-01-01", "2025-02-01")]
    pool = _twin_pool(rows + [_twin_row("2026-01-01", "WWDLW", "LDWDL")])
    q, as_of = pool.iloc[4], pool.iloc[4]["date"]
    flat = twins.TwinIndex(pool).query(q, k=4, as_of=as_of).outcomes["win"]
    decayed = twins.TwinIndex(pool, half_life=3.0).query(q, k=4, as_of=as_of).outcomes["win"]
    assert flat["actual"] == decayed["actual"] == 100.0
    assert decayed["ci"][0] < flat["ci"][0]                                   # same rate, less certainty


def test_the_batch_scorer_reproduces_the_live_query():
    """`tune` re-weights cached category scores instead of running a query per configuration; if the
    two ever disagree the search would be tuning something the site does not run."""
    rows = [_twin_row(f"2026-01-{d:02d}", "WWDLW" if d % 2 else "LLDWW", "LDWDL", p_home=0.3 + d / 100)
            for d in range(1, 16)]
    pool = _twin_pool(rows).sort_values(["date", "match_id"]).reset_index(drop=True)
    idx = twins.TwinIndex(pool)
    q = pool.iloc[[14]]
    cfg = tune._Scored(twins.Weights(), None)
    batch = tune._probs_for_configs(idx, q, [cfg], k=6, log_every=0)[0, 0]

    res = idx.query(pool.iloc[14], k=6, as_of=pool.iloc[14]["date"])
    ftr = res.rows["ftr"].astype(str).to_numpy()
    assert np.allclose(batch, [(ftr == "H").mean(), (ftr == "D").mean(), (ftr == "A").mean()], atol=1e-6)


def test_a_category_at_weight_zero_is_absent_rather_than_scored_fifty():
    """Zero weight must drop the category out of both sums; counting it as `missing` at 50 would let
    a switched-off category still push the score around."""
    pool = _twin_pool([_twin_row("2026-01-01", "WWDLW", "LDWDL", p_home=0.20),
                       _twin_row("2026-01-02", "WWDLW", "LDWDL", p_home=0.50)])
    w = twins.Weights(market=0.0, strength=1.0, opponent=1.0, gap=1.0, form=1.0, goals=1.0, movement=1.0)
    res = twins.TwinIndex(pool, weights=w).query(pool.iloc[1], k=2)
    assert res.rows.iloc[0]["twin_score"] == 100.0        # identical everywhere except the ignored price


def test_a_tuned_mix_that_loses_on_the_test_window_is_not_adopted(tmp_path):
    """The third window is not decoration: a configuration that only looked good while being chosen
    must never reach the live engine."""
    import json

    (tmp_path / "backtest").mkdir()
    payload = {"chosen": {"weights": {"market": 9.0, "strength": 0.0, "opponent": 0.0, "gap": 0.0,
                                      "form": 0.0, "goals": 0.0, "movement": 0.0}, "half_life": 3.0},
               "beats_default_on_test": False, "test": {}}
    p = tmp_path / "backtest" / "twin_weights.json"
    p.write_text(json.dumps(payload), encoding="utf-8")

    w, hl, meta = twins.load_weights(tmp_path)
    assert w.as_dict() == twins.Weights().as_dict() and hl is None
    assert meta["source"] == "varsayılan" and "geçemedi" in meta["reason"]

    p.write_text(json.dumps({**payload, "beats_default_on_test": True}), encoding="utf-8")
    w, hl, meta = twins.load_weights(tmp_path)
    assert w.market == 9.0 and w.form == 0.0 and hl == 3.0 and meta["source"] == "ayarlanmış"


def test_tuning_never_scores_a_configuration_on_the_window_that_chose_it():
    """The windows must not overlap — otherwise `test` is just more validation."""
    v_lo, v_hi = tune.DEFAULT_WINDOWS.validation
    t_lo, t_hi = tune.DEFAULT_WINDOWS.test
    assert pd.Timestamp(v_hi) <= pd.Timestamp(t_lo)
    assert pd.Timestamp(tune.DEFAULT_WINDOWS.train[1]) <= pd.Timestamp(v_lo)


# --------------------------------------------------------------------------- team A x team B

def _row(date, home, away, **kw):
    """One prepared row with the columns the combined queries read; everything else defaults."""
    return {"date": date, "home_team": home, "away_team": away,
            "p_home": 0.45, "p_draw": 0.27, "p_away": 0.28, **kw}


def test_a_pattern_can_describe_both_teams_at_once():
    """"A side on WWW" and "a side on WWW facing a side on LLL" are different claims, and only the
    second one is about a fixture."""
    pool = _pool([
        _row("2026-01-01", "H", "A", h_form="WWW", a_form="LLL", ftr="H"),
        _row("2026-01-02", "H", "B", h_form="WWW", a_form="WWW", ftr="A"),
        _row("2026-01-03", "H", "C", h_form="WWW", a_form="LLL", ftr="D"),
        _row("2026-01-04", "H", "D", h_form="LLL", a_form="LLL", ftr="H"),
    ])
    one_side = engine.select(pool, engine.Pattern(form="WWW", side="home"))
    both = engine.select(pool, engine.Pattern(form="WWW", opp_form="LLL", side="home"))
    assert len(one_side) == 3 and len(both) == 2
    assert set(both["away_team"]) == {"A", "C"}
    # read from the away side the roles swap: the opponent is now the home team
    flipped = engine.select(pool, engine.Pattern(form="LLL", opp_form="WWW", side="away"))
    assert set(flipped["away_team"]) == {"A", "C"}


def test_the_opponent_gets_its_own_tolerance_and_shows_up_in_the_label():
    pool = _pool([
        _row("2026-01-01", "H", "A", h_form="WWW", a_form="LLL", ftr="H"),
        _row("2026-01-02", "H", "B", h_form="WWW", a_form="LDL", ftr="H"),
    ])
    strict = engine.Pattern(form="WWW", opp_form="LLL", side="home")
    loose = engine.Pattern(form="WWW", opp_form="LLL", side="home", opp_approx=1)
    assert len(engine.select(pool, strict)) == 1 and len(engine.select(pool, loose)) == 2
    assert "rakip LLL" in strict.label() and "rakip LLL (±1)" in loose.label()
    assert "saha formu" in engine.Pattern(form="WW", venue_form="WW", side="home").label()


def test_the_venue_form_narrows_alongside_the_overall_form_not_instead_of_it():
    """`form_venue=True` swaps which column `form` reads; `venue_form` is a second condition. The
    two must not be confused — stacking both sequences is what collapses the sample."""
    pool = _pool([
        _row("2026-01-01", "H", "A", h_form="WWW", h_form_venue="LLL", ftr="H"),
        _row("2026-01-02", "H", "B", h_form="WWW", h_form_venue="WWW", ftr="H"),
    ])
    assert len(engine.select(pool, engine.Pattern(form="WWW", side="home"))) == 2
    assert len(engine.select(pool, engine.Pattern(form="WWW", form_venue=True, side="home"))) == 1
    assert len(engine.select(pool, engine.Pattern(form="WWW", venue_form="WWW", side="home"))) == 1


def test_the_cascade_only_ever_narrows_and_says_what_each_step_cost():
    pool = _pool([_row(f"2026-01-{d:02d}", "H", f"T{d}", h_form="WWW" if d % 2 else "LLL",
                       a_form="LLL" if d % 3 else "WWW", h_tsi_pct=50.0 + d, ftr="H" if d % 2 else "A")
                  for d in range(1, 25)])
    steps = [
        ("form", engine.Pattern(form="WWW", side="home")),
        ("+ güç", engine.Pattern(form="WWW", side="home", tsi_pct=(50, 70))),
        ("+ rakip", engine.Pattern(form="WWW", side="home", tsi_pct=(50, 70), opp_form="LLL")),
    ]
    rows = engine.cascade(pool, steps, outcomes=("win",))
    assert [r["step"] for r in rows] == ["form", "+ güç", "+ rakip"]
    ns = [r["n"] for r in rows]
    assert ns == sorted(ns, reverse=True)                     # a condition can only remove matches
    assert rows[0]["n_lost"] is None and rows[1]["n_lost"] == ns[0] - ns[1]
    assert rows[2]["n_before"] == ns[1]
    # running each step against the whole pool must give the same counts as the nested walk
    assert ns == [len(engine.select(pool, p)) for _, p in steps]


def test_the_combined_engine_never_reads_a_later_match():
    """Spec 25, as a test: every historical row a query may see must predate the query's own date."""
    pool = _pool([_row(f"2026-01-{d:02d}", "H", f"T{d}", h_form="WWW", a_form="LLL", ftr="H")
                  for d in range(1, 21)])
    cut = pd.Timestamp("2026-01-10")
    rows = engine.cascade(pool, [("form", engine.Pattern(form="WWW", side="home")),
                                 ("+ rakip", engine.Pattern(form="WWW", opp_form="LLL", side="home"))],
                          as_of=cut, outcomes=("win",))
    assert all(r["n"] == 9 for r in rows)                     # the 1st to the 9th, never the 10th on
    seen = engine.select(pool, engine.Pattern(form="WWW", opp_form="LLL", side="home"), as_of=cut)
    assert seen["date"].max() < cut


def test_an_unpriced_outcome_is_compared_with_matches_at_the_same_price():
    """The oldest trap in this project, caught in production on the explorer: a team on WWW leads at
    half time far more often than the pool average, because it is a better team. Compared with the
    pool the pattern "discovers" +8.9 points; compared with matches priced the same way it finds
    nothing. Half-time markets carry no price, so the reference has to be built, not assumed."""
    rows = []
    for i in range(400):                       # strong sides: priced high AND lead at half time
        rows.append(_row(f"2026-01-{1 + i % 28:02d}", "H", f"S{i}", h_form="WWW", ftr="H",
                         p_home=0.70, p_draw=0.18, p_away=0.12, htr="H" if i % 10 < 7 else "D"))
    for i in range(400):                       # weak sides: priced low AND rarely lead
        rows.append(_row(f"2026-02-{1 + i % 28:02d}", "H", f"W{i}", h_form="LLL", ftr="A",
                         p_home=0.30, p_draw=0.28, p_away=0.42, htr="H" if i % 10 < 2 else "D"))
    pool = _pool(rows)
    sub = engine.select(pool, engine.Pattern(form="WWW", side="home"))

    naive = engine.pool_rates(pool, "home", ("ht_win",))["ht_win"]
    matched = engine.matched_rates(pool, sub, "home", ("ht_win",))["ht_win"]
    assert round(100 * naive) == 45                       # every match, strong and weak together
    assert round(100 * matched) == 70                     # only matches priced like these ones

    vs_pool = engine.measure(sub, "home", "ht_win", ref=naive)
    vs_price = engine.measure(sub, "home", "ht_win", ref=matched)
    assert vs_pool["vs_ref"] > 20                          # a discovery, made of nothing
    assert abs(vs_price["vs_ref"]) < 1                     # and it is gone when the price is matched
