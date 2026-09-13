"""Data provider interfaces.

The analysis engine only depends on these two abstractions, so the historical source or the
live-odds source can be swapped without touching the models:

* :class:`HistoricalDataProvider` -> a processed match frame (see ``src.data.build``).
* :class:`CurrentOddsProvider`    -> upcoming fixtures with pre-match odds in the same
  canonical column names (``league, date, time, home_team, away_team, cons_h/d/a, cons_o25/u25 ...``).

Implementations:

* :class:`ParquetHistoricalProvider`   — reads ``data/processed/matches.parquet``.
* :class:`FootballDataFixturesProvider` — ``fixtures.csv`` from Football-Data (default).
* :class:`TheOddsApiProvider`          — https://the-odds-api.com (needs ``THE_ODDS_API_KEY``);
  produces the same frame from the JSON API so the engine does not change.
"""

from __future__ import annotations

import datetime as dt
import os
from abc import ABC, abstractmethod
from pathlib import Path

import numpy as np
import pandas as pd
import requests

from ..config import Settings, current_season_code
from ..features.odds import add_market_features
from ..logging_setup import get_logger
from .football_data import download_fixtures, normalise_frame, read_raw_csv

log = get_logger("data.providers")


class HistoricalDataProvider(ABC):
    @abstractmethod
    def load(self) -> pd.DataFrame:
        """Processed historical matches (one row per match, canonical columns)."""


class CurrentOddsProvider(ABC):
    @abstractmethod
    def fetch(self, date_from: dt.date | None = None, date_to: dt.date | None = None) -> pd.DataFrame:
        """Upcoming fixtures with pre-match odds in canonical columns."""


# --------------------------------------------------------------------------- historical

class ParquetHistoricalProvider(HistoricalDataProvider):
    def __init__(self, settings: Settings, path: Path | None = None):
        self.path = path or (settings.processed_dir / "matches.parquet")

    def load(self) -> pd.DataFrame:
        if not self.path.exists():
            raise FileNotFoundError(f"{self.path} missing — run `python -m src.cli build` first")
        df = pd.read_parquet(self.path)
        df["date"] = pd.to_datetime(df["date"])
        return df


# --------------------------------------------------------------------------- Football-Data fixtures

class FootballDataFixturesProvider(CurrentOddsProvider):
    """fixtures.csv: the coming week's matches with the same bookmaker columns as the result files."""

    def __init__(self, settings: Settings, force_refresh: bool = False):
        self.settings = settings
        self.force_refresh = force_refresh

    def fetch(self, date_from: dt.date | None = None, date_to: dt.date | None = None) -> pd.DataFrame:
        path = download_fixtures(self.settings, force=self.force_refresh)
        raw = read_raw_csv(path)
        frames = []
        season = current_season_code()
        for div, part in raw.groupby(raw["Div"].astype(str)):
            frames.append(normalise_frame(part, season, str(div)))
        if not frames:
            return pd.DataFrame()
        df = pd.concat(frames, ignore_index=True)
        odds_cfg = self.settings.section("odds")
        df = add_market_features(df, odds_cfg.get("normalization", "proportional"), odds_cfg.get("min_valid_odds", 1.01),
                                 odds_cfg.get("max_valid_odds", 200.0), odds_cfg.get("max_overround", 1.30))
        allowed = set(self.settings.active_leagues)
        df = df[df["league"].isin(allowed)].copy()
        if date_from is not None:
            df = df[df["date"].dt.date >= date_from]
        if date_to is not None:
            df = df[df["date"].dt.date <= date_to]
        df = df[df["has_1x2"]].sort_values(["date", "time", "league"]).reset_index(drop=True)
        log.info("fixtures: %d matches with 1X2 odds in %d leagues", len(df), df["league"].nunique())
        return df


# --------------------------------------------------------------------------- The Odds API

# the-odds-api sport keys -> Football-Data division codes
ODDS_API_SPORT_KEYS: dict[str, str] = {
    "soccer_epl": "E0",
    "soccer_efl_champ": "E1",
    "soccer_spain_la_liga": "SP1",
    "soccer_spain_segunda_division": "SP2",
    "soccer_italy_serie_a": "I1",
    "soccer_italy_serie_b": "I2",
    "soccer_germany_bundesliga": "D1",
    "soccer_germany_bundesliga2": "D2",
    "soccer_france_ligue_one": "F1",
    "soccer_france_ligue_two": "F2",
    "soccer_netherlands_eredivisie": "N1",
    "soccer_portugal_primeira_liga": "P1",
    "soccer_belgium_first_div": "B1",
    "soccer_turkey_super_league": "T1",
    "soccer_greece_super_league": "G1",
    "soccer_spl": "SC0",
}


