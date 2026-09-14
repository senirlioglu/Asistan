"""Streamlit dashboard — Turkish, mobile-first, card based.

    python -m src.cli dashboard          (or: streamlit run src/dashboard/app.py)

Reads results/YYYY-MM-DD_predictions.csv, _details.json, analogues/…parquet and the backtest
summary. Every number is explained in plain language; abbreviations are avoided on screen and
defined in the glossary at the bottom.
"""

from __future__ import annotations

import io
import json
import os
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
from src.pipeline.jobs import is_running, read_status, start_background  # noqa: E402

st.set_page_config(page_title="Maç Oranları — Tarihsel Karşılaştırma", page_icon="⚽", layout="centered",
                   initial_sidebar_state="collapsed")
settings = load_settings()
RESULTS = settings.results_dir
ADMIN_KEY = os.environ.get("FO_ADMIN_KEY", "")
DAYS_AHEAD = int(os.environ.get("FO_DAYS_AHEAD", "2"))

# --------------------------------------------------------------------------- design tokens
# Validated two-series palette (dataviz reference palette, slots 1 and 2): blue = piyasa, orange = geçmiş.
C_MARKET = "#2a78d6"
C_HIST = "#eb6834"
C_TEXT = "#0b0b0b"
C_TEXT2 = "#52514e"
C_MUTED = "#8a8985"
C_GRID = "#e6e5e1"
C_SURFACE = "#fcfcfb"

st.markdown(f"""
<style>
  .block-container {{ padding: 1rem 0.9rem 4rem; max-width: 880px; }}
  h1 {{ font-size: 1.55rem !important; line-height: 1.25; }}
  h2 {{ font-size: 1.2rem !important; margin-top: 0.4rem; }}
  h3 {{ font-size: 1.05rem !important; }}
  .fo-lead {{ color: {C_TEXT2}; font-size: 0.95rem; }}
  .fo-card-title {{ font-size: 1.12rem; font-weight: 700; color: {C_TEXT}; margin: 0; }}
  .fo-card-sub {{ color: {C_TEXT2}; font-size: 0.85rem; margin: 0 0 0.4rem 0; }}
  .fo-odds {{ display: flex; gap: 8px; flex-wrap: wrap; margin: 0.4rem 0 0.2rem; }}
  .fo-odd {{ flex: 1 1 90px; border: 1px solid {C_GRID}; border-radius: 12px; padding: 8px 10px; background: {C_SURFACE}; }}
  .fo-odd .l {{ color: {C_TEXT2}; font-size: 0.75rem; }}
  .fo-odd .v {{ font-size: 1.25rem; font-weight: 700; color: {C_TEXT}; }}
  .fo-odd .p {{ color: {C_MUTED}; font-size: 0.75rem; }}
  .fo-chip {{ display: inline-block; padding: 3px 10px; border-radius: 999px; font-size: 0.78rem; margin: 2px 6px 2px 0;
             background: #f0efec; color: {C_TEXT}; border: 1px solid {C_GRID}; }}
  .fo-chip.strong {{ background: #fde8df; border-color: #f4b8a0; }}
  .fo-chip.moderate {{ background: #fff3d6; border-color: #f2d48a; }}
  .fo-chip.low {{ background: #eeeeee; color: {C_TEXT2}; }}
  .fo-sentence {{ font-size: 0.95rem; color: {C_TEXT}; margin: 0.5rem 0 0.2rem; }}
  .fo-small {{ font-size: 0.8rem; color: {C_MUTED}; }}
  .fo-kpi {{ border: 1px solid {C_GRID}; border-radius: 12px; padding: 10px 12px; background: {C_SURFACE}; }}
  .fo-kpi .l {{ color: {C_TEXT2}; font-size: 0.78rem; }}
  .fo-kpi .v {{ font-size: 1.4rem; font-weight: 700; color: {C_TEXT}; }}
  div[data-testid="stMetricValue"] {{ font-size: 1.3rem; }}
</style>
""", unsafe_allow_html=True)

