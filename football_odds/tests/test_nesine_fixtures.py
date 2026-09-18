"""nesine's bulletin as state-table fixtures: name resolution, league placement, no-vig prices, dedup."""

import datetime as dt

import pandas as pd

from src.nesine import fixtures as nf


def _bulletin():
    return [
        {"code": 101, "date": "2030-01-05", "time": "20:00", "home": "H1", "away": "A2", "league": "Lig A",
         "ms": {"1": 2.0, "X": 3.5, "2": 4.0}, "o25": {"ust": 1.8, "alt": 2.0}},
        {"code": 102, "date": "2030-01-05", "time": "20:00", "home": "H1", "away": "A2", "league": "Lig A",   # duplicate line
         "ms": {"1": 2.0, "X": 3.5, "2": 4.0}},
        {"code": 103, "date": "2030-01-06", "time": "18:00", "home": "H3", "away": "Nobody FC", "league": "Lig B",
         "ms": {"1": 1.5, "X": 4.0, "2": 6.0}},                                                     # away unknown
        {"code": 104, "date": "2029-12-01", "time": "18:00", "home": "H3", "away": "A4", "league": "Lig B",
         "ms": {"1": 1.5, "X": 4.0, "2": 6.0}},                                                     # in the past
        {"code": 105, "date": "2030-01-06", "time": "18:00", "home": "H5", "away": "A6", "league": "Kupa",
         "ms": {"1": 1.5, "X": 4.0}},                                                               # no full 1X2
    ]


def _leagues(hist):
    long = pd.concat([hist[["home_team", "league", "date"]].rename(columns={"home_team": "team"}),
                      hist[["away_team", "league", "date"]].rename(columns={"away_team": "team"})])
    return long.sort_values("date").groupby("team")["league"].last().to_dict()


def test_fixture_table_resolves_and_prices(settings, history):
    hist = history.copy()
    # put the pair of the first line into one league so it is a league fixture we can place
    lg = _leagues(hist)
    hist.loc[(hist["home_team"] == "H1") | (hist["away_team"] == "H1") | (hist["home_team"] == "A2") | (hist["away_team"] == "A2"), "league"] = "E0"
    table, meta = nf.nesine_fixture_table(settings, hist=hist, matches=_bulletin(), today=dt.date(2030, 1, 1))
    assert len(table) == 1, table                          # the duplicate, the unknown club, the past and the unpriced are all dropped
    r = table.iloc[0]
    assert (r["home"], r["away"], r["league"], r["date"]) == ("H1", "A2", "E0", "2030-01-05")
    assert abs(r["market_h"] + r["market_d"] + r["market_a"] - 100) < 0.05     # margin removed
    assert r["market_h"] > r["market_d"] > r["market_a"] and r["odds_h"] == 2.0
    assert abs(r["market_over25"] - 100 * (1 / 1.8) / (1 / 1.8 + 1 / 2.0)) < 0.05
    assert meta[r["match_id"]]["code"] == 101 and meta[r["match_id"]]["league_name"] == "Lig A"
    assert r["match_id"] == nf._match_id("E0", "2030-01-05", "H1", "A2")


def test_cup_ties_are_placed_with_each_clubs_own_league(settings, history):
    hist = history.copy()
    hist.loc[hist["home_team"] == "H1", "league"] = "E0"
    hist.loc[hist["away_team"] == "A2", "league"] = "SP1"
    hist.loc[hist["home_team"] == "A2", "league"] = "SP1"
    hist.loc[hist["away_team"] == "H1", "league"] = "E0"
    # what nesine calls a league fixture cannot join two of our leagues: that is a name resolved to the wrong club
    table, meta = nf.nesine_fixture_table(settings, hist=hist, matches=_bulletin()[:1], today=dt.date(2030, 1, 1))
    assert table.empty
    cup = [{**_bulletin()[0], "league": "UEFA Avrupa Ligi"}]
    table, meta = nf.nesine_fixture_table(settings, hist=hist, matches=cup, today=dt.date(2030, 1, 1))
    assert len(table) == 1
    r = table.iloc[0]
    assert (r["league"], r["home_league"], r["away_league"]) == (nf.CUP, "E0", "SP1")
    assert nf.is_cup("Brezilya Serie B") is False and nf.is_cup("İngiltere Lig Kupası") and nf.is_cup("Libertadores Kupası")
    assert r["match_id"] == nf._match_id(nf.CUP, "2030-01-05", "H1", "A2")


def test_merge_prefers_the_analysed_row():
    have = pd.DataFrame([{"match_id": "fd1", "date": "2030-01-05", "home": "H1", "away": "A2", "league": "E0"}])
    extra = pd.DataFrame([
        {"match_id": "n1", "date": "2030-01-06", "home": "H1", "away": "A2", "league": "E0"},   # same clubs, date rolled over midnight
        {"match_id": "n2", "date": "2030-01-06", "home": "H7", "away": "A8", "league": "E0"},   # genuinely new
        {"match_id": "fd1", "date": "2030-01-05", "home": "H1", "away": "A2", "league": "E0"},  # same id
    ])
    out = nf.merge_fixtures(have, extra)
    assert list(out["match_id"]) == ["fd1", "n2"]
    assert nf.merge_fixtures(None, extra) is extra and nf.merge_fixtures(have, None) is have


