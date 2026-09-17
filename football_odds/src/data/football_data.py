"""Football-Data.co.uk downloader, cache and parser.

URL pattern: ``https://www.football-data.co.uk/mmz4281/<season>/<div>.csv`` (e.g. ``2425/E0.csv``).
Fixtures with pre-match odds: ``https://www.football-data.co.uk/fixtures.csv``.

Cache policy
------------
* Raw CSVs live in ``data/raw/<season>/<div>.csv`` next to a ``<div>.meta.json``.
* Completed seasons are never re-downloaded unless ``force=True``.
* The current season (and any season code >= the current one) is refreshed when the cached
  copy is older than ``data.refresh_hours``.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import io
import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd
import requests

from ..config import Settings, current_season_code, extra_season_code, season_start_year
from ..logging_setup import get_logger
from .schema import BOOKMAKER_1X2_PREFIXES, CANONICAL_COLUMNS, numeric_canonical_columns

log = get_logger("data.football_data")

USER_AGENT = "football-odds-similarity/0.1 (+research; contact via repo)"


@dataclass
class DownloadResult:
    season: str
    league: str
    path: Path
    downloaded: bool
    status: str  # "downloaded" | "cached" | "failed" | "empty"
    size: int = 0
    error: str | None = None


# --------------------------------------------------------------------------- HTTP

def _http_get(url: str, timeout: int, retries: int) -> bytes:
    last_err: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            resp = requests.get(url, timeout=timeout, headers={"User-Agent": USER_AGENT}, allow_redirects=True)
            if resp.status_code == 404:
                raise FileNotFoundError(url)
            resp.raise_for_status()
            return resp.content
        except FileNotFoundError:
            raise
        except Exception as exc:  # noqa: BLE001 - we retry on anything transient
            last_err = exc
            wait = 2 ** attempt
            log.warning("GET %s failed (%s), retry %d/%d in %ss", url, exc, attempt, retries, wait)
            time.sleep(wait)
    raise RuntimeError(f"GET {url} failed after {retries} attempts: {last_err}")


def season_url(settings: Settings, season: str, league: str) -> str:
    return f"{settings.get('data.base_url').rstrip('/')}/mmz4281/{season}/{league}.csv"


def extra_url(settings: Settings, league: str) -> str:
    meta = settings.extra_leagues[league]
    return f"{settings.get('data.base_url').rstrip('/')}/new/{meta.get('file', league)}.csv"


def raw_path(settings: Settings, season: str, league: str) -> Path:
    """Cache path. Extra leagues have ONE file for every season, so `season` is ignored for them."""
    if settings.is_extra_league(league):
        return settings.raw_dir / "new" / f"{settings.extra_leagues[league].get('file', league)}.csv"
    return settings.raw_dir / season / f"{league}.csv"


def _needs_refresh(path: Path, season: str, refresh_hours: float, today: dt.date | None = None) -> bool:
    if not path.exists() or path.stat().st_size == 0:
        return True
    if season < current_season_code(today):
        return False
    age_h = (time.time() - path.stat().st_mtime) / 3600.0
    return age_h > refresh_hours


def download_season_file(settings: Settings, season: str, league: str, force: bool = False) -> DownloadResult:
    path = raw_path(settings, season, league)
    extra = settings.is_extra_league(league)
    # an extra file always contains the running season -> it follows the current-season refresh rule
    refresh_season = current_season_code() if extra else season
    if not force and not _needs_refresh(path, refresh_season, float(settings.get("data.refresh_hours", 12))):
        return DownloadResult(season, league, path, False, "cached", path.stat().st_size)
    url = extra_url(settings, league) if extra else season_url(settings, season, league)
    try:
        content = _http_get(url, int(settings.get("data.http_timeout_s", 60)), int(settings.get("data.http_retries", 3)))
    except FileNotFoundError:
        return DownloadResult(season, league, path, False, "failed", 0, "404 not found")
    except Exception as exc:  # noqa: BLE001
        return DownloadResult(season, league, path, False, "failed", 0, str(exc))
    if len(content) < 50:
        return DownloadResult(season, league, path, False, "empty", len(content), "empty response")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    meta = {
        "url": url,
        "fetched_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "size": len(content),
        "sha1": hashlib.sha1(content).hexdigest(),
    }
    path.with_suffix(".meta.json").write_text(json.dumps(meta, indent=2))
    return DownloadResult(season, league, path, True, "downloaded", len(content))


def download_all(settings: Settings, seasons: Iterable[str] | None = None, leagues: Iterable[str] | None = None,
                 force: bool = False) -> list[DownloadResult]:
    seasons = list(seasons or settings.seasons)
    leagues = list(leagues or settings.active_leagues)
    results: list[DownloadResult] = []
    # (season, league) pairs: one file per season for the main divisions, one file in total per extra league
    jobs = [(s, lg) for s in seasons for lg in leagues if not settings.is_extra_league(lg)]
    jobs += [("all", lg) for lg in leagues if settings.is_extra_league(lg)]
    for season, league in jobs:
        res = download_season_file(settings, season, league, force=force)
        results.append(res)
        if res.status == "downloaded":
            log.info("downloaded %s/%s (%d bytes)", season, league, res.size)
        elif res.status in ("failed", "empty"):
            log.warning("%s/%s: %s", season, league, res.error)
    n_dl = sum(r.status == "downloaded" for r in results)
    n_cached = sum(r.status == "cached" for r in results)
    n_fail = sum(r.status in ("failed", "empty") for r in results)
    log.info("download summary: %d downloaded, %d cached, %d failed", n_dl, n_cached, n_fail)
    return results


def download_fixtures(settings: Settings, force: bool = False, max_age_hours: float = 1.0, url: str | None = None,
                      name: str = "fixtures.csv") -> Path:
    path = settings.raw_dir / name
    if path.exists() and not force:
        age_h = (time.time() - path.stat().st_mtime) / 3600.0
        if age_h < max_age_hours:
            return path
    try:
        content = _http_get(url or settings.get("current.fixtures_url"), int(settings.get("data.http_timeout_s", 60)),
                            int(settings.get("data.http_retries", 3)))
    except Exception as exc:  # noqa: BLE001 - the source is down or misrouted: the last file we have beats no file
        if not path.exists():
            raise
        age_h = (time.time() - path.stat().st_mtime) / 3600.0
        # 17 Sep 2026: football-data.co.uk answered every request with a redirect to http://127.0.0.1/ for
        # hours; the daily job died on this line and nothing after it (state table, cycle pairs, notes)
        # ran. A stale fixture list is a known, visible degradation; an aborted job is a silent one.
        log.warning("%s: download failed (%s); using the cached file from %.1f h ago", name, exc, age_h)
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


# --------------------------------------------------------------------------- parsing

def read_raw_csv(path: Path) -> pd.DataFrame:
    """Read a Football-Data CSV robustly (BOM, latin-1 fallback, trailing empty columns)."""
    data = path.read_bytes()
    for enc in ("utf-8-sig", "latin-1"):
        try:
            text = data.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    else:  # pragma: no cover
        text = data.decode("utf-8", errors="replace")
    # index_col=False: rows with a trailing comma must not turn the first column into the index
    df = pd.read_csv(io.StringIO(text), dtype=str, keep_default_na=True, na_values=["", " ", "NA", "#N/A"],
                     on_bad_lines="skip", engine="python", index_col=False)
    df = df.loc[:, [c for c in df.columns if not str(c).startswith("Unnamed")]]
    df.columns = [str(c).strip().lstrip("﻿") for c in df.columns]
    return df


def parse_dates(series: pd.Series) -> pd.Series:
    s = series.astype("string").str.strip()
    out = pd.to_datetime(s, format="%d/%m/%Y", errors="coerce")
    missing = out.isna() & s.notna()
    if missing.any():
        out2 = pd.to_datetime(s[missing], format="%d/%m/%y", errors="coerce")
        out = out.copy()
        out[missing] = out2
    return out


def map_columns(df: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, str]]:
    """Rename raw columns to canonical names. Returns (frame, {canonical: source})."""
    mapping: dict[str, str] = {}
    columns: dict[str, pd.Series] = {}
    for canonical, candidates in CANONICAL_COLUMNS.items():
        for cand in candidates:
            if cand in df.columns:
                columns[canonical] = df[cand]
                mapping[canonical] = cand
                break
        else:
            columns[canonical] = pd.Series(np.nan, index=df.index)
    # keep the individual bookmaker 1X2 columns for consensus fallback (raw names)
    for prefix in BOOKMAKER_1X2_PREFIXES:
        for suffix in ("H", "D", "A"):
            col = f"{prefix}{suffix}"
            if col in df.columns:
                columns[f"raw__{col}"] = df[col]
    out = pd.DataFrame(columns, index=df.index)
    return out, mapping


def normalise_frame(df: pd.DataFrame, season: str, league: str) -> pd.DataFrame:
    """Canonical frame for one raw file: typed columns, season/league, match_id."""
    mapped, _ = map_columns(df)
    mapped = mapped[mapped["home_team"].notna() & mapped["away_team"].notna()].copy()
    mapped["date"] = parse_dates(mapped["date"])
    mapped = mapped[mapped["date"].notna()].copy()
    # convert in bulk (one block per dtype) instead of column by column, which fragments the frame
    num_cols = numeric_canonical_columns() + [c for c in mapped.columns if c.startswith("raw__")]
    mapped[num_cols] = mapped[num_cols].apply(pd.to_numeric, errors="coerce")
    text_cols = ["home_team", "away_team", "ftr", "htr", "time"]
    mapped[text_cols] = mapped[text_cols].apply(lambda s: s.astype("string").str.strip())
    mapped = mapped.copy()
    mapped["league"] = league
    mapped["season"] = season
    mapped["season_start_year"] = season_start_year(season)
    mapped["div"] = mapped["div"].fillna(league)
    mapped["match_id"] = [
        hashlib.sha1(f"{league}|{d:%Y-%m-%d}|{h}|{a}".encode("utf-8")).hexdigest()[:16]
        for d, h, a in zip(mapped["date"], mapped["home_team"], mapped["away_team"])
    ]
    return mapped.reset_index(drop=True)


def normalise_extra_frame(raw: pd.DataFrame, league: str, meta: dict, season_start_years: set[int] | None = None) -> pd.DataFrame:
    """Canonical frame for an extra-league file (Country/League/Season columns, every season in one file).

    Keeps the rows of `meta['fd_league']` (or every competition when null), maps the Season strings to
    our codes ('2016/2017' -> '1617', '2015' -> 'Y2015') and normalises each season like a main file."""
    raw = raw.copy()
    raw.columns = [str(c).strip() for c in raw.columns]
    want = meta.get("fd_league")
    if want and "League" in raw.columns:
        raw = raw[raw["League"].astype(str).str.strip() == str(want).strip()]
    codes = raw["Season"].map(extra_season_code) if "Season" in raw.columns else pd.Series(None, index=raw.index, dtype="object")
    raw = raw.assign(_season=codes)[codes.notna()]
    if season_start_years:
        raw = raw[raw["_season"].map(season_start_year).isin(season_start_years)]
    parts = [normalise_frame(part.drop(columns=["_season"]), str(code), league) for code, part in raw.groupby("_season", sort=True)]
    return pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()


def load_raw_extra_league(settings: Settings, league: str) -> pd.DataFrame | None:
    path = raw_path(settings, "all", league)
    if not path.exists() or path.stat().st_size == 0:
        return None
    try:
        raw = read_raw_csv(path)
    except Exception as exc:  # noqa: BLE001
        log.error("cannot parse %s: %s", path, exc)
        return None
    if raw.empty:
        return None
    years = {season_start_year(s) for s in settings.seasons}
    df = normalise_extra_frame(raw, league, settings.extra_leagues[league], years)
    return df if not df.empty else None


def load_raw_season(settings: Settings, season: str, league: str) -> pd.DataFrame | None:
    if settings.is_extra_league(league):
        df = load_raw_extra_league(settings, league)
        if df is None:
            return None
        part = df[df["season"] == season]
        return part.reset_index(drop=True) if not part.empty else None
    path = raw_path(settings, season, league)
    if not path.exists() or path.stat().st_size == 0:
        return None
    try:
        raw = read_raw_csv(path)
    except Exception as exc:  # noqa: BLE001
        log.error("cannot parse %s: %s", path, exc)
        return None
    if raw.empty:
        return None
    return normalise_frame(raw, season, league)


def raw_headers(settings: Settings, season: str, league: str) -> list[str] | None:
    path = raw_path(settings, season, league)
    if not path.exists() or path.stat().st_size == 0:
        return None
    try:
        return list(read_raw_csv(path).columns)
    except Exception:  # noqa: BLE001
        return None
