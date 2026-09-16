"""ODDS MOVEMENT ENGINE — what the price did on its way to kick-off, and whether that is a signal.

`archive.py` keeps every price nesine has shown us since 15 September 2026, one line per change.
This module turns those lines back into a time series per selection and measures it. Nothing here
invents data: a window with no snapshot in it returns None rather than a number, and a match with
four snapshots is labelled LOW CONFIDENCE rather than classified.

    archive lines ──► trajectory() ──► per-group series, forward filled
                                  ──► no-vig probability (features/odds.remove_margin)
                                  ──► windows 24h..15m, velocity, acceleration
                                  ──► classify() ──► STEAM / DRIFT / LATE_* / REVERSAL / STABLE

**Probability, not raw odds.** 1.80 -> 1.65 is a different amount of information at different price
levels, and the raw number still carries nesine's margin (17 % in the lower divisions). Every
measurement is therefore in margin-free probability points, computed with the project's own
`remove_margin` rather than a second implementation. A market is only stripped of its margin when
the archive carries *all* of its outcomes; where it carries a subset (the correct-score markets,
where only four of 29 prices are tracked) the series falls back to the raw implied probability and
says so in `novig: false`.

**Only price changes are stored**, so the series is a step function: between two lines the price
held. What the lines alone cannot say is whether a flat stretch means the price held or the watcher
was down — the heartbeat rows (`archive.load_day(runs=True)`) answer that, and `coverage()` turns
them into the number the UI shows next to the verdict.

Thresholds live in `MovementConfig`, not in the code, because "5 % is steam" is a guess until a
backtest has an opinion. Nothing in this module is allowed to hardcode one.
"""

from __future__ import annotations

import datetime as dt
import json
from dataclasses import dataclass, field, replace

import numpy as np

from ..config import Settings
from ..features.odds import remove_margin
from ..logging_setup import get_logger
from . import archive
from .watcher import TRACKED, kickoff

log = get_logger("nesine.movement")

# Groups the archive tracks in full ("group.*" in watcher.TRACKED) can have their margin removed;
# the rest are a subset of the market and a no-vig normalisation over them would be nonsense.
FULL_GROUPS: frozenset[str] = frozenset(spec.split(".")[0] for spec in TRACKED if spec.endswith(".*"))

# minutes before kick-off. 24h first so the widest window is also the fallback "whole history".
WINDOWS: tuple[tuple[str, int], ...] = (("24h", 1440), ("12h", 720), ("6h", 360), ("3h", 180),
                                        ("1h", 60), ("30m", 30), ("15m", 15))
VELOCITY_WINDOWS = ("15m", "30m", "1h", "3h", "6h")


@dataclass(frozen=True)
class MovementConfig:
    """Every threshold the classification uses. A backtest may replace any of them.

    The defaults are deliberately conservative: they were chosen so that an average match comes out
    STABLE, because the alternative — a scheme that labels everything — produces a pattern for every
    match and a signal for none."""

    stable_max_pp: float = 0.75        # below this much total movement: nothing happened
    movement_min_pp: float = 1.5       # at least this much to be called steam or drift
    direction_consistency: float = 0.70  # |net| / path length; below it the move wandered
    reversal_min_pp: float = 1.5       # both legs of a reversal must clear this
    reversal_min_share: float = 0.5    # ...and the leg back must undo this much of the leg out
    late_move_share: float = 0.60      # share of the move inside late_window_min => LATE_*
    late_window_min: int = 60
    accel_ratio: float = 1.5           # late velocity over early velocity
    min_snapshots: int = 4             # fewer than this: LOW CONFIDENCE, no classification
    min_span_min: int = 30             # and the snapshots must span at least this long
    # sample floors for anything built ON TOP of the classification (module 3)
    min_display_n: int = 30
    min_research_n: int = 100
    min_validation_n: int = 300

    def as_dict(self) -> dict:
        return dict(self.__dict__)


DEFAULT_CONFIG = MovementConfig()


@dataclass
class Point:
    """One instant of a selection's price."""

    ts: dt.datetime
    minutes: float | None      # to kick-off; negative once the match has started
    odds: float
    prob: float | None         # margin-free where the whole market is tracked
    changed: bool              # True on a recorded change, False on a forward-filled sample