LEAGUE_TR = {
    "E0": "İngiltere · Premier Lig", "E1": "İngiltere · Championship", "SP1": "İspanya · La Liga", "SP2": "İspanya · Segunda",
    "I1": "İtalya · Serie A", "I2": "İtalya · Serie B", "D1": "Almanya · Bundesliga", "D2": "Almanya · 2. Bundesliga",
    "F1": "Fransa · Ligue 1", "F2": "Fransa · Ligue 2", "N1": "Hollanda · Eredivisie", "P1": "Portekiz · Primeira Liga",
    "B1": "Belçika · Pro League", "T1": "Türkiye · Süper Lig", "G1": "Yunanistan · Süper Lig", "SC0": "İskoçya · Premiership",
    "E2": "İngiltere · League One", "E3": "İngiltere · League Two", "EC": "İngiltere · National League",
    "SC1": "İskoçya · Championship", "SC2": "İskoçya · League One", "SC3": "İskoçya · League Two",
    "ARG": "Arjantin · Liga Profesional", "AUT": "Avusturya · Bundesliga", "BRA": "Brezilya · Série A", "CHN": "Çin · Süper Lig",
    "DNK": "Danimarka · Superliga", "FIN": "Finlandiya · Veikkausliiga", "IRL": "İrlanda · Premier Division", "JPN": "Japonya · J1 Ligi",
    "MEX": "Meksika · Liga MX", "NOR": "Norveç · Eliteserien", "POL": "Polonya · Ekstraklasa", "ROU": "Romanya · Superliga",
    "RUS": "Rusya · Premier Lig", "SWE": "İsveç · Allsvenskan", "SWZ": "İsviçre · Süper Lig",
    "USA": "ABD · MLS",
}
SIGNAL_TR = {
    "STRONG HISTORICAL DEVIATION": ("Belirgin sapma", "strong"),
    "MODERATE HISTORICAL DEVIATION": ("Orta düzey sapma", "moderate"),
    "NEUTRAL": ("Sapma yok", ""),
    "LOW SAMPLE": ("Yetersiz örnek", "low"),
}
CONF_TR = {"HIGH": "Yüksek", "MEDIUM": "Orta", "LOW": "Düşük", "VERY LOW": "Çok düşük"}
OUTCOME_TR = {"home": "ev sahibi kazanır", "draw": "beraberlik", "away": "deplasman kazanır"}
OUTCOME_SHORT = {"h": "Ev sahibi", "d": "Beraberlik", "a": "Deplasman"}


# --------------------------------------------------------------------------- data
@st.cache_data(show_spinner=False, ttl=120)
def list_prediction_dates() -> list[str]:
    return sorted({p.name[:10] for p in RESULTS.glob("*_predictions.csv")}, reverse=True)


@st.cache_data(show_spinner=False, ttl=300)
def load_day(stamp: str):
    table = pd.read_csv(RESULTS / f"{stamp}_predictions.csv")
    details_path = RESULTS / f"{stamp}_details.json"
    details = json.loads(details_path.read_text()) if details_path.exists() else {"matches": {}}
    an_path = RESULTS / "analogues" / f"{stamp}_analogues.parquet"
    analogues = pd.read_parquet(an_path) if an_path.exists() else pd.DataFrame()
    return table, details, analogues


@st.cache_data(show_spinner=False, ttl=600)
def load_backtest():
    p = RESULTS / "backtest" / "selected_params.json"
    return json.loads(p.read_text()) if p.exists() else {}


def to_excel(df: pd.DataFrame) -> bytes:
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as xw:
        df.to_excel(xw, index=False, sheet_name="tahminler")
    return buf.getvalue()


def fmt_date_tr(stamp: str) -> str:
    d = pd.Timestamp(stamp)
    months = ["Ocak", "Şubat", "Mart", "Nisan", "Mayıs", "Haziran", "Temmuz", "Ağustos", "Eylül", "Ekim", "Kasım", "Aralık"]
    days = ["Pazartesi", "Salı", "Çarşamba", "Perşembe", "Cuma", "Cumartesi", "Pazar"]
    return f"{d.day} {months[d.month - 1]} {d.year}, {days[d.weekday()]}"


