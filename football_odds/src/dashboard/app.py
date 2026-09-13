"""Streamlit dashboard.

    python -m src.cli dashboard          (or: streamlit run src/dashboard/app.py)

Reads the prediction files written by `python -m src.cli today` (results/YYYY-MM-DD_predictions.csv,
_details.json, analogues/YYYY-MM-DD_analogues.parquet) and the backtest summary.
"""

from __future__ import annotations

import io
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.config import load_settings  # noqa: E402

st.set_page_config(page_title="Football odds — historical analogues", layout="wide")
settings = load_settings()
RESULTS = settings.results_dir

TABLE_COLS = ["date", "time", "league", "home", "away", "odds_h", "odds_d", "odds_a", "market_h", "market_d", "market_a",
              "n", "hist_h", "hist_d", "hist_a", "adj_h", "adj_d", "adj_a", "edge_h", "edge_d", "edge_a",
              "over25", "under25", "btts", "avg_goals", "confidence", "signal"]
HEADERS = {"date": "DATE", "time": "TIME", "league": "LEAGUE", "home": "HOME", "away": "AWAY", "odds_h": "H ODDS",
           "odds_d": "D ODDS", "odds_a": "A ODDS", "market_h": "MARKET H %", "market_d": "MARKET D %", "market_a": "MARKET A %",
           "n": "SIMILAR N", "hist_h": "HIST H %", "hist_d": "HIST D %", "hist_a": "HIST A %", "adj_h": "ADJ H %",
           "adj_d": "ADJ D %", "adj_a": "ADJ A %", "edge_h": "HOME EDGE", "edge_d": "DRAW EDGE", "edge_a": "AWAY EDGE",
           "over25": "OVER 2.5 %", "under25": "UNDER 2.5 %", "btts": "BTTS %", "avg_goals": "AVG GOALS",
           "confidence": "CONFIDENCE", "signal": "MODEL SIGNAL"}


@st.cache_data(show_spinner=False)
def list_prediction_dates() -> list[str]:
    return sorted({p.name[:10] for p in RESULTS.glob("*_predictions.csv")}, reverse=True)


@st.cache_data(show_spinner=False)
def load_day(stamp: str):
    table = pd.read_csv(RESULTS / f"{stamp}_predictions.csv")
    details_path = RESULTS / f"{stamp}_details.json"
    details = json.loads(details_path.read_text()) if details_path.exists() else {"matches": {}}
    an_path = RESULTS / "analogues" / f"{stamp}_analogues.parquet"
    analogues = pd.read_parquet(an_path) if an_path.exists() else pd.DataFrame()
    return table, details, analogues


@st.cache_data(show_spinner=False)
def load_backtest():
    p = RESULTS / "backtest" / "selected_params.json"
    return json.loads(p.read_text()) if p.exists() else {}


def to_excel(df: pd.DataFrame) -> bytes:
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as xw:
        df.to_excel(xw, index=False, sheet_name="predictions")
    return buf.getvalue()


# ----------------------------------------------------------------------------- sidebar
st.sidebar.title("Filters")
dates = list_prediction_dates()
if not dates:
    st.warning("No prediction files yet. Run `python -m src.cli today` first.")
    st.stop()
stamp = st.sidebar.selectbox("Prediction date", dates)
table, details, analogues = load_day(stamp)
bt = load_backtest()

leagues = sorted(table["league"].unique())
sel_leagues = st.sidebar.multiselect("LEAGUE", leagues, default=leagues)
min_sample = st.sidebar.slider("MINIMUM SAMPLE (N)", 0, int(max(table["n"].max(), 1)), 0, step=10)
min_sim = st.sidebar.slider("MINIMUM AVG SIMILARITY %", 0.0, 100.0, 0.0, step=0.5)
only_dev = st.sidebar.checkbox("HIGH HISTORICAL DEVIATION only", value=False)
min_edge = st.sidebar.slider("Minimum |edge| (pp)", 0.0, 15.0, 0.0, step=0.5)

view = table[table["league"].isin(sel_leagues) & (table["n"] >= min_sample) & (table["avg_similarity"].fillna(0) >= min_sim)]
view = view[view[["edge_h", "edge_d", "edge_a"]].abs().max(axis=1) >= min_edge]
if only_dev:
    view = view[view["signal"].str.contains("DEVIATION")]

