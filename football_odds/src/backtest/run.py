"""Full backtest orchestration.

Stage 1  validation seasons  -> parameter grid, choose the configuration (lowest adjusted log loss)
Stage 2  test seasons        -> report market / historical / adjusted scores with the chosen params,
                                calibration, per-season & per-league stability, ablations, ROI
Stage 3  market analyses     -> favourite buckets, league calibration, time stability, league groups
Stage 4  odds movement       -> opening vs closing, steam vs drift

Outputs land in results/backtest/. `selected_params.json` is what the today pipeline reads; its
`backtest_ok` flag is True only when the adjusted model's out-of-sample Brier score is not worse
than the market baseline — otherwise the dashboard says so and never shows a STRONG signal.
"""

from __future__ import annotations

import datetime as dt
import json
import time
from pathlib import Path

import numpy as np
import pandas as pd

from ..config import Settings, season_label
from ..data.providers import ParquetHistoricalProvider
from ..features.vectors import feature_mask
from ..logging_setup import get_logger
from ..models.similarity import METRICS, SimilarityIndex
from .buckets import (cluster_leagues, favourite_bucket_analysis, league_calibration, league_profiles, time_stability,
                      write_league_groups)
from .metrics import brier_per_match, calibration_table, expected_calibration_error, paired_difference, score_table
from .movement import movement_by_bucket, movement_frame, opening_vs_closing_scores, steam_vs_drift_test
from .roi import roi_table
from .walk_forward import compute_neighbours, evaluate_grid, predict_from_neighbours, season_test_frame

log = get_logger("backtest.run")
MARKET_COLS = ["p_home", "p_draw", "p_away"]


def _hl(value) -> float | None:
    return None if value in (None, 0, "null", "None") else float(value)


def _grid(settings: Settings, quick: bool) -> dict:
    sim = settings.section("similarity")
    shr = settings.section("shrinkage")
    grid = {
        "feature_sets": ["1x2", "1x2_ou"],
        "metrics": list(METRICS),
        "scopes": ["global", "same_league"],
        "ks": [int(k) for k in sim.get("k_options", [25, 50, 100, 250, 500])],
        "half_lives": [_hl(h) for h in sim.get("half_life_options", [None, 3, 5, 7])],
        "priors": [float(m) for m in shr.get("prior_strength_options", [0, 10, 25, 50, 100, 200])],
        "min_sims": [0.0] + [float(s) for s in sim.get("min_similarity_options", [98, 97, 95, 92])],
    }
    if quick:
        grid.update({"metrics": ["manhattan", "euclidean"], "scopes": ["global"], "ks": [50, 250, 500],
                     "half_lives": [None, 5.0], "priors": [0.0, 50.0], "min_sims": [0.0, 97.0]})
    return grid


def select_configuration(val_table: pd.DataFrame) -> tuple[dict, dict]:
    """Pick the production configuration from the validation grid with a one-standard-error rule.

    1. Best = lowest adjusted log loss.
    2. Candidates = configurations whose log loss is within one standard error of the best
       (SE of the paired per-match log-loss difference against the market, which is the
       resolution at which two near-market configurations can be told apart).
    3. Among candidates prefer: larger K (more analogues, stabler statistics), then no time
       weighting, then the stronger prior (closer to the market), then the simpler feature set.

    This stops the choice from riding a 0.0001 log-loss difference that is pure noise.
    Returns (selected, {"best": ..., "n_candidates": ...}).
    """
    adj = val_table[val_table["model"] == "adj"].copy()
    adj = adj.sort_values(["logloss", "brier"]).reset_index(drop=True)
    best = adj.iloc[0]
    se = float(best.get("logloss_diff_se", np.nan))
    if not np.isfinite(se) or se <= 0:
        se = 0.0
    cands = adj[adj["logloss"] <= best["logloss"] + se].copy()
    cands["_hl"] = cands["half_life"].fillna(0).astype(float)
    cands["_fs"] = (cands["feature_set"] != "1x2").astype(int)
    cands = cands.sort_values(["k", "_hl", "prior_strength", "_fs", "logloss"], ascending=[False, True, False, True, True])
    pick = cands.iloc[0]

    def _as_dict(r) -> dict:
        return {"feature_set": r["feature_set"], "metric": r["metric"], "scope": r["scope"], "k": int(r["k"]),
                "half_life_years": _hl(r["half_life"]), "prior_strength": float(r["prior_strength"]),
                "min_similarity": float(r["min_similarity"]), "val_logloss": float(r["logloss"]),
                "val_logloss_market": float(r["logloss_market"])}

    return _as_dict(pick), {"best": _as_dict(best), "one_se": se, "n_candidates": int(len(cands))}


