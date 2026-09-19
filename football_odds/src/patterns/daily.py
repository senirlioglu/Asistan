"""Günün raporu — the day's matches through every main target, compiled once and kept on the volume.

Mode 2 of the lab scans one target at a time, ten minutes each, and the result lived in memory until
the next deploy. On 19 Sep the seven scans of the day had to be run by hand and stitched together by
hand. This module does that stitching: it runs the main targets in turn (they share the lab's one
scan pool, so the site stays responsive), then compiles what the pattern engines found per match,
grouped by direction, with the biggest layer differences and the notebook notes that speak about a
result. The report is written to results/lab_daily/<date>.json and rebuilt when it is missing or a
half day old; the page reads the file.
"""
from __future__ import annotations

import datetime as dt
import json
import threading
import traceback
from typing import Callable

from ..config import Settings
from ..logging_setup import get_logger
from . import target as tg

log = get_logger("patterns.daily")

# the targets a day is scanned for, in the order they run (the ones people ask about first)
REPORT_TARGETS = ["ft_1", "ft_X", "ft_2", "over25", "btts", "htft_1/2", "htft_2/1", "ht_1", "ht_X", "ht_2"]
REBUILD_AFTER_H = 12          # a report older than this is rebuilt by the hourly job
PER_DIRECTION = 30            # at most this many matches per (target, direction) in the digest
# the notebook notes that name a result (the odds-structure ones fire on a third of the bulletin every day)
RESULT_NOTES = {"n1", "n2", "n4", "n5", "n6", "n7", "n10", "n11", "n14", "n16", "n19"}

_RUN: dict = {"date": None, "state": "idle", "step": None, "step_no": 0, "steps": 0, "done": 0, "total": 0,
              "started_at": None, "finished_at": None, "error": None}
_RUN_LOCK = threading.Lock()

Collector = Callable[[str], tuple[list[dict], dict]]     # date -> (matches, nesine_by_id), as mode 2 assembles them


def reports_dir(settings: Settings):
    return settings.results_dir / "lab_daily"


def report_path(settings: Settings, date: str):
    return reports_dir(settings) / f"{date}.json"


def load_report(settings: Settings, date: str) -> dict | None:
    p = report_path(settings, date)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def report_dates(settings: Settings) -> list[str]:
    d = reports_dir(settings)
    if not d.exists():
        return []
    return sorted(p.stem for p in d.glob("*.json") if len(p.stem) == 10)


def status(settings: Settings, date: str) -> dict:
    """What the page shows above the report: running (which target, how far), or when it was made."""
    with _RUN_LOCK:
        run = dict(_RUN)
    rep = load_report(settings, date)
    out = {"date": date, "running": run["state"] == "running" and run["date"] == date,
           "run": run if run["date"] == date else None,
           "generated_at": rep.get("generated_at") if rep else None, "exists": rep is not None,
           "dates": report_dates(settings)}
    return out


def is_running() -> bool:
    with _RUN_LOCK:
        return _RUN["state"] == "running"


def is_fresh(settings: Settings, date: str, max_age_h: float | None = None) -> bool:
    max_age_h = REBUILD_AFTER_H if max_age_h is None else max_age_h
    rep = load_report(settings, date)
    if not rep or not rep.get("generated_at"):
        return False
    try:
        made = dt.datetime.fromisoformat(rep["generated_at"])
    except ValueError:
        return False
    return (dt.datetime.now(dt.timezone.utc) - made).total_seconds() < max_age_h * 3600


# --------------------------------------------------------------------------- the digest

def _direction(row: dict) -> str:
    """more / less / mixed: what the engines (or, failing them, the layers' total) say about this target."""
    pats = row.get("patterns") or []
    if pats:
        signs = {1 if (f.get("edge") or 0) > 0 else -1 for f in pats if f.get("edge")}
        if len(signs) == 1:
            return "more" if 1 in signs else "less"
        return "mixed"
    d = row.get("difference")
    return "more" if (d or 0) > 0 else "less"


