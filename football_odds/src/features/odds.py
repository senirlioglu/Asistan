"""Odds normalisation.

Reference method (the one in the specification) — proportional / "basic" normalisation::

    raw_i = 1 / odds_i
    total = sum(raw_i)            # = 1 + overround
    p_i   = raw_i / total

Two research alternatives are provided because they are standard in the literature:

* ``shin``  — Shin (1993) insider-trading model, solved for z by bisection.
* ``power`` — p_i = raw_i ** k with k solved so that the probabilities sum to one.

All functions are vectorised over rows and return NaN for a row when any required odds is
missing or invalid (<= 1.0), so a partially quoted market never produces a fake probability.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from ..data.schema import BOOKMAKER_1X2_PREFIXES

VALID_METHODS = ("proportional", "shin", "power")
MIN_OVERROUND = 0.98  # below this the "market" is an arbitrage => data error


def implied_probabilities(odds: np.ndarray, min_odds: float = 1.01, max_odds: float = 200.0) -> np.ndarray:
    """1/odds with invalid quotes turned into NaN."""
    arr = np.asarray(odds, dtype=float)
    with np.errstate(divide="ignore", invalid="ignore"):
        raw = 1.0 / arr
    bad = ~np.isfinite(arr) | (arr < min_odds) | (arr > max_odds)
    raw = np.where(bad, np.nan, raw)
    return raw


def _proportional(raw: np.ndarray) -> np.ndarray:
    total = raw.sum(axis=1, keepdims=True)
    return raw / total


def _power(raw: np.ndarray, iters: int = 60) -> np.ndarray:
    out = np.full_like(raw, np.nan)
    for i in range(raw.shape[0]):
        r = raw[i]
        if not np.all(np.isfinite(r)):
            continue
        lo, hi = 0.5, 3.0  # exponent bracket
        for _ in range(iters):
            k = (lo + hi) / 2
            s = np.sum(r ** k)
            if s > 1.0:
                lo = k
            else:
                hi = k
        out[i] = r ** ((lo + hi) / 2)
        out[i] /= out[i].sum()
    return out


def _shin(raw: np.ndarray, iters: int = 60) -> np.ndarray:
    """Shin (1993): p_i = (sqrt(z^2 + 4(1-z) raw_i^2 / total) - z) / (2(1-z)), z solved so sum p = 1."""
    out = np.full_like(raw, np.nan)
    for i in range(raw.shape[0]):
        r = raw[i]
        if not np.all(np.isfinite(r)):
            continue
        total = r.sum()
        if total <= 1.0:  # no margin -> proportional is exact
            out[i] = r / total
            continue

        def probs(z: float) -> np.ndarray:
            return (np.sqrt(z * z + 4 * (1 - z) * r * r / total) - z) / (2 * (1 - z))

        lo, hi = 0.0, 0.5
        for _ in range(iters):
            z = (lo + hi) / 2
            if probs(z).sum() > 1.0:
                lo = z
            else:
                hi = z
        p = probs((lo + hi) / 2)
        out[i] = p / p.sum()
    return out


def remove_margin(raw: np.ndarray, method: str = "proportional") -> np.ndarray:
    """Normalise raw implied probabilities row-wise. Rows with any NaN stay NaN."""
    raw = np.asarray(raw, dtype=float)
    if raw.ndim == 1:
        raw = raw[None, :]
    if method not in VALID_METHODS:
        raise ValueError(f"unknown normalisation method {method!r}; expected one of {VALID_METHODS}")
    complete = np.all(np.isfinite(raw), axis=1)
    out = np.full_like(raw, np.nan)
    if complete.any():
        sub = raw[complete]
        if method == "proportional":
            out[complete] = _proportional(sub)
        elif method == "power":
            out[complete] = _power(sub)
        else:
            out[complete] = _shin(sub)
    return out


def overround(raw: np.ndarray) -> np.ndarray:
    raw = np.asarray(raw, dtype=float)
    if raw.ndim == 1:
        raw = raw[None, :]
    return raw.sum(axis=1)


# --------------------------------------------------------------------------- consensus

def consensus_1x2(df: pd.DataFrame) -> pd.DataFrame:
    """Consensus 1X2 odds: market average (AvgH/BbAvH) when present, else the row-wise mean
    of the individual bookmakers listed in `BOOKMAKER_1X2_PREFIXES` (raw__ columns)."""
    out = pd.DataFrame(index=df.index)
    avg = df[["avg_h", "avg_d", "avg_a"]].to_numpy(dtype=float)
    have_avg = np.all(np.isfinite(avg), axis=1)

    # bookmakers that quote all three outcomes in this frame
    prefixes = [p for p in BOOKMAKER_1X2_PREFIXES
                if all(f"raw__{p}{s}" in df.columns for s in ("H", "D", "A"))]
    means = np.full((len(df), 3), np.nan)
    n_books = np.zeros(len(df), dtype=int)
    if prefixes:
        blocks = []
        for suffix in ("H", "D", "A"):
            block = df[[f"raw__{p}{suffix}" for p in prefixes]].to_numpy(dtype=float)
            block = np.where(np.isfinite(block) & (block >= 1.01), block, np.nan)
            blocks.append(block)
        # only use a bookmaker on a row when it quotes all three outcomes there
        quoted = np.all([np.isfinite(b) for b in blocks], axis=0)
        n_books = quoted.sum(axis=1)
        with np.errstate(invalid="ignore"):
            for j, block in enumerate(blocks):
                masked = np.where(quoted, block, np.nan)
                means[:, j] = np.where(n_books > 0, np.nanmean(np.where(n_books[:, None] > 0, masked, 1.0), axis=1), np.nan)
    have_books = np.all(np.isfinite(means), axis=1)

    cons = np.where(have_avg[:, None], avg, means)
    out["cons_h"], out["cons_d"], out["cons_a"] = cons[:, 0], cons[:, 1], cons[:, 2]
    source = np.where(have_avg, "avg", np.where(have_books, "books_mean", "none"))
    out["consensus_source"] = source
    out["n_books_used"] = np.where(have_avg, df["n_books_1x2"].fillna(0).to_numpy(dtype=float), n_books)
    return out


def market_block(df: pd.DataFrame, cols: tuple[str, ...], names: tuple[str, ...], method: str,
                 min_odds: float, max_odds: float, max_overround: float | None = None) -> pd.DataFrame:
    """Raw + normalised probabilities for one market (e.g. cols=('cons_h','cons_d','cons_a'))."""
    raw = implied_probabilities(df[list(cols)].to_numpy(dtype=float), min_odds, max_odds)
    ov = overround(raw)
    # a consensus market whose implied probabilities sum to < 1 (arbitrage) or far above the usual
    # margin is a data error (swapped/missing columns), not a real market
    bad = ov < MIN_OVERROUND
    if max_overround is not None:
        bad |= ov > max_overround
    raw[bad] = np.nan
    ov = np.where(bad, np.nan, ov)
    probs = remove_margin(raw, method)
    out = pd.DataFrame(index=df.index)
    for j, name in enumerate(names):
        out[f"raw_p_{name}"] = raw[:, j]
        out[f"p_{name}"] = probs[:, j]
    out["overround"] = ov
    return out


def add_market_features(df: pd.DataFrame, method: str = "proportional", min_odds: float = 1.01,
                        max_odds: float = 200.0, max_overround: float = 1.30) -> pd.DataFrame:
    """Append consensus odds, margin-free probabilities and derived market features."""
    df = df.copy()
    cons = consensus_1x2(df)
    for c in cons.columns:
        df[c] = cons[c].to_numpy()

    m = market_block(df, ("cons_h", "cons_d", "cons_a"), ("home", "draw", "away"), method, min_odds, max_odds, max_overround)
    df["raw_p_home"], df["raw_p_draw"], df["raw_p_away"] = m["raw_p_home"], m["raw_p_draw"], m["raw_p_away"]
    df["p_home"], df["p_draw"], df["p_away"] = m["p_home"], m["p_draw"], m["p_away"]
    df["overround_1x2"] = m["overround"]
    df["has_1x2"] = df["p_home"].notna()

    # Over/Under 2.5: market average first, else Bet365, else Pinnacle
    o25 = df["avg_o25"].where(df["avg_o25"].notna(), df["b365_o25"]).where(lambda s: s.notna(), df["p_o25"])
    u25 = df["avg_u25"].where(df["avg_u25"].notna(), df["b365_u25"]).where(lambda s: s.notna(), df["p_u25"])
    df["cons_o25"], df["cons_u25"] = o25, u25
    df["ou_source"] = np.where(df["avg_o25"].notna(), "avg", np.where(df["b365_o25"].notna(), "b365",
                               np.where(df["p_o25"].notna(), "pinnacle", "none")))
    ou = market_block(df, ("cons_o25", "cons_u25"), ("over25", "under25"), method, min_odds, max_odds, 1.25)
    df["p_over25"], df["p_under25"], df["overround_ou"] = ou["p_over25"], ou["p_under25"], ou["overround"]
    df["has_ou"] = df["p_over25"].notna()

    # Closing 1X2 (2019/20+)
    cl = market_block(df, ("avgc_h", "avgc_d", "avgc_a"), ("home", "draw", "away"), method, min_odds, max_odds, max_overround)
    df["pc_home"], df["pc_draw"], df["pc_away"] = cl["p_home"], cl["p_draw"], cl["p_away"]
    df["has_closing"] = df["pc_home"].notna()
    for o in ("home", "draw", "away"):
        df[f"delta_p_{o}"] = df[f"pc_{o}"] - df[f"p_{o}"]

    # Pinnacle (pre-closing + closing) as a sharper benchmark where available
    ps = market_block(df, ("ps_h", "ps_d", "ps_a"), ("home", "draw", "away"), method, min_odds, max_odds, max_overround)
    df["pin_p_home"], df["pin_p_draw"], df["pin_p_away"] = ps["p_home"], ps["p_draw"], ps["p_away"]
    psc = market_block(df, ("psc_h", "psc_d", "psc_a"), ("home", "draw", "away"), method, min_odds, max_odds, max_overround)
    df["pinc_p_home"], df["pinc_p_draw"], df["pinc_p_away"] = psc["p_home"], psc["p_draw"], psc["p_away"]

    # Asian handicap: line + margin-free home side probability
    ah = market_block(df, ("avg_ahh", "avg_aha"), ("ah_home", "ah_away"), method, min_odds, max_odds, 1.25)
    df["p_ah_home"] = ah["p_ah_home"]
    df["has_ah"] = df["p_ah_home"].notna() & df["ah_line"].notna()
    return df
