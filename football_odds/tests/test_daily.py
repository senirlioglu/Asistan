"""Günün raporu: the day's targets in turn, compiled, kept on the volume; scans share one pool and survive a restart."""
import json
import time

import pytest

from src.patterns import daily, target as tg


def _row(mid, home, away, diff, ci, patterns=(), notes=(), evidence="disc", nesine=None):
    return {"id": mid, "home": home, "away": away, "league": "E0", "league_name": "İngiltere · Premier Lig", "date": "2026-09-19",
            "time": "17:00", "nesine": nesine, "notes": list(notes), "patterns": list(patterns), "patterns_scanned": 6, "patterns_thin": 2,
            "market": {"p": 50.0, "odds": 1.9, "source": "nesine"}, "estimate": {"p": 50.0 + diff, "ci": [40, 60], "basis": "x"},
            "difference": diff, "difference_ci": ci, "similarity": 80.0,
            "evidence": {"key": evidence, "label": "KEŞİF" if evidence == "disc" else "FARK YOK", "why": "w"},
            "n_layers": 3, "layers": [{"key": "similar", "n": 3000, "edge": diff, "evidence": evidence}], "relevance": {"score": abs(diff), "z": 2.0, "quality": 0.8, "tested": False}}


def _job(target, rows):
    return {"date": "2026-09-19", "target": target, "state": "done", "total": len(rows), "done": len(rows), "rows": rows, "errors": 0,
            "started_at": "t0", "finished_at": "t1", "note": tg.RELEVANCE_NOTE, "state_stamp": 123.0, "stale": False}


def test_compile_groups_matches_by_what_the_engines_say():
    """A match whose engine patterns all point up is 'more', all down 'less', both 'mixed'; a match with no
    pattern falls back to the sign of the layers' total; a match with neither is left out."""
    pat = lambda edge: {"source_tr": "Form deseni · tüm takımlar", "side": "home", "detail": "form WWWWD", "n": 500, "actual": 60.0 + edge, "market": 60.0, "edge": edge, "evidence_tr": "KEŞİF"}
    rows = [_row("a", "Arsenal", "Everton", 3.0, [1.5, 4.5], patterns=[pat(5.0)]),
            _row("b", "Bologna", "Torino", -2.0, [-3.5, -0.5], patterns=[pat(-4.0), pat(-3.0)]),
            _row("c", "Celta", "Sevilla", 0.5, [-1.0, 2.0], patterns=[pat(4.0), pat(-3.0)]),
            _row("d", "Dundee", "Hearts", -1.5, [-2.8, -0.2]),
            _row("e", "Elche", "Getafe", 0.1, [-1.0, 1.2], evidence="none")]
    rep = daily.compile_report("2026-09-19", {"ft_1": _job("ft_1", rows)}, state_stamp=123.0)
    t = rep["targets"][0]
    assert t["key"] == "ft_1" and t["label"] == "1" and t["group"] == "ms" and t["n_rows"] == 5 and t["n_patterns"] == 3 and t["n_clear"] == 3
    assert [e["id"] for e in t["more"]] == ["a"] and [e["id"] for e in t["less"]] == ["b", "d"] and [e["id"] for e in t["mixed"]] == ["c"]
    assert rep["top"][0]["id"] == "a" and all(e["patterns"] for e in rep["top"])      # the engines' finds lead
    assert rep["n_matches"] == 5 and rep["generated_at"] and rep["state_stamp"] == 123.0


def test_compile_keeps_the_result_notes_and_the_most_noted_matches():
    n2 = {"id": "n2", "no": 2, "title": "Ters çevirenin 7. maçı", "expect": "1/2 veya 2/1", "evidence": {"Everton 7 maç önce": "İY H / MS A"}, "related": False}
    n12 = {"id": "n12", "no": 12, "title": "6+ gol", "expect": "…", "evidence": {}, "related": False}
    n6 = {"id": "n6", "no": 6, "title": "1/2 veya 2/1 oranı 18'in altında", "expect": "mutlaka", "evidence": {"İY/MS 2/1": 15.6}, "related": True}
    nes = {"code": 1, "ms": {"1": 1.24, "X": 5.2, "2": 5.5}}
    rows = [_row("a", "Arsenal", "Everton", 1.0, [0.2, 1.8], notes=[n2, n12], nesine=nes),
            _row("m", "Molde", "Aalesund", 1.0, [0.2, 1.8], notes=[n6, n12, n2], nesine=nes)]
    rep = daily.compile_report("2026-09-19", {"ft_1": _job("ft_1", rows), "htft_2/1": _job("htft_2/1", rows)})
    notes = rep["notes"]
    assert [b["no"] for b in notes["result_notes"]] == [2, 6]                 # note 12 is an odds-structure note
    assert {m["id"] for m in notes["result_notes"][0]["matches"]} == {"a", "m"}
    assert notes["most"][0]["id"] == "m" and notes["most"][0]["n"] == 3 and notes["most"][0]["nos"] == [2, 6, 12]
    assert notes["n_with_notes"] == 2 and rep["n_linked"] == 2
    # the same match is counted once even though two targets scanned it
    assert rep["n_matches"] == 2


