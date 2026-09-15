"""Hosted entry point (Railway / any container host): one process that

1. bootstraps the data when the container is empty (download -> build -> today, in the background
   so the web port is bound immediately and health checks pass),
2. runs the daily job every day at FO_DAILY_UTC (default 06:30 UTC),
3. serves the Streamlit dashboard on $PORT.

Environment:
    PORT            web port (Railway sets it)
    FO_DAILY_UTC    HH:MM, daily job time in UTC (default 06:30)
    FO_SCORECARD_UTC HH:MM, when yesterday's scorecard (market vs history on played matches) is written (default 05:00 = 08:00 TR)
    FO_DAYS_AHEAD   how many days of fixtures to analyse (default 7)
    FO_ADMIN_KEY    optional; when set the dashboard's "Refresh now" button asks for it
    LOG_LEVEL       default INFO
"""

from __future__ import annotations

import os
import subprocess
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.config import load_settings  # noqa: E402
from src.logging_setup import get_logger, setup_logging  # noqa: E402
from src.pipeline.jobs import needs_bootstrap, run_daily_job, seconds_until  # noqa: E402

log = get_logger("serve")


def _scorecard(settings) -> None:
    try:
        from src.pipeline.scorecard import run_scorecard_job

        run_scorecard_job(settings)
    except Exception as exc:  # noqa: BLE001 - the scorecard is derived data; the daily job must not depend on it
        log.error("scorecard job failed: %s", exc)


def scheduler_loop(settings, hhmm: str, days: int, scorecard_hhmm: str) -> None:
    if needs_bootstrap(settings):
        log.info("no data in container -> bootstrap run")
        full = not (settings.processed_dir / "matches.parquet").exists()
        run_daily_job(settings, days=days, full_download=full)
    jobs = [(hhmm, "daily", lambda: run_daily_job(settings, days=days)), (scorecard_hhmm, "scorecard", lambda: _scorecard(settings))]
    while True:
        waits = [(seconds_until(t), name, fn) for t, name, fn in jobs]
        wait, name, fn = min(waits, key=lambda x: x[0])
        log.info("next job '%s' in %.0f min", name, wait / 60)
        time.sleep(wait)
        fn()
        time.sleep(60)  # never fire twice inside the same minute


def main() -> int:
    setup_logging()
    settings = load_settings()
    hhmm = os.environ.get("FO_DAILY_UTC", "06:30")
    scorecard_hhmm = os.environ.get("FO_SCORECARD_UTC", "05:00")  # 08:00 Turkey time: yesterday's scorecard
    days = int(os.environ.get("FO_DAYS_AHEAD", "7"))
    port = os.environ.get("PORT", "8501")

    threading.Thread(target=scheduler_loop, args=(settings, hhmm, days, scorecard_hhmm), name="fo-scheduler", daemon=True).start()

    if os.environ.get("FO_UI", "web") == "streamlit":  # legacy dashboard, kept for local use
        cmd = [sys.executable, "-m", "streamlit", "run", str(ROOT / "src" / "dashboard" / "app.py"),
               "--server.port", port, "--server.address", "0.0.0.0", "--server.headless", "true",
               "--browser.gatherUsageStats", "false"]
        log.info("starting Streamlit dashboard on port %s", port)
        return subprocess.call(cmd, cwd=str(ROOT))

    import uvicorn

    log.info("starting web app on port %s", port)
    uvicorn.run("src.web.api:app", host="0.0.0.0", port=int(port), log_level="info", access_log=False)
    return 0


if __name__ == "__main__":
    sys.exit(main())
