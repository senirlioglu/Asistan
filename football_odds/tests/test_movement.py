"""Odds movement engine: the measurements must be in margin-free probability, the windows must
refuse to answer when nobody was watching, and the classification must not fire on noise."""

import datetime as dt
import json

import pytest

from src.nesine import archive, movement as mv

KO = dt.datetime(2026, 9, 20, 18, 0, tzinfo=dt.timezone.utc)      # 21:00 Turkey time
META = {"code": 55, "date": "2026-09-20", "time": "21:00", "home": "A", "away": "B", "league": "L"}


@pytest.fixture()
def arch(settings, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "raw", settings.with_overrides(**{"data.results_dir": str(tmp_path)}).raw)
    mv._CACHE.clear()
    return settings


def write(settings, rows, day=KO.date(), code=55):
    """rows: (minutes_before_kickoff, path, odds). One archive line each, plus a heartbeat per stamp."""
    d = archive.archive_dir(settings)
    d.mkdir(parents=True, exist_ok=True)
    lines, seen = [], set()
    for minutes, path, odds in rows:
        ts = (KO - dt.timedelta(minutes=minutes)).isoformat(timespec="seconds")
        if ts not in seen:
            lines.append({"ts": ts, "k": "run", "n": 1, "ch": 1})
            seen.add(ts)
        lines.append({"ts": ts, "c": code, "p": path, "o": odds, "m": minutes})
    with archive.day_path(settings, day).open("a", encoding="utf-8") as fh:
        for line in lines:
            fh.write(json.dumps(line) + "\n")
    meta = json.loads(archive.meta_path(settings, day).read_text(encoding="utf-8")) if archive.meta_path(settings, day).exists() else {}
    archive.meta_path(settings, day).write_text(json.dumps({**meta, str(code): {**META, "code": code}}), encoding="utf-8")
    mv._CACHE.clear()


def steam_rows():
    """The spec's own example: 2.05 -> 1.96 -> 1.88 -> 1.81 -> 1.76 with the other two drifting."""
    home = [(1440, 2.05), (720, 1.96), (360, 1.88), (60, 1.81), (15, 1.76)]
    rows = []
    for minutes, o in home:
        rows += [(minutes, "ms.1", o), (minutes, "ms.X", 3.40), (minutes, "ms.2", round(4.00 + (2.05 - o) * 3, 2))]
    return rows


def test_the_series_is_margin_free_probability_not_raw_odds(arch):
    write(arch, steam_rows())
    s = mv.trajectory(arch, 55, as_of=KO - dt.timedelta(minutes=10))["ms.1"]
    assert s.novig is True and len(s.points) == 5
    # 1/2.05 = 48.8 % raw, but the three prices carry a margin, so the no-vig figure is lower
    assert 0.42 < s.points[0].prob < 0.487
    assert abs(sum(p.prob for p in mv.trajectory(arch, 55, as_of=KO)["ms.1"].points[:1]) - s.points[0].prob) < 1e-9
    total = sum(mv.trajectory(arch, 55, as_of=KO)[p].points[0].prob for p in ("ms.1", "ms.X", "ms.2"))
    assert abs(total - 1.0) < 1e-9                    # the margin is gone: the three sum to one


def test_a_partially_tracked_market_is_not_pretended_to_be_no_vig(arch):
    write(arch, [(600, "skor.diger", 30.0), (60, "skor.diger", 26.0)])
    s = mv.trajectory(arch, 55, as_of=KO)["skor.diger"]
    assert s.novig is False                            # four of 29 outcomes: normalising would be a lie
    assert abs(s.points[0].prob - 1 / 30.0) < 1e-9     # raw implied probability instead