@dataclass
class Series:
    """One selection's whole trajectory, plus where the archive's knowledge starts and stops."""

    code: int
    group: str
    selection: str
    points: list[Point] = field(default_factory=list)
    novig: bool = True
    kickoff: dt.datetime | None = None

    @property
    def path(self) -> str:
        return f"{self.group}.{self.selection}"

    def before_kickoff(self) -> list[Point]:
        return [p for p in self.points if p.minutes is None or p.minutes >= 0]


# --------------------------------------------------------------------------- reading the archive

_CACHE: dict[str, tuple[int, dict]] = {}       # day file -> (bytes consumed, index built so far)


def _index_day(settings: Settings, day: dt.date) -> dict:
    """{code: {path: [(ts, odds), ...]}} for one archive day, read incrementally.

    Today's file grows every minute and is the one every request needs; re-parsing it each time
    would be the most expensive thing in the request. The cache keeps the byte offset it stopped at
    and parses only the tail. A file that has shrunk (rotated, or gzipped underneath us) fails that
    check and is simply read again from the start."""
    p = archive.day_path(settings, day)
    if not p.exists():                      # finished days are gzipped: no tail to follow
        return _rows_to_index(archive.load_day(settings, day))
    key, size = str(p), p.stat().st_size
    offset, index = _CACHE.get(key, (0, {}))
    if offset > size:                       # the file was replaced: everything we cached is stale
        offset, index = 0, {}
    if offset == size and index:
        return index
    with p.open("r", encoding="utf-8") as fh:
        fh.seek(offset)
        tail = fh.read()
    end, rows = offset + len(tail.encode("utf-8")), []
    for line in tail.splitlines(keepends=True):
        if not line.endswith("\n"):         # a half-written last line: leave it for the next read
            end -= len(line.encode("utf-8"))
            break
        if line.strip():
            rows.append(json.loads(line))
    _rows_to_index(rows, into=index)
    _CACHE[key] = (end, index)
    return index


def _rows_to_index(rows: list[dict], into: dict | None = None) -> dict:
    index = into if into is not None else {}
    for r in rows:
        path = r.get("p")
        if not path:                        # heartbeat line
            continue
        index.setdefault(r["c"], {}).setdefault(path, []).append((r["ts"], r["o"]))
    return index


def _days_back(as_of: dt.datetime, days: int) -> list[dt.date]:
    return [(as_of - dt.timedelta(days=i)).date() for i in range(days, -1, -1)]


def raw_series(settings: Settings, code: int, as_of: dt.datetime | None = None,
               days: int = 4) -> dict[str, list[tuple[str, float]]]:
    """{path: [(iso ts, odds)]} for one match, oldest first, across the last `days` archive days."""
    as_of = as_of or dt.datetime.now(dt.timezone.utc)
    out: dict[str, list[tuple[str, float]]] = {}
    for day in _days_back(as_of, days):
        for path, points in (_index_day(settings, day).get(code) or {}).items():
            out.setdefault(path, []).extend(points)
    for path in out:
        out[path].sort(key=lambda x: x[0])
    return out


def match_meta(settings: Settings, code: int, as_of: dt.datetime | None = None, days: int = 4) -> dict | None:
    """The teams and kick-off behind a code, from whichever day file first recorded it."""
    as_of = as_of or dt.datetime.now(dt.timezone.utc)
    for day in reversed(_days_back(as_of, days)):
        m = archive.load_meta(settings, day).get(str(code))
        if m:
            return m
    return None


def codes_on(settings: Settings, date: str, days: int = 3) -> dict[int, dict]:
    """{code: meta} for every archived match kicking off on `date` (Turkey local).

    The archive is filed by the UTC day a price was *seen*, not by kick-off, and a code's meta row is
    written once — on the first day its price moved, which is usually days before the match. The
    lookup therefore reads a small window of day files and filters on the meta's own date."""
    try:
        day = dt.date.fromisoformat(str(date))
    except ValueError:
        return {}
    out: dict[int, dict] = {}
    for offset in range(-days, 2):
        for code, m in archive.load_meta(settings, day + dt.timedelta(days=offset)).items():
            if str(m.get("date")) == str(date):
                out.setdefault(int(code), m)
    return out