def _entry(row: dict, target: str) -> dict:
    t = tg.TARGETS.get(target, {})
    nes = row.get("nesine") or {}
    return {"id": row["id"], "home": row["home"], "away": row["away"], "time": row.get("time"), "league": row.get("league"),
            "league_name": row.get("league_name"), "target": target, "target_label": t.get("label", target),
            "group": t.get("group"), "direction": _direction(row),
            "market": row.get("market"), "estimate": row.get("estimate"), "difference": row.get("difference"),
            "difference_ci": row.get("difference_ci"), "evidence": row.get("evidence"), "similarity": row.get("similarity"),
            "patterns": row.get("patterns") or [], "layers": row.get("layers") or [],
            "nesine": {k: nes.get(k) for k in ("code", "ms", "iy", "iyms", "o25") if nes.get(k) is not None} or None,
            "relevance": row.get("relevance") or {}}


def _interesting(row: dict) -> bool:
    ev = (row.get("evidence") or {}).get("key")
    return bool(row.get("patterns")) or ev not in (None, "none", "thin")


def compile_report(date: str, scans: dict[str, dict], state_stamp: float | None = None) -> dict:
    """The digest of one day's finished scans, one per target (a job dict as `start_day_scan` leaves it)."""
    targets_out = []
    top: list[dict] = []
    all_rows: dict[str, dict] = {}
    for key in REPORT_TARGETS:
        job = scans.get(key)
        if not job:
            continue
        t = tg.TARGETS.get(key, {})
        rows = job.get("rows") or []
        for r in rows:
            all_rows.setdefault(r["id"], r)
        entries = [_entry(r, key) for r in rows if _interesting(r)]
        entries.sort(key=lambda e: -(e["relevance"].get("score") or 0))
        buckets = {"more": [], "less": [], "mixed": []}
        for e in entries:
            buckets[e["direction"]].append(e)
        targets_out.append({"key": key, "label": t.get("label", key), "group": t.get("group"), "group_label": t.get("group_label"),
                            "explain": t.get("explain"), "n_rows": len(rows), "n_errors": job.get("errors", 0),
                            "n_patterns": sum(1 for r in rows if r.get("patterns")),
                            "n_clear": sum(1 for r in rows if (r.get("difference_ci") or [None])[0] is not None
                                           and (r["difference_ci"][0] > 0 or r["difference_ci"][1] < 0)),
                            "more": buckets["more"][:PER_DIRECTION], "less": buckets["less"][:PER_DIRECTION],
                            "mixed": buckets["mixed"][:PER_DIRECTION], "state_stamp": job.get("state_stamp"),
                            "finished_at": job.get("finished_at")})
        top.extend(e for e in entries if e["patterns"])
    top.sort(key=lambda e: -(e["relevance"].get("score") or 0))
    # the notebook: the notes that name a result, match by match; and the matches that collect the most notes
    by_note: dict[str, dict] = {}
    most = []
    for r in all_rows.values():
        notes = r.get("notes") or []
        if notes:
            most.append({"id": r["id"], "home": r["home"], "away": r["away"], "time": r.get("time"), "league_name": r.get("league_name"),
                         "nesine": ((r.get("nesine") or {}).get("ms")), "n": len(notes), "nos": sorted({n.get("no") for n in notes if n.get("no")})})
        for n in notes:
            if str(n.get("id")) not in RESULT_NOTES:
                continue
            b = by_note.setdefault(str(n["id"]), {"id": n["id"], "no": n.get("no"), "title": n.get("title"), "expect": n.get("expect"), "matches": []})
            b["matches"].append({"id": r["id"], "home": r["home"], "away": r["away"], "time": r.get("time"), "league_name": r.get("league_name"),
                                 "nesine": ((r.get("nesine") or {}).get("ms")), "evidence": n.get("evidence") or {}})
    result_notes = sorted(by_note.values(), key=lambda b: (b["no"] or 0))
    for b in result_notes:
        b["matches"].sort(key=lambda m: (m.get("time") or "", m["home"]))
    most.sort(key=lambda m: (-m["n"], m.get("time") or ""))
    return {"date": date, "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
            "state_stamp": state_stamp, "n_matches": len(all_rows),
            "n_linked": sum(1 for r in all_rows.values() if r.get("nesine")),
            "targets": targets_out, "top": top[:12],
            "notes": {"result_notes": result_notes, "most": most[:10],
                      "n_with_notes": sum(1 for r in all_rows.values() if r.get("notes"))},
            "note": ("Hiçbir satır kazananı söylemez. Her satır, o maça benzeyen eski maçlarda o sonucun oranların dediğinden "
                     "daha çok mu, daha az mı geldiğini gösterir; bulguların hepsi ilk kez görülen desenlerdir.")}


