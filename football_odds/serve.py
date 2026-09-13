"""Hosted entry point (Railway / any container host): one process that

1. bootstraps the data when the container is empty (download -> build -> today, in the background
   so the web port is bound immediately and health checks pass),
2. runs the daily job every day at FO_DAILY_UTC (default 06:30 UTC),
3. serves the Streamlit dashboard on $PORT.

Environment:
    PORT            web port (Railway sets it)
    FO_DAILY_UTC    HH:MM, daily job time in UTC (default 06:30)
    FO_DAYS_AHEAD   how many days of fixtures to analyse (default 2)
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


def scheduler_loop(settings, hhmm: str, days: int) -> None:
    if needs_bootstrap(settings):
        log.info("no data in container -> bootstrap run")
        full = not (settings.processed_dir / "matches.parquet").exists()
        run_daily_job(settings, days=days, full_download=full)
    while True:
        wait = seconds_until(hhmm)
        log.info("next daily job in %.0f min (%s UTC)", wait / 60, hhmm)
        time.sleep(wait)
        run_daily_job(settings, days=days)
        time.sleep(60)  # never fire twice inside the same minute


def main() -> int:
    setup_logging()
    settings = load_settings()
    hhmm = os.environ.get("FO_DAILY_UTC", "06:30")
    days = int(os.environ.get("FO_DAYS_AHEAD", "2"))
    port = os.environ.get("PORT", "8501")

    threading.Thread(target=scheduler_loop, args=(settings, hhmm, days), name="fo-scheduler", daemon=True).start()

    cmd = [sys.executable, "-m", "streamlit", "run", str(ROOT / "src" / "dashboard" / "app.py"),
           "--server.port", port, "--server.address", "0.0.0.0", "--server.headless", "true",
           "--browser.gatherUsageStats", "false"]
    log.info("starting dashboard on port %s", port)
    return subprocess.call(cmd, cwd=str(ROOT))


if __name__ == "__main__":
    sys.exit(main())
