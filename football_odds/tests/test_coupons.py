import pytest

from src.pipeline import coupons as cp


def _row(**kw):
    base = {"id": "m1", "date": "2026-09-14", "time": "22:00", "league": "E0", "home": "Arsenal", "away": "Everton",
            "market": {"h": 60.0, "d": 22.0, "a": 18.0}, "adj": {"h": 55.0, "d": 26.0, "a": 19.0},
            "odds": {"h": 1.6, "d": 4.2, "a": 5.5}, "odds_o25": 1.9, "odds_u25": 1.95, "market_over25": 55.0, "hist_over25": 45.0,
            "hist_over15": 80.0, "fh_over05": 0.6, "fh_over15": 0.2, "sh_over05": 0.7, "sh_over15": 0.3}
    base.update(kw)
    return base


def test_system_picks_per_market():
    r = _row()
    assert cp.system_picks(r, "ms") == {"hist": "h", "market": "h", "p_hist": 55.0, "p_market": 60.0}
    assert cp.system_picks(r, "o25")["hist"] == "under" and cp.system_picks(r, "o25")["market"] == "over"
    assert cp.system_picks(r, "fh15") == {"hist": "under", "market": None, "p_hist": 20.0, "p_market": None}
    assert cp.odds_for(r, "ms", "d") == 4.2 and cp.odds_for(r, "o25", "under") == 1.95 and cp.odds_for(r, "fh05", "over") is None


def test_build_coupon_validates():
    rows = {"m1": _row()}
    c = cp.build_coupon([{"match_id": "m1", "market": "ms", "pick": "d"}, {"match_id": "m1", "market": "sh05", "pick": "over"}], rows, "test")
    assert len(c["picks"]) == 2 and c["label"] == "test" and c["picks"][0]["odds"] == 4.2 and c["picks"][1]["odds"] is None
    assert c["picks"][0]["system"]["hist"] == "h"
    with pytest.raises(ValueError):
        cp.build_coupon([], rows)
    with pytest.raises(ValueError):
        cp.build_coupon([{"match_id": "zz", "market": "ms", "pick": "h"}], rows)
    with pytest.raises(ValueError):
        cp.build_coupon([{"match_id": "m1", "market": "ms", "pick": "x"}], rows)
    with pytest.raises(ValueError):
        cp.build_coupon([{"match_id": "m1", "market": "ms", "pick": "h"}, {"match_id": "m1", "market": "ms", "pick": "d"}], rows)


def test_settle_and_evaluate():
    rows = {"m1": _row()}
    c = cp.attach_prices(cp.build_coupon([{"match_id": "m1", "market": "ms", "pick": "d"}, {"match_id": "m1", "market": "o25", "pick": "under"},
                                          {"match_id": "m1", "market": "fh05", "pick": "over"}], rows), rows)
    pending = cp.evaluate(c, {})
    assert pending["status"] == "pending" and pending["tally"]["user"]["pending"] == 3
    done = cp.evaluate(c, {"m1": {"hs": 1, "as": 1, "ht_h": 0, "ht_a": 0}})
    by = {p["market"]: p for p in done["picks"]}          # picks are stored sorted by market name
    p_ms, p_o25, p_fh = by["ms"], by["o25"], by["fh05"]
    assert p_ms["user_ok"] and not p_ms["hist_ok"] and not p_ms["market_ok"]          # you: X ✓, system: 1 ✗
    assert p_o25["user_ok"] and p_o25["hist_ok"] and not p_o25["market_ok"]          # under ✓; history under ✓; market over ✗
    assert not p_fh["user_ok"] and not p_fh["hist_ok"] and p_fh["market_ok"] is None  # 0 first-half goals: over wrong, market has no view
    assert done["tally"]["user"]["wrong"] == 1 and done["status"] == "lost"
    assert abs(done["tally"]["user"]["pnl"] - ((4.2 - 1) + (1.95 - 1))) < 1e-9
    assert abs(done["tally"]["hist"]["pnl"] - (-1.0 + (1.95 - 1))) < 1e-9             # system: 1 lost at 1.6, under won at 1.95
    assert abs(done["tally"]["market"]["pnl"] - (-1.0 - 1.0)) < 1e-9
    half_missing = cp.evaluate(c, {"m1": {"hs": 1, "as": 1, "ht_h": None, "ht_a": None}})
    assert next(p for p in half_missing["picks"] if p["market"] == "fh05")["user_ok"] is None and half_missing["status"] == "pending"


def test_store_roundtrip(tmp_path):
    from src.config import load_settings
    settings = load_settings().with_overrides(**{"data.results_dir": str(tmp_path)})
    assert cp.load(settings) == []
    cp.save(settings, [{"id": "a", "picks": []}])
    assert cp.load(settings)[0]["id"] == "a"


def test_half_time_markets_settle_and_frozen_odds_ride_along():
    rows = {"m1": _row()}
    lab = {"target": "htft_2/1", "target_label": "2/1", "market_p": 3.1, "estimate_p": 3.4, "difference": 0.3,
           "evidence": "FARK YOK", "why": "eski maçlar oranı doğruluyor", "source": "pattern-lab", "junk": "dropped"}
    c = cp.build_coupon([{"match_id": "m1", "market": "iyms", "pick": "2/1", "odds": 24.95, "odds_source": "nesine", "nesine_code": 3144896, "lab": lab},
                         {"match_id": "m1", "market": "iy", "pick": "d"}], rows, "lab kuponu")
    p = next(x for x in c["picks"] if x["market"] == "iyms")
    assert p["odds"] == 24.95 and p["odds_source"] == "nesine" and p["nesine_code"] == 3144896
    assert p["lab"]["evidence"] == "FARK YOK" and "junk" not in p["lab"]
    assert p["system"] == {"hist": None, "market": None, "p_hist": None, "p_market": None}
    # settled from the half-time score: trailed 0-1 at the break, won 2-1
    res = {"m1": {"hs": 2, "as": 1, "ht_h": 0, "ht_a": 1}}
    ev = cp.evaluate(c, res)
    got = {x["market"]: x for x in ev["picks"]}
    assert got["iyms"]["user_ok"] is True and got["iyms"]["pnl"] == pytest.approx(23.95) and got["iyms"]["pick_label"] == "2/1"
    assert got["iy"]["user_ok"] is False                       # half time was 0-1, not a draw
    assert ev["tally"]["user"] == {"ok": 1, "wrong": 1, "pending": 0, "pnl": pytest.approx(23.95), "n_odds": 1}
    # no half-time score: those markets wait
    ev2 = cp.evaluate(c, {"m1": {"hs": 2, "as": 1, "ht_h": None, "ht_a": None}})
    assert all(x["user_ok"] is None for x in ev2["picks"]) and ev2["status"] == "pending"
    # a bad price is ignored, not stored
    c2 = cp.build_coupon([{"match_id": "m1", "market": "ms", "pick": "h", "odds": "abc"}], rows)
    assert c2["picks"][0]["odds"] == rows["m1"]["odds"]["h"] and "odds_source" not in c2["picks"][0]
    with pytest.raises(ValueError):
        cp.build_coupon([{"match_id": "m1", "market": "iyms", "pick": "3/1"}], rows)
