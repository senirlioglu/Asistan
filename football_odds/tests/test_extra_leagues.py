"""Football-Data 'extra' league files (new/<CODE>.csv): one file per country, closing odds only."""

import io

import pandas as pd

from src.config import extra_season_code, load_settings, season_label, season_start_year
from src.data.football_data import normalise_extra_frame, raw_path
from src.data.providers import extra_fixture_frames, extra_league_code
from src.features.odds import add_market_features

EXTRA_CSV = (
    "﻿Country,League,Season,Date,Time,Home,Away,HG,AG,Res,PSCH,PSCD,PSCA,MaxCH,MaxCD,MaxCA,AvgCH,AvgCD,AvgCA,BFECH,BFECD,BFECA,B365CH,B365CD,B365CA\n"
    "Switzerland,Super League,2016/2017,23/07/2016,17:00,Basel,Sion,2,1,H,1.5,4.2,6.5,1.55,4.4,7.0,1.48,4.1,6.2,,,,1.5,4.2,6.0\n"
    "Switzerland,Challenge League,2016/2017,23/07/2016,17:00,Aarau,Wil,0,0,D,2.1,3.3,3.4,2.2,3.4,3.6,2.05,3.25,3.3,,,,2.1,3.3,3.4\n"
    "Switzerland,Super League ,2026/2027,20/07/2026,15:30,Young Boys,Lugano,3,1,H,1.6,4.0,5.5,1.65,4.2,6.0,1.58,3.95,5.3,1.66,4.1,5.9,1.6,4.0,5.5\n"
    "Switzerland,Super League,1999/2000,20/07/1999,15:30,Old,Older,1,1,D,,,,,,,2.0,3.0,4.0,,,,,,\n"
)
CALENDAR_CSV = (
    "Country,League,Season,Date,Time,Home,Away,HG,AG,Res,PSCH,PSCD,PSCA,MaxCH,MaxCD,MaxCA,AvgCH,AvgCD,AvgCA\n"
    "Brazil,Serie A,2025,13/04/2025,20:00,Flamengo,Santos,2,0,H,1.7,3.6,5.0,1.75,3.8,5.5,1.68,3.55,4.9\n"
    "Brazil,Serie A,2026,05/09/2026,22:00,Palmeiras,Gremio,1,1,D,1.9,3.4,4.2,1.95,3.5,4.5,1.88,3.35,4.1\n"
)


def _raw(text: str) -> pd.DataFrame:
    return pd.read_csv(io.StringIO(text), dtype=str, index_col=False)


def test_season_codes():
    assert extra_season_code("2016/2017") == "1617"
    assert extra_season_code("2015") == "Y2015"
    assert extra_season_code("Season") is None
    assert season_start_year("Y2015") == 2015 and season_label("Y2015") == "2015"
    assert season_start_year("1617") == 2016 and season_label("1617") == "2016/17"


def test_extra_frame_filters_league_and_maps_seasons():
    settings = load_settings()
    years = {season_start_year(s) for s in settings.seasons}
    df = normalise_extra_frame(_raw(EXTRA_CSV), "SWZ", settings.extra_leagues["SWZ"], years)
    assert list(df["home_team"]) == ["Basel", "Young Boys"]          # Challenge League + 1999 row dropped
    assert list(df["season"]) == ["1617", "2627"]
    assert list(df["div"]) == ["SWZ", "SWZ"] and df["time"].iloc[0] == "17:00"
    assert df["hthg"].isna().all()                                     # extra files carry no half-time score
    df2 = normalise_extra_frame(_raw(EXTRA_CSV), "SWZ2", {"fd_league": "Challenge League"}, years)
    assert list(df2["home_team"]) == ["Aarau"]
    bra = normalise_extra_frame(_raw(CALENDAR_CSV), "BRA", settings.extra_leagues["BRA"], years)
    assert list(bra["season"]) == ["Y2025", "Y2026"] and list(bra["season_start_year"]) == [2025, 2026]


def test_closing_average_serves_as_market_for_extra_leagues():
    settings = load_settings()
    df = normalise_extra_frame(_raw(EXTRA_CSV), "SWZ", settings.extra_leagues["SWZ"], None)
    out = add_market_features(df)
    assert (out["consensus_source"] == "avg_closing").all()
    assert out["has_1x2"].all()
    assert abs(out["cons_h"].iloc[0] - 1.48) < 1e-9
    assert abs(out[["p_home", "p_draw", "p_away"]].iloc[0].sum() - 1.0) < 1e-9
    # no separate closing benchmark when closing IS the market
    assert not out["has_closing"].any() and out["delta_p_home"].isna().all()


def test_extra_fixture_mapping():
    settings = load_settings()
    assert extra_league_code(settings, "Switzerland", "Challenge League") is None   # only 2 rows on Football-Data: not configured
    assert extra_league_code(settings, "Switzerland", "Super League") == "SWZ"
    assert extra_league_code(settings, "Argentina", "Copa De La Liga Profesional") == "ARG"   # fd_league null
    assert extra_league_code(settings, "Atlantis", "Premier") is None
    fx = _raw("﻿Country,League,Date,Time,Home,Away,PSH,PSD,PSA,MaxH,MaxD,MaxA,AvgH,AvgD,AvgA\n"
              "Brazil,Serie A,20/09/2026,00:30,Flamengo,Santos,1.7,3.6,5.0,1.75,3.8,5.5,1.68,3.55,4.9\n"
              "Narnia,League,20/09/2026,00:30,A,B,1.7,3.6,5.0,1.75,3.8,5.5,1.68,3.55,4.9\n")
    frames = extra_fixture_frames(fx, settings, "2627")
    assert len(frames) == 1 and frames[0]["league"].iloc[0] == "BRA" and frames[0]["avg_h"].iloc[0] == 1.68


def test_extra_raw_path_ignores_season():
    settings = load_settings()
    assert raw_path(settings, "1112", "SWZ") == raw_path(settings, "2627", "SWZ")
    assert raw_path(settings, "1112", "E0") != raw_path(settings, "1213", "E0")
