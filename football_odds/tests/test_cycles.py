"""Cycle measurement: the pair table must find the shapes the per-team engine finds, the claims
must be priced, and nothing measured on the pool alone may come back as confirmed."""

import numpy as np
import pandas as pd

from src.patterns import cycles, sequence


def _season(team, opps, season, start, results):
    rows = []
    for i, (opp, r) in enumerate(zip(opps, results)):
        hg, ag = {"W": (2, 0), "D": (1, 1), "L": (0, 1)}[r]
        rows.append({"match_id": f"{team}-{season}-{i}", "date": pd.Timestamp(start) + pd.Timedelta(days=7 * i),
                     "league": "I1", "season": season, "home_team": team, "away_team": opp, "fthg": hg, "ftag": ag,
                     "ftr": "H" if hg > ag else "D" if hg == ag else "A", "htr": "A" if r == "W" else "D",
                     "p_home": 0.5, "p_draw": 0.25, "p_away": 0.25, "h_tsi_pct": 60.0, "a_tsi_pct": 50.0,
                     "cons_h": 2.0, "cons_d": 4.0, "cons_a": 4.0, "avgc_h": 1.9, "avgc_d": 4.0, "avgc_a": 4.2})
    return pd.DataFrame(rows)


def _db():
    past = _season("S", ["Juventus", "Monza", "Bologna", "Torino", "Atalanta"], "2324", "2024-01-01", "WWLDD")
    now = _season("S", ["Atalanta", "Torino", "Bologna", "Juventus", "Monza"], "2627", "2026-08-01", "DLWWD")
    return pd.concat([past, now], ignore_index=True)


def test_the_pair_table_agrees_with_the_per_team_engine_on_the_sassuolo_shape():
    df = _db()
    pairs = cycles.pair_table(df)
    rev = pairs[(pairs["kind"] == "EXACT_REVERSE") & (pairs["window"] == 2) & (pairs["now_match_id"] == "S-2627-2")]
    assert len(rev) == 1
    r = rev.iloc[0]
    assert r["similarity"] == 100.0 and r["positional"] == 60.0 and r["wing"] == 100.0 and r["n_compared"] == 5
    found = sequence.find_cycles(df, "S", centre_match_id="S-2627-2", min_similarity=60)["cycles"][0]
    assert (found["kind"], found["window"], found["similarity"]) == ("EXACT_REVERSE", 2, 100.0)


def test_claims_are_priced_and_read_from_the_club_view():
    pairs = cycles.pair_table(_db())
    r = pairs[(pairs["kind"] == "EXACT_REVERSE") & (pairs["window"] == 2) & (pairs["now_match_id"] == "S-2627-2")].iloc[0]
    assert r["past_res"] == "L" and r["now_res"] == "W"                  # Bologna: lost then, won now
    assert r["mirror_hit"] == 1.0 and r["repeat_hit"] == 0.0             # the mirror held, the repeat did not
    assert abs(r["mirror_p"] - 0.5) < 1e-6                               # priced at the win's own probability
    assert np.isfinite(r["mirror_odds"]) and np.isfinite(r["mirror_close"])


def test_a_pool_measurement_is_never_confirmed_by_itself():
    full = {"n": 5000, "edge": 3.0, "p": 0.001}
    thin = {"n": 20, "edge": 3.0, "p": 0.001}
    assert cycles.evidence(thin, thin, thin, thin) == "thin"
    assert cycles.evidence(full, full, {"n": 0}, {"n": 0}) == "discovery"
    assert cycles.evidence(full, full, full, {"n": 0}) == "confirmed"
    assert cycles.evidence(full, full, full, full) == "tested"
    flipped = {"n": 5000, "edge": -3.0, "p": 0.001}
    assert cycles.evidence(full, full, flipped, full) == "discovery"      # a sign flip is not a confirmation


def test_measure_reports_three_layers_and_the_examples():
    pairs = cycles.pair_table(_db())
    m = cycles.measure(pairs, "EXACT_REVERSE", 2, 100.0, team="S", tsi=60.0)
    assert m["hypothesis"] == "mirror" and [l["key"] for l in m["layers"]] == ["same_team", "all", "similar"]
    assert all(l["evidence"] == "thin" for l in m["layers"])
    ex = m["examples"]
    assert ex and ex[0]["own"] and ex[0]["held"] is True and ex[0]["market_p"] == 50.0
    assert ex[0]["season_a"] == "2324" and ex[0]["season_b"] == "2627"


def test_a_cup_fixture_keeps_each_club_in_its_own_table():
    """A tie between clubs of two leagues names each club's league; positions come from those tables,
    and the CUP row never makes a two-club league."""
    import numpy as np
    import pandas as pd

    from src.patterns.state import build_state, fixture_rows

    rows = []
    d = pd.Timestamp("2025-08-01")
    for k in range(6):                                              # two leagues, three rounds each
        for lg, teams in (("E0", ["E1", "E2", "E3", "E4"]), ("SP1", ["S1", "S2", "S3", "S4"])):
            h, a = teams[k % 4], teams[(k + 1) % 4]
            rows.append({"match_id": f"{lg}{k}", "date": d + pd.Timedelta(days=7 * k), "league": lg, "season": "2526",
                         "home_team": h, "away_team": a, "fthg": 2.0 if lg == "E0" else 0.0, "ftag": 0.0 if lg == "E0" else 1.0,
                         "ftr": "H" if lg == "E0" else "A", "p_home": 0.5, "p_draw": 0.25, "p_away": 0.25})
    df = pd.DataFrame(rows)
    fx = pd.DataFrame([{"match_id": "cup1", "date": "2025-09-20", "league": "CUP", "home": "E1", "away": "S2",
                        "home_league": "E0", "away_league": "SP1", "market_h": 50.0, "market_d": 25.0, "market_a": 25.0}])
    extra = fixture_rows(fx)
    assert list(extra["home_league"]) == ["E0"] and list(extra["away_league"]) == ["SP1"]
    st = build_state(pd.concat([df, extra], ignore_index=True), progress_every=0)
    cup = st[st["match_id"] == "cup1"].iloc[0]
    last_e = st[(st["league"] == "E0")].iloc[-1]
    # the home club's position is its E0 position (a four-club table), not 1 or 2 of a two-club "CUP" league
    assert cup["h_pos"] is not None and not np.isnan(float(cup["h_pos"])) and 1 <= float(cup["h_pos"]) <= 4
    assert cup["a_pos"] is not None and not np.isnan(float(cup["a_pos"])) and 1 <= float(cup["a_pos"]) <= 4
    assert cup["league"] == "CUP" and last_e["league"] == "E0"
    # the last match's own and conceded goals ride along (note 19 reads "lost 2-3")
    for r in (last_e, cup):
        for col in ("h_last_gf", "h_last_ga", "a_last_gf", "a_last_ga"):
            assert r[col] is not None and int(r[col]) in (0, 1, 2)                 # each club's previous score, from its own view
    assert int(cup["a_last_gf"]) + int(cup["a_last_ga"]) == 1                    # SP1 games end 0-1
