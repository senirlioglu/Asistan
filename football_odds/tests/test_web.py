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


@pytest.fixture()
def research_client(client, tmp_path, monkeypatch):
    """The API with a small state table of its own, so the twin endpoint has something to search."""
    import numpy as np

    from src.patterns import service, state

    processed = tmp_path / "processed"
    processed.mkdir()
    monkeypatch.setattr(web.settings, "raw", web.settings.with_overrides(
        **{"data.processed_dir": str(processed), "data.results_dir": str(web.RESULTS)}).raw)
    rows = []
    for i in range(60):
        rows.append({"date": f"2026-0{1 + i // 30}-{1 + i % 28:02d}", "league": "E0", "season": "2526",
                     "home_team": f"T{i % 6}", "away_team": f"T{(i + 1) % 6}", "fthg": i % 3, "ftag": (i + 1) % 2,
                     "p_home": 0.45 + (i % 5) / 100, "p_draw": 0.25, "p_away": 0.30 - (i % 5) / 100,
                     "htr": "H" if i % 2 else "D", "hthg": 1, "htag": 0})
    df = pd.DataFrame(rows)
    df["date"] = pd.to_datetime(df["date"])
    df["match_id"] = [f"s{i}" for i in range(len(df))]
    df["ftr"] = np.where(df["fthg"] > df["ftag"], "H", np.where(df["fthg"] == df["ftag"], "D", "A"))
    df["total_goals"] = df["fthg"] + df["ftag"]
    state.build(web.settings, df)
    service._cached.cache_clear()
    service._POOL_STATS.clear()
    return client


def test_twins_endpoint_answers_with_its_own_quality(research_client):
    d = research_client.get("/api/twins/s59?k=10").json()
    assert d["match"]["id"] == "s59" and d["k"] == 10
    assert len(d["twins"]) and all(t["date"] < d["match"]["date"] for t in d["twins"])   # only earlier matches
    g = d["diagnostics"]
    assert g["k"] == 10 and g["best"] >= g["median"] >= g["worst"]      # how far the last twin is, always reported
    assert set(g["categories"]) == set(d["weights"])
    # what the twins did comes with what the market said about those same twins
    assert d["outcomes"]["win"]["n"] == 10 and "market" in d["outcomes"]["win"]
    assert research_client.get("/api/twins/yok").status_code == 404
    assert research_client.get("/api/twins/s59?k=1").status_code == 422        # k is bounded


def test_research_endpoint_reports_the_pool_and_the_missing_pieces(research_client):
    d = research_client.get("/api/research").json()
    assert d["state"]["matches"] == 60 and d["state"]["from"] == "2026-01-01"
    # the offline artefacts are absent in this temporary results dir, and that is said rather than faked
    assert d["notes"] is None and d["models"] is None and d["discovery"] is None


def test_the_match_carries_the_state_table_reading_the_engines_run_on(research_client):
    """Strength, venue form, goals and rest were computed for every match and then dropped on the
    way to the page, which made every engine below look like it ran on the price alone."""
    q = research_client.get("/api/twins/s59?k=10").json()["match"]
    for key in ("h_tsi_pct", "a_tsi_pct", "gap", "h_form_venue", "a_form_venue",
                "h_gf5", "h_ga5", "a_gf5", "a_ga5", "h_rest_days", "a_rest_days"):
        assert key in q, key
    assert q["h_tsi_pct"] is not None and q["h_form_venue"] != ""


def test_twins_report_which_weights_and_decay_they_ran_with(research_client):
    d = research_client.get("/api/twins/s59?k=10").json()
    assert d["config"]["source"] in ("varsayılan", "ayarlanmış")
    assert set(d["config"]["weights"]) == set(d["weights"])
    assert "half_life" in d["diagnostics"] and "n_eff" in d["diagnostics"]
    assert d["outcomes"]["win"]["n_eff"] > 0


