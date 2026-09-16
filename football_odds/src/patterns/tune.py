"""TWIN WEIGHT TUNING — stop guessing the mix, measure it.

`twins.Weights` shipped with numbers somebody typed: market 3, strength 2, form 1.5, and so on.
They are plausible and that is exactly the problem — a plausible number nobody tested is an
assumption wearing a lab coat. This module chooses them, and the time-decay half life, the only
way the rest of this project allows: on a **validation window**, scored by a proper scoring rule,
and then reported once on a **test window** that took no part in the choice.

    train / arama   2011-07 → 2018-07     (the twins a query may draw on)
    validation      2018-07 → 2021-07     the configuration is chosen here
    test            2021-07 → 2027-07     touched once, at the end, to report what that bought

The score is the log loss of the twins' own 1X2 rates on the held-out match — the raw rates, not
the shrunk ones. Shrinkage with a prior of 200 pulls every configuration to within a whisker of
the market, which would make the search compare rounding noise. Brier, the shrunk score and the
market's score on the same matches are all reported next to it, so "better" can be read against
"better than the price", which is the only comparison that matters.

Search: one-at-a-time variations around the current best, all evaluated in a single pass over the
sample (the category scores are the expensive part and are computed once per match, then re-weighted
for every candidate — that is what makes ~50 configurations cost barely more than one). The best
move per category is then combined and the combination re-measured, twice. It is a greedy search,
not a global one; it is also 90 configurations rather than 6^7 = 280.000, and the honest report of
what it found is the test window, not the search.

Nothing here writes into the live path by itself: the result lands in
`results/backtest/twin_weights.json` and `twins.load_weights()` picks it up if it is there.
"""

from __future__ import annotations

import datetime as dt
import json

import numpy as np
import pandas as pd

from ..config import Settings
from ..logging_setup import get_logger
from . import state, twins
from .discovery import DEFAULT_WINDOWS, Windows

log = get_logger("patterns.tune")

GRID = {                                  # the values each category weight may take
    "market": (0.0, 1.0, 2.0, 3.0, 4.0, 6.0),
    "strength": (0.0, 0.5, 1.0, 2.0, 3.0, 4.0),
    "opponent": (0.0, 0.5, 1.0, 2.0, 3.0, 4.0),
    "gap": (0.0, 0.5, 1.0, 2.0, 3.0, 4.0),
    "form": (0.0, 0.5, 1.0, 1.5, 2.5, 4.0),
    "goals": (0.0, 0.5, 1.0, 2.0, 3.0, 4.0),
    "movement": (0.0, 0.5, 1.0, 2.0, 3.0, 4.0),
}
HALF_LIVES = (None, 3.0, 5.0, 8.0, 12.0)
K = 100
PRIOR = 200.0                             # only for the reported adjusted score, never for the search
ROUNDS = 2


class _Scored:
    """One configuration and what it scored, kept comparable across the search."""

    __slots__ = ("weights", "half_life", "logloss", "brier", "logloss_adj", "brier_adj", "n")

    def __init__(self, weights: twins.Weights, half_life: float | None):
        self.weights, self.half_life = weights, half_life
        self.logloss = self.brier = self.logloss_adj = self.brier_adj = float("nan")
        self.n = 0

    def key(self) -> tuple:
        return (tuple(self.weights.as_dict().items()), self.half_life)

    def as_dict(self) -> dict:
        return {"weights": self.weights.as_dict(), "half_life": self.half_life, "n": self.n,
                "logloss": round(self.logloss, 5), "brier": round(self.brier, 5),
                "logloss_adj": round(self.logloss_adj, 5), "brier_adj": round(self.brier_adj, 5)}


def _sample(frame: pd.DataFrame, window: tuple[str, str], n: int, seed: int) -> pd.DataFrame:
    lo, hi = window
    sub = frame[(frame["date"] >= pd.Timestamp(lo)) & (frame["date"] < pd.Timestamp(hi))]
    sub = sub[np.isfinite(pd.to_numeric(sub["p_home"], errors="coerce")) & sub["ftr"].isin(["H", "D", "A"])]
    if len(sub) > n:
        sub = sub.sample(n=n, random_state=seed)
    return sub.sort_values(["date", "match_id"])