def test_open_current_close_and_that_close_stays_empty_until_kick_off(arch):
    write(arch, steam_rows())
    before = mv.trajectory(arch, 55, as_of=KO - dt.timedelta(minutes=10))["ms.1"]
    live = mv.open_current_close(before, started=False)
    assert live["open"]["odds"] == 2.05 and live["current"]["odds"] == 1.76
    assert live["closing"] is None                     # the last price we hold is not a closing price

    done = mv.open_current_close(before, started=True)
    assert done["closing"]["odds"] == 1.76             # only once the match has actually started


def test_a_window_whose_start_we_never_saw_reports_nothing(arch):
    """The archive begins when the archive begins. A match first seen 100 minutes before kick-off
    has no 3h, 6h, 12h or 24h measurement, and inventing one from the earliest price we happen to
    hold would turn "we arrived late" into "the price did not move"."""
    write(arch, [(100, "ms.1", 2.05), (100, "ms.X", 3.4), (100, "ms.2", 4.0),
                 (15, "ms.1", 1.76), (15, "ms.X", 3.4), (15, "ms.2", 5.0)])
    w = mv.window_features(mv.trajectory(arch, 55, as_of=KO)["ms.1"])
    for name in ("24h", "12h", "6h", "3h"):
        assert w[name]["insufficient"] is True and w[name]["delta_p"] is None, name
    assert w["1h"]["insufficient"] is False and w["1h"]["n_changes"] == 1
    assert w["15m"]["insufficient"] is False


def test_a_price_in_force_carries_across_a_quiet_window(arch):
    """Only changes are stored, so silence means the price held: a window with no change inside it
    still has a start and an end, and its delta is zero rather than unknown."""
    write(arch, [(1440, "ms.1", 2.05), (1440, "ms.X", 3.4), (1440, "ms.2", 4.0),
                 (15, "ms.1", 1.76), (15, "ms.X", 3.4), (15, "ms.2", 5.0)])
    w = mv.window_features(mv.trajectory(arch, 55, as_of=KO)["ms.1"])
    assert w["6h"]["insufficient"] is False and w["6h"]["n_changes"] == 1
    assert w["24h"]["n_changes"] == 2
    assert w["6h"]["start_p"] == w["24h"]["start_p"]          # the 24h price was still in force


def test_velocity_separates_the_same_move_at_two_speeds(arch):
    """The same +pp over 30 minutes and over 6 hours is not the same signal, and the number has to
    say so: percentage points per hour, not percentage points."""
    def legs(minutes_from, minutes_to):
        return [(minutes_from, "ms.1", 2.05), (minutes_from, "ms.X", 3.4), (minutes_from, "ms.2", 4.0),
                (minutes_to, "ms.1", 1.80), (minutes_to, "ms.X", 3.4), (minutes_to, "ms.2", 4.0)]

    write(arch, legs(31, 1), code=55)
    write(arch, legs(360, 1), code=66)
    fast = mv.velocities(mv.window_features(mv.trajectory(arch, 55, as_of=KO)["ms.1"]))
    slow = mv.velocities(mv.window_features(mv.trajectory(arch, 66, as_of=KO)["ms.1"]))
    assert fast["velocity_30m"] is not None and slow["velocity_6h"] is not None
    assert abs(fast["velocity_30m"]) > 5 * abs(slow["velocity_6h"])   # identical move, far faster


def test_direction_consistency_tells_a_straight_move_from_a_wandering_one(arch):
    straight = [mv.Point(ts=KO, minutes=m, odds=0, prob=p / 100, changed=True)
                for m, p in ((240, 50.0), (180, 51.5), (120, 53.0), (60, 54.5))]
    wobble = [mv.Point(ts=KO, minutes=m, odds=0, prob=p / 100, changed=True)
              for m, p in ((240, 50.0), (180, 53.5), (120, 51.0), (60, 54.5))]
    assert mv.direction_consistency(straight) == 1.0            # every step in the same direction
    assert mv.direction_consistency(wobble) < 0.6               # same destination, longer road
    assert mv.direction_consistency(straight[:1]) is None       # one point is not a direction