def frozen_row(settings: Settings, code: int, as_of: dt.datetime | None = None, days: int = 4,
               meta: dict | None = None) -> dict | None:
    """The bulletin row as it stood at the last price seen before kick-off.

    nesine publishes a *pre*-bulletin: the moment betting closes a match leaves it, so a played
    fixture cannot be looked up live at all — not a bug, and not something a retry fixes. The
    archive is the other half of that deal, and `watcher.TRACKED` is by construction every price a
    note reads, so the row can be rebuilt from it and the notes can still be evaluated afterwards.

    What comes back is a frozen row, and it says so: `frozen`, `frozen_at` and `minutes_before`
    travel with it, because a price read 40 minutes before kick-off is not the closing price and
    nothing downstream may quietly treat it as one. Prices seen *after* kick-off are dropped — the
    archive can contain them when a match starts late — since a note about a pre-match price must
    never be judged on one the bettor could not have had."""
    meta = meta if meta is not None else match_meta(settings, code, as_of=as_of, days=days)
    if not meta:
        return None
    raw = raw_series(settings, int(code), as_of=as_of, days=days)
    if not raw:
        return None
    ko = kickoff(meta)
    cut = ko.isoformat(timespec="seconds") if ko else None
    out: dict = {"code": int(code), "frozen": True,
                 **{k: meta.get(k) for k in ("date", "time", "home", "away", "league", "league_code")}}
    last_ts: str | None = None
    for path, points in raw.items():
        usable = [(ts, o) for ts, o in points if cut is None or ts <= cut]
        if not usable:
            continue
        ts, odds = usable[-1]
        group, _, sel = path.partition(".")
        if sel:
            out.setdefault(group, {})[sel] = odds
        last_ts = ts if last_ts is None or ts > last_ts else last_ts
    if not out.get("ms"):
        return None                     # no 1X2 is no bulletin row; half a market would mislead
    out["frozen_at"] = last_ts
    out["minutes_before"] = (None if not (ko and last_ts)
                             else round((ko - _parse_ts(last_ts)).total_seconds() / 60))
    return out


# --------------------------------------------------------------------------- building the series

def _parse_ts(s: str) -> dt.datetime:
    d = dt.datetime.fromisoformat(s)
    return d if d.tzinfo else d.replace(tzinfo=dt.timezone.utc)


def trajectory(settings: Settings, code: int, as_of: dt.datetime | None = None, days: int = 4,
               meta: dict | None = None) -> dict[str, Series]:
    """Every tracked selection of one match as a margin-free probability series.

    The archive stores each selection independently, but a no-vig probability needs the whole market
    at one instant. The selections of a group are therefore merged onto their union of timestamps
    and forward filled — which is exactly what a step function of "last price seen" means — and the
    margin is removed row by row. Instants before every selection of the group has been seen once
    are dropped rather than normalised against a half-quoted market."""
    raw = raw_series(settings, code, as_of=as_of, days=days)
    meta = meta if meta is not None else match_meta(settings, code, as_of=as_of, days=days)
    ko = kickoff(meta) if meta else None

    groups: dict[str, dict[str, list[tuple[str, float]]]] = {}
    for path, pts in raw.items():
        group, _, sel = path.partition(".")
        groups.setdefault(group, {})[sel] = pts

    out: dict[str, Series] = {}
    for group, sels in groups.items():
        names = sorted(sels)
        stamps = sorted({ts for pts in sels.values() for ts, _ in pts})
        cursor = {n: 0 for n in names}
        last: dict[str, float | None] = {n: None for n in names}
        rows, changed_at, kept = [], [], []
        for ts in stamps:
            moved = set()
            for n in names:
                pts = sels[n]
                while cursor[n] < len(pts) and pts[cursor[n]][0] <= ts:
                    last[n] = pts[cursor[n]][1]
                    moved.add(n)
                    cursor[n] += 1
            if any(last[n] is None for n in names):
                continue                    # the market is not fully quoted yet
            rows.append([last[n] for n in names])
            changed_at.append(moved)
            kept.append(ts)
        if not rows:
            continue
        arr = np.asarray(rows, dtype=float)
        novig = group in FULL_GROUPS and arr.shape[1] > 1
        probs = remove_margin(1.0 / arr, "proportional") if novig else 1.0 / arr
        for j, n in enumerate(names):
            s = Series(code=code, group=group, selection=n, novig=bool(novig), kickoff=ko)
            for i, ts in enumerate(kept):
                t = _parse_ts(ts)
                mins = (ko - t).total_seconds() / 60 if ko else None
                pr = float(probs[i, j])
                s.points.append(Point(ts=t, minutes=mins, odds=float(arr[i, j]),
                                      prob=pr if np.isfinite(pr) else None, changed=n in changed_at[i]))
            out[s.path] = s
    return out


