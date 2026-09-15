"""Background job runner for the hosted deployment.

One job = refresh the current season's Football-Data files -> rebuild the processed database ->
analyse the upcoming fixtures. It is triggered by the daily scheduler in `serve.py`, by the
"Refresh now" button in the dashboard, and once at boot when the container has no data yet
(hosted filesystems are ephemeral). Status is written to results/job_status.json so the
dashboard can show it; a process-wide lock prevents overlapping runs.
"""

from __future__ import annotations

import datetime as dt
import json
import threading
import traceback

from ..config import Settings, current_season_code
from ..data.build import build_processed
from ..data.football_data import download_all
from ..logging_setup import get_logger
from .today import run_today

log = get_logger("pipeline.jobs")
_LOCK = threading.Lock()


def status_path(settings: Settings):
    return settings.results_dir / "job_status.json"


def read_status(settings: Settings) -> dict:
    p = status_path(settings)
    if not p.exists():
        return {"state": "never", "message": "no run yet"}
    try:
        return json.loads(p.read_text())
    except json.JSONDecodeError:
        return {"state": "unknown", "message": "unreadable status file"}


def _write(settings: Settings, state: str, message: str, **extra) -> None:
    settings.results_dir.mkdir(parents=True, exist_ok=True)
    payload = {"state": state, "message": message, "updated_at": dt.datetime.now(dt.timezone.utc).isoformat(), **extra}
    status_path(settings).write_text(json.dumps(payload, indent=2, default=str))


LOCK_STALE_S = 2 * 3600  # a lock older than this belongs to a crashed run


def lock_path(settings: Settings):
    return settings.results_dir / ".job.lock"


def _acquire_file_lock(settings: Settings) -> bool:
    """Cross-process lock: the scheduler (serve.py) and the dashboard (Streamlit subprocess) share it."""
    import os
    import time

    settings.results_dir.mkdir(parents=True, exist_ok=True)
    p = lock_path(settings)
    try:
        if p.exists() and time.time() - p.stat().st_mtime > LOCK_STALE_S:
            p.unlink()
        fd = os.open(str(p), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        return False
    with os.fdopen(fd, "w") as fh:
        fh.write(f"{os.getpid()} {dt.datetime.now(dt.timezone.utc).isoformat()}\n")
    return True


def _release_file_lock(settings: Settings) -> None:
    try:
        lock_path(settings).unlink()
    except FileNotFoundError:
        pass


def is_running(settings: Settings | None = None) -> bool:
    if _LOCK.locked():
        return True
    if settings is not None:
        import time
        p = lock_path(settings)
        return p.exists() and time.time() - p.stat().st_mtime <= LOCK_STALE_S
    return False


def run_daily_job(settings: Settings, days: int = 7, full_download: bool = False) -> bool:
    """Download -> build -> today. Returns False when another run is already in progress."""
    if not _LOCK.acquire(blocking=False):
        log.info("job already running in this process, skipping")
        return False
    if not _acquire_file_lock(settings):
        _LOCK.release()
        log.info("job already running in another process, skipping")
        return False
    started = dt.datetime.now(dt.timezone.utc)
    try:
        _write(settings, "running", "downloading Football-Data files", started_at=started.isoformat())
        seasons = None if full_download else [current_season_code()]
        download_all(settings, seasons=seasons)
        _write(settings, "running", "building processed database", started_at=started.isoformat())
        df, _ = build_processed(settings)
        _write(settings, "running", "analysing upcoming fixtures", started_at=started.isoformat())
        table = run_today(settings, date=dt.date.today(), days=days, refresh=True)
        try:  # the last week: any day without a prediction file gets analysed after the fact (results come from the database)
            _write(settings, "running", "analysing last week's matches", started_at=started.isoformat())
            from .today import run_backfill
            run_backfill(settings, days=7)
        except Exception as exc:  # noqa: BLE001 - derived data; never fails the daily job
            log.warning("backfill skipped: %s", exc)
        secs = (dt.datetime.now(dt.timezone.utc) - started).total_seconds()
        _write(settings, "ok", f"{len(table)} fixtures analysed, {len(df)} historical matches", started_at=started.isoformat(),
               finished_at=dt.datetime.now(dt.timezone.utc).isoformat(), duration_s=round(secs), n_fixtures=int(len(table)),
               n_history=int(len(df)))
        log.info("daily job finished in %.0fs (%d fixtures)", secs, len(table))
        return True
    except Exception as exc:  # noqa: BLE001 - the status file is the error channel for the dashboard
        log.error("daily job failed: %s\n%s", exc, traceback.format_exc())
        _write(settings, "error", f"{type(exc).__name__}: {exc}", started_at=started.isoformat())
        return True
    finally:
        _release_file_lock(settings)
        _LOCK.release()


def start_background(settings: Settings, days: int = 7, full_download: bool = False) -> threading.Thread | None:
    if is_running(settings):
        return None
    t = threading.Thread(target=run_daily_job, args=(settings, days, full_download), name="fo-daily-job", daemon=True)
    t.start()
    return t


def needs_bootstrap(settings: Settings) -> bool:
    processed = settings.processed_dir / "matches.parquet"
    if not processed.exists():
        return True
    today = dt.date.today().isoformat()
    return not (settings.results_dir / f"{today}_predictions.csv").exists()


def seconds_until(hhmm_utc: str, now: dt.datetime | None = None) -> float:
    """Seconds until the next occurrence of HH:MM UTC."""
    now = now or dt.datetime.now(dt.timezone.utc)
    hour, minute = (int(x) for x in hhmm_utc.split(":"))
    target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if target <= now:
        target += dt.timedelta(days=1)
    return (target - now).total_seconds()
