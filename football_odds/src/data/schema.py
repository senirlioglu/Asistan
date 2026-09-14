"""Canonical schema and Football-Data column mapping.

Football-Data renamed several columns over the years:

* 2011/12 - 2018/19: Betbrain aggregates ``BbAvH/BbMxH/Bb1X2``, ``BbAv>2.5``, ``BbAHh``.
* 2019/20 onwards : market aggregates ``AvgH/MaxH``, ``Avg>2.5``, ``AHh`` **plus closing odds**
  with a ``C`` after the bookmaker prefix (``AvgCH``, ``PSCH``, ``AvgC>2.5``, ``AHCh``).
* ``Time`` exists from 2019/20; older files only have ``Date`` (``dd/mm/yy`` or ``dd/mm/yyyy``).
* The "new" (non-European) files use ``HG/AG/Res`` instead of ``FTHG/FTAG/FTR``.
* 2026/27 adds post-match ``HxG/AxG`` (expected goals) — a **look-ahead** column, never a feature.

`CANONICAL_COLUMNS` maps every canonical name to an ordered list of source candidates; the
first one present in a file wins. Missing candidates simply produce NaN — nothing crashes.
"""

from __future__ import annotations

from typing import Final

# canonical name -> ordered candidate source columns
CANONICAL_COLUMNS: Final[dict[str, list[str]]] = {
    # identity / result -------------------------------------------------------
    "div": ["Div"],
    "date": ["Date"],
    "time": ["Time"],
    "home_team": ["HomeTeam", "HT", "Home"],
    "away_team": ["AwayTeam", "AT", "Away"],
    "fthg": ["FTHG", "HG"],
    "ftag": ["FTAG", "AG"],
    "ftr": ["FTR", "Res"],
    "hthg": ["HTHG"],
    "htag": ["HTAG"],
    "htr": ["HTR"],
    # 1X2 pre-closing ------------------------------------------------------------
    "b365_h": ["B365H"], "b365_d": ["B365D"], "b365_a": ["B365A"],
    "ps_h": ["PSH", "PH"], "ps_d": ["PSD", "PD"], "ps_a": ["PSA", "PA"],
    "bw_h": ["BWH"], "bw_d": ["BWD"], "bw_a": ["BWA"],
    "wh_h": ["WHH"], "wh_d": ["WHD"], "wh_a": ["WHA"],
    "iw_h": ["IWH"], "iw_d": ["IWD"], "iw_a": ["IWA"],
    "vc_h": ["VCH", "BVH"], "vc_d": ["VCD", "BVD"], "vc_a": ["VCA", "BVA"],
    "lb_h": ["LBH"], "lb_d": ["LBD"], "lb_a": ["LBA"],
    "bfe_h": ["BFEH"], "bfe_d": ["BFED"], "bfe_a": ["BFEA"],
    "max_h": ["MaxH", "BbMxH"], "max_d": ["MaxD", "BbMxD"], "max_a": ["MaxA", "BbMxA"],
    "avg_h": ["AvgH", "BbAvH"], "avg_d": ["AvgD", "BbAvD"], "avg_a": ["AvgA", "BbAvA"],
    "n_books_1x2": ["Bb1X2"],
    # 1X2 closing ------------------------------------------------------------------
    "b365c_h": ["B365CH"], "b365c_d": ["B365CD"], "b365c_a": ["B365CA"],
    "psc_h": ["PSCH"], "psc_d": ["PSCD"], "psc_a": ["PSCA"],
    "maxc_h": ["MaxCH"], "maxc_d": ["MaxCD"], "maxc_a": ["MaxCA"],
    "avgc_h": ["AvgCH"], "avgc_d": ["AvgCD"], "avgc_a": ["AvgCA"],
    # Over/Under 2.5 pre-closing ------------------------------------------------------
    "b365_o25": ["B365>2.5"], "b365_u25": ["B365<2.5"],
    "p_o25": ["P>2.5"], "p_u25": ["P<2.5"],
    "max_o25": ["Max>2.5", "BbMx>2.5"], "max_u25": ["Max<2.5", "BbMx<2.5"],
    "avg_o25": ["Avg>2.5", "BbAv>2.5"], "avg_u25": ["Avg<2.5", "BbAv<2.5"],
    "n_books_ou": ["BbOU"],
    # Over/Under 2.5 closing ------------------------------------------------------------
    "b365c_o25": ["B365C>2.5"], "b365c_u25": ["B365C<2.5"],
    "pc_o25": ["PC>2.5"], "pc_u25": ["PC<2.5"],
    "avgc_o25": ["AvgC>2.5"], "avgc_u25": ["AvgC<2.5"],
    # Asian handicap ----------------------------------------------------------------------
    "ah_line": ["AHh", "BbAHh"],
    "b365_ahh": ["B365AHH"], "b365_aha": ["B365AHA"],
    "p_ahh": ["PAHH"], "p_aha": ["PAHA"],
    "avg_ahh": ["AvgAHH", "BbAvAHH"], "avg_aha": ["AvgAHA", "BbAvAHA"],
    "max_ahh": ["MaxAHH", "BbMxAHH"], "max_aha": ["MaxAHA", "BbMxAHA"],
    "n_books_ah": ["BbAH"],
    "ahc_line": ["AHCh"],
    "avgc_ahh": ["AvgCAHH"], "avgc_aha": ["AvgCAHA"],
    "pc_ahh": ["PCAHH"], "pc_aha": ["PCAHA"],
}