class TheOddsApiProvider(CurrentOddsProvider):
    """Live odds from the-odds-api.com. Consensus = mean of all bookmakers returned (h2h + totals)."""

    BASE = "https://api.the-odds-api.com/v4"

    def __init__(self, settings: Settings, api_key: str | None = None, regions: str = "eu,uk", leagues: list[str] | None = None):
        self.settings = settings
        self.api_key = api_key or os.environ.get(settings.get("current.the_odds_api_key_env", "THE_ODDS_API_KEY"), "")
        if not self.api_key:
            raise RuntimeError("The Odds API key missing (set THE_ODDS_API_KEY)")
        self.regions = regions
        wanted = set(leagues or settings.active_leagues)
        self.sports = {k: v for k, v in ODDS_API_SPORT_KEYS.items() if v in wanted}

    def _get(self, sport: str) -> list[dict]:
        url = f"{self.BASE}/sports/{sport}/odds"
        params = {"apiKey": self.api_key, "regions": self.regions, "markets": "h2h,totals", "oddsFormat": "decimal"}
        resp = requests.get(url, params=params, timeout=30)
        resp.raise_for_status()
        return resp.json()

    def fetch(self, date_from: dt.date | None = None, date_to: dt.date | None = None) -> pd.DataFrame:
        rows: list[dict] = []
        for sport, league in self.sports.items():
            try:
                events = self._get(sport)
            except Exception as exc:  # noqa: BLE001
                log.warning("odds api %s failed: %s", sport, exc)
                continue
            for ev in events:
                home, away = ev.get("home_team"), ev.get("away_team")
                kick = pd.to_datetime(ev.get("commence_time"), utc=True)
                h, d, a, o, u = [], [], [], [], []
                for bk in ev.get("bookmakers", []):
                    for mk in bk.get("markets", []):
                        prices = {oc["name"]: oc.get("price") for oc in mk.get("outcomes", [])}
                        if mk["key"] == "h2h" and all(k in prices for k in (home, away, "Draw")):
                            h.append(prices[home]); d.append(prices["Draw"]); a.append(prices[away])
                        elif mk["key"] == "totals":
                            pts = {oc["name"]: oc for oc in mk.get("outcomes", []) if oc.get("point") == 2.5}
                            if "Over" in pts and "Under" in pts:
                                o.append(pts["Over"]["price"]); u.append(pts["Under"]["price"])
                if not h:
                    continue
                rows.append({
                    "Div": league, "Date": kick.strftime("%d/%m/%Y"), "Time": kick.strftime("%H:%M"),
                    "HomeTeam": home, "AwayTeam": away,
                    "AvgH": float(np.mean(h)), "AvgD": float(np.mean(d)), "AvgA": float(np.mean(a)),
                    "MaxH": float(np.max(h)), "MaxD": float(np.max(d)), "MaxA": float(np.max(a)),
                    "Avg>2.5": float(np.mean(o)) if o else np.nan, "Avg<2.5": float(np.mean(u)) if u else np.nan,
                    "Bb1X2": len(h),
                })
        if not rows:
            return pd.DataFrame()
        raw = pd.DataFrame(rows)
        frames = [normalise_frame(part, current_season_code(), str(div)) for div, part in raw.groupby("Div")]
        df = pd.concat(frames, ignore_index=True)
        odds_cfg = self.settings.section("odds")
        df = add_market_features(df, odds_cfg.get("normalization", "proportional"), odds_cfg.get("min_valid_odds", 1.01),
                                 odds_cfg.get("max_valid_odds", 200.0), odds_cfg.get("max_overround", 1.30))
        if date_from is not None:
            df = df[df["date"].dt.date >= date_from]
        if date_to is not None:
            df = df[df["date"].dt.date <= date_to]
        return df[df["has_1x2"]].sort_values(["date", "time", "league"]).reset_index(drop=True)


def make_current_provider(settings: Settings, name: str | None = None, **kwargs) -> CurrentOddsProvider:
    name = name or settings.get("current.provider", "football_data_fixtures")
    if name == "football_data_fixtures":
        return FootballDataFixturesProvider(settings, **kwargs)
    if name == "the_odds_api":
        return TheOddsApiProvider(settings, **kwargs)
    raise ValueError(f"unknown current odds provider: {name}")
