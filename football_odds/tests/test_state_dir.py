import os
from pathlib import Path

from src.config import load_settings


def test_state_dir_redirects_generated_paths(monkeypatch, tmp_path):
    monkeypatch.setenv("FO_STATE_DIR", str(tmp_path))
    s = load_settings()
    assert s.raw_dir == tmp_path / "raw" and s.processed_dir == tmp_path / "processed" and s.results_dir == tmp_path / "results"
    monkeypatch.delenv("FO_STATE_DIR")
    s2 = load_settings()
    assert s2.results_dir == Path(s2.root) / "results"
    assert os.environ.get("FO_STATE_DIR") is None