def test_a_finished_scan_is_written_to_the_volume_and_read_back_after_a_restart(settings, tmp_path, monkeypatch):
    s = settings.with_overrides(**{"data.results_dir": str(tmp_path / "r"), "data.processed_dir": str(tmp_path / "p")})
    (tmp_path / "p").mkdir()
    monkeypatch.setattr(tg, "analyse", lambda *a, **k: {"market": {"p": 50.0}, "estimate": None, "difference": 1.0, "difference_ci": [0.2, 1.8],
                                                          "evidence": {"key": "disc", "label": "KEŞİF"}, "layers": [], "combined": {"edge": 1.0, "se": 0.5, "n_layers": 1}})
    monkeypatch.setattr(tg, "target_patterns", lambda *a, **k: {"found": [], "scanned": 0, "thin": 0})
    tg._JOBS.clear()
    matches = [{"id": f"m{i}", "home": f"H{i}", "away": f"A{i}", "league": "E0", "date": "2026-09-19", "time": "17:00"} for i in range(3)]
    job = tg.start_day_scan(s, "2026-09-19", "htft_1/2", matches)
    tg.wait_day_scan(job, timeout_s=20, poll_s=0.05)
    assert job["state"] == "done" and len(job["rows"]) == 3
    p = tg._scan_path(s, "2026-09-19", "htft_1/2")
    assert p.name == "2026-09-19__htft_1-2.json" and json.loads(p.read_text(encoding="utf-8"))["done"] == 3
    tg._JOBS.clear()                                                              # a deploy
    back = tg.day_scan_status(s, "2026-09-19", "htft_1/2")
    assert back is not None and back["state"] == "done" and len(back["rows"]) == 3 and back["stale"] is False
    assert tg.day_scan_status(s, "2026-09-19", "ft_X") is None
    # the state table was rebuilt since: the saved scan still answers, flagged stale
    from src.patterns import state as st_mod

    tg._JOBS.clear()
    sp = st_mod.state_path(s); sp.parent.mkdir(parents=True, exist_ok=True); sp.write_bytes(b"x")
    assert tg.day_scan_status(s, "2026-09-19", "htft_1/2")["stale"] is True


def test_scans_share_one_pool(settings, tmp_path, monkeypatch):
    """Two scans started together never run more than SCAN_WORKERS matches at once between them."""
    import threading

    s = settings.with_overrides(**{"data.results_dir": str(tmp_path / "r"), "data.processed_dir": str(tmp_path / "p")})
    (tmp_path / "p").mkdir()
    live, peak, lock = [0], [0], threading.Lock()

    def slow(*a, **k):
        with lock:
            live[0] += 1; peak[0] = max(peak[0], live[0])
        time.sleep(0.05)
        with lock:
            live[0] -= 1
        return {"market": {"p": 50.0}, "estimate": None, "difference": 0.0, "difference_ci": [-1, 1], "evidence": {"key": "none", "label": "FARK YOK"},
                "layers": [], "combined": {"edge": 0.0, "se": 0.5, "n_layers": 1}}

    monkeypatch.setattr(tg, "analyse", slow)
    monkeypatch.setattr(tg, "target_patterns", lambda *a, **k: {"found": [], "scanned": 0, "thin": 0})
    tg._JOBS.clear()
    matches = [{"id": f"m{i}", "home": "H", "away": "A", "league": "E0", "date": "2026-09-19", "time": ""} for i in range(12)]
    jobs = [tg.start_day_scan(s, "2026-09-19", t, matches) for t in ("ft_1", "ft_X", "ft_2")]
    for j in jobs:
        tg.wait_day_scan(j, timeout_s=30, poll_s=0.05)
    assert all(j["state"] == "done" and j["done"] == 12 for j in jobs)
    assert peak[0] <= tg.SCAN_WORKERS


def test_build_report_runs_the_targets_in_turn_and_the_hourly_job_only_rebuilds_a_stale_one(settings, tmp_path, monkeypatch):
    s = settings.with_overrides(**{"data.results_dir": str(tmp_path / "r"), "data.processed_dir": str(tmp_path / "p")})
    (tmp_path / "p").mkdir()
    monkeypatch.setattr(tg, "analyse", lambda *a, **k: {"market": {"p": 50.0}, "estimate": {"p": 53.0, "ci": [45, 60], "basis": "x"}, "difference": 3.0,
                                                          "difference_ci": [1.0, 5.0], "evidence": {"key": "disc", "label": "KEŞİF", "why": "w"}, "layers": [],
                                                          "combined": {"edge": 3.0, "se": 1.0, "n_layers": 1}})
    monkeypatch.setattr(tg, "target_patterns", lambda *a, **k: {"found": [], "scanned": 0, "thin": 0})
    tg._JOBS.clear()
    matches = [{"id": "m1", "home": "H", "away": "A", "league": "E0", "league_name": "x", "date": "2026-09-19", "time": "17:00"}]
    collect = lambda date: (matches, {})
    rep = daily.build_report(s, "2026-09-19", collect, targets=["ft_1", "over25"])
    assert [t["key"] for t in rep["targets"]] == ["ft_1", "over25"] and rep["targets"][0]["more"][0]["id"] == "m1"
    assert daily.load_report(s, "2026-09-19")["n_matches"] == 1 and daily.report_dates(s) == ["2026-09-19"]
    st = daily.status(s, "2026-09-19")
    assert st["exists"] and not st["running"] and st["generated_at"]
    # fresh: the hourly job leaves it; stale: it starts one (in the background)
    monkeypatch.setattr(daily, "REPORT_TARGETS", ["ft_1"])
    monkeypatch.setattr("src.patterns.service.frame", lambda *a, **k: object())
    assert daily.maybe_schedule(s, collect, date="2026-09-19") is False
    monkeypatch.setattr(daily, "REBUILD_AFTER_H", 0)
    assert daily.maybe_schedule(s, collect, date="2026-09-19") is True
    for _ in range(100):
        if not daily.is_running():
            break
        time.sleep(0.05)
    assert not daily.is_running() and daily.status(s, "2026-09-19")["run"]["state"] == "done"
    monkeypatch.setenv("FO_DAILY_REPORT", "0")
    assert daily.maybe_schedule(s, collect, date="2026-09-19") is False