def test_reversal_reports_both_legs_and_the_recovery(arch):
    pts = [mv.Point(ts=KO, minutes=m, odds=0, prob=p / 100, changed=True)
           for m, p in ((300, 50.0), (200, 58.0), (100, 56.0), (30, 46.0))]
    r = mv.reversal(pts)
    assert r["initial_pp"] == 8.0 and r["reversal_pp"] == -12.0
    assert r["recovery_pct"] == 150.0                            # it came back past where it started
    tiny = [mv.Point(ts=KO, minutes=m, odds=0, prob=p / 100, changed=True)
            for m, p in ((300, 50.0), (200, 50.4), (30, 50.1))]
    assert mv.reversal(tiny) is None                             # a 0.4 pp wobble is not a reversal


def test_steam_is_classified_and_a_flat_price_is_not(arch):
    write(arch, steam_rows())
    s = mv.trajectory(arch, 55, as_of=KO)["ms.1"]
    got = mv.classify(s)
    assert got["type"] == "STEAM" and got["total_pp"] > 1.5
    assert got["consistency"] == 1.0 and got["confidence"] == "ok"

    flat = []
    for minutes in (1440, 720, 360, 60):
        flat += [(minutes, "ms.1", 2.05 if minutes > 300 else 2.04), (minutes, "ms.X", 3.4), (minutes, "ms.2", 4.0)]
    write(arch, flat, code=66)
    steady = mv.classify(mv.trajectory(arch, 66, as_of=KO)["ms.1"])
    assert steady["type"] == "STABLE" and abs(steady["total_pp"]) < 0.75


def test_a_match_with_two_snapshots_is_not_classified(arch):
    write(arch, [(1440, "ms.1", 2.05), (1440, "ms.X", 3.4), (1440, "ms.2", 4.0)])
    got = mv.classify(mv.trajectory(arch, 55, as_of=KO)["ms.1"])
    assert got["type"] is None and got["confidence"] == "low"
    assert "snapshot" in got["reason"]


def test_thresholds_come_from_config_and_nothing_is_hardcoded(arch, monkeypatch):
    write(arch, steam_rows())
    s = mv.trajectory(arch, 55, as_of=KO)["ms.1"]
    assert mv.classify(s)["type"] == "STEAM"
    strict = mv.MovementConfig(movement_min_pp=50.0, stable_max_pp=49.0)
    assert mv.classify(s, strict)["type"] == "STABLE"            # same data, a different opinion

    monkeypatch.setenv("FO_MOVE_MOVEMENT_MIN_PP", "9.5")
    assert mv.config_from_env().movement_min_pp == 9.5
    monkeypatch.setenv("FO_MOVE_MOVEMENT_MIN_PP", "nonsense")
    assert mv.config_from_env().movement_min_pp == mv.DEFAULT_CONFIG.movement_min_pp


def test_coverage_counts_the_refreshes_not_the_price_changes(arch):
    write(arch, steam_rows())
    s = mv.trajectory(arch, 55, as_of=KO)["ms.1"]
    q = mv.coverage(arch, s, as_of=KO)
    assert q["snapshots"] == 5 and q["runs"] >= 4 and q["novig"] is True
    assert 0.0 <= q["coverage"] <= 1.0


def test_the_payload_says_which_selections_it_could_not_find(arch):
    write(arch, steam_rows())
    out = mv.for_match(arch, 55, as_of=KO - dt.timedelta(minutes=5))
    assert out["match"]["home"] == "A" and out["started"] is False
    assert out["selections"]["ms.1"]["movement"]["type"] == "STEAM"
    assert out["selections"]["ms.1"]["closing"] is None
    assert len(out["selections"]["ms.1"]["chart"]) == 5
    missing = mv.for_match(arch, 55, paths=("o25.ust",), as_of=KO)
    assert missing["selections"]["o25.ust"] == {"missing": True}


