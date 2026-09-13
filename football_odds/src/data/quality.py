"""Data quality report, produced on every build."""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

import numpy as np
import pandas as pd

from ..config import Settings, season_label


def data_quality_report(df: pd.DataFrame, settings: Settings) -> dict:
    n = len(df)
    min_odds = float(settings.get("odds.min_valid_odds", 1.01))
    odds_cols = [c for c in ("cons_h", "cons_d", "cons_a", "b365_h", "b365_d", "b365_a", "max_h", "max_d", "max_a",
                             "cons_o25", "cons_u25") if c in df.columns]
    invalid_odds = 0
    for c in odds_cols:
        vals = df[c].to_numpy(dtype=float)
        invalid_odds += int(np.sum(np.isfinite(vals) & (vals <= 1.0)))

    dup = int(df["match_id"].duplicated().sum())
    missing_result = float(df["result_code"].isna().mean() * 100) if n else 0.0
    missing_1x2 = float((~df["has_1x2"]).mean() * 100) if n else 0.0
    missing_ou = float((~df["has_ou"]).mean() * 100) if n else 0.0
    missing_closing = float((~df["has_closing"]).mean() * 100) if n else 0.0

    by_league = (df.groupby("league").agg(matches=("match_id", "size"), seasons=("season", "nunique"),
                                          odds_pct=("has_1x2", lambda s: 100 * s.mean()),
                                          ou_pct=("has_ou", lambda s: 100 * s.mean()),
                                          closing_pct=("has_closing", lambda s: 100 * s.mean()))
                 .round(1).reset_index())
    by_season = (df.groupby("season").agg(matches=("match_id", "size"), leagues=("league", "nunique"),
                                          odds_pct=("has_1x2", lambda s: 100 * s.mean()),
                                          ou_pct=("has_ou", lambda s: 100 * s.mean()),
                                          closing_pct=("has_closing", lambda s: 100 * s.mean()))
                 .round(1).reset_index())
    by_season["label"] = by_season["season"].map(season_label)

    overround = df.loc[df["has_1x2"], "overround_1x2"]
    return {
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "n_rows": int(n),
        "n_leagues": int(df["league"].nunique()),
        "n_seasons": int(df["season"].nunique()),
        "date_min": str(df["date"].min().date()) if n else None,
        "date_max": str(df["date"].max().date()) if n else None,
        "missing_1x2_odds_pct": round(missing_1x2, 2),
        "missing_ou_odds_pct": round(missing_ou, 2),
        "missing_closing_odds_pct": round(missing_closing, 2),
        "missing_result_pct": round(missing_result, 2),
        "duplicate_matches": dup,
        "invalid_odds_values": invalid_odds,
        "overround_1x2_mean": round(float(overround.mean()), 4) if len(overround) else None,
        "overround_1x2_p99": round(float(overround.quantile(0.99)), 4) if len(overround) else None,
        "consensus_sources": {k: int(v) for k, v in df["consensus_source"].value_counts().items()},
        "league_coverage": by_league.to_dict(orient="records"),
        "season_coverage": by_season.to_dict(orient="records"),
    }


def write_quality_report(report: dict, results_dir: Path) -> Path:
    results_dir.mkdir(parents=True, exist_ok=True)
    (results_dir / "data_quality_report.json").write_text(json.dumps(report, indent=2, default=str))
    md = [
        "# Data quality report", "",
        f"Generated: {report['generated_at']}", "",
        "| metric | value |", "|---|---|",
        f"| matches | {report['n_rows']} |",
        f"| leagues | {report['n_leagues']} |",
        f"| seasons | {report['n_seasons']} |",
        f"| date range | {report['date_min']} → {report['date_max']} |",
        f"| missing 1X2 odds % | {report['missing_1x2_odds_pct']} |",
        f"| missing O/U 2.5 odds % | {report['missing_ou_odds_pct']} |",
        f"| missing closing odds % | {report['missing_closing_odds_pct']} |",
        f"| missing result % | {report['missing_result_pct']} |",
        f"| duplicate matches | {report['duplicate_matches']} |",
        f"| invalid odds values (<= 1.00) | {report['invalid_odds_values']} |",
        f"| mean 1X2 overround | {report['overround_1x2_mean']} |",
        f"| missing files | {len(report.get('missing_files', []))} |",
        "", "## League coverage", "",
        "| league | matches | seasons | 1X2 % | O/U % | closing % |", "|---|---|---|---|---|---|",
    ]
    for r in report["league_coverage"]:
        md.append(f"| {r['league']} | {r['matches']} | {r['seasons']} | {r['odds_pct']} | {r['ou_pct']} | {r['closing_pct']} |")
    md += ["", "## Season coverage", "", "| season | matches | leagues | 1X2 % | O/U % | closing % |", "|---|---|---|---|---|---|"]
    for r in report["season_coverage"]:
        md.append(f"| {r['label']} | {r['matches']} | {r['leagues']} | {r['odds_pct']} | {r['ou_pct']} | {r['closing_pct']} |")
    if report.get("missing_files"):
        md += ["", "## Missing files", ""] + [f"- {m}" for m in report["missing_files"]]
    path = results_dir / "data_quality_report.md"
    path.write_text("\n".join(md) + "\n", encoding="utf-8")
    return path