def _probs_for_configs(index: twins.TwinIndex, rows: pd.DataFrame, configs: list[_Scored],
                       k: int = K, log_every: int = 200) -> np.ndarray:
    """(config, match, 3) twin rates. The category scores are computed once per match and reused.

    This is the whole reason the search is affordable: the distance work does not depend on the
    weights, only the weighted mean over it does."""
    out = np.full((len(configs), len(rows), 3), np.nan)
    ftr_pool = index.frame["ftr"].astype(str).to_numpy()
    ids = index.frame["match_id"].to_numpy() if "match_id" in index.frame else None
    names = list(twins.CATEGORIES)
    penalty = configs[0].weights.missing_penalty
    W = np.array([[cfg.weights.as_dict()[n] for n in names] for cfg in configs], dtype=np.float32)
    for i, (_, row) in enumerate(rows.iterrows()):
        if log_every and i and i % log_every == 0:
            log.info("  %d / %d matches", i, len(rows))
        cats = index.category_scores(row)
        # the weighted mean is linear in the weights, so the per-category parts are built once and
        # every configuration is then one row of a matrix product rather than its own pass
        A = np.empty((len(names), len(index.frame)), dtype=np.float32)
        B = np.empty_like(A)
        for j, name in enumerate(names):
            s = cats[name]
            known = np.isfinite(s)
            A[j] = np.where(known, s, penalty * 50.0)
            B[j] = np.where(known, 1.0, penalty)
        num, den = W @ A, W @ B
        allowed = index.dates < np.datetime64(pd.Timestamp(row["date"]))
        if ids is not None and "match_id" in row:
            allowed &= ids != row["match_id"]
        pool = np.flatnonzero(allowed)
        if not len(pool):
            continue
        is_h, is_d = ftr_pool[pool] == "H", ftr_pool[pool] == "D"
        for c, cfg in enumerate(configs):
            overall = np.where(den[c][pool] > 0, num[c][pool] / np.maximum(den[c][pool], 1e-9), -np.inf)
            kk = min(k, len(pool))
            take = np.argpartition(-overall, kk - 1)[:kk] if kk < len(pool) else np.arange(len(pool))
            take = take[np.isfinite(overall[take])]
            if not len(take):
                continue
            w = twins.decay_weights(index.dates[pool[take]], row["date"], cfg.half_life)
            tot = w.sum()
            if tot <= 0:
                continue
            h, d = w[is_h[take]].sum(), w[is_d[take]].sum()
            out[c, i] = [h / tot, d / tot, (tot - h - d) / tot]
    return out


def _score(probs: np.ndarray, rows: pd.DataFrame, market: np.ndarray) -> tuple[float, float, float, float, int]:
    y = rows["ftr"].map({"H": 0, "D": 1, "A": 2}).to_numpy(dtype=int)
    ok = np.isfinite(probs).all(axis=1)
    if not ok.any():
        return (float("nan"),) * 4 + (0,)
    p, yy, mk = _norm(probs[ok]), y[ok], market[ok]
    adj = _norm((K * p + PRIOR * mk) / (K + PRIOR))
    return (_logloss(p, yy), _brier(p, yy), _logloss(adj, yy), _brier(adj, yy), int(ok.sum()))


def _norm(p: np.ndarray) -> np.ndarray:
    p = np.clip(p, 1e-4, 1.0)
    return p / p.sum(axis=1, keepdims=True)


def _logloss(p: np.ndarray, y: np.ndarray) -> float:
    return float(-np.mean(np.log(p[np.arange(len(y)), y])))


def _brier(p: np.ndarray, y: np.ndarray) -> float:
    one = np.zeros_like(p)
    one[np.arange(len(y)), y] = 1.0
    return float(np.mean(np.sum((p - one) ** 2, axis=1)))


