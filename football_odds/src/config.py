"""Configuration loading.

The YAML file at config/settings.yaml is the single source of truth. Paths inside it are
relative to the project root (the directory that contains `config/` and `src/`).
"""

from __future__ import annotations

import copy
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "config" / "settings.yaml"


@dataclass
class Settings:
    """Thin wrapper around the parsed YAML with resolved paths."""

    raw: dict[str, Any]
    root: Path = PROJECT_ROOT

    # ---- generic access -------------------------------------------------
    def section(self, name: str) -> dict[str, Any]:
        value = self.raw.get(name)
        if value is None:
            raise KeyError(f"Missing config section: {name}")
        return value

    def get(self, dotted: str, default: Any = None) -> Any:
        node: Any = self.raw
        for part in dotted.split("."):
            if not isinstance(node, dict) or part not in node:
                return default
            node = node[part]
        return node

    # ---- paths ----------------------------------------------------------
    def path(self, dotted: str) -> Path:
        value = self.get(dotted)
        if value is None:
            raise KeyError(f"Missing path setting: {dotted}")
        p = Path(value)
        return p if p.is_absolute() else self.root / p

    @property
    def raw_dir(self) -> Path:
        return self.path("data.raw_dir")

    @property
    def processed_dir(self) -> Path:
        return self.path("data.processed_dir")

    @property
    def results_dir(self) -> Path:
        return self.path("data.results_dir")

    # ---- leagues / seasons ---------------------------------------------
    @property
    def main_leagues(self) -> dict[str, dict[str, Any]]:
        """Divisions served as mmz4281/<season>/<div>.csv (one file per season)."""
        return self.get("data.leagues", {})

    @property
    def extra_leagues(self) -> dict[str, dict[str, Any]]:
        """Countries served as new/<file>.csv (one file, every season, closing odds only)."""
        return self.get("data.extra_leagues", {}) or {}

    @property
    def leagues(self) -> dict[str, dict[str, Any]]:
        merged = dict(self.main_leagues)
        for code, meta in self.extra_leagues.items():
            merged[code] = {**meta, "core": False, "source": "extra"}
        return merged

    def is_extra_league(self, code: str) -> bool:
        return code in self.extra_leagues

    @property
    def core_leagues(self) -> list[str]:
        return [code for code, meta in self.leagues.items() if meta.get("core")]

    @property
    def active_leagues(self) -> list[str]:
        if self.get("data.include_extra_leagues", True):
            return list(self.leagues.keys())
        return self.core_leagues

    @property
    def seasons(self) -> list[str]:
        return [str(s) for s in self.get("data.seasons", [])]

    def league_name(self, code: str) -> str:
        meta = self.leagues.get(code, {})
        if not meta:
            return code
        return f"{meta.get('country', '')} {meta.get('name', code)}".strip()

    def with_overrides(self, **overrides: Any) -> "Settings":
        """Return a copy with dotted-key overrides applied (used by CLI flags and tests)."""
        raw = copy.deepcopy(self.raw)
        for dotted, value in overrides.items():
            node = raw
            parts = dotted.split(".")
            for part in parts[:-1]:
                node = node.setdefault(part, {})
            node[parts[-1]] = value
        return Settings(raw=raw, root=self.root)


def load_settings(path: str | os.PathLike[str] | None = None) -> Settings:
    cfg_path = Path(path) if path else Path(os.environ.get("FO_CONFIG", DEFAULT_CONFIG_PATH))
    with open(cfg_path, "r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh) or {}
    root = cfg_path.resolve().parent.parent if cfg_path.parent.name == "config" else PROJECT_ROOT
    return Settings(raw=raw, root=root)


def season_label(code: str) -> str:
    """'1112' -> '2011/12'; calendar-year seasons ('Y2015', used by the extra leagues) -> '2015'."""
    code = str(code)
    if code.startswith("Y"):
        return code[1:]
    start = int(code[:2])
    return f"20{start:02d}/{code[2:]}"


def season_start_year(code: str) -> int:
    code = str(code)
    if code.startswith("Y"):
        return int(code[1:])
    return 2000 + int(code[:2])


def extra_season_code(raw: str) -> str | None:
    """Season strings of the extra files -> our codes: '2016/2017' -> '1617', '2015' -> 'Y2015'.
    Returns None for anything unparseable."""
    s = str(raw or "").strip()
    if "/" in s:
        a, b = s.split("/", 1)
        if a.isdigit() and b.isdigit() and len(a) == 4:
            return f"{int(a) % 100:02d}{int(b) % 100:02d}"
        return None
    if s.isdigit() and len(s) == 4:
        return f"Y{s}"
    return None


def current_season_code(today=None) -> str:
    """European football seasons start in July/August; the code is '<yy><yy+1>'."""
    import datetime as _dt

    today = today or _dt.date.today()
    start = today.year if today.month >= 7 else today.year - 1
    return f"{start % 100:02d}{(start + 1) % 100:02d}"
