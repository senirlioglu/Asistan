"""The fixture list download: a source that is down must not take the daily job down with it."""

import os
import time

import pytest

from src.data import football_data as fd


def _settings(settings, tmp_path):
    return settings.with_overrides(**{"data.raw_dir": str(tmp_path / "raw")})


def test_stale_cached_fixtures_are_used_when_the_source_fails(settings, tmp_path, monkeypatch):
    s = _settings(settings, tmp_path)
    p = s.raw_dir / "fixtures.csv"
    p.parent.mkdir(parents=True)
    p.write_bytes(b"Div,Date\nE0,20/09/2026\n")
    old = time.time() - 5 * 3600
    os.utime(p, (old, old))                                            # older than max_age_hours: a download is due

    def boom(*a, **k):
        raise RuntimeError("GET failed after 3 attempts: redirect to http://127.0.0.1/")
    monkeypatch.setattr(fd, "_http_get", boom)
    assert fd.download_fixtures(s, force=True) == p                    # even a forced refresh keeps the old file
    assert p.read_bytes().startswith(b"Div,Date")


def test_no_cached_fixtures_still_raises(settings, tmp_path, monkeypatch):
    s = _settings(settings, tmp_path)
    monkeypatch.setattr(fd, "_http_get", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("down")))
    with pytest.raises(RuntimeError):
        fd.download_fixtures(s, force=True)


def test_fresh_download_overwrites_the_cache(settings, tmp_path, monkeypatch):
    s = _settings(settings, tmp_path)
    monkeypatch.setattr(fd, "_http_get", lambda *a, **k: b"Div,Date\nSP1,21/09/2026\n")
    p = fd.download_fixtures(s, force=True)
    assert p.read_bytes() == b"Div,Date\nSP1,21/09/2026\n"