# ----------------------------------------------------------------------------- header
st.title("Today's matches — market vs historical analogues")
if bt:
    verdict = ("adjusted model beat the market out-of-sample (p<0.05)" if bt.get("backtest_ok") else
               "historical similarity did NOT significantly improve on the market out-of-sample — no STRONG signals")
    st.caption(f"Backtest ({', '.join(bt.get('test_seasons', []))}): Brier market {bt.get('brier_market', float('nan')):.5f} · "
               f"adjusted {bt.get('brier_adj', float('nan')):.5f} · p={bt.get('brier_adj_p_value', float('nan')):.3f} → **{verdict}**. "
               f"Params: {bt.get('feature_set')} / {bt.get('metric')} / {bt.get('scope')} / K={bt.get('k')} / half-life={bt.get('half_life_years')} / prior={bt.get('prior_strength')}")
else:
    st.caption("No backtest results found — signals are capped at MODERATE until `python -m src.cli backtest` has run.")

n_dev = int(table["signal"].str.contains("DEVIATION").sum())
c1, c2, c3, c4 = st.columns(4)
c1.metric("Matches", len(table))
c2.metric("Shown", len(view))
c3.metric("Deviations flagged", n_dev)
c4.metric("Median N", int(table["n"].median()) if len(table) else 0)
if n_dev == 0:
    st.info("NO STATISTICALLY MEANINGFUL DEVIATION today.")
st.markdown("*Edge = adjusted historical probability − market probability, in percentage points. "
            "An edge is a historical deviation, not a profitable bet.*")

# ----------------------------------------------------------------------------- main table
show = view[TABLE_COLS].rename(columns=HEADERS).copy()
num_cols = [c for c in show.columns if show[c].dtype.kind == "f"]
st.dataframe(show.style.format({c: "{:.1f}" for c in num_cols if "ODDS" not in c} | {c: "{:.2f}" for c in num_cols if "ODDS" in c or c == "AVG GOALS"})
             .map(lambda v: "color:#1a7f37;font-weight:600" if isinstance(v, (int, float)) and v >= 3 else ("color:#b42318" if isinstance(v, (int, float)) and v <= -3 else ""),
                  subset=["HOME EDGE", "DRAW EDGE", "AWAY EDGE"]),
             width="stretch", hide_index=True, height=min(600, 60 + 35 * len(show)))

