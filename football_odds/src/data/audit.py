"""PHASE 1 — data audit: which columns / markets exist in which season and league.

Produces ``results/audit/column_availability.csv`` (season x league x market), the raw header
inventory and a Markdown summary. The audit only reads the cached raw CSVs.
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from ..config import Settings, season_label
from ..logging_setup import get_logger
from .football_data import raw_headers
from .schema import CANONICAL_COLUMNS, data_dictionary

log = get_logger("data.audit")

# markets to track, canonical name -> label
MARKETS = {
    "time": "kick-off time",
    "avg_h": "1X2 market average (AvgH/BbAvH)",
    "max_h": "1X2 market max (MaxH/BbMxH)",
    "b365_h": "Bet365 1X2",
    "ps_h": "Pinnacle 1X2",
    "bfe_h": "Betfair Exchange 1X2",
    "avgc_h": "closing 1X2 average (AvgCH)",
    "psc_h": "Pinnacle closing 1X2",
    "avg_o25": "O/U 2.5 average",
    "b365_o25": "Bet365 O/U 2.5",
    "p_o25": "Pinnacle O/U 2.5",
    "avgc_o25": "closing O/U 2.5 average",
    "ah_line": "Asian handicap line",
    "avg_ahh": "AH average odds",
    "avgc_ahh": "closing AH average odds",
}


def _resolve(headers: list[str], canonical: str) -> str | None:
    for cand in CANONICAL_COLUMNS[canonical]:
        if cand in headers:
            return cand
    return None


def run_audit(settings: Settings, out_dir: Path | None = None) -> pd.DataFrame:
    out_dir = out_dir or (settings.results_dir / "audit")
    out_dir.mkdir(parents=True, exist_ok=True)
    rows = []
    headers_inventory: dict[str, list[str]] = {}
    pairs = [(s, lg) for s in settings.seasons for lg in settings.active_leagues if not settings.is_extra_league(lg)]
    pairs += [("all", lg) for lg in settings.active_leagues if settings.is_extra_league(lg)]  # one file, every season
    for season, league in pairs:
        headers = raw_headers(settings, season, league)
        if headers is None:
            rows.append({"season": season, "league": league, "file": "missing"})
            continue
        headers_inventory[f"{season}/{league}"] = headers
        row = {"season": season, "league": league, "file": "ok", "n_columns": len(headers)}
        for canonical in MARKETS:
            row[canonical] = _resolve(headers, canonical)
        row["btts_odds"] = None  # Football-Data never publishes BTTS odds
        row["xg_post_match"] = "HxG" if "HxG" in headers else None
        rows.append(row)
    audit = pd.DataFrame(rows)
    audit.to_csv(out_dir / "column_availability.csv", index=False)
    (out_dir / "raw_headers.json").write_text(json.dumps(headers_inventory, indent=1))
    pd.DataFrame(data_dictionary()).to_csv(out_dir / "data_dictionary.csv", index=False)

    # season-level availability summary (share of league files that carry each market)
    ok = audit[audit["file"] == "ok"]
    summary = ok.groupby("season")[list(MARKETS)].agg(lambda s: f"{int(s.notna().sum())}/{len(s)}")
    summary.index = [season_label(s) if s != "all" else "extra leagues (all seasons)" for s in summary.index]
    summary.to_csv(out_dir / "market_availability_by_season.csv")

    md = ["# Football-Data column audit", "",
          f"Files: {int((audit['file'] == 'ok').sum())} ok, {int((audit['file'] == 'missing').sum())} missing", "",
          "Share of league files (per season) that carry each market:", "",
          "| season | " + " | ".join(MARKETS.values()) + " |",
          "|---|" + "---|" * len(MARKETS)]
    for label, r in summary.iterrows():
        md.append(f"| {label} | " + " | ".join(str(r[c]) for c in MARKETS) + " |")
    md += ["", "Notes:", "",
           "- BTTS odds are **not** published by Football-Data in any season; BTTS is derived from the score only.",
           "- Closing odds (`*C*` columns) exist from 2019/20 onwards.",
           "- Pre-2019/20 aggregates come from Betbrain (`BbAvH`, `BbMxH`, `BbAv>2.5`, `BbAHh`).",
           "- `HxG/AxG` (2026/27+) are post-match expected goals — excluded from every feature vector.",
           "- Kick-off `Time` exists from 2019/20 only; earlier matches have a date but no time."]
    (out_dir / "audit_summary.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    log.info("audit written to %s", out_dir)
    return audit