def test_the_incremental_reader_sees_lines_appended_after_the_first_read(arch):
    write(arch, [(1440, "ms.1", 2.05), (1440, "ms.X", 3.4), (1440, "ms.2", 4.0)])
    first = mv.trajectory(arch, 55, as_of=KO)["ms.1"]
    assert len(first.points) == 1
    mv._CACHE[str(archive.day_path(arch, KO.date()))] = _consumed(arch)   # pretend we cached the head
    write(arch, [(60, "ms.1", 1.80), (60, "ms.X", 3.4), (60, "ms.2", 4.6)])
    again = mv.trajectory(arch, 55, as_of=KO)["ms.1"]
    assert len(again.points) == 2 and again.points[-1].odds == 1.80


def _consumed(settings):
    p = archive.day_path(settings, KO.date())
    return (p.stat().st_size, mv._rows_to_index(archive.load_day(settings, KO.date())))


def test_the_verdict_has_one_shape_whether_or_not_there_was_enough_data(arch):
    """A caller must not have to branch on which keys exist: the thin answer carries the same fields
    as the full one, filled with None."""
    write(arch, steam_rows(), code=55)
    write(arch, [(1440, "ms.1", 2.05), (1440, "ms.X", 3.4), (1440, "ms.2", 4.0)], code=66)
    full = mv.classify(mv.trajectory(arch, 55, as_of=KO)["ms.1"])
    thin = mv.classify(mv.trajectory(arch, 66, as_of=KO)["ms.1"])
    assert set(full) == set(thin)
    assert thin["type"] is None and thin["total_pp"] is None and thin["consistency"] is None


# --------------------------------------------------------------------------- the forward test

def test_the_verdict_is_frozen_once_before_kick_off_and_never_revised(arch):
    """Spec 30. The trajectory is only complete after the match has started, so reclassifying later
    is always possible and always wrong. The freeze happens before, once, and is append-only."""
    import datetime as dt

    from src.nesine import forward

    write(arch, steam_rows())
    m = {**META, "ms": {"1": 1.76, "X": 3.40, "2": 4.87}}
    just_before = KO - dt.timedelta(minutes=10)

    assert forward.freeze_due(arch, [m], now=KO - dt.timedelta(hours=3)) == 0     # too early
    assert forward.freeze_due(arch, [m], now=just_before) == 1
    assert forward.freeze_due(arch, [m], now=just_before) == 0                    # never twice
    assert forward.freeze_due(arch, [m], now=KO + dt.timedelta(minutes=5)) == 0   # too late

    rows = forward.load(arch, "freeze")
    assert len(rows) == 1
    r = rows[0]
    assert r["code"] == 55 and r["minutes_left"] == 10 and r["market"]["ms.1"] == 1.76
    assert r["sel"]["ms.1"]["movement"]["type"] == "STEAM"
    assert r["sel"]["ms.1"]["quality"]["snapshots"] >= 4
    assert "config" in r and r["config"]["movement_min_pp"] > 0    # the thresholds it was judged by


def test_settling_appends_the_result_and_leaves_the_verdict_alone(arch):
    import datetime as dt

    import pandas as pd

    from src.nesine import forward

    write(arch, steam_rows())
    forward.freeze_due(arch, [META], now=KO - dt.timedelta(minutes=10))
    before = forward.store_path(arch).read_text(encoding="utf-8")

    df = pd.DataFrame([{"date": pd.Timestamp(KO.date()), "home_team": "A", "away_team": "B",
                        "fthg": 2, "ftag": 0, "ftr": "H", "htr": "H", "hthg": 1, "htag": 0,
                        "league": "L", "season": "2627", "cons_h": 1.8, "cons_d": 3.5, "cons_a": 4.2}])
    assert forward.settle(arch, df=df, now=KO + dt.timedelta(minutes=30)) == 0        # still playing
    assert forward.settle(arch, df=df, now=KO + dt.timedelta(hours=4)) == 1
    assert forward.settle(arch, df=df, now=KO + dt.timedelta(hours=5)) == 0           # only once

    after = forward.store_path(arch).read_text(encoding="utf-8")
    assert after.startswith(before)                              # the frozen line is untouched
    got = forward.load(arch, "settle")[0]
    assert got["ftr"] == "H" and got["fthg"] == 2


