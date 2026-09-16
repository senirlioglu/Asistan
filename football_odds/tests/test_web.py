import json

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from src.web import api as web


@pytest.fixture()
def client(tmp_path, monkeypatch):
    """API pointed at a temporary results directory with one prediction file."""
    results = tmp_path / "results"
    (results / "analogues").mkdir(parents=True)
    (results / "backtest").mkdir()
    monkeypatch.setattr(web, "RESULTS", results)
    monkeypatch.setattr(web.settings, "raw", web.settings.with_overrides(**{"data.results_dir": str(results)}).raw)
    row = {
        "date": "2026-09-14", "time": "20:00", "league": "E0", "home": "Arsenal", "away": "Everton", "match_id": "abc",
        "odds_h": 1.72, "odds_d": 3.8, "odds_a": 4.7, "market_h": 55.0, "market_d": 24.9, "market_a": 20.1, "n": 500, "n_eff": 500,
        "hist_h": 61.8, "hist_d": 23.2, "hist_a": 15.0, "adj_h": 59.7, "adj_d": 23.8, "adj_a": 16.5,
        "edge_h": 4.7, "edge_d": -1.1, "edge_a": -3.6, "over25": 54.7, "under25": 45.3, "btts": 51.2, "avg_goals": 2.71,
        "confidence": "HIGH", "signal": "MODERATE HISTORICAL DEVIATION", "signal_outcome": "home", "avg_similarity": 96.8,
        "median_similarity": 97.0, "min_similarity": 94.0, "ci_h_lo": 56.4, "ci_h_hi": 66.9, "ci_d_lo": 19.5, "ci_d_hi": 27.1,
        "ci_a_lo": 12.1, "ci_a_hi": 18.4, "fair_h": 1.67, "fair_d": 4.2, "fair_a": 6.06, "market_over25": float("nan"),
    }
    pd.DataFrame([row]).to_csv(results / "2026-09-14_predictions.csv", index=False)
    (results / "2026-09-14_details.json").write_text(json.dumps({"matches": {"abc": {
        "scorelines": {"1-0": 0.12, "other": 0.5}, "goals_dist": {"0": 0.1, "1": 0.2}, "scopes": {}, "tolerance": {"probs": {"0.02": 120}}}}}))
    pd.DataFrame([{
        "fixture_id": "abc", "date": "2019-03-02", "league": "SP1", "home_team": "Sevilla", "away_team": "Alaves", "cons_h": 1.7,
        "cons_d": 3.8, "cons_a": 4.8, "similarity": 99.1, "ftr": "H", "score": "2-0", "ou25": "Under", "btts": "No", "distance": 0.01, "years_old": 7.5,
    }]).to_parquet(results / "analogues" / "2026-09-14_analogues.parquet", index=False)
    (results / "backtest" / "selected_params.json").write_text(json.dumps({"backtest_ok": False, "brier_market": 0.5899, "brier_adj": 0.5897,
                                                                            "test_seasons": ["2122"], "n_test_matches": 10}))
    web._load_analogues.cache_clear()
    return TestClient(web.app)


def test_health_and_index(client):
    assert client.get("/api/health").json() == {"ok": True}
    r = client.get("/")
    assert r.status_code == 200 and "Oran Karşılaştırma" in r.text
    assert client.get("/static/app.js").status_code == 200


def test_meta_lists_dates_and_backtest(client):
    m = client.get("/api/meta").json()
    assert m["dates"] == ["2026-09-14"]
    assert m["backtest"]["backtest_ok"] is False and m["backtest"]["brier_market"] == 0.5899
    assert m["status"]["state"] in ("never", "ok", "error", "running")


