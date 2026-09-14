"""Live scores for the fixtures on the page.

Football-Data publishes no live data, so in-play minute and score come from ESPN's public
scoreboard JSON (no key; unofficial, so every call is wrapped and a failure simply yields no
live badge). Finished matches that are already in the processed database are answered from
there, which is the reliable source once Football-Data has published the result.

Team names differ between the two sources ("Inter" vs "Internazionale", "Sp Braga" vs
"Braga"); matching is done per league and day on normalised names with a small alias table,
choosing the ESPN event whose home+away names are closest to the fixture's.
"""

from __future__ import annotations

import datetime as dt
import difflib
import re
import threading
import time
import unicodedata
from typing import Any

import requests

from ..logging_setup import get_logger

log = get_logger("web.live")

ESPN_LEAGUES = {
    "E0": "eng.1", "E1": "eng.2", "SP1": "esp.1", "SP2": "esp.2", "I1": "ita.1", "I2": "ita.2", "D1": "ger.1", "D2": "ger.2",
    "F1": "fra.1", "F2": "fra.2", "N1": "ned.1", "P1": "por.1", "B1": "bel.1", "T1": "tur.1", "G1": "gre.1", "SC0": "sco.1",
    "E2": "eng.3", "E3": "eng.4", "EC": "eng.5", "SC1": "sco.2", "SC2": "sco.3", "SC3": "sco.4",
    "ARG": "arg.1", "AUT": "aut.1", "BRA": "bra.1", "CHN": "chn.1", "DNK": "den.1", "FIN": "fin.1", "IRL": "irl.1", "JPN": "jpn.1",
    "MEX": "mex.1", "NOR": "nor.1", "POL": "pol.1", "ROU": "rou.1", "RUS": "rus.1", "SWE": "swe.1", "SWZ": "sui.1",
    "USA": "usa.1",
}
ESPN_URL = "https://site.api.espn.com/apis/site/v2/sports/soccer/{league}/scoreboard"
CACHE_TTL_S = 45
USER_AGENTS = ["curl/8.5.0", "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0 Safari/537.36", "football-odds/0.1"]

# Football-Data spelling -> tokens that identify the club on ESPN (lower-case, ascii)
ALIASES = {
    "man united": "manchester united", "man city": "manchester city", "nott'm forest": "nottingham forest",
    "wolves": "wolverhampton wanderers", "spurs": "tottenham hotspur", "tottenham": "tottenham hotspur",
    "sheffield united": "sheffield united", "sheffield weds": "sheffield wednesday", "qpr": "queens park rangers",
    "west brom": "west bromwich albion", "west ham": "west ham united", "newcastle": "newcastle united",
    "inter": "internazionale", "milan": "ac milan", "ath madrid": "atletico madrid", "ath bilbao": "athletic club",
    "sociedad": "real sociedad", "betis": "real betis", "espanol": "espanyol", "sp braga": "braga", "sp lisbon": "sporting cp",
    "guimaraes": "vitoria guimaraes", "gaziantep": "gaziantep fk", "basaksehir": "istanbul basaksehir",
    "fenerbahce": "fenerbahce", "galatasaray": "galatasaray", "besiktas": "besiktas", "trabzonspor": "trabzonspor",
    "ein frankfurt": "eintracht frankfurt", "m'gladbach": "borussia monchengladbach", "dortmund": "borussia dortmund",
    "leverkusen": "bayer leverkusen", "mainz": "mainz 05", "hoffenheim": "tsg hoffenheim", "fc koln": "koln",
    "paris sg": "paris saint-germain", "st etienne": "saint-etienne", "psv eindhoven": "psv", "for sittard": "fortuna sittard",
    "go ahead eagles": "go ahead eagles", "club brugge": "club brugge", "st truiden": "sint-truiden", "standard": "standard liege",
    "olympiakos": "olympiacos", "aek": "aek athens", "paok": "paok", "celtic": "celtic", "rangers": "rangers",
    "hearts": "heart of midlothian", "hibernian": "hibernian", "st mirren": "st. mirren", "st johnstone": "st. johnstone",
}
_STOP = {"fc", "cf", "sc", "ac", "as", "us", "ss", "afc", "cd", "ud", "sd", "rc", "rcd", "club", "de", "fk", "sk", "the"}


def norm(name: str) -> str:
    s = unicodedata.normalize("NFKD", str(name or "")).encode("ascii", "ignore").decode().lower().strip()
    s = ALIASES.get(s, s)
    s = re.sub(r"[^a-z0-9 ]+", " ", s)
    toks = [t for t in s.split() if t not in _STOP]
    return " ".join(toks)