def run_full_backtest(settings: Settings, quick: bool = False, leagues: list[str] | None = None,
                      reuse_validation: bool = False) -> dict:
    t0 = time.time()
    out = settings.results_dir / "backtest"
    out.mkdir(parents=True, exist_ok=True)
    df = ParquetHistoricalProvider(settings).load()
    if leagues:
        df = df[df["league"].isin(leagues)].copy()
    bt = settings.section("backtest")
    val_seasons = [str(s) for s in bt["validation_seasons"]]
    test_seasons = [str(s) for s in bt["test_seasons"]]
    grid = _grid(settings, quick)
    k_max = max(grid["ks"])
    log.info("backtest on %d matches, %d leagues; validation %s; test %s", len(df), df["league"].nunique(), val_seasons, test_seasons)

    # ------------------------------------------------------------------ Stage 1: validation grid
    indexes: dict[str, SimilarityIndex] = {fs: SimilarityIndex(df, fs) for fs in grid["feature_sets"]}
    grid_path = out / "validation_grid.csv"
    if reuse_validation and grid_path.exists():
        val_table = pd.read_csv(grid_path)
        log.info("reusing validation grid %s (%d rows)", grid_path, len(val_table))
    else:
        tables = []
        for fs in grid["feature_sets"]:
            val_df = season_test_frame(df, val_seasons, fs)
            market = val_df[MARKET_COLS].to_numpy(dtype=float)
            res = val_df["result_code"].to_numpy(dtype=int)
            for metric in grid["metrics"]:
                for scope in grid["scopes"]:
                    t1 = time.time()
                    nm = compute_neighbours(indexes[fs], val_df, k_max, metric, scope)
                    tab = evaluate_grid(nm, market, res, grid["ks"], grid["half_lives"], grid["priors"], grid["min_sims"])
                    tab["stage"] = "validation"
                    tables.append(tab)
                    log.info("validation %s/%s/%s: %d matches, %.1fs", fs, metric, scope, len(val_df), time.time() - t1)
        val_table = pd.concat(tables, ignore_index=True)
        val_table.to_csv(grid_path, index=False)

    selected, selection_info = select_configuration(val_table)
    log.info("selected on validation (1-SE rule, %d candidates, SE=%.5f): %s | best raw: %s", selection_info["n_candidates"],
             selection_info["one_se"], selected, selection_info["best"])

    # ------------------------------------------------------------------ Stage 2: test seasons
    fs = selected["feature_set"]
    index = indexes[fs]
    test_df = season_test_frame(df, test_seasons, fs)
    market = test_df[MARKET_COLS].to_numpy(dtype=float)
    res = test_df["result_code"].to_numpy(dtype=int)
    nm = compute_neighbours(index, test_df, k_max, selected["metric"], selected["scope"])
    hist, adj, n_eff = predict_from_neighbours(nm, market, selected["k"], selected["half_life_years"],
                                              selected["prior_strength"], selected["min_similarity"])
    prob_sets = {"market": market, "hist": hist, "adj": adj}
    scores = score_table(prob_sets, res)
    scores["stage"] = "test"
    scores.to_csv(out / "test_scores.csv", index=False)

    # Pinnacle benchmark on the subset where Pinnacle pre-closing odds exist
    pin_mask = test_df[["pin_p_home", "pin_p_draw", "pin_p_away"]].notna().all(axis=1).to_numpy()
    if pin_mask.sum() > 100:
        pin = test_df.loc[pin_mask, ["pin_p_home", "pin_p_draw", "pin_p_away"]].to_numpy(dtype=float)
        sub = {"market": market[pin_mask], "pinnacle": pin, "hist": hist[pin_mask], "adj": adj[pin_mask]}
        score_table(sub, res[pin_mask]).to_csv(out / "test_scores_pinnacle_subset.csv", index=False)
    # closing-line benchmarks: the sharpest information available before kick-off (2019/20+ only)
    close_mask = test_df[["pc_home", "pc_draw", "pc_away", "pinc_p_home", "pinc_p_draw", "pinc_p_away"]].notna().all(axis=1).to_numpy()
    if close_mask.sum() > 100:
        sub = {"market": market[close_mask],
               "closing_avg": test_df.loc[close_mask, ["pc_home", "pc_draw", "pc_away"]].to_numpy(dtype=float),
               "pinnacle_closing": test_df.loc[close_mask, ["pinc_p_home", "pinc_p_draw", "pinc_p_away"]].to_numpy(dtype=float),
               "hist": hist[close_mask], "adj": adj[close_mask]}
        score_table(sub, res[close_mask]).to_csv(out / "test_scores_closing_subset.csv", index=False)

    # calibration
    cal = pd.concat([calibration_table(p, res, int(bt.get("calibration_bins", 10))).assign(model=name)
                     for name, p in prob_sets.items()], ignore_index=True)
    cal.to_csv(out / "calibration.csv", index=False)
    ece = {name: expected_calibration_error(p, res) for name, p in prob_sets.items()}

    # per-season and per-league stability of the adjusted model vs market
    stab_rows = []
    for key in ("season", "league"):
        for val, g in test_df.groupby(key).indices.items():
            g = np.asarray(g)
            pb = paired_difference(brier_per_match(adj[g], res[g]), brier_per_match(market[g], res[g]))
            stab_rows.append({"group_type": key, "group": val, "n": len(g), "brier_market": float(brier_per_match(market[g], res[g]).mean()),
                              "brier_adj": float(brier_per_match(adj[g], res[g]).mean()), "brier_diff": pb["mean_diff"],
                              "p_value": pb["p_value"], "adj_better": pb["mean_diff"] < 0})
    stability = pd.DataFrame(stab_rows)
    stability.to_csv(out / "test_stability.csv", index=False)

    # ablations on the test set (transparency only — selection happened on validation)
    abl = evaluate_grid(nm, market, res, grid["ks"], grid["half_lives"], [selected["prior_strength"]] + [p for p in grid["priors"] if p != selected["prior_strength"]], grid["min_sims"])
    abl["stage"] = "test_ablation"
    abl.to_csv(out / "test_ablation.csv", index=False)

    # Model 1 (1X2) vs Model 2 (1X2 + O/U) on the common subset of test matches with O/U odds
    fs_rows = []
    common = test_df if fs == "1x2_ou" else season_test_frame(df, test_seasons, "1x2_ou")
    common_ids = set(common["match_id"])
    for fset in grid["feature_sets"]:
        tdf = season_test_frame(df, test_seasons, fset)
        tdf = tdf[tdf["match_id"].isin(common_ids)].reset_index(drop=True)
        if tdf.empty:
            continue
        m = tdf[MARKET_COLS].to_numpy(dtype=float)
        r = tdf["result_code"].to_numpy(dtype=int)
        nmx = compute_neighbours(indexes[fset], tdf, k_max, selected["metric"], selected["scope"])
        _, a, _ = predict_from_neighbours(nmx, m, selected["k"], selected["half_life_years"], selected["prior_strength"], selected["min_similarity"])
        st = score_table({"market": m, "adj": a}, r)
        st["feature_set"] = fset
        fs_rows.append(st)
    if fs_rows:
        pd.concat(fs_rows, ignore_index=True).to_csv(out / "feature_set_comparison.csv", index=False)

    # scope comparison (global / same league / similar leagues) with the selected other params
    profiles = league_profiles(df)
    profiles.to_csv(out / "league_profiles.csv", index=False)
    groups = cluster_leagues(profiles)
    write_league_groups(groups, settings.results_dir / "league_groups.json")
    scope_rows = []
    for scope in ["global", "same_league"] + (["league_group"] if groups else []):
        nms = compute_neighbours(index, test_df, k_max, selected["metric"], scope, league_groups=groups)
        _, a, ne = predict_from_neighbours(nms, market, selected["k"], selected["half_life_years"], selected["prior_strength"], selected["min_similarity"])
        st = score_table({"market": market, "adj": a}, res)
        st["scope"] = scope
        st["n_eff_median"] = float(np.median(ne))
        scope_rows.append(st)
    pd.concat(scope_rows, ignore_index=True).to_csv(out / "scope_comparison.csv", index=False)

    # ROI simulation
    roi = roi_table(test_df, adj, market, [float(t) for t in bt.get("roi_thresholds_pp", [2, 3, 5, 7.5, 10])])
    roi.to_csv(out / "roi.csv", index=False)

    # ------------------------------------------------------------------ Stage 3: market analyses
    edges = [float(e) for e in bt.get("probability_buckets")]
    favourite_bucket_analysis(df, edges).to_csv(out / "favourite_buckets.csv", index=False)
    league_calibration(df, edges).to_csv(out / "league_calibration.csv", index=False)
    time_stability(df, edges, bt.get("time_stability_periods", {})).to_csv(out / "time_stability.csv", index=False)

    # ------------------------------------------------------------------ Stage 4: odds movement
    mv = movement_frame(df)
    movement_summary = {}
    if len(mv) > 500:
        opening_vs_closing_scores(mv).to_csv(out / "movement_opening_vs_closing.csv", index=False)
        mb = pd.concat([movement_by_bucket(mv, o) for o in ("home", "away")], ignore_index=True)
        mb.to_csv(out / "movement_by_bucket.csv", index=False)
        sv = steam_vs_drift_test(mb)
        sv.to_csv(out / "movement_steam_vs_drift.csv", index=False)
        movement_summary = {"n_matches_with_closing": int(len(mv)),
                            "buckets_with_significant_steam_drift_gap": int((sv["p_value"] < 0.05).sum()) if not sv.empty else 0,
                            "buckets_tested": int(len(sv))}

    # ------------------------------------------------------------------ summary + selected params
    s_market = scores[scores["model"] == "market"].iloc[0]
    s_hist = scores[scores["model"] == "hist"].iloc[0]
    s_adj = scores[scores["model"] == "adj"].iloc[0]
    not_worse = bool(s_adj["brier"] <= s_market["brier"])
    significant = bool(s_adj["brier_p_value"] < 0.05) and not_worse
    # The STRONG signal gate: only when the adjusted model beat the market out-of-sample at p < 0.05.
    # "Not worse but indistinguishable" is not evidence that the analogues carry information.
    backtest_ok = significant
    selected.update({
        "backtest_ok": backtest_ok, "adjusted_not_worse_than_market": not_worse, "significant_improvement": significant,
        "test_seasons": test_seasons, "validation_seasons": val_seasons, "n_test_matches": int(len(test_df)),
        "brier_market": float(s_market["brier"]), "brier_hist": float(s_hist["brier"]), "brier_adj": float(s_adj["brier"]),
        "logloss_market": float(s_market["logloss"]), "logloss_hist": float(s_hist["logloss"]), "logloss_adj": float(s_adj["logloss"]),
        "brier_adj_p_value": float(s_adj["brier_p_value"]), "ece": ece, "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "selection": selection_info,
        "quick": quick, "leagues": leagues or sorted(df["league"].unique().tolist()),
    })
    (out / "selected_params.json").write_text(json.dumps(selected, indent=2, default=str))
    _write_summary(out, selected, scores, val_table, roi, stability, groups, movement_summary, ece)
    log.info("backtest finished in %.0fs -> %s", time.time() - t0, out)
    return selected


