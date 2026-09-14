"""Shared fixtures: a small synthetic historical frame in the processed schema."""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.config import load_settings  # noqa: E402
from src.data.build import add_targets  # noqa: E402
from src.features.odds import add_market_features  # noqa: E402


@pytest.fixture(scope="session")
def settings():
    return load_settings(ROOT / "config" / "settings.yaml")


def make_history(n: int = 3000, seed: int = 7, start="2012-08-01") -> pd.DataFrame:
    """Synthetic matches whose outcomes are drawn from the market probabilities (a calibrated market)."""
    rng = np.random.default_rng(seed)
    dates = pd.to_datetime(start) + pd.to_timedelta(np.sort(rng.integers(0, 365 * 10, n)), unit="D")
    p_home = rng.uniform(0.2, 0.75, n)
    p_draw = np.clip(0.30 - 0.15 * (p_home - 0.4), 0.12, 0.35)
    p_away = 1 - p_home - p_draw
    margin = 1.06
    df = pd.DataFrame({
        "match_id": [f"m{i:05d}" for i in range(n)],
        "league": rng.choice(["E0", "SP1", "D1"], n),
        "season": [f"{d.year % 100 if d.month >= 7 else (d.year - 1) % 100:02d}{(d.year + 1) % 100 if d.month >= 7 else d.year % 100:02d}" for d in dates],
        "date": dates, "time": "15:00",
        "home_team": [f"H{i % 40}" for i in range(n)], "away_team": [f"A{i % 37}" for i in range(n)],
        "avg_h": margin / p_home / margin * 1 / margin * margin, "avg_d": 1 / (p_draw * margin), "avg_a": 1 / (p_away * margin),
        "n_books_1x2": 20,
        "avg_o25": 1 / (0.5 * 1.05), "avg_u25": 1 / (0.5 * 1.05),
    })
    df["avg_h"] = 1 / (p_home * margin)
    res = np.array([rng.choice(3, p=[h, d, a]) for h, d, a in zip(p_home, p_draw, p_away)])
    goals_h = rng.poisson(1.5, n)
    goals_a = rng.poisson(1.1, n)
    # force the score to agree with the sampled result
    goals_h = np.where(res == 0, np.maximum(goals_h, goals_a + 1), goals_h)
    goals_a = np.where(res == 2, np.maximum(goals_a, goals_h + 1), goals_a)
    goals_a = np.where(res == 1, goals_h, goals_a)
    df["fthg"], df["ftag"] = goals_h.astype(float), goals_a.astype(float)
    df["ftr"] = np.array(["H", "D", "A"])[res]
    for col in ["hthg", "htag", "htr", "b365_h", "b365_d", "b365_a", "ps_h", "ps_d", "ps_a", "max_h", "max_d", "max_a",
                "avgc_h", "avgc_d", "avgc_a", "psc_h", "psc_d", "psc_a", "b365_o25", "b365_u25", "p_o25", "p_u25",
                "avg_ahh", "avg_aha", "ah_line", "season_start_year"]:
        df[col] = np.nan
    df["max_h"], df["max_d"], df["max_a"] = df["avg_h"] * 1.05, df["avg_d"] * 1.05, df["avg_a"] * 1.05
    df = add_market_features(df, "proportional", 1.01, 200.0, 1.15)
    return add_targets(df)


@pytest.fixture(scope="session")
def history() -> pd.DataFrame:
    return make_history()