def league_name(code: str) -> str:
    return LEAGUE_TR.get(code, code)


# --------------------------------------------------------------------------- charts
def compare_chart(row: pd.Series, height: int = 190) -> go.Figure:
    """Grouped horizontal bars: market vs adjusted historical probability, per outcome."""
    labels = ["Ev sahibi", "Beraberlik", "Deplasman"]
    market = [row["market_h"], row["market_d"], row["market_a"]]
    hist = [row["adj_h"], row["adj_d"], row["adj_a"]]
    fig = go.Figure()
    fig.add_bar(name="Piyasanın beklentisi", y=labels, x=market, orientation="h", marker_color=C_MARKET,
                text=[f"{v:.0f}%" for v in market], textposition="outside", textfont=dict(color=C_TEXT2, size=12),
                hovertemplate="Piyasa · %{y}: %{x:.1f}%<extra></extra>")
    fig.add_bar(name="Benzer maçlarda gerçekleşen", y=labels, x=hist, orientation="h", marker_color=C_HIST,
                text=[f"{v:.0f}%" for v in hist], textposition="outside", textfont=dict(color=C_TEXT2, size=12),
                hovertemplate="Geçmiş · %{y}: %{x:.1f}%<extra></extra>")
    fig.update_layout(barmode="group", bargap=0.35, bargroupgap=0.12, height=height, margin=dict(l=0, r=30, t=30, b=0),
                      paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                      legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0, font=dict(size=11, color=C_TEXT2)),
                      xaxis=dict(range=[0, max(max(market), max(hist)) * 1.25], showgrid=True, gridcolor=C_GRID, zeroline=False,
                                 ticksuffix="%", tickfont=dict(color=C_MUTED, size=10)),
                      yaxis=dict(autorange="reversed", tickfont=dict(color=C_TEXT, size=12)), font=dict(family="sans-serif"))
    return fig


def single_bar_chart(keys: list[str], values: list[float], title: str, height: int = 220) -> go.Figure:
    fig = go.Figure(go.Bar(x=keys, y=values, marker_color=C_MARKET, text=[f"{v:.0f}%" for v in values], textposition="outside",
                           textfont=dict(color=C_TEXT2, size=11), hovertemplate="%{x}: %{y:.1f}%<extra></extra>"))
    fig.update_layout(title=dict(text=title, font=dict(size=13, color=C_TEXT2), x=0), height=height,
                      margin=dict(l=0, r=0, t=36, b=0), paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                      yaxis=dict(showgrid=True, gridcolor=C_GRID, ticksuffix="%", tickfont=dict(color=C_MUTED, size=10), zeroline=False,
                                 range=[0, max(values) * 1.3 if values else 1]),
                      xaxis=dict(tickfont=dict(color=C_TEXT, size=11)), bargap=0.35)
    return fig


# --------------------------------------------------------------------------- text helpers
def significance_text(row: pd.Series, outcome: str) -> tuple[bool, str]:
    """Is the market probability outside the 95 % interval of the raw historical rate?"""
    k = {"home": "h", "draw": "d", "away": "a"}[outcome]
    lo, hi, market = row.get(f"ci_{k}_lo"), row.get(f"ci_{k}_hi"), row.get(f"market_{k}")
    if pd.isna(lo) or pd.isna(hi):
        return False, ""
    outside = market < lo or market > hi
    return bool(outside), f"%{lo:.0f}–%{hi:.0f}"