# Individual 1X2 bookmakers used to build a consensus when Avg/BbAv is missing.
# Betfair Exchange (BFE) is excluded: exchange prices have a different margin structure.
BOOKMAKER_1X2_PREFIXES: Final[list[str]] = [
    "B365", "BW", "IW", "PS", "WH", "VC", "BV", "LB", "GB", "SB", "SJ", "BS",
    "BFD", "BMGM", "CL", "PP", "SK", "SKB", "SO", "SY", "1XB", "BF",
]

# Columns that are only known AFTER kick-off. They are kept in the processed DB as
# targets/diagnostics but must never enter a feature vector.
POST_MATCH_COLUMNS: Final[set[str]] = {
    "fthg", "ftag", "ftr", "hthg", "htag", "htr",
    "total_goals", "btts", "over25", "result_code",
}

RESULT_CODES: Final[dict[str, int]] = {"H": 0, "D": 1, "A": 2}
RESULT_LABELS: Final[list[str]] = ["H", "D", "A"]


def numeric_canonical_columns() -> list[str]:
    non_numeric = {"div", "date", "time", "home_team", "away_team", "ftr", "htr"}
    return [c for c in CANONICAL_COLUMNS if c not in non_numeric]


def data_dictionary() -> list[dict[str, str]]:
    """Human-readable dictionary of the processed schema (used by the audit report)."""
    rows: list[dict[str, str]] = []
    descriptions = {
        "match_id": "Stable hash of league|date|home|away",
        "league": "Football-Data division code (E0, SP1, ...)",
        "season": "Season code (1112 = 2011/12)",
        "date": "Kick-off date",
        "time": "Kick-off time (2019/20+ only)",
        "home_team": "Home team", "away_team": "Away team",
        "fthg": "Full-time home goals (TARGET)", "ftag": "Full-time away goals (TARGET)",
        "ftr": "Full-time result H/D/A (TARGET)",
        "hthg": "Half-time home goals (post-match)", "htag": "Half-time away goals (post-match)",
        "htr": "Half-time result (post-match)",
        "cons_h": "Consensus home odds (AvgH/BbAvH, else mean of listed bookmakers)",
        "cons_d": "Consensus draw odds", "cons_a": "Consensus away odds",
        "consensus_source": "avg | books_mean | none",
        "overround_1x2": "Sum of raw implied probabilities of the consensus 1X2 market",
        "p_home": "Margin-free market probability of a home win",
        "p_draw": "Margin-free market probability of a draw",
        "p_away": "Margin-free market probability of an away win",
        "raw_p_home": "Raw implied probability 1/odds (with margin)",
        "cons_o25": "Consensus over 2.5 odds", "cons_u25": "Consensus under 2.5 odds",
        "overround_ou": "Overround of the O/U 2.5 market",
        "p_over25": "Margin-free market probability of over 2.5 goals",
        "p_under25": "Margin-free market probability of under 2.5 goals",
        "has_ou": "True when the O/U market is available",
        "pc_home": "Closing margin-free home probability (AvgC, 2019/20+)",
        "pc_draw": "Closing draw probability", "pc_away": "Closing away probability",
        "delta_p_home": "pc_home - p_home (odds movement, 2019/20+)",
        "delta_p_draw": "pc_draw - p_draw", "delta_p_away": "pc_away - p_away",
        "has_closing": "True when closing 1X2 odds are available",
        "ah_line": "Asian handicap line for the home team (market/Betbrain)",
        "p_ah_home": "Margin-free AH home probability", "has_ah": "AH market available",
        "total_goals": "fthg + ftag (TARGET)",
        "btts": "Both teams scored (TARGET)", "over25": "total_goals > 2.5 (TARGET)",
        "result_code": "0=H, 1=D, 2=A (TARGET)",
        "years_old": "Filled at query time: age of the match relative to the analysed match",
    }
    for col, desc in descriptions.items():
        rows.append({"column": col, "description": desc})
    for col, sources in CANONICAL_COLUMNS.items():
        if col in descriptions:
            continue
        rows.append({"column": col, "description": f"Football-Data: {' | '.join(sources)}"})
    return rows
