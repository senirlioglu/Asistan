/* Oran Karşılaştırma — frontend. Vanilla JS, talks to /api/*. */
(function () {
  "use strict";

  const $ = (sel, root = document) => root.querySelector(sel);
  const el = (tag, cls, html) => { const n = document.createElement(tag); if (cls) n.className = cls; if (html != null) n.innerHTML = html; return n; };
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const pct = (v, d = 0) => (v == null ? "–" : `%${Number(v).toFixed(d)}`);
  const num = (v, d = 2) => (v == null ? "–" : Number(v).toFixed(d));
  const pp = (v) => (v == null ? "–" : `${v > 0 ? "+" : ""}${Number(v).toFixed(1)} puan`);

  const MONTHS = ["Ocak", "Şubat", "Mart", "Nisan", "Mayıs", "Haziran", "Temmuz", "Ağustos", "Eylül", "Ekim", "Kasım", "Aralık"];
  const DAYS = ["Pazar", "Pazartesi", "Salı", "Çarşamba", "Perşembe", "Cuma", "Cumartesi"];
  const fmtDate = (s) => { const d = new Date(s + "T12:00:00"); return `${d.getDate()} ${MONTHS[d.getMonth()]} ${d.getFullYear()}, ${DAYS[d.getDay()]}`; };
  const fmtShort = (s) => { const d = new Date(s + "T12:00:00"); return `${d.getDate()}.${String(d.getMonth() + 1).padStart(2, "0")}.${d.getFullYear()}`; };

  const OUT = { h: "Ev sahibi", d: "Beraberlik", a: "Deplasman" };
  const OUT_SENT = { home: "ev sahibi kazanır", draw: "beraberlik", away: "deplasman kazanır" };
  const KEY = { home: "h", draw: "d", away: "a" };
  const SIGNAL = {
    "STRONG HISTORICAL DEVIATION": ["Belirgin sapma", "strong"],
    "MODERATE HISTORICAL DEVIATION": ["Orta düzey sapma", "moderate"],
    "NEUTRAL": ["Sapma yok", ""],
    "LOW SAMPLE": ["Yetersiz örnek", "low"],
  };
  const CONF = { HIGH: "Yüksek", MEDIUM: "Orta", LOW: "Düşük", "VERY LOW": "Çok düşük" };

  const state = { meta: null, date: null, day: null, leagues: new Set(), sort: "edge", onlyDev: false, view: "list", pollTimer: null };

  // ------------------------------------------------------------------ api
  async function api(path, opts) {
    const r = await fetch(path, opts);
    if (!r.ok) throw new Error(`${r.status} ${await r.text()}`);
    return r.json();
  }

  // ------------------------------------------------------------------ status
  function renderStatus(meta) {
    const st = meta.status || {};
    const dot = $("#status-dot"), txt = $("#status-text");
    dot.className = "status-dot " + (st.running ? "running" : st.state === "ok" ? "ok" : st.state === "error" ? "error" : "");
    txt.textContent = st.running ? "Güncelleniyor…" : st.state === "ok" ? "Veri güncel" : st.state === "error" ? "Güncelleme hatası" : "Veri yok";
  }

  async function refreshNow() {
    const headers = {};
    if (state.meta?.admin_required) {
      const key = window.prompt("Yönetici anahtarı");
      if (!key) return;
      headers["X-Admin-Key"] = key;
    }
    try {
      const r = await api("/api/refresh", { method: "POST", headers });
      toast(r.started ? "Güncelleme başladı (1–3 dakika)." : "Zaten bir güncelleme sürüyor.");
      startPolling();
    } catch (e) { toast("Başlatılamadı: " + e.message); }
  }

  function startPolling() {
    if (state.pollTimer) return;
    state.pollTimer = setInterval(async () => {
      try {
        const meta = await api("/api/meta");
        const wasRunning = state.meta?.status?.running;
        state.meta = meta; renderStatus(meta);
        if (!meta.status.running) {
          clearInterval(state.pollTimer); state.pollTimer = null;
          if (wasRunning) { toast("Veri güncellendi."); await loadDates(true); }
        }
      } catch (_) { /* keep polling */ }
    }, 15000);
  }

  function statusDetail() {
    const st = state.meta?.status || {};
    const when = st.finished_at ? `Son güncelleme ${st.finished_at.slice(0, 16).replace("T", " ")} UTC (${st.duration_s ?? "?"} sn).` : "Henüz güncelleme yapılmadı.";
    const daily = `Her gün ${state.meta?.daily_utc || "06:30"} UTC'de kendiliğinden yenilenir.`;
    if (window.confirm(`${when}\n${st.message || ""}\n${daily}\n\nŞimdi güncellensin mi?`)) refreshNow();
  }

  function toast(msg) {
    const t = $("#toast"); t.textContent = msg; t.hidden = false;
    clearTimeout(t._t); t._t = setTimeout(() => { t.hidden = true; }, 3500);
  }

  // ------------------------------------------------------------------ views
  function showView(name) {
    state.view = name;
    document.querySelectorAll(".tab").forEach((b) => b.classList.toggle("is-active", b.dataset.view === name));
    $("#view-list").hidden = name !== "list";
    $("#view-glossary").hidden = name !== "glossary";
    $("#view-empty").hidden = true;
  }

  // ------------------------------------------------------------------ list
  async function loadDates(keepDate) {
    const meta = state.meta;
    const sel = $("#date-select");
    sel.innerHTML = "";
    if (!meta.dates.length) {
      $("#view-list").hidden = true; $("#view-glossary").hidden = true; $("#view-empty").hidden = false;
      if (!meta.status.running) { $("#empty-title").textContent = "Henüz analiz yok"; $("#empty-text").textContent = "Sağ üstteki durum düğmesinden güncellemeyi başlatabilirsin."; }
      startPolling();
      return;
    }
    meta.dates.forEach((d) => { const o = el("option"); o.value = d; o.textContent = fmtDate(d); sel.appendChild(o); });
    const want = keepDate && state.date && meta.dates.includes(state.date) ? state.date : meta.dates[0];
    sel.value = want;
    await loadDay(want);
  }

  async function loadDay(stamp) {
    state.date = stamp;
    state.day = await api(`/api/day/${stamp}`);
    if (state.leagues.size === 0) state.day.matches.forEach((m) => state.leagues.add(m.league));
    renderSummary(); renderLeagueChips(); renderCards();
  }

  function renderSummary() {
    const ms = state.day.matches;
    const dev = ms.filter((m) => m.signal.includes("DEVIATION")).length;
    const sims = ms.map((m) => m.avg_sim).filter((v) => v != null);
    const avgSim = sims.length ? sims.reduce((a, b) => a + b, 0) / sims.length : null;
    $("#stats").innerHTML = [
      ["Maç", ms.length], ["Sapma işaretli", dev], ["Ort. benzerlik", pct(avgSim, 1)],
    ].map(([l, v]) => `<div class="stat"><span class="label">${l}</span><div class="v num">${v}</div></div>`).join("");
    const bt = state.meta.backtest || {};
    const v = $("#verdict");
    if (bt.brier_market != null) {
      const ok = bt.backtest_ok;
      v.innerHTML = `Körleme test (${(bt.test_seasons || []).length} sezon, ${bt.n_test_matches} maç): sistem ${ok ? "<b>piyasadan daha iyi tahmin etti</b>" : "<b>piyasadan daha iyi tahmin edemedi</b>; bu yüzden hiçbir maçta \"belirgin sapma\" verilmez"}. Kalibrasyon skoru (düşük iyi): piyasa ${num(bt.brier_market, 4)}, sistem ${num(bt.brier_adj, 4)}.`;
    } else { v.hidden = true; }
  }

  function renderLeagueChips() {
    const wrap = $("#league-chips"); wrap.innerHTML = "";
    const leagues = [...new Map(state.day.matches.map((m) => [m.league, m.league_name])).entries()].sort((a, b) => a[1].localeCompare(b[1], "tr"));
    const all = el("button", "chip" + (state.leagues.size === leagues.length ? " is-on" : ""), "Tümü"); all.type = "button";
    all.onclick = () => { state.leagues = new Set(leagues.map((l) => l[0])); renderLeagueChips(); renderCards(); };
    wrap.appendChild(all);
    leagues.forEach(([code, name]) => {
      const b = el("button", "chip" + (state.leagues.has(code) && state.leagues.size !== leagues.length ? " is-on" : ""), esc(name)); b.type = "button";
      b.onclick = () => { if (state.leagues.size === leagues.length) state.leagues = new Set([code]); else if (state.leagues.has(code)) { state.leagues.delete(code); if (!state.leagues.size) state.leagues = new Set(leagues.map((l) => l[0])); } else state.leagues.add(code); renderLeagueChips(); renderCards(); };
      wrap.appendChild(b);
    });
  }

  const maxEdge = (m) => Math.max(...["h", "d", "a"].map((k) => Math.abs(m.edge[k] ?? 0)));

  function outsideCI(m, oc) {
    const k = KEY[oc]; const [lo, hi] = m.ci[k] || []; const mk = m.market[k];
    if (lo == null || hi == null || mk == null) return [false, ""];
    return [mk < lo || mk > hi, `%${lo.toFixed(0)}–%${hi.toFixed(0)}`];
  }

  function sentence(m) {
    const oc = OUT_SENT[m.signal_outcome] ? m.signal_outcome : "home";
    const k = KEY[oc];
    const market = m.market[k], hist = m.hist[k], adj = m.adj[k], edge = m.edge[k];
    const [outside, ci] = outsideCI(m, oc);
    let s = `Piyasa <b>${OUT_SENT[oc]}</b> ihtimalini <b>${pct(market)}</b> görüyor. Bu maça en çok benzeyen <b>${m.n} geçmiş maçta</b> bu sonuç <b>${pct(hist)}</b> oranında gerçekleşti; küçük örneklem düzeltmesiyle <b>${pct(adj)}</b>. `;
    if (edge == null || Math.abs(edge) < 2) s += "Fark 2 puandan küçük: geçmiş, piyasayla aynı şeyi söylüyor.";
    else {
      s += `Yani bu sonuç geçmişte piyasanın beklediğinden <b>${Math.abs(edge).toFixed(1)} puan ${edge > 0 ? "daha sık" : "daha seyrek"}</b> gerçekleşmiş`;
      s += outside ? ` ve fark şansla açıklanamayacak kadar büyük (güven aralığı ${ci}, piyasa bunun dışında).` : `; ancak fark şans eseri olabilir (güven aralığı ${ci}, piyasa bu aralığın içinde).`;
    }
    return s;
  }

  function barRow(name, market, hist, scale) {
    const w = (v) => `${Math.max(1, ((v ?? 0) / scale) * 100)}%`;
    return `<div class="bar-row"><span class="name">${name}</span><div class="bar-pair">
      <div class="bar-line"><div class="bar" style="width:${w(market)}"></div><span class="bar-val">${pct(market)}</span></div>
      <div class="bar-line"><div class="bar hist" style="width:${w(hist)}"></div><span class="bar-val">${pct(hist)}</span></div></div></div>`;
  }

  function cardHTML(m) {
    const [sigLabel, sigCls] = SIGNAL[m.signal] || [m.signal, ""];
    const scale = Math.max(...["h", "d", "a"].flatMap((k) => [m.market[k] ?? 0, m.adj[k] ?? 0])) * 1.08;
    return `
      <div class="card-top"><span>${esc(m.league_name)}${m.time ? " · " + esc(m.time) : ""}</span><span class="num">Benzerlik ${pct(m.avg_sim, 1)}</span></div>
      <div class="teams"><span>${esc(m.home)}</span><span class="vs">–</span><span>${esc(m.away)}</span></div>
      <div class="odds">${["h", "d", "a"].map((k) => `<div class="odd"><span class="label">${OUT[k]}</span><div class="v num">${num(m.odds[k])}</div><div class="p num">piyasa ${pct(m.market[k])}</div></div>`).join("")}</div>
      <div class="legend"><span><i></i>Piyasanın beklentisi</span><span><i class="hist"></i>Benzer maçlarda gerçekleşen</span></div>
      <div class="bars">${barRow("Ev sahibi", m.market.h, m.adj.h, scale)}${barRow("Beraberlik", m.market.d, m.adj.d, scale)}${barRow("Deplasman", m.market.a, m.adj.a, scale)}</div>
      <p class="sentence">${sentence(m)}</p>
      <div class="tags"><span class="tag ${sigCls}">${sigLabel}</span><span class="tag">Güven: ${CONF[m.confidence] || m.confidence} · ${m.n} maç</span></div>
      <div class="goals">Benzer maçlarda gol: 2,5 üstü ${pct(m.over25)} · iki takım da gol attı ${pct(m.btts)} · ortalama ${num(m.avg_goals)} gol${m.market_over25 != null ? ` · piyasanın 2,5 üstü beklentisi ${pct(m.market_over25)}` : ""}</div>
      <span class="card-more">Ayrıntılar ve benzer maçlar →</span>`;
  }

  function renderCards() {
    const wrap = $("#cards"); wrap.innerHTML = "";
    let ms = state.day.matches.filter((m) => state.leagues.has(m.league));
    if (state.onlyDev) ms = ms.filter((m) => m.signal.includes("DEVIATION"));
    if (state.sort === "edge") ms.sort((a, b) => maxEdge(b) - maxEdge(a));
    else if (state.sort === "time") ms.sort((a, b) => (a.date + a.time).localeCompare(b.date + b.time));
    else ms.sort((a, b) => a.league_name.localeCompare(b.league_name, "tr") || a.time.localeCompare(b.time));
    $("#count").textContent = `${fmtDate(state.date)} · ${ms.length} maç`;
    if (!ms.length) { wrap.appendChild(el("p", "count", "Filtrelere uyan maç yok.")); return; }
    ms.forEach((m) => {
      const c = el("button", "card", cardHTML(m)); c.type = "button"; c.setAttribute("aria-label", `${m.home} – ${m.away} ayrıntıları`);
      c.onclick = () => openSheet(m);
      wrap.appendChild(c);
    });
  }

  // ------------------------------------------------------------------ detail sheet
  function vbars(obj, title, note) {
    const entries = Object.entries(obj); if (!entries.length) return "";
    const max = Math.max(...entries.map(([, v]) => v)) || 1;
    return `<section><h3>${title}</h3><div class="vbars">${entries.map(([k, v]) => `<div class="vbar"><span class="num">${(100 * v).toFixed(0)}%</span><i style="height:${Math.max(2, (v / max) * 80)}%"></i><small>${esc(k)}</small></div>`).join("")}</div>${note ? `<p class="note">${note}</p>` : ""}</section>`;
  }

  async function openSheet(m) {
    $("#sheet-sub").textContent = `${m.league_name}${m.time ? " · " + m.time : ""} · ${fmtDate(m.date)}`;
    $("#sheet-title").textContent = `${m.home} – ${m.away}`;
    const body = $("#sheet-body");
    const rows = ["home", "draw", "away"].map((oc) => {
      const k = KEY[oc]; const [outside, ci] = outsideCI(m, oc);
      return `<tr><td>${OUT[k]}</td><td class="num">${pct(m.market[k], 1)}</td><td class="num">${pct(m.hist[k], 1)}</td><td class="num">${pct(m.adj[k], 1)}</td><td class="num">${pp(m.edge[k])}</td><td class="num">${ci || "–"}</td><td class="num">${num(m.fair[k])}</td><td>${outside ? '<span class="yes">Hayır, anlamlı</span>' : '<span class="no">Evet, olabilir</span>'}</td></tr>`;
    }).join("");
    const scopeTr = { global: "Tüm ligler", same_league: "Sadece aynı lig", similar_leagues: "Benzer ligler" };
    const scopes = Object.entries(m.scopes || {}).map(([k, v]) => `<tr><td>${scopeTr[k] || k}</td><td class="num">${v.n}</td><td class="num">${v.hist.map((x) => `%${(100 * x).toFixed(0)}`).join(" / ")}</td><td class="num">${v.adj.map((x) => `%${(100 * x).toFixed(0)}`).join(" / ")}</td><td class="num">${pct(v.avg_similarity, 1)}</td></tr>`).join("");
    const tol = m.tolerance?.probs ? Object.entries(m.tolerance.probs).map(([k, v]) => `±${(100 * Number(k)).toFixed(0)} puan: ${v} maç`).join(" · ") : "";
    const top = Object.entries(m.scorelines || {}).filter(([k]) => k !== "other").sort((a, b) => b[1] - a[1]).slice(0, 8);
    body.innerHTML = `
      <section><h3>Üç ihtimal, üç bakış</h3><div class="table-wrap"><table>
        <thead><tr><th>Sonuç</th><th class="num">Piyasa</th><th class="num">Geçmiş (ham)</th><th class="num">Düzeltilmiş</th><th class="num">Sapma</th><th class="num">%95 aralık</th><th class="num">Adil oran</th><th>Şansla açıklanır mı?</th></tr></thead>
        <tbody>${rows}</tbody></table></div>
        <p class="note">Adil oran = 1 / düzeltilmiş geçmiş ihtimal. Piyasa oranı bundan yüksekse piyasa bu sonucu geçmişe göre daha az olası görüyor; bu tek başına kârlı bahis demek değildir.</p></section>
      ${vbars(m.goals_dist || {}, "Toplam gol dağılımı (benzer maçlar)")}
      ${vbars(Object.fromEntries(top), "En sık skorlar (benzer maçlar)")}
      ${scopes ? `<section><h3>Farklı havuzlarla aynı hesap</h3><div class="table-wrap"><table><thead><tr><th>Havuz</th><th class="num">Maç</th><th class="num">Ev / Ber. / Dep.</th><th class="num">Düzeltilmiş</th><th class="num">Benzerlik</th></tr></thead><tbody>${scopes}</tbody></table></div></section>` : ""}
      ${tol ? `<section><h3>Tolerans eşleşmesi</h3><p class="note">Üç ihtimalin hepsi bu kadar yakın olan geçmiş maç sayısı: ${tol}</p></section>` : ""}
      <section><h3>Aynı takımlar</h3><div id="teams">Yükleniyor…</div></section>
      <section><h3>En benzer geçmiş maçlar</h3><div class="kseg" id="kseg">${[25, 50, 100, 250, 500].map((k) => `<button type="button" data-k="${k}" class="${k === 25 ? "is-on" : ""}">${k}</button>`).join("")}</div><div id="analogues">Yükleniyor…</div></section>`;
    $("#sheet").hidden = false; $("#sheet-backdrop").hidden = false; document.body.style.overflow = "hidden";
    $("#sheet").scrollTop = 0;
    const load = (k) => loadAnalogues(m, k);
    body.querySelectorAll("#kseg button").forEach((b) => { b.onclick = () => { body.querySelectorAll("#kseg button").forEach((x) => x.classList.toggle("is-on", x === b)); load(Number(b.dataset.k)); }; });
    load(25);
    loadTeams(m);
  }

  const OUTCOME_BADGE = { G: ["G", "Galibiyet", "win"], B: ["B", "Beraberlik", "draw"], M: ["M", "Mağlubiyet", "loss"] };

  function teamRows(rows) {
    return `<div class="table-wrap"><table><thead><tr><th>Tarih</th><th>Maç</th><th class="num">1 / X / 2</th><th class="num">Takımın ihtimali</th><th>Sonuç</th></tr></thead><tbody>
      ${rows.map((r) => { const [l, t, c] = OUTCOME_BADGE[r.outcome] || ["?", "", ""]; return `<tr><td class="num">${fmtShort(r.date)}</td><td>${esc(r.home)} – ${esc(r.away)} <small class="muted">${r.venue === "ev" ? "(ev)" : "(dep.)"}</small></td><td class="num">${r.odds.map((o) => num(o)).join(" / ")}</td><td class="num">${pct(r.p_team)}</td><td><span class="badge ${c}" title="${t}">${l}</span> ${esc(r.score)}</td></tr>`; }).join("")}
      </tbody></table></div>`;
  }

  function teamBlock(t, side) {
    if (!t.n_total) return `<div class="teambox"><h4>${esc(t.team)}</h4><p class="note">Veritabanında bu takımın maçı yok (havuzdaki 16 lig dışında oynuyor olabilir).</p></div>`;
    if (!t.n_similar) return `<div class="teambox"><h4>${esc(t.team)}</h4><p class="note">Havuzda ${t.n_total} maçı var ama hiçbirinde bugünkü gibi (${side} olarak ~${pct(t.p_today)}) fiyatlanmamış.</p></div>`;
    const conf = t.n_similar < 30 ? "çok az örnek, sadece fikir verir" : t.n_similar < 100 ? "az örnek" : "yeterli örnek";
    return `<div class="teambox"><h4>${esc(t.team)}</h4>
      <p class="sentence">Bugün ${side} olarak kazanma ihtimali <b>${pct(t.p_today)}</b>. ${t.first_season.slice(0, 2)}/${t.first_season.slice(2)} sezonundan beri oynadığı ${t.n_total} maçın <b>${t.n_similar}</b>'inde benzer fiyatlanmış (±${t.tolerance_pp} puan). O maçlarda: <b>${pct(t.win_pct)} galibiyet</b>, ${pct(t.draw_pct)} beraberlik, ${pct(t.loss_pct)} mağlubiyet; ortalama ${num(t.avg_goals)} gol.
      <span class="muted">Galibiyet için %95 aralık ${pct(t.ci[0])}–${pct(t.ci[1])} — ${conf}.</span></p>
      ${teamRows(t.rows)}${t.n_similar > t.rows.length ? `<p class="note">Son ${t.rows.length} maç gösteriliyor.</p>` : ""}</div>`;
  }

  async function loadTeams(m) {
    const box = $("#teams");
    try {
      const d = await api(`/api/teams/${state.date}/${m.id}`);
      const h = d.h2h;
      const h2h = h.n
        ? `<div class="teambox"><h4>${esc(m.home)} – ${esc(m.away)} karşılaşmaları</h4>
           <p class="sentence">Havuzda <b>${h.n}</b> karşılaşma var${h.shown < h.n ? ` (son ${h.shown} tanesi listede)` : ""}: ${esc(m.home)} ${h.home_wins} galibiyet, ${h.draws} beraberlik, ${esc(m.away)} ${h.away_wins} galibiyet.</p>
           ${teamRows(h.rows)}</div>`
        : `<div class="teambox"><h4>${esc(m.home)} – ${esc(m.away)} karşılaşmaları</h4><p class="note">Havuzda (2011'den beri, 16 lig) bu iki takım birbiriyle oynamamış.</p></div>`;
      box.innerHTML = `<p class="note">Bu bölüm sadece bu iki takıma bakar; oran benzerliğiyle ilgisi yoktur. Az sayıda maça dayanır, o yüzden yüzdeler kaba fikir verir.</p>${h2h}${teamBlock(d.home, "ev sahibi")}${teamBlock(d.away, "deplasman")}`;
    } catch (e) { box.innerHTML = `<p class="note">Takım geçmişi yüklenemedi: ${esc(e.message)}</p>`; }
  }

  async function loadAnalogues(m, k) {
    const box = $("#analogues");
    try {
      const data = await api(`/api/analogues/${state.date}/${m.id}?k=${k}`);
      if (!data.rows.length) { box.textContent = "Benzer maç listesi bulunamadı."; return; }
      const RES = { H: "Ev", D: "Ber.", A: "Dep." };
      const same = data.same_team_count || 0;
      const sameNote = same
        ? `<p class="note">Bu listede ${m.home} veya ${m.away}'nın kendi maçlarından <b>${same} tane</b> var (işaretli satırlar). Benzerlik yalnızca oran profiline bakar; takım adı hesaba girmez, bu maçlar tesadüfen buradadır.</p>`
        : `<p class="note">Listede ${m.home} veya ${m.away}'nın kendi maçı yok. Benzerlik yalnızca oran profiline bakar; takım adı hesaba girmez.</p>`;
      box.innerHTML = `<p class="note">Gösterilen ${data.rows.length} maçta: ev sahibi %${data.share.h.toFixed(0)} · beraberlik %${data.share.d.toFixed(0)} · deplasman %${data.share.a.toFixed(0)}</p>${sameNote}
        <div class="table-wrap"><table><thead><tr><th>Tarih</th><th>Lig</th><th>Maç</th><th class="num">1 / X / 2</th><th class="num">Benzerlik</th><th>Sonuç</th><th>2,5</th><th>KG</th></tr></thead><tbody>
        ${data.rows.map((r) => `<tr class="${r.same_team ? "same-team" : ""}"><td class="num">${fmtShort(r.date)}</td><td>${esc(r.league_name)}</td><td>${r.same_team ? "★ " : ""}${esc(r.home)} – ${esc(r.away)}</td><td class="num">${r.odds.map((o) => num(o)).join(" / ")}</td><td class="num">${pct(r.sim, 1)}</td><td class="res-${r.result}">${RES[r.result] || r.result} ${esc(r.score)}</td><td>${r.over25 ? "Üst" : "Alt"}</td><td>${r.btts ? "Var" : "Yok"}</td></tr>`).join("")}
        </tbody></table></div>`;
    } catch (e) { box.textContent = "Liste yüklenemedi: " + e.message; }
  }

  function closeSheet() { $("#sheet").hidden = true; $("#sheet-backdrop").hidden = true; document.body.style.overflow = ""; }

  // ------------------------------------------------------------------ glossary
  const GLOSSARY = [
    ["Oran (1 / X / 2)", "Bahis şirketinin fiyatı. 1 = ev sahibi kazanır, X = beraberlik, 2 = deplasman kazanır. Oran ne kadar düşükse şirket o sonucu o kadar olası görüyor."],
    ["Piyasanın beklentisi", "Oranlardan hesaplanan ihtimal: 1/oran alınır, şirketin kâr payı (marj) çıkarılır, üçünün toplamı %100 yapılır. Birçok şirketin ortalaması kullanılır."],
    ["Benzer maçlar", "2011'den bugüne 16 ligden 84 bin maç arasında piyasa ihtimalleri bu maça en yakın 500 maç. Yalnızca analiz gününden önce oynanmış maçlar kullanılır."],
    ["Benzerlik %", "İki maçın ihtimal profilleri arasındaki yakınlık. %98 benzerlik, ihtimallerin toplam 2 puan farklı olduğu anlamına gelir. %95'in altı zayıf benzerliktir."],
    ["Geçmiş (ham)", "Benzer maçlarda o sonucun gerçekleşme yüzdesi. 500 maçın 290'ında ev sahibi kazandıysa %58."],
    ["Geçmiş (düzeltilmiş)", "Ham yüzde, az örneklemin abartmasını önlemek için piyasaya doğru biraz çekilir. Kartlarda ve sapmada bu değer kullanılır."],
    ["Sapma (puan)", "Düzeltilmiş geçmiş yüzdesi eksi piyasa yüzdesi. +3 puan: bu sonuç geçmişte piyasanın beklediğinden 3 puan daha sık gerçekleşmiş. Sapma, kârlı bahis demek değildir."],
    ["%95 güven aralığı", "Geçmiş yüzdesinin gerçek değerinin büyük ihtimalle içinde olduğu aralık. Piyasa bu aralığın içindeyse fark şans eseri olabilir; dışındaysa fark anlamlıdır."],
    ["Güven (örnek sayısı)", "Kaç benzer maç bulunduğuna göre: 250 ve üzeri Yüksek, 100–249 Orta, 30–99 Düşük, 30 altı Çok düşük."],
    ["Sinyal", "Kural tabanlı özet. Belirgin sapma: fark 5 puan ve üzeri, anlamlı, benzerlik yüksek ve sistem körleme testte piyasayı yenmiş olmalı (yenmediği için şu an verilmez). Orta düzey: fark 3 puan ve üzeri, anlamlı. Sapma yok: gerisi. Yetersiz örnek: 100'den az benzer maç."],
    ["Adil oran", "1 / düzeltilmiş geçmiş ihtimal; geçmişe göre 'olması gereken' oran. Marj ve belirsizlik dahil değildir."],
    ["2,5 üstü / altı", "Maçta toplam 3 ve daha fazla gol (üst) ya da 2 ve daha az gol (alt). Benzer maçlarda üst oranı gösterilir."],
    ["İki takım da gol attı (KG)", "Benzer maçların yüzde kaçında her iki takım da en az bir gol attı."],
    ["Aynı takımlar", "Detay panelindeki bu bölüm oran benzerliğinden bağımsızdır: iki takımın birbirine karşı geçmiş maçları ve her takımın bugünkü gibi fiyatlandığı (±5 puan) kendi maçlarında ne yaptığı. Az maça dayandığı için yüzdeler kaba fikir verir; güven aralığı yanında yazar."],
    ["Körleme test", "Sistem 2017–2021 sezonlarında ayarlandı, 2021–2026 sezonlarında hiç görmediği maçlarda denendi; bir maçı analiz ederken yalnızca ondan önce oynanmış maçları görebilir. Sonuç: piyasadan daha iyi tahmin edemedi."],
    ["Kalibrasyon skoru (Brier)", "Tahmin kalitesi ölçüsü; düşük daha iyi. Piyasa 0.5899, sistem 0.5897: fark yok denecek kadar küçük ve istatistiksel olarak anlamsız."],
  ];

  function renderGlossary() {
    $("#glossary").innerHTML = GLOSSARY.map(([t, d]) => `<div><dt>${t}</dt><dd>${d}</dd></div>`).join("");
  }

  // ------------------------------------------------------------------ boot
  async function boot() {
    renderGlossary();
    document.querySelectorAll(".tab").forEach((b) => (b.onclick = () => showView(b.dataset.view)));
    $("#status-btn").onclick = statusDetail;
    $("#sheet-close").onclick = closeSheet; $("#sheet-backdrop").onclick = closeSheet;
    document.addEventListener("keydown", (e) => { if (e.key === "Escape") closeSheet(); });
    $("#date-select").onchange = (e) => loadDay(e.target.value);
    $("#sort-select").onchange = (e) => { state.sort = e.target.value; renderCards(); };
    $("#only-dev").onchange = (e) => { state.onlyDev = e.target.checked; renderCards(); };
    try { if (!localStorage.getItem("fo.introClosed")) $("#intro").hidden = false; } catch (_) { $("#intro").hidden = false; }
    $("#intro-close").onclick = () => { $("#intro").hidden = true; try { localStorage.setItem("fo.introClosed", "1"); } catch (_) {} };
    try {
      state.meta = await api("/api/meta");
      renderStatus(state.meta);
      if (state.meta.status.running) startPolling();
      await loadDates(false);
    } catch (e) {
      $("#view-list").hidden = true; $("#view-empty").hidden = false;
      $("#empty-title").textContent = "Sunucuya ulaşılamadı"; $("#empty-text").textContent = e.message;
    }
  }
  boot();
})();