def plain_sentence(row: pd.Series) -> str:
    outcome = row.get("signal_outcome") if isinstance(row.get("signal_outcome"), str) else "home"
    k = {"home": "h", "draw": "d", "away": "a"}[outcome]
    market, hist, adj, edge = row[f"market_{k}"], row[f"hist_{k}"], row[f"adj_{k}"], row[f"edge_{k}"]
    n = int(row["n"])
    outside, ci = significance_text(row, outcome)
    name = OUTCOME_TR[outcome]
    s = (f"Piyasa <b>{name}</b> ihtimalini <b>%{market:.0f}</b> görüyor. Oran profili bu maça en çok benzeyen "
         f"<b>{n} geçmiş maçta</b> bu sonuç <b>%{hist:.0f}</b> oranında gerçekleşti; küçük örneklem etkisi düzeltildiğinde <b>%{adj:.0f}</b>. ")
    if abs(edge) < 2:
        s += "Fark 2 puandan küçük; geçmiş, piyasayla aynı şeyi söylüyor."
    else:
        yon = "daha sık" if edge > 0 else "daha seyrek"
        s += f"Yani bu sonuç geçmişte piyasanın beklediğinden <b>{abs(edge):.1f} puan {yon}</b> gerçekleşmiş"
        if outside:
            s += f" ve bu fark şansla açıklanamayacak kadar büyük (geçmiş oranın %95 güven aralığı {ci}, piyasa bunun dışında)."
        else:
            s += f"; ancak fark şans eseri de olabilir (geçmiş oranın %95 güven aralığı {ci}, piyasa bu aralığın içinde)."
    return s


def signal_chip(sig: str) -> str:
    label, cls = SIGNAL_TR.get(sig, (sig, ""))
    return f'<span class="fo-chip {cls}">Sinyal: {label}</span>'


def render_odds(row: pd.Series) -> str:
    cells = []
    for k, lab in OUTCOME_SHORT.items():
        cells.append(f'<div class="fo-odd"><div class="l">{lab}</div><div class="v">{row[f"odds_{k}"]:.2f}</div>'
                     f'<div class="p">piyasa %{row[f"market_{k}"]:.0f}</div></div>')
    return '<div class="fo-odds">' + "".join(cells) + "</div>"


# --------------------------------------------------------------------------- status panel
def render_status_panel() -> None:
    status = read_status(settings)
    running = is_running(settings) or status.get("state") == "running"
    state_tr = {"ok": "güncel", "error": "hata", "running": "güncelleniyor", "never": "henüz çalışmadı"}.get(status.get("state"), "bilinmiyor")
    icon = {"ok": "🟢", "error": "🔴", "running": "🟡"}.get(status.get("state"), "⚪")
    with st.expander(f"{icon} Veri durumu: {state_tr}", expanded=running or status.get("state") not in ("ok",)):
        st.write("Henüz hiç güncelleme yapılmadı." if status.get("state") == "never" else status.get("message", ""))
        if status.get("finished_at"):
            st.caption(f"Son güncelleme {status['finished_at'][:16].replace('T', ' ')} UTC · {status.get('duration_s', '?')} saniye sürdü. "
                       f"Her gün 06:30 UTC'de (Türkiye saatiyle 09:30) otomatik yenilenir.")
        if running:
            st.info("Güncelleme sürüyor (verileri indir → veritabanını kur → maçları analiz et, 1–3 dakika). Biraz sonra sayfayı yenile.")
        else:
            key_ok = True
            if ADMIN_KEY:
                key_ok = st.text_input("Yönetici anahtarı", type="password", key="admin_key") == ADMIN_KEY
            if st.button("Şimdi güncelle", disabled=not key_ok, help="Bu sezonun sonuçlarını indirir, veritabanını yeniler ve maçları yeniden analiz eder"):
                if start_background(settings, days=DAYS_AHEAD, full_download=not (settings.processed_dir / "matches.parquet").exists()):
                    st.cache_data.clear()
                    st.rerun()
                else:
                    st.warning("Zaten bir güncelleme sürüyor.")


# --------------------------------------------------------------------------- page
st.title("⚽ Maç oranları: piyasa ne bekliyor, geçmişte ne oldu?")
st.markdown('<p class="fo-lead">Bugünkü maçların bahis oranlarını 15 sezonluk bir havuzla karşılaştırır: oran profili en çok benzeyen '
            'geçmiş maçları bulur ve o maçlarda gerçekte ne olduğunu sayar. Bahis tavsiyesi vermez; piyasanın beklentisiyle '
            'geçmişin gerçekleşmesi arasındaki farkı, belirsizliğiyle birlikte gösterir.</p>', unsafe_allow_html=True)

