import json
from pathlib import Path

import pandas as pd

from src.nesine import bulletin, rules
from src.nesine.history import TeamIndex, backtest, team_hits

SAMPLE = json.loads((Path(__file__).parent / "fixtures_nesine_sample.json").read_text(encoding="utf-8"))


def test_parse_sample_bulletin():
    ms = bulletin.parse_bulletin(SAMPLE)
    assert len(ms) == 2
    m = ms[0]
    assert m["home"] and m["away"] and m["date"].startswith("2026-") and m["time"]
    assert set(m["ms"]) == {"1", "X", "2"} and all(v > 1.0 for v in m["ms"].values())
    assert set(m["iyms"]) == {"1/1", "1/X", "1/2", "X/1", "X/X", "X/2", "2/1", "2/X", "2/2"}
    assert m["iy_skor"].get("0-0") and m["skor"].get("1-0") and "diger" in m["iy_skor"] and "diger" in m["skor"]
    assert set(m["o25"]) == {"alt", "ust"} and set(m["iy_kg"]) == {"var", "yok"}
    assert "evet/evet" in m["iy_y2_kg"] and "1&var" in m["iy_sonucu_kg"]
    assert m["korner"] and all(" · " in k for k in m["korner"])


def _m(**kw):
    base = {"code": 1, "date": "2026-09-20", "time": "20:00", "home": "A", "away": "B", "league": "L", "league_code": 1,
            "ms": {"1": 2.30, "X": 3.40, "2": 2.30}, "iyms": {"1/2": 24.0, "2/1": 24.0}, "iy": {}, "iy05": {"alt": 1.64, "ust": 2.2},
            "h1_15": {}, "h2_15": {}, "o25": {}, "o35": {}, "o45": {"ust": 3.0}, "gol_araligi": {}, "iy_kg": {}, "y2_kg": {},
            "iy_y2_kg": {"evet/evet": 7.5}, "iy_sonucu_kg": {"1&var": 7.9, "2&var": 12.0}, "ilk_gol": {}, "iki_yari_15_ust": {"evet": 3.15},
            "iy_skor": {"2-1": 30.0, "1-2": 33.0, "2-2": 37.0, "diger": 4.9}, "skor": {"diger": 7.5}, "korner": {}}
    base.update(kw)
    return base


def test_rules_fire_and_explain():
    hits = {h["id"]: h for h in rules.evaluate(_m())}
    assert "n1" in hits and hits["n1"]["evidence"]["İY skor 2-2"] == 37.0
    assert "n5" in hits and "İY 0,5 alt" in hits["n5"]["evidence"]
    assert "n6" not in hits                      # 24 is not below 18
    assert "n7" in hits and "n12" in hits and "n13" in hits and "n15" in hits
    assert "n11" in hits and "OYNA" in hits["n11"]["expect"] and "OYNAMA" not in hits["n11"]["expect"]
    # asymmetric by 0.01: direction follows the lower side, window check on that combo only
    h2 = {h["id"]: h for h in rules.evaluate(_m(ms={"1": 2.31, "X": 3.4, "2": 2.30}, iyms={"1/2": 27.0, "2/1": 24.0}))}
    assert h2["n11"]["expect"].startswith("1/2") and "OYNAMA" in h2["n11"]["expect"]
    assert "n6" in {h["id"] for h in rules.evaluate(_m(iyms={"1/2": 17.5}))}
    h4 = {h["id"]: h for h in rules.evaluate(_m(ms={"1": 1.15, "X": 6.0, "2": 12.0}))}
    assert "n4" in h4 and h4["n4"]["evidence"]["Favori"] == "ev sahibi"
    assert "n4" in {h["id"] for h in rules.evaluate(_m(ms={"X": 8.0, "2": 15.0}))}   # favourite not offered
    h10 = {h["id"]: h for h in rules.evaluate(_m(ms={"1": 1.67, "X": 3.6, "2": 4.5}))}
    assert "n10" in h10 and "n16" in h10 and "1-0" in h10["n10"]["expect"]
    assert "n16" in {h["id"] for h in rules.evaluate(_m(ms={"1": 4.5, "X": 3.6, "2": 1.75}))}
    assert "n10" not in {h["id"] for h in rules.evaluate(_m(ms={"1": 1.68, "X": 3.6, "2": 4.5}))}
    assert not [h for h in rules.evaluate(_m(ms={"1": 1.5, "X": 4.0, "2": 6.0}, iyms={}, iy05={}, iy_y2_kg={}, iy_sonucu_kg={}, iy_skor={}, skor={}, o45={}, iki_yari_15_ust={}))]


def test_team_history_hits(history):
    df = history.copy()
    df["htr"] = "D"; df["hthg"] = 0.0; df["htag"] = 0.0
    # note 2 counts the matches played after the reversal: today is the 7th of them, so the reversal is
    # the 7th row back. The 6th row back must NOT fire it (the bug the owner caught on Espanyol).
    rows = df[(df["home_team"] == "H1") | (df["away_team"] == "H1")].sort_values("date")
    last, seventh = rows.index[-1], rows.index[-7]
    df.loc[last, ["htr", "ftr"]] = ["H", "A"]
    df.loc[seventh, ["htr", "ftr"]] = ["A", "H"]
    idx = TeamIndex(df, recent_days=40000)
    assert idx.resolve("H1") == "H1" and idx.resolve("Zzz United") is None
    # women's / youth / reserve sides are different clubs, never resolved to the first team
    for wrong in ("H1 (K)", "H1 Kadın", "H1 U21", "H1 U19", "H1 Women", "H1 II"):
        assert idx.resolve(wrong) is None, wrong
    hits = team_hits({"date": "2030-01-01", "home": "H1", "away": "Nobody FC"}, idx)
    assert "n14" in hits and "n2" in hits and "7 maç önce" in " ".join(hits["n2"]["evidence"])
    # the same reversal one row later (6 matches back) is the wrong count and must not fire note 2
    df2 = df.copy()
    df2.loc[seventh, ["htr", "ftr"]] = ["D", "D"]
    df2.loc[rows.index[-6], ["htr", "ftr"]] = ["A", "H"]
    assert "n2" not in team_hits({"date": "2030-01-01", "home": "H1", "away": "Nobody FC"}, TeamIndex(df2, recent_days=40000))
    bt = backtest(df)
    assert bt["n_matches"] > 0 and "n4" in bt and "n11" in bt and bt["n14"]["n"] >= 1 and bt["n2"]["n"] >= 1


def test_nesine_prices_survive_the_high_margin(settings):
    from src.nesine.analyze import MAX_OVERROUND, priced_row, to_raw_row
    m = _m(ms={"1": 2.53, "X": 3.01, "2": 2.07}, o25={"alt": 1.83, "ust": 1.51})
    raw = to_raw_row(m)
    assert raw["AvgH"] == 2.53 and raw["Avg>2.5"] == 1.51 and raw["Date"] == "20/09/2026"
    row = priced_row(settings, m)
    assert row is not None and bool(row["has_1x2"]) and bool(row["has_ou"])
    # nesine's margin is ~21 %: far above the config ceiling for European averages, still priced here
    assert 1.15 < float(row["overround_1x2"]) < MAX_OVERROUND
    assert abs(float(row["p_home"]) + float(row["p_draw"]) + float(row["p_away"]) - 1.0) < 1e-9
    assert priced_row(settings, _m(ms={"1": 2.53})) is None        # incomplete 1X2 -> not analysable
