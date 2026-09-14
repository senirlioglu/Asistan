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
    assert m["odds"]["h"] == 1.72 and m["edge"]["h"] == 4.7 and m["ci"]["h"] == [56.4, 66.9]
    assert m["market_over25"] is None  # NaN -> null
    assert m["tolerance"]["probs"]["0.02"] == 120
    assert client.get("/api/day/2000-01-01").status_code == 404


def test_analogues(client):
    a = client.get("/api/analogues/2026-09-14/abc?k=25").json()
    assert len(a["rows"]) == 1 and a["rows"][0]["home"] == "Sevilla" and a["rows"][0]["over25"] is False
    assert a["share"]["h"] == 100.0
    # Sevilla–Alaves involves neither Arsenal nor Everton -> not flagged
    assert a["rows"][0]["same_team"] is False and a["same_team_count"] == 0 and a["teams"] == ["Arsenal", "Everton"]
    assert client.get("/api/analogues/2026-09-14/nope").json()["rows"] == []


def test_refresh_requires_key_when_set(client, monkeypatch):
    monkeypatch.setenv("FO_ADMIN_KEY", "s3cret")
    assert client.post("/api/refresh").status_code == 401
    monkeypatch.setattr(web, "start_background", lambda *a, **k: object())
    assert client.post("/api/refresh", headers={"X-Admin-Key": "s3cret"}).json()["started"] is True