with st.expander("Bu sayfayı nasıl okumalıyım? (ilk kez bakıyorsan aç)", expanded=False):
    st.markdown("""
- **Oran** bahis şirketinin fiyatıdır. 1.72 gibi bir oran, şirketin bu sonuca kabaca **%55** ihtimal verdiği anlamına gelir (marj temizlendikten sonra). Buna **piyasanın beklentisi** diyoruz.
- Sistem, bu üç ihtimale (ev sahibi / beraberlik / deplasman) en çok benzeyen **500 geçmiş maçı** bulur ve o maçlarda ev sahibinin kaç kez kazandığını, kaç gol atıldığını sayar. Buna **benzer maçlarda gerçekleşen** diyoruz.
- İkisi arasındaki farka **sapma** denir ve **puan** cinsinden yazılır: piyasa %55, geçmiş %58 ise sapma +3 puan.
- Sapma her zaman biraz vardır; önemli olan **şansla açıklanabilir mi** sorusudur. Bunun için her oranın yanında bir **güven aralığı** verilir. Piyasanın değeri bu aralığın içindeyse fark şans eseri olabilir.
- **En önemli uyarı:** Bu sistem 5 sezonluk körleme testte piyasadan **daha iyi tahmin edemedi**. Yani "sapma var" bilgisi ilginçtir ama "oyna" anlamına gelmez. Sayfanın altındaki sözlükte her terim açıklanmıştır.
""")

render_status_panel()

dates = list_prediction_dates()
if not dates:
    if is_running(settings) or read_status(settings).get("state") == "running":
        st.info("İlk veri yüklemesi sürüyor (Football-Data indirme → veritabanı → maç analizi). Birkaç dakika sonra sayfayı yenile.")
    else:
        st.warning("Henüz analiz dosyası yok. Yukarıdaki **Şimdi güncelle** düğmesini kullan.")
    st.stop()

stamp = st.selectbox("Tarih", dates, format_func=fmt_date_tr)
table, details, analogues = load_day(stamp)
bt = load_backtest()

# ---- headline tiles
n_dev = int(table["signal"].str.contains("DEVIATION").sum())
c1, c2, c3 = st.columns(3)
c1.markdown(f'<div class="fo-kpi"><div class="l">Analiz edilen maç</div><div class="v">{len(table)}</div></div>', unsafe_allow_html=True)
c2.markdown(f'<div class="fo-kpi"><div class="l">Sapma işaretlenen</div><div class="v">{n_dev}</div></div>', unsafe_allow_html=True)
c3.markdown(f'<div class="fo-kpi"><div class="l">Ortalama benzerlik</div><div class="v">%{table["avg_similarity"].mean():.1f}</div></div>', unsafe_allow_html=True)

if bt:
    verdict = ("**piyasadan daha iyi tahmin etti**" if bt.get("backtest_ok")
               else "**piyasadan daha iyi tahmin edemedi**; bu yüzden hiçbir maçta \"belirgin sapma\" sinyali verilmez")
    st.caption(f"Körleme test ({', '.join(bt.get('test_seasons', []))} sezonları, {bt.get('n_test_matches', '?')} maç): sistem {verdict}. "
               f"Kalibrasyon skoru (Brier, düşük iyi): piyasa {bt.get('brier_market', float('nan')):.4f}, sistem {bt.get('brier_adj', float('nan')):.4f}.")
if n_dev == 0:
    st.info("Bugün istatistiksel olarak anlamlı bir sapma yok. Bu normal bir sonuçtur.")