# --------------------------------------------------------------------------- building

def build_report(settings: Settings, date: str, collect: Collector, targets: list[str] | None = None) -> dict:
    """Scan the date for every report target in turn, compile, write. Blocks; run it in a thread."""
    targets = targets or REPORT_TARGETS
    matches, nesine_by_id = collect(date)
    with _RUN_LOCK:
        _RUN.update(date=date, state="running", step=None, step_no=0, steps=len(targets), done=0, total=len(matches),
                    started_at=dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"), finished_at=None, error=None)
    scans: dict[str, dict] = {}
    stamp = None
    for i, key in enumerate(targets, 1):
        with _RUN_LOCK:
            _RUN.update(step=key, step_no=i, done=0)
        job = tg.start_day_scan(settings, date, key, matches, nesine_by_id)
        while job["state"] == "running":
            with _RUN_LOCK:
                _RUN["done"] = job["done"]
            tg.wait_day_scan(job, timeout_s=2.0)
        scans[key] = job
        stamp = job.get("state_stamp", stamp)
    report = compile_report(date, scans, state_stamp=stamp)
    p = report_path(settings, date)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(report, ensure_ascii=False, default=tg._json_default), encoding="utf-8")
    tmp.replace(p)
    with _RUN_LOCK:
        _RUN.update(state="done", step=None, finished_at=dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"))
    log.info("günün raporu %s: %d maç, %d hedef -> %s", date, report["n_matches"], len(scans), p)
    return report


def start_build(settings: Settings, date: str, collect: Collector, targets: list[str] | None = None) -> dict:
    """Build in the background; refused (with the current run's status) while one is running."""
    with _RUN_LOCK:
        if _RUN["state"] == "running":
            return {"started": False, "reason": "running", "run": dict(_RUN)}
        _RUN.update(date=date, state="running", step=None, step_no=0, steps=len(targets or REPORT_TARGETS), done=0, total=0,
                    started_at=dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"), finished_at=None, error=None)

    def work():
        try:
            build_report(settings, date, collect, targets)
        except Exception as exc:  # noqa: BLE001 - the page shows the error; the next hourly job retries
            log.error("günün raporu %s failed: %s\n%s", date, exc, traceback.format_exc())
            with _RUN_LOCK:
                _RUN.update(state="error", error=f"{type(exc).__name__}: {exc}",
                            finished_at=dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"))

    threading.Thread(target=work, name=f"lab-daily-{date}", daemon=True).start()
    with _RUN_LOCK:
        return {"started": True, "run": dict(_RUN)}


def today_tr() -> str:
    from zoneinfo import ZoneInfo

    return dt.datetime.now(ZoneInfo("Europe/Istanbul")).date().isoformat()


def maybe_schedule(settings: Settings, collect: Collector, date: str | None = None) -> bool:
    """Called by the hourly job after the state table is rebuilt: start today's report when there is
    none yet or the one there is half a day old. Never blocks the job. Returns True when started."""
    import os

    date = date or today_tr()
    if os.environ.get("FO_DAILY_REPORT", "1").strip().lower() in ("0", "false", "no"):
        return False
    if is_running() or is_fresh(settings, date):
        return False
    from . import service

    if service.frame(settings) is None:          # nothing to scan yet (first boot)
        return False
    out = start_build(settings, date, collect)
    return bool(out.get("started"))