def test_pattern_endpoint_answers_at_three_levels_with_both_match_counts(research_client):
    d = research_client.get("/api/patterns/s59").json()
    assert d["match"]["id"] == "s59" and d["match"]["form"]
    assert set(d["levels"]) <= {"all", "same_team", "similar"} and "all" in d["levels"]
    assert d["n_exact"] >= 0 and d["approx"] == 0
    win = d["levels"]["all"]["outcomes"]["win"]
    assert "actual" in win and "diff_ci" in win            # never a hit rate on its own
    loose = research_client.get("/api/patterns/s59?approx=2").json()
    assert loose["levels"]["all"]["n"] >= d["levels"]["all"]["n"]   # slack can only widen the net
    assert research_client.get("/api/patterns/yok").status_code == 404
    assert research_client.get("/api/patterns/s59?approx=9").status_code == 422


def test_movement_endpoint_answers_in_probability_and_admits_what_it_lacks(client, tmp_path, monkeypatch):
    """The page must never receive a verdict without the data quality that produced it."""
    import datetime as dt
    import json as _json

    from src.nesine import archive, movement as mv

    monkeypatch.setattr(web.settings, "raw", web.settings.with_overrides(
        **{"data.results_dir": str(tmp_path)}).raw)
    mv._CACHE.clear()
    ko = dt.datetime.now(dt.timezone.utc) + dt.timedelta(minutes=30)   # every snapshot below is in the past
    day = ko.date()
    local = ko.astimezone(dt.timezone(dt.timedelta(hours=3)))
    meta = {"code": 91, "date": local.strftime("%Y-%m-%d"), "time": local.strftime("%H:%M"),
            "home": "Ev", "away": "Dep", "league": "L"}
    archive.archive_dir(web.settings).mkdir(parents=True, exist_ok=True)
    with archive.day_path(web.settings, day).open("w", encoding="utf-8") as fh:
        for mins, h, a in ((240, 2.05, 4.00), (180, 1.96, 4.30), (60, 1.81, 4.90)):
            ts = (ko - dt.timedelta(minutes=mins)).isoformat(timespec="seconds")
            fh.write(_json.dumps({"ts": ts, "k": "run", "n": 1, "ch": 3}) + "\n")
            for path, o in (("ms.1", h), ("ms.X", 3.4), ("ms.2", a)):
                fh.write(_json.dumps({"ts": ts, "c": 91, "p": path, "o": o, "m": mins}) + "\n")
    archive.meta_path(web.settings, day).write_text(_json.dumps({"91": meta}), encoding="utf-8")

    d = client.get("/api/hareket/91").json()
    s = d["selections"]["ms.1"]
    assert d["started"] is False and s["closing"] is None          # not a closing price until kick-off
    assert s["movement"]["type"] == "STEAM" and s["movement"]["total_pp"] > 0
    assert s["open"]["p"] < s["current"]["p"]                      # probability, not raw odds
    assert s["quality"]["snapshots"] == 3 and s["quality"]["runs"] >= 3
    assert "config" in d and d["config"]["movement_min_pp"] > 0    # thresholds are data, not code
    assert client.get("/api/hareket/91?days=99").status_code == 422


def test_combined_endpoint_cascades_and_never_widens(research_client):
    d = research_client.get("/api/kombine/s59?length=3&approx=1").json()
    assert d["match"]["team"] and d["match"]["opponent"] and d["length"] == 3
    ns = [r["n"] for r in d["rows"]]
    assert ns == sorted(ns, reverse=True)                      # each condition can only remove matches
    assert d["rows"][0]["n_lost"] is None and all("step" in r for r in d["rows"])
    win = d["rows"][0]["outcomes"]["win"]
    assert "actual" in win and "diff_ci" in win                # never a hit rate on its own
    tight = research_client.get("/api/kombine/s59?length=5&approx=0").json()
    assert tight["rows"][-1]["n"] <= d["rows"][-1]["n"]        # stricter cannot find more
    assert research_client.get("/api/kombine/yok").status_code == 404
    assert research_client.get("/api/kombine/s59?length=9").status_code == 422


