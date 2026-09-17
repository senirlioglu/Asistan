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


def test_cup_ties_are_not_placed(settings, history):
    hist = history.copy()
    hist.loc[hist["home_team"] == "H1", "league"] = "E0"
    hist.loc[hist["away_team"] == "A2", "league"] = "SP1"
    hist.loc[hist["home_team"] == "A2", "league"] = "SP1"
    hist.loc[hist["away_team"] == "H1", "league"] = "E0"
    table, meta = nf.nesine_fixture_table(settings, hist=hist, matches=_bulletin()[:1], today=dt.date(2030, 1, 1))
    assert table.empty and meta == {}


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
