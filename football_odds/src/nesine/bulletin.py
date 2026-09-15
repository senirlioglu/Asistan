"""nesine.com pre-match bulletin: fetch, cache, and flatten the odds a football match carries.

Source: ``https://cdnbulten.nesine.com/api/bulten/getprebultenfull`` (the JSON the site itself loads,
~4 MB, every sport). Football events have ``GT == 1``; each carries ``MA`` markets identified by a
numeric market type (``MTID``) plus a line (``SOV``), and outcomes ``OCA`` = [{N: outcome id, O: odds}].
Names for the ids come from the site's own market definitions (``market_types.json``, extracted from
nesine's bundle). Correct-score markets publish no outcome names, their layouts are fixed below.

The parsed shape per match::

    {"code", "date" (YYYY-MM-DD, Turkey), "time", "home", "away", "league", "league_code",
     "ms": {"1": 2.30, "X": 3.40, "2": 2.31}, "iyms": {"1/1": ..., "2/1": ...}, "iy": {...},
     "iy05": {"alt","ust"}, "h1_15": {...}, "h2_15": {...}, "o25", "o35", "o45": {"alt","ust"},
     "gol_araligi": {"0-1","2-3","4-5","6+"}, "iy_kg": {"var","yok"}, "y2_kg": {...},
     "iy_y2_kg": {"evet/evet", ...}, "iy_sonucu_kg": {"1&var", "x&var", "2&var", ...},
     "ilk_gol": {"1","olmaz","2"}, "iki_yari_15_ust": {"evet","hayir"},
     "iy_skor": {"1-0": .., "diger": ..}, "skor": {"1-0": .., "diger": ..}, "korner": {label: odds}}

Odds of exactly 1.00 mean "not offered" on nesine and are dropped.
"""

from __future__ import annotations

import datetime as dt
import json
import time
from pathlib import Path
from typing import Any

import requests

from ..config import Settings
from ..logging_setup import get_logger

log = get_logger("nesine.bulletin")

URL = "https://cdnbulten.nesine.com/api/bulten/getprebultenfull"
CACHE_TTL_S = 15 * 60
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0 Safari/537.36"

MARKET_TYPES: dict[str, dict] = json.loads((Path(__file__).parent / "market_types.json").read_text(encoding="utf-8"))

# fixed layouts (the definitions publish no names for these ids; verified against live odds)
SCORE_FT = {1: "1-0", 2: "2-0", 3: "2-1", 4: "3-0", 5: "3-1", 6: "3-2", 7: "4-0", 8: "4-1", 9: "4-2", 10: "5-0", 11: "5-1", 12: "6-0",
            13: "0-0", 14: "1-1", 15: "2-2", 16: "3-3", 17: "0-1", 18: "0-2", 19: "1-2", 20: "0-3", 21: "1-3", 22: "2-3", 23: "0-4",
            24: "1-4", 25: "2-4", 26: "0-5", 27: "1-5", 28: "0-6", 29: "diger"}
SCORE_HT = {4: "1-0", 5: "2-0", 6: "2-1", 1: "0-0", 2: "1-1", 3: "2-2", 7: "0-1", 8: "0-2", 9: "1-2", 10: "diger"}
IYMS = {1: "1/1", 2: "1/X", 3: "1/2", 4: "X/1", 5: "X/X", 6: "X/2", 7: "2/1", 8: "2/X", 9: "2/2"}
ALT_UST = {1: "alt", 2: "ust"}
VAR_YOK = {1: "var", 2: "yok"}
EVET_HAYIR = {1: "evet", 2: "hayir"}


def _cache_path(settings: Settings) -> Path:
    return settings.results_dir / "nesine_bulten.json"


def fetch_raw(settings: Settings, max_age_s: int = CACHE_TTL_S, force: bool = False) -> tuple[dict, dict]:
    """Bulletin JSON + {fetched_at, from_cache, error}. A stale cache is served when the fetch fails."""
    p = _cache_path(settings)
    meta: dict[str, Any] = {"fetched_at": None, "from_cache": False, "error": None}
    if p.exists() and not force and time.time() - p.stat().st_mtime < max_age_s:
        meta.update(fetched_at=dt.datetime.fromtimestamp(p.stat().st_mtime, dt.timezone.utc).isoformat(timespec="seconds"), from_cache=True)
        return json.loads(p.read_text(encoding="utf-8")), meta
    try:
        r = requests.get(URL, timeout=60, headers={"User-Agent": USER_AGENT, "Accept": "application/json", "Referer": "https://www.nesine.com/"})
        r.raise_for_status()
        data = r.json()
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        meta["fetched_at"] = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
        return data, meta
    except Exception as exc:  # noqa: BLE001 - keep serving the cache
        log.warning("nesine fetch failed: %s", exc)
        meta["error"] = str(exc)
        if p.exists():
            meta.update(fetched_at=dt.datetime.fromtimestamp(p.stat().st_mtime, dt.timezone.utc).isoformat(timespec="seconds"), from_cache=True)
            return json.loads(p.read_text(encoding="utf-8")), meta
        raise