def test_the_pattern_explorer_answers_a_typed_query_against_the_price(research_client):
    """The research tab has always claimed an idea can be tested in seconds; this is the control that
    does it, and it must come back with the interval, not only the hit rate."""
    d = research_client.get("/api/desen?form=WWW&side=home").json()
    assert d["pool"] > 0 and "label" in d and len(d["span"]) == 2
    win = d["outcomes"]["win"]
    assert "actual" in win and "diff_ci" in win
    assert d["n_exact"] <= d["pool"]

    loose = research_client.get("/api/desen?form=WWW&side=home&approx=2").json()
    assert loose["n"] >= d["n"]                       # slack can only widen the net
    banded = research_client.get("/api/desen?form=WWW&side=home&tsi_lo=90&tsi_hi=100").json()
    assert banded["n"] <= d["n"]                      # a band can only narrow it
    assert "TSI%" in banded["label"]

    assert research_client.get("/api/desen?form=WWW&approx=9").status_code == 422
    assert research_client.get("/api/desen?form=WWW&p_lo=2").status_code == 422


def test_fixture_context_lists_past_meetings_and_carries_its_own_verdict(research_client):
    """The "same fixture sequence repeated" graphics are checkable here — and the check has to come
    with what the whole database says about the claim, which is that context shrinks the sample
    rather than sharpening the effect."""
    d = research_client.get("/api/fikstur/s59").json()
    q = d["match"]
    assert q["home"] and q["away"] and "h_prev_opp" in q and "h_next_opp" in q
    assert d["meetings"] >= 0 and isinstance(d["shown"], list)
    for r in d["shown"]:
        assert r["date"] < q["date"]                       # only earlier meetings
        assert 0 <= r["n_same"] <= 4
    v = d["verdict"]
    assert v["none"]["n"] > v["prev_only"]["n"] > v["full"]["n"]     # context only ever narrows
    assert v["full"]["ci"][0] < 0 < v["full"]["ci"][1]               # and the full context says nothing
    assert research_client.get("/api/fikstur/yok").status_code == 404


def test_the_cycle_endpoint_takes_a_team_and_nothing_else(research_client):
    """Spec 4: no season picker, no window picker, no search-type picker — the reader picks a club."""
    d = research_client.get("/api/dongu?team=T0").json()
    assert d["team"] == "T0" and d["windows"] == [2, 3, 4]
    assert "searched" in d and isinstance(d["cycles"], list)
    for c in d["cycles"]:
        assert c["kind"] in ("EXACT_SAME", "EXACT_REVERSE", "SHIFTED", "STRENGTH")
        assert c["n_compared"] >= 2 and "positional" in c and "wing" in c
        assert c["past"]["date"] < c["now"]["date"]
    unknown = research_client.get("/api/dongu?team=Yok").json()
    assert unknown["cycles"] == [] and unknown.get("note")
    assert research_client.get("/api/dongu?team=T").status_code == 422


def test_the_scan_corrects_across_the_whole_family_before_showing_anything(research_client):
    """Eight engines times nine outcomes is a search, and a screen that shows its winners shows
    noise forever. The correction is the product, so the denominator has to survive to the payload."""
    d = research_client.get("/api/tarama/s59").json()
    assert d["match"]["id"] == "s59"
    assert d["scanned"] >= d["after_correction"]                  # the funnel only ever narrows
    assert d["after_correction"] == len(d["findings"])
    assert d["alpha"] == 0.05 and d["min_n"] >= 100
    for f in d["findings"]:
        assert f["q"] <= d["alpha"] and abs(f["edge"]) >= d["min_edge"]
        assert f["n"] >= d["min_n"] and f["evidence"] in ("KEŞİF", "İLERİ TESTTE")   # never "doğrulandı" from one pool
        assert f["ci"][0] is not None
    # context never enters the family: a similarity and a shape are not claims that took a test
    for c in d["context"]:
        assert c["source"] in ("sequence", "movement", "note") and "q" not in c
    assert research_client.get("/api/tarama/yok").status_code == 404


