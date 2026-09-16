"""HISTORICAL TWIN ENGINE — the most similar past matches, on more than the price.

`models/similarity.py` already finds neighbours, but it only knows the price: three numbers. Two
matches priced 1.72 / 3.8 / 4.7 are "identical" to it even when one is a leader hosting a
relegation side after a week's rest and the other a mid-table pair in their third game in seven
days. This engine keeps that price similarity as one category among several and scores each
separately, so a twin can be read rather than trusted:

    piyasa        the 1X2 probability profile           (total variation, in percentage points)
    güç           the side's strength percentile        (`tsi_pct`)
    rakip         the opponent's strength percentile
    fark          the rating gap between them           (`strength_gap`)
    form          the last five results, position by position
    gol           goals scored and conceded in the last five
    hareket       how the price moved from the opening to the closing line

Every category returns 0-100 (100 = identical) and the overall score is their weighted mean over
the categories that both matches actually have — a 2014 match has no closing line, so for it the
movement category is simply absent rather than invented. `Weights` is a plain dataclass, so the
mix is configurable, and `missing_penalty` controls how much an absent category costs.

Two things are configurable and both are chosen by `tune.py` on a validation window, never by
taste: the category weights, and `half_life` — the time decay that says how fast a twin's evidence
goes stale. The decay weights what a twin is *worth*, not whether it is a twin, and every rate and
interval downstream then runs on Kish's effective sample size instead of the raw count.

What comes back is not only the list: `diagnostics` reports how far the K-th twin actually is, the
spec's own worry ("the 100th match may not resemble today's at all"), and `outcomes` reports what
happened in the twins **next to what the market thought of those same twins** — the rule the whole
project runs on. A twin set that says 60 % where its own prices said 59 % has found nothing.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from .state import seq

# how much raw difference counts as "completely different" for each category. Form and goals are
# scored on the MEAN difference per slot, so a missing half of a team's history cannot buy a
# perfect score: a side with two matches played is compared over two slots or not at all.
SCALES = {"market": 0.30, "strength": 40.0, "opponent": 40.0, "gap": 300.0, "form": 1.2, "goals": 5.0, "movement": 0.08}
FORM_N = 5
MIN_SLOTS = {"form": 3, "goals": 2}     # fewer comparable slots than this -> not comparable at all


CATEGORIES = ("market", "strength", "opponent", "gap", "form", "goals", "movement")


@dataclass
class Weights:
    market: float = 3.0
    strength: float = 2.0
    opponent: float = 2.0
    gap: float = 2.0
    form: float = 1.5
    goals: float = 1.0
    movement: float = 1.0
    missing_penalty: float = 0.5     # a category the pair cannot compare counts at half weight, at 50

    def as_dict(self) -> dict[str, float]:
        return {k: getattr(self, k) for k in CATEGORIES}

    def replace(self, **kw) -> "Weights":
        return Weights(**{**{k: getattr(self, k) for k in CATEGORIES},
                          "missing_penalty": self.missing_penalty, **kw})


def load_weights(results_dir) -> tuple[Weights, float | None, dict]:
    """The tuned mix if `cli tune-twins` has produced one, otherwise the hand-set defaults.

    The tuner writes the winner AND what it scored on the untouched test window. A configuration
    that lost to the defaults there is not adopted, however good it looked while being chosen —
    that is the whole point of keeping a third window."""
    import json

    path = results_dir / "backtest" / "twin_weights.json"
    if not path.exists():
        return Weights(), None, {"source": "varsayılan", "reason": "ayarlama çalıştırılmadı"}
    try:
        d = json.loads(path.read_text(encoding="utf-8"))
        chosen = d["chosen"]
    except (json.JSONDecodeError, OSError, KeyError):
        return Weights(), None, {"source": "varsayılan", "reason": "twin_weights.json okunamadı"}
    if not d.get("beats_default_on_test"):
        return Weights(), None, {"source": "varsayılan", "reason": "ayarlanan mix test penceresinde varsayılanı geçemedi",
                                 "tuned": chosen, "test": d.get("test")}
    kw = {k: float(v) for k, v in chosen["weights"].items()}
    if chosen.get("missing_penalty") is not None:
        kw["missing_penalty"] = float(chosen["missing_penalty"])
    w = Weights(**kw)
    return w, chosen.get("half_life"), {"source": "ayarlanmış", "generated_at": d.get("generated_at"),
                                        "missing_penalty": w.missing_penalty, "test": d.get("test")}


def decay_weights(twin_dates: np.ndarray, as_of, half_life: float | None) -> np.ndarray:
    """exp(-ln2 * age_years / half_life) — a twin from 2012 counts less than one from last season.

    The same decay the similarity engine has always had (`models/time_weights`), reused rather than
    re-derived so the two engines cannot drift apart on what a half life means. `half_life=None`
    returns ones, which is what this engine did before the decay existed.

    The decay weights what a twin is *worth*, never which twins are chosen: a 2012 match with the
    same DNA IS a twin, it is only weaker evidence about today."""
    from ..models.time_weights import time_weights, years_between

    if half_life is None:
        return np.ones(len(twin_dates))
    return time_weights(years_between(pd.Timestamp(as_of), twin_dates), half_life)


@dataclass
class TwinResult:
    rows: pd.DataFrame                  # the twins, best first, with their per-category scores
    diagnostics: dict
    outcomes: dict
    weights: dict


def _side_cols(side: str) -> tuple[str, str]:
    return ("h_", "a_") if side == "home" else ("a_", "h_")


def _form_vec(forms: pd.Series) -> np.ndarray:
    """The last five results as +1/0/-1, padded with NaN when the team has played fewer."""
    out = np.full((len(forms), FORM_N), np.nan)
    for i, f in enumerate(forms.fillna("").astype(str).to_numpy()):
        s = seq(f)[-FORM_N:]
        if s:
            out[i, FORM_N - len(s):] = s
    return out


def _features(frame: pd.DataFrame, side: str) -> dict[str, np.ndarray]:
    """Everything the distances are computed from, as plain arrays (built once per index)."""
    p, o = _side_cols(side)
    num = lambda c: pd.to_numeric(frame[c], errors="coerce").to_numpy(dtype=float) if c in frame else np.full(len(frame), np.nan)  # noqa: E731
    market = np.column_stack([num("p_home"), num("p_draw"), num("p_away")])
    if side == "away":
        market = market[:, ::-1]                       # read the profile from the away side's view
    gap = num("strength_gap") * (1 if side == "home" else -1)
    move = num("delta_p_home") * (1 if side == "home" else -1)
    return {"market": market, "strength": num(f"{p}tsi_pct"), "opponent": num(f"{o}tsi_pct"), "gap": gap,
            "form": _form_vec(frame[f"{p}form"]) if f"{p}form" in frame else np.full((len(frame), FORM_N), np.nan),
            "goals": np.column_stack([num(f"{p}gf5"), num(f"{p}ga5"), num(f"{o}gf5"), num(f"{o}ga5")]),
            "movement": move}


def _category_scores(pool: dict[str, np.ndarray], q: dict[str, np.ndarray]) -> dict[str, np.ndarray]:
    """0-100 per category for every row of the pool against one query row (NaN = not comparable)."""
    out: dict[str, np.ndarray] = {}
    # market: total variation between the two probability profiles, in probability mass
    d = 0.5 * np.nansum(np.abs(pool["market"] - q["market"]), axis=1)
    d[np.isnan(pool["market"]).any(axis=1) | np.isnan(q["market"]).any()] = np.nan
    out["market"] = 100 * (1 - np.minimum(1.0, d / SCALES["market"]))
    for name in ("strength", "opponent", "gap", "movement"):
        diff = np.abs(pool[name] - q[name])
        out[name] = 100 * (1 - np.minimum(1.0, diff / SCALES[name]))
    for name in ("form", "goals"):
        out[name] = _per_slot_score(pool[name], q[name], SCALES[name], MIN_SLOTS[name])
    return out


def _per_slot_score(pool: np.ndarray, q: np.ndarray, scale: float, min_slots: int) -> np.ndarray:
    """Mean difference over the slots BOTH rows know, NaN when too few of them are comparable.

    Nansum over the raw difference was the bug this replaces: a team with two matches of history
    left three of the five form slots empty, they were skipped, and the pair came out identical."""
    d = np.abs(pool - q)
    known = np.isfinite(d)
    n = known.sum(axis=1)
    mean = np.where(n > 0, np.nansum(d, axis=1) / np.maximum(n, 1), np.nan)
    score = 100 * (1 - np.minimum(1.0, mean / scale))
    score[n < min_slots] = np.nan
    return score


class TwinIndex:
    """A pool of matches prepared once, queried many times."""

    def __init__(self, frame: pd.DataFrame, side: str = "home", weights: Weights | None = None,
                 half_life: float | None = None):
        self.frame = frame.reset_index(drop=True)
        self.side = side
        self.weights = weights or Weights()
        self.half_life = half_life
        self.features = _features(self.frame, side)
        self.dates = self.frame["date"].to_numpy(dtype="datetime64[ns]")

    def _query_features(self, row: pd.Series) -> dict[str, np.ndarray]:
        one = _features(pd.DataFrame([row]), self.side)
        return {k: (v[0] if v.ndim > 1 else v[0]) for k, v in one.items()}

    def category_scores(self, row: pd.Series) -> dict[str, np.ndarray]:
        """Every category's 0-100 score against one query row, before any weighting.

        The expensive half of a query, and the half that does not depend on the weights — which is
        what lets `tune.py` try fifty mixes for the price of one."""
        return _category_scores(self.features, self._query_features(row))

    def query(self, row: pd.Series, k: int = 100, as_of: pd.Timestamp | None = None,
              min_score: float = 0.0) -> TwinResult:
        q = self._query_features(row)
        cats = _category_scores(self.features, q)
        w = self.weights.as_dict()
        num = np.zeros(len(self.frame))
        den = np.zeros(len(self.frame))
        for name, weight in w.items():
            s = cats[name]
            known = np.isfinite(s)
            num += np.where(known, s * weight, self.weights.missing_penalty * weight * 50.0)
            den += np.where(known, weight, self.weights.missing_penalty * weight)
        overall = np.where(den > 0, num / np.maximum(den, 1e-9), np.nan)

        ok = np.ones(len(self.frame), dtype=bool)
        if as_of is not None:
            ok &= self.dates < np.datetime64(pd.Timestamp(as_of))
        if "match_id" in self.frame and "match_id" in row:
            ok &= self.frame["match_id"].to_numpy() != row["match_id"]      # never twin with itself
        ok &= np.isfinite(overall)
        if min_score:
            ok &= overall >= min_score
        idx = np.flatnonzero(ok)
        idx = idx[np.argsort(-overall[idx], kind="stable")][:k]

        rows = self.frame.iloc[idx].copy()
        rows["twin_score"] = np.round(overall[idx], 1)
        for name in w:
            rows[f"sim_{name}"] = np.round(cats[name][idx], 1)
        ref_date = as_of if as_of is not None else row.get("date")
        tw = decay_weights(self.dates[idx], ref_date, self.half_life) if ref_date is not None else np.ones(len(idx))
        rows["twin_weight"] = np.round(tw, 3)
        scores = overall[idx]
        diag = {"k": int(len(idx)), "asked": k, "best": _r(scores.max() if len(scores) else None),
                "worst": _r(scores.min() if len(scores) else None), "mean": _r(scores.mean() if len(scores) else None),
                "median": _r(np.median(scores) if len(scores) else None),
                "n_candidates": int(ok.sum()), "n_above_90": int((scores >= 90).sum()),
                "half_life": self.half_life,
                "n_eff": _r(float(tw.sum() ** 2 / np.sum(tw ** 2)) if len(tw) else None),
                "categories": {name: _r(_nanmean(cats[name][idx])) for name in w}}
        return TwinResult(rows=rows, diagnostics=diag, outcomes=self._outcomes(rows, tw), weights=w)

    def _outcomes(self, rows: pd.DataFrame, tw: np.ndarray | None = None) -> dict:
        """What happened in the twins, next to what the market said about those same twins."""
        from . import engine

        out = {}
        for o in ("win", "draw", "loss", "over25", "btts", "reversal", "ht_draw"):
            m = engine.measure(rows, self.side, o, w=tw)
            if m["n"]:
                out[o] = m
        return out


def _nanmean(a: np.ndarray) -> float | None:
    """The mean of the comparable entries, or None when the category is comparable nowhere.

    A category that no twin can be scored on (movement, before there are closing lines) is reported
    as absent rather than as a warning and a NaN."""
    ok = np.isfinite(a)
    return float(a[ok].mean()) if ok.any() else None


def _r(v) -> float | None:
    return None if v is None or (isinstance(v, float) and not np.isfinite(v)) else round(float(v), 1)


def k_sweep(index: TwinIndex, row: pd.Series, ks: tuple[int, ...] = (50, 100, 200, 500),
            as_of: pd.Timestamp | None = None) -> pd.DataFrame:
    """The spec's K question: does the 100th twin still look like today's match, and does the
    answer change when K does? One row per K with the twin quality and what the twins did."""
    out = []
    for k in ks:
        res = index.query(row, k=k, as_of=as_of)
        win = res.outcomes.get("win", {})
        out.append({"k": k, "n": res.diagnostics["k"], "best": res.diagnostics["best"],
                    "worst": res.diagnostics["worst"], "median": res.diagnostics["median"],
                    "n_above_90": res.diagnostics["n_above_90"],
                    "win_actual": win.get("actual"), "win_market": win.get("market"), "win_diff": win.get("diff")})
    return pd.DataFrame(out)