# ---- filters
with st.expander("Filtrele ve sırala", expanded=False):
    leagues = sorted(table["league"].unique(), key=league_name)
    sel_leagues = st.multiselect("Lig", leagues, default=leagues, format_func=league_name)
    order = st.radio("Sıralama", ["En büyük sapma önce", "Saate göre", "Lige göre"], horizontal=True)
    only_dev = st.checkbox("Sadece sapma işaretlenen maçlar", value=False)
    min_edge = st.slider("En az sapma (puan)", 0.0, 10.0, 0.0, 0.5, help="Piyasa ile geçmiş arasındaki fark en az bu kadar olan maçlar")
    min_sim = st.slider("En az benzerlik (%)", 90.0, 100.0, 90.0, 0.5, help="Bulunan geçmiş maçların ortalama benzerliği")

view = table[table["league"].isin(sel_leagues) & (table["avg_similarity"].fillna(0) >= min_sim)].copy()
view["_edge"] = view[["edge_h", "edge_d", "edge_a"]].abs().max(axis=1)
view = view[view["_edge"] >= min_edge]
if only_dev:
    view = view[view["signal"].str.contains("DEVIATION")]
if order == "En büyük sapma önce":
    view = view.sort_values("_edge", ascending=False)
elif order == "Saate göre":
    view = view.sort_values(["date", "time"])
else:
    view = view.sort_values(["league", "time"])