# --------------------------------------------------------------------------- Pattern Lab (/api/lab/*)

def test_lab_targets_are_only_what_the_backend_measures(client):
    d = client.get("/api/lab/hedefler").json()
    keys = {t["key"] for g in d["groups"] for t in g["targets"]}
    assert {"ft_1", "ht_X", "htft_2/1", "over25", "btts"} <= keys
    from src.patterns import engine
    assert keys <= set(engine.OUTCOMES)                     # every target is a measurable outcome
    two_one = next(t for g in d["groups"] for t in g["targets"] if t["key"] == "htft_2/1")
    assert "deplasman önde" in two_one["explain"] and "ev sahibi kazanır" in two_one["explain"]


def test_lab_target_analysis_keeps_market_and_similarity_apart(research_client, monkeypatch):
    """Spec 7 and 8: every layer carries N / actual / expectation / difference / CI / evidence; the
    market is the reference or the payload says there is none; similarity is never the probability."""
    monkeypatch.setattr(web, "_nesine_brief", lambda *a, **k: None)
    d = research_client.get("/api/lab/hedef/s59?target=ft_1").json()
    assert d["target"]["key"] == "ft_1" and d["match"]["id"] == "s59"
    assert d["market"]["source"] == "football-data" and d["market"]["p"] is not None
    for l in d["layers"]:
        assert {"n", "actual", "expected", "edge", "ci", "evidence_tr"} <= set(l)
        assert l["evidence_tr"] in ("YETERSİZ VERİ", "KEŞİF", "DOĞRULANDI", "İLERİ TESTTE", "FARK YOK")
    assert d["similarity"] is None or "median" in d["similarity"]     # a different field, a different thing
    assert d["evidence"]["label"] in ("YETERSİZ VERİ", "KEŞİF", "DOĞRULANDI", "İLERİ TESTTE", "FARK YOK")
    assert isinstance(d["reasons"]["pro"], list) and isinstance(d["reasons"]["con"], list)
    # a half-time target has no Football-Data price: no number is invented
    h = research_client.get("/api/lab/hedef/s59?target=htft_2/1").json()
    assert h["market"]["p"] is None and "mevcut değil" in h["market"]["note"]
    assert all(l["reference"] in (None, "matched") for l in h["layers"] if l["n"])
    assert research_client.get("/api/lab/hedef/s59?target=nope").status_code == 422
    assert research_client.get("/api/lab/hedef/yok?target=ft_1").status_code == 404


def test_lab_own_pattern_adds_one_condition_at_a_time(research_client):
    """Spec 12: each condition is a row, N can only fall, and the reader sees which one moved the number."""
    d = research_client.get("/api/lab/kendi?side=home&form=W&strength=strong&opp_strength=weak&goals=gf5:0-30&role=favorite").json()
    ns = [r["n"] for r in d["rows"]]
    assert len(d["rows"]) == 5 and ns == sorted(ns, reverse=True)
    assert d["steps"][0].startswith("Ev sahibi formu W") and "+ favori" in d["steps"]
    assert "win" in d["rows"][0]["outcomes"] and "diff_ci" in d["rows"][0]["outcomes"]["win"]
    extra = research_client.get("/api/lab/kendi?side=away&form=L&outcome=htft_2/1").json()
    assert "htft_2/1" in extra["outcomes"]
    last = d["rows"][-1]
    assert isinstance(last.get("sample"), list) and len(last["sample"]) <= 25      # the matches behind the last row
    if last["sample"]:
        assert {"date", "home_team", "away_team", "ftr"} <= set(last["sample"][0])
    assert len(research_client.get("/api/lab/kendi?side=home&form=W&sample=3").json()["rows"][-1]["sample"]) <= 3
    assert research_client.get("/api/lab/kendi?strength=bad").status_code == 422


