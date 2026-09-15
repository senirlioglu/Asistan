"""The intraday fixture re-read: Football-Data fills fixtures.csv in through the day, so a second run
must ADD the matches published since the morning without rewriting what was already shown."""

import datetime as dt
import json

import pandas as pd

from src.pipeline import today as today_mod


def _fixtures(history: pd.DataFrame, day: dt.date, n: int) -> pd.DataFrame:
    """n rows of the synthetic history re-dated to `day`, used as if they were today's fixture list."""
    fx = history.head(n).copy()
    fx["date"] = pd.Timestamp(day)
    return fx.reset_index(drop=True)


def test_second_run_adds_the_new_fixtures_and_keeps_the_old_analysis(settings, history, tmp_path):
    day = history["date"].max().date() + dt.timedelta(days=1)
    pool = history[history["date"] < pd.Timestamp(day)]
    stamp = day.isoformat()

    morning = today_mod.analyse_fixtures(settings, pool, _fixtures(history, day, 2), day, stamp, tmp_path, report=False)
    assert len(morning) == 2
    first_id = morning["match_id"].iloc[0]
    first_edge = round(float(morning["edge_h"].iloc[0]), 3)   # the kept row comes back from the rounded CSV

    # the evening list holds the same two matches (with the odds moved) plus three that were not published yet
    evening = _fixtures(history, day, 5)
    evening.loc[0, ["odds_h", "cons_h"] if "cons_h" in evening.columns else ["odds_h"]] = 1.01
    table = today_mod.analyse_fixtures(settings, pool, evening, day, stamp, tmp_path, report=False, merge=True)

    assert len(table) == 5                                    # the three new ones were added
    assert table["match_id"].is_unique
    row = table[table["match_id"] == first_id].iloc[0]
    assert float(row["edge_h"]) == first_edge                 # a match already shown keeps its analysis

    written = pd.read_csv(tmp_path / f"{stamp}_predictions.csv")
    assert len(written) == 5 and list(written.columns)[:4] == list(table.columns)[:4]
    details = json.loads((tmp_path / f"{stamp}_details.json").read_text())["matches"]
    assert set(details) == set(table["match_id"])             # every match on the page has its detail sheet
    an = pd.read_parquet(tmp_path / "analogues" / f"{stamp}_analogues.parquet")
    assert set(an["fixture_id"]) == set(table["match_id"]) and an["fixture_id"].nunique() == 5


def test_a_fixture_that_left_the_list_is_not_dropped(settings, history, tmp_path):
    """After kick-off Football-Data removes the match from fixtures.csv; the day's file must keep it."""
    day = history["date"].max().date() + dt.timedelta(days=1)
    pool = history[history["date"] < pd.Timestamp(day)]
    stamp = day.isoformat()
    today_mod.analyse_fixtures(settings, pool, _fixtures(history, day, 3), day, stamp, tmp_path, report=False)
    later = today_mod.analyse_fixtures(settings, pool, _fixtures(history, day, 3).tail(1), day, stamp, tmp_path,
                                       report=False, merge=True)
    assert len(later) == 3
    # ... and with merge off the same call would replace the file, which is why the daily job owns that path
    assert len(today_mod.analyse_fixtures(settings, pool, _fixtures(history, day, 3).tail(1), day, stamp, tmp_path,
                                          report=False)) == 1
