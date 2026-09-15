import pandas as pd

from src.pipeline import scorecard as sc


def _row(**kw):
    base = {"id": "m1", "stamp": "2026-09-14", "league": "E0", "date_uk": "2026-09-14", "time_uk": "20:00", "date": "2026-09-14", "time": "22:00",
            "home": "Arsenal", "away": "Everton", "market": {"h": 60.0, "d": 22.0, "a": 18.0}, "adj": {"h": 55.0, "d": 25.0, "a": 20.0},
            "market_over25": 58.0, "hist_over25": 45.0, "hist_over15": 80.0, "fh_over05": 0.6, "fh_over15": 0.2, "sh_over05": 0.7, "sh_over15": 0.3, "halves_n": 100}
    base.update(kw)
    return base


def test_to_turkey_rolls_over_midnight():
    assert sc.to_turkey("2026-09-14", "20:00") == ("2026-09-14", "22:00")
    assert sc.to_turkey("2026-09-14", "23:00") == ("2026-09-15", "01:00")
    assert sc.to_turkey("2026-09-14", "") == ("2026-09-14", "")


def test_score_match_home_win_three_goals():
    s = sc.score_match(_row(), {"hs": 2, "as": 1, "ht_h": 1, "ht_a": 0, "source": "test"})
    assert s["result"] == "h" and s["total"] == 3 and s["ht_score"] == "1-0"
    assert s["ms"]["market"]["pick"] == "h" and s["ms"]["market"]["ok"] and s["ms"]["hist"]["ok"]
    assert s["ms"]["closer"] == "market"                      # 60 vs 55 on the realised outcome
    assert s["o25"]["market"]["ok"] and not s["o25"]["hist"]["ok"]   # market said over (58), history under (45)
    assert s["o25"]["closer"] == "market"
    assert s["o15"]["market"] is None and s["o15"]["hist"]["ok"]
    # first half 1 goal: history said "at least 1" (60%) -> right; "at least 2" only 20% -> pick "no" -> also right
    assert s["fh05"]["hist"]["ok"] and s["fh15"]["hist"]["pick"] == "no" and s["fh15"]["hist"]["ok"]
    assert s["sh05"]["hist"]["ok"] and not s["sh15"]["hist"]["ok"]    # second half 2 goals: "at least 2" was only 30% -> pick "no" -> wrong
    s2 = sc.score_match(_row(), {"hs": 3, "as": 2, "ht_h": 2, "ht_a": 1})
    assert not s2["fh15"]["hist"]["ok"] and not s2["sh15"]["hist"]["ok"]   # 3 first-half goals, 2 second-half: "no" picks were wrong
    assert abs(s["ms"]["market"]["brier"] - ((0.4) ** 2 + 0.22 ** 2 + 0.18 ** 2)) < 1e-9


def test_score_match_without_halftime_has_no_half_markets():
    s = sc.score_match(_row(), {"hs": 0, "as": 0, "ht_h": None, "ht_a": None})
    assert s["result"] == "d" and "fh05" not in s and s["ht_score"] == ""
    assert s["ms"]["closer"] == "hist"                        # draw: history 25 vs market 22
    assert s["o25"]["hist"]["ok"] and not s["o25"]["market"]["ok"]


def test_build_scorecard_aggregates_and_filters():
    rows = [_row(), _row(id="m2", league="SP1", home="Betis", away="Sevilla", market_over25=None),
            _row(id="m3", league="SP1", home="Getafe", away="Cadiz", date="2026-09-13")]
    results = {"m1": {"hs": 2, "as": 1, "ht_h": 1, "ht_a": 0}, "m2": {"hs": 0, "as": 0, "ht_h": None, "ht_a": None}}
    card = sc.build_scorecard(rows, results, "2026-09-14", "2026-09-14", names={"E0": "Premier"})
    assert card["n_matches"] == 2 and card["n_finished"] == 2 and card["n_pending"] == 0
    ms = next(b for b in card["markets"] if b["key"] == "ms")
    assert ms["n"] == 2 and ms["market"]["ok"] == 1 and ms["hist"]["ok"] == 1
    assert ms["closer"] == {"market": 1, "hist": 1, "equal": 0}
    o25 = next(b for b in card["markets"] if b["key"] == "o25")
    assert o25["market"]["n"] == 1 and o25["hist"]["n"] == 2 and o25["actual_pct"] == 50.0
    fh = next(b for b in card["markets"] if b["key"] == "fh05")
    assert fh["n"] == 1 and fh["market"] is None
    assert [l["league"] for l in card["by_league"]] == ["E0", "SP1"] and card["by_league"][0]["league_name"] == "Premier"
    only = sc.build_scorecard(rows, results, "2026-09-14", "2026-09-14", leagues={"SP1"})
    assert only["n_matches"] == 1 and only["matches"][0]["home"] == "Betis"
    pending = sc.build_scorecard(rows, {}, "2026-09-13", "2026-09-14")
    assert pending["n_finished"] == 0 and pending["n_pending"] == 3


def test_db_result_lookup_and_cache(tmp_path):
    from src.config import load_settings
    settings = load_settings().with_overrides(**{"data.results_dir": str(tmp_path)})
    hist = pd.DataFrame([{"league": "E0", "date": pd.Timestamp("2026-09-14"), "home_team": "Arsenal", "away_team": "Everton",
                          "fthg": 3, "ftag": 1, "ftr": "H", "hthg": 2, "htag": 0}])
    rows = [_row(), _row(id="m2", home="Chelsea", away="Fulham")]
    res = sc.realised_results(settings, rows, hist, use_live=False)
    assert res == {"m1": {"hs": 3, "as": 1, "ht_h": 2, "ht_a": 0, "source": "football-data"}}
    sc.save_cache(settings, {"m2": {"hs": 1, "as": 1, "ht_h": None, "ht_a": None, "source": "espn"}})
    res = sc.realised_results(settings, rows, hist, use_live=False)
    assert res["m2"]["hs"] == 1 and res["m2"]["source"] == "espn"
