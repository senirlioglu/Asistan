"""Match state: the features must describe the past only, and describe it correctly."""

import pandas as pd
import pytest

from src.patterns import state


def _frame(rows: list[dict]) -> pd.DataFrame:
    """A minimal processed-schema frame: the builder only needs these columns."""
    df = pd.DataFrame(rows)
    df["date"] = pd.to_datetime(df["date"])
    df["match_id"] = [f"m{i}" for i in range(len(df))]
    df["league"] = df.get("league", "E0")
    df["season"] = df.get("season", "2526")
    df["ftr"] = ["H" if h > a else "D" if h == a else "A" for h, a in zip(df["fthg"], df["ftag"])]
    for col in ("p_home", "p_draw", "p_away"):
        if col not in df:
            df[col] = float("nan")
    return df


def _m(date, home, away, hg, ag, **kw):
    return {"date": date, "home_team": home, "away_team": away, "fthg": hg, "ftag": ag, **kw}


def test_form_goals_table_and_h2h_are_read_off_the_earlier_matches():
    df = _frame([
        _m("2026-01-01", "A", "B", 4, 0),
        _m("2026-01-04", "C", "A", 1, 1),
        _m("2026-01-08", "A", "C", 5, 1),
        _m("2026-01-11", "B", "A", 2, 0),
        _m("2026-01-14", "A", "B", 4, 1),     # A's last three: 5-1, 0-2 (away), 4-1
        _m("2026-01-17", "A", "C", 0, 0),     # <- the row under test
    ])
    row = state.build_state(df).iloc[-1]
    assert row["h_form"] == "WDWLW" and row["h_form_venue"] == "WWW"      # B's win came away from A
    assert state.seq(row["h_form"]) == [1, 0, 1, -1, 1]
    assert row["h_gf3"] == 9 and row["h_ga3"] == 4                         # 5+0+4 scored, 1+2+1 conceded
    assert row["h_cs3"] == 0 and row["h_fts3"] == 1 and row["h_btts3"] == 2
    assert row["h_rest_days"] == 3 and row["h_games7"] == 2 and row["h_games14"] == 4
    assert row["h_played"] == 5 and row["h_pts"] == 10 and row["h_gd"] == 9
    assert row["a_form"] == "DL" and row["a_played"] == 2                  # C drew, then lost 1-5
    assert row["h_pos"] == 1                                               # A leads the table on points
    # H2H is counted from TODAY'S home team's view: A drew 1-1 at C, then beat C 5-1
    assert (row["h2h_n"], row["h2h_home_wins"], row["h2h_draws"], row["h2h_away_wins"]) == (2, 1, 1, 0)


def test_state_never_looks_at_the_match_itself_or_later_ones():
    """Rebuild each row from the prefix of the database that precedes it: the features must match."""
    rows = []
    teams = ["A", "B", "C", "D"]
    for i in range(40):
        h, a = teams[i % 4], teams[(i + 1 + i // 4) % 4]
        if h == a:
            a = teams[(i + 2) % 4]
        rows.append(_m(f"2026-{1 + i // 20:02d}-{1 + i % 20:02d}", h, a, i % 4, (i + 1) % 3,
                       p_home=0.4 + (i % 5) / 20, p_draw=0.25, p_away=0.35 - (i % 5) / 20))
    df = _frame(rows)
    full = state.build_state(df).set_index("match_id")
    for mid in ("m20", "m31", "m39"):
        target = df[df["match_id"] == mid]
        earlier = df[df["date"] < target["date"].iloc[0]]
        # the same match, but with every later match (and every same-day one) removed from the pool
        partial = state.build_state(pd.concat([earlier, target], ignore_index=True)).set_index("match_id")
        a, b = full.loc[mid], partial.loc[mid]
        same = [c for c in full.columns if c not in ("date",)]
        pd.testing.assert_series_equal(a[same], b[same], check_names=False, obj=f"{mid} rebuilt from its own past")


def test_tsi_follows_the_market_not_the_scoreline():
    """The rating distils what bookmakers thought, so a heavy favourite that keeps losing keeps its rating."""
    rows = [_m(f"2026-01-{d:02d}", "Fav", "Dog", 0, 1, p_home=0.80, p_draw=0.12, p_away=0.08) for d in range(1, 11)]
    out = state.build_state(_frame(rows))
    assert out["h_elo"].iloc[0] == state.ELO_START
    assert out["h_elo"].iloc[-1] > out["h_elo"].iloc[0] + 30      # ten losses, still rated up: the market said so
    assert out["strength_gap"].iloc[-1] > 60
    # ... and with no odds at all the rating cannot move
    flat = state.build_state(_frame([_m(f"2026-02-{d:02d}", "X", "Y", 3, 0) for d in range(1, 6)]))
    assert flat["h_elo"].nunique() == 1 == flat["a_elo"].nunique()


def test_build_writes_next_to_the_database(settings, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "raw", settings.with_overrides(**{"data.processed_dir": str(tmp_path)}).raw)
    df = _frame([_m("2026-01-01", "A", "B", 1, 0), _m("2026-01-05", "B", "A", 2, 2)])
    out = state.build(settings, df)
    assert state.state_path(settings).exists() and len(state.load(settings)) == len(out) == 2
    with pytest.raises(ValueError, match="match state needs columns"):
        state.build_state(df.drop(columns=["fthg"]))
