"""Command-line entry point.

    python -m src.cli download            # fetch/refresh Football-Data CSVs into data/raw
    python -m src.cli audit               # PHASE 1 column/market availability audit
    python -m src.cli build               # processed Parquet database + data quality report
    python -m src.cli state               # match state table (form, goals, table, TSI) next to it
    python -m src.cli backtest            # walk-forward backtest, model comparison, ROI, buckets
    python -m src.cli today               # analyse upcoming fixtures -> results/YYYY-MM-DD_predictions.csv
    python -m src.cli dashboard           # launch the Streamlit dashboard
"""

from __future__ import annotations

import argparse
import datetime as dt
import sys

from .config import load_settings
from .logging_setup import setup_logging


def _parse_list(value: str | None) -> list[str] | None:
    if not value:
        return None
    return [v.strip() for v in value.split(",") if v.strip()]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="football-odds", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--config", help="path to settings.yaml", default=None)
    parser.add_argument("--log-level", default=None)
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("download", help="download / refresh raw Football-Data CSVs")
    p.add_argument("--seasons", help="comma separated season codes (default: config)")
    p.add_argument("--leagues", help="comma separated league codes (default: config)")
    p.add_argument("--force", action="store_true")

    sub.add_parser("audit", help="column availability audit (reads cached raw files)")

    p = sub.add_parser("build", help="build processed parquet database")
    p.add_argument("--seasons")
    p.add_argument("--leagues")

    sub.add_parser("state", help="build the match state table (pre-match form / goals / table / TSI)")

    p = sub.add_parser("backtest", help="walk-forward backtest + model comparison")
    p.add_argument("--quick", action="store_true", help="smaller parameter grid (development)")
    p.add_argument("--leagues", help="restrict to these leagues (default: config)")
    p.add_argument("--reuse-validation", action="store_true", help="reuse results/backtest/validation_grid.csv instead of recomputing stage 1")

    sub.add_parser("backtest-calibration", help="walk-forward backtest of the market re-calibration models (fast)")

    p = sub.add_parser("today", help="analyse upcoming fixtures")
    p.add_argument("--date", help="YYYY-MM-DD (default: today)")
    p.add_argument("--days", type=int, default=1, help="how many days ahead to include (default 1 = the given day only)")
    p.add_argument("--provider", help="football_data_fixtures | the_odds_api")
    p.add_argument("--refresh", action="store_true", help="force re-download of fixtures")
    p.add_argument("--update", action="store_true", help="refresh the current season's results and rebuild the database first")

    p = sub.add_parser("backfill", help="analyse last week's played matches that have no prediction file (as of their own day)")
    p.add_argument("--days", type=int, default=7)
    p.add_argument("--force", action="store_true", help="re-analyse even when a file exists")

    sub.add_parser("dashboard", help="run the legacy Streamlit dashboard")
    p = sub.add_parser("web", help="run the web app (FastAPI + HTML frontend) with the daily scheduler")
    p.add_argument("--port", type=int, default=8000)

    args = parser.parse_args(argv)
    log = setup_logging(args.log_level)
    settings = load_settings(args.config)

    if args.command == "download":
        from .data.football_data import download_all
        results = download_all(settings, _parse_list(args.seasons), _parse_list(args.leagues), force=args.force)
        failed = [r for r in results if r.status in ("failed", "empty")]
        for r in failed:
            log.warning("missing %s/%s: %s", r.season, r.league, r.error)
        return 0

    if args.command == "audit":
        from .data.audit import run_audit
        run_audit(settings)
        return 0

    if args.command == "build":
        from .data.build import build_processed
        df, report = build_processed(settings, _parse_list(args.seasons), _parse_list(args.leagues))
        log.info("built %d matches; missing 1X2 %.2f%%; duplicates %d", len(df), report["missing_1x2_odds_pct"], report["duplicate_matches"])
        return 0

    if args.command == "state":
        from .patterns.state import build, state_path
        out = build(settings)
        log.info("wrote %s: %d matches, %d columns", state_path(settings), len(out), len(out.columns))
        return 0

    if args.command == "backtest":
        from .backtest.run import run_full_backtest
        run_full_backtest(settings, quick=args.quick, leagues=_parse_list(args.leagues), reuse_validation=args.reuse_validation)
        return 0

    if args.command == "backtest-calibration":
        from .backtest.calibration_model import run_calibration_backtest
        run_calibration_backtest(settings)
        return 0

    if args.command == "today":
        from .pipeline.today import run_today
        date = dt.date.fromisoformat(args.date) if args.date else dt.date.today()
        run_today(settings, date=date, days=args.days, provider_name=args.provider, refresh=args.refresh, update=args.update)
        return 0

    if args.command == "backfill":
        from .pipeline.today import run_backfill
        done = run_backfill(settings, days=args.days, force=args.force)
        log.info("backfill: %s", done or "nothing to do")
        return 0

    if args.command == "dashboard":
        import subprocess
        from pathlib import Path
        app = Path(__file__).resolve().parent / "dashboard" / "app.py"
        return subprocess.call([sys.executable, "-m", "streamlit", "run", str(app)])

    if args.command == "web":
        import os
        import runpy
        from pathlib import Path
        os.environ["PORT"] = str(args.port)
        runpy.run_path(str(Path(__file__).resolve().parent.parent / "serve.py"), run_name="__main__")
        return 0

    parser.error("unknown command")
    return 2


if __name__ == "__main__":
    sys.exit(main())
