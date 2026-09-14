"""Build the processed historical database (Parquet) from cached raw CSVs."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from ..config import Settings
from ..features.odds import add_market_features
from ..logging_setup import get_logger
from .football_data import load_raw_extra_league, load_raw_season
from .quality import data_quality_report, write_quality_report
from .schema import RESULT_CODES

log = get_logger("data.build")

KEEP_COLUMNS = [
    "match_id", "league", "season", "season_start_year", "date", "time", "home_team", "away_team",
    "fthg", "ftag", "ftr", "hthg", "htag", "htr",
    "b365_h", "b365_d", "b365_a", "ps_h", "ps_d", "ps_a", "max_h", "max_d", "max_a",
    "avg_h", "avg_d", "avg_a", "n_books_1x2", "bfe_h", "bfe_d", "bfe_a",
    "b365c_h", "b365c_d", "b365c_a", "psc_h", "psc_d", "psc_a", "maxc_h", "maxc_d", "maxc_a",
    "avgc_h", "avgc_d", "avgc_a",
    "b365_o25", "b365_u25", "p_o25", "p_u25", "max_o25", "max_u25", "avg_o25", "avg_u25",
    "b365c_o25", "b365c_u25", "pc_o25", "pc_u25", "avgc_o25", "avgc_u25",
    "ah_line", "b365_ahh", "b365_aha", "p_ahh", "p_aha", "avg_ahh", "avg_aha", "max_ahh", "max_aha",
    "ahc_line", "avgc_ahh", "avgc_aha", "pc_ahh", "pc_aha",
    "cons_h", "cons_d", "cons_a", "consensus_source", "n_books_used",
    "raw_p_home", "raw_p_draw", "raw_p_away", "p_home", "p_draw", "p_away", "overround_1x2", "has_1x2",
    "cons_o25", "cons_u25", "ou_source", "p_over25", "p_under25", "overround_ou", "has_ou",
    "pc_home", "pc_draw", "pc_away", "has_closing", "delta_p_home", "delta_p_draw", "delta_p_away",
    "pin_p_home", "pin_p_draw", "pin_p_away", "pinc_p_home", "pinc_p_draw", "pinc_p_away",
    "p_ah_home", "has_ah",
    "total_goals", "btts", "over25", "result_code",
]


def add_targets(df: pd.DataFrame) -> pd.DataFrame:
    """Realised outcomes. These are TARGETS only — never features (see schema.POST_MATCH_COLUMNS)."""
    df = df.copy()
    df["total_goals"] = df["fthg"] + df["ftag"]
    df["btts"] = (df["fthg"] > 0) & (df["ftag"] > 0)
    df["btts"] = df["btts"].where(df["total_goals"].notna(), other=pd.NA).astype("boolean")
    df["over25"] = (df["total_goals"] > 2.5).where(df["total_goals"].notna(), other=pd.NA).astype("boolean")
    # ftr can be missing in a handful of old rows even when goals exist -> derive it
    derived = np.select([df["fthg"] > df["ftag"], df["fthg"] == df["ftag"], df["fthg"] < df["ftag"]], ["H", "D", "A"], default=None)
    df["ftr"] = df["ftr"].where(df["ftr"].isin(list(RESULT_CODES)), pd.Series(derived, index=df.index))
    df["result_code"] = df["ftr"].map(RESULT_CODES).astype("Int8")
    return df


def build_processed(settings: Settings, seasons: list[str] | None = None, leagues: list[str] | None = None,
                    out_path: Path | None = None) -> tuple[pd.DataFrame, dict]:
    seasons = seasons or settings.seasons
    leagues = leagues or settings.active_leagues
    odds_cfg = settings.section("odds")

    frames: list[pd.DataFrame] = []
    missing: list[str] = []
    for season in seasons:
        for league in leagues:
            if settings.is_extra_league(league):
                continue
            part = load_raw_season(settings, season, league)
            if part is None or part.empty:
                missing.append(f"{season}/{league}")
                continue
            frames.append(part)
    # extra leagues: one file holds every season
    for league in leagues:
        if not settings.is_extra_league(league):
            continue
        part = load_raw_extra_league(settings, league)
        if part is None or part.empty:
            missing.append(f"all/{league}")
            continue
        frames.append(part)
    if not frames:
        raise RuntimeError("no raw files found — run `python -m src.cli download` first")
    df = pd.concat(frames, ignore_index=True)
    log.info("loaded %d rows from %d files (%d missing)", len(df), len(frames), len(missing))

    df = add_market_features(df, odds_cfg.get("normalization", "proportional"), float(odds_cfg.get("min_valid_odds", 1.01)),
                             float(odds_cfg.get("max_valid_odds", 200.0)), float(odds_cfg.get("max_overround", 1.30)))
    df = add_targets(df)

    # quality report is computed BEFORE dropping duplicates so it can count them
    report = data_quality_report(df, settings)
    report["missing_files"] = missing

    before = len(df)
    df = df.sort_values(["date", "league", "home_team"]).drop_duplicates("match_id", keep="first")
    dropped = before - len(df)
    if dropped:
        log.warning("dropped %d duplicate match_ids", dropped)

    # rows without a result are unplayed/abandoned: keep them out of the historical pool
    played = df["result_code"].notna()
    log.info("%d rows without result removed", int((~played).sum()))
    df = df[played].copy()

    cols = [c for c in KEEP_COLUMNS if c in df.columns]
    df = df[cols].reset_index(drop=True)
    df["date"] = pd.to_datetime(df["date"])

    out_path = out_path or (settings.processed_dir / "matches.parquet")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(out_path, index=False)
    log.info("wrote %s (%d matches)", out_path, len(df))

    report["rows_written"] = int(len(df))
    write_quality_report(report, settings.results_dir)
    (settings.processed_dir / "build_info.json").write_text(json.dumps({
        "rows": int(len(df)), "seasons": seasons, "leagues": leagues, "missing_files": missing,
        "date_min": str(df["date"].min().date()), "date_max": str(df["date"].max().date()),
    }, indent=2))
    return df, report