d1, d2 = st.columns(2)
d1.download_button("CSV indir", view.drop(columns=["_edge"]).to_csv(index=False).encode("utf-8"), f"{stamp}_tahminler.csv", "text/csv")
d2.download_button("Excel indir", to_excel(view.drop(columns=["_edge"])), f"{stamp}_tahminler.xlsx",
                   "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

st.markdown(f"## {fmt_date_tr(stamp)} · {len(view)} maç")
if view.empty:
    st.info("Filtrelere uyan maç yok.")
    st.stop()

# ---- match cards
for _, row in view.iterrows():
    with st.container(border=True):
        t = row["time"] if isinstance(row["time"], str) and row["time"] else ""
        st.markdown(f'<p class="fo-card-sub">{league_name(row["league"])}{" · " + t if t else ""}</p>'
                    f'<p class="fo-card-title">{row["home"]} – {row["away"]}</p>', unsafe_allow_html=True)
        st.markdown(render_odds(row), unsafe_allow_html=True)
        st.plotly_chart(compare_chart(row), width="stretch", config={"displayModeBar": False})
        st.markdown(f'<p class="fo-sentence">{plain_sentence(row)}</p>', unsafe_allow_html=True)
        chips = signal_chip(row["signal"])
        chips += f'<span class="fo-chip">Güven: {CONF_TR.get(row["confidence"], row["confidence"])} ({int(row["n"])} maç)</span>'
        chips += f'<span class="fo-chip">Benzerlik: %{row["avg_similarity"]:.1f}</span>'
        st.markdown(chips, unsafe_allow_html=True)
        st.markdown(f'<p class="fo-small">Benzer maçlarda gol: 2,5 üstü %{row["over25"]:.0f} · iki takım da gol attı %{row["btts"]:.0f} · '
                    f'ortalama {row["avg_goals"]:.2f} gol'
                    + (f' · piyasanın 2,5 üstü beklentisi %{row["market_over25"]:.0f}' if pd.notna(row.get("market_over25")) else "") + "</p>",
                    unsafe_allow_html=True)

        with st.expander("Ayrıntılar ve benzer geçmiş maçlar"):
            det = details.get("matches", {}).get(row["match_id"], {})
            st.markdown("**Üç ihtimal, üç bakış**")
            rows = []
            for k, lab in OUTCOME_SHORT.items():
                oc = {"h": "home", "d": "draw", "a": "away"}[k]
                outside, ci = significance_text(row, oc)
                rows.append({"Sonuç": lab, "Piyasa": f"%{row[f'market_{k}']:.1f}", "Geçmiş (ham)": f"%{row[f'hist_{k}']:.1f}",
                             "Geçmiş (düzeltilmiş)": f"%{row[f'adj_{k}']:.1f}", "Sapma": f"{row[f'edge_{k}']:+.1f} puan",
                             "%95 güven aralığı": ci, "Adil oran": f"{row[f'fair_{k}']:.2f}",
                             "Şansla açıklanır mı?": "Hayır, fark anlamlı" if outside else "Evet, olabilir"})
            st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
            st.caption("Adil oran = 1 / düzeltilmiş geçmiş ihtimal. Piyasa oranı bundan yüksekse piyasa bu sonucu geçmişe göre daha "
                       "az olası görüyor demektir; bu tek başına kârlı bahis anlamına gelmez (marj ve belirsizlik dahil değildir).")

            g1, g2 = st.columns(2)
            gd = det.get("goals_dist", {})
            if gd:
                g1.plotly_chart(single_bar_chart(list(gd.keys()), [100 * v for v in gd.values()], "Toplam gol dağılımı (benzer maçlar)"),
                                width="stretch", config={"displayModeBar": False})
            sl = det.get("scorelines", {})
            if sl:
                top = sorted(sl.items(), key=lambda kv: -kv[1])[:8]
                g2.plotly_chart(single_bar_chart([k for k, _ in top], [100 * v for _, v in top], "En sık skorlar (benzer maçlar)"),
                                width="stretch", config={"displayModeBar": False})

            scopes = det.get("scopes", {})
            if scopes:
                scope_tr = {"global": "Tüm ligler", "same_league": "Sadece aynı lig", "similar_leagues": "Benzer ligler"}
                srows = [{"Havuz": scope_tr.get(k, k), "Maç": v["n"],
                          "Ev / Berabere / Dep. (geçmiş)": " / ".join(f"%{100 * x:.0f}" for x in v["hist"]),
                          "Düzeltilmiş": " / ".join(f"%{100 * x:.0f}" for x in v["adj"]),
                          "Benzerlik": f"%{v['avg_similarity']:.1f}"} for k, v in scopes.items()]
                st.markdown("**Farklı havuzlarla aynı hesap**")
                st.dataframe(pd.DataFrame(srows), hide_index=True, width="stretch")

            tol = det.get("tolerance", {})
            if tol and tol.get("probs"):
                parts = [f"±{float(k) * 100:.0f} puan içinde {v} maç" for k, v in tol["probs"].items()]
                st.markdown("**Tolerans eşleşmesi** (üç ihtimalin hepsi bu kadar yakın olan geçmiş maç sayısı): " + " · ".join(parts))

            if not analogues.empty:
                an = analogues[analogues["fixture_id"] == row["match_id"]].sort_values("distance")
                top_k = st.radio("Kaç benzer maç gösterilsin?", [25, 50, 100, 250, 500], horizontal=True, index=0, key=f"k_{row['match_id']}")
                an = an.head(top_k).copy()
                res_tr = {"H": "Ev", "D": "Berabere", "A": "Dep."}
                show = pd.DataFrame({
                    "Tarih": pd.to_datetime(an["date"]).dt.strftime("%d.%m.%Y"),
                    "Lig": an["league"].map(league_name),
                    "Maç": an["home_team"] + " – " + an["away_team"],
                    "Oranlar 1/X/2": an["cons_h"].map("{:.2f}".format) + " / " + an["cons_d"].map("{:.2f}".format) + " / " + an["cons_a"].map("{:.2f}".format),
                    "Benzerlik": an["similarity"].map(lambda v: f"%{v:.1f}"),
                    "Sonuç": an["ftr"].map(res_tr) + " " + an["score"],
                    "2,5": an["ou25"].map({"Over": "Üst", "Under": "Alt"}),
                    "KG": an["btts"].map({"Yes": "Var", "No": "Yok"}),
                })
                st.dataframe(show, hide_index=True, width="stretch", height=min(520, 40 + 35 * len(show)))
                counts = an["ftr"].value_counts(normalize=True).reindex(["H", "D", "A"]).fillna(0) * 100
                st.caption(f"Gösterilen {len(an)} maçta: ev sahibi %{counts['H']:.0f} · beraberlik %{counts['D']:.0f} · deplasman %{counts['A']:.0f}")

# --------------------------------------------------------------------------- glossary
st.markdown("## Sözlük: sayılar ne anlama geliyor?")
glossary = [
    ("Oran (1 / X / 2)", "Bahis şirketinin fiyatı. 1 = ev sahibi kazanır, X = beraberlik, 2 = deplasman kazanır. Oran ne kadar düşükse şirket o sonucu o kadar olası görüyor."),
    ("Piyasanın beklentisi", "Oranlardan hesaplanan ihtimal. 1/oran alınır, şirketin kâr payı (marj) çıkarılır, üçü toplamı %100 yapılır. Piyasadaki birçok şirketin ortalaması kullanılır."),
    ("Benzer maçlar", "Geçmiş 15 sezondan (2011'den bugüne, 38 lig, 130 binden fazla maç) piyasa ihtimalleri bu maça en yakın 500 maç. Yalnızca analiz gününden önce oynanmış maçlar kullanılır."),
    ("Benzerlik %", "İki maçın ihtimal profilleri arasındaki fark. %98 benzerlik, ihtimallerin toplam 2 puan farklı olduğu anlamına gelir. %95'in altı zayıf benzerliktir."),
    ("Geçmiş (ham)", "Benzer maçlarda o sonucun gerçekleşme yüzdesi. Örnek: 500 maçın 290'ında ev sahibi kazandıysa %58."),
    ("Geçmiş (düzeltilmiş)", "Ham yüzde, az örneklemin abartmasını önlemek için piyasaya doğru biraz çekilir. Kararlarda bu değer kullanılır."),
    ("Sapma (puan)", "Düzeltilmiş geçmiş yüzdesi eksi piyasa yüzdesi. +3 puan: bu sonuç geçmişte piyasanın beklediğinden 3 puan daha sık gerçekleşmiş. Sapma, kârlı bahis demek değildir."),
    ("%95 güven aralığı", "Geçmiş yüzdesinin gerçek değerinin büyük ihtimalle içinde olduğu aralık. Piyasa bu aralığın içindeyse fark şans eseri olabilir; dışındaysa fark anlamlıdır."),
    ("Güven (örnek sayısı)", "Kaç benzer maç bulunduğuna göre: 250+ Yüksek, 100–249 Orta, 30–99 Düşük, 30 altı Çok düşük."),
    ("Sinyal", "Kural tabanlı özet. Belirgin sapma: fark ≥5 puan, anlamlı, benzerlik yüksek VE sistem körleme testte piyasayı yenmiş olmalı (şu an yenmediği için verilmez). Orta düzey: fark ≥3 puan ve anlamlı. Sapma yok: gerisi. Yetersiz örnek: 100'den az benzer maç."),
    ("Adil oran", "1 / düzeltilmiş geçmiş ihtimal. Geçmişe göre 'olması gereken' oran. Piyasa oranıyla karşılaştırmak için; marj ve belirsizlik dahil değildir."),
    ("2,5 üstü / altı", "Maçta toplam 3 ve daha fazla gol (üst) ya da 2 ve daha az gol (alt). Benzer maçlarda üst oranı gösterilir."),
    ("İki takım da gol attı (KG var)", "Benzer maçların yüzde kaçında her iki takım da en az bir gol attı."),
    ("Körleme test", "Sistem 2017–2021 sezonlarında ayarlandı, 2021–2026 sezonlarında hiç görmediği maçlarda denendi. Bir maçı analiz ederken yalnızca o maçtan önce oynanmış maçları görebilir. Sonuç: piyasadan daha iyi tahmin edemedi."),
    ("Brier skoru", "Tahmin kalitesi ölçüsü; düşük daha iyi. Piyasa 0.5899, sistem 0.5897: fark yok denecek kadar küçük ve istatistiksel olarak anlamsız."),
]
for term, desc in glossary:
    st.markdown(f"**{term}** — {desc}")

st.markdown('<p class="fo-small">Veri: Football-Data.co.uk (oranlar cuma/salı öğleden sonra toplanır, kapanış oranı değildir). '
            'Bu sayfa bir araştırma aracıdır; bahis tavsiyesi değildir.</p>', unsafe_allow_html=True)