# --------------------------------------------------------------------------- parsing

def _odds(markets: list[dict], mtid: int, sov: float | None = None) -> dict[int, float]:
    for m in markets:
        if m.get("MTID") == mtid and (sov is None or float(m.get("SOV") or 0) == sov):
            return {int(o["N"]): float(o["O"]) for o in m.get("OCA", []) if o.get("O") is not None and float(o["O"]) > 1.0}
    return {}


def _named(raw: dict[int, float], names: dict[int, str]) -> dict[str, float]:
    return {names[k]: v for k, v in raw.items() if k in names}


def parse_event(e: dict, leagues: dict[int, str]) -> dict | None:
    if e.get("GT") != 1 or e.get("TYPE") != 1 or not e.get("HN") or not e.get("AN"):
        return None
    ma = e.get("MA", [])
    try:
        d = dt.datetime.strptime(str(e.get("D", "")), "%d.%m.%Y").date().isoformat()
    except ValueError:
        d = ""
    ms = _named(_odds(ma, 1), {1: "1", 2: "X", 3: "2"})
    korner: dict[str, float] = {}
    for m in ma:
        t = MARKET_TYPES.get(str(m.get("MTID")), {})
        title = t.get("Title", "")
        if "Korner" not in title:
            continue
        sov = m.get("SOV")
        line = f"{sov:g}".replace(".", ",") if sov not in (None, 0.0) else ""
        label = " ".join(title.replace("{{handicap}}", line).split())
        vals = {v["id"]: v["title"] for v in (t.get("Value") or [])}
        for o in m.get("OCA", []):
            if o.get("O") and float(o["O"]) > 1.0:
                korner[f"{label} · {vals.get(int(o['N']), o['N'])}"] = float(o["O"])
    return {
        "code": e.get("C"), "date": d, "time": str(e.get("T", "")), "home": str(e["HN"]), "away": str(e["AN"]),
        "league": leagues.get(e.get("LC"), str(e.get("LC", ""))), "league_code": e.get("LC"),
        "ms": ms, "iyms": _named(_odds(ma, 5), IYMS), "iy": _named(_odds(ma, 7), {1: "1", 2: "X", 3: "2"}),
        "iy05": _named(_odds(ma, 209, 0.5), ALT_UST), "h1_15": _named(_odds(ma, 14, 1.5), ALT_UST),
        "h2_15": _named(_odds(ma, 281, 1.5) or _odds(ma, 283, 1.5), ALT_UST),
        "o25": _named(_odds(ma, 12, 2.5), ALT_UST), "o35": _named(_odds(ma, 13, 3.5), ALT_UST), "o45": _named(_odds(ma, 155, 4.5), ALT_UST),
        "gol_araligi": _named(_odds(ma, 43), {1: "0-1", 2: "2-3", 3: "4-5", 4: "6+"}),
        "iy_kg": _named(_odds(ma, 452), VAR_YOK), "y2_kg": _named(_odds(ma, 599), VAR_YOK),
        "iy_y2_kg": _named(_odds(ma, 801), {3: "evet/evet", 2: "evet/hayir", 4: "hayir/evet", 1: "hayir/hayir"}),
        "iy_sonucu_kg": _named(_odds(ma, 416), {1: "1&var", 3: "x&var", 5: "2&var", 2: "1&yok", 4: "x&yok", 6: "2&yok"}),
        "ilk_gol": _named(_odds(ma, 291), {1: "1", 2: "olmaz", 3: "2"}),
        "iki_yari_15_ust": _named(_odds(ma, 529), EVET_HAYIR),
        "iy_skor": _named(_odds(ma, 779), SCORE_HT), "skor": _named(_odds(ma, 777), SCORE_FT),
        "korner": korner,
    }


def parse_bulletin(data: dict) -> list[dict]:
    sg = data.get("sg", {})
    leagues = {int(x["LID"]): str(x["N"]) for x in sg.get("LA", []) if "LID" in x}
    out = []
    for e in sg.get("EA", []):
        m = parse_event(e, leagues)
        if m and m["ms"]:
            out.append(m)
    out.sort(key=lambda m: (m["date"], m["time"], m["league"]))
    return out


def load_matches(settings: Settings, force: bool = False) -> tuple[list[dict], dict]:
    data, meta = fetch_raw(settings, force=force)
    matches = parse_bulletin(data)
    meta["n_matches"] = len(matches)
    return matches, meta