# --------------------------------------------------------------------------- measuring one series

def _p(point: Point) -> float | None:
    return None if point.prob is None else 100 * point.prob


def _at(points: list[Point], minutes: float) -> Point | None:
    """The price in force `minutes` before kick-off — the last point at or before that instant."""
    before = [p for p in points if p.minutes is not None and p.minutes >= minutes]
    return before[-1] if before else None


def open_current_close(s: Series, started: bool | None = None) -> dict:
    """OPEN = first valid price, CURRENT = last valid price, CLOSE = last one before kick-off.

    CLOSE stays None while the match has not kicked off: the last price we happen to hold is not a
    closing price, and calling it one would quietly invent the number every CLV claim rests on."""
    pts = [p for p in s.points if p.prob is not None]
    if not pts:
        return {"open": None, "current": None, "closing": None}
    pre = [p for p in pts if p.minutes is None or p.minutes >= 0]
    if started is None:
        started = bool(s.kickoff and pts[-1].minutes is not None and pts[-1].minutes < 0)
    close = pre[-1] if (started and pre) else None
    return {
        "open": {"odds": pts[0].odds, "p": round(_p(pts[0]), 2), "ts": pts[0].ts.isoformat(),
                 "minutes": None if pts[0].minutes is None else round(pts[0].minutes)},
        "current": {"odds": pts[-1].odds, "p": round(_p(pts[-1]), 2), "ts": pts[-1].ts.isoformat(),
                    "minutes": None if pts[-1].minutes is None else round(pts[-1].minutes)},
        "closing": None if close is None else {"odds": close.odds, "p": round(_p(close), 2),
                                               "ts": close.ts.isoformat()},
    }


def window_features(s: Series, cfg: MovementConfig = DEFAULT_CONFIG) -> dict:
    """Per window: where the price started and ended, how far it travelled and how fast.

    A window with no snapshot inside it and no price in force at its start returns None throughout —
    `insufficient` rather than a zero, because "did not move" and "was not watched" are different
    claims and only one of them is ours to make."""
    pts = [p for p in s.points if p.prob is not None and p.minutes is not None]
    out: dict[str, dict] = {}
    for name, mins in WINDOWS:
        start = _at(pts, mins)
        inside = [p for p in pts if 0 <= p.minutes <= mins]
        if start is None or not inside:
            out[name] = {"insufficient": True, "start_p": None, "end_p": None, "delta_p": None,
                         "delta_odds": None, "n_changes": 0, "max_p": None, "min_p": None,
                         "volatility": None, "velocity": None}
            continue
        seq = ([start] if start is not inside[0] else []) + inside
        ps = [_p(p) for p in seq]
        hours = max((seq[0].minutes - seq[-1].minutes) / 60, 1e-9)
        out[name] = {
            "insufficient": False,
            "start_p": round(ps[0], 2), "end_p": round(ps[-1], 2),
            "delta_p": round(ps[-1] - ps[0], 2),
            "delta_odds": round(seq[-1].odds - seq[0].odds, 3),
            "n_changes": sum(1 for p in inside if p.changed),
            "max_p": round(max(ps), 2), "min_p": round(min(ps), 2),
            "volatility": round(float(np.std(ps)), 3) if len(ps) > 1 else 0.0,
            "velocity": round((ps[-1] - ps[0]) / hours, 3),
            "hours": round(hours, 3),
        }
    return out