def test_lab_team_picker_and_match_picker(research_client):
    t = research_client.get("/api/lab/takimlar?q=t1").json()["teams"]
    assert t and all("t1" in x["team"].lower() for x in t) and {"league", "season", "n"} <= set(t[0])
    m = research_client.get("/api/lab/maclar?from=2026-09-14&to=2026-09-14").json()
    assert m["matches"] and m["matches"][0]["home"] == "Arsenal" and m["matches"][0]["ready"] is False   # not in the state table


def test_lab_day_scan_runs_in_the_background_and_ranks_without_a_bet_score(research_client, monkeypatch, tmp_path):
    """Spec 10: the scan is started, polled, and its ordering is explained as research relevance."""
    import time

    from src.patterns import target as tg

    monkeypatch.setattr(web, "_nesine_brief", lambda *a, **k: None)
    # one match of the state table doubles as an analysed fixture of the day
    monkeypatch.setattr(web, "lab_matches", lambda *a, **k: {"matches": [
        {"id": "s59", "date": "2026-02-28", "time": "20:00", "league": "E0", "league_name": "x", "home": "T5", "away": "T0", "ready": True}]})
    tg._JOBS.clear()
    r = research_client.post("/api/lab/tara?date=2026-02-28&target=ft_1").json()
    assert r["state"] in ("running", "done") and r["total"] == 1
    for _ in range(100):
        d = research_client.get("/api/lab/tara?date=2026-02-28&target=ft_1").json()
        if d["state"] == "done":
            break
        time.sleep(0.2)
    assert d["state"] == "done" and len(d["rows"]) == 1
    row = d["rows"][0]
    assert {"market", "estimate", "difference", "similarity", "evidence", "relevance"} <= set(row)
    assert "bahis" in d["note"] and "değildir" in d["note"]           # the ordering is not a bet score
    assert research_client.get("/api/lab/tara?date=2026-02-28&target=ft_X").json()["state"] == "none"


def test_the_sassuolo_cycle_is_found_and_measured_through_the_api(client, tmp_path, monkeypatch):
    """Spec 17 and 19: pick the team, nothing else; the reverse cycle comes back at ±2 and 100 %, and
    the measurement of that shape over the whole database comes back with its three layers."""
    import numpy as np

    from src.patterns import cycles, service, state

    processed = tmp_path / "processed"
    processed.mkdir()
    monkeypatch.setattr(web.settings, "raw", web.settings.with_overrides(
        **{"data.processed_dir": str(processed), "data.results_dir": str(web.RESULTS)}).raw)
    rows = []
    seasons = {"2324": ("2024-01-01", ["Juventus", "Monza", "Bologna", "Torino", "Atalanta"]),
               "2425": ("2025-01-01", ["Inter", "Milan", "Bologna", "Roma", "Lazio"]),
               "2627": ("2026-08-01", ["Atalanta", "Torino", "Bologna", "Juventus", "Monza"])}
    for season, (start, opps) in seasons.items():
        for i, opp in enumerate(opps):
            rows.append({"match_id": f"S-{season}-{i}", "date": pd.Timestamp(start) + pd.Timedelta(days=7 * i),
                         "league": "I1", "season": season, "home_team": "Sassuolo", "away_team": opp,
                         "fthg": 1 + (i % 2), "ftag": 1, "p_home": 0.45, "p_draw": 0.27, "p_away": 0.28,
                         "htr": "A" if i % 2 else "D", "hthg": 0, "htag": 1 if i % 2 else 0})
    df = pd.DataFrame(rows)
    df["ftr"] = np.where(df["fthg"] > df["ftag"], "H", np.where(df["fthg"] == df["ftag"], "D", "A"))
    df["total_goals"] = df["fthg"] + df["ftag"]
    state.build(web.settings, df)
    service._cached.cache_clear()
    cycles._MEM.update(key=None, pairs=None)

    d = client.get("/api/dongu?team=Sassuolo").json()                  # the club, nothing else
    best = d["cycles"][0]
    assert best["kind"] == "EXACT_REVERSE" and best["window"] == 2 and best["similarity"] == 100.0
    assert best["now"]["away"] == "Bologna" and best["now"]["tsi"] is not None and best["now"]["played"] is True
    tm = client.get("/api/lab/takim-maclari?team=Sassuolo").json()
    assert tm["season"] == "2627" and len(tm["matches"]) == 5 and tm["matches"][0]["opponent"] == "Monza"
    d = client.get("/api/dongu?team=Sassuolo&match_id=S-2627-2").json()
    best = d["cycles"][0]
    assert best["past"]["season"] == "2324" and best["past"]["opponents"] == ["Juventus", "Monza", "Bologna", "Torino", "Atalanta"]
    assert d["centre"]["venue"] == "home" and "pairs" in d

    m = client.get("/api/dongu-olc-yok").status_code == 404 or True       # (route name check below)
    m = client.get(f"/api/lab/dongu-olc?kind=EXACT_REVERSE&window=2&similarity=100&team=Sassuolo&tsi={d['centre']['tsi'] or 50}").json()
    band = m["bands"][0]
    assert band["hypothesis"] == "mirror" and {"same_team", "all"} <= {l["key"] for l in band["layers"]}
    for l in band["layers"]:
        assert {"n", "actual", "market", "edge", "ci", "evidence_tr"} <= set(l)
        assert l["evidence_tr"] == "YETERSİZ VERİ"                    # three seasons of one club is not evidence
    assert "olasılık değildir" in m["bands"][0]["note"]
    assert client.get("/api/lab/dongu-olc?kind=NOPE&window=2&similarity=50").status_code == 422

