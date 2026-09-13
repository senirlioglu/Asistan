"""Walk-forward backtest of the market re-calibration models.

For every test season S the calibrator is fitted on all matches from seasons strictly before S
(never on S itself), applied to S, and scored against the market. Because the training frontier
is a season boundary, nothing from the test season — not even its early rounds — enters the fit.

Outputs (results/backtest/):
    market_calibration_scores.csv     overall Brier/log loss vs market, per model
    market_calibration_by_season.csv  per-season stability
    market_calibration_roi.csv        flat-stake ROI at the usual thresholds
    market_calibration_summary.md
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from ..config import Settings, season_label
from ..data.providers import ParquetHistoricalProvider
from ..logging_setup import get_logger
from ..models.calibration import CALIBRATORS, MARKET_COLS
from .metrics import brier_per_match, paired_difference, score_table
from .roi import roi_table

log = get_logger("backtest.calibration")


def walk_forward_calibration(df: pd.DataFrame, test_seasons: list[str], min_train_seasons: int = 4,
                             models: tuple[str, ...] = ("isotonic", "bucket")) -> tuple[pd.DataFrame, dict[str, np.ndarray]]:
    d = df[df["has_1x2"] & df["result_code"].notna()].sort_values(["date", "match_id"]).reset_index(drop=True)
    seasons = sorted(d["season"].unique())
    preds: dict[str, list[np.ndarray]] = {m: [] for m in models}
    frames: list[pd.DataFrame] = []
    for s in test_seasons:
        train_seasons = [x for x in seasons if x < s]
        if len(train_seasons) < min_train_seasons:
            log.warning("season %s skipped: only %d training seasons", s, len(train_seasons))
            continue
        train = d[d["season"].isin(train_seasons)]
        test = d[d["season"] == s]
        if test.empty:
            continue
        Xtr, ytr = train[MARKET_COLS].to_numpy(dtype=float), train["result_code"].to_numpy(dtype=int)
        Xte = test[MARKET_COLS].to_numpy(dtype=float)
        for m in models:
            cal = CALIBRATORS[m]().fit(Xtr, ytr)
            preds[m].append(cal.predict(Xte))
        frames.append(test)
    test_df = pd.concat(frames, ignore_index=True)
    return test_df, {m: np.vstack(v) for m, v in preds.items()}


def run_calibration_backtest(settings: Settings, out_dir: Path | None = None) -> dict:
    out = out_dir or (settings.results_dir / "backtest")
    out.mkdir(parents=True, exist_ok=True)
    df = ParquetHistoricalProvider(settings).load()
    bt = settings.section("backtest")
    test_seasons = [str(s) for s in bt["test_seasons"]]
    test_df, preds = walk_forward_calibration(df, test_seasons, int(bt.get("min_train_seasons", 4)))
    market = test_df[MARKET_COLS].to_numpy(dtype=float)
    res = test_df["result_code"].to_numpy(dtype=int)

    prob_sets = {"market": market, **preds}
    scores = score_table(prob_sets, res)
    scores.to_csv(out / "market_calibration_scores.csv", index=False)

    rows = []
    for s, g in test_df.groupby("season").indices.items():
        g = np.asarray(g)
        for m, p in preds.items():
            pd_ = paired_difference(brier_per_match(p[g], res[g]), brier_per_match(market[g], res[g]))
            rows.append({"season": s, "model": m, "n": len(g), "brier_market": float(brier_per_match(market[g], res[g]).mean()),
                         "brier_model": float(brier_per_match(p[g], res[g]).mean()), "brier_diff": pd_["mean_diff"], "p_value": pd_["p_value"]})
    by_season = pd.DataFrame(rows)
    by_season.to_csv(out / "market_calibration_by_season.csv", index=False)

    rois = []
    for m, p in preds.items():
        r = roi_table(test_df, p, market, [float(t) for t in bt.get("roi_thresholds_pp", [2, 3, 5, 7.5, 10])])
        r.insert(0, "model", m)
        rois.append(r)
    roi = pd.concat(rois, ignore_index=True)
    roi.to_csv(out / "market_calibration_roi.csv", index=False)

    best = scores[scores["model"] != "market"].sort_values("brier").iloc[0]
    summary = {
        "n_test_matches": int(len(test_df)), "test_seasons": test_seasons,
        "best_model": best["model"], "brier_market": float(scores.loc[scores["model"] == "market", "brier"].iloc[0]),
        "brier_best": float(best["brier"]), "brier_diff": float(best["brier_vs_baseline"]), "p_value": float(best["brier_p_value"]),
        "significant": bool(best["brier_vs_baseline"] < 0 and best["brier_p_value"] < 0.05),
        "seasons_better": int((by_season[by_season["model"] == best["model"]]["brier_diff"] < 0).sum()),
        "seasons_total": int(by_season["season"].nunique()),
    }
    (out / "market_calibration_summary.json").write_text(json.dumps(summary, indent=2))
    _write_summary(out, summary, scores, by_season, roi)
    log.info("calibration backtest: %s", summary)
    return summary


def _write_summary(out: Path, s: dict, scores: pd.DataFrame, by_season: pd.DataFrame, roi: pd.DataFrame) -> None:
    verdict = ("Re-calibrating the market on past seasons **improved** out-of-sample Brier (p < 0.05)" if s["significant"]
               else "Re-calibrating the market did **not** significantly improve out-of-sample Brier")
    lines = ["# Market re-calibration backtest", "",
             f"Test seasons: {', '.join(season_label(x) for x in s['test_seasons'])} · {s['n_test_matches']} matches · "
             f"training = all seasons strictly before each test season.", "",
             "## Verdict", "", f"{verdict}: best model `{s['best_model']}` Brier {s['brier_best']:.5f} vs market {s['brier_market']:.5f} "
             f"({s['brier_diff']:+.5f}, p={s['p_value']:.3f}); better in {s['seasons_better']}/{s['seasons_total']} test seasons.", "",
             "## Scores", "", "| model | Brier | log loss | Brier vs market | p |", "|---|---|---|---|---|"]
    for _, r in scores.iterrows():
        lines.append(f"| {r['model']} | {r['brier']:.5f} | {r['logloss']:.5f} | {r['brier_vs_baseline']:+.5f} | {r['brier_p_value']:.3f} |")
    lines += ["", "## Per season", "", "| season | model | n | Brier market | Brier model | diff | p |", "|---|---|---|---|---|---|---|"]
    for _, r in by_season.iterrows():
        lines.append(f"| {season_label(str(r['season']))} | {r['model']} | {r['n']} | {r['brier_market']:.5f} | {r['brier_model']:.5f} | {r['brier_diff']:+.5f} | {r['p_value']:.3f} |")
    lines += ["", "## Flat-stake ROI (1 unit, thresholds on model − market probability)", "",
              "| model | price | threshold pp | bets | win rate | avg odds | profit | ROI % | max DD | profitable seasons |",
              "|---|---|---|---|---|---|---|---|---|---|"]
    for _, r in roi.iterrows():
        wr = f"{100 * r['win_rate']:.1f}%" if pd.notna(r["win_rate"]) else "-"
        ao = f"{r['avg_odds']:.2f}" if pd.notna(r["avg_odds"]) else "-"
        ro = f"{r['roi_pct']:+.2f}" if pd.notna(r["roi_pct"]) else "-"
        lines.append(f"| {r['model']} | {r['price']} | {r['threshold_pp']} | {r['n_bets']} | {wr} | {ao} | {r['profit']:+.1f} | {ro} | {r['max_drawdown']:.1f} | {r['seasons_profitable']}/{r['seasons_total']} |")
    lines += ["", "The calibrators see only the margin-free market probability; the favourite-longshot pattern in",
              "`favourite_buckets.csv` is exactly what they try to exploit. A negative *Brier vs market* with p < 0.05 and",
              "most seasons better is the minimum bar before any of this is used live."]
    (out / "market_calibration_summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