def _steps(points: list[Point]) -> list[float]:
    ps = [_p(p) for p in points if p.prob is not None]
    return [b - a for a, b in zip(ps, ps[1:])]


def direction_consistency(points: list[Point]) -> float | None:
    """|net movement| / total distance travelled, in [0, 1].

    1.90 -> 1.84 -> 1.79 -> 1.73 and 1.90 -> 1.81 -> 1.88 -> 1.73 end in the same place; the first
    walked straight there and the second wandered. Net movement alone cannot tell them apart."""
    steps = _steps(points)
    path = sum(abs(x) for x in steps)
    if path < 1e-9:
        return None
    return round(abs(sum(steps)) / path, 3)


def reversal(points: list[Point], cfg: MovementConfig = DEFAULT_CONFIG) -> dict | None:
    """The size of the move out and the size of the move back, not a boolean.

    OPEN 1.85 -> LOW 1.70 -> CLOSE 1.91 is one thing at a 6 pp swing and another at 0.4 pp; both
    legs have to clear `reversal_min_pp` before the word is used at all.

    They also have to be comparable. A 10 pp move that ticks 1.6 pp back has not reversed, it has
    paused — but the absolute test alone called it a REVERSAL, and because the check runs before
    STEAM/DRIFT it swallowed those categories whole: the first sixteen matches frozen in production
    came out 8 REVERSAL and 0 STEAM. `reversal_min_share` is what the spec meant by a *strong* turn
    back: the leg back must undo at least this much of the leg out."""
    ps = [_p(p) for p in points if p.prob is not None]
    if len(ps) < 3:
        return None
    first = ps[0]
    hi, lo = int(np.argmax(ps)), int(np.argmin(ps))
    best = None
    for turn in (hi, lo):
        if turn in (0, len(ps) - 1):
            continue
        initial, back = ps[turn] - first, ps[-1] - ps[turn]
        if initial * back >= 0:
            continue                                   # not a turn: both legs go the same way
        if abs(initial) < cfg.reversal_min_pp or abs(back) < cfg.reversal_min_pp:
            continue
        if abs(back) / abs(initial) < cfg.reversal_min_share:
            continue          # a pullback is not a reversal: the spec asks for a STRONG turn back
        cand = {"initial_pp": round(initial, 2), "reversal_pp": round(back, 2),
                "recovery_pct": round(100 * min(abs(back) / abs(initial), 9.99), 1),
                "peak_p": round(ps[turn], 2), "at_index": turn}
        if best is None or abs(back) > abs(best["reversal_pp"]):
            best = cand
    return best


def classify(s: Series, cfg: MovementConfig = DEFAULT_CONFIG, windows: dict | None = None) -> dict:
    """The verdict, its evidence, and the reason when there is no verdict.

    The shapes are not mutually exclusive — a move can be late AND accelerating — so a primary type
    comes back with a list of tags rather than one label pretending to cover everything."""
    pre = [p for p in s.before_kickoff() if p.prob is not None]
    span = (pre[0].minutes - pre[-1].minutes) if len(pre) > 1 and pre[0].minutes is not None else 0
    n_changes = sum(1 for p in pre if p.changed)
    blank = {"type": None, "tags": [], "confidence": "low", "total_pp": None, "consistency": None,
             "late_share": None, "reversal": None, "n_points": len(pre), "n_changes": n_changes,
             "span_min": round(span) if span else 0, "reason": "yeterli snapshot yok"}
    if len(pre) < 2 or n_changes < 2:
        return blank                       # same shape either way: a reader must not have to branch

    total = _p(pre[-1]) - _p(pre[0])
    consistency = direction_consistency(pre)
    rev = reversal(pre, cfg)
    windows = windows if windows is not None else window_features(s, cfg)

    late = windows.get(f"{cfg.late_window_min}m") or windows.get("1h") or {}
    late_delta = late.get("delta_p")
    late_share = (abs(late_delta) / abs(total)) if (late_delta is not None and abs(total) > 1e-9) else None

    tags: list[str] = []
    if abs(total) < cfg.stable_max_pp:
        kind = "STABLE"
    elif rev and abs(rev["reversal_pp"]) >= cfg.reversal_min_pp:
        kind = "REVERSAL"
    elif abs(total) >= cfg.movement_min_pp and (consistency or 0) >= cfg.direction_consistency:
        kind = "STEAM" if total > 0 else "DRIFT"
        if late_share is not None and late_share >= cfg.late_move_share:
            tags.append("LATE_STEAM" if total > 0 else "LATE_DRIFT")
    else:
        kind = "STABLE" if abs(total) < cfg.movement_min_pp else "NOISY"

    pace = _pace(windows, cfg)
    if pace:
        tags.append(pace)

    low = len(pre) < cfg.min_snapshots or span < cfg.min_span_min
    return {
        "type": kind, "tags": tags,
        "confidence": "low" if low else "ok",
        "total_pp": round(total, 2), "consistency": consistency,
        "late_share": None if late_share is None else round(late_share, 3),
        "reversal": rev, "n_points": len(pre), "n_changes": n_changes,
        "span_min": round(span) if span else 0,
        "reason": "az snapshot, sınıflandırma zayıf" if low else None,
    }