def _write_summary(out: Path, sel: dict, scores: pd.DataFrame, val: pd.DataFrame, roi: pd.DataFrame, stab: pd.DataFrame,
                   groups: dict, mv: dict, ece: dict) -> None:
    verdict = ("Historical similarity **improved** out-of-sample calibration versus the market baseline (p < 0.05)"
               if sel["significant_improvement"] else
               "Historical similarity matched the market baseline but the difference is **not statistically significant** — "
               "historical similarity did not improve predictive performance"
               if sel.get("adjusted_not_worse_than_market") else
               "**Historical similarity did not improve predictive performance** over the market baseline")
    lines = [
        "# Walk-forward backtest summary", "", f"Generated: {sel['generated_at']}", "",
        f"Validation seasons: {', '.join(season_label(s) for s in sel['validation_seasons'])}  ",
        f"Test seasons: {', '.join(season_label(s) for s in sel['test_seasons'])}  ",
        f"Test matches: {sel['n_test_matches']}", "",
        "## Verdict", "", verdict + ".", "",
        "## Selected configuration (chosen on validation only)", "",
        "| parameter | value |", "|---|---|",
    ]
    for k in ("feature_set", "metric", "scope", "k", "half_life_years", "prior_strength", "min_similarity"):
        lines.append(f"| {k} | {sel[k]} |")
    info = sel.get("selection", {})
    if info:
        b = info.get("best", {})
        lines += ["", f"One-standard-error rule: {info.get('n_candidates')} configurations lie within SE={info.get('one_se', 0):.5f} "
                  f"of the best validation log loss ({b.get('val_logloss', float('nan')):.5f} vs market {b.get('val_logloss_market', float('nan')):.5f}); "
                  f"the largest-K / simplest one was chosen. Raw best: {b.get('feature_set')} / {b.get('metric')} / {b.get('scope')} / "
                  f"K={b.get('k')} / half-life={b.get('half_life_years')} / prior={b.get('prior_strength')} / min sim={b.get('min_similarity')}."]
    lines += ["", "## Out-of-sample scores (test seasons)", "",
              "| model | Brier | log loss | Brier vs market | p-value | ECE |", "|---|---|---|---|---|---|"]
    for _, r in scores.iterrows():
        lines.append(f"| {r['model']} | {r['brier']:.5f} | {r['logloss']:.5f} | {r['brier_vs_baseline']:+.5f} | {r['brier_p_value']:.3f} | {ece.get(r['model'], float('nan')):.4f} |")
    adj_val = val[val["model"] == "adj"]
    lines += ["", "## Validation grid (top 10 adjusted configurations by log loss)", "",
              "| feature set | metric | scope | K | half-life | prior | min sim | log loss | Brier | market Brier |",
              "|---|---|---|---|---|---|---|---|---|---|"]
    for _, r in adj_val.sort_values("logloss").head(10).iterrows():
        lines.append(f"| {r['feature_set']} | {r['metric']} | {r['scope']} | {r['k']} | {r['half_life'] or 'none'} | {r['prior_strength']:.0f} | {r['min_similarity']:.0f} | {r['logloss']:.5f} | {r['brier']:.5f} | {r['brier_market']:.5f} |")
    lines += ["", "## Stability of the adjusted model vs market (test seasons)", "",
              "| group | n | Brier market | Brier adj | diff | p | adj better |", "|---|---|---|---|---|---|---|"]
    for _, r in stab.iterrows():
        lines.append(f"| {r['group_type']}={r['group']} | {r['n']} | {r['brier_market']:.5f} | {r['brier_adj']:.5f} | {r['brier_diff']:+.5f} | {r['p_value']:.3f} | {'yes' if r['adj_better'] else 'no'} |")
    lines += ["", "## Flat-stake ROI simulation (test seasons, 1 unit per bet)", "",
              "Bets are placed on every outcome whose adjusted probability exceeds the market by the threshold.",
              "`avg` uses the consensus average odds, `max` the best available price (optimistic bound).", "",
              "| price | threshold pp | bets | win rate | avg odds | profit | ROI % | max DD | profitable seasons |",
              "|---|---|---|---|---|---|---|---|---|"]
    for _, r in roi.iterrows():
        wr = f"{100 * r['win_rate']:.1f}%" if pd.notna(r["win_rate"]) else "-"
        ao = f"{r['avg_odds']:.2f}" if pd.notna(r["avg_odds"]) else "-"
        roi_s = f"{r['roi_pct']:+.2f}" if pd.notna(r["roi_pct"]) else "-"
        lines.append(f"| {r['price']} | {r['threshold_pp']} | {r['n_bets']} | {wr} | {ao} | {r['profit']:+.1f} | {roi_s} | {r['max_drawdown']:.1f} | {r['seasons_profitable']}/{r['seasons_total']} |")
    lines += ["", "## Similar-league groups (hierarchical clustering of league profiles)", ""]
    if groups:
        seen = set()
        for lg, members in groups.items():
            key = tuple(sorted(members))
            if key in seen:
                continue
            seen.add(key)
            lines.append(f"- {', '.join(key)}")
    else:
        lines.append("Not enough data for stable groups — the `similar_leagues` scope is disabled.")
    if mv:
        lines += ["", "## Odds movement", "",
                  f"Matches with closing odds: {mv['n_matches_with_closing']}. Closing-probability buckets where steam vs drift "
                  f"realised rates differ at p < 0.05: {mv['buckets_with_significant_steam_drift_gap']} of {mv['buckets_tested']}.",
                  "See movement_by_bucket.csv and movement_steam_vs_drift.csv."]
    lines += ["", "## Reading these numbers", "",
              "- A negative *Brier vs market* means the model is better calibrated than the consensus odds out-of-sample.",
              "- Correlation ≠ exploitable edge: the ROI table uses pre-closing average odds without accounting for limits,",
              "  line movement after collection or bookmaker restrictions.",
              "- Parameters were chosen on the validation seasons only; every number above is from unseen test seasons."]
    (out / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
