from src.pipeline import paper


def _row(**kw):
    base = {"id": "m1", "date": "2026-09-14", "time": "22:00", "league": "E0", "home": "Arsenal", "away": "Everton",
            "market": {"h": 60.0, "d": 22.0, "a": 18.0}, "adj": {"h": 55.0, "d": 26.0, "a": 19.0},
            "odds": {"h": 1.6, "d": 4.2, "a": 5.5}, "odds_max": {"h": 1.7, "d": 4.5, "a": 6.0},
            "odds_o25": 1.9, "odds_u25": 1.95, "odds_max_o25": 2.0, "odds_max_u25": 2.05, "market_over25": 55.0, "hist_over25": 45.0}
    base.update(kw)
    return base


def test_picks():
    r = _row()
    assert paper.pick_for("market_fav", r, 3) == ("h", 1.6, 1.7)
    assert paper.pick_for("hist_fav", r, 3) == ("h", 1.6, 1.7)
    assert paper.pick_for("deviation", r, 3) == ("d", 4.2, 4.5)      # draw: history 26 vs market 22 -> +4
    assert paper.pick_for("deviation", r, 5) is None                  # no gap of 5 points
    assert paper.pick_for("contrarian", r, 3) == ("h", 1.6, 1.7)     # home: market 60 vs history 55 -> +5 for the market
    assert paper.pick_for("ou25_hist", r, 3) == ("under", 1.95, 2.05)
    assert paper.pick_for("ou25_market", r, 3) == ("over", 1.9, 2.0)
    assert paper.pick_for("ou25_hist", _row(odds_o25=None), 3) is None


def test_settle():
    assert paper.settle("h", {"hs": 2, "as": 1}) and not paper.settle("d", {"hs": 2, "as": 1})
    assert paper.settle("over", {"hs": 2, "as": 1}) and paper.settle("under", {"hs": 1, "as": 1})


def test_simulate_profit_and_roi():
    rows = [_row(), _row(id="m2", date="2026-09-15", home="Chelsea", away="Fulham"), _row(id="m3", date="2026-09-16")]
    results = {"m1": {"hs": 2, "as": 1}, "m2": {"hs": 0, "as": 0}}       # m3 pending
    out = paper.simulate(rows, results, edge=3.0, names={"E0": "Premier"})
    fav = next(s for s in out["strategies"] if s["key"] == "market_fav")
    assert fav["n_bets"] == 3 and fav["n_settled"] == 2 and fav["n_pending"] == 1
    assert fav["wins"] == 1 and abs(fav["profit"] - (0.6 - 1.0)) < 1e-9 and abs(fav["roi_pct"] - (-20.0)) < 1e-9
    assert abs(fav["profit_max"] - (0.7 - 1.0)) < 1e-9
    assert [c["pnl"] for c in fav["curve"]] == [0.6, -0.4]
    assert fav["max_drawdown"] == 1.0
    dev = next(s for s in out["strategies"] if s["key"] == "deviation")
    assert dev["wins"] == 1 and abs(dev["profit"] - (3.2 - 1.0)) < 1e-9   # draw came in the second match at 4.2
    assert dev["by_league"][0]["league_name"] == "Premier" and "3 puan" in dev["desc"]
    ou = next(s for s in out["strategies"] if s["key"] == "ou25_hist")
    assert ou["wins"] == 1 and ou["losses"] == 1                          # under: lost 2-1, won 0-0
    assert all(b["settled"] is False for b in fav["bets"] if b["id"] == "m3")
