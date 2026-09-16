"""Append-only history of every nesine price we have ever seen.

`watcher.py` keeps a *working* view of the odds (the opening price, the last few changes, pruned to
the matches still in the bulletin) — that is what the page draws arrows from. It is deliberately
small and it forgets: a match that kicks off disappears from it.

Research needs the opposite: nothing may be lost. Every changed price is therefore appended to a
plain JSON-lines file, one per UTC day, that is never rewritten:

    results/odds_snapshots/2026-09-16.jsonl        {"ts","c","p","o","m"} per line
    results/odds_snapshots/2026-09-16-matches.json {code: {date,time,home,away,league,league_code}}

`c` is nesine's match code, `p` the odds path ("ms.1"), `o` the price and `m` the minutes left to
kick-off — the field that makes "this moved in the last 30 minutes" answerable later. Team names
live in the per-day meta file instead of on every row, so the lines stay narrow (~70 bytes).

Finished days are gzipped on the next run; `load_day` reads either form. The archive starts the day
this code ships, so it can only ever answer questions about matches from then on — the 15 years of
history in the parquet carry a single pre-close -> close step, nothing finer.
"""

from __future__ import annotations

import datetime as dt
import gzip
import json
from pathlib import Path

from ..config import Settings
from ..logging_setup import get_logger

log = get_logger("nesine.archive")

DIR = "odds_snapshots"


def archive_dir(settings: Settings) -> Path:
    return settings.results_dir / DIR


def day_path(settings: Settings, day: dt.date, gz: bool = False) -> Path:
    return archive_dir(settings) / f"{day.isoformat()}.jsonl{'.gz' if gz else ''}"


def meta_path(settings: Settings, day: dt.date) -> Path:
    return archive_dir(settings) / f"{day.isoformat()}-matches.json"


def _meta_row(m: dict) -> dict:
    return {k: m.get(k) for k in ("date", "time", "home", "away", "league", "league_code")}


def append(settings: Settings, changes: list[dict], matches: list[dict], now: dt.datetime | None = None) -> int:
    """Append this refresh's changed prices; returns how many lines were written."""
    if not changes:
        return 0
    now = now or dt.datetime.now(dt.timezone.utc)
    d = archive_dir(settings)
    d.mkdir(parents=True, exist_ok=True)
    stamp = now.isoformat(timespec="seconds")
    with day_path(settings, now.date()).open("a", encoding="utf-8") as fh:
        for row in changes:
            fh.write(json.dumps({"ts": stamp, **row}, ensure_ascii=False, separators=(",", ":")) + "\n")
    # the teams behind those codes, written once per code per day
    p = meta_path(settings, now.date())
    try:
        meta = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
    except (json.JSONDecodeError, OSError):
        meta = {}
    codes = {str(row["c"]) for row in changes}
    new = {str(m["code"]): _meta_row(m) for m in matches if str(m.get("code")) in codes and str(m["code"]) not in meta}
    if new:
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps({**meta, **new}, ensure_ascii=False), encoding="utf-8")
        tmp.replace(p)
    return len(changes)


def load_day(settings: Settings, day: dt.date) -> list[dict]:
    """Every price change recorded on that UTC day, oldest first (reads the gzipped file too)."""
    for gz in (False, True):
        p = day_path(settings, day, gz=gz)
        if not p.exists():
            continue
        opener = gzip.open if gz else open
        with opener(p, "rt", encoding="utf-8") as fh:
            return [json.loads(line) for line in fh if line.strip()]
    return []


def load_meta(settings: Settings, day: dt.date) -> dict:
    p = meta_path(settings, day)
    try:
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
    except (json.JSONDecodeError, OSError):
        return {}


def compress_old(settings: Settings, today: dt.date | None = None) -> list[Path]:
    """Gzip the day files that are finished (~10x smaller). Today's file stays open for appends."""
    today = today or dt.datetime.now(dt.timezone.utc).date()
    done = []
    for p in sorted(archive_dir(settings).glob("*.jsonl")) if archive_dir(settings).exists() else []:
        if p.stem >= today.isoformat():
            continue
        gz = p.with_suffix(".jsonl.gz")
        try:
            with p.open("rb") as src, gzip.open(gz, "wb") as dst:
                dst.write(src.read())
            p.unlink()
            done.append(gz)
        except OSError as exc:  # noqa: PERF203 - one bad file must not stop the rest
            log.warning("could not compress %s: %s", p, exc)
    return done