d1, d2 = st.columns(2)
d1.download_button("Export CSV", view.to_csv(index=False).encode("utf-8"), f"{stamp}_predictions_filtered.csv", "text/csv")
d2.download_button("Export Excel", to_excel(view), f"{stamp}_predictions_filtered.xlsx",
                   "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

# ----------------------------------------------------------------------------- match detail
st.divider()
st.header("Match detail")
if view.empty:
    st.stop()
labels = [f"{r.league} · {r.home} – {r.away} ({r.odds_h:.2f}/{r.odds_d:.2f}/{r.odds_a:.2f})" for r in view.itertuples()]
choice = st.selectbox("Select a match", labels)
row = view.iloc[labels.index(choice)]
det = details.get("matches", {}).get(row["match_id"], {})

st.subheader(f"{row['home']} – {row['away']}  ·  {row['league']}  ·  {row['date']} {row['time'] if isinstance(row['time'], str) else ''}")
m1, m2, m3 = st.columns(3)
m1.markdown(f"**CURRENT MARKET**  \nOdds: {row['odds_h']:.2f} / {row['odds_d']:.2f} / {row['odds_a']:.2f}  \n"
            f"Normalised: {row['market_h']:.1f} / {row['market_d']:.1f} / {row['market_a']:.1f} %")
m2.markdown(f"**HISTORICAL ANALOGUES**  \nN = {int(row['n'])} (n_eff {row['n_eff']:.0f}) · avg similarity {row['avg_similarity']:.1f} % "
            f"(median {row['median_similarity']:.1f}, min {row['min_similarity']:.1f})  \n"
            f"Raw: {row['hist_h']:.1f} / {row['hist_d']:.1f} / {row['hist_a']:.1f} %  \n"
            f"Adjusted: {row['adj_h']:.1f} / {row['adj_d']:.1f} / {row['adj_a']:.1f} %")
m3.markdown(f"**DEVIATION**  \nHOME {row['edge_h']:+.1f} pp · DRAW {row['edge_d']:+.1f} pp · AWAY {row['edge_a']:+.1f} pp  \n"
            f"95 % CI (raw home) {row['ci_h_lo']:.1f}–{row['ci_h_hi']:.1f} %  \n"
            f"Fair odds (adj): {row['fair_h']:.2f} / {row['fair_d']:.2f} / {row['fair_a']:.2f}  \n"
            f"**{row['signal']}** · {row['confidence']}")
st.caption("Signal reasoning: " + str(row["signal_reason"]))

g1, g2, g3 = st.columns(3)
fig = go.Figure()
for name, cols in (("Market", ["market_h", "market_d", "market_a"]), ("Historical", ["hist_h", "hist_d", "hist_a"]), ("Adjusted", ["adj_h", "adj_d", "adj_a"])):
    fig.add_bar(name=name, x=["HOME", "DRAW", "AWAY"], y=[row[c] for c in cols])
fig.update_layout(barmode="group", title="Probability %: market vs historical vs adjusted", height=340, margin=dict(t=40, b=20))
g1.plotly_chart(fig, width="stretch")

gd = det.get("goals_dist", {})
if gd:
    fig2 = go.Figure(go.Bar(x=list(gd.keys()), y=[100 * v for v in gd.values()]))
    fig2.update_layout(title="Total goals distribution % (analogues)", height=340, margin=dict(t=40, b=20))
    g2.plotly_chart(fig2, width="stretch")
sl = det.get("scorelines", {})
if sl:
    top = sorted(sl.items(), key=lambda kv: -kv[1])[:10]
    fig3 = go.Figure(go.Bar(x=[k for k, _ in top], y=[100 * v for _, v in top]))
    fig3.update_layout(title="Most frequent scorelines % (analogues)", height=340, margin=dict(t=40, b=20))
    g3.plotly_chart(fig3, width="stretch")

o1, o2 = st.columns(2)
o1.markdown(f"**Over 2.5** {row['over25']:.1f} % · **Under 2.5** {row['under25']:.1f} % · **BTTS** {row['btts']:.1f} % · "
            f"**Avg goals** {row['avg_goals']:.2f}" + (f" · market O2.5 {row['market_over25']:.1f} %" if pd.notna(row.get("market_over25")) else ""))
scopes = det.get("scopes", {})
if scopes:
    rows = [{"scope": k, "N": v["n"], "hist H/D/A %": " / ".join(f"{100 * x:.1f}" for x in v["hist"]),
             "adj H/D/A %": " / ".join(f"{100 * x:.1f}" for x in v["adj"]), "avg sim %": f"{v['avg_similarity']:.1f}"} for k, v in scopes.items()]
    o2.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
tol = det.get("tolerance", {})
if tol:
    st.markdown("**Model A — tolerance matching (matches within ±tol on all three outcomes)**")
    st.dataframe(pd.DataFrame({mode: {f"±{float(k) * 100:.0f}%": v for k, v in lv.items()} for mode, lv in tol.items()}).T, width="stretch")

st.subheader("TOP HISTORICAL ANALOGUES")
if not analogues.empty:
    an = analogues[analogues["fixture_id"] == row["match_id"]].sort_values("distance")
    top_k = st.radio("Show top", [25, 50, 100, 250, 500], horizontal=True, index=1)
    an = an.head(top_k)
    cols = ["date", "league", "home_team", "away_team", "cons_h", "cons_d", "cons_a", "p_home", "p_draw", "p_away",
            "similarity", "ftr", "score", "ou25", "btts", "weight"]
    show_an = an[[c for c in cols if c in an.columns]].copy()
    for c in ("p_home", "p_draw", "p_away"):
        show_an[c] = 100 * show_an[c]
    show_an["date"] = pd.to_datetime(show_an["date"]).dt.date
    show_an = show_an.rename(columns={"home_team": "Home", "away_team": "Away", "cons_h": "Odds H", "cons_d": "Odds D", "cons_a": "Odds A",
                                      "p_home": "Prob H %", "p_draw": "Prob D %", "p_away": "Prob A %", "similarity": "Similarity %",
                                      "ftr": "Result", "score": "Score", "ou25": "O/U 2.5", "btts": "BTTS", "weight": "Time weight"})
    st.dataframe(show_an.style.format({"Odds H": "{:.2f}", "Odds D": "{:.2f}", "Odds A": "{:.2f}", "Prob H %": "{:.1f}", "Prob D %": "{:.1f}",
                                       "Prob A %": "{:.1f}", "Similarity %": "{:.2f}", "Time weight": "{:.2f}"}),
                 hide_index=True, width="stretch", height=min(700, 60 + 35 * len(show_an)))
    res_counts = an["ftr"].value_counts(normalize=True).reindex(["H", "D", "A"]).fillna(0) * 100
    fig4 = go.Figure(go.Bar(x=["HOME", "DRAW", "AWAY"], y=res_counts.values))
    fig4.update_layout(title=f"Results among the {len(an)} shown analogues (%)", height=300, margin=dict(t=40, b=20))
    st.plotly_chart(fig4, width="stretch")
else:
    st.info("Analogue file not found for this date.")
