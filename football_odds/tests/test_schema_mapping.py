import io

import pandas as pd

from src.data.football_data import map_columns, normalise_frame, parse_dates, read_raw_csv
from src.data.schema import CANONICAL_COLUMNS, POST_MATCH_COLUMNS
from src.features.vectors import FEATURE_SETS

OLD_CSV = "Div,Date,HomeTeam,AwayTeam,FTHG,FTAG,FTR,B365H,B365D,B365A,Bb1X2,BbMxH,BbAvH,BbMxD,BbAvD,BbMxA,BbAvA,BbOU,BbMx>2.5,BbAv>2.5,BbMx<2.5,BbAv<2.5,BbAH,BbAHh\n" \
          "E0,13/08/11,Blackburn,Wolves,1,2,A,2.2,3.2,3.5,37,2.22,2.13,3.43,3.29,3.75,3.52,37,2.06,1.96,1.89,1.82,18,-0.5,\n"
NEW_CSV = "﻿Div,Date,Time,HomeTeam,AwayTeam,FTHG,FTAG,FTR,HxG,AxG,B365H,B365D,B365A,MaxH,MaxD,MaxA,AvgH,AvgD,AvgA,Avg>2.5,Avg<2.5,AHh,AvgAHH,AvgAHA,AvgCH,AvgCD,AvgCA\n" \
          "E0,15/08/2025,20:00,Liverpool,Bournemouth,4,2,H,2.1,0.9,1.3,6,8.5,1.34,6.5,9.5,1.31,5.96,8.31,1.38,3.3,-1.5,1.9,2.0,1.28,6.3,9.2\n"


def _frame(text: str) -> pd.DataFrame:
    return pd.read_csv(io.StringIO(text), dtype=str, index_col=False)


def test_old_season_betbrain_columns_map_to_avg_max():
    mapped, mapping = map_columns(_frame(OLD_CSV))
    assert mapping["avg_h"] == "BbAvH" and mapping["max_h"] == "BbMxH"
    assert mapping["avg_o25"] == "BbAv>2.5" and mapping["ah_line"] == "BbAHh"
    assert "avgc_h" not in mapping  # no closing odds in 2011/12
    assert mapped["avgc_h"].isna().all()  # ...but the column exists and is NaN, nothing crashes


def test_new_season_columns_and_bom():
    mapped, mapping = map_columns(_frame(NEW_CSV))
    assert mapping["avg_h"] == "AvgH" and mapping["avgc_h"] == "AvgCH" and mapping["time"] == "Time"
    assert "HxG" not in mapped.columns  # post-match xG never enters the canonical frame


def test_date_parsing_both_formats():
    s = pd.Series(["13/08/11", "15/08/2025", None])
    out = parse_dates(s)
    assert out[0] == pd.Timestamp("2011-08-13") and out[1] == pd.Timestamp("2025-08-15") and pd.isna(out[2])


def test_normalise_frame_types_and_ids():
    df = normalise_frame(_frame(OLD_CSV), "1112", "E0")
    assert len(df) == 1
    assert df.loc[0, "season_start_year"] == 2011
    assert df["fthg"].dtype.kind in "fi"
    assert len(df.loc[0, "match_id"]) == 16
    df2 = normalise_frame(_frame(OLD_CSV), "1112", "E0")
    assert df.loc[0, "match_id"] == df2.loc[0, "match_id"]  # deterministic


def test_read_raw_csv_handles_trailing_commas(tmp_path):
    p = tmp_path / "x.csv"
    p.write_text(OLD_CSV, encoding="utf-8")
    df = read_raw_csv(p)
    assert not any(str(c).startswith("Unnamed") for c in df.columns)


def test_feature_sets_never_contain_post_match_columns():
    for cols in FEATURE_SETS.values():
        assert not set(cols) & POST_MATCH_COLUMNS
        for c in cols:
            assert c not in CANONICAL_COLUMNS or c not in ("fthg", "ftag", "ftr")