def _pace(windows: dict, cfg: MovementConfig) -> str | None:
    """Is the move speeding up as kick-off approaches? Velocity late over velocity early."""
    late, early = windows.get("1h"), windows.get("6h")
    if not late or not early or late.get("velocity") is None or early.get("velocity") is None:
        return None
    if abs(early["velocity"]) < 1e-6:
        return None
    ratio = abs(late["velocity"]) / abs(early["velocity"])
    if ratio >= cfg.accel_ratio:
        return "ACCELERATING"
    if ratio <= 1 / cfg.accel_ratio:
        return "DECELERATING"
    return None


def velocities(windows: dict) -> dict[str, float | None]:
    return {f"velocity_{name}": (windows.get(name) or {}).get("velocity") for name in VELOCITY_WINDOWS}


# the feature names the twin engine will compare on once the archive has history. Kept in one place
# so the storage, the frame and the similarity cannot drift apart on spelling.
FEATURES = ("mv_type", "mv_total_pp", "mv_3h", "mv_1h", "mv_30m", "mv_15m",
            "mv_velocity_1h", "mv_consistency", "mv_reversal_pp")


def features_for(s: Series, cfg: MovementConfig = DEFAULT_CONFIG, windows: dict | None = None) -> dict:
    """One selection's movement as a flat feature row — spec 27's list, and nothing more.

    This is the shape the twin engine will read and the forward store already writes. Every value is
    None when the archive cannot support it, because a movement feature defaulted to zero is a claim
    that the price held, which is the one thing a missing measurement does not tell you."""
    w = windows if windows is not None else window_features(s, cfg)
    verdict = classify(s, cfg, windows=w)
    rev = verdict.get("reversal") or {}
    return {
        "mv_type": verdict.get("type"),
        "mv_total_pp": verdict.get("total_pp"),
        "mv_3h": (w.get("3h") or {}).get("delta_p"),
        "mv_1h": (w.get("1h") or {}).get("delta_p"),
        "mv_30m": (w.get("30m") or {}).get("delta_p"),
        "mv_15m": (w.get("15m") or {}).get("delta_p"),
        "mv_velocity_1h": (w.get("1h") or {}).get("velocity"),
        "mv_consistency": verdict.get("consistency"),
        "mv_reversal_pp": rev.get("reversal_pp"),
        "mv_confidence": verdict.get("confidence"),
    }


# --------------------------------------------------------------------------- data quality