def test_a_firing_notebook_note_arrives_with_the_verdict_it_already_earned(research_client, monkeypatch):
    """The notes are hypotheses and Pattern Lab is the hypothesis engine, so a note that fires today
    comes back with what it measured over 179.545 matches. Lighting up today is not new evidence:
    24 of the 26 claims did not survive their own correction, and the hit must not hide that."""
    import json as _json

    from src.patterns import lab, service

    monkeypatch.setattr(web, "_nesine_brief", lambda *a, **k: {
        "code": 1, "hits": [{"no": 4, "title": "Favoriye oran açılmıyor", "id": "n4"}]})
    monkeypatch.setattr(service, "research_files", lambda *a, **k: {"notes": [
        {"no": 4, "title": "Favoriye oran açılmıyor", "claims": [
            {"outcome": "win", "text": "favori kazanır", "actual": 71.0, "market": 70.4,
             "diff": 0.6, "q": 0.83},
            {"outcome": "draw", "text": "berabere", "actual": 18.0, "ref": 18.2, "q": 0.91}]}]})

    out = lab.scan(web.settings, "s59")
    notes = [c for c in out["context"] if c["source"] == "note"]
    assert len(notes) == 1
    n = notes[0]
    assert n["source_tr"] == "Defter notu 4"
    assert n["value"] == "hiçbir iddiası ayakta değil"        # both q values are far above alpha
    assert "yeni kanıt değil" in n["note"] and "q=0.83" in n["note"]
    # and it stays context: a note measured in its own family never joins this match's correction
    assert all(f["source"] != "note" for f in out["findings"])


def test_the_pattern_lab_tab_is_wired_to_something(client):
    """A tab button whose view nothing ever unhides is worse than no tab. The Pattern Lab lives at
    the top of the research view (the four modes of the brief); the tab jumps there, and every mode
    has a panel, a handler and a real engine behind it."""
    html = client.get("/").text
    js = client.get("/static/app.js").text
    assert 'data-view="lab"' in html and 'id="lab"' in html
    assert 'if (name === "lab")' in js                          # showView knows the tab
    for mode in ("match", "find", "own", "cycle"):              # the four modes, each with its panel
        assert f'data-lab="{mode}"' in html and f'id="lab-{mode}"' in html
    for fn in ("function labInit", "function renderScan", "function renderCycles", "function renderFind",
               "function targetHTML", "function renderOwn", "function renderMeasure"):
        assert fn in js
    for endpoint in ("/api/tarama/", "/api/dongu?", "/api/lab/hedef/", "/api/lab/tara?", "/api/lab/kendi?", "/api/lab/dongu-olc?"):
        assert endpoint in js                                   # the screens call the real engines


