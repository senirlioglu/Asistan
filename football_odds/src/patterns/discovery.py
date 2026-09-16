"""PATTERN DISCOVERY — scan many conditions, then try very hard to disqualify what looks good.

Scanning thousands of conditions and reporting the best ones is how you produce nonsense: with
2.000 claims measured at 95 %, a hundred come back "significant" from noise alone. So the finding
step here is the cheap part and the disqualifying steps are the point.

    1  KEŞİF      (train, oldest seasons)   measure every candidate; keep the ones that clear the
                                            minimum sample and look different from the price
    2  DOĞRULAMA  (validation, middle)      re-measure ONLY those; keep the ones that repeat with
                                            the same sign — a pattern that flips direction is noise
    3  TEST       (test, untouched)         measure the survivors once, then apply Benjamini-
                                            Hochberg across that set. Nothing else is ever reported

The candidate grid is written out in `candidates()` rather than generated open-endedly, so the
number of tests is auditable: whoever reads the result can count what was tried. A pattern is only
ever described as a finding if it came through all three windows with the same sign, and even then
the honest reading is "worth watching from here", not "works" — the test window is one sample.

Benchmarks are the same as everywhere else in this package: the market's own price where
Football-Data quotes it, and matches carrying a similar price where it does not.
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass

import numpy as np
import pandas as pd

from ..logging_setup import get_logger
from . import engine
from .engine import Pattern

log = get_logger("patterns.discovery")

FORMS = ("WWW", "WWWW", "WWWWW", "LLL", "LLLL", "DDD", "WW-D-WW", "WWW-D-WWW", "WLWLW", "WDWDW", "DD")
PRICE_BANDS = (None, (0.0, 0.30), (0.30, 0.45), (0.45, 0.60), (0.60, 0.80), (0.80, 1.0))
REST_BANDS = (None, (0.0, 3.0), (8.0, 400.0))
OUTCOMES = ("win", "draw", "loss", "over25", "reversal", "ht_draw")
PRICED = ("win", "draw", "loss", "over25")

MIN_N = 200                 # a candidate below this never enters the funnel, however good it looks
MIN_EDGE = 1.0              # percentage points; smaller than this is not worth a bet slip anyway


@dataclass
class Windows:
    """Time-based split. Never random: a future match may not help discover a past pattern."""

    train: tuple[str, str]
    validation: tuple[str, str]
    test: tuple[str, str]

    def slice(self, frame: pd.DataFrame, which: str) -> pd.DataFrame:
        lo, hi = getattr(self, which)
        return frame[(frame["date"] >= pd.Timestamp(lo)) & (frame["date"] < pd.Timestamp(hi))]


DEFAULT_WINDOWS = Windows(train=("2011-07-01", "2018-07-01"),
                          validation=("2018-07-01", "2021-07-01"),
                          test=("2021-07-01", "2027-07-01"))


def candidates() -> list[Pattern]:
    """Every condition the scan will try, written out so the number of tests can be counted."""
    out: list[Pattern] = []
    for form, side, price, rest in itertools.product(FORMS, ("home", "away"), PRICE_BANDS, REST_BANDS):
        # rest goes in the dataclass field, not in `extra`: `label()` prints the field, so two
        # candidates that differ only by their rest band cannot print the same name
        out.append(Pattern(form=form, side=side, market=price, rest_days=rest))
    return out


def _only(df: pd.DataFrame, pairs: dict) -> pd.DataFrame:
    """The rows of `df` that belong to the (pattern, outcome) pairs still in the funnel."""
    if df.empty:
        return df
    return df[[(k, o) in pairs for k, o in zip(df["key"], df["outcome"])]]


def _key(p: Pattern) -> str:
    return f"{p.side}|{p.form}|{p.market}|{p.rest_days}|{sorted(p.extra.items())}"


def measure_all(frame: pd.DataFrame, patterns: list[Pattern], outcomes: tuple[str, ...] = OUTCOMES,
                min_n: int = MIN_N, log_every: int = 100) -> pd.DataFrame:
    """One row per (pattern, outcome) with the edge over the market or over similar prices."""
    base = {side: engine.baseline(frame, side, PRICED) for side in ("home", "away")}
    rows = []
    for i, p in enumerate(patterns):
        if log_every and i and i % log_every == 0:
            log.info("scan %d / %d", i, len(patterns))
        sub = engine.select(frame, p)
        if len(sub) < min_n:
            continue
        unpriced = tuple(o for o in outcomes if o not in PRICED)
        refs = engine.matched_rates(frame, sub, p.side, unpriced) if unpriced else {}
        for o in outcomes:
            m = engine.measure(sub, p.side, o, ref=refs.get(o))
            if not m["n"] or m["n"] < min_n:
                continue
            if o in PRICED and m.get("diff") is not None:
                off = base[p.side].get(o, 0.0)        # the pool's own bias, removed before anything is an edge
                edge, lo, hi = m["diff"] - off, m["diff_ci"][0] - off, m["diff_ci"][1] - off
            else:
                edge, (lo, hi) = m.get("vs_ref"), (m.get("vs_ref_ci") or [None, None])
            if edge is None or lo is None or m.get("p") is None:
                continue          # no benchmark, no claim — the rule the whole package runs on
            rows.append({"key": _key(p), "label": p.label(), "side": p.side, "form": p.form, "outcome": o,
                         "n": m["n"], "actual": m["actual"], "market": m.get("market"), "ref": m.get("ref"),
                         "edge": edge, "lo": lo, "hi": hi, "p": m.get("p"),
                         "priced": o in PRICED, "pattern": p})
    return pd.DataFrame(rows)


def discover(frame: pd.DataFrame, windows: Windows = DEFAULT_WINDOWS, min_n: int = MIN_N,
             min_edge: float = MIN_EDGE, alpha: float = 0.05, patterns: list[Pattern] | None = None) -> dict:
    """Run the three windows and return everything, including how many died at each step."""
    cands = patterns if patterns is not None else candidates()
    log.info("%d candidate patterns x %d outcomes", len(cands), len(OUTCOMES))

    train = measure_all(windows.slice(frame, "train"), cands, min_n=min_n)
    if train.empty:
        return {"stages": {"scanned": 0}, "survivors": pd.DataFrame()}
    keep = train[(train["edge"].abs() >= min_edge) & (train["p"].notna()) & (train["p"] < alpha)]
    log.info("train: %d claims measured, %d worth a second look", len(train), len(keep))

    pairs = {(r["key"], r["outcome"]): r["pattern"] for _, r in keep.iterrows()}
    val = measure_all(windows.slice(frame, "validation"), list({_key(p): p for p in pairs.values()}.values()),
                      outcomes=tuple(sorted({o for _, o in pairs})), min_n=min_n)
    val = _only(val, pairs)
    merged = val.merge(keep[["key", "outcome", "edge"]], on=["key", "outcome"], suffixes=("", "_train")) if len(val) \
        else pd.DataFrame(columns=[*keep.columns, "edge_train"])
    confirmed = merged[(np.sign(merged["edge"]) == np.sign(merged["edge_train"]))
                       & (merged["edge"].abs() >= min_edge) & merged["p"].notna() & (merged["p"] < alpha)] \
        if len(merged) else merged
    # a claim that simply had too few matches in the shorter window did not FAIL — it was never asked
    unmeasured_val = len(pairs) - len(merged)
    log.info("validation: %d re-measured (%d too small to ask), %d repeated with the same sign",
             len(merged), unmeasured_val, len(confirmed))

    survivors = pd.DataFrame()
    unmeasured_test = 0
    if not confirmed.empty:
        pairs2 = {(r["key"], r["outcome"]): r["pattern"] for _, r in confirmed.iterrows()}
        test = measure_all(windows.slice(frame, "test"), list({_key(p): p for p in pairs2.values()}.values()),
                           outcomes=tuple(sorted({o for _, o in pairs2})), min_n=min_n)
        test = _only(test, pairs2).copy()
        unmeasured_test = len(pairs2) - len(test)
        if not test.empty:
            test["q"] = engine.fdr(list(test["p"]))
            test = test.merge(confirmed[["key", "outcome", "edge"]], on=["key", "outcome"], suffixes=("", "_val"))
            survivors = test[(test["q"] <= alpha) & (np.sign(test["edge"]) == np.sign(test["edge_val"]))]
        log.info("test: %d re-measured (%d too small to ask), %d survived FDR with the same sign",
                 len(test), unmeasured_test, len(survivors))

    stages = {"candidates": len(cands), "claims_scanned": int(len(train)),
              "passed_train": int(len(keep)), "validation_too_small": int(unmeasured_val),
              "validation_measured": int(len(merged)), "passed_validation": int(len(confirmed)),
              "test_too_small": int(unmeasured_test), "survived_test": int(len(survivors))}
    return {"stages": stages, "train": train, "confirmed": confirmed, "survivors": survivors, "windows": windows}


def report(result: dict) -> str:
    s = result["stages"]
    out = [f"aday desen: {s.get('candidates', 0)} · ölçülen iddia: {s.get('claims_scanned', 0)}",
           f"keşif penceresini geçen: {s.get('passed_train', 0)}",
           f"doğrulama: {s.get('validation_measured', 0)} tanesi yeniden ölçüldü "
           f"({s.get('validation_too_small', 0)} tanesi bu pencerede yeterli maça ulaşmadı), "
           f"aynı yönde tekrarlayan: {s.get('passed_validation', 0)}",
           f"test penceresinde FDR'den sağ çıkan: {s.get('survived_test', 0)}"]
    surv = result.get("survivors")
    if surv is not None and len(surv):
        out.append("\nSAĞ KALANLAR (test penceresi, düzeltilmiş):")
        for _, r in surv.iterrows():
            ref = f"piyasa %{r['market']:.1f}" if r["priced"] else f"benzer fiyat %{r['ref']:.1f}"
            side = "ev" if r["side"] == "home" else "dep"
            out.append(f"  [{side}] {r['label']:42} {r['outcome']:8} N={r['n']:5}  %{r['actual']:.1f} vs {ref}"
                       f"  fark {r['edge']:+.1f} [{r['lo']:+.1f}, {r['hi']:+.1f}]  q={r['q']:.3f}")
    else:
        out.append("\nHiçbir desen üç pencereden de geçemedi.")
    return "\n".join(out)