def _market(rows: pd.DataFrame) -> np.ndarray:
    return _norm(rows[["p_home", "p_draw", "p_away"]].to_numpy(dtype=float))


def _evaluate(index: twins.TwinIndex, rows: pd.DataFrame, configs: list[_Scored], k: int) -> None:
    probs = _probs_for_configs(index, rows, configs, k=k)
    market = _market(rows)
    for c, cfg in enumerate(configs):
        cfg.logloss, cfg.brier, cfg.logloss_adj, cfg.brier_adj, cfg.n = _score(probs[c], rows, market)


def search(index: twins.TwinIndex, rows: pd.DataFrame, base: twins.Weights | None = None,
           k: int = K, rounds: int = ROUNDS) -> tuple[_Scored, list[dict]]:
    """Greedy one-at-a-time search around `base`. Returns the winner and every configuration tried."""
    best = _Scored(base or twins.Weights(), None)
    tried: list[dict] = []
    seen: set[tuple] = set()

    for r in range(rounds):
        cands = [_Scored(best.weights, hl) for hl in HALF_LIVES]
        for name, values in GRID.items():
            for v in values:
                if v == getattr(best.weights, name):
                    continue
                cands.append(_Scored(best.weights.replace(**{name: v}), best.half_life))
        cands = [c for c in cands if c.key() not in seen]
        if not cands:
            break
        log.info("round %d: %d configurations over %d matches", r + 1, len(cands), len(rows))
        _evaluate(index, rows, cands, k)
        for c in cands:
            seen.add(c.key())
            tried.append(c.as_dict())

        if np.isnan(best.logloss):                      # score the starting point in the first round
            _evaluate(index, rows, [best], k)
            tried.append({**best.as_dict(), "base": True})
            seen.add(best.key())

        # combine the best move per coordinate, then let the combination compete with the singles
        moved = {}
        for name in GRID:
            pool = [c for c in cands if c.half_life == best.half_life
                    and getattr(c.weights, name) != getattr(best.weights, name)
                    and all(getattr(c.weights, o) == getattr(best.weights, o) for o in GRID if o != name)]
            win = min((c for c in pool if np.isfinite(c.logloss)), key=lambda c: c.logloss, default=None)
            if win is not None and win.logloss < best.logloss:
                moved[name] = getattr(win.weights, name)
        extra = []
        if moved:
            extra.append(_Scored(best.weights.replace(**moved), best.half_life))
        hl_win = min((c for c in cands if c.weights.as_dict() == best.weights.as_dict() and np.isfinite(c.logloss)),
                     key=lambda c: c.logloss, default=None)
        if hl_win is not None and moved:
            extra.append(_Scored(best.weights.replace(**moved), hl_win.half_life))
        extra = [c for c in extra if c.key() not in seen]
        if extra:
            _evaluate(index, rows, extra, k)
            for c in extra:
                seen.add(c.key())
                tried.append({**c.as_dict(), "combined": True})

        pick = min((c for c in cands + extra if np.isfinite(c.logloss)), key=lambda c: c.logloss, default=None)
        if pick is None or pick.logloss >= best.logloss:
            log.info("round %d improved nothing — stopping", r + 1)
            break
        log.info("round %d: %.5f -> %.5f  %s hl=%s", r + 1, best.logloss, pick.logloss,
                 pick.weights.as_dict(), pick.half_life)
        best = pick
    return best, tried


