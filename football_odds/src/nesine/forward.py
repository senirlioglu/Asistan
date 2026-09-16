"""FORWARD TEST — freeze the movement verdict before kick-off, settle it afterwards.

Every backtest in this project is walk-forward, and every one of them still has the same weakness:
the code that produced the verdict was written after the matches it is scored on. A movement
classification is worse than that, because the trajectory it reads is only complete once the match
has started — so the temptation to "reclassify with hindsight" is built into the data.

This module removes the temptation. Shortly before kick-off the verdict is computed and written to
an append-only file with the timestamp it was made at. After the match the result is appended as a
SEPARATE line. Nothing is ever rewritten, so a classification cannot be quietly improved once the
outcome is known:

    results/forward/movement.jsonl
        {"k":"freeze","ts",...,"code","home","away","league","kickoff","market","sel":{path:{...}}}
        {"k":"settle","ts",...,"code","ftr","fthg","ftag","match_id"}

The freeze is the part that cannot be repaired later: a match that kicks off unfrozen is a forward
test that can never be run, however much history the archive accumulates afterwards. Settling, by
contrast, can happen any time the result turns up.

Sample floors live in `MovementConfig` (min_display_n / min_research_n / min_validation_n) and this
module refuses to summarise below them rather than reporting a rate on fourteen matches.
"""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

from ..config import Settings
from ..logging_setup import get_logger
from . import movement as mv
from .watcher import kickoff, value_at

log = get_logger("nesine.forward")

LEAD_MIN = 25          # freeze this many minutes before kick-off: late enough to have the run-up,
MIN_LEAD_MIN = 2       # early enough that the match has not started while we were computing it
PATHS = ("ms.1", "ms.X", "ms.2")


def store_path(settings: Settings) -> Path:
    return settings.results_dir / "forward" / "movement.jsonl"


def _append(settings: Settings, rows: list[dict]) -> int:
    if not rows:
        return 0
    p = store_path(settings)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False, separators=(",", ":")) + "\n")
    return len(rows)


def load(settings: Settings, kind: str | None = None) -> list[dict]:
    p = store_path(settings)
    if not p.exists():
        return []
    out = []
    for line in p.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if kind is None or row.get("k") == kind:
            out.append(row)
    return out


def frozen_codes(settings: Settings) -> set[int]:
    return {int(r["code"]) for r in load(settings, "freeze") if r.get("code") is not None}


def settled_codes(settings: Settings) -> set[int]:
    return {int(r["code"]) for r in load(settings, "settle") if r.get("code") is not None}


def freeze_due(settings: Settings, matches: list[dict], now: dt.datetime | None = None,
               lead_min: int = LEAD_MIN, cfg: mv.MovementConfig | None = None) -> int:
    """Freeze the verdict for every match about to kick off that has not been frozen yet.

    Called from the watcher loop, which already runs every minute once something is close. A match
    is frozen once and never again — a second look would be a second opinion, and the whole point is
    that there is only one."""
    now = now or dt.datetime.now(dt.timezone.utc)
    cfg = cfg or mv.config_from_env()
    done = frozen_codes(settings)
    rows = []
    for m in matches:
        code = m.get("code")
        if code is None or int(code) in done:
            continue
        ko = kickoff(m)
        if ko is None:
            continue
        left = (ko - now).total_seconds() / 60
        if not (MIN_LEAD_MIN <= left <= lead_min):
            continue
        series = mv.trajectory(settings, int(code), as_of=now, meta=m)
        sel = {}
        for path in PATHS:
            s = series.get(path)
            if s is None:
                continue
            w = mv.window_features(s, cfg)
            ocp = mv.open_current_close(s, started=False)
            sel[path] = {
                "movement": mv.classify(s, cfg, windows=w),
                "open_p": (ocp["open"] or {}).get("p"), "now_p": (ocp["current"] or {}).get("p"),
                "odds": (ocp["current"] or {}).get("odds"),
                "windows": {k: w[k].get("delta_p") for k, _ in mv.WINDOWS},
                **mv.velocities(w),
                "quality": mv.coverage(settings, s, as_of=now),
            }
        if not sel:
            continue
        rows.append({
            "k": "freeze", "ts": now.isoformat(timespec="seconds"), "code": int(code),
            "home": m.get("home"), "away": m.get("away"), "league": m.get("league"),
            "kickoff": ko.isoformat(), "minutes_left": round(left),
            "market": {p: value_at(m, p) for p in PATHS},
            "config": cfg.as_dict(), "sel": sel,
        })
    n = _append(settings, rows)
    if n:
        log.info("forward: froze %d match(es) before kick-off", n)
    return n


