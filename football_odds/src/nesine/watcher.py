"""Keep the nesine odds live and remember how they moved.

Odds drift as kick-off approaches and several of the notes depend on the exact number (note 5's
1.64, note 11's 23–25 window, note 16's 1.65/1.67/1.75), so a bulletin fetched once an hour is
worse than useless — it can show a rule firing on a price that is gone. A background thread
therefore refreshes the bulletin on an interval that tightens as matches get close:

    a match kicks off within 45 min ->  60 s
    within 3 hours                  -> 180 s
    otherwise                       -> 600 s
    nothing in the bulletin         -> 900 s

Every refresh records the prices of the markets the notes use, so each match carries its opening
price, its previous price and when it last changed. The store is a small JSON on the results
directory (the mounted volume on Railway), pruned to matches that have not kicked off yet.

Environment:
    FO_NESINE_WATCH   0/false turns the thread off (default on)
    FO_NESINE_MIN_S   floor for the refresh interval in seconds (default 30)
"""

from __future__ import annotations

import datetime as dt
import json
import os
import threading
import time
from pathlib import Path
from typing import Any

from ..config import Settings
from ..logging_setup import get_logger
from .bulletin import load_matches

log = get_logger("nesine.watcher")

# the prices the notes actually read; anything else would only bloat the store
TRACKED: tuple[str, ...] = (
    "ms.1", "ms.X", "ms.2", "o25.alt", "o25.ust", "o35.ust", "o45.ust",
    "iy.1", "iy.X", "iy.2", "iy05.alt", "iy05.ust", "iy_kg.var", "y2_kg.var",
    "iyms.1/2", "iyms.2/1", "iy_skor.diger", "skor.diger",
    "iki_yari_15_ust.evet", "iy_y2_kg.evet/evet", "iy_sonucu_kg.1&var", "iy_sonucu_kg.2&var",
    "ilk_gol.1", "ilk_gol.2",
)
MAX_POINTS = 12          # per price: the opening one plus the last eleven changes
NEAR_S = 45 * 60
SOON_S = 3 * 3600
INTERVALS = {"near": 60, "soon": 180, "far": 600, "idle": 900}


def value_at(m: dict, path: str) -> float | None:
    group, _, key = path.partition(".")
    g = m.get(group)
    v = g.get(key) if isinstance(g, dict) else None
    return float(v) if isinstance(v, (int, float)) else None


def store_path(settings: Settings) -> Path:
    return settings.results_dir / "nesine_moves.json"


def load_store(settings: Settings) -> dict:
    p = store_path(settings)
    try:
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {"matches": {}}
    except (json.JSONDecodeError, OSError):
        return {"matches": {}}