def coverage(settings: Settings, s: Series, as_of: dt.datetime | None = None, days: int = 4) -> dict:
    """How much of this match's run-up we were actually watching.

    The heartbeat rows say when the watcher looked; the series says when the price moved. Coverage
    is the share of the last 24 hours before kick-off in which a refresh happened at all, so a
    STABLE verdict produced during an outage can be read as what it is."""
    as_of = as_of or dt.datetime.now(dt.timezone.utc)
    pts = [p for p in s.points if p.prob is not None]
    out = {"snapshots": len(pts), "changes": sum(1 for p in pts if p.changed),
           "first": pts[0].ts.isoformat() if pts else None, "last": pts[-1].ts.isoformat() if pts else None,
           "novig": s.novig, "coverage": None, "runs": 0}
    if not s.kickoff:
        return out
    start = s.kickoff - dt.timedelta(hours=24)
    end = min(s.kickoff, as_of)
    if end <= start:
        return out
    runs = []
    for day in _days_back(as_of, days):
        runs += [_parse_ts(r["ts"]) for r in archive.load_day(settings, day, runs=True)]
    inside = sorted(t for t in runs if start <= t <= end)
    out["runs"] = len(inside)
    if not inside:
        out["coverage"] = 0.0
        return out
    # the watcher's own interval is the resolution: a gap longer than twice it is a hole
    gaps = [(b - a).total_seconds() for a, b in zip(inside, inside[1:])]
    typical = float(np.median(gaps)) if gaps else 0.0
    hole = max(2 * typical, 900.0)
    watched = (end - start).total_seconds() - sum(g - typical for g in gaps if g > hole)
    watched -= max((inside[0] - start).total_seconds() - hole, 0)
    out["coverage"] = round(max(0.0, min(1.0, watched / (end - start).total_seconds())), 3)
    return out


# --------------------------------------------------------------------------- the payload

def for_match(settings: Settings, code: int, paths: tuple[str, ...] = ("ms.1", "ms.X", "ms.2"),
              cfg: MovementConfig = DEFAULT_CONFIG, as_of: dt.datetime | None = None,
              days: int = 4, chart_points: int = 60) -> dict:
    """Everything the match page needs for one match: per selection, with its own data quality."""
    as_of = as_of or dt.datetime.now(dt.timezone.utc)
    meta = match_meta(settings, code, as_of=as_of, days=days)
    series = trajectory(settings, code, as_of=as_of, days=days, meta=meta)
    ko = kickoff(meta) if meta else None
    started = bool(ko and as_of > ko)

    out = {"code": code, "match": meta, "kickoff": ko.isoformat() if ko else None,
           "started": started, "config": cfg.as_dict(), "selections": {},
           "available": sorted(series), "archive_from": archive_start(settings)}
    for path in paths:
        s = series.get(path)
        if s is None:
            out["selections"][path] = {"missing": True}
            continue
        w = window_features(s, cfg)
        out["selections"][path] = {
            "group": s.group, "selection": s.selection, "novig": s.novig,
            **open_current_close(s, started=started),
            "windows": w, **velocities(w),
            "movement": classify(s, cfg, windows=w),
            "quality": coverage(settings, s, as_of=as_of, days=days),
            "chart": _chart(s, chart_points),
        }
    return out


def _chart(s: Series, limit: int) -> list[dict]:
    """The trajectory thinned for drawing: every change, plus the first and last point."""
    pts = [p for p in s.points if p.prob is not None]
    keep = [p for p in pts if p.changed] or pts
    if pts and keep[0] is not pts[0]:
        keep = [pts[0]] + keep
    if pts and keep[-1] is not pts[-1]:
        keep = keep + [pts[-1]]
    if len(keep) > limit:                     # keep the ends, thin the middle evenly
        idx = sorted({0, len(keep) - 1, *np.linspace(0, len(keep) - 1, limit).astype(int).tolist()})
        keep = [keep[i] for i in idx]
    return [{"ts": p.ts.isoformat(), "minutes": None if p.minutes is None else round(p.minutes),
             "odds": p.odds, "p": round(_p(p), 2)} for p in keep]


def archive_start(settings: Settings) -> str | None:
    """The first day the archive holds — the honest left edge of every movement claim."""
    d = archive.archive_dir(settings)
    if not d.exists():
        return None
    days = sorted(p.name.split(".")[0] for p in d.glob("*.jsonl*"))
    return days[0] if days else None


def config_from_env(base: MovementConfig = DEFAULT_CONFIG) -> MovementConfig:
    """FO_MOVE_<FIELD> overrides any threshold without a deploy, for the backtest to sweep."""
    import os

    kw = {}
    for name, value in base.as_dict().items():
        raw = os.environ.get(f"FO_MOVE_{name.upper()}")
        if raw:
            try:
                kw[name] = type(value)(raw)
            except (TypeError, ValueError):
                log.warning("ignoring FO_MOVE_%s=%r", name.upper(), raw)
    return replace(base, **kw) if kw else base
