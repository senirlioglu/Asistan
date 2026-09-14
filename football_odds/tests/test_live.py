from src.web import live


def test_norm_and_aliases():
    assert live.norm("Inter") == "internazionale"
    assert live.norm("Sp Braga") == "braga"
    assert live.norm("Ath Madrid") == "atletico madrid"
    assert live.norm("Gaziantep FK") == "gaziantep"          # stop token removed
    assert live.norm("Fenerbahçe") == "fenerbahce"           # accent stripped


def test_name_score_handles_common_spellings():
    assert live.name_score("Inter", "Internazionale") == 1.0
    assert live.name_score("Newcastle", "Newcastle United") == 1.0
    assert live.name_score("Como", "Como") == 1.0
    assert live.name_score("Parma", "Parma") == 1.0
    assert live.name_score("Villarreal", "Real Betis") < 0.5


def test_match_event_picks_the_right_fixture():
    events = [
        {"home": "Como", "away": "Parma", "home_short": "Como", "away_short": "Parma", "state": "in"},
        {"home": "Torino", "away": "AS Roma", "home_short": "Torino", "away_short": "Roma", "state": "in"},
        {"home": "Internazionale", "away": "Udinese", "home_short": "Inter", "away_short": "Udinese", "state": "pre"},
    ]
    assert live.match_event(events, "Inter", "Udinese")["home"] == "Internazionale"
    assert live.match_event(events, "Torino", "Roma")["away"] == "AS Roma"
    assert live.match_event(events, "Lecce", "Monza") is None


def test_status_label():
    assert live.status_label_tr({"state": "in", "detail": "54'", "clock": "54'"}) == "54'"
    assert live.status_label_tr({"state": "in", "detail": "HT", "clock": "45'"}) == "İY"
    assert live.status_label_tr({"state": "post", "detail": "FT"}) == "MS"
    assert live.status_label_tr({"state": "pre", "detail": "Scheduled"}) == ""


def test_parse_event_extracts_scores_and_halftime():
    raw = {"date": "2026-09-14T15:30Z", "status": {"type": {"state": "in", "shortDetail": "54'"}, "displayClock": "54'", "period": 2},
           "competitions": [{"competitors": [
               {"homeAway": "home", "score": "1", "team": {"displayName": "Como", "shortDisplayName": "Como"}, "linescores": [{"value": 1.0}, {"value": 0.0}]},
               {"homeAway": "away", "score": "0", "team": {"displayName": "Parma", "shortDisplayName": "Parma"}, "linescores": [{"value": 0.0}, {"value": 0.0}]},
           ]}]}
    ev = live._parse_event(raw)
    assert ev["home"] == "Como" and ev["home_score"] == 1 and ev["away_score"] == 0
    assert ev["ht_home"] == 1 and ev["ht_away"] == 0 and ev["state"] == "in" and ev["clock"] == "54'"
    assert live._parse_event({}) is None