def save_store(settings: Settings, store: dict) -> None:
    p = store_path(settings)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(store, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    tmp.replace(p)


def kickoff(m: dict) -> dt.datetime | None:
    """Kick-off as an aware UTC datetime; nesine's date and time are Turkey local."""
    try:
        from zoneinfo import ZoneInfo

        naive = dt.datetime.strptime(f"{m['date']} {m['time'][:5]}", "%Y-%m-%d %H:%M")
        return naive.replace(tzinfo=ZoneInfo("Europe/Istanbul")).astimezone(dt.timezone.utc)
    except (ValueError, KeyError, TypeError):
        return None


def record(store: dict, matches: list[dict], now: dt.datetime | None = None) -> dict:
    """Append changed prices to the store and forget matches the bulletin no longer carries."""
    now = now or dt.datetime.now(dt.timezone.utc)
    stamp = now.isoformat(timespec="seconds")
    out = store.setdefault("matches", {})
    seen = set()
    for m in matches:
        code = str(m.get("code"))
        seen.add(code)
        entry = out.setdefault(code, {"first_seen": stamp, "odds": {}})
        for path in TRACKED:
            v = value_at(m, path)
            if v is None:
                continue
            points = entry["odds"].setdefault(path, [])
            if points and abs(points[-1][1] - v) < 1e-9:
                continue                      # unchanged: nothing to store
            points.append([stamp, v])
            if len(points) > MAX_POINTS:
                del points[0:len(points) - MAX_POINTS]
    # forget matches that are no longer in the bulletin (played or pulled)
    for code in [c for c in out if c not in seen]:
        del out[code]
    store["updated_at"] = stamp
    return store


def movement(store: dict, code: int | str, changed_only: bool = False) -> dict[str, dict]:
    """{path: {open, prev, now, dir, changed_at, n}} for one match.

    With ``changed_only`` the prices that never moved are left out — that is most of them, and the
    frontend has nothing to draw for them.
    """
    entry = (store.get("matches") or {}).get(str(code))
    if not entry:
        return {}
    out: dict[str, dict] = {}
    for path, points in (entry.get("odds") or {}).items():
        if not points or (changed_only and len(points) < 2):
            continue
        first, last = points[0], points[-1]
        prev = points[-2] if len(points) > 1 else None
        d = 0
        if prev is not None:
            d = 1 if last[1] > prev[1] else -1 if last[1] < prev[1] else 0
        out[path] = {"open": first[1], "now": last[1], "prev": prev[1] if prev else None,
                     "dir": d, "changed_at": last[0] if prev else None, "n": len(points)}
    return out


def interval_for(matches: list[dict], now: dt.datetime | None = None) -> int:
    now = now or dt.datetime.now(dt.timezone.utc)
    if not matches:
        return INTERVALS["idle"]
    gaps = [(k - now).total_seconds() for k in (kickoff(m) for m in matches) if k is not None]
    upcoming = [g for g in gaps if g > -900]      # a match that started 15 min ago is no longer ours
    if not upcoming:
        return INTERVALS["idle"]
    soonest = min(upcoming)
    if soonest <= NEAR_S:
        return INTERVALS["near"]
    if soonest <= SOON_S:
        return INTERVALS["soon"]
    return INTERVALS["far"]


# --------------------------------------------------------------------------- the thread

_state: dict[str, Any] = {"thread": None, "last": None, "error": None, "interval": None, "n": 0, "runs": 0}
_lock = threading.Lock()


def status() -> dict:
    with _lock:
        out = {k: v for k, v in _state.items() if k != "thread"}
        out["running"] = _state["thread"] is not None and _state["thread"].is_alive()
    return out


def refresh_once(settings: Settings) -> tuple[list[dict], dict]:
    matches, meta = load_matches(settings, force=True)
    store = record(load_store(settings), matches)
    save_store(settings, store)
    with _lock:
        _state.update(last=meta.get("fetched_at"), error=meta.get("error"), n=len(matches), runs=_state["runs"] + 1)
    return matches, meta


def _loop(settings: Settings, min_interval: int) -> None:
    while True:
        wait = INTERVALS["idle"]
        try:
            matches, _ = refresh_once(settings)
            wait = max(min_interval, interval_for(matches))
        except Exception as exc:  # noqa: BLE001 - the watcher must never die
            log.warning("nesine refresh failed: %s", exc)
            with _lock:
                _state["error"] = str(exc)
            wait = max(min_interval, 120)
        with _lock:
            _state["interval"] = wait
        time.sleep(wait)


def start(settings: Settings, min_interval: int = 30) -> threading.Thread | None:
    """Start the refresher once per process."""
    with _lock:
        if _state["thread"] is not None and _state["thread"].is_alive():
            return _state["thread"]
        t = threading.Thread(target=_loop, args=(settings, min_interval), name="nesine-watcher", daemon=True)
        _state["thread"] = t
    t.start()
    log.info("nesine watcher started")
    return t


def enabled() -> bool:
    return os.environ.get("FO_NESINE_WATCH", "1").strip().lower() not in ("0", "false", "no", "off")


def start_if_enabled(settings: Settings) -> threading.Thread | None:
    """Called from the web app as well as from serve.py, so odds stay live under any entry point."""
    if not enabled():
        return None
    return start(settings, min_interval=int(os.environ.get("FO_NESINE_MIN_S", "30")))