def test_meta_roundtrip(settings, tmp_path):
    import copy

    from src.config import Settings

    s = Settings(raw=copy.deepcopy(settings.raw), root=settings.root)
    s.raw.setdefault("data", {})["results_dir"] = str(tmp_path)
    nf.write_meta(s, {"abc": {"code": 5, "time": "20:00", "league_name": "Lig"}})
    assert nf.read_meta(s)["abc"]["code"] == 5


def _fake_analysis(hit):
    import numpy as np

    summary = pd.Series({"match_id": "x", "n": 120, "n_eff": 100.0, "confidence": "MEDIUM", "signal": "NEUTRAL", "signal_outcome": "home",
                         "market_h": 40.0, "market_d": 28.0, "market_a": 32.0, "hist_h": 42.0, "hist_d": 27.0, "hist_a": 31.0,
                         "adj_h": 41.0, "adj_d": 27.5, "adj_a": 31.5, "edge_h": 1.0, "edge_d": -0.5, "edge_a": -0.5,
                         "over25": 50.0, "under25": 50.0, "btts": 48.0, "avg_goals": np.float64(2.6), "avg_similarity": 95.0,
                         "median_similarity": 95.5, "min_similarity": 90.0, "ci_h_lo": 35.0, "ci_h_hi": 47.0, "ci_d_lo": 20.0, "ci_d_hi": 35.0,
                         "ci_a_lo": 25.0, "ci_a_hi": 38.0, "fair_h": 2.4, "fair_d": 3.6, "fair_a": 3.2, "market_over25": np.nan,
                         "scorelines": {"1-0": 0.1}})
    analogues = pd.DataFrame([{"date": pd.Timestamp("2024-03-02"), "league": "E0", "home_team": "H1", "away_team": "A2", "cons_h": 2.0,
                               "cons_d": 3.5, "cons_a": 4.0, "similarity": 98.0, "ftr": "H", "fthg": 2.0, "ftag": 0.0, "distance": 0.01}])
    return {"summary": summary, "analogues": analogues, "details": {"scorelines": {"1-0": np.float64(0.1)}, "goals_dist": {}, "scopes": {}},
            "feature_set": "1x2", "overround": 1.06}


def test_bulletin_is_analysed_into_prediction_files_and_cached(settings, history, tmp_path, monkeypatch):
    import copy
    import datetime as dt2

    from src.config import Settings
    from src.nesine import analyze

    s = Settings(raw=copy.deepcopy(settings.raw), root=settings.root)
    s.raw.setdefault("data", {})["results_dir"] = str(tmp_path / "results")
    hist = history.copy()
    for t in ("H1", "A2"):
        hist.loc[(hist["home_team"] == t) | (hist["away_team"] == t), "league"] = "E0"
    matches = _bulletin()[:1]
    table, meta = nf.nesine_fixture_table(s, hist=hist, matches=matches, today=dt2.date(2030, 1, 1))
    calls = []
    monkeypatch.setattr(analyze, "analyse", lambda st, hit, as_of=None: (calls.append(hit["code"]) or _fake_analysis(hit)))
    now = dt2.datetime(2030, 1, 4, 10, tzinfo=dt2.timezone.utc)
    assert nf.analyse_bulletin(s, table, meta, matches=matches, now=now) == 1
    pred = pd.read_csv(s.results_dir / nf.PRED_NAME)
    assert list(pred["match_id"]) == list(table["match_id"]) and pred.iloc[0]["home"] == "H1" and pred.iloc[0]["source"] == "nesine"
    assert pred.iloc[0]["nesine_code"] == 101 and pred.iloc[0]["league_name"] == "Lig A" and pred.iloc[0]["odds_h"] == 2.0
    assert nf.read_details(s)[pred.iloc[0]["match_id"]]["scorelines"]["1-0"] == 0.1
    an = pd.read_parquet(s.results_dir / "analogues" / nf.ANALOGUES_NAME)
    assert list(an["fixture_id"]) == [pred.iloc[0]["match_id"]]
    # an hour later with the same price: kept, not re-analysed
    assert nf.analyse_bulletin(s, table, meta, matches=matches, now=now + dt2.timedelta(hours=1)) == 0 and calls == [101]
    # the price moved: analysed again
    moved = copy.deepcopy(matches); moved[0]["ms"]["1"] = 2.4
    assert nf.analyse_bulletin(s, table, meta, matches=moved, now=now + dt2.timedelta(hours=1)) == 1 and calls == [101, 101]
    # a day later: stale by age
    assert nf.analyse_bulletin(s, table, meta, matches=moved, now=now + dt2.timedelta(hours=30)) == 1