def test_a_played_match_says_why_the_notebook_was_never_asked(research_client, monkeypatch):
    """The state table is history, so every match Pattern Lab can scan has already been played — and
    nesine's bulletin is a *pre*-bulletin, dropping an event the moment betting closes. "No note
    fired" and "there was no price to ask about" therefore look identical on screen while meaning
    opposite things, and the second one is the one that happens all day."""
    from src.nesine import bulletin
    from src.patterns import lab

    monkeypatch.setattr(bulletin, "load_matches", lambda *a, **k: ([], {"fetched_at": "x"}))

    out = lab.scan(web.settings, "s59")
    note = next(c for c in out["context"] if c["source"] == "note")
    assert note["label"] == "fiyat yok" and note["data"]["source"] == "yok"
    assert "bahis kapandığı anda maç bültenden düşer" in note["note"]
    assert "hiç sorulmadı" in note["note"]                  # not "the rules were tried and failed"
    assert all(f["source"] != "note" for f in out["findings"])


def test_a_played_match_gets_its_notes_from_the_frozen_pre_kick_off_price(research_client, monkeypatch, tmp_path):
    """Once the bulletin has dropped the match, the archive is the only place its price survives —
    and `watcher.TRACKED` is by construction every price a note reads, so the row can be rebuilt and
    the notebook asked after all. The answer must say it is reading a frozen price, because a price
    seen 15 minutes before kick-off is not the closing price."""
    import datetime as dt

    from src.nesine import archive, bulletin, movement as mv
    from src.patterns import lab

    monkeypatch.setattr(bulletin, "load_matches", lambda *a, **k: ([], {"fetched_at": "x"}))
    monkeypatch.setattr(web.settings, "raw", web.settings.with_overrides(
        **{"data.results_dir": str(tmp_path / "res")}).raw)
    ko = dt.datetime(2026, 2, 4, 18, 0, tzinfo=dt.timezone.utc)      # 21:00 Turkey, the fixture's day
    meta = {"date": "2026-02-04", "time": "21:00", "home": "T5", "away": "T0", "league": "L", "league_code": 1}
    d = archive.archive_dir(web.settings)
    d.mkdir(parents=True, exist_ok=True)
    rows = []
    for minutes, one in ((1440, 2.05), (360, 1.92), (60, 1.84), (15, 1.78)):
        ts = (ko - dt.timedelta(minutes=minutes)).isoformat(timespec="seconds")
        rows.append({"ts": ts, "k": "run", "n": 1, "ch": 3})
        for path, o in (("ms.1", one), ("ms.X", 3.4), ("ms.2", 4.3), ("iy05.alt", 1.64)):
            rows.append({"ts": ts, "c": 777, "p": path, "o": o, "m": minutes})
    with archive.day_path(web.settings, ko.date()).open("a", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r) + "\n")
    archive.meta_path(web.settings, ko.date()).write_text(json.dumps({"777": meta}), encoding="utf-8")
    mv._CACHE.clear()

    out = lab.scan(web.settings, "s59")
    note = next(c for c in out["context"] if c["source"].startswith("note"))
    assert note["source_tr"] == "Defter notu 5"                  # 1,64 in the HT 0,5 market fires it
    assert "donmuş fiyatta tutuyordu" in note["note"] and "15 dakika önceki" in note["note"]
    assert "yeni kanıt değil" in note["note"]                    # still context, still already measured
    # and the movement shape comes back from the same archive the bulletin no longer has
    move = next((c for c in out["context"] if c["source"] == "movement"), None)
    assert move is not None and move["data"]["movement"]["type"]
    assert all(f["source"] != "note" for f in out["findings"])