def run(settings: Settings, windows: Windows = DEFAULT_WINDOWS, n_val: int = 600, n_test: int = 1200,
        k: int = K, seed: int = 7) -> dict:
    """Choose on validation, then report once on test. Writes results/backtest/twin_weights.json."""
    frame = state.load(settings)
    if frame is None:
        raise FileNotFoundError("match_state.parquet is missing — run `cli state` first")
    frame = frame.sort_values(["date", "match_id"]).reset_index(drop=True)
    index = twins.TwinIndex(frame, "home")

    val = _sample(frame, windows.validation, n_val, seed)
    test = _sample(frame, windows.test, n_test, seed + 1)
    log.info("validation %d matches, test %d matches", len(val), len(test))

    started = dt.datetime.now()
    base = twins.Weights()
    best, tried = search(index, val, base, k=k)

    # "does time decay help?" deserves its own number rather than an inference from the search: the
    # half lives are swept once more at the FINAL weights, on both windows. The search only ever saw
    # them at the weights it happened to hold at the time.
    sweep_val = [_Scored(best.weights, hl) for hl in HALF_LIVES]
    _evaluate(index, val, sweep_val, k)
    sweep_test = [_Scored(best.weights, hl) for hl in HALF_LIVES]
    _evaluate(index, test, sweep_test, k)
    decay = [{"half_life": v.half_life, "validation": round(v.logloss, 5), "test": round(t.logloss, 5)}
             for v, t in zip(sweep_val, sweep_test)]

    # the test window is read ONCE, after the choice is frozen, for the defaults and the winner
    frozen = [_Scored(base, None), _Scored(best.weights, best.half_life)]
    _evaluate(index, test, frozen, k)
    base_test, best_test = frozen
    market_test = _market(test)
    y = test["ftr"].map({"H": 0, "D": 1, "A": 2}).to_numpy(dtype=int)
    mk = {"logloss": round(_logloss(market_test, y), 5), "brier": round(_brier(market_test, y), 5)}

    base_val = next((t for t in tried if t.get("base")), None)
    out = {
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "windows": {"validation": list(windows.validation), "test": list(windows.test)},
        "k": k, "prior_for_adjusted": PRIOR, "n_configs": len(tried),
        "seconds": round((dt.datetime.now() - started).total_seconds()),
        "chosen": best.as_dict(), "default_on_validation": base_val, "decay_sweep": decay,
        "test": {"chosen": best_test.as_dict(), "default": base_test.as_dict(), "market": mk},
        "beats_default_on_test": bool(np.isfinite(best_test.logloss) and np.isfinite(base_test.logloss)
                                      and best_test.logloss < base_test.logloss),
        "beats_market_on_test": bool(np.isfinite(best_test.logloss) and best_test.logloss < mk["logloss"]),
        "tried": sorted(tried, key=lambda t: (np.isnan(t["logloss"]), t["logloss"]))[:40],
    }
    path = settings.results_dir / "backtest" / "twin_weights.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
    log.info("wrote %s", path)
    return out


def report(out: dict) -> str:
    c, t = out["chosen"], out["test"]
    lines = [
        "İKİZ AĞIRLIKLARI — doğrulama penceresinde seçildi, test penceresinde bir kez ölçüldü",
        f"  denenen yapılandırma : {out['n_configs']}  ({out['seconds']} s)",
        f"  seçilen ağırlıklar   : {c['weights']}",
        f"  seçilen yarı ömür    : {c['half_life']} yıl" if c["half_life"] else "  seçilen yarı ömür    : yok (zaman ağırlığı kapalı)",
        "",
        f"  doğrulama  seçilen {c['logloss']:.5f}   varsayılan {(out['default_on_validation'] or {}).get('logloss')}",
        f"  TEST       seçilen {t['chosen']['logloss']:.5f}   varsayılan {t['default']['logloss']:.5f}   piyasa {t['market']['logloss']:.5f}",
        "",
        f"  varsayılanı testte geçti mi : {'EVET' if out['beats_default_on_test'] else 'HAYIR'}",
        f"  piyasayı testte geçti mi    : {'EVET' if out['beats_market_on_test'] else 'HAYIR'}",
        "",
        "  ZAMAN AĞIRLIĞI — seçilen ağırlıklarla yarı ömür taraması (log loss, düşük = iyi)",
        "    yarı ömür   doğrulama      test",
    ]
    for d in out.get("decay_sweep", []):
        name = "kapalı" if d["half_life"] is None else f"{d['half_life']:g} yıl"
        lines.append(f"    {name:<11} {d['validation']:.5f}   {d['test']:.5f}")
    return "\n".join(lines)