def test_the_forward_summary_refuses_to_quote_a_rate_on_a_handful(arch):
    """Spec 29: STEAM came in at 71 % is a coin landing the same way fourteen times."""
    import datetime as dt

    import pandas as pd

    from src.nesine import forward

    write(arch, steam_rows())
    forward.freeze_due(arch, [META], now=KO - dt.timedelta(minutes=10))
    df = pd.DataFrame([{"date": pd.Timestamp(KO.date()), "home_team": "A", "away_team": "B",
                        "fthg": 2, "ftag": 0, "ftr": "H", "htr": "H", "hthg": 1, "htag": 0,
                        "league": "L", "season": "2627", "cons_h": 1.8, "cons_d": 3.5, "cons_a": 4.2}])
    forward.settle(arch, df=df, now=KO + dt.timedelta(hours=4))

    out = forward.summary(arch)
    assert out["n_frozen"] == 1 and out["n_settled"] == 1
    steam = next(r for r in out["rows"] if r["type"] == "STEAM")
    assert steam["n_settled"] == 1 and steam["enough"] is False
    assert steam["actual"] is None and steam["market"] is None    # a rate on one match is not a rate
    assert out["floors"]["display"] >= 30


def test_the_feature_row_is_none_where_the_archive_cannot_support_it(arch):
    """Spec 27's list, and a zero is never used to stand in for a missing measurement: a movement
    feature defaulted to 0 claims the price held, which is exactly what we do not know."""
    write(arch, [(100, "ms.1", 2.05), (100, "ms.X", 3.4), (100, "ms.2", 4.0),
                 (15, "ms.1", 1.76), (15, "ms.X", 3.4), (15, "ms.2", 5.0)])
    f = mv.features_for(mv.trajectory(arch, 55, as_of=KO)["ms.1"])
    assert set(mv.FEATURES) <= set(f)
    assert f["mv_3h"] is None                      # the 3h window's start was never seen
    assert f["mv_15m"] is not None and f["mv_total_pp"] is not None


def test_the_forward_store_turns_into_a_frame_only_once_matches_are_settled(arch):
    import datetime as dt

    import pandas as pd

    from src.nesine import forward

    write(arch, steam_rows())
    assert forward.to_frame(arch).empty                       # nothing frozen yet
    forward.freeze_due(arch, [META], now=KO - dt.timedelta(minutes=10))
    assert forward.to_frame(arch).empty                       # frozen, but no result yet

    df = pd.DataFrame([{"match_id": "abc123", "date": pd.Timestamp(KO.date()), "home_team": "A",
                        "away_team": "B", "fthg": 2, "ftag": 0, "ftr": "H", "htr": "H", "hthg": 1,
                        "htag": 0, "league": "L", "season": "2627", "cons_h": 1.8, "cons_d": 3.5,
                        "cons_a": 4.2}])
    forward.settle(arch, df=df, now=KO + dt.timedelta(hours=4))
    out = forward.to_frame(arch)
    assert len(out) == 1 and out.iloc[0]["ftr"] == "H"
    assert out.iloc[0]["mv_type"] == "STEAM" and out.iloc[0]["mv_total_pp"] > 0
    assert list(out.columns)[-len(mv.FEATURES):] == list(mv.FEATURES)


def test_settling_records_our_own_match_id_so_the_join_is_possible(arch):
    """It used not to: history.load_history never read the match_id column, so every settled row
    carried an empty id and the forward frame could only ever come back empty."""
    from src.nesine.history import COLS

    assert "match_id" in COLS