def _nesine_files(results):
    """One analysed bulletin fixture under the stamp "nesine", the shape the daily job writes."""
    from src.nesine import fixtures as nf

    row = {
        "date": "2026-09-20", "time": "21:00", "league": "CUP", "home": "Juventus", "away": "Nijmegen", "match_id": "nes1",
        "odds_h": 1.06, "odds_d": 6.66, "odds_a": 11.9, "market_h": 80.1, "market_d": 12.9, "market_a": 7.0, "n": 100, "n_eff": 90,
        "hist_h": 91.0, "hist_d": 5.0, "hist_a": 4.0, "adj_h": 83.2, "adj_d": 10.0, "adj_a": 6.8,
        "edge_h": 3.1, "edge_d": -2.9, "edge_a": -0.2, "over25": 60.0, "under25": 40.0, "btts": 40.0, "avg_goals": 3.1,
        "confidence": "MEDIUM", "signal": "NEUTRAL", "signal_outcome": "home", "avg_similarity": 94.0, "median_similarity": 94.5,
        "min_similarity": 90.0, "ci_h_lo": 78.0, "ci_h_hi": 88.0, "ci_d_lo": 6.0, "ci_d_hi": 14.0, "ci_a_lo": 3.0, "ci_a_hi": 10.0,
        "fair_h": 1.2, "fair_d": 10.0, "fair_a": 14.7, "market_over25": float("nan"), "nesine_code": 3188900,
        "league_name": "UEFA Avrupa Ligi", "source": "nesine", "analysed_at": "2026-09-18T06:30:00+00:00",
    }
    pd.DataFrame([row]).to_csv(results / nf.PRED_NAME, index=False)
    (results / nf.DETAILS_NAME).write_text(json.dumps({"matches": {"nes1": {"scorelines": {"2-0": 0.2}, "goals_dist": {}, "scopes": {}}}}))
    pd.DataFrame([{"fixture_id": "nes1", "date": "2023-10-05", "league": "I1", "home_team": "Juventus", "away_team": "Lecce", "cons_h": 1.1,
                   "cons_d": 7.0, "cons_a": 15.0, "similarity": 97.0, "ftr": "H", "score": "3-0", "ou25": "Over", "btts": "No", "distance": 0.02,
                   "years_old": 2.9}]).to_parquet(results / "analogues" / nf.ANALOGUES_NAME, index=False)


def test_day_falls_back_to_the_analysed_bulletin(client):
    _nesine_files(web.RESULTS)
    web._nesine_table_cached.cache_clear()
    # a day Football-Data has not published: the bulletin's fixtures make the day
    d = client.get("/api/day/2026-09-20").json()
    assert [m["id"] for m in d["matches"]] == ["nes1"]
    m = d["matches"][0]
    assert m["source"] == "nesine" and m["nesine_code"] == 3188900 and m["league_name"] == "UEFA Avrupa Ligi" and m["stamp"] == "nesine"
    assert m["home"] == "Juventus" and m["time"] == "21:00" and m["adj"]["h"] == 83.2 and m["scorelines"] == {"2-0": 0.2}
    assert m["live_available"] is False
    # an analysed day keeps its own rows and gains nothing from the bulletin
    assert [x["id"] for x in client.get("/api/day/2026-09-14").json()["matches"]] == ["abc"]
    # the sheet's endpoints read the same files
    assert client.get("/api/match/nes1").json()["match"]["id"] == "nes1"
    an = client.get("/api/analogues/nesine/nes1").json()
    assert an["rows"] and an["rows"][0]["home"] == "Juventus"
    # the bulletin file is not a run day: /api/meta's dates ignore it
    assert "nesine" not in " ".join(client.get("/api/meta").json()["dates"])