def test_day_payload_shape_and_nan_to_null(client):
    d = client.get("/api/day/2026-09-14").json()
    assert len(d["matches"]) == 1
    m = d["matches"][0]
    assert m["home"] == "Arsenal" and m["league_name"].startswith("İngiltere")
    assert m["stamp"] == "2026-09-14"  # which prediction/analogue file the row came from
    # Football-Data's 20:00 UK (BST in September) is 22:00 in Turkey; the UK originals are kept
    assert m["time"] == "22:00" and m["date"] == "2026-09-14" and m["time_uk"] == "20:00"
    assert m["odds"]["h"] == 1.72 and m["edge"]["h"] == 4.7 and m["ci"]["h"] == [56.4, 66.9]
    assert m["market_over25"] is None  # NaN -> null
    assert m["tolerance"]["probs"]["0.02"] == 120
    assert client.get("/api/day/2000-01-01").status_code == 404


def test_uk_to_turkey_conversion_rolls_the_date():
    assert web._to_turkey("2026-09-14", "20:00") == ("2026-09-14", "22:00")   # BST: +2h
    assert web._to_turkey("2026-12-14", "20:00") == ("2026-12-14", "23:00")   # GMT: +3h
    assert web._to_turkey("2026-12-14", "22:30") == ("2026-12-15", "01:30")   # rolls into the next Turkish day
    assert web._to_turkey("2026-09-14", "") == ("2026-09-14", "")


def test_analogues(client):
    a = client.get("/api/analogues/2026-09-14/abc?k=25").json()
    assert len(a["rows"]) == 1 and a["rows"][0]["home"] == "Sevilla" and a["rows"][0]["over25"] is False
    assert a["share"]["h"] == 100.0
    # Sevilla–Alaves involves neither Arsenal nor Everton -> not flagged
    assert a["rows"][0]["same_team"] is False and a["same_team_count"] == 0 and a["teams"] == ["Arsenal", "Everton"]
    assert client.get("/api/analogues/2026-09-14/nope").json()["rows"] == []


def test_teams_endpoint_head_to_head_and_similar_pricing(client, tmp_path, monkeypatch):
    processed = tmp_path / "processed"
    processed.mkdir()
    rows = [
        # Arsenal home vs Everton, Arsenal priced 56% -> similar to today's 55%, Arsenal won
        dict(date="2024-03-01", league="E0", season="2324", home_team="Arsenal", away_team="Everton", cons_h=1.7, cons_d=3.8, cons_a=4.8,
             p_home=0.56, p_draw=0.24, p_away=0.20, ftr="H", fthg=2, ftag=0, result_code=0, total_goals=2),
        # Everton home vs Arsenal (h2h, reversed venue), Arsenal priced 40% -> not similar; draw
        dict(date="2023-10-01", league="E0", season="2324", home_team="Everton", away_team="Arsenal", cons_h=2.5, cons_d=3.3, cons_a=2.7,
             p_home=0.38, p_draw=0.28, p_away=0.34, ftr="D", fthg=1, ftag=1, result_code=1, total_goals=2),
        # Arsenal away at Chelsea priced 53% -> similar, Arsenal lost
        dict(date="2025-01-10", league="E0", season="2425", home_team="Chelsea", away_team="Arsenal", cons_h=3.0, cons_d=3.5, cons_a=1.85,
             p_home=0.27, p_draw=0.20, p_away=0.53, ftr="H", fthg=1, ftag=0, result_code=0, total_goals=1),
        # a match AFTER the analysed date must be ignored
        dict(date="2026-10-01", league="E0", season="2627", home_team="Arsenal", away_team="Everton", cons_h=1.7, cons_d=3.8, cons_a=4.8,
             p_home=0.55, p_draw=0.25, p_away=0.20, ftr="H", fthg=3, ftag=0, result_code=0, total_goals=3),
    ]
    pd.DataFrame(rows).to_parquet(processed / "matches.parquet", index=False)
    monkeypatch.setattr(web.settings, "raw", web.settings.with_overrides(**{"data.processed_dir": str(processed)}).raw)
    web._history_cached.cache_clear()
    d = client.get("/api/teams/2026-09-14/abc").json()
    assert d["h2h"]["n"] == 2 and d["h2h"]["home_wins"] == 1 and d["h2h"]["draws"] == 1
    assert d["h2h"]["rows"][0]["date"] == "2024-03-01"  # newest first, future match excluded
    home = d["home"]
    assert home["team"] == "Arsenal" and home["n_total"] == 3 and home["n_similar"] == 2
    assert home["win_pct"] == 50.0 and home["rows"][0]["outcome"] == "M" and home["rows"][0]["venue"] == "dep"
    away = d["away"]
    # Everton was priced 20 % away in the 2024 match (today 20.1 %) -> one similar match, lost it
    assert away["team"] == "Everton" and away["n_total"] == 2 and away["n_similar"] == 1
    assert away["rows"][0]["outcome"] == "M" and away["win_pct"] == 0.0
    assert client.get("/api/teams/2026-09-14/nope").status_code == 404


