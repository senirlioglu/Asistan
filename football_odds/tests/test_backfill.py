import datetime as dt

import pandas as pd

from src.pipeline import today as today_mod


def test_backfill_analyses_missing_days_only(settings, history, tmp_path, monkeypatch):
    monkeypatch.setattr(today_mod.ParquetHistoricalProvider, "load", lambda self: history)
    # a day in the synthetic history that has matches; the pool must be strictly earlier
    last = history["date"].max().date()
    day = last - dt.timedelta(days=0)
    n_day = int((history["date"] == pd.Timestamp(day)).sum())
    assert n_day > 0
    done = today_mod.run_backfill(settings, days=1, today=day + dt.timedelta(days=1), out_dir=tmp_path)
    assert done == {day.isoformat(): n_day}
    table = pd.read_csv(tmp_path / f"{day.isoformat()}_predictions.csv")
    assert len(table) == n_day and (table["date"] == day.isoformat()).all()
    # the analogues never include the analysed day itself (no look-ahead)
    an = pd.read_parquet(tmp_path / "analogues" / f"{day.isoformat()}_analogues.parquet")
    assert (pd.to_datetime(an["date"]) < pd.Timestamp(day)).all()
    # second run: file exists -> nothing to do
    assert today_mod.run_backfill(settings, days=1, today=day + dt.timedelta(days=1), out_dir=tmp_path) == {}
    # a day without matches is skipped silently
    assert today_mod.run_backfill(settings, days=1, today=dt.date(2030, 1, 2), out_dir=tmp_path) == {}
