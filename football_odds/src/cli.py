"""Command-line entry point.

    python -m src.cli download            # fetch/refresh Football-Data CSVs into data/raw
    python -m src.cli audit               # PHASE 1 column/market availability audit
    python -m src.cli build               # processed Parquet database + data quality report
    python -m src.cli state               # match state table (form, goals, table, TSI) next to it
    python -m src.cli notes               # re-measure the notebook notes against price-matched history
    python -m src.cli tune-twins          # choose the twin weights + time decay on validation, report on test
    python -m src.cli models              # walk-forward comparison: market vs similarity / pattern / twin
    python -m src.cli discover            # scan the pattern grid: discovery -> validation -> untouched test
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


def _round_claims(df) -> list[dict]:
    """The full claims table, rounded so the file stays small enough to ship to a phone."""
    out = df.copy()
    for c in out.columns:
        if out[c].dtype.kind == "f":
            out[c] = out[c].round(3)
    keep = [c for c in out.columns if c != "key"]
    return out[keep].to_dict("records")


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

    sub.add_parser("notes", help="measure the notebook notes against the market and against price-matched matches")

    p = sub.add_parser("discover", help="scan the candidate pattern grid through train / validation / test windows")
    p.add_argument("--min-n", type=int, default=200, help="smallest sample a claim may be made on (default 200)")
    p.add_argument("--min-edge", type=float, default=1.0, help="points of edge worth following up (default 1.0)")

    p = sub.add_parser("tune-twins", help="choose the twin category weights + time decay on a validation window")
    p.add_argument("--val", type=int, default=600, help="validation matches the search is scored on (default 600)")
    p.add_argument("--test", type=int, default=1200, help="test matches the winner is reported on (default 1200)")
    p.add_argument("--k", type=int, default=100, help="twins per query (default 100)")

    p = sub.add_parser("models", help="walk-forward comparison of market / similarity / pattern / twin models")
    p.add_argument("--sample", type=int, default=1000, help="test matches per season (default 1000)")
    p.add_argument("--seasons", help="comma separated season codes (default: the last five)")
    p.add_argument("--k-twins", type=int, default=200)

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

    if args.command == "notes":
        import json

        import pandas as pd

        from .patterns import engine, notes, state
        st = state.load(settings)
        if st is None:
            log.error("match state not built yet — run: python -m src.cli state")
            return 1
        frame = engine.prepare(st, pd.read_parquet(settings.processed_dir / "matches.parquet"))
        rows = notes.measure_notes(frame)
        print(notes.report(rows))
        out = settings.results_dir / "notes_measured.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
        log.info("wrote %s", out)
        return 0

    if args.command == "discover":
        import json

        import pandas as pd

        from .patterns import discovery, engine, state
        st = state.load(settings)
        if st is None:
            log.error("match state not built yet — run: python -m src.cli state")
            return 1
        frame = engine.prepare(st, pd.read_parquet(settings.processed_dir / "matches.parquet"))
        res = discovery.discover(frame, min_n=args.min_n, min_edge=args.min_edge)
        print("\n" + discovery.report(res))
        out = settings.results_dir / "backtest" / "discovery.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        claims = res.get("claims")
        payload = {"stages": res["stages"],
                   "survivors": [] if not len(res["survivors"]) else res["survivors"].drop(columns=["pattern"]).to_dict("records"),
                   "confirmed": [] if not len(res["confirmed"]) else res["confirmed"].drop(columns=["pattern"]).to_dict("records"),
                   # every claim the scan measured, with the window it reached: the funnel counts
                   # alone hide which ideas died, which is the answer to most readers' questions
                   "claims": [] if claims is None or not len(claims) else _round_claims(claims),
                   "stage_names": discovery.STAGES}
        out.write_text(json.dumps(payload, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
        log.info("wrote %s", out)
        return 0

    if args.command == "tune-twins":
        from .patterns import tune
        try:
            out = tune.run(settings, n_val=args.val, n_test=args.test, k=args.k)
        except FileNotFoundError as exc:
            log.error("%s", exc)
            return 1
        print("\n" + tune.report(out))
        return 0

    if args.command == "models":
        import json

        import pandas as pd

        from .patterns import engine, evaluate, state
        st = state.load(settings)
        if st is None:
            log.error("match state not built yet — run: python -m src.cli state")
            return 1
        frame = engine.prepare(st, pd.read_parquet(settings.processed_dir / "matches.parquet"))
        per = evaluate.run(settings, frame, test_seasons=_parse_list(args.seasons), sample=args.sample,
                           k_twins=args.k_twins)
        summary = evaluate.summarise(per)
        print("\n=== sezon bazında ===\n" + per.to_string(index=False))
        print("\n=== toplam ===\n" + summary.to_string(index=False))
        out = settings.results_dir / "backtest" / "models.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps({"per_season": per.to_dict("records"), "summary": summary.to_dict("records")},
                                  ensure_ascii=False, indent=1), encoding="utf-8")
        log.info("wrote %s", out)
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