def test_refresh_requires_key_when_set(client, monkeypatch):
    monkeypatch.setenv("FO_ADMIN_KEY", "s3cret")
    assert client.post("/api/refresh").status_code == 401
    monkeypatch.setattr(web, "start_background", lambda *a, **k: object())
    assert client.post("/api/refresh", headers={"X-Admin-Key": "s3cret"}).json()["started"] is True


def test_match_detail_carries_the_nesine_side(client, monkeypatch):
    """The Oyun tab opens a coupon row by match id and expects the analysis plus the nesine odds/notes."""
    from src.nesine import bulletin, watcher

    sample = {"code": 4242, "date": "2026-09-14", "time": "22:00", "home": "Arsenal FC", "away": "Everton",
              "league": "İngiltere Premier Lig", "league_code": 1, "ms": {"1": 1.72, "X": 3.8, "2": 4.7},
              "iyms": {}, "iy": {}, "iy05": {"alt": 1.64, "ust": 2.2}, "h1_15": {}, "h2_15": {}, "o25": {"alt": 1.9, "ust": 1.8},
              "o35": {}, "o45": {}, "gol_araligi": {}, "iy_kg": {}, "y2_kg": {}, "iy_y2_kg": {}, "iy_sonucu_kg": {},
              "ilk_gol": {}, "iki_yari_15_ust": {}, "iy_skor": {}, "skor": {}, "korner": {"9,5 Korner Alt/Üst · Üst": 1.9}}
    monkeypatch.setattr(bulletin, "load_matches", lambda *a, **k: ([sample], {"fetched_at": "2026-09-14T18:00:00+00:00"}))
    monkeypatch.setattr(watcher, "load_store", lambda *a, **k: {"matches": {"4242": {"odds": {"ms.1": [["t0", 1.80], ["t1", 1.72]]}}}})

    d = client.get("/api/match/abc").json()
    assert d["match"]["home"] == "Arsenal" and d["match"]["edge"]["h"] == 4.7      # our analysis rides along
    n = d["nesine"]
    assert n["code"] == 4242 and n["ms"]["1"] == 1.72 and n["name_score"] >= 0.6
    assert "korner" not in n and n["korner_n"] == 1                                 # the corner list stays server-side
    assert n["moves"]["ms.1"] == {"open": 1.80, "now": 1.72, "prev": 1.80, "dir": -1, "changed_at": "t1", "n": 2}
    # note 5 reads exactly 1.64 in the İY 0,5 market: it fires, and says which odds it read
    n5 = next(h for h in n["hits"] if h["id"] == "n5")
    assert n5["evidence"]["İY 0,5 alt"] == 1.64 and n5["paths"]["İY 0,5 alt"] == "iy05.alt"

    assert client.get("/api/match/yok-boyle-bir-mac").status_code == 404
    # a bulletin without this match: the sheet says so instead of guessing
    monkeypatch.setattr(bulletin, "load_matches", lambda *a, **k: ([{**sample, "home": "Chelsea", "away": "Fulham"}], {}))
    assert client.get("/api/match/abc").json()["nesine"] is None