def name_score(a: str, b: str) -> float:
    a, b = norm(a), norm(b)
    if not a or not b:
        return 0.0
    if a == b or a in b or b in a:
        return 1.0
    ta, tb = set(a.split()), set(b.split())
    jac = len(ta & tb) / max(1, len(ta | tb))
    return max(jac, difflib.SequenceMatcher(None, a, b).ratio())


# --------------------------------------------------------------------------- ESPN fetch (cached)
_cache: dict[tuple[str, str], tuple[float, list[dict]]] = {}
_lock = threading.Lock()


def _fetch_scoreboard(league_code: str, yyyymmdd: str) -> list[dict]:
    slug = ESPN_LEAGUES.get(league_code)
    if not slug:
        return []
    key = (slug, yyyymmdd)
    with _lock:
        hit = _cache.get(key)
        if hit and time.time() - hit[0] < CACHE_TTL_S:
            return hit[1]
    events: list[dict] = []
    last_exc: Exception | None = None
    # ESPN's edge answers 403 to some user agents; try a few and keep the first that works
    for ua in USER_AGENTS:
        try:
            r = requests.get(ESPN_URL.format(league=slug), params={"dates": yyyymmdd}, timeout=12, headers={"User-Agent": ua})
            if r.status_code == 403:
                last_exc = RuntimeError("403")
                continue
            r.raise_for_status()
            events = [e for e in (_parse_event(x) for x in r.json().get("events", [])) if e]
            last_exc = None
            break
        except Exception as exc:  # noqa: BLE001 - live data is best effort
            last_exc = exc
    if last_exc is not None:
        log.warning("espn %s %s: %s", slug, yyyymmdd, last_exc)
    with _lock:
        _cache[key] = (time.time(), events)
    return events


def _parse_event(e: dict) -> dict | None:
    try:
        comp = e["competitions"][0]
        home = next(c for c in comp["competitors"] if c.get("homeAway") == "home")
        away = next(c for c in comp["competitors"] if c.get("homeAway") == "away")
        status = e.get("status", {})
        stype = status.get("type", {})
        state = stype.get("state", "pre")  # pre | in | post
        detail = stype.get("shortDetail") or stype.get("detail") or ""
        clock = status.get("displayClock", "")
        period = status.get("period", 0)

        def ht(c: dict) -> int | None:
            ls = c.get("linescores") or []
            return int(float(ls[0]["value"])) if ls and ls[0].get("value") is not None else None

        return {
            "home": home["team"].get("displayName") or home["team"].get("name"),
            "away": away["team"].get("displayName") or away["team"].get("name"),
            "home_short": home["team"].get("shortDisplayName", ""), "away_short": away["team"].get("shortDisplayName", ""),
            "home_score": int(home.get("score") or 0), "away_score": int(away.get("score") or 0),
            "ht_home": ht(home), "ht_away": ht(away),
            "state": state, "detail": detail, "clock": clock, "period": period,
            "start": e.get("date", ""),
        }
    except Exception:  # noqa: BLE001
        return None


def match_event(events: list[dict], home: str, away: str, min_score: float = 0.55) -> dict | None:
    best, best_s = None, 0.0
    for ev in events:
        s = (max(name_score(home, ev["home"]), name_score(home, ev.get("home_short", "")))
             + max(name_score(away, ev["away"]), name_score(away, ev.get("away_short", "")))) / 2
        if s > best_s:
            best, best_s = ev, s
    return best if best is not None and best_s >= min_score else None


def live_for_fixture(league: str, date_uk: str, home: str, away: str) -> dict | None:
    """Best-effort live/finished info for one fixture; None when nothing matched."""
    days = []
    try:
        d = dt.date.fromisoformat(date_uk[:10])
        days = [d.strftime("%Y%m%d"), (d + dt.timedelta(days=1)).strftime("%Y%m%d")]
    except ValueError:
        return None
    for yyyymmdd in days:
        ev = match_event(_fetch_scoreboard(league, yyyymmdd), home, away)
        if ev:
            return {k: ev[k] for k in ("home_score", "away_score", "ht_home", "ht_away", "state", "detail", "clock", "period")} | {"source": "espn"}
    return None


def status_label_tr(info: dict[str, Any]) -> str:
    """'54'' / 'İY' / 'MS' / '' for the badge."""
    state = info.get("state")
    if state == "post":
        return "MS"
    if state == "in":
        detail = str(info.get("detail", ""))
        if "HT" in detail.upper() or "HALF" in detail.upper():
            return "İY"
        clock = str(info.get("clock", "")).replace("'", "")
        return f"{clock}'" if clock else "canlı"
    return ""
