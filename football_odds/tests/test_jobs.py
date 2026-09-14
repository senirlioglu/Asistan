import datetime as dt
import os
import threading

import pytest

from src.pipeline import jobs


def test_seconds_until_wraps_to_next_day():
    now = dt.datetime(2026, 9, 13, 7, 0, tzinfo=dt.timezone.utc)
    assert jobs.seconds_until("06:30", now) == pytest.approx(23.5 * 3600)
    assert jobs.seconds_until("07:30", now) == pytest.approx(1800)


def test_needs_bootstrap_when_parquet_missing(settings, tmp_path):
    s = settings.with_overrides(**{"data.processed_dir": str(tmp_path / "p"), "data.results_dir": str(tmp_path / "r")})
    assert jobs.needs_bootstrap(s)
    (tmp_path / "p").mkdir()
    (tmp_path / "p" / "matches.parquet").write_bytes(b"x")
    assert jobs.needs_bootstrap(s)  # no predictions for today yet
    (tmp_path / "r").mkdir()
    (tmp_path / "r" / f"{dt.date.today().isoformat()}_predictions.csv").write_text("a")
    assert not jobs.needs_bootstrap(s)


def test_file_lock_blocks_second_run_and_is_released(settings, tmp_path, monkeypatch):
    s = settings.with_overrides(**{"data.results_dir": str(tmp_path / "r")})
    calls = []

    def fake_download(*a, **k):
        calls.append("download")
        # while the job holds the lock a second start must be refused
        assert jobs.start_background(s) is None
        assert jobs.is_running(s)

    monkeypatch.setattr(jobs, "download_all", fake_download)
    monkeypatch.setattr(jobs, "build_processed", lambda st: (__import__("pandas").DataFrame({"a": [1, 2]}), {}))
    monkeypatch.setattr(jobs, "run_today", lambda *a, **k: __import__("pandas").DataFrame({"a": [1]}))
    assert jobs.run_daily_job(s, days=1) is True
    assert calls == ["download"]
    assert not jobs.is_running(s)
    assert not jobs.lock_path(s).exists()
    status = jobs.read_status(s)
    assert status["state"] == "ok" and status["n_fixtures"] == 1 and status["n_history"] == 2


def test_error_is_written_to_status(settings, tmp_path, monkeypatch):
    s = settings.with_overrides(**{"data.results_dir": str(tmp_path / "r")})
    monkeypatch.setattr(jobs, "download_all", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    assert jobs.run_daily_job(s) is True
    st = jobs.read_status(s)
    assert st["state"] == "error" and "boom" in st["message"]
    assert not jobs.lock_path(s).exists()


def test_stale_lock_is_removed(settings, tmp_path, monkeypatch):
    s = settings.with_overrides(**{"data.results_dir": str(tmp_path / "r")})
    (tmp_path / "r").mkdir()
    p = jobs.lock_path(s)
    p.write_text("dead")
    old = dt.datetime.now().timestamp() - 3 * 3600
    os.utime(p, (old, old))
    assert not jobs.is_running(s)
    monkeypatch.setattr(jobs, "download_all", lambda *a, **k: None)
    monkeypatch.setattr(jobs, "build_processed", lambda st: (__import__("pandas").DataFrame({"a": [1]}), {}))
    monkeypatch.setattr(jobs, "run_today", lambda *a, **k: __import__("pandas").DataFrame())
    assert jobs.run_daily_job(s) is True
    assert jobs.read_status(s)["state"] == "ok"