def settle(settings: Settings, df=None, now: dt.datetime | None = None) -> int:
    """Attach the result to every frozen match that has one, as a new line.

    The frozen verdict is never touched. Matching nesine's spelling to ours reuses the resolver the
    notes already run on (`history.TeamIndex`) rather than a second one that could disagree."""
    import pandas as pd

    from .history import TeamIndex, load_history

    now = now or dt.datetime.now(dt.timezone.utc)
    pending = [r for r in load(settings, "freeze") if int(r["code"]) not in settled_codes(settings)]
    if not pending:
        return 0
    df = load_history(settings) if df is None else df
    if df is None or not len(df):
        return 0
    index = TeamIndex(df)
    rows = []
    for r in pending:
        ko = dt.datetime.fromisoformat(r["kickoff"])
        if (now - ko).total_seconds() < 3 * 3600:        # not finished yet; try again next time
            continue
        home, away = index.resolve(r.get("home") or ""), index.resolve(r.get("away") or "")
        if not home or not away:
            continue
        day = pd.Timestamp(ko.date())
        hit = df[(df["home_team"] == home) & (df["away_team"] == away)
                 & (df["date"] >= day - pd.Timedelta(days=2)) & (df["date"] <= day + pd.Timedelta(days=2))]
        if hit.empty:
            continue
        m = hit.sort_values("date").iloc[-1]
        rows.append({"k": "settle", "ts": now.isoformat(timespec="seconds"), "code": int(r["code"]),
                     "match_id": str(m.get("match_id", "")), "ftr": str(m["ftr"]),
                     "fthg": _i(m.get("fthg")), "ftag": _i(m.get("ftag")),
                     "home_team": home, "away_team": away, "date": str(m["date"])[:10]})
    n = _append(settings, rows)
    if n:
        log.info("forward: settled %d match(es)", n)
    return n


def _i(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def summary(settings: Settings, cfg: mv.MovementConfig | None = None) -> dict:
    """What the forward test can say yet — usually "not enough matches", and that is the answer.

    Nothing here is presented as a rate until the sample clears `min_display_n`. A movement class
    that came in at 71 % on fourteen matches is a coin landing the same way fourteen times; naming
    it is how a research tool turns into a tipster."""
    cfg = cfg or mv.config_from_env()
    frozen = {int(r["code"]): r for r in load(settings, "freeze")}
    results = {int(r["code"]): r for r in load(settings, "settle")}
    per: dict[str, dict] = {}
    for code, r in frozen.items():
        res = results.get(code)
        for path, s in (r.get("sel") or {}).items():
            kind = (s.get("movement") or {}).get("type")
            if not kind:
                continue
            row = per.setdefault(kind, {"n_frozen": 0, "n_settled": 0, "hits": 0, "market_sum": 0.0})
            row["n_frozen"] += 1
            if not res:
                continue
            want = {"ms.1": "H", "ms.X": "D", "ms.2": "A"}[path]
            row["n_settled"] += 1
            row["hits"] += int(res.get("ftr") == want)
            if s.get("now_p") is not None:
                row["market_sum"] += float(s["now_p"])
    out = []
    for kind, row in sorted(per.items()):
        n = row["n_settled"]
        enough = n >= cfg.min_display_n
        out.append({
            "type": kind, "n_frozen": row["n_frozen"], "n_settled": n,
            "actual": round(100 * row["hits"] / n, 1) if (enough and n) else None,
            "market": round(row["market_sum"] / n, 1) if (enough and n) else None,
            "enough": enough,
        })
    first = min((r["ts"] for r in load(settings, "freeze")), default=None)
    return {"since": first, "rows": out, "floors": {"display": cfg.min_display_n,
                                                    "research": cfg.min_research_n,
                                                    "validation": cfg.min_validation_n},
            "n_frozen": len(frozen), "n_settled": len(results)}
