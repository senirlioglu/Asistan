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

  const state = { meta: null, date: null, day: null, leagues: new Set(), status: new Set(["post", "in", "pre"]), sort: "time",
                onlyDev: false, view: "list", pollTimer: null };

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
    if (name === "lab") {                     // the Pattern Lab tab: the lab sits at the top of the research view
      showView("research");
      setTimeout(() => { const lab = $("#lab"); if (lab) lab.scrollIntoView({ behavior: "smooth", block: "start" }); }, 60);
      return;
    }
    state.view = name;
    document.querySelectorAll(".tab").forEach((b) => b.classList.toggle("is-active", b.dataset.view === name));
    $("#view-list").hidden = name !== "list";
    $("#view-glossary").hidden = name !== "glossary";
    $("#view-scorecard").hidden = name !== "scorecard";
    $("#view-paper").hidden = name !== "paper";
    $("#view-notes").hidden = name !== "notes";
    $("#view-research").hidden = name !== "research";
    $("#view-empty").hidden = true;
    if (name === "notes" && !state.nt.data) loadNotes();
    if (name === "research" && !state.rs) loadResearch();
    if (name === "scorecard" && !state.sc.data) loadScorecard();
    if (name === "paper") { if (!state.pp.data) loadPaper(); if (!state.cp.loaded) { initCouponBuilder(); loadCoupons(); } }
  }

  // ------------------------------------------------------------------ research (Araştırma)
  const pp1 = (v) => (v == null ? "–" : `${v > 0 ? "+" : ""}${Number(v).toFixed(1)}`);

  async function loadResearch() {
    const box = $("#rs-verdict");
    try {
      state.rs = await api("/api/research");
    } catch (e) { box.textContent = "Araştırma sonuçları yüklenemedi: " + e.message; return; }
    renderResearch();
  }


  // ---------------------------------------------------------------- taranan bütün desenler
  // The funnel says 658 -> 65 -> 4 -> 1 and hides the useful half: WHICH ideas died and where.
  // A reader who wants to try every pattern mostly wants this table, because their idea is
  // probably already in it with a cause of death attached.
  function acRender() {
    const all = (state.rs?.discovery?.claims) || [];
    const names = state.rs?.discovery?.stage_names || {};
    const out = $("#ac-out");
    if (!out) return;
    if (!all.length) { out.innerHTML = `<p class="note">Tarama sonucu henüz yok (<code>cli discover</code>).</p>`; return; }
    const fill = (id, vals, label) => {
      const sel = $(id);
      if (!sel || sel._filled) return;
      sel._filled = true;
      vals.forEach((v) => { const o = el("option", "", label(v)); o.value = v; sel.appendChild(o); });
      sel.onchange = acRender;
    };
    fill("#ac-stage", [...new Set(all.map((r) => r.stage))], (v) => names[v] || v);
    fill("#ac-outcome", [...new Set(all.map((r) => r.outcome))], (v) => EX_OUT[v] || v);
    const sortSel = $("#ac-sort"); if (sortSel && !sortSel._w) { sortSel._w = true; sortSel.onchange = acRender; }
    const sideSel = $("#ac-side"); if (sideSel && !sideSel._w) { sideSel._w = true; sideSel.onchange = acRender; }

    const st = $("#ac-stage")?.value, oc = $("#ac-outcome")?.value, sd = $("#ac-side")?.value;
    let rows = all.filter((r) => (!st || r.stage === st) && (!oc || r.outcome === oc) && (!sd || r.side === sd));
    const how = $("#ac-sort")?.value || "abs";
    rows.sort((a, b) => how === "n" ? b.n_train - a.n_train
      : how === "p" ? (a.p_train ?? 1) - (b.p_train ?? 1)
      : Math.abs(b.edge_train) - Math.abs(a.edge_train));
    const shown = rows.slice(0, 120);
    out.innerHTML = `<p class="note">${all.length} iddia ölçüldü · filtreye uyan ${rows.length}${rows.length > shown.length ? `, ilk ${shown.length} gösteriliyor` : ""}.</p>
      <div class="table-wrap"><table><thead><tr><th>Desen</th><th>Sonuç</th><th class="num hide-sm">N</th>
        <th class="num">Keşif</th><th class="num hide-sm">Doğrulama</th><th class="num hide-sm">Test</th>
        <th>Nerede elendi</th></tr></thead><tbody>
        ${shown.map((r) => `<tr class="${r.stage === "survived" ? "ac-alive" : ""}">
          <td class="wrap">${esc(r.side === "home" ? "ev · " : "dep · ")}${esc(r.label)}</td>
          <td>${EX_OUT[r.outcome] || r.outcome}</td>
          <td class="num hide-sm">${r.n_train}</td>
          <td class="num"><b>${pp1(r.edge_train)}</b></td>
          <td class="num hide-sm">${r.edge_val == null ? "–" : pp1(r.edge_val)}</td>
          <td class="num hide-sm">${r.edge_test == null ? "–" : pp1(r.edge_test)}${r.q_test != null ? `<br><small class="muted">q=${num(r.q_test, 3)}</small>` : ""}</td>
          <td class="wrap"><small>${esc(names[r.stage] || r.stage)}</small></td></tr>`).join("")}
      </tbody></table></div>
      <p class="note">Sütunlar üç pencerenin farkı (puan). Bir desenin keşif penceresinde büyük çıkıp
        doğrulamada küçülmesi ya da <b>işaret değiştirmesi</b> beklenen bir şeydir — tek pencerede ölçüp
        inanmanın neden yanlış olduğunu bu tablo gösterir.</p>`;
  }


  function renderResearch() {
    labInit();
    const d = state.rs || {};
    const sum = (d.models?.summary) || [];
    const market = sum.find((r) => r.model.startsWith("A"));
    const best = sum.filter((r) => r.brier_diff != null).sort((a, b) => a.brier_diff - b.brier_diff)[0];
    const st = d.state || {};
    $("#rs-verdict").innerHTML = `<span class="verdict-tag">HAVUZ GENELİ · seçtiğin maça özel değil</span>` + (market
      ? `Havuz: <b>${st.matches?.toLocaleString("tr")} maç</b> (${st.from} – ${st.to}). ${market.n.toLocaleString("tr")} maçlık
         ileriye dönük testte <b>hiçbir motor piyasayı geçemedi</b>; en iyisi ${esc(best?.model || "–")} ve o bile piyasadan
         ${pp1(1000 * (best?.brier_diff ?? 0))} binde Brier kadar geride. Bu sekmedeki her şey bu cümlenin altında okunmalı.`
      : `Havuz: <b>${st.matches?.toLocaleString("tr") || "?"} maç</b>. Model karşılaştırması henüz çalıştırılmadı.`);

    $("#rs-models").innerHTML = sum.length
      ? `<div class="table-wrap"><table><thead><tr><th>Model</th><th class="num">Brier</th><th class="num">Fark</th>
         <th class="num hide-sm">Kalibrasyon</th><th class="num">ROI</th><th class="num">CLV</th><th class="num hide-sm">İsabet</th>
         <th class="num hide-sm">Kazandığı sezon</th></tr></thead><tbody>
         ${sum.map((r) => `<tr><td class="wrap">${esc(r.model)}</td><td class="num">${num(r.brier, 5)}</td>
           <td class="num ${r.brier_diff > 0 ? "res-A" : ""}">${r.brier_diff == null ? "–" : pp1(1000 * r.brier_diff) + " ‰"}</td>
           <td class="num hide-sm">${num(r.calib_err, 4)}</td><td class="num">${pp1(r.roi)}%</td>
           <td class="num ${r.clv > 0 ? "yes" : ""}">${r.clv == null ? "–" : pp1(r.clv) + "%"}</td>
           <td class="num hide-sm">%${num(r.hit_rate, 1)}</td>
           <td class="num hide-sm">${r.seasons_better == null ? "–" : r.seasons_better + " / 5"}</td></tr>`).join("")}
         </tbody></table></div>
         <p class="note">A piyasa · B bugün sitede çalışan benzerlik · C form desenleri · D çok boyutlu ikiz · E hepsi birlikte.
         Fark binde Brier cinsinden; artı = piyasadan kötü. <b>CLV</b> = seçilen oranın kapanış oranına göre değeri
         (2019/20'den beri kapanış oranı olan maçlarda); artı CLV, bahsin girildiği anda piyasadan iyi fiyat alındığı anlamına gelir
         ve uzun vadede kârın tek güvenilir erken göstergesidir.</p>`
      : `<p class="note">Model karşılaştırması henüz çalıştırılmadı (<code>cli models</code>).</p>`;

    acRender();
    const fw = d.forward || {};
    const fwRows = fw.rows || [];
    $("#rs-forward").innerHTML = fw.n_frozen
      ? `<div class="rs-funnel">
           ${[["dondurulan karar", fw.n_frozen], ["sonucu gelen", fw.n_settled],
              ["gösterim eşiği", fw.floors?.display], ["araştırma eşiği", fw.floors?.research]]
             .map(([k, v]) => `<div class="rs-step"><span class="v num">${v == null ? "–" : v}</span><small>${k}</small></div>`).join("")}
         </div>
         <div class="table-wrap"><table><thead><tr><th>Hareket sınıfı</th><th class="num">Donduruldu</th>
           <th class="num">Sonuçlandı</th><th class="num">Gerçekleşen</th><th class="num">Piyasa</th></tr></thead><tbody>
           ${fwRows.map((r) => `<tr class="${r.enough ? "" : "thin"}"><td>${esc(r.type)}</td>
             <td class="num">${r.n_frozen}</td><td class="num">${r.n_settled}</td>
             <td class="num">${r.actual == null ? "—" : "%" + num(r.actual, 1)}</td>
             <td class="num">${r.market == null ? "—" : "%" + num(r.market, 1)}</td></tr>`).join("")}
         </tbody></table></div>
         <p class="note">${fw.since ? `İlk donmuş karar: ${ntAgo(fw.since)}. ` : ""}Örneklem
         ${fw.floors?.display} maçın altındayken oran <b>gösterilmiyor</b> — 14 maçta gelen %71, aynı yöne
         düşen 14 yazı turadır. Bu tablo dolmaya başladığında F (piyasa + hareket) ve G (hepsi birlikte)
         modelleri yukarıdaki karşılaştırmaya eklenecek; o zamana kadar eklenmeyecek.</p>`
      : `<p class="note">Henüz donmuş karar yok. Oran arşivi 15 Eylül 2026'da başladı ve ileri test,
         bir maç kick-off'tan ~25 dakika önce izlenirken kaydediliyor — yani tablo ancak bugünden sonra
         oynanan maçlarla dolar. <b>Geçmişe dönük üretilmeyecek:</b> maç başladıktan sonra hesaplanan bir
         sınıflandırma ileri test değildir.</p>`;

    const dc = d.discovery || {};
    const s2 = dc.stages || {};
    $("#rs-discovery").innerHTML = s2.candidates
      ? `<div class="rs-funnel">
           ${[["aday desen", s2.candidates], ["ölçülen iddia", s2.claims_scanned], ["keşfi geçen", s2.passed_train],
              ["doğrulamayı geçen", s2.passed_validation], ["testten sağ çıkan", s2.survived_test]]
             .map(([k, v]) => `<div class="rs-step"><span class="v num">${v}</span><small>${k}</small></div>`).join("")}
         </div>
         ${(dc.survivors || []).length
            ? `<div class="table-wrap"><table><thead><tr><th>Desen</th><th>Başlık</th><th class="num">N</th>
               <th class="num">Gerçekleşen</th><th class="num">Kıyas</th><th class="num">Fark</th><th class="num">q</th></tr></thead><tbody>
               ${dc.survivors.map((r) => `<tr><td class="wrap">${esc(r.side === "home" ? "ev · " : "dep · ")}${esc(r.label)}</td>
                 <td>${esc(r.outcome)}</td><td class="num">${r.n}</td><td class="num">%${num(r.actual, 1)}</td>
                 <td class="num">%${num(r.priced ? r.market : r.ref, 1)}</td>
                 <td class="num"><b>${pp1(r.edge)}</b> <small class="muted">[${pp1(r.lo)}, ${pp1(r.hi)}]</small></td>
                 <td class="num">${num(r.q, 3)}</td></tr>`).join("")}</tbody></table></div>
               <p class="note">Sağ kalan desen bile "oyna" demek değildir: aynı deseni bir modele çevirmek yukarıdaki
               tabloda piyasayı geçmiyor. Bu, "bu tarif edilen durumda fiyat biraz farklı davranmış" demek.</p>`
            : `<p class="note">Hiçbir desen üç pencereden de geçemedi.</p>`}`
      : `<p class="note">Tarama henüz çalıştırılmadı (<code>cli discover</code>).</p>`;

    const noteRank = (r) => {
      const alive = (r.claims || []).filter((c) => c.q != null && c.q <= 0.05);
      const priced = alive.filter((c) => c.edge != null && c.edge > 0);
      const bestQ = Math.min(1, ...(r.claims || []).map((c) => (c.q == null ? 1 : c.q)));
      return [priced.length ? 0 : alive.length ? 1 : 2, bestQ];
    };
    const notes = (d.notes || []).slice().sort((a, b) => { const x = noteRank(a), y = noteRank(b); return x[0] - y[0] || x[1] - y[1]; });
    $("#rs-notes").innerHTML = notes.length
      ? `<p class="note">Sıralama: önce düzeltmeden sonra ayakta kalan iddiası olan notlar (piyasadan iyi olanlar en başta), sonra gerisi. Sıra kanıt gücünü değil, yalnızca düzeltilmiş q değerini izler.</p>` + notes.map((r) => `<div class="rs-note"><h4>${r.no}. ${esc(r.title)} <small class="muted">· ${esc(r.side)} · N=${r.n}</small></h4>
          <p class="nt-note">“${esc(r.note)}”</p>
          <div class="table-wrap"><table><thead><tr><th>İddia</th><th class="num">N</th><th class="num">Gerçekleşen</th>
            <th class="num">Kıyas</th><th class="num">Fark</th><th>Sonuç</th></tr></thead><tbody>
            ${r.claims.map((c) => {
              const bench = c.market != null ? `piyasa %${num(c.market, 1)}` : c.ref != null ? `benzer fiyat %${num(c.ref, 1)}` : "–";
              const diff = c.edge != null ? c.edge : c.vs_ref;
              const ci = c.edge != null ? c.edge_ci : c.vs_ref_ci;
              const good = c.q != null && c.q <= 0.05;
              return `<tr><td class="wrap">${esc(c.text)}</td><td class="num">${c.n || "–"}</td>
                <td class="num">${c.actual == null ? "–" : "%" + num(c.actual, 1)}</td><td class="num">${bench}</td>
                <td class="num">${diff == null ? "–" : `<b>${pp1(diff)}</b> <small class="muted">[${pp1(ci?.[0])}, ${pp1(ci?.[1])}]</small>`}</td>
                <td class="wrap">${good ? `<span class="yes">${esc(rsVerdict(c))}</span>` : `<span class="no">fark yok</span>`}</td></tr>`;
            }).join("")}</tbody></table></div>
          <p class="note"><b>Nasıl ölçüldü:</b> ${esc(r.how)}</p></div>`).join("")
      : `<p class="note">Notlar henüz ölçülmedi (<code>cli notes</code>).</p>`;
  }

  function rsVerdict(c) {
    const d = c.edge != null ? c.edge : c.vs_ref;
    if (c.edge != null) return d > 0 ? "piyasadan iyi" : "piyasadan kötü";
    return d > 0 ? "benzer fiyatlılardan yüksek" : "benzer fiyatlılardan düşük";
  }

  // ------------------------------------------------------------------ notes over nesine odds (Notlar)
  state.nt = { data: null, date: null, rules: new Set(), leagues: new Set(), mode: "hits", q: "", sort: "time",
               market: "", min: null, max: null, loading: false };

  async function loadNotes(refresh, silent) {
    if (state.nt.loading) return;
    state.nt.loading = true;
    if (!silent) $("#nt-count").textContent = refresh ? "Oranlar yenileniyor…" : "Nesine bülteni okunuyor…";
    try {
      const q = new URLSearchParams();
      if (state.nt.date) q.set("date", state.nt.date);
      if (refresh) q.set("refresh", "true");
      state.nt.data = await api(`/api/notlar?${q}`);
      state.nt.date = state.nt.data.date;
      renderNotes();
    } catch (e) { if (!silent) $("#nt-count").textContent = "Notlar yüklenemedi: " + e.message; }
    state.nt.loading = false;
  }

  // Odds move as kick-off approaches and several notes depend on the exact price, so the page
  // re-reads the bulletin while the Nesine tab is open (and never while it is hidden).
  function ntAutoPoll() {
    setInterval(() => {
      if (state.view !== "notes" || document.hidden || !state.nt.data) return;
      loadNotes(false, true);
    }, 30000);
    document.addEventListener("visibilitychange", () => {
      if (!document.hidden && state.view === "notes" && state.nt.data) loadNotes(false, true);
    });
  }

  const fmtOdd = (v) => (typeof v === "number" ? v.toFixed(2) : esc(String(v)));

  function ntRuleList(d) {
    const h = d.history || {};
    return d.rules.map((r) => {
      const bt = h[r.id];
      const rows = bt && bt.rows ? `<div class="table-wrap"><table><thead><tr><th>Beklenti</th><th class="num">Not</th><th class="num">Kural sağlanınca</th><th class="num">Genel</th></tr></thead><tbody>${bt.rows.map((x) => `<tr><td class="wrap">${esc(x.what)}</td><td class="num">${esc(x.note)}</td><td class="num"><b>${x.rule.pct == null ? "–" : "%" + x.rule.pct.toFixed(0)}</b><small class="muted"> (${x.rule.n})</small></td><td class="num">${x.base.pct == null ? "–" : "%" + x.base.pct.toFixed(0)}</td></tr>`).join("")}</tbody></table></div>` : "";
      return `<div class="nt-rule${r.applied ? "" : " is-off"}"><h4>${r.no}. ${esc(r.title)}${r.applied ? "" : ' <span class="tag">uygulanmadı</span>'}</h4><p class="nt-note">“${esc(r.note)}”</p><p class="note"><b>Nasıl uygulandı:</b> ${esc(r.how)}</p>${rows}</div>`;
    }).join("") + (h.note ? `<p class="note">${esc(h.note)}${h.n_matches ? ` Veritabanı: ${h.n_matches} maç.` : ""}</p>` : "");
  }

  // value of an odds path like "o25.ust" on one match; "fav" = the lower of MS 1 / MS 2
  function ntValue(m, path) {
    if (path === "fav") {
      const v = ["1", "2"].map((k) => m.ms[k]).filter((x) => x != null);
      return v.length ? Math.min(...v) : null;
    }
    const i = path.indexOf(".");
    const group = m[path.slice(0, i)];
    const v = group ? group[path.slice(i + 1)] : null;
    return typeof v === "number" ? v : null;
  }

  function ntAgo(iso) {
    if (!iso) return "bilinmiyor";
    const s = (Date.now() - Date.parse(iso)) / 1000;
    if (!isFinite(s)) return "bilinmiyor";
    if (s < 90) return "az önce alındı";
    if (s < 5400) return `${Math.round(s / 60)} dk önce alındı`;
    return `${Math.round(s / 3600)} saat önce alındı`;
  }

  // how that price moved since the watcher first saw it: ▲/▼ plus the opening price on hover
  function ntArrow(m, path) {
    const mv = (m.moves || {})[path];
    if (!mv || !mv.dir) return "";
    const when = mv.changed_at ? ` · ${mv.changed_at.slice(11, 16)} UTC'de değişti` : "";
    const t = `açılış ${mv.open.toFixed(2)} → şimdi ${mv.now.toFixed(2)}${when}`;
    return `<i class="mv ${mv.dir > 0 ? "up" : "down"}" title="${esc(t)}">${mv.dir > 0 ? "▲" : "▼"}</i>`;
  }

  /** One note hit: its evidence with the movement arrows, what it expects, and a warning when its own price moved. */
  function ntHit(m, x) {
    const ev = Object.entries(x.evidence || {}).map(([k, v]) =>
      `<span class="nt-ev"><span>${esc(k)}</span><b class="num">${fmtOdd(v)}${ntArrow(m, (x.paths || {})[k])}</b></span>`).join("");
    // note 5 says it outright ("oran değişmişse oynama"): if the price the note read has moved since we
    // first saw it, the note was written about a price that is no longer on the board.
    const ch = Object.entries(x.paths || {}).map(([k, p]) => [k, (m.moves || {})[p]]).filter(([, mv]) => mv && mv.open !== mv.now);
    const drift = ch.length
      ? `<p class="nt-drift">Notun baktığı oran açılıştan beri değişti: ${ch.map(([k, mv]) => `${esc(k)} ${mv.open.toFixed(2)} → ${mv.now.toFixed(2)}`).join(" · ")}</p>`
      : "";
    return `<div class="nt-hit"><div class="nt-hit-head"><b>${x.no}. ${esc(x.title)}</b></div><div class="nt-evs">${ev}</div><p class="nt-expect">${esc(x.expect)}</p>${drift}</div>`;
  }

  const NT_GRID = [
    ["MS", ["ms.1", "ms.X", "ms.2"], ["1", "X", "2"]],
    ["İlk yarı", ["iy.1", "iy.X", "iy.2"], ["1", "X", "2"]],
    ["2,5 gol", ["o25.alt", "o25.ust"], ["Alt", "Üst"]],
    ["3,5 gol", ["o35.alt", "o35.ust"], ["Alt", "Üst"]],
    ["İY 0,5", ["iy05.alt", "iy05.ust"], ["Alt", "Üst"]],
    ["Karşılıklı gol", ["iy_kg.var", "y2_kg.var"], ["İY var", "2.Y var"]],
    ["İY/MS ters", ["iyms.1/2", "iyms.2/1"], ["1/2", "2/1"]],
    ["Skor diğer", ["iy_skor.diger", "skor.diger"], ["İY", "MS"]],
  ];

  function ntOddsGrid(m) {
    const cells = NT_GRID.map(([label, paths, names]) => {
      const vs = paths.map((p, i) => { const v = ntValue(m, p); return v == null ? "" : `<span class="nt-o"><small>${names[i]}</small><b class="num">${v.toFixed(2)}${ntArrow(m, p)}</b></span>`; }).join("");
      return vs ? `<div class="nt-grp"><span class="label">${label}</span><div class="nt-os">${vs}</div></div>` : "";
    }).join("");
    return cells ? `<div class="nt-grid">${cells}</div>` : "";
  }

  function renderNotes() {
    const d = state.nt.data, s = state.nt;
    $("#nt-rule-list").innerHTML = ntRuleList(d);
    const sel = $("#nt-date"); sel.innerHTML = "";
    d.dates.forEach((x) => { const o = el("option"); o.value = x; o.textContent = fmtDate(x); sel.appendChild(o); });
    sel.value = s.date;

    // the filters apply in order: mode -> league -> search -> odds -> note
    const byMode = d.matches.filter((m) => (s.mode === "all" ? true : s.mode === "ours" ? !!m.ours : m.hits.length));
    const q = s.q.trim().toLocaleLowerCase("tr");
    // Typing a team name is asking "where is THIS match", not "browse the current mode". The mode
    // defaults to "nota uyanlar", which hides two thirds of the bulletin — a match that fires no
    // note was unfindable by search, which reads as "the site does not have it".
    const base = q ? d.matches : byMode;
    const match = (m) => (!q || `${m.home} ${m.away} ${m.league}`.toLocaleLowerCase("tr").includes(q))
      && (!s.leagues.size || s.leagues.has(m.league))
      && (!s.market || (() => { const v = ntValue(m, s.market); return v != null && (s.min == null || v >= s.min - 1e-9) && (s.max == null || v <= s.max + 1e-9); })())
      && (!s.rules.size || m.hits.some((x) => s.rules.has(x.id)));

    const leagues = [...new Map(base.map((m) => [m.league, 0])).keys()].sort((a, b) => a.localeCompare(b, "tr"));
    const lwrap = $("#nt-leagues"); lwrap.innerHTML = "";
    const lall = el("button", "chip" + (s.leagues.size === 0 ? " is-on" : ""), `Tüm ligler <small>${leagues.length}</small>`); lall.type = "button";
    lall.onclick = () => { s.leagues = new Set(); renderNotes(); }; lwrap.appendChild(lall);
    leagues.forEach((lg) => {
      const n = base.filter((m) => m.league === lg).length;
      const b = el("button", "chip" + (s.leagues.has(lg) ? " is-on" : ""), `${esc(lg)} <small>${n}</small>`); b.type = "button";
      b.onclick = () => { if (s.leagues.has(lg)) s.leagues.delete(lg); else s.leagues.add(lg); renderNotes(); };
      lwrap.appendChild(b);
    });

    const chips = $("#nt-chips"); chips.innerHTML = "";
    const all = el("button", "chip" + (s.rules.size === 0 ? " is-on" : ""), "Tüm notlar"); all.type = "button";
    all.onclick = () => { s.rules = new Set(); renderNotes(); }; chips.appendChild(all);
    d.rules.filter((r) => r.applied).forEach((r) => {
      const n = base.filter((m) => m.hits.some((x) => x.id === r.id)).length;
      const b = el("button", "chip" + (s.rules.has(r.id) ? " is-on" : ""), `${r.no}. ${esc(r.title)} <small>${n}</small>`); b.type = "button";
      b.onclick = () => { if (s.rules.has(r.id)) s.rules.delete(r.id); else s.rules.add(r.id); renderNotes(); };
      chips.appendChild(b);
    });

    let ms = base.filter(match);
    const key = { ms1: (m) => m.ms["1"] ?? 99, ms2: (m) => m.ms["2"] ?? 99 }[s.sort];
    if (key) ms.sort((a, b) => key(a) - key(b));
    else if (s.sort === "hits") ms.sort((a, b) => b.hits.length - a.hits.length || (a.time || "").localeCompare(b.time || ""));
    else if (s.sort === "league") ms.sort((a, b) => a.league.localeCompare(b.league, "tr") || (a.time || "").localeCompare(b.time || ""));
    else ms.sort((a, b) => (a.time || "").localeCompare(b.time || ""));

    const meta = d.meta || {};
    const moved = ms.filter((m) => Object.keys(m.moves || {}).length).length;
    $("#nt-count").textContent = `${fmtDate(d.date)} · nesine'de ${d.matches.length} maç, ${d.n_hits} tanesi bir nota uyuyor · gösterilen ${ms.length}`
      + ` · oranlar ${ntAgo(meta.fetched_at)}${meta.error ? " · yenileme başarısız, eski oranlar" : ""}`
      + (meta.watch?.running ? (meta.watch.interval ? ` · her ${Math.round(meta.watch.interval / 60)} dk'da bir canlı yenileniyor` : " · canlı yenileme açık") : "")
      + (moved ? ` · ${moved} maçta oran oynadı` : "")
      + (q && s.mode !== "all" ? " · arama bültenin tamamında yapıldı" : "");

    const body = $("#nt-body");
    if (!ms.length) {
      const why = q ? `"${esc(s.q.trim())}" bugünün nesine bülteninde (${d.matches.length} maç) bulunamadı — maç başka bir güne ait olabilir, ya da takım adı nesine'de farklı yazılıyordur.`
        : `Bu filtrelere uyan maç yok. Üstteki seçimi "Tüm maçlar" yapmayı ya da oran filtresini temizlemeyi dene.`;
      body.innerHTML = `<div class="day-empty">${why}</div>`;
      return;
    }
    body.innerHTML = ms.slice(0, 250).map((m) => {
      const hits = m.hits.filter((x) => !s.rules.size || s.rules.has(x.id));
      const ours = m.ours ? `<p class="note nt-ours">Bizim analiz (${esc(m.ours.league_name)}): piyasa ${pct(m.ours.market.h)} / ${pct(m.ours.market.d)} / ${pct(m.ours.market.a)} · geçmiş ${pct(m.ours.adj.h)} / ${pct(m.ours.adj.d)} / ${pct(m.ours.adj.a)} · 2,5 üst ${pct(m.ours.over25)} · ${m.ours.n} benzer maç</p>` : "";
      const msLine = ["1", "X", "2"].map((k) => `${fmtOdd(m.ms[k] ?? "–")}${ntArrow(m, "ms." + k)}`).join(" / ");
      return `<div class="nt-card"><div class="card-top"><span>${esc(m.league)} · ${esc(m.time)}</span><span class="num">MS ${msLine}</span></div>
        <div class="teams"><span>${esc(m.home)}</span><span class="vs">–</span><span>${esc(m.away)}</span></div>
        ${hits.map((x) => ntHit(m, x)).join("")}
        ${s.mode === "hits" && hits.length ? "" : ntOddsGrid(m)}
        ${ours}
        <div class="nt-actions"><button type="button" class="btn ghost" data-analyse="${m.code}">Bu maçı analiz et</button></div></div>`;
    }).join("") + (ms.length > 250 ? `<p class="note">İlk 250 maç gösteriliyor; daraltmak için filtre kullan.</p>` : "");
    body.querySelectorAll("[data-analyse]").forEach((b) => (b.onclick = () => openNesineSheet(Number(b.dataset.analyse), b)));
  }

  async function openNesineSheet(code, btn) {
    const label = btn ? btn.textContent : "";
    if (btn) { btn.disabled = true; btn.textContent = "Analiz ediliyor…"; }
    try {
      const d = await api(`/api/nesine-analiz?code=${code}&k=25`);
      const m = d.match;
      m._analogues = d.analogues; m._analogueK = 25; m._teams = d.teams; m._nesine = d.nesine;
      openSheet(m);
    } catch (e) { toast("Analiz edilemedi: " + e.message); }
    if (btn) { btn.disabled = false; btn.textContent = label; }
  }

  // ------------------------------------------------------------------ coupons (Oyun)
  state.cp = { loaded: false, date: null, day: null, picks: new Map(), saving: false, info: null, matches: new Map() };
  const CP_MARKETS = [
    ["ms", "Maç sonucu", ["h", "d", "a"]], ["o25", "2,5 gol", ["over", "under"]], ["o15", "1,5 gol", ["over", "under"]],
    ["fh05", "İY 0,5", ["over", "under"]], ["fh15", "İY 1,5", ["over", "under"]], ["sh05", "2Y 0,5", ["over", "under"]], ["sh15", "2Y 1,5", ["over", "under"]],
  ];
  const CP_PICK = { h: "1", d: "X", a: "2", over: "Üst", under: "Alt" };

  function cpProbs(m, market) {
    // {pick: {hist: %, market: %}} for the builder; null where a side has no view
    const yn = (p) => (p == null ? null : { over: p, under: 100 - p });
    const gd = m.goals_dist || {};
    const o15 = gd["0"] != null && gd["1"] != null ? 100 * (1 - gd["0"] - gd["1"]) : null;
    const hv = m.halves || {};
    const f = (v) => (v == null ? null : 100 * v);
    switch (market) {
      case "ms": return { hist: m.adj, market: m.market };
      case "o25": return { hist: yn(m.over25), market: yn(m.market_over25) };
      case "o15": return { hist: yn(o15), market: null };
      case "fh05": return { hist: yn(f(hv.fh_over05)), market: null };
      case "fh15": return { hist: yn(f(hv.fh_over15)), market: null };
      case "sh05": return { hist: yn(f(hv.sh_over05)), market: null };
      case "sh15": return { hist: yn(f(hv.sh_over15)), market: null };
      default: return { hist: null, market: null };
    }
  }
  const cpArgmax = (o) => (o ? Object.keys(o).filter((k) => o[k] != null).sort((a, b) => o[b] - o[a])[0] || null : null);

  function initCouponBuilder() {
    const sel = $("#cp-date"); sel.innerHTML = "";
    const today = state.meta?.today || isoDay(new Date());
    const has = new Set(state.meta?.dates || []);
    for (let i = 0; i < 7; i++) {
      const d = new Date(today + "T12:00:00"); d.setDate(d.getDate() + i); const s = isoDay(d);
      const o = el("option"); o.value = s; o.textContent = fmtDate(s) + (i === 0 ? " · bugün" : "") + (has.has(s) ? "" : " · henüz maç yok"); sel.appendChild(o);
    }
    sel.value = state.date && state.date >= today ? state.date : today;
    sel.onchange = () => loadCouponDay(sel.value);
    $("#cp-save").onclick = saveCoupon;
    $("#cp-clear").onclick = () => { state.cp.picks.clear(); renderCouponDay(); };
    $("#cp-copy").onclick = () => {
      (state.cp.day?.matches || []).forEach((m) => CP_MARKETS.forEach(([mk]) => { const h = cpArgmax(cpProbs(m, mk).hist); if (h) state.cp.picks.set(`${m.id}|${mk}`, h); }));
      renderCouponDay();
    };
    state.cp.loaded = true;
    loadCouponDay(sel.value);
  }

  async function loadCouponDay(stamp) {
    state.cp.date = stamp; state.cp.picks.clear(); state.cp.info = null;   // the open panel belongs to the old day
    $("#cp-matches").innerHTML = `<p class="note">Yükleniyor…</p>`;
    try { state.cp.day = await api(`/api/day/${stamp}`); }
    catch (e) { state.cp.day = { matches: [] }; }
    renderCouponDay();
  }

  function cpRow(m) {
    const cells = CP_MARKETS.map(([mk, label, opts]) => {
      const pr = cpProbs(m, mk);
      const hPick = cpArgmax(pr.hist), mPick = cpArgmax(pr.market);
      if (!hPick && !mPick) return `<div class="cp-mk is-na"><span class="cp-mk-label">${label}</span><span class="note">veri yok</span></div>`;
      const btns = opts.map((o) => {
        const key = `${m.id}|${mk}`, on = state.cp.picks.get(key) === o;
        const marks = `${hPick === o ? '<i class="mk-h" title="geçmişin seçimi">G</i>' : ""}${mPick === o ? '<i class="mk-m" title="piyasanın seçimi">P</i>' : ""}`;
        const ph = pr.hist && pr.hist[o] != null ? pct(pr.hist[o]) : "–";
        return `<button type="button" class="cp-btn${on ? " is-on" : ""}" data-key="${key}" data-pick="${o}"><b>${CP_PICK[o]}</b><small>${ph}</small>${marks}</button>`;
      }).join("");
      return `<div class="cp-mk"><span class="cp-mk-label">${label}</span><div class="cp-btns">${btns}</div></div>`;
    }).join("");
    return `<div class="cp-row"><div class="cp-head"><div><b>${esc(m.home)} – ${esc(m.away)}</b><span class="muted">${esc(m.league_name)}${m.time ? " · " + esc(m.time) : ""} · oran ${num(m.odds.h)} / ${num(m.odds.d)} / ${num(m.odds.a)}</span></div>
      <button type="button" class="infobtn" data-info="${esc(m.id)}" title="Analiz, sapma, nesine oranları ve notlar" aria-label="${esc(m.home)} – ${esc(m.away)} bilgi">i</button></div><div class="cp-mks">${cells}</div></div>`;
  }

  function renderCouponDay() {
    const box = $("#cp-matches");
    const ms = (state.cp.day?.matches || []).slice().sort((a, b) => (a.time || "").localeCompare(b.time || "") || a.league_name.localeCompare(b.league_name, "tr"));
    if (!ms.length) { box.innerHTML = `<div class="day-empty">Bu gün için analiz edilmiş maç yok. Football-Data yeni haftanın maçlarını genellikle Salı–Çarşamba yükler.</div>`; }
    else box.innerHTML = ms.map(cpRow).join("");
    const byId = new Map(ms.map((m) => [m.id, m]));
    box.querySelectorAll("[data-info]").forEach((b) => (b.onclick = () => {
      state.cp.info = state.cp.info === b.dataset.info ? null : b.dataset.info;
      mountBuilderInfo(byId);
    }));
    mountBuilderInfo(byId);
    box.querySelectorAll(".cp-btn").forEach((b) => (b.onclick = () => {
      const key = b.dataset.key, pick = b.dataset.pick;
      if (state.cp.picks.get(key) === pick) state.cp.picks.delete(key); else state.cp.picks.set(key, pick);
      renderCouponDay();
    }));
    const n = state.cp.picks.size;
    $("#cp-summary").textContent = n ? `${n} seçim` : "Henüz seçim yok";
    $("#cp-save").disabled = n === 0 || state.cp.saving;
  }

  /** The open match panel of the coupon builder, re-mounted after every redraw of the list. */
  function mountBuilderInfo(byId) {
    const box = $("#cp-matches");
    box.querySelectorAll(".cp-detail").forEach((x) => x.remove());
    box.querySelectorAll("[data-info]").forEach((b) => b.classList.toggle("is-on", b.dataset.info === state.cp.info));
    const m = state.cp.info && byId.get(state.cp.info);
    if (!m) return;
    const row = box.querySelector(`[data-info="${CSS.escape(m.id)}"]`)?.closest(".cp-row");
    if (!row) return;
    const panel = detailPanel(m, () => { state.cp.info = null; mountBuilderInfo(byId); });
    row.insertAdjacentElement("afterend", panel);
  }

  /** An inline copy of the detail sheet: same body, its own header and a close button. */
  function detailPanel(m, onClose) {
    const panel = el("div", "cp-detail");
    panel.dataset.mid = m.id;
    const head = el("div", "cp-detail-head",
      `<div><b>${esc(m.home)} – ${esc(m.away)}</b><small class="muted">${esc(m.league_name || "")}${m.time ? " · " + esc(m.time) : ""} · ${fmtDate(m.date)}</small></div>`);
    const close = el("button", "btn ghost", "Bilgileri kapat"); close.type = "button";
    close.onclick = onClose;
    head.appendChild(close);
    const body = el("div", "sheet-body cp-detail-body");   // same styling as the full-screen sheet
    const foot = el("div", "cp-detail-foot");
    const close2 = el("button", "btn ghost", "Bilgileri kapat"); close2.type = "button";
    close2.onclick = onClose;                               // the panel is long: a way out at both ends
    foot.appendChild(close2);
    panel.append(head, body, foot);
    mountDetail(body, m);
    return panel;
  }

  async function saveCoupon() {
    if (!state.cp.picks.size) return;
    state.cp.saving = true; $("#cp-save").disabled = true;
    const picks = [...state.cp.picks.entries()].map(([key, pick]) => { const [match_id, market] = key.split("|"); return { match_id, market, pick }; });
    try {
      await api("/api/coupons", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ picks, label: $("#cp-label").value }) });
      toast("Kupon kaydedildi."); state.cp.picks.clear(); $("#cp-label").value = ""; renderCouponDay(); await loadCoupons();
    } catch (e) { toast("Kaydedilemedi: " + e.message); }
    state.cp.saving = false; renderCouponDay();
  }

  async function loadCoupons() {
    const box = $("#cp-list");
    try {
      const d = await api("/api/coupons");
      renderCoupons(d.coupons || []);
    } catch (e) { box.textContent = "Kuponlar yüklenemedi: " + e.message; }
  }

  const tallyTxt = (t) => `${t.ok} tuttu · ${t.wrong} tutmadı${t.pending ? ` · ${t.pending} bekliyor` : ""}${t.n_odds ? ` · kâr ${signed(t.pnl)} (${t.n_odds} oranlı seçim)` : ""}`;
  const statusTr = { pending: ["Bekliyor", ""], won: ["Hepsi tuttu", "won"], lost: ["Tutmadı", "lost"] };

  function renderCoupons(list) {
    const box = $("#cp-list");
    if (!list.length) { box.innerHTML = `<p class="note">Henüz kupon yok. Yukarıdan maç seçip kaydet.</p>`; return; }
    const agg = { user: { ok: 0, wrong: 0, pending: 0, pnl: 0, n_odds: 0 }, hist: { ok: 0, wrong: 0, pending: 0, pnl: 0, n_odds: 0 }, market: { ok: 0, wrong: 0, pending: 0, pnl: 0, n_odds: 0 } };
    list.forEach((c) => Object.keys(agg).forEach((s) => Object.keys(agg[s]).forEach((k) => (agg[s][k] += c.tally[s][k] || 0))));
    const settledAll = agg.user.ok + agg.user.wrong;
    const head = settledAll ? `<div class="cp-total"><span class="label">Tüm kuponlarda</span>
      <div class="cp-total-row"><b>Sen</b><span>${tallyTxt(agg.user)}</span></div>
      <div class="cp-total-row"><b class="c-hist">Geçmiş</b><span>${tallyTxt(agg.hist)}</span></div>
      <div class="cp-total-row"><b class="c-market">Piyasa</b><span>${tallyTxt(agg.market)}</span></div>
      <p class="note">Piyasa yalnızca maç sonucu ve 2,5 golde görüş bildirir; 1,5 gol ve yarı başlıklarında sadece sen ve geçmiş sayılır. Kâr: seçim başına 1 birim, o tarafın kendi seçiminin oranıyla.</p></div>` : "";
    box.innerHTML = head + list.map((c) => {
      const [st, cls] = statusTr[c.status] || [c.status, ""];
      const rows = c.picks.map((p) => `<tr><td class="wrap"><button type="button" class="infobtn" data-mid="${esc(p.match_id)}" title="Analiz, sapma, nesine oranları ve notlar" aria-label="${esc(p.home)} – ${esc(p.away)} bilgi">i</button> ${esc(p.home)} – ${esc(p.away)}<small class="muted"> · ${fmtShort(p.date)}${p.time ? " " + esc(p.time) : ""}${p.score ? ` · <b>${esc(p.score)}</b>${p.ht_score ? ` (${esc(p.ht_score)})` : ""}` : ""}</small></td><td class="wrap">${esc(p.market_label)}</td>
        <td class="num">${esc(p.pick_label)} ${okMark(p.user_ok)}${p.odds ? `<small class="muted"> @${num(p.odds)}</small>` : ""}</td>
        <td class="num">${p.hist_pick ? `${CP_PICK[p.hist_pick]} ${okMark(p.hist_ok)}` : "–"}</td>
        <td class="num hide-sm">${p.market_pick ? `${CP_PICK[p.market_pick]} ${okMark(p.market_ok)}` : "–"}</td>
        <td class="num hide-sm">${esc(p.score || "–")}${p.ht_score ? `<small class="muted"> (${esc(p.ht_score)})</small>` : ""}</td></tr>`).join("");
      return `<div class="cp-card"><div class="cp-card-head"><div><b>${esc(c.label || "Kupon")}</b> <span class="tag ${cls}">${st}</span><br><small class="muted">${c.n_picks} seçim · ${c.created_at.slice(0, 16).replace("T", " ")} UTC</small></div><button type="button" class="linkbtn" data-del="${c.id}">Sil</button></div>
        <div class="cp-tally"><span><b>Sen</b> ${tallyTxt(c.tally.user)}</span><span><b class="c-hist">Geçmiş</b> ${tallyTxt(c.tally.hist)}</span><span><b class="c-market">Piyasa</b> ${tallyTxt(c.tally.market)}</span></div>
        <div class="table-wrap"><table><thead><tr><th>Maç</th><th>Başlık</th><th class="num">Sen</th><th class="num">Geçmiş</th><th class="num hide-sm">Piyasa</th><th class="num hide-sm">Skor (İY)</th></tr></thead><tbody>${rows}</tbody></table></div></div>`;
    }).join("");
    box.querySelectorAll("[data-mid]").forEach((b) => (b.onclick = () => togglePickDetail(b)));
    box.querySelectorAll("[data-del]").forEach((b) => (b.onclick = async () => {
      if (!window.confirm("Bu kupon silinsin mi?")) return;
      try { await api(`/api/coupons/${b.dataset.del}`, { method: "DELETE" }); await loadCoupons(); } catch (e) { toast("Silinemedi: " + e.message); }
    }));
  }

  /** A coupon row knows only the match id: fetch the analysis (with its nesine side) and open it under
      the coupon, so the picks stay on screen next to what the numbers say about them. */
  async function togglePickDetail(btn) {
    const card = btn.closest(".cp-card"), id = btn.dataset.mid;
    const mark = () => {
      const open = card.querySelector(".cp-detail");
      card.querySelectorAll("[data-mid]").forEach((b) => b.classList.toggle("is-on", !!open && b.dataset.mid === open.dataset.mid));
    };
    const open = card.querySelector(".cp-detail");
    if (open) { const same = open.dataset.mid === id; open.remove(); mark(); if (same) return; }
    let box = el("div", "cp-detail", `<p class="note">Yükleniyor…</p>`);
    box.dataset.mid = id;
    card.appendChild(box); mark();
    try {
      let m = state.cp.matches.get(id);
      if (!m) {
        const d = await api(`/api/match/${encodeURIComponent(id)}`);
        m = d.match; m._nesine = d.nesine;
        state.cp.matches.set(id, m);
      }
      if (!card.contains(box)) return;            // closed again while the request was in flight
      const panel = detailPanel(m, () => { panel.remove(); mark(); });
      box.replaceWith(panel); box = panel; mark();
      panel.scrollIntoView({ behavior: "smooth", block: "nearest" });
    } catch (e) { box.innerHTML = `<p class="note">Maç açılamadı: ${esc(e.message)}</p>`; }
  }

  // ------------------------------------------------------------------ paper trading (Sanal oyun)
  state.pp = { from: null, to: null, leagues: new Set(), edge: 3, data: null, strategy: "deviation" };

  function setPRange(days) {
    const today = new Date((state.meta?.today || isoDay(new Date())) + "T12:00:00");
    const to = new Date(today); to.setDate(to.getDate() - 1);
    const from = new Date(to); from.setDate(from.getDate() - (days - 1));
    state.pp.from = isoDay(from); state.pp.to = isoDay(to);
    $("#pp-from").value = state.pp.from; $("#pp-to").value = state.pp.to;
    document.querySelectorAll("#view-paper [data-prange]").forEach((b) => b.classList.toggle("is-on", Number(b.dataset.prange) === days));
  }

  async function loadPaper() {
    if (!state.pp.from) setPRange(30);
    $("#pp-count").textContent = "Yükleniyor…";
    try {
      const q = new URLSearchParams({ from: state.pp.from, to: state.pp.to, edge: String(state.pp.edge) });
      if (state.pp.leagues.size) q.set("leagues", [...state.pp.leagues].join(","));
      state.pp.data = await api(`/api/paper?${q}`);
      renderPaper();
    } catch (e) { $("#pp-count").textContent = "Sanal oyun yüklenemedi: " + e.message; }
  }

  const signed = (v, d = 2) => (v == null ? "–" : `${v > 0 ? "+" : ""}${Number(v).toFixed(d)}`);
  const signedPct = (v) => (v == null ? "–" : `${v > 0 ? "+" : ""}%${Number(v).toFixed(1)}`);
  const pnlCls = (v) => (v == null ? "" : v > 0 ? "pos" : v < 0 ? "neg" : "");

  function sparkline(curve) {
    if (!curve || curve.length < 2) return "";
    const w = 160, h = 40, vals = curve.map((c) => c.pnl);
    const lo = Math.min(0, ...vals), hi = Math.max(0, ...vals), span = hi - lo || 1;
    const x = (i) => (i / (curve.length - 1)) * w, y = (v) => h - ((v - lo) / span) * h;
    const pts = vals.map((v, i) => `${x(i).toFixed(1)},${y(v).toFixed(1)}`).join(" ");
    const last = vals[vals.length - 1];
    return `<svg class="spark" viewBox="0 0 ${w} ${h}" width="${w}" height="${h}" aria-hidden="true"><line x1="0" x2="${w}" y1="${y(0).toFixed(1)}" y2="${y(0).toFixed(1)}" class="zero"/><polyline points="${pts}" class="${last >= 0 ? "pos" : "neg"}"/></svg>`;
  }

  function stratCard(s) {
    const on = s.key === state.pp.strategy;
    if (!s.n_bets) return `<button type="button" class="pp-card is-empty${on ? " is-on" : ""}" data-strategy="${s.key}"><h3>${s.label}</h3><p class="note">${s.desc}</p><p class="note">Bu aralıkta oynayacağı maç yok.</p></button>`;
    return `<button type="button" class="pp-card${on ? " is-on" : ""}" data-strategy="${s.key}"><h3>${s.label}</h3><p class="note">${s.desc}</p>
      <div class="pp-main"><div><div class="pp-big num ${pnlCls(s.profit)}">${signed(s.profit)}</div><div class="label">birim kâr/zarar</div></div>${sparkline(s.curve)}</div>
      <div class="pp-stats">
        <span><b class="num">${s.wins}/${s.n_settled}</b> tuttu${s.n_pending ? ` · ${s.n_pending} bekliyor` : ""}</span>
        <span>getiri <b class="num ${pnlCls(s.roi_pct)}">${signedPct(s.roi_pct)}</b></span>
        <span>ort. oran <b class="num">${num(s.avg_odds)}</b></span>
        <span>en yüksek oranla <b class="num ${pnlCls(s.profit_max)}">${s.n_max ? signed(s.profit_max) + " (" + signedPct(s.roi_max_pct) + ")" : "–"}</b></span>
        <span>maks. düşüş <b class="num">${num(s.max_drawdown)}</b></span>
      </div></button>`;
  }

  function renderPaper() {
    const d = state.pp.data;
    const wrap = $("#pp-leagues"); wrap.innerHTML = "";
    const all = el("button", "chip" + (state.pp.leagues.size === 0 ? " is-on" : ""), "Tümü"); all.type = "button";
    all.onclick = () => { state.pp.leagues = new Set(); loadPaper(); }; wrap.appendChild(all);
    d.leagues.forEach((l) => {
      const b = el("button", "chip" + (state.pp.leagues.has(l.code) ? " is-on" : ""), esc(l.name)); b.type = "button";
      b.onclick = () => { if (state.pp.leagues.has(l.code)) state.pp.leagues.delete(l.code); else state.pp.leagues.add(l.code); loadPaper(); };
      wrap.appendChild(b);
    });
    $("#pp-count").textContent = `${fmtShort(d.from)} – ${fmtShort(d.to)} · ${d.n_matches} maç, ${d.n_finished} sonuçlandı · sapma eşiği ${d.edge} puan`;
    const body = $("#pp-body");
    if (!d.n_matches) { body.innerHTML = `<div class="day-empty">Bu aralıkta analiz edilmiş maç yok.</div>`; return; }
    const s = d.strategies.find((x) => x.key === state.pp.strategy) || d.strategies[0];
    const settled = s.bets.filter((b) => b.settled), pending = s.bets.filter((b) => !b.settled);
    const rows = settled.map((b) => `<tr><td class="num hide-sm">${fmtShort(b.date)}</td><td class="wrap">${esc(b.home)} – ${esc(b.away)}<small class="muted"> · ${esc(b.league_name)}</small></td><td class="num">${esc(b.pick_label)}</td><td class="num">${num(b.odds)}<small class="muted hide-sm">${b.odds_max ? " / " + num(b.odds_max) : ""}</small></td><td class="num">${esc(b.score)}</td><td class="num ${b.won ? "ok" : "bad"}">${b.won ? "✓" : "✗"}</td><td class="num ${pnlCls(b.pnl)}">${signed(b.pnl)}</td></tr>`).join("");
    const league = s.by_league.length > 1 ? `<section><h3>Lige göre · ${s.label}</h3><div class="table-wrap"><table><thead><tr><th>Lig</th><th class="num">Bahis</th><th class="num">Tuttu</th><th class="num">Kâr/zarar</th></tr></thead><tbody>${s.by_league.map((l) => `<tr><td class="wrap">${esc(l.league_name)}</td><td class="num">${l.n}</td><td class="num">${l.wins}</td><td class="num ${pnlCls(l.pnl)}">${signed(l.pnl)}</td></tr>`).join("")}</tbody></table></div></section>` : "";
    body.innerHTML = `<div class="pp-grid">${d.strategies.map(stratCard).join("")}</div>
      <section><h3>Bahis bahis · ${s.label}</h3>
      ${settled.length ? `<div class="table-wrap"><table><thead><tr><th class="hide-sm">Tarih</th><th>Maç</th><th class="num">Seçim</th><th class="num">Oran</th><th class="num">Skor</th><th class="num"></th><th class="num">Kâr</th></tr></thead><tbody>${rows}</tbody></table></div>` : `<p class="note">Bu stratejinin sonuçlanmış bahsi yok.</p>`}
      ${pending.length ? `<p class="note">Sonucu bekleyen ${pending.length} bahis: ${pending.map((b) => `${esc(b.home)} – ${esc(b.away)} (${esc(b.pick_label)} @ ${num(b.odds)})`).join(", ")}.</p>` : ""}
      <p class="table-hint">Bir stratejinin kartına dokununca listesi ve lig tablosu gelir. Oran sütununda ortalama / en yüksek oran; kâr ortalama oranla hesaplanır.</p></section>${league}`;
    body.querySelectorAll("[data-strategy]").forEach((b) => (b.onclick = () => { state.pp.strategy = b.dataset.strategy; renderPaper(); }));
  }

  // ------------------------------------------------------------------ scorecard (Özet)
  state.sc = { from: null, to: null, leagues: new Set(), data: null, loading: false };
  const PICK = { h: "1", d: "X", a: "2", yes: "Üst", no: "Alt" };
  const isoDay = (d) => d.toISOString().slice(0, 10);

  function setRange(days) {
    const today = new Date((state.meta?.today || isoDay(new Date())) + "T12:00:00");
    const to = new Date(today); to.setDate(to.getDate() - 1);
    const from = new Date(to); from.setDate(from.getDate() - (days - 1));
    state.sc.from = isoDay(from); state.sc.to = isoDay(to);
    $("#sc-from").value = state.sc.from; $("#sc-to").value = state.sc.to;
    document.querySelectorAll("#view-scorecard [data-range]").forEach((b) => b.classList.toggle("is-on", Number(b.dataset.range) === days));
  }

  async function loadScorecard() {
    if (!state.sc.from) setRange(1);
    state.sc.loading = true;
    $("#sc-count").textContent = "Yükleniyor…";
    try {
      const q = new URLSearchParams({ from: state.sc.from, to: state.sc.to });
      if (state.sc.leagues.size) q.set("leagues", [...state.sc.leagues].join(","));
      state.sc.data = await api(`/api/scorecard?${q}`);
      renderScorecard();
    } catch (e) { $("#sc-count").textContent = "Özet yüklenemedi: " + e.message; }
    state.sc.loading = false;
  }

  function scLeagueChips(d) {
    const wrap = $("#sc-leagues"); wrap.innerHTML = "";
    const all = el("button", "chip" + (state.sc.leagues.size === 0 ? " is-on" : ""), "Tümü"); all.type = "button";
    all.onclick = () => { state.sc.leagues = new Set(); loadScorecard(); };
    wrap.appendChild(all);
    d.leagues.forEach((l) => {
      const b = el("button", "chip" + (state.sc.leagues.has(l.code) ? " is-on" : ""), esc(l.name)); b.type = "button";
      b.onclick = () => { if (state.sc.leagues.has(l.code)) state.sc.leagues.delete(l.code); else state.sc.leagues.add(l.code); loadScorecard(); };
      wrap.appendChild(b);
    });
  }

  const okMark = (ok) => (ok == null ? "–" : ok ? '<span class="ok">✓</span>' : '<span class="bad">✗</span>');
  const closerWord = { market: "piyasa", hist: "geçmiş", equal: "eşit" };

  function scSide(s, binary) {
    if (!s) return `<div class="sc-side"><span class="label">–</span><p class="note">Bu piyasa için veri yok.</p></div>`;
    let extra = binary
      ? `beklenen üst ${pct(s.expected_pct)}`
      : `kalibrasyon ${num(s.brier, 3)} · gerçekleşene verilen ihtimal ort. ${pct(s.p_realised_avg)}`;
    return `<div class="sc-side"><div class="sc-big num">${s.ok}<small>/${s.n}</small></div><div class="sc-pct num">${pct(s.ok_pct)} isabet</div><p class="note">${extra}</p></div>`;
  }

  function scCard(b) {
    const binary = b.key !== "ms";
    if (!b.n) return `<div class="sc-card is-empty"><h3>${b.label}</h3><p class="note">Bu aralıkta sayılabilecek maç yok.</p></div>`;
    const c = b.closer;
    const total = c ? c.market + c.hist + c.equal : 0;
    const bar = c && total ? `<div class="sc-split" aria-hidden="true"><i class="m" style="width:${(100 * c.market) / total}%"></i><i class="e" style="width:${(100 * c.equal) / total}%"></i><i class="h" style="width:${(100 * c.hist) / total}%"></i></div>
      <p class="note">Gerçeğe daha yakın: <b>piyasa ${c.market}</b> · eşit ${c.equal} · <b>geçmiş ${c.hist}</b></p>` : "";
    const actual = binary && b.actual_pct != null ? `<p class="note">Gerçekleşen üst oranı: <b>${pct(b.actual_pct)}</b> (${b.n} maç)</p>` : `<p class="note">${b.n} maç</p>`;
    return `<div class="sc-card"><h3>${b.label}</h3><p class="note">${b.desc}</p>
      <div class="sc-sides"><div><span class="label">Piyasa</span>${scSide(b.market, binary)}</div><div><span class="label hist">Geçmiş</span>${scSide(b.hist, binary)}</div></div>
      ${actual}${bar}</div>`;
  }

  function renderScorecard() {
    const d = state.sc.data;
    scLeagueChips(d);
    const same = d.from === d.to;
    $("#sc-count").textContent = `${same ? fmtDate(d.from) : fmtShort(d.from) + " – " + fmtShort(d.to)} · ${d.n_matches} maç, ${d.n_finished} sonuçlandı${d.n_pending ? `, ${d.n_pending} sonuç bekliyor` : ""}`;
    const body = $("#sc-body");
    if (!d.n_matches) { body.innerHTML = `<div class="day-empty">Bu aralıkta analiz edilmiş maç yok.</div>`; return; }
    if (!d.n_finished) { body.innerHTML = `<div class="day-empty">Sonuçlar henüz gelmedi. Skorlar maç bitince (canlı kaynak olan liglerde) ya da ertesi sabahki güncellemeyle gelir.</div>`; return; }
    const ms = d.markets.find((b) => b.key === "ms");
    const lead = ms && ms.closer ? (ms.closer.hist > ms.closer.market ? "geçmiş sayımları" : ms.closer.market > ms.closer.hist ? "piyasa" : "ikisi eşit") : null;
    const headline = lead ? `<p class="verdict">Maç sonucunda gerçeğe daha yakın olan: <b>${lead}</b> (piyasa ${ms.closer.market}, geçmiş ${ms.closer.hist}, eşit ${ms.closer.equal}). Piyasa favorisi ${ms.market.ok}/${ms.market.n}, geçmiş favorisi ${ms.hist.ok}/${ms.hist.n} tuttu. Küçük sayılar tesadüf olabilir; körleme testin sonucu (${d.n_finished} maçla değil, 38 bin maçla) değişmez.</p>` : "";
    const league = d.by_league.length > 1 ? `<section><h3>Lige göre maç sonucu</h3><div class="table-wrap"><table><thead><tr><th>Lig</th><th class="num">Maç</th><th class="num">Piyasa tuttu</th><th class="num">Geçmiş tuttu</th><th class="num hide-sm">Daha yakın (P / E / G)</th><th class="num hide-sm">2,5 geçmiş</th></tr></thead><tbody>
      ${d.by_league.map((l) => `<tr><td class="wrap">${esc(l.league_name)}</td><td class="num">${l.n}</td><td class="num">${l.market_ok}</td><td class="num">${l.hist_ok}</td><td class="num hide-sm">${l.closer.market} / ${l.closer.equal} / ${l.closer.hist}</td><td class="num hide-sm">${l.o25_n ? `${l.o25_hist_ok}/${l.o25_n}` : "–"}</td></tr>`).join("")}
      </tbody></table></div><p class="table-hint">P = piyasa, E = eşit, G = geçmiş. Telefonda son iki sütun gizli; ekranı döndürünce görünür.</p></section>` : "";
    const rows = d.matches.map((m) => `<tr><td class="num hide-sm">${fmtShort(m.date)}</td><td class="wrap">${esc(m.home)} – ${esc(m.away)}<small class="muted"> · ${esc((d.leagues.find((l) => l.code === m.league) || {}).name || m.league)}</small></td>
      <td class="num res-${m.result}">${esc(m.score)}${m.ht_score ? `<small> (${esc(m.ht_score)})</small>` : ""}</td>
      <td class="num">${PICK[m.ms.market.pick] || "–"} ${okMark(m.ms.market.ok)}</td><td class="num">${PICK[m.ms.hist.pick] || "–"} ${okMark(m.ms.hist.ok)}</td>
      <td class="hide-sm">${closerWord[m.ms.closer] || "–"}</td>
      <td class="num">${m.o25.hist ? `${PICK[m.o25.hist.pick]} ${okMark(m.o25.hist.ok)}` : "–"}${m.o25.market ? `<small class="muted"> · piyasa ${PICK[m.o25.market.pick]} ${okMark(m.o25.market.ok)}</small>` : ""}</td>
      <td class="num hide-sm">${m.o15.hist ? `${PICK[m.o15.hist.pick]} ${okMark(m.o15.hist.ok)}` : "–"}</td></tr>`).join("");
    const pending = d.pending.length ? `<p class="note">Sonucu bekleyen: ${d.pending.map((p) => `${esc(p.home)} – ${esc(p.away)}`).join(", ")}.</p>` : "";
    const filled = d.markets.filter((b) => b.n), empty = d.markets.filter((b) => !b.n);
    const emptyCard = empty.length ? `<div class="sc-card is-empty"><h3>Henüz sayılamayan piyasalar</h3><p class="note">${empty.map((b) => b.label).join(" · ")}. ${empty.some((b) => b.key.startsWith("fh") || b.key.startsWith("sh")) ? "Yarı ölçümleri ilk yarı skorunu ister; canlı kaynak bunu her zaman vermez, Football-Data verisi ertesi sabah gelince dolar." : ""}</p></div>` : "";
    body.innerHTML = `${headline}<div class="sc-grid">${filled.map(scCard).join("")}${emptyCard}</div>${league}
      <section><h3>Maç maç</h3><div class="table-wrap"><table><thead><tr><th class="hide-sm">Tarih</th><th>Maç</th><th class="num">Skor (İY)</th><th class="num">Piyasa MS</th><th class="num">Geçmiş MS</th><th class="hide-sm">Yakın</th><th class="num">2,5 geçmiş</th><th class="num hide-sm">1,5 geçmiş</th></tr></thead><tbody>${rows}</tbody></table></div>
      <p class="table-hint">MS sütunları: tarafın en yüksek ihtimal verdiği sonuç (1 = ev sahibi, X = beraberlik, 2 = deplasman) ve tuttu mu. 2,5 / 1,5: geçmişin üst/alt seçimi. Telefonda bazı sütunlar gizli.</p>${pending}</section>`;
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
    const today = meta.today || new Date().toISOString().slice(0, 10);
    // always offer the last 7 days (played: what the statistics said, what happened), today and the next 6 days,
    // plus any other day that has data
    const window = [];
    for (let i = -7; i < 7; i++) { const d = new Date(today + "T12:00:00"); d.setDate(d.getDate() + i); window.push(d.toISOString().slice(0, 10)); }
    const has = new Set(meta.dates);
    const all = [...new Set([...meta.dates.filter((d) => d < window[0]), ...window, ...meta.dates.filter((d) => d > window[window.length - 1])])].sort();
    all.forEach((d) => {
      const o = el("option"); o.value = d;
      const tag = d === today ? " · bugün" : d < today ? " · oynandı" : "";
      o.textContent = fmtDate(d) + tag + (has.has(d) ? "" : d < today ? " · analiz yok" : " · henüz maç yok");
      sel.appendChild(o);
    });
    const want = keepDate && state.date && all.includes(state.date) ? state.date : today;
    sel.value = want;
    await loadDay(want);
  }

  async function loadDay(stamp) {
    state.date = stamp;
    try {
      state.day = await api(`/api/day/${stamp}`);
    } catch (e) {
      if (!String(e.message).startsWith("404")) throw e;
      state.day = { date: stamp, matches: [] };
    }
    // the league filter is per day: every day starts with all of its leagues selected (a filter kept from
    // another day would hide everything when the leagues differ)
    state.leagues = new Set(state.day.matches.map((m) => m.league));
    state.live = {};
    state.status = new Set(STATUS.map((s) => s[0]));   // a status filter kept from another day would hide everything
    renderSummary(); renderFlagged(); renderLeagueChips(); renderStatusChips(); renderCards(); renderTally();
    loadLive();
  }

  // ------------------------------------------------------------------ live scores
  async function loadLive() {
    if (!state.day || !state.day.matches.length) return;
    const date = state.date;
    try {
      const d = await api(`/api/live/${date}`);
      if (state.date !== date) return;
      state.live = d.live || {};
      applyLive();
      clearTimeout(state.liveTimer);
      if (d.any_live) state.liveTimer = setTimeout(loadLive, 60000);
    } catch (_) { /* live is best effort */ }
  }

  function liveBadge(info, m) {
    if (!info) return m && m.live_available === false ? `<span class="live na" title="Bu lig için canlı skor kaynağı yok; sonuç ertesi sabah veriyle gelir">canlı skor yok</span>` : "";
    const score = `${info.home_score}-${info.away_score}`;
    const ht = info.ht_home != null ? ` <small>(İY ${info.ht_home}-${info.ht_away})</small>` : "";
    if (info.state === "in") return `<span class="live in"><i></i>${esc(info.label || "canlı")} · ${score}${ht}</span>`;
    if (info.state === "post") return `<span class="live post">MS ${score}${ht}</span>`;
    return "";
  }

  function applyLive() {
    const byId = new Map(state.day.matches.map((m) => [m.id, m]));
    document.querySelectorAll(".card[data-id]").forEach((c) => {
      const m = byId.get(c.dataset.id), info = state.live[c.dataset.id];
      const slot = c.querySelector(".live-slot");
      if (slot) slot.innerHTML = liveBadge(info, m);
      const com = c.querySelector("[data-comment]");
      if (com && m) com.innerHTML = `<b class="comment-label">Yorum</b> ${commentary(m, info).short}`;
    });
    const open = $("#sheet-live");
    if (open && open.dataset.id) open.innerHTML = liveBadge(state.live[open.dataset.id], byId.get(open.dataset.id));
    document.querySelectorAll("[data-mcomment]").forEach((p) => {
      const id = p.dataset.mcomment;
      if (byId.has(id)) p.innerHTML = commentary(byId.get(id), state.live[id]).full;
    });
    renderStatusChips();   // the live scores just told us which matches are over and which are running
    if (state.status.size !== STATUS.length) renderCards();   // ... which can move a match out of the current filter
    renderTally();
  }

  function renderTally() {
    // Over the day's finished matches: whose expectation (market or history) sat closer to what happened.
    const box = $("#tally");
    const done = state.day.matches.filter((m) => state.live?.[m.id]?.state === "post");
    if (!done.length) { box.hidden = true; return; }
    const t = { market: 0, hist: 0, live: 0 };
    done.forEach((m) => { const c = commentary(m, state.live[m.id]).closer || {}; t.market += c.market || 0; t.hist += c.hist || 0; });
    state.day.matches.forEach((m) => { if (state.live?.[m.id]?.state === "in") t.live++; });
    const lead = t.hist > t.market ? "geçmiş sayımları" : t.market > t.hist ? "piyasa" : "ikisi eşit";
    box.hidden = false;
    box.innerHTML = `Bugün biten <b>${done.length} maçta</b> gerçeğe daha yakın olan: <b>${lead}</b>. Piyasa ${t.market} başlıkta, geçmiş ${t.hist} başlıkta daha yakındı (maç sonucu ve 2,5 gol ayrı birer başlık)${t.live ? ` · ${t.live} maç sürüyor` : ""}. Küçük sayılar tesadüf olabilir; körleme testin sonucu değişmez.`;
  }

  function renderFlagged() {
    const box = $("#flagged"), list = $("#flag-list");
    const flagged = state.day.matches.filter((m) => m.signal.includes("DEVIATION")).sort((a, b) => maxEdge(b) - maxEdge(a));
    box.hidden = flagged.length === 0;
    list.innerHTML = "";
    flagged.forEach((m) => {
      const [label, cls] = SIGNAL[m.signal] || [m.signal, ""];
      const oc = KEY[m.signal_outcome] || "h";
      const edge = m.edge[oc];
      const b = el("button", "flag " + cls, `<b>${esc(m.home)} – ${esc(m.away)}</b><small>${label} · ${OUT[oc]} ${pp(edge)} · ${m.time || ""}</small>`);
      b.type = "button"; b.onclick = () => openSheet(m);
      list.appendChild(b);
    });
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
    const kEl = $("#intro-k"); if (kEl && bt.k) kEl.textContent = bt.k;
    if (bt.brier_market != null) {
      const ok = bt.backtest_ok;
      const worse = !ok && bt.brier_adj > bt.brier_market && bt.brier_adj_p_value != null && bt.brier_adj_p_value < 0.05;
      const verdict = ok ? "<b>piyasadan daha iyi tahmin etti</b>"
        : worse ? "<b>piyasadan biraz daha kötü tahmin etti</b> (fark küçük ama şansla açıklanmıyor); bu yüzden hiçbir maçta \"belirgin sapma\" verilmez"
        : "<b>piyasadan daha iyi tahmin edemedi</b>; bu yüzden hiçbir maçta \"belirgin sapma\" verilmez";
      v.innerHTML = `Körleme test (${(bt.test_seasons || []).length} sezon, ${bt.n_test_matches} maç): sistem ${verdict}. Kalibrasyon skoru (düşük iyi): piyasa ${num(bt.brier_market, 4)}, sistem ${num(bt.brier_adj, 4)}.`;
    } else { v.hidden = true; }
  }

  // ------------------------------------------------------------------ played / in play / to come
  const STATUS = [["post", "Oynanmış"], ["in", "Devam eden"], ["pre", "Oynanacak"]];
  const IN_PLAY_MIN = 130;   // 90 + half time + stoppage: after this a match without a live source is over

  /** "now" as {date, minutes} in Turkey, the frame the page shows every kick-off in. */
  function nowTR() {
    const p = new Intl.DateTimeFormat("en-CA", { timeZone: "Europe/Istanbul", year: "numeric", month: "2-digit",
      day: "2-digit", hour: "2-digit", minute: "2-digit", hour12: false }).formatToParts(new Date());
    const g = (t) => p.find((x) => x.type === t).value;
    return { date: `${g("year")}-${g("month")}-${g("day")}`, min: Number(g("hour")) * 60 + Number(g("minute")) };
  }

  /** "post" | "in" | "pre" — the live score when we have one, otherwise the clock. */
  function matchStatus(m) {
    const live = state.live?.[m.id];
    if (live && live.state) return live.state;
    const now = nowTR();
    if (!m.date) return "pre";
    if (m.date !== now.date) return m.date < now.date ? "post" : "pre";
    const [h, mi] = String(m.time || "00:00").split(":").map(Number);
    const diff = now.min - (h * 60 + (mi || 0));
    return diff < 0 ? "pre" : diff < IN_PLAY_MIN ? "in" : "post";
  }

  function renderStatusChips() {
    const wrap = $("#status-chips"); if (!wrap) return;
    wrap.innerHTML = "";
    const counts = {};
    state.day.matches.forEach((m) => { const s = matchStatus(m); counts[s] = (counts[s] || 0) + 1; });
    const all = el("button", "chip" + (state.status.size === STATUS.length ? " is-on" : ""), "Tüm durumlar"); all.type = "button";
    all.onclick = () => { state.status = new Set(STATUS.map((s) => s[0])); renderStatusChips(); renderCards(); };
    wrap.appendChild(all);
    STATUS.forEach(([key, label]) => {
      const on = state.status.has(key) && state.status.size !== STATUS.length;
      const b = el("button", "chip" + (on ? " is-on" : ""), `${label} <small>${counts[key] || 0}</small>`); b.type = "button";
      b.onclick = () => {
        if (state.status.size === STATUS.length) state.status = new Set([key]);           // first click: only this one
        else if (state.status.has(key)) { state.status.delete(key); if (!state.status.size) state.status = new Set(STATUS.map((s) => s[0])); }
        else state.status.add(key);                                                        // several can stay on at once
        renderStatusChips(); renderCards();
      };
      wrap.appendChild(b);
    });
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

  // ------------------------------------------------------------------ commentary
  const SIDE = { h: "ev sahibi", d: "beraberlik", a: "deplasman" };
  const fav = (o) => ["h", "d", "a"].reduce((b, k) => ((o[k] ?? -1) > (o[b] ?? -1) ? k : b), "h");
  const resultKey = (hs, as) => (hs > as ? "h" : hs < as ? "a" : "d");
  const tone = (diff) => (Math.abs(diff) < 2 ? "aynı görüşte" : diff > 0 ? "geçmiş biraz daha iyimser" : "geçmiş biraz daha temkinli");

  function htConditional(htft, s) {
    // P(FT outcome | HT state s) from the 9-way HT/FT distribution
    const sym = { h: "1", d: "X", a: "2" }[s];
    const p = { h: htft[`${sym}/1`] || 0, d: htft[`${sym}/X`] || 0, a: htft[`${sym}/2`] || 0 };
    const t = p.h + p.d + p.a;
    return t > 0 ? { h: p.h / t, d: p.d / t, a: p.a / t, n: t } : null;
  }

  function commentary(m, live) {
    const f = fav(m.market), name = SIDE[f];
    const mk = m.market[f], hs = m.adj[f], diff = (hs ?? 0) - (mk ?? 0);
    const mo = m.market_over25, ho = m.over25;
    const parts = [], short = [];
    const state = live?.state;

    if (state === "post") {
      const r = resultKey(live.home_score, live.away_score), total = live.home_score + live.away_score;
      const won = r === f;
      const mkR = m.market[r], hsR = m.adj[r];
      let s1 = `<b>Sonuç ${live.home_score}-${live.away_score}, ${SIDE[r]}.</b> `;
      if (won) s1 += `Piyasa ${pct(mk)}, benzer maçlar ${pct(hs)} ile ${name} bekliyordu; ikisi de doğru yönü gösterdi${Math.abs(diff) >= 2 ? ` (${diff > 0 ? "geçmiş" : "piyasa"} daha kararlıydı)` : ""}.`;
      else s1 += `Piyasa ${pct(mk)}, benzer maçlar ${pct(hs)} ile ${name} bekliyordu; sonuç ters geldi. Bu profildeki maçların yaklaşık ${pct(hsR)}'i böyle bitiyor; tek maç bir olasılığı yanlışlamaz.`;
      parts.push(s1); short.push(s1);
      let closerCount = { market: 0, hist: 0 };
      if (mkR != null && hsR != null && Math.abs(mkR - hsR) >= 1) (hsR > mkR ? closerCount.hist++ : closerCount.market++);
      if (mo != null && ho != null) {
        const over = total > 2.5;
        const pm = over ? mo : 100 - mo, ph = over ? ho : 100 - ho;
        let s2 = `Gol: toplam ${total}, 2,5 <b>${over ? "üstü" : "altı"}</b>. Piyasa üst ${pct(mo)}, benzer maçlar ${pct(ho)} demişti → `;
        s2 += (over ? mo >= 50 : mo < 50) ? "piyasanın beklentisi tuttu" : "piyasanın beklentisi tutmadı";
        s2 += Math.abs(pm - ph) >= 1 ? ` (${ph > pm ? "geçmiş" : "piyasa"} gerçeğe biraz daha yakındı).` : ".";
        parts.push(s2);
        if (Math.abs(pm - ph) >= 1) (ph > pm ? closerCount.hist++ : closerCount.market++);
      }
      if (live.ht_home != null && m.htft && Object.keys(m.htft).length) {
        const htKey = resultKey(live.ht_home, live.ht_away);
        const sym = { h: "1", d: "X", a: "2" };
        const combo = `${sym[htKey]}/${sym[r]}`, share = m.htft[combo] || 0;
        const rank = HTFT_ORDER.map((k) => m.htft[k] || 0).sort((a, b) => b - a).indexOf(share) + 1;
        parts.push(`İY/MS <b>${combo}</b>: benzer maçlarda ${pct(100 * share)} görülen, ${rank <= 2 ? "en sık" : rank <= 4 ? "orta sıklıkta" : "nadir"} bir kombinasyon.`);
      }
      const tally = closerCount.hist > closerCount.market ? "geçmiş" : closerCount.market > closerCount.hist ? "piyasa" : "ikisi eşit";
      parts.push(`<span class="muted">Bu maçta gerçeğe daha yakın olan: <b>${tally}</b> (${closerCount.market} başlıkta piyasa, ${closerCount.hist} başlıkta geçmiş). Tek maçtan genelleme yapılmaz; gün özetindeki sayaca bak.</span>`);
      return { short: short.join(" "), full: parts.join(" "), closer: closerCount };
    }

    if (state === "in") {
      const lead = resultKey(live.home_score, live.away_score), total = live.home_score + live.away_score;
      const minute = parseInt(String(live.clock || "").replace(/\D/g, ""), 10) || 0;
      const secondHalf = (live.period || 0) >= 2 || minute > 45;
      let s1 = `<b>${live.label || "Canlı"} · ${live.home_score}-${live.away_score}.</b> `;
      const cond = secondHalf && m.htft ? htConditional(m.htft, live.ht_home != null ? resultKey(live.ht_home, live.ht_away) : lead) : null;
      if (cond) {
        const base = live.ht_home != null ? `Devre arası ${live.ht_home}-${live.ht_away}` : `Şu an ${SIDE[lead]}${lead === "d" ? "" : " önde"}`;
        s1 += `${base}; benzer maçlarda bu durumdan maç sonu: ev sahibi ${pct(100 * cond.h)}, beraberlik ${pct(100 * cond.d)}, deplasman ${pct(100 * cond.a)}. `;
      }
      s1 += lead === f ? `Maç, piyasanın (${pct(mk)}) ve geçmişin (${pct(hs)}) işaret ettiği yönde gidiyor.`
        : lead === "d" ? `Favori ${name} (${pct(mk)}) henüz öne geçemedi.` : `Favori ${name} (${pct(mk)}) geride; bu profildeki maçların ${pct(m.adj[lead])}'i böyle bitiyor.`;
      parts.push(s1); short.push(s1);
      if (m.halves && m.halves.sh_avg != null) {
        const need = Math.max(0, 3 - total);
        let s2 = `Gol: şu ana kadar ${total}. 2,5 üstü için ${need === 0 ? "sınır geçildi" : `en az ${need} gol daha gerekli`}; `;
        s2 += secondHalf ? `benzer maçlarda ikinci yarıda ortalama ${num(m.halves.sh_avg)} gol atıldı, en az 1 gol ${pct(100 * m.halves.sh_over05)}, en az 2 gol ${pct(100 * m.halves.sh_over15)}.`
          : `benzer maçlarda ilk yarıda ortalama ${num(m.halves.fh_avg)} gol, maç toplamı ${num(m.avg_goals)}; 2,5 üstü ${pct(ho)} (piyasa ${pct(mo)}).`;
        parts.push(s2);
      }
      return { short: short.join(" "), full: parts.join(" ") };
    }

    // pre-match
    let s1 = `Piyasa favorisi <b>${name}</b> (${pct(mk)}); benzer ${m.n} maçta ${pct(hs)} → ${tone(diff)}.`;
    parts.push(s1); short.push(s1);
    if (mo != null && ho != null) {
      const gd = ho - mo;
      parts.push(`Gol: piyasa 2,5 üstü ${pct(mo)}, benzer maçlar ${pct(ho)}${Math.abs(gd) < 3 ? " → aynı görüşte" : gd > 0 ? " → geçmiş daha gollü" : " → geçmiş daha az gollü"}; iki takım da gol attı ${pct(m.btts)}, ortalama ${num(m.avg_goals)} gol.`);
    }
    if (m.ht && m.ht.home != null && m.htft) {
      const top = HTFT_ORDER.map((k) => [k, m.htft[k] || 0]).sort((a, b) => b[1] - a[1])[0];
      parts.push(`İlk yarı: benzer maçların ${pct(m.ht.home)}'inde ev sahibi, ${pct(m.ht.draw)}'inde berabere, ${pct(m.ht.away)}'inde deplasman devreye önde girdi; en sık İY/MS ${top[0]} (${pct(100 * top[1])}).`);
    }
    parts.push(`<span class="muted">Bu yorum yalnızca oran profiline ve geçmiş sayımlara dayanır; kadro, form ve sakatlık bilgisi içermez.</span>`);
    return { short: short.join(" "), full: parts.join(" ") };
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
      <div class="card-top"><span>${esc(m.league_name)}${m.time ? " · " + esc(m.time) : ""} <span class="live-slot">${liveBadge(state.live?.[m.id], m)}</span></span><span class="num">Benzerlik ${pct(m.avg_sim, 1)}</span></div>
      <div class="teams"><span>${esc(m.home)}</span><span class="vs">–</span><span>${esc(m.away)}</span></div>
      <div class="odds">${["h", "d", "a"].map((k) => `<div class="odd"><span class="label">${OUT[k]}</span><div class="v num">${num(m.odds[k])}</div><div class="p num">piyasa ${pct(m.market[k])}</div></div>`).join("")}</div>
      <div class="legend"><span><i></i>Piyasanın beklentisi</span><span><i class="hist"></i>Benzer maçlarda gerçekleşen</span></div>
      <div class="bars">${barRow("Ev sahibi", m.market.h, m.adj.h, scale)}${barRow("Beraberlik", m.market.d, m.adj.d, scale)}${barRow("Deplasman", m.market.a, m.adj.a, scale)}</div>
      <p class="sentence">${sentence(m)}</p>
      <div class="tags"><span class="tag ${sigCls}">${sigLabel}</span><span class="tag">Güven: ${CONF[m.confidence] || m.confidence} · ${m.n} maç</span></div>
      <p class="comment" data-comment><b class="comment-label">Yorum</b> ${commentary(m, state.live?.[m.id]).short}</p>
      <div class="goals">Benzer maçlarda gol: 2,5 üstü ${pct(m.over25)} · iki takım da gol attı ${pct(m.btts)} · ortalama ${num(m.avg_goals)} gol${m.market_over25 != null ? ` · piyasanın 2,5 üstü beklentisi ${pct(m.market_over25)}` : ""}</div>
      <span class="card-more">Ayrıntılar ve benzer maçlar →</span>`;
  }

  function renderCards() {
    const wrap = $("#cards"); wrap.innerHTML = "";
    let ms = state.day.matches.filter((m) => state.leagues.has(m.league) && state.status.has(matchStatus(m)));
    if (state.onlyDev) ms = ms.filter((m) => m.signal.includes("DEVIATION"));
    if (state.sort === "edge") ms.sort((a, b) => maxEdge(b) - maxEdge(a));
    else if (state.sort === "time") ms.sort((a, b) => (a.date + a.time).localeCompare(b.date + b.time));
    else ms.sort((a, b) => a.league_name.localeCompare(b.league_name, "tr") || a.time.localeCompare(b.time));
    $("#count").textContent = `${fmtDate(state.date)} · ${ms.length} maç`;
    if (!state.day.matches.length) {
      const today = state.meta?.today || "";
      const msg = state.date < today
        ? "Bu gün için kayıtlı analiz yok."
        : "Bu gün için henüz analiz yok. Football-Data yeni haftanın maçlarını oranlarıyla birlikte genellikle <b>Salı–Çarşamba</b> yükler; sabah 09:30'daki otomatik güncellemeden sonra bu günün maçları burada görünür. Daha erken görmek için sağ üstteki durum düğmesinden <b>Şimdi güncelle</b> diyebilirsin.";
      wrap.appendChild(el("div", "day-empty", msg)); return;
    }
    if (!ms.length) { wrap.appendChild(el("p", "count", "Filtrelere uyan maç yok.")); return; }
    ms.forEach((m) => {
      const c = el("button", "card", cardHTML(m)); c.type = "button"; c.dataset.id = m.id; c.setAttribute("aria-label", `${m.home} – ${m.away} ayrıntıları`);
      c.onclick = () => openSheet(m);
      wrap.appendChild(c);
    });
  }

  // ------------------------------------------------------------------ detail sheet
  const HTFT_ORDER = ["1/1", "1/X", "1/2", "X/1", "X/X", "X/2", "2/1", "2/X", "2/2"];

  function htftSection(m) {
    const d = m.htft || {};
    if (!Object.keys(d).length) return "";
    const ht = m.ht || {};
    const max = Math.max(...HTFT_ORDER.map((k) => d[k] || 0)) || 1;
    const top = HTFT_ORDER.map((k) => [k, d[k] || 0]).sort((a, b) => b[1] - a[1]).slice(0, 3);
    return `<section><h3>İlk yarı / maç sonu (benzer maçlar)</h3>
      <p class="sentence">İlk yarı sonucu: ev sahibi önde <b>${pct(ht.home)}</b>, berabere <b>${pct(ht.draw)}</b>, deplasman önde <b>${pct(ht.away)}</b>${ht.n ? ` (${ht.n} maç)` : ""}.
      En sık İY/MS: ${top.map(([k, v]) => `<b>${k}</b> ${pct(100 * v)}`).join(" · ")}.</p>
      <div class="vbars">${HTFT_ORDER.map((k) => `<div class="vbar"><span class="num">${(100 * (d[k] || 0)).toFixed(0)}%</span><i style="height:${Math.max(2, ((d[k] || 0) / max) * 80)}%"></i><small>${k}</small></div>`).join("")}</div>
      <p class="note">İY/MS = ilk yarı sonucu / maç sonucu. 1 = ev sahibi, X = beraberlik, 2 = deplasman. Örnek: X/2 = ilk yarı berabere, maçı deplasman kazandı.</p>
      ${halvesTable(m.halves)}</section>`;
  }

  function halvesTable(h) {
    if (!h || h.fh_avg == null) return "";
    const p = (v) => pct(100 * v);
    return `<h3 style="margin-top:12px">Yarı yarı gol (benzer maçlar)</h3>
      <div class="table-wrap"><table><thead><tr><th>Yarı</th><th class="num">Ort. gol</th><th class="num">0,5 üst</th><th class="num">1,5 üst</th></tr></thead><tbody>
      <tr><td>İlk yarı</td><td class="num">${num(h.fh_avg)}</td><td class="num">${p(h.fh_over05)}</td><td class="num">${p(h.fh_over15)}</td></tr>
      <tr><td>İkinci yarı</td><td class="num">${num(h.sh_avg)}</td><td class="num">${p(h.sh_over05)}</td><td class="num">${p(h.sh_over15)}</td></tr>
      </tbody></table></div>
      <p class="note">İkinci yarıda daha çok gol: ${p(h.more_goals_2h)} · iki yarı eşit: ${p(h.equal_halves)} · ilk yarıda daha çok: ${p(1 - h.more_goals_2h - h.equal_halves)}. "0,5 üst" = o yarıda en az 1 gol, "1,5 üst" = en az 2 gol. Yarılar için piyasa oranı kaynakta yok; bunlar yalnızca gerçekleşen sonuçlardır.</p>`;
  }

  function vbars(obj, title, note) {
    const entries = Object.entries(obj); if (!entries.length) return "";
    const max = Math.max(...entries.map(([, v]) => v)) || 1;
    return `<section><h3>${title}</h3><div class="vbars">${entries.map(([k, v]) => `<div class="vbar"><span class="num">${(100 * v).toFixed(0)}%</span><i style="height:${Math.max(2, (v / max) * 80)}%"></i><small>${esc(k)}</small></div>`).join("")}</div>${note ? `<p class="note">${note}</p>` : ""}</section>`;
  }

  /** The whole analysis of one match as HTML. The same body fills the full-screen sheet (Maçlar, Nesine)
      and the panel that opens inside a coupon (Oyun), so ids are data attributes scoped to the container. */
  function detailHTML(m) {
    const rows = ["home", "draw", "away"].map((oc) => {
      const k = KEY[oc]; const [outside, ci] = outsideCI(m, oc);
      return `<tr><td>${OUT[k]}</td><td class="num">${pct(m.market[k], 1)}</td><td class="num hide-sm">${pct(m.hist[k], 1)}</td><td class="num">${pct(m.adj[k], 1)}</td><td class="num">${pp(m.edge[k])}</td><td class="num hide-sm">${ci || "–"}</td><td class="num hide-sm">${num(m.fair[k])}</td><td class="wrap">${outside ? '<span class="yes">Hayır, anlamlı</span>' : '<span class="no">Evet, olabilir</span>'}</td></tr>`;
    }).join("");
    const scopeTr = { global: "Tüm ligler", same_league: "Sadece aynı lig", similar_leagues: "Benzer ligler" };
    const scopes = Object.entries(m.scopes || {}).map(([k, v]) => `<tr><td>${scopeTr[k] || k}</td><td class="num">${v.n}</td><td class="num">${v.hist.map((x) => `%${(100 * x).toFixed(0)}`).join(" / ")}</td><td class="num">${v.adj.map((x) => `%${(100 * x).toFixed(0)}`).join(" / ")}</td><td class="num">${pct(v.avg_similarity, 1)}</td></tr>`).join("");
    const tol = m.tolerance?.probs ? Object.entries(m.tolerance.probs).map(([k, v]) => `±${(100 * Number(k)).toFixed(0)} puan: ${v} maç`).join(" · ") : "";
    const top = Object.entries(m.scorelines || {}).filter(([k]) => k !== "other").sort((a, b) => b[1] - a[1]).slice(0, 8);
    const nesineNote = m.source === "nesine"
      ? `<p class="note nt-warn">Bu analiz <b>nesine oranlarıyla</b> yapıldı. Nesine'nin marjı yüksektir (bu maçta oranların toplam ihtimali <b>${m.overround != null ? "%" + (100 * m.overround).toFixed(0) : "?"}</b>, Avrupa ortalamasında ~%107), marj çıkarıldıktan sonraki yüzdeler bu yüzden Maçlar sekmesindekilerden biraz farklı çıkabilir. Benzer maçlar yine 38 ligden, 179 bin maçlık havuzdan seçilir; bu maçın ligi havuzda olmayabilir, seçim yalnızca oran profiline bakar.</p>`
      : "";
    return `
      ${nesineNote}
      ${decisionHTML(m)}
      <section><h3>Yorum</h3><p class="sentence comment full" data-mcomment="${esc(m.id)}">${commentary(m, state.live?.[m.id]).full}</p></section>
      <section><h3>Üç ihtimal, üç bakış</h3><div class="table-wrap"><table>
        <thead><tr><th>Sonuç</th><th class="num">Piyasa</th><th class="num hide-sm">Geçmiş (ham)</th><th class="num">Düzeltilmiş</th><th class="num">Sapma</th><th class="num hide-sm">%95 aralık</th><th class="num hide-sm">Adil oran</th><th>Şansla açıklanır mı?</th></tr></thead>
        <tbody>${rows}</tbody></table></div>
        <p class="note">Adil oran = 1 / düzeltilmiş geçmiş ihtimal. Piyasa oranı bundan yüksekse piyasa bu sonucu geçmişe göre daha az olası görüyor; bu tek başına kârlı bahis demek değildir.</p></section>
      ${htftSection(m)}
      ${vbars(m.goals_dist || {}, "Toplam gol dağılımı (benzer maçlar)")}
      ${vbars(Object.fromEntries(top), "En sık skorlar (benzer maçlar)")}
      ${scopes ? `<section><h3>Farklı havuzlarla aynı hesap</h3><div class="table-wrap"><table><thead><tr><th>Havuz</th><th class="num">Maç</th><th class="num">Ev / Ber. / Dep.</th><th class="num">Düzeltilmiş</th><th class="num">Benzerlik</th></tr></thead><tbody>${scopes}</tbody></table></div></section>` : ""}
      ${tol ? `<section><h3>Tolerans eşleşmesi</h3><p class="note">Üç ihtimalin hepsi bu kadar yakın olan geçmiş maç sayısı: ${tol}</p></section>` : ""}
      <section data-anchor="move"><h3>Oran hareketi <small class="muted">(nesine, kick-off'a doğru)</small></h3>${whatFor("move")}<div data-move>Yükleniyor…</div></section>
      <section data-anchor="dna"><h3>Maç künyesi <small class="muted">(maç öncesi bilinenler)</small></h3>${whatFor("dna")}<div data-dna>Yükleniyor…</div></section>
      <section data-anchor="twins"><h3>Çok boyutlu ikizler <small class="muted">(araştırma)</small></h3>${whatFor("twins")}
        <div class="kseg" data-twink>${[25, 50, 100, 250].map((k) => `<button type="button" data-k="${k}" class="${k === 50 ? "is-on" : ""}">${k}</button>`).join("")}</div>
        <div data-twins>Yükleniyor…</div></section>
      <section data-anchor="patterns"><h3>Bu form dizisinden sonra <small class="muted">(desen motoru)</small></h3>${whatFor("patterns")}<div data-patterns>Yükleniyor…</div></section>
      <section data-anchor="fixture"><h3>Fikstür bağlamı <small class="muted">(aynı sıra tekrarlıyor mu)</small></h3>${whatFor("fixture")}<div data-fixture>Yükleniyor…</div></section>
      <section data-anchor="combo"><h3>İki takım birlikte <small class="muted">(koşul koşul)</small></h3>${whatFor("combo")}<div data-combo>Yükleniyor…</div></section>
      <section data-anchor="nesine"><h3>Nesine oranları ve defter notları</h3><div data-nesine>Yükleniyor…</div></section>
      <section><h3>Aynı takımlar</h3><div data-teams>Yükleniyor…</div></section>
      <section><h3>En benzer geçmiş maçlar</h3><div class="kseg" data-kseg>${[25, 50, 100, 250, 500].map((k) => `<button type="button" data-k="${k}" class="${k === 25 ? "is-on" : ""}">${k}</button>`).join("")}</div><div data-analogues>Yükleniyor…</div></section>`;
  }


  /** What each engine is FOR, in the place the reader meets it. Written to answer the question a
      user actually has — "does this help me decide?" — and the measured answer to that is no, not
      in the sense of picking winners. Saying so where the numbers are is the whole point: a table
      of historical rates with no such line reads as a tip sheet whatever the footnotes say. */
  const WHAT_FOR = {
    move: ["Fiyat kick-off'a doğru ne yaptı?",
      `<p>Oran, bahis girdikçe ve haber geldikçe oynar. Bu blok o hareketi <b>marjsız olasılık</b> cinsinden ölçer —
       çünkü 1,80'den 1,65'e düşmek ile 6,00'dan 5,50'ye düşmek aynı miktarda bilgi değildir, üstelik ham oran
       nesine'nin payını da taşır (alt liglerde %17'ye kadar).</p>
       <p><b>Ne işe yarar:</b> "bu maçta fiyat oynadı mı, ne kadar, ne kadar hızlı ve tek yönlü mü" sorusuna sayı verir.
       Kapanışa yakın tek yönlü sert hareket, piyasanın yeni bir şey öğrendiğinin işaretidir — <i>ne öğrendiğini</i> söylemez.</p>
       <p><b>Ne işe yaramaz:</b> "STEAM var, o zaman oynanır" demeye. Bunu iddia edebilmek için hareket sınıfının
       sonuçları fiyattan daha iyi öngördüğünü ölçmüş olmamız gerekir. Arşiv 15 Eylül 2026'da başladı; o ölçüm
       henüz yapılamıyor ve yapılana kadar burada ROI iddiası göremeyeceksiniz.</p>`],
    dna: ["Maçın maç öncesi künyesi",
      `<p>Bu satırlar motorların <b>girdisi</b>. Güç göstergesi (TSI) sonuçtan değil, piyasanın o maça verdiği
       fiyattan öğrenir — bu yüzden "sonucu bilme" sızıntısı taşımaz.</p>
       <p><b>Ne işe yarar:</b> aşağıdaki iki motorun neye bakarak benzerlik kurduğunu görmeye. Bir ikiz listesi
       beklemediğiniz maçlar getiriyorsa sebebi genelde buradadır.</p>`],
    twins: ["Benzer maçlarda ne olmuş?",
      `<p>Bu maça yalnız fiyatıyla değil, yedi başlıkta birden benzeyen geçmiş maçları bulur ve o maçlarda ne
       olduğunu gösterir — <b>her zaman o maçların kendi fiyatının yanında</b>.</p>
       <p><b>Asıl okunacak satır budur:</b> "50 ikizde %69 kazanmış" tek başına hiçbir şey demez. O maçların fiyatı
       da %68 diyorsa piyasa zaten biliyordu. Fark satırına ve onun %95 aralığına bakın; <b>aralık sıfırı
       içeriyorsa ortada bulgu yok</b>.</p>
       <p><b>Ölçülmüş sonuç:</b> bu motoru tahmine çevirip 5.000 maçlık ileriye dönük testte piyasayla yarıştırdık.
       Geçemedi (Araştırma sekmesi). Yani karar verirken kullanacağınız şey "ikizler şunu diyor" değil,
       "ikizler piyasadan farklı bir şey söylemiyor" olmalı — ki bu da bir bilgidir: fikrinizi eleyen bilgi.</p>`],
    patterns: ["Bu form dizisinden sonra ne oluyor?",
      `<p>Aynı form dizisiyle gelen takımların geçmişte ne yaptığını üç havuzda ölçer: bu takım, tüm takımlar,
       ve <b>o tarihte benzer güçte</b> olan takımlar (isimle değil, güç bandıyla).</p>
       <p><b>Ne işe yarar:</b> "WWWWW gelen takım kazanır" türü sezgileri <b>elemeye</b>. Böyle bir takım gerçekten
       daha sık kazanır — ve piyasa bunu zaten fiyatlar. Tablo bunu yan yana koyar.</p>
       <p><b>Dikkat:</b> "Bu takım" satırındaki N çoğu zaman tek haneli olur; %100 yazması hiçbir şey ifade etmez,
       o yüzden güven aralığı da yanında durur. 396 aday desen taradık, üç zaman penceresinden ve çoklu test
       düzeltmesinden <b>bir tanesi</b> sağ çıktı — o da "fiyattan ~2 puan daha az kaybediyor" diyor.</p>`],
    fixture: ["Aynı fikstür sırası tekrarlıyor mu?",
      `<p>"2013'te de aynı sırayla oynamışlardı ve şu olmuştu" tipindeki grafikler bu bölümün konusu.
       Burada o iddiayı kontrol edebilirsin: iki takımın geçmiş karşılaşmaları, her birinin öncesinde ve
       sonrasında kimlerle oynadıklarıyla birlikte.</p>
       <p><b>Ölçüldü:</b> "aynı bağlam yaşandıysa sonuç tekrarlar" iddiası tüm veritabanında sınandı. Bağlam
       eklendikçe etki <b>kayboluyor</b>, artmıyor — çünkü bağlam etkiyi yaratmıyor, sadece örneklemi
       küçültüyor. Ayrıntılı tablo aşağıda.</p>`],
    combo: ["İki takımı birlikte tarif etmek",
      `<p>Koşullar tek tek ekleniyor ve her satır bir öncekinin alt kümesi. Amaç son satır değil: <b>hangi koşulun
       sayıyı değiştirdiğini</b> görmek.</p>
       <p><b>Ne işe yarar:</b> bir koşul eklediğinizde fark büyüyor ama N düşüyorsa, aralığın ne kadar açıldığına
       bakın. Genelde fark büyümez — sadece belirsizleşir. Bu tabloyu okumanın doğru yolu budur.</p>
       <p><b>Neden 3'lü dizi varsayılan:</b> ölçtük. Birebir 5'li diziyle iki tarafı birden tarif ettiğinizde
       180 bin maçta ortanca örneklem rakip daha tarif edilmeden <b>sıfıra</b> iniyor. Tek bir tarihsel maçı
       tarif eden desen hiçbir şey öngörmez.</p>`],
  };

  function whatFor(key) {
    const x = WHAT_FOR[key];
    return x ? `<details class="whatfor"><summary>Bu bölüm ne işe yarar?</summary><div>${x[1]}</div></details>` : "";
  }


  // ---------------------------------------------------------------- karar özeti
  // Every engine already answers the same question — "is this different from the price, and by how
  // much, and how sure are we" — but the answers were scattered over twelve sections and the reader
  // had to combine the intervals in their head. This card puts them on one line each, drawn against
  // zero, and then says out loud what the combination means. In most matches that sentence is
  // "nothing here", which is the honest majority case and the one the old layout hid best.
  const DECISION_ROWS = [
    ["price", "Benzer fiyat", "Fiyatı bu maça benzeyen geçmiş maçlar (ana motor)"],
    ["twins", "Çok boyutlu ikiz", "Fiyat + güç + form + gol benzerliği"],
    ["pattern", "Form deseni", "Aynı form dizisiyle gelen takımlar"],
    ["combo", "İki takım birlikte", "Her iki takımın durumu aynı anda"],
    ["move", "Oran hareketi", "Fiyat kick-off'a doğru ne yaptı"],
  ];
  const DECISION_OUTCOMES = [["home", "Ev sahibi kazanır"], ["draw", "Beraberlik"],
                             ["away", "Deplasman kazanır"], ["over25", "2,5 üst"]];

  function decisionHTML(m) {
    const best = (m.market?.h >= m.market?.a && m.market?.h >= m.market?.d) ? "home"
      : (m.market?.a >= m.market?.d ? "away" : "draw");
    return `<section class="decide" data-decide data-oc="${best}">
      <div class="decide-top"><h3>Karar özeti</h3>
        <select data-decide-oc aria-label="Hangi sonuç">${DECISION_OUTCOMES.map(([k, t]) =>
          `<option value="${k}"${k === best ? " selected" : ""}>${t}</option>`).join("")}</select></div>
      <div class="decide-mk" data-decide-mk></div>
      <div class="table-wrap"><table class="decide-tbl"><thead><tr><th>Motor</th><th class="num">Fark</th>
        <th>Sıfıra göre</th><th class="num hide-sm">%95 aralık</th></tr></thead>
        <tbody>${DECISION_ROWS.map(([k, label, hint]) =>
          `<tr data-row="${k}"><td class="wrap"><button type="button" class="jump" data-jump="${k}" title="${esc(hint)}">${label}</button></td>
           <td class="num" data-cell="edge">…</td><td data-cell="bar"></td>
           <td class="num hide-sm" data-cell="ci">…</td></tr>`).join("")}</tbody></table></div>
      <p class="decide-verdict" data-decide-verdict>Motorlar yükleniyor…</p>
    </section>`;
  }

  /** One interval drawn against zero. The only thing worth seeing at a glance is whether it crosses. */
  function ciBar(edge, lo, hi) {
    if (edge == null || lo == null || hi == null) return `<span class="muted">–</span>`;
    const span = Math.max(12, Math.abs(lo), Math.abs(hi), Math.abs(edge)) * 1.1;
    const x = (v) => 50 + 50 * (Math.max(-span, Math.min(span, v)) / span);
    const crosses = lo <= 0 && hi >= 0;
    return `<svg class="cib ${crosses ? "" : "solid"}" viewBox="0 0 100 14" preserveAspectRatio="none"
        role="img" aria-label="${edge > 0 ? "+" : ""}${edge.toFixed(1)} puan, aralık ${lo.toFixed(1)} ile ${hi.toFixed(1)}, sıfırı ${crosses ? "içeriyor" : "içermiyor"}">
      <line class="zero" x1="50" y1="0" x2="50" y2="14"/>
      <line class="rng" x1="${x(lo).toFixed(1)}" y1="7" x2="${x(hi).toFixed(1)}" y2="7"/>
      <circle class="pt" cx="${x(edge).toFixed(1)}" cy="7" r="2.6"/></svg>`;
  }

  /** Each loader reports here as it finishes; the verdict is recomputed from whatever has arrived. */
  function setDecision(root, key, data) {
    const box = root.querySelector("[data-decide]");
    if (!box) return;
    box._got = box._got || {};
    if (data !== undefined) box._got[key] = data;
    const oc = box.dataset.oc;
    const rows = box._got;
    let crossing = 0, solid = 0, known = 0;
    DECISION_ROWS.forEach(([k]) => {
      const tr = box.querySelector(`[data-row="${k}"]`);
      if (!tr) return;
      const got = rows[k];
      const v = got && typeof got === "function" ? got(oc) : got;
      if (!v) { tr.querySelector('[data-cell="edge"]').textContent = rows[k] === null ? "yok" : "…";
                tr.querySelector('[data-cell="ci"]').textContent = "–";
                tr.querySelector('[data-cell="bar"]').innerHTML = ""; return; }
      if (v.text) {                                    // movement: a label, not an edge
        tr.querySelector('[data-cell="edge"]').innerHTML = esc(v.text);
        tr.querySelector('[data-cell="ci"]').textContent = v.note || "–";
        tr.querySelector('[data-cell="bar"]').innerHTML = "";
        return;
      }
      const [lo, hi] = v.ci || [null, null];
      tr.querySelector('[data-cell="edge"]').innerHTML = v.edge == null ? "–"
        : `<b class="${lo != null && (lo > 0 || hi < 0) ? "yes" : ""}">${pp1(v.edge)}</b>`;
      tr.querySelector('[data-cell="ci"]').textContent = lo == null ? "–" : `[${pp1(lo)}, ${pp1(hi)}]`;
      tr.querySelector('[data-cell="bar"]').innerHTML = ciBar(v.edge, lo, hi);
      if (lo != null) { known++; if (lo > 0 || hi < 0) solid++; else crossing++; }
    });
    const vb = box.querySelector("[data-decide-verdict]");
    if (!known) { vb.textContent = "Motorlar yükleniyor…"; return; }
    const name = (DECISION_OUTCOMES.find(([k]) => k === oc) || [, oc])[1];
    vb.innerHTML = solid === 0
      ? `<b>«${esc(name)}» için ${known} ölçümün ${known === 1 ? "tamamı" : "hepsi"} sıfırı içeriyor — bu maçta piyasadan
         ayrılan bir şey bulunamadı.</b> Bu, sonucun ne olacağı hakkında bir şey söylemez; sadece bizim fiyata
         ekleyecek bir şeyimiz olmadığını söyler.`
      : `${known} ölçümden <b>${solid} tanesi</b> sıfırı dışlıyor, ${crossing} tanesi içeriyor.
         Dışlayan satır(lar) tek başına bir bahis gerekçesi değildir: aynı maçta dört market ve beş motor
         ölçülüyor, yani bu kadar testten birinin şans eseri sıfırı dışlaması beklenen bir şeydir.
         <b>Hiçbir motor ileriye dönük testte piyasayı geçemedi</b> (Araştırma sekmesi).`;
  }

  function mountDecision(root, m) {
    const box = root.querySelector("[data-decide]");
    if (!box) return;
    const mk = box.querySelector("[data-decide-mk]");
    const sel = box.querySelector("[data-decide-oc]");
    const paint = () => {
      const oc = box.dataset.oc, k = KEY[oc];
      const p = oc === "over25" ? m.over25 : m.market?.[k];
      const fair = oc === "over25" ? (m.over25 ? 100 / m.over25 : null) : m.fair?.[k];
      const mkt = oc === "over25" ? m.market_over25 : m.market?.[k];
      mk.innerHTML = `<span>Piyasa <b>${pct(mkt, 1)}</b></span>
        <span>Geçmiş (düzeltilmiş) <b>${pct(p, 1)}</b></span>
        <span>Adil oran <b>${num(fair)}</b></span>
        <span class="muted">${esc((DECISION_OUTCOMES.find(([x]) => x === oc) || [, ""])[1])}</span>`;
      setDecision(root, "__paint", undefined);
    };
    sel.onchange = () => { box.dataset.oc = sel.value; paint(); };
    // the card doubles as the table of contents: the engines themselves sit eight sections further
    // down, which is how a reader ends up asking which tab they are on
    const ANCHOR = { price: "twins", twins: "twins", pattern: "patterns", combo: "combo", move: "move" };
    box.querySelectorAll("[data-jump]").forEach((b) => {
      b.onclick = () => {
        const target = root.querySelector(`[data-anchor="${ANCHOR[b.dataset.jump] || b.dataset.jump}"]`);
        if (target) target.scrollIntoView({ behavior: "smooth", block: "start" });
      };
    });
    paint();
    // the price engine's own answer is already in the payload
    const priceRow = (oc) => {
      if (oc === "over25") return { edge: null, ci: [null, null] };
      const k = KEY[oc], [outside, ci] = outsideCI(m, oc);
      const raw = (m.ci?.[k] || [null, null]);
      return { edge: m.edge?.[k], ci: m.market?.[k] == null || raw[0] == null ? [null, null]
                 : [raw[0] - m.market[k], raw[1] - m.market[k]] };
    };
    setDecision(root, "price", priceRow);
  }

  /** Put that body into `root` and start the three lazy parts inside it. */
  function mountDetail(root, m) {
    root.innerHTML = detailHTML(m);
    mountDecision(root, m);
    root.querySelectorAll("[data-kseg] button").forEach((b) => {
      b.onclick = () => {
        root.querySelectorAll("[data-kseg] button").forEach((x) => x.classList.toggle("is-on", x === b));
        loadAnalogues(m, Number(b.dataset.k), root);
      };
    });
    root.querySelectorAll("[data-twink] button").forEach((b) => {
      b.onclick = () => {
        root.querySelectorAll("[data-twink] button").forEach((x) => x.classList.toggle("is-on", x === b));
        loadTwins(m, root, Number(b.dataset.k));
      };
    });
    loadAnalogues(m, 25, root);
    loadTeams(m, root);
    // the movement engine is keyed by nesine's match code, which the nesine lookup is what resolves
    Promise.resolve(loadNesineFor(m, root)).then(() => loadMovement(m, root));
    loadTwins(m, root, 50);
    loadPatterns(m, root);
    loadCombined(m, root);
    loadFixture(m, root);
  }

  /** "Aynı fikstür sırası tekrarlıyor" — the pattern those Mackolik graphics are built on, made
      checkable. The measurement travels with it, because it says the context is what kills the
      effect rather than what creates it. */
  async function loadFixture(m, root) {
    const box = root.querySelector("[data-fixture]");
    if (!box) return;
    if (m.source === "nesine") { box.innerHTML = `<p class="note">Bu bölüm veritabanımızdaki maçlar için çalışır.</p>`; return; }
    try {
      const d = m._fx !== undefined ? m._fx : await api(`/api/fikstur/${encodeURIComponent(m.id)}`);
      m._fx = d;
      const q = d.match, v = d.verdict;
      const chip = (on, txt) => `<span class="fx-o ${on ? "on" : ""}">${esc(txt || "–")}</span>`;
      const rows = (d.shown || []).map((r) => `<tr class="${r.same_full ? "ac-alive" : ""}">
        <td class="num">${fmtShort(r.date)}</td><td class="num res-${esc(r.ftr)}">${esc(r.score)}</td>
        <td class="wrap hide-sm">${chip(r.same.h_prev_opp, r.h_prev_opp)}</td>
        <td class="wrap hide-sm">${chip(r.same.h_next_opp, r.h_next_opp)}</td>
        <td class="num">${r.n_same}/4</td></tr>`).join("");
      box.innerHTML = `<p class="sentence">Bu maçtan önce <b>${esc(q.home)}</b> ${chip(true, q.h_prev_opp)} ile oynadı,
          sonra ${chip(true, q.h_next_opp)} ile oynayacak. <b>${esc(q.away)}</b> için: ${chip(true, q.a_prev_opp)} →
          ${chip(true, q.a_next_opp)}. Aynı iki takım daha önce <b>${d.meetings}</b> kez karşılaştı.</p>
        ${rows ? `<div class="table-wrap"><table><thead><tr><th>Tarih</th><th class="num">Skor</th>
          <th class="hide-sm">Ev · önceki rakip</th><th class="hide-sm">Ev · sonraki rakip</th>
          <th class="num">Bağlam</th></tr></thead><tbody>${rows}</tbody></table></div>`
          : `<p class="note">Bu iki takımın veritabanında daha önceki karşılaşması yok.</p>`}
        <p class="note">Yeşil işaretli rakip, bugünküyle <b>aynı</b>. "Bağlam" sütunu dört bağlam öğesinden
          kaçının tuttuğunu söyler (ev/deplasman × önceki/sonraki rakip).</p>
        <div class="fx-verdict">
          <p><b>Peki bu bir şey söylüyor mu?</b> Tüm veritabanında ölçtük: "geçmişte aynı bağlam yaşandıysa sonuç
          tekrarlar" iddiası. Karşılaştırma her zaman <b>o maçların kendi fiyatıyla</b>.</p>
          <div class="table-wrap"><table><thead><tr><th>Ne kadar benzer</th><th class="num">N</th>
            <th class="num">Tekrarladı</th><th class="num">Piyasa</th><th class="num">Fark</th>
            <th class="num hide-sm">%95 aralık</th></tr></thead><tbody>
            ${[["Sadece aynı eşleşme (bağlam yok)", v.none], ["+ önceki rakip de aynı", v.prev_only],
               ["+ sonraki rakip de aynı (tam bağlam)", v.full]].map(([t, x]) =>
              `<tr><td class="wrap">${t}</td><td class="num">${x.n.toLocaleString("tr")}</td>
               <td class="num">%${num(x.actual, 1)}</td><td class="num">%${num(x.market, 1)}</td>
               <td class="num ${x.ci[0] > 0 || x.ci[1] < 0 ? "yes" : ""}"><b>${pp1(x.edge)}</b></td>
               <td class="num hide-sm">[${pp1(x.ci[0])}, ${pp1(x.ci[1])}]</td></tr>`).join("")}
          </tbody></table></div>
          <p class="note"><b>Bağlam eklendikçe etki artmıyor, kayboluyor.</b> Sadece "aynı eşleşme" 141.054 maçta
          fiyatın 0,43 puan üstünde — küçük ama ölçülebilir bir şey. Önceki rakibi de şart koşunca N 26.239'a
          düşüyor ve fark 0,58 oluyor: aynı şey, daha belirsiz. Sonraki rakibi de şart koşunca N 3.901'e iniyor
          ve fark <b>−0,36</b>'ya, aralığı sıfırı içine alarak. Yani etkiyi yaratan bağlam değil; bağlam sadece
          örneklemi küçültüyor. Tek bir tarihsel tekrar (N=1) ise hiçbir şey söylemez.</p>
        </div>`;
    } catch (e) {
      const msg = String(e.message || "");
      box.innerHTML = `<p class="note">${msg.startsWith("404") ? "Bu maç için durum tablosu hazır değil." : "Yüklenemedi: " + esc(msg)}</p>`;
    }
  }

  /** TEAM A x TEAM B, one condition at a time. The point of the table is not its last row: it is
      which condition moved the number, and which only made the sample smaller. */
  async function loadCombined(m, root, opts = {}) {
    const box = root.querySelector("[data-combo]");
    if (!box) return;
    if (m.source === "nesine") { box.innerHTML = `<p class="note">Bu bölüm veritabanımızdaki maçlar için çalışır.</p>`; return; }
    const length = opts.length ?? 3, approx = opts.approx ?? 1, key = `${length}:${approx}`;
    box.innerHTML = `<p class="note">Yükleniyor…</p>`;
    try {
      m._combo = m._combo || {};
      const d = m._combo[key] !== undefined ? m._combo[key]
        : await api(`/api/kombine/${encodeURIComponent(m.id)}?length=${length}&approx=${approx}`);
      m._combo[key] = d;
      const q = d.match;
      setDecision(root, "combo", (want) => {
        const key = { home: "win", draw: "draw", away: "loss", over25: "over25" }[want];
        // the last row that still rests on a readable sample: below 200 the interval is the answer
        const usable = (d.rows || []).filter((r) => (r.outcomes?.[key]?.n || 0) >= 200);
        const r = usable[usable.length - 1];
        const x = r?.outcomes?.[key];
        if (!x) return { edge: null, ci: [null, null] };
        return { edge: x.edge != null ? x.edge : x.vs_ref, ci: x.edge_ci || x.vs_ref_ci || [null, null] };
      });
      const oc = opts.outcome || "win";
      const rows = d.rows.map((r) => {
        const x = r.outcomes[oc] || {};
        const edge = x.edge != null ? x.edge : x.vs_ref;
        const ci = x.edge_ci || x.vs_ref_ci || [null, null];
        const solid = ci[0] != null && (ci[0] > 0 || ci[1] < 0);
        const thin = x.n != null && x.n < 200;
        return `<tr class="${thin ? "thin" : ""}"><td class="wrap">${esc(r.step)}</td>
          <td class="num">${r.n}${r.n_lost ? `<br><small class="muted">−${r.n_lost}</small>` : ""}</td>
          <td class="num">${x.actual == null ? "–" : "%" + num(x.actual, 1)}</td>
          <td class="num">${(x.market ?? x.ref) == null ? "–" : "%" + num(x.market ?? x.ref, 1)}</td>
          <td class="num ${solid ? "yes" : ""}">${edge == null ? "–" : pp1(edge)}</td>
          <td class="num hide-sm">${ci[0] == null ? "–" : `[${pp1(ci[0])}, ${pp1(ci[1])}]`}</td></tr>`;
      }).join("");
      box.innerHTML = `<p class="sentence"><b>${esc(q.team)}</b> <span class="fseq">${esc(q.form)}</span>
          (sahasında <span class="fseq">${esc(q.venue_form || "–")}</span>, güç %${num(q.tsi_pct, 0)}) —
          <b>${esc(q.opponent)}</b> <span class="fseq">${esc(q.opp_form || "–")}</span>
          (<span class="fseq">${esc(q.opp_venue_form || "–")}</span>, güç %${num(q.opp_tsi_pct, 0)}).
          Koşullar tek tek ekleniyor; her satır bir öncekinin alt kümesi.</p>
        <div class="kseg" data-combolen>${[3, 4, 5].map((n) => `<button type="button" data-n="${n}" class="${n === length ? "is-on" : ""}">${n}'li dizi</button>`).join("")}</div>
        <div class="kseg" data-comboap>${[0, 1, 2].map((a) => `<button type="button" data-a="${a}" class="${a === approx ? "is-on" : ""}">${a === 0 ? "birebir" : `±${a}`}</button>`).join("")}</div>
        <div class="kseg" data-comboout>${[["win", "Kazanır"], ["over25", "2.5 üst"], ["btts", "KG"], ["ht_draw", "İY berabere"]]
          .map(([k, t]) => `<button type="button" data-o="${k}" class="${k === oc ? "is-on" : ""}">${t}</button>`).join("")}</div>
        <div class="table-wrap"><table><thead><tr><th>Koşul</th><th class="num">N</th><th class="num">Gerçekleşen</th>
          <th class="num">Piyasa</th><th class="num">Fark</th><th class="num hide-sm">%95 aralık</th></tr></thead>
          <tbody>${rows}</tbody></table></div>
        <p class="note">Varsayılan 3'lü dizi ve ±1 <b>ölçülerek</b> seçildi: birebir 5'li diziyle iki tarafı birden
          tarif ettiğinizde 180 bin maçta ortanca örneklem rakip daha tarif edilmeden <b>sıfıra</b> iniyor
          (881 → 10 → 0). Daha sıkı ayarları deneyebilirsiniz; N'in çöküşünü görmek de bir bulgudur —
          iki tane birebir 5 maçlık dizi neredeyse tekil anahtardır ve tek bir tarihsel maçı tarif eden desen
          hiçbir şey öngörmez. <b>Gri satırlar 200 maçın altında</b>, okunmamalı.</p>`;
      box.querySelectorAll("[data-combolen] button").forEach((b) => (b.onclick = () => loadCombined(m, root, { ...opts, length: Number(b.dataset.n), approx })));
      box.querySelectorAll("[data-comboap] button").forEach((b) => (b.onclick = () => loadCombined(m, root, { ...opts, length, approx: Number(b.dataset.a) })));
      box.querySelectorAll("[data-comboout] button").forEach((b) => (b.onclick = () => loadCombined(m, root, { ...opts, length, approx, outcome: b.dataset.o })));
    } catch (e) {
      const msg = String(e.message || "");
      box.innerHTML = `<p class="note">${msg.startsWith("404") ? "Bu maç için durum tablosu hazır değil." : "Yüklenemedi: " + esc(msg)}</p>`;
    }
  }

  const MOVE_TR = {
    STEAM: ["Para geliyor (STEAM)", "up"], DRIFT: ["Para çekiliyor (DRIFT)", "down"],
    REVERSAL: ["Dönüş (REVERSAL)", "warn"], STABLE: ["Sabit", "flat"], NOISY: ["Dağınık", "flat"],
    LATE_STEAM: ["son anda geldi", ""], LATE_DRIFT: ["son anda çekildi", ""],
    ACCELERATING: ["hızlanıyor", ""], DECELERATING: ["yavaşlıyor", ""],
  };
  const MOVE_SEL = { "ms.1": "Ev sahibi", "ms.X": "Beraberlik", "ms.2": "Deplasman" };

  /** The odds movement engine. Everything is in margin-free probability points, because a 0.15 drop
      in the raw price means different things at 1.80 and at 6.00 — and the raw number still carries
      nesine's margin. A verdict is never shown without the data quality that produced it. */
  async function loadMovement(m, root) {
    const box = root.querySelector("[data-move]");
    if (!box) return;
    const code = m.nesine_code || m._nesine?.code || (m.source === "nesine" ? m.code : null);
    if (!code) {
      box.innerHTML = `<p class="note">Bu maç nesine bülteninde eşleşmedi, oran hareketi geçmişi yok.</p>`;
      return;
    }
    try {
      const d = m._move !== undefined ? m._move : await api(`/api/hareket/${code}`);
      m._move = d;
      setDecision(root, "move", (oc) => {
        const path = { home: "ms.1", draw: "ms.X", away: "ms.2" }[oc];
        const sel = path && d.selections?.[path];
        if (!sel || sel.missing) return { text: "—", note: "bu markette kayıt yok" };
        const v = sel.movement;
        if (v.confidence === "low") return { text: "düşük güven", note: `${v.n_points || 0} snapshot` };
        return { text: (MOVE_TR[v.type] || [v.type])[0], note: v.total_pp == null ? "–" : `${pp1(v.total_pp)} puan` };
      });
      const rows = Object.entries(d.selections).map(([path, s]) => mvBlock(path, s, d)).filter(Boolean);
      box.innerHTML = rows.length
        ? rows.join("")
          + `<p class="note">Arşiv ${d.archive_from || "—"} tarihinde başladı; o günden öncesi için oran geçmişi <b>yok</b>,
             uydurulmuyor. Eşikler ayarlanabilir (şu an: hareket ≥ ${d.config.movement_min_pp} puan,
             tutarlılık ≥ %${Math.round(100 * d.config.direction_consistency)}, sabit &lt; ${d.config.stable_max_pp} puan).</p>`
        : `<p class="note">Bu maç için henüz kayıtlı oran hareketi yok.</p>`;
    } catch (e) {
      box.innerHTML = `<p class="note">Oran hareketi yüklenemedi: ${esc(e.message)}</p>`;
    }
  }

  function mvBlock(path, s, d) {
    if (s.missing) return "";
    const mvv = s.movement, q = s.quality;
    const [label, tone] = MOVE_TR[mvv.type] || ["—", "flat"];
    const tags = (mvv.tags || []).map((t) => (MOVE_TR[t] || [t])[0]).join(" · ");
    const low = mvv.confidence === "low";
    const win = (k) => { const w = s.windows[k]; return w && !w.insufficient ? pp1(w.delta_p) : "–"; };
    return `<div class="mvb">
      <div class="mvb-top"><b>${MOVE_SEL[path] || esc(path)}</b>
        ${low ? `<span class="chip warn">DÜŞÜK GÜVEN</span>`
              : `<span class="mv-verdict ${tone}">${label}</span>${tags ? ` <small class="muted">${tags}</small>` : ""}`}</div>
      <div class="mvb-grid">
        <div><small>Açılış</small><b class="num">${num(s.open?.odds)}</b><small class="muted">%${num(s.open?.p, 1)}</small></div>
        <div><small>Şimdi</small><b class="num">${num(s.current?.odds)}</b><small class="muted">%${num(s.current?.p, 1)}</small></div>
        <div><small>Kapanış</small><b class="num">${s.closing ? num(s.closing.odds) : "—"}</b>
          <small class="muted">${s.closing ? "%" + num(s.closing.p, 1) : (d.started ? "yok" : "maç başlamadı")}</small></div>
        <div><small>Hareket</small><b class="num ${mvv.total_pp > 0 ? "up" : mvv.total_pp < 0 ? "down" : ""}">${mvv.total_pp == null ? "–" : pp1(mvv.total_pp)}</b><small class="muted">puan</small></div>
        <div><small>Tutarlılık</small><b class="num">${mvv.consistency == null ? "–" : "%" + Math.round(100 * mvv.consistency)}</b><small class="muted">tek yönlülük</small></div>
        <div><small>Hız (1s)</small><b class="num">${s.velocity_1h == null ? "–" : pp1(s.velocity_1h)}</b><small class="muted">puan/saat</small></div>
      </div>
      ${mvSpark(s)}
      <div class="mvb-win">${["6h", "3h", "1h", "30m", "15m"].map((k) => `<span><small>${k}</small> ${win(k)}</span>`).join("")}</div>
      ${mvv.reversal ? `<p class="note">Önce ${pp1(mvv.reversal.initial_pp)} puan gitti, sonra ${pp1(mvv.reversal.reversal_pp)} puan geri döndü
        (başlangıcın %${num(mvv.reversal.recovery_pct, 0)}'i kadar).</p>` : ""}
      <p class="note">Snapshot ${q.snapshots} (${q.changes} değişim) · ilk kayıt ${ntAgo(q.first)} · son ${ntAgo(q.last)}
        ${q.coverage == null ? "" : ` · son 24 saatin %${Math.round(100 * q.coverage)}'ünde izleniyorduk`}
        ${q.novig ? "" : " · <b>marj atılamadı</b> (bu markette tüm sonuçlar izlenmiyor)"}
        ${low ? ` · <b>${mvv.reason || "veri az"}</b> — sınıflandırma yapılmadı` : ""}</p>
    </div>`;
  }

  /** Probability against time-to-kick-off. Small on purpose: the numbers above are the content. */
  function mvSpark(s) {
    const pts = (s.chart || []).filter((p) => p.minutes != null && p.p != null);
    if (pts.length < 3) return "";
    const W = 280, H = 54, pad = 3;
    const xs = pts.map((p) => Math.max(p.minutes, 0)), ys = pts.map((p) => p.p);
    const x0 = Math.max(...xs), y0 = Math.min(...ys), y1 = Math.max(...ys);
    const span = Math.max(y1 - y0, 0.5);
    const X = (m) => pad + (W - 2 * pad) * (1 - Math.max(m, 0) / Math.max(x0, 1));
    const Y = (p) => H - pad - (H - 2 * pad) * ((p - y0) / span);
    const dAttr = pts.map((p, i) => `${i ? "L" : "M"}${X(p.minutes).toFixed(1)},${Y(p.p).toFixed(1)}`).join(" ");
    const last = pts[pts.length - 1];
    return `<svg class="mv-spark" viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" role="img"
        aria-label="Kick-off'a doğru marjsız olasılık: %${ys[0].toFixed(1)} → %${last.p.toFixed(1)}">
      <path d="${dAttr}" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linejoin="round"/>
      <circle cx="${X(pts[0].minutes).toFixed(1)}" cy="${Y(pts[0].p).toFixed(1)}" r="2.5" class="sp-open"/>
      <circle cx="${X(last.minutes).toFixed(1)}" cy="${Y(last.p).toFixed(1)}" r="2.5" class="sp-now"/>
    </svg><div class="mv-axis"><small>açılış · ${Math.round(x0 / 60)} sa önce</small><small>%${y0.toFixed(1)}–%${y1.toFixed(1)}</small><small>kick-off</small></div>`;
  }

  /** The state table's own numbers for this match: strength, form, goals, rest — what the twin and
      pattern engines actually read. They were computed and then never shown, which made every
      engine below look like it ran on the price alone. */
  function dnaHTML(q) {
    if (!q) return `<p class="note">Bu maç için durum tablosu henüz hazır değil.</p>`;
    // the state table keeps ten results; the row says five, so it shows five — the most recent ones
    const formChips = (f) => String(f || "").slice(-5).split("").map((c) => `<span class="fchip f-${c}">${c === "W" ? "G" : c === "D" ? "B" : "M"}</span>`).join("") || "–";
    const tsi = (v) => (v == null ? "–" : `%${num(v, 0)} <small class="muted">lig içi</small>`);
    return `<div class="dna">
      <div class="dna-row"><span class="dna-k">Güç sırası (TSI)</span>
        <span class="dna-v">${tsi(q.h_tsi_pct)}</span><span class="dna-v">${tsi(q.a_tsi_pct)}</span></div>
      <div class="dna-row"><span class="dna-k">Son 5 (genel)</span>
        <span class="dna-v">${formChips(q.h_form)}</span><span class="dna-v">${formChips(q.a_form)}</span></div>
      <div class="dna-row"><span class="dna-k">Son 5 (kendi sahasında / deplasmanda)</span>
        <span class="dna-v">${formChips(q.h_form_venue)}</span><span class="dna-v">${formChips(q.a_form_venue)}</span></div>
      <div class="dna-row"><span class="dna-k">Son 5'te attığı – yediği</span>
        <span class="dna-v">${q.h_gf5 == null ? "–" : `${num(q.h_gf5, 0)} – ${num(q.h_ga5, 0)}`}</span>
        <span class="dna-v">${q.a_gf5 == null ? "–" : `${num(q.a_gf5, 0)} – ${num(q.a_ga5, 0)}`}</span></div>
      <div class="dna-row"><span class="dna-k">Dinlenme (gün)</span>
        <span class="dna-v">${q.h_rest_days == null ? "–" : num(q.h_rest_days, 0)}</span>
        <span class="dna-v">${q.a_rest_days == null ? "–" : num(q.a_rest_days, 0)}</span></div>
      <div class="dna-row"><span class="dna-k">Güç farkı</span><span class="dna-v" colspan="2">${q.gap == null ? "–" : (q.gap > 0 ? "+" : "") + num(q.gap, 0) + " puan (ev lehine)"}</span></div>
      </div>
      <p class="note">TSI = piyasadan türetilmiş güç göstergesi (sonuçtan değil, o maça verilen fiyattan öğrenir — bu yüzden
      sonucu bilme sızıntısı taşımaz), lig içi yüzdelik olarak. Bu satırlar aşağıdaki iki motorun girdisidir.</p>`;
  }

  /** The twin engine: similarity on form, strength and price rather than price alone. Research only —
      the model comparison says turning it into a prediction does not beat the market, and it says so here. */
  async function loadTwins(m, root, k = 50) {
    const box = root.querySelector("[data-twins]");
    const dna = root.querySelector("[data-dna]");
    if (!box) return;
    if (m.source === "nesine") {
      box.innerHTML = `<p class="note">Bu bölüm bizim veritabanımızdaki maçlar için çalışır; nesine üzerinden açılan maçlarda yok.</p>`;
      if (dna) dna.innerHTML = `<p class="note">Durum tablosu 38 ligin veritabanı üzerinden kurulur; nesine üzerinden açılan maçlarda yok.</p>`;
      return;
    }
    box.innerHTML = `<p class="note">Yükleniyor…</p>`;
    try {
      m._twins = m._twins || {};
      const d = m._twins[k] !== undefined ? m._twins[k] : await api(`/api/twins/${encodeURIComponent(m.id)}?k=${k}`);
      m._twins[k] = d;
      if (dna) dna.innerHTML = dnaHTML(d.match);
      setDecision(root, "twins", (oc) => {
        const x = d.outcomes?.[{ home: "win", draw: "draw", away: "loss", over25: "over25" }[oc]];
        return x && x.diff != null ? { edge: x.diff, ci: x.diff_ci } : { edge: null, ci: [null, null] };
      });
      const g = d.diagnostics, w = d.outcomes?.win;
      const rows = d.twins.map((t) => `<tr><td class="num">${fmtShort(t.date)}</td><td class="wrap">${esc(t.home_team)} – ${esc(t.away_team)}</td>
        <td class="num"><b>${num(t.twin_score, 1)}</b></td><td class="num hide-sm">${num(t.sim_market, 0)}</td>
        <td class="num hide-sm">${num(t.sim_form, 0)}</td><td class="num hide-sm">${num(t.sim_gap, 0)}</td>
        <td class="num res-${esc(t.ftr)}">${t.fthg == null ? "–" : `${t.fthg}-${t.ftag}`}</td></tr>`).join("");
      box.innerHTML = `<p class="note">Benzerlik yedi başlıkta ayrı ayrı ölçülür: piyasa profili, iki tarafın gücü, güç farkı,
          son beş maçın formu, gol dengesi ve oran hareketi. En yakın ${d.twins.length} maç listelenir; skor 100 = birebir aynı.</p>
        <div class="rs-funnel">
          ${[["en yakın", g.best], ["${d.k}. ikiz".replace("${d.k}", d.k), g.worst], ["ortanca", g.median], ["90 üstü", g.n_above_90]]
            .map(([k, v]) => `<div class="rs-step"><span class="v num">${v == null ? "–" : v}</span><small>${k}</small></div>`).join("")}
        </div>
        ${w && w.market != null
          ? `<p class="sentence">Bu ${w.n} ikizde ev sahibi <b>${pct(w.actual, 1)}</b> kazanmış
             <span class="muted">(%95 aralık ${pct(w.ci[0], 1)}–${pct(w.ci[1], 1)})</span>; <b>o maçların kendi fiyatı</b>
             ${pct(w.market, 1)} diyordu. Fark <b>${pp1(w.diff)}</b> puan
             <span class="muted">[${pp1(w.diff_ci[0])}, ${pp1(w.diff_ci[1])}]</span> —
             ${w.diff_ci[0] > 0 || w.diff_ci[1] < 0 ? "aralık sıfırı içermiyor" : "<b>aralık sıfırı içeriyor, yani piyasadan ayırt edilemez</b>"}.
             Bugünün piyasası ${pct(m.market.h, 1)}.</p>`
          : ""}
        <div class="table-wrap"><table><thead><tr><th>Tarih</th><th>Maç</th><th class="num">Skor</th>
          <th class="num hide-sm">Piyasa</th><th class="num hide-sm">Form</th><th class="num hide-sm">Güç farkı</th>
          <th class="num">Sonuç</th></tr></thead><tbody>${rows}</tbody></table></div>
        <p class="note">Ağırlıklar ${d.config?.source === "ayarlanmış"
            ? "doğrulama penceresinde <b>ölçülerek</b> seçildi"
            : "el ile konmuş varsayılanlar" + (d.config?.reason ? ` (${esc(d.config.reason)})` : "")}${
            g.half_life ? `; zaman ağırlığı açık, yarı ömür ${g.half_life} yıl (etkin örneklem ${num(g.n_eff, 1)})`
                        : "; zaman ağırlığı <b>kapalı</b> — ölçüldü ve açmak sonucu iyileştirmedi"}.</p>
        <p class="note">Bu bölüm araştırma içindir: aynı motoru tahmine çevirdiğimizde 5.000 maçlık ileriye dönük testte
          piyasayı geçemedi (Araştırma sekmesi). "Benzer maçlarda şu oldu" cümlesi, "bu maçta şu olur" demek değildir.</p>`;
    } catch (e) {
      const msg = String(e.message || "");
      box.innerHTML = `<p class="note">${msg.startsWith("404") ? "Bu maç için durum tablosu henüz hazır değil; günlük güncellemeden sonra görünür." : "İkizler yüklenemedi: " + esc(msg)}</p>`;
    }
  }

  const PATTERN_OUT = { win: "Kazanır", draw: "Berabere", loss: "Kaybeder", over25: "2.5 üstü",
    btts: "Karşılıklı gol", over15: "1.5 üstü", over35: "3.5 üstü", ht_draw: "İY berabere", ht_win: "İY önde" };
  const LEVEL_TR = { same_team: "Bu takım", all: "Tüm takımlar", similar: "Benzer güçteki takımlar" };

  /** The pattern engine at its three levels. The number to read is never the hit rate: it is the
      difference from what the market charged for those same matches, after the pool-wide offset. */
  async function loadPatterns(m, root, approx = 0) {
    const box = root.querySelector("[data-patterns]");
    if (!box) return;
    if (m.source === "nesine") { box.innerHTML = `<p class="note">Desen motoru veritabanımızdaki maçlar için çalışır; nesine üzerinden açılan maçlarda yok.</p>`; return; }
    box.innerHTML = `<p class="note">Yükleniyor…</p>`;
    try {
      m._pat = m._pat || {};
      const d = m._pat[approx] !== undefined ? m._pat[approx] : await api(`/api/patterns/${encodeURIComponent(m.id)}?approx=${approx}`);
      m._pat[approx] = d;
      const q = d.match;
      setDecision(root, "pattern", (oc) => {
        const x = d.levels?.all?.outcomes?.[{ home: "win", draw: "draw", away: "loss", over25: "over25" }[oc]];
        if (!x) return { edge: null, ci: [null, null] };
        return { edge: x.edge != null ? x.edge : x.vs_ref, ci: x.edge_ci || x.vs_ref_ci || [null, null] };
      });
      const near = d.levels.all?.n ?? 0;
      const lvOrder = ["same_team", "all", "similar"].filter((k) => d.levels[k]);
      const body = d.outcomes.map((o) => {
        const cells = lvOrder.map((lv) => {
          const x = d.levels[lv].outcomes[o];
          if (!x || !x.n) return `<td class="num">–</td>`;
          const edge = x.edge != null ? x.edge : x.vs_ref;
          const ci = x.edge_ci || x.vs_ref_ci;
          const solid = ci && ci[0] != null && (ci[0] > 0 || ci[1] < 0);
          return `<td class="num"><b>%${num(x.actual, 1)}</b>
            <small class="muted">/ %${num(x.market != null ? x.market : x.ref, 1)}</small><br>
            <span class="${solid ? "yes" : "muted"}">${edge == null ? "–" : pp1(edge)}</span>
            ${ci && ci[0] != null ? `<small class="muted">[${pp1(ci[0])}, ${pp1(ci[1])}]</small>` : ""}</td>`;
        }).join("");
        return `<tr><td>${PATTERN_OUT[o] || o}</td>${cells}</tr>`;
      }).join("");
      box.innerHTML = `<p class="sentence"><b>${esc(q.team)}</b> bu maça <span class="fseq">${esc(q.form)}</span> dizisiyle geldi
          (${q.side === "home" ? "ev sahibi" : "deplasman"} tarafı, lig içi güç sırası %${num(q.tsi_pct, 0)}, rakip %${num(q.opp_tsi_pct, 0)}).
          Aynı dizinin geçmişte ne getirdiği üç ayrı havuzda ölçüldü.</p>
        <div class="kseg" data-approx>${[0, 1, 2].map((a) => `<button type="button" data-a="${a}" class="${a === approx ? "is-on" : ""}">${a === 0 ? "birebir" : `±${a} maç`}</button>`).join("")}</div>
        <p class="note">Birebir eşleşme: <b>${d.n_exact}</b> maç${approx ? ` · ±${approx} toleransla: <b>${near}</b> maç` : ""}.</p>
        <div class="table-wrap"><table><thead><tr><th>Sonuç</th>
          ${lvOrder.map((lv) => `<th class="num">${LEVEL_TR[lv]}<br><small class="muted">${d.levels[lv].n} maç</small></th>`).join("")}
          </tr></thead><tbody>${body}</tbody></table></div>
        <p class="note">Her hücrede üst satır <b>gerçekleşen / o maçların kendi fiyatı</b>, alt satır ikisinin farkı ve %95 aralığı.
          Fark, havuz geneli sapma çıkarıldıktan sonradır — ev sahibi galibiyetleri fiyatın 0,6 puan üstünde geldiği için,
          bu düzeltme olmasa her ev deseni bedava 0,6 puan kazanmış görünürdü. <b>Aralık sıfırı içeriyorsa desen, piyasanın
          zaten bildiği bir şeyi söylüyor.</b> "Bu takım" seviyesindeki N tek haneliyse hiçbir şey ifade etmez.</p>`;
      box.querySelectorAll("[data-approx] button").forEach((b) => {
        b.onclick = () => loadPatterns(m, root, Number(b.dataset.a));
      });
    } catch (e) {
      const msg = String(e.message || "");
      box.innerHTML = `<p class="note">${msg.startsWith("404") ? "Bu maç için durum tablosu ya da form dizisi hazır değil (takımın yeterli geçmişi olmayabilir)." : "Desenler yüklenemedi: " + esc(msg)}</p>`;
    }
  }

  function openSheet(m) {
    const src = m.source === "nesine" ? ` · <b>nesine oranıyla</b>` : "";
    $("#sheet-sub").innerHTML = `${esc(m.league_name)}${m.time ? " · " + esc(m.time) : ""} · ${fmtDate(m.date)}${src} <span id="sheet-live" data-id="${esc(m.id)}">${liveBadge(state.live?.[m.id], m)}</span>`;
    $("#sheet-title").textContent = `${m.home} – ${m.away}`;
    mountDetail($("#sheet-body"), m);
    $("#sheet").hidden = false; $("#sheet-backdrop").hidden = false; document.body.style.overflow = "hidden";
    $("#sheet").scrollTop = 0;
  }

  /** The same match on nesine: its odds with the movement arrows and every notebook note it fires. */
  async function loadNesineFor(m, root) {
    const box = root.querySelector("[data-nesine]");
    if (!box) return;
    try {
      // opened from the Nesine tab the bulletin entry rides along; from Maçlar/Oyun it is fetched by match id
      const n = m._nesine !== undefined ? m._nesine
        : m.source === "nesine" ? null
        : (await api(`/api/match/${encodeURIComponent(m.id)}`)).nesine;
      m._nesine = n;
      if (n && n.error) { box.innerHTML = `<p class="note">Nesine bülteni okunamadı: ${esc(n.error)}</p>`; return; }
      if (!n) {
        box.innerHTML = `<p class="note">Bu maç nesine bülteninde bulunamadı — kupondan kaldırılmış, oynanmış ya da takım adları eşleşmemiş olabilir.</p>`;
        return;
      }
      const hits = n.hits || [];
      box.innerHTML = `<p class="note">nesine: ${esc(n.league)} · ${esc(n.time)} · kod ${n.code} · oranlar ${ntAgo(n.fetched_at)}${n.watch?.running ? " (canlı yenileniyor)" : ""}</p>`
        + ntOddsGrid(n)
        + (hits.length ? hits.map((x) => ntHit(n, x)).join("")
                       : `<p class="note">Bu maç defterdeki notların hiçbirinin şartını sağlamıyor.</p>`);
    } catch (e) { box.innerHTML = `<p class="note">Nesine tarafı yüklenemedi: ${esc(e.message)}</p>`; }
  }

  const OUTCOME_BADGE = { G: ["G", "Galibiyet", "win"], B: ["B", "Beraberlik", "draw"], M: ["M", "Mağlubiyet", "loss"] };

  function teamRows(rows) {
    return `<div class="table-wrap"><table><thead><tr><th>Tarih</th><th>Maç</th><th class="num hide-sm">1 / X / 2</th><th class="num">İhtimali</th><th>Sonuç</th></tr></thead><tbody>
      ${rows.map((r) => { const [l, t, c] = OUTCOME_BADGE[r.outcome] || ["?", "", ""]; return `<tr><td class="num">${fmtShort(r.date)}</td><td class="wrap">${esc(r.home)} – ${esc(r.away)} <small class="muted">${r.venue === "ev" ? "(ev)" : "(dep.)"}</small></td><td class="num hide-sm">${r.odds.map((o) => num(o)).join(" / ")}</td><td class="num">${pct(r.p_team)}</td><td><span class="badge ${c}" title="${t}">${l}</span> ${esc(r.score)}</td></tr>`; }).join("")}
      </tbody></table></div><p class="table-hint">Telefonda oranlar gizli; tabloyu sola kaydırarak veya ekranı döndürerek tüm sütunları görebilirsin.</p>`;
  }

  function teamBlock(t, side) {
    if (!t.n_total) return `<div class="teambox"><h4>${esc(t.team)}</h4><p class="note">Veritabanında bu takımın maçı yok (havuzdaki 38 lig dışında oynuyor olabilir).</p></div>`;
    if (!t.n_similar) return `<div class="teambox"><h4>${esc(t.team)}</h4><p class="note">Havuzda ${t.n_total} maçı var ama hiçbirinde bugünkü gibi (${side} olarak ~${pct(t.p_today)}) fiyatlanmamış.</p></div>`;
    const conf = t.n_similar < 30 ? "çok az örnek, sadece fikir verir" : t.n_similar < 100 ? "az örnek" : "yeterli örnek";
    return `<div class="teambox"><h4>${esc(t.team)}</h4>
      <p class="sentence">Bugün ${side} olarak kazanma ihtimali <b>${pct(t.p_today)}</b>. ${t.first_season.slice(0, 2)}/${t.first_season.slice(2)} sezonundan beri oynadığı ${t.n_total} maçın <b>${t.n_similar}</b>'inde benzer fiyatlanmış (±${t.tolerance_pp} puan). O maçlarda: <b>${pct(t.win_pct)} galibiyet</b>, ${pct(t.draw_pct)} beraberlik, ${pct(t.loss_pct)} mağlubiyet; ortalama ${num(t.avg_goals)} gol.
      <span class="muted">Galibiyet için %95 aralık ${pct(t.ci[0])}–${pct(t.ci[1])} — ${conf}.</span></p>
      ${teamRows(t.rows)}${t.n_similar > t.rows.length ? `<p class="note">Son ${t.rows.length} maç gösteriliyor.</p>` : ""}</div>`;
  }

  async function loadTeams(m, root) {
    const box = root.querySelector("[data-teams]");
    if (!box) return;
    try {
      const d = m._teams !== undefined ? m._teams : await api(`/api/teams/${m.stamp || state.date}/${m.id}`);
      m._teams = d;   // reopening the panel (a pick re-renders the list) must not hit the API again
      if (!d) { box.innerHTML = `<p class="note">Bu maçın takımları veritabanımızda bulunamadı (nesine yazımı eşleşmedi ya da lig kapsam dışı).</p>`; return; }
      const h = d.h2h;
      const h2h = h.n
        ? `<div class="teambox"><h4>${esc(m.home)} – ${esc(m.away)} karşılaşmaları</h4>
           <p class="sentence">Havuzda <b>${h.n}</b> karşılaşma var${h.shown < h.n ? ` (son ${h.shown} tanesi listede)` : ""}: ${esc(m.home)} ${h.home_wins} galibiyet, ${h.draws} beraberlik, ${esc(m.away)} ${h.away_wins} galibiyet.</p>
           ${teamRows(h.rows)}</div>`
        : `<div class="teambox"><h4>${esc(m.home)} – ${esc(m.away)} karşılaşmaları</h4><p class="note">Havuzda (2011'den beri, 38 lig) bu iki takım birbiriyle oynamamış.</p></div>`;
      box.innerHTML = `<p class="note">Bu bölüm sadece bu iki takıma bakar; oran benzerliğiyle ilgisi yoktur. Az sayıda maça dayanır, o yüzden yüzdeler kaba fikir verir.</p>${h2h}${teamBlock(d.home, "ev sahibi")}${teamBlock(d.away, "deplasman")}`;
    } catch (e) { box.innerHTML = `<p class="note">Takım geçmişi yüklenemedi: ${esc(e.message)}</p>`; }
  }

  async function loadAnalogues(m, k, root) {
    const box = root.querySelector("[data-analogues]");
    if (!box) return;
    try {
      const data = m._analogues && m._analogueK === k ? m._analogues
        : m.nesine_code ? (await api(`/api/nesine-analiz?code=${m.nesine_code}&k=${k}`)).analogues
        : await api(`/api/analogues/${m.stamp || state.date}/${m.id}?k=${k}`);
      m._analogues = data; m._analogueK = k;
      if (!data.rows.length) { box.textContent = "Benzer maç listesi bulunamadı."; return; }
      const RES = { H: "Ev", D: "Ber.", A: "Dep." };
      const same = data.same_team_count || 0;
      const sameNote = same
        ? `<p class="note">Bu listede ${m.home} veya ${m.away}'nın kendi maçlarından <b>${same} tane</b> var (işaretli satırlar). Benzerlik yalnızca oran profiline bakar; takım adı hesaba girmez, bu maçlar tesadüfen buradadır.</p>`
        : `<p class="note">Listede ${m.home} veya ${m.away}'nın kendi maçı yok. Benzerlik yalnızca oran profiline bakar; takım adı hesaba girmez.</p>`;
      box.innerHTML = `<p class="note">Gösterilen ${data.rows.length} maçta: ev sahibi %${data.share.h.toFixed(0)} · beraberlik %${data.share.d.toFixed(0)} · deplasman %${data.share.a.toFixed(0)}</p>${sameNote}
        <div class="table-wrap"><table><thead><tr><th>Tarih</th><th class="hide-sm">Lig</th><th>Maç</th><th class="num hide-sm">1 / X / 2</th><th class="num hide-sm">Benzerlik</th><th class="num">İY</th><th class="num">MS</th><th>İY/MS</th><th>2,5</th><th>KG</th></tr></thead><tbody>
        ${data.rows.map((r) => `<tr class="${r.same_team ? "same-team" : ""}"><td class="num">${fmtShort(r.date)}</td><td class="hide-sm">${esc(r.league_name)}</td><td class="wrap">${r.same_team ? "★ " : ""}${esc(r.home)} – ${esc(r.away)}</td><td class="num hide-sm">${r.odds.map((o) => num(o)).join(" / ")}</td><td class="num hide-sm">${pct(r.sim, 1)}</td><td class="num">${esc(r.ht_score || "–")}</td><td class="num res-${r.result}">${esc(r.score)}</td><td class="num"><b>${esc(r.htft || "–")}</b></td><td>${r.over25 ? "Üst" : "Alt"}</td><td>${r.btts ? "Var" : "Yok"}</td></tr>`).join("")}
        </tbody></table></div><p class="table-hint">Telefonda lig, oranlar ve benzerlik sütunları gizli; ekranı döndürünce hepsi görünür. İY = ilk yarı skoru, MS = maç sonu skoru.</p>`;
    } catch (e) { box.textContent = "Liste yüklenemedi: " + e.message; }
  }

  function closeSheet() { $("#sheet").hidden = true; $("#sheet-backdrop").hidden = true; document.body.style.overflow = ""; }

  // ------------------------------------------------------------------ glossary
  const GLOSSARY = [
    ["Oran (1 / X / 2)", "Bahis şirketinin fiyatı. 1 = ev sahibi kazanır, X = beraberlik, 2 = deplasman kazanır. Oran ne kadar düşükse şirket o sonucu o kadar olası görüyor."],
    ["Piyasanın beklentisi", "Oranlardan hesaplanan ihtimal: 1/oran alınır, şirketin kâr payı (marj) çıkarılır, üçünün toplamı %100 yapılır. Birçok şirketin ortalaması kullanılır."],
    ["Benzer maçlar", "2011'den bugüne 38 ligden 179 bin maç arasında piyasa ihtimalleri bu maça en yakın K maç (K körleme testte seçilir; şu an sayfanın başındaki sayı). Yalnızca analiz gününden önce oynanmış maçlar kullanılır."],
    ["Benzerlik %", "İki maçın ihtimal profilleri arasındaki yakınlık. %98 benzerlik, ihtimallerin toplam 2 puan farklı olduğu anlamına gelir. %95'in altı zayıf benzerliktir."],
    ["Geçmiş (ham)", "Benzer maçlarda o sonucun gerçekleşme yüzdesi. 100 maçın 58'inde ev sahibi kazandıysa %58."],
    ["Geçmiş (düzeltilmiş)", "Ham yüzde, az örneklemin abartmasını önlemek için piyasaya doğru biraz çekilir. Kartlarda ve sapmada bu değer kullanılır."],
    ["Sapma (puan)", "Düzeltilmiş geçmiş yüzdesi eksi piyasa yüzdesi. +3 puan: bu sonuç geçmişte piyasanın beklediğinden 3 puan daha sık gerçekleşmiş. Sapma, kârlı bahis demek değildir."],
    ["%95 güven aralığı", "Geçmiş yüzdesinin gerçek değerinin büyük ihtimalle içinde olduğu aralık. Piyasa bu aralığın içindeyse fark şans eseri olabilir; dışındaysa fark anlamlıdır."],
    ["Güven (örnek sayısı)", "Kaç benzer maç bulunduğuna göre: 250 ve üzeri Yüksek, 100–249 Orta, 30–99 Düşük, 30 altı Çok düşük."],
    ["Sinyal", "Kural tabanlı özet. Belirgin sapma: fark 5 puan ve üzeri, anlamlı, benzerlik yüksek ve sistem körleme testte piyasayı yenmiş olmalı (yenmediği için şu an verilmez). Orta düzey: fark 3 puan ve üzeri, anlamlı. Sapma yok: gerisi. Yetersiz örnek: 100'den az benzer maç."],
    ["Adil oran", "1 / düzeltilmiş geçmiş ihtimal; geçmişe göre 'olması gereken' oran. Marj ve belirsizlik dahil değildir."],
    ["2,5 üstü / altı", "Maçta toplam 3 ve daha fazla gol (üst) ya da 2 ve daha az gol (alt). Benzer maçlarda üst oranı gösterilir."],
    ["İki takım da gol attı (KG)", "Benzer maçların yüzde kaçında her iki takım da en az bir gol attı."],
    ["İY/MS (ilk yarı / maç sonu)", "Benzer maçlarda ilk yarı ve maç sonu sonuçlarının birlikte dağılımı. 1 = ev sahibi, X = beraberlik, 2 = deplasman; 1/1 ilk yarıyı da maçı da ev sahibi önde bitirdi, X/2 ilk yarı berabere, maçı deplasman kazandı demektir. Listedeki her benzer maçın ilk yarı skoru ve maç sonu skoru ayrı sütunlarda yazar."],
    ["Yarı yarı gol", "Benzer maçlarda ilk yarı ve ikinci yarı ayrı ayrı: ortalama gol, en az 1 gol (0,5 üst) ve en az 2 gol (1,5 üst) oranı, hangi yarıda daha çok gol atıldığı. Maç sonu 2,5 üstü ile aynı mantık, yalnızca yarıya bölünmüş. Yarılar için piyasa oranı kaynakta olmadığından karşılaştırma yapılmaz."],
    ["Aynı takımlar", "Detay panelindeki bu bölüm oran benzerliğinden bağımsızdır: iki takımın birbirine karşı geçmiş maçları ve her takımın bugünkü gibi fiyatlandığı (±5 puan) kendi maçlarında ne yaptığı. Az maça dayandığı için yüzdeler kaba fikir verir; güven aralığı yanında yazar."],
    ["Özet: favori tuttu", "Oynanan maçlarda tarafın (piyasa ya da geçmiş) en yüksek ihtimal verdiği sonuç geldi mi? Gol başlıklarında %50 ve üzeri 'üst' seçimi sayılır. İki taraf çoğu maçta aynı favoriyi seçtiği için isabet sayıları birbirine yakındır."],
    ["Özet: gerçeğe daha yakın", "Gelen sonuca hangi taraf daha yüksek ihtimal vermişti? Aynı favoriyi seçmiş olsalar bile derece farkını ölçer. Fark 1 puandan azsa 'eşit'. Geçmiş, piyasaya doğru çekilmiş (düzeltilmiş) ihtimali kullandığı için farklar çoğunlukla 1–4 puandır."],
    ["Özet: beklenen / gerçekleşen üst", "Tarafın verdiği üst ihtimallerinin ortalaması ile gerçekten üst biten maçların oranı. Yakınsa taraf iyi ayarlıdır; tek tek isabetten daha sağlam bir ölçüdür."],
    ["Körleme test","Sistem 2017–2021 sezonlarında ayarlandı, 2021–2026 sezonlarında hiç görmediği maçlarda denendi; bir maçı analiz ederken yalnızca ondan önce oynanmış maçları görebilir. Sonuç: piyasadan daha iyi tahmin edemedi."],
    ["Pattern Lab", "Araştırma sekmesinin üstündeki araç. Dört mod: bir maç seç (araştırılabilir durumları sistem bulur), bir sonuç seç (günün maçları taranır), kendi koşullarını kur (koşul koşul geçmiş), bir takım seç (fikstür döngüleri). Motor, pencere ya da araştırma türü seçtirmez."],
    ["Araştırılabilir durum", "Pattern Lab'ın bir maçta bulduğu şey. 'Sinyal' değildir: bir motorun ölçümü, aynı maçın bütün ölçümleri arasında çoklu test düzeltmesinden geçtikten sonra da sıfırı dışlıyorsa araştırılabilir durum sayılır. Döngü ve oran hareketi bağlamdır, ölçüm değil."],
    ["Pattern benzerliği", "Maçın geçmiş koşullara (fiyat, güç, form, gol) ne kadar benzediği; 0–100. Sonucun gerçekleşme olasılığı DEĞİLDİR: %83 benzerlik, hedefin %83 ihtimalle olacağı anlamına gelmez. Ekranda olasılıklardan ayrı bir kartta durur."],
    ["Pattern tahmini", "Bugünkü piyasa olasılığı + katmanların (takım, rakip, benzer durumlar, ikizler, döngü) fiyata göre farklarının hassasiyet ağırlıklı ortalaması. Katmanlar örtüştüğü için aralığı iyimserdir; piyasa yoksa katmanların gerçekleşme oranıdır ve kıyas 'benzer fiyatlı maçlar'dır."],
    ["Kanıt seviyesi", "KEŞİF: havuzda sıfırı dışlıyor, o kadar. DOĞRULANDI: doğrulama penceresinde aynı işaretle tekrarladı. İLERİ TESTTE: dokunulmamış test penceresinde de tuttu. YETERSİZ VERİ: 200 maçın altı. FARK YOK: fiyattan ayrılmıyor. Eğitimde bulunan hiçbir şey 'doğrulandı' diye gösterilmez."],
    ["Fikstür döngüsü", "Bir takımın bir merkez maç etrafındaki rakip dizisinin (±2/±3/±4) geçmiş bir sezonda aynı sırayla, ters sırayla, kaymış olarak ya da benzer güç profiliyle tekrarlaması. Bir benzerliktir; 'geçmişte işe yaramış mı' sorusu bütün veritabanındaki döngü çiftleri üzerinde, piyasa fiyatının yanında ayrıca ölçülür."],
    ["Ayna hipotezi", "Fikstür sırası tersine döndüyse merkez maçın sonucu da tersine (1 ↔ 2) dönüyor mu? Grafiklerin iması; doğru kabul edilmez, her ters döngü çiftinde yeni merkez maçın sonucu ve o sonucun fiyatı üzerinden test edilir."],
    ["Kalibrasyon skoru (Brier)", "Tahmin kalitesi ölçüsü; düşük daha iyi. Piyasa 0.5899, sistem 0.5897: fark yok denecek kadar küçük ve istatistiksel olarak anlamsız."],
  ];

  function renderGlossary() {
    $("#glossary").innerHTML = GLOSSARY.map(([t, d]) => `<div><dt>${t}</dt><dd>${d}</dd></div>`).join("");
  }

  // ================================================================== PATTERN LAB
  // The orchestration UI. Four modes over the engines that already exist: the reader picks a match,
  // a result, their own conditions, or a club — never an engine, never a window, never "exact or
  // ±2". Every number is drawn next to the market's expectation, similarity never wears the label
  // of a probability, and nothing found in the pool alone is called "doğrulandı".
  const EX_OUT = { win: "Kazanır", draw: "Berabere", loss: "Kaybeder", over25: "2,5 üst", btts: "KG var",
                   over15: "1,5 üst", over35: "3,5 üst", ht_draw: "İY berabere", ht_win: "İY önde" };
  const leagueName = (code) => (state.meta?.leagues || {})[code] || code;
  state.lab = { inited: false, mode: null, targets: null, day: null, dayList: [], picked: null, scan: null,
                target: null, find: { target: null, timer: null }, cycle: { team: null, data: null } };

  const EV_CLS = { "YETERSİZ VERİ": "thin", "KEŞİF": "disc", "DOĞRULANDI": "conf", "İLERİ TESTTE": "test", "FARK YOK": "none" };
  const evBadge = (tr) => `<span class="ev ev-${EV_CLS[tr] || "none"}">${esc(tr || "–")}</span>`;
  const pctv = (v, d = 1) => (v == null ? "–" : `%${Number(v).toFixed(d)}`);
  const ppv = (v) => (v == null ? "–" : `${v > 0 ? "+" : ""}${Number(v).toFixed(1)} puan`);
  const ciTxt = (ci) => (!ci || ci[0] == null ? "–" : `[${pp1(ci[0])}, ${pp1(ci[1])}]`);
  const SIM_TIP = "Pattern benzerliği maçın geçmiş koşullara ne kadar benzediğini gösterir. Sonucun gerçekleşme olasılığı değildir.";

  /** The question, restated at the top of the stage — the reader should see what they asked. */
  function labQ(html) { const q = $("#lab-qbar"); if (q) q.innerHTML = html || ""; }

  // ---- figures ------------------------------------------------------------------------------
  // Every interval in a table sits on that table's ONE scale: symmetric, in points, rounded to 5.
  function fpDomain(items) {
    let m = 5;
    items.forEach((it) => { if (it && it.ci && it.ci[0] != null) m = Math.max(m, Math.abs(it.ci[0]), Math.abs(it.ci[1]), Math.abs(it.edge || 0)); });
    return Math.min(60, Math.ceil(m / 5) * 5);
  }
  function fpCell(edge, ci, dom) {
    if (edge == null || !ci || ci[0] == null) return `<span class="muted">–</span>`;
    const W = 132, pad = 10, x = (v) => pad + (W - 2 * pad) * (Math.max(-dom, Math.min(dom, v)) + dom) / (2 * dom);
    const clear = ci[0] > 0 || ci[1] < 0;
    return `<svg class="fp ${clear ? "clear" : ""} ${edge < 0 ? "neg" : ""}" viewBox="0 0 ${W} 18" role="img"
        aria-label="${pp1(edge)} puan, aralık ${pp1(ci[0])} ile ${pp1(ci[1])}, sıfırı ${clear ? "dışlıyor" : "içeriyor"}">
      <line class="zero" x1="${x(0).toFixed(1)}" y1="1" x2="${x(0).toFixed(1)}" y2="17"/>
      <line class="rng" x1="${x(ci[0]).toFixed(1)}" y1="9" x2="${x(ci[1]).toFixed(1)}" y2="9"/>
      <circle class="pt" cx="${x(edge).toFixed(1)}" cy="9" r="4"/></svg>`;
  }
  function fpAxis(dom) {
    const W = 132, pad = 10, x = (v) => pad + (W - 2 * pad) * (v + dom) / (2 * dom);
    return `<svg class="fp-axis" viewBox="0 0 ${W} 14" aria-hidden="true">
      <line x1="${x(-dom)}" y1="3" x2="${x(dom)}" y2="3"/>
      <text x="${x(-dom)}" y="13" text-anchor="start">−${dom}</text><text x="${x(0)}" y="13" text-anchor="middle">0</text><text x="${x(dom)}" y="13" text-anchor="end">+${dom}</text></svg>`;
  }
  /** Market vs pattern on one % axis: two dots, the pattern's interval as a band, a legend. */
  function dumbbell(market, est) {
    const vals = [market, est?.p, est?.ci?.[0], est?.ci?.[1]].filter((v) => v != null);
    if (!vals.length) return "";
    const hi = Math.min(100, Math.ceil(Math.max(...vals) * 1.25 / 5) * 5 || 5);
    const W = 300, pad = 12, x = (v) => pad + (W - 2 * pad) * Math.max(0, Math.min(hi, v)) / hi;
    const band = est?.ci?.[0] != null ? `<line class="band" x1="${x(est.ci[0]).toFixed(1)}" y1="30" x2="${x(est.ci[1]).toFixed(1)}" y2="30"/>` : "";
    const link = market != null && est?.p != null ? `<line class="link" x1="${x(market).toFixed(1)}" y1="30" x2="${x(est.p).toFixed(1)}" y2="30"/>` : "";
    const lbl = (v, cls, dy) => v == null ? "" : `<text x="${x(v).toFixed(1)}" y="${dy}" text-anchor="middle">${pctv(v)}</text>`;
    const apart = market != null && est?.p != null && Math.abs(x(market) - x(est.p)) < 34;
    return `<div class="dumb"><svg viewBox="0 0 ${W} 58" preserveAspectRatio="none" role="img" aria-label="piyasa ${pctv(market)} ile pattern tahmini ${est ? pctv(est.p) : "yok"} aynı yüzde ekseninde">
      <line class="axis" x1="${pad}" y1="30" x2="${W - pad}" y2="30"/>
      <text class="tick" x="${pad}" y="52" text-anchor="start">%0</text><text class="tick" x="${W - pad}" y="52" text-anchor="end">%${hi}</text>
      ${band}${link}
      ${market != null ? `<circle class="pt m" cx="${x(market).toFixed(1)}" cy="30" r="5"/>` : ""}
      ${est?.p != null ? `<circle class="pt p" cx="${x(est.p).toFixed(1)}" cy="30" r="5"/>` : ""}
      ${lbl(market, "m", apart ? 12 : 18)}${lbl(est?.p, "p", apart && market != null ? 22 : 18)}</svg>
      <div class="legend-row"><span><i class="lm"></i>piyasa</span><span><i class="lp"></i>pattern tahmini (bant: %95 aralık)</span></div></div>`;
  }
  /** Similarity: a hatched meter, deliberately unlike a probability bar. */
  function meter(sim) {
    if (sim == null) return `<p class="note">ikiz benzerliği ölçülemedi</p>`;
    return `<div class="meter" title="${esc(SIM_TIP)}"><div class="meter-track"><div class="meter-fill" style="width:${Math.max(0, Math.min(100, sim))}%"></div></div>
      <div class="meter-lbl"><span>benzerlik — olasılık değil</span><span>%${Number(sim).toFixed(0)}</span></div></div>`;
  }
  /** N as a thin magnitude bar on a shared max. */
  function nbar(n, max, thin) { return `<span class="nbar ${thin ? "thin" : ""}"><i style="width:${Math.max(2, 60 * (n || 0) / Math.max(max, 1)).toFixed(0)}px"></i>${(n || 0).toLocaleString("tr")}</span>`; }
  /** The two runs aligned by offset from the centre, identical clubs joined — a reversal reads as an X. */
  function mirror(cyc) {
    const w = cyc.window, n = 2 * w + 1;
    const place = (run) => { const s = new Array(n).fill(null); run.opponents.forEach((o, i) => { const off = i - run.centre; if (off >= -w && off <= w) s[off + w] = o; }); return s; };
    const past = place(cyc.past), now = place(cyc.now);
    const cell = (s, i, other) => `<div class="mirror-cell ${i === w ? "is-c" : ""}">${s[i] ? `<span class="chip-o ${other.includes(s[i]) && i !== w ? "same" : ""}">${esc(s[i])}</span>` : `<span class="muted">·</span>`}</div>`;
    const links = [];
    past.forEach((o, i) => { if (!o) return; const j = now.indexOf(o); if (j >= 0) links.push(`<line class="${i === w && j === w ? "c" : ""}" x1="${(100 * (i + 0.5) / n).toFixed(2)}" y1="0" x2="${(100 * (j + 0.5) / n).toFixed(2)}" y2="100"/>`); });
    const cols = `grid-template-columns: 52px repeat(${n}, minmax(64px, 1fr))`;
    const offs = Array.from({ length: n }, (_, i) => `<div class="mirror-off">${i - w > 0 ? "+" : ""}${i - w}</div>`).join("");
    return `<div class="mirror"><div class="mirror-grid" style="${cols}">
      <div class="mirror-lbl">${cyc.past.season.slice(0, 2)}/${cyc.past.season.slice(2)}</div>${past.map((_, i) => cell(past, i, now)).join("")}
      <div></div><svg class="mirror-links" style="grid-column: 2 / -1" viewBox="0 0 100 100" preserveAspectRatio="none" aria-hidden="true">${links.join("")}</svg>
      <div class="mirror-lbl">${cyc.now.season.slice(0, 2)}/${cyc.now.season.slice(2)}</div>${now.map((_, i) => cell(now, i, past)).join("")}
      <div></div>${offs}</div>
      <p class="note">Sütunlar merkez maça uzaklık (−${w} … +${w}); çizgiler aynı kulübü iki sezonda birleştirir. Düz çizgiler aynı sıra, çapraz çizgiler ters sıra demektir. Kalın kenarlı rakip diğer dizide de var.</p></div>`;
  }

  async function labInit() {
    if (state.lab.inited) return;
    state.lab.inited = true;
    document.querySelectorAll("[data-lab]").forEach((b) => (b.onclick = () => labShow(b.dataset.lab)));
    try { state.lab.targets = await api("/api/lab/hedefler"); } catch (e) { state.lab.targets = { groups: [] }; }
    lmInit(); lfInit(); exWire(); lcInit();
    let want = "match";
    try { want = localStorage.getItem("fo.labMode") || "match"; } catch (_) {}
    labShow(want);
  }


  const LAB_Q = { match: "Bir maç seç. Sistem form, güç, gol, ikiz, fikstür döngüsü ve oran hareketini tarar; sen yalnızca sonucu okursun.",
                  find: "Bir sonuç seç. Günün maçlarında o sonucun geçmişte fiyattan ne kadar ayrıldığı taranır.",
                  own: "Koşullarını kur. Her koşul bir satır olarak eklenir; sayıyı hangisinin oynattığını görürsün.",
                  cycle: "Bir takım seç. Fikstür döngülerini sistem bulur; döngünün bir anlamı olup olmadığı ayrıca ölçülür." };
  function labShow(mode) {
    state.lab.mode = mode;
    document.querySelectorAll("[data-lab]").forEach((b) => { b.classList.toggle("is-on", b.dataset.lab === mode); b.setAttribute("aria-selected", b.dataset.lab === mode ? "true" : "false"); });
    ["match", "find", "own", "cycle"].forEach((k) => { const p = $(`#lab-${k}`); if (p) p.hidden = k !== mode; });
    if (mode === "match" && state.lab.picked) labQ(`<b>${esc(state.lab.picked.home)} – ${esc(state.lab.picked.away)}</b> maçında ne olur?`);
    else if (mode === "own") labQ(exSentence());
    else if (mode === "cycle" && state.lab.cycle.team) labQ(`<b>${esc(state.lab.cycle.team)}</b> fikstürü geçmiş bir sezonu tekrarlıyor mu?`);
    else labQ(LAB_Q[mode]);
    try { localStorage.setItem("fo.labMode", mode); } catch (_) {}
  }

  function tpBuild(root, onPick) {
    const groups = state.lab.targets?.groups || [];
    const st = { group: groups[0]?.key, key: null };
    const paint = () => {
      const g = groups.find((x) => x.key === st.group) || groups[0];
      root.innerHTML = `<div class="kseg tp-groups">${groups.map((x) =>
          `<button type="button" data-g="${x.key}" class="${x.key === st.group ? "is-on" : ""}">${esc(x.label)}</button>`).join("")}</div>
        <div class="tp-targets">${(g?.targets || []).map((t) =>
          `<button type="button" data-t="${esc(t.key)}" class="tp-t ${t.key === st.key ? "is-on" : ""}" title="${esc(t.explain)}">${esc(t.label)}</button>`).join("")}</div>
        <p class="tp-explain">${st.key ? esc((g.targets.find((t) => t.key === st.key) || {}).explain || "") : "<span class=\"muted\">bir sonuç seç</span>"}</p>`;
      root.querySelectorAll("[data-g]").forEach((b) => (b.onclick = () => { st.group = b.dataset.g; paint(); }));
      root.querySelectorAll("[data-t]").forEach((b) => (b.onclick = () => { st.key = b.dataset.t; paint(); onPick(st.key); }));
    };
    paint();
    return { set(key) { const g = groups.find((x) => x.targets.some((t) => t.key === key)); if (g) { st.group = g.key; st.key = key; paint(); } },
             get key() { return st.key; } };
  }

  function labDates(sel, onChange) {
    // the same window the Maçlar tab offers: the last week (played — analysed as of their own day),
    // today, and the next six days. Football-Data lists a fixture only once its odds are out, so
    // days past the coming round are usually empty until Tuesday/Wednesday; the option says so.
    const today = state.meta?.today || isoDay(new Date());
    const has = new Set(state.meta?.dates || []);
    sel.innerHTML = "";
    for (let i = -7; i < 7; i++) {
      const d = new Date(today + "T12:00:00"); d.setDate(d.getDate() + i); const s = isoDay(d);
      const o = el("option"); o.value = s;
      const tag = i === 0 ? " · bugün" : i < 0 ? " · oynandı" : "";
      o.textContent = fmtDate(s) + tag + (has.has(s) ? "" : i < 0 ? " · analiz yok" : " · henüz maç yok");
      sel.appendChild(o);
    }
    sel.value = today;
    sel.onchange = () => onChange(sel.value);
  }

  // ---------------------------------------------------------------- MOD 1 — bu maçta ne olur?
  function lmInit() {
    labDates($("#lm-date"), lmLoad);
    $("#lm-q").oninput = lmList;
    $("#lm-go").onclick = lmScan;
    lmLoad($("#lm-date").value);
  }

  async function lmLoad(date) {
    state.lab.picked = null; $("#lm-picked").hidden = true; $("#lm-scan").innerHTML = ""; $("#lm-target").hidden = true;
    $("#lm-list").innerHTML = `<p class="note">Yükleniyor…</p>`;
    // two sources: the analysed fixtures (full payload, opens the match sheet as-is) and the nesine
    // bulletin's matches that got a state row (a week ahead, every league nesine prices)
    let day = { matches: [] }, lab = { matches: [] };
    try { day = await api(`/api/day/${date}`); } catch (_) {}
    try { lab = await api(`/api/lab/maclar?from=${date}&to=${date}`); } catch (_) {}
    if ($("#lm-date").value !== date) return;
    const payload = new Map(day.matches.map((m) => [m.id, m]));
    state.lab.day = day;
    state.lab.dayList = lab.matches.map((m) => ({ ...m, _ready: m.ready !== false, _m: payload.get(m.id) || null,
      odds: { h: m.odds?.[0], d: m.odds?.[1], a: m.odds?.[2] } }));
    state.lab.leagues = new Set(state.lab.dayList.map((m) => m.league));
    const wrap = $("#lm-leagues"); wrap.innerHTML = "";
    const leagues = [...new Map(state.lab.dayList.map((m) => [m.league, m.league_name])).entries()].sort((a, b) => a[1].localeCompare(b[1], "tr"));
    const all = el("button", "chip is-on", "Tümü"); all.type = "button";
    all.onclick = () => { state.lab.leagues = new Set(leagues.map((l) => l[0])); wrap.querySelectorAll(".chip").forEach((c, i) => c.classList.toggle("is-on", i === 0)); lmList(); };
    wrap.appendChild(all);
    leagues.forEach(([code, name]) => {
      const b = el("button", "chip", esc(name)); b.type = "button";
      b.onclick = () => { state.lab.leagues = new Set([code]); wrap.querySelectorAll(".chip").forEach((c) => c.classList.toggle("is-on", c === b)); lmList(); };
      wrap.appendChild(b);
    });
    lmList();
  }

  function lmList() {
    const q = ($("#lm-q").value || "").trim().toLocaleLowerCase("tr");
    const ms = state.lab.dayList.filter((m) => state.lab.leagues.has(m.league) && (!q || `${m.home} ${m.away}`.toLocaleLowerCase("tr").includes(q)));
    const box = $("#lm-list");
    if (!state.lab.dayList.length) {
      const today = state.meta?.today || "";
      box.innerHTML = `<div class="day-empty">${$("#lm-date").value < today ? "Bu gün için kayıtlı analiz yok."
        : "Bu gün için henüz analiz edilmiş maç yok. Football-Data bir maçı ancak oranı yayınlanınca fikstüre ekler; hafta sonu maçları genellikle <b>Salı–Çarşamba</b> gelir ve sabah güncellemesinden sonra burada görünür. Geçen haftanın oynanmış maçlarını da seçebilirsin — analiz o günün bilgisiyle yapılır."}</div>`;
      return;
    }
    if (!ms.length) { box.innerHTML = `<p class="note">Filtreye uyan maç yok.</p>`; return; }
    const nNes = ms.filter((m) => m.source === "nesine").length;
    box.innerHTML = (nNes ? `<p class="note">${ms.length} maç; ${nNes} tanesi yalnızca nesine bülteninden (fiyatı nesine'nin, marj çıkarılmış; Maçlar sekmesindeki analiz yok, Pattern Lab motorları çalışır).</p>` : "")
      + ms.slice(0, 200).map((m) => `<button type="button" class="lab-row${m._ready ? "" : " is-na"}" data-pick="${esc(m.id)}" ${m._ready ? "" : 'title="Bu maç için durum tablosu henüz hazır değil (günlük iş)"'}>
        <span class="lab-row-main"><b>${esc(m.home)} – ${esc(m.away)}</b><small class="muted">${esc(m.league_name)}${m.time ? " · " + esc(m.time) : ""}${m.source === "nesine" ? ' · <span class="ev ev-ctx">nesine</span>' : ""}</small></span>
        <span class="num muted">${num(m.odds.h)} / ${num(m.odds.d)} / ${num(m.odds.a)}</span></button>`).join("");
    box.querySelectorAll("[data-pick]").forEach((b) => (b.onclick = () => lmPick(b.dataset.pick)));
  }


  function lmPick(id, opts = {}) {
    const m = state.lab.dayList.find((x) => x.id === id);
    if (!m) return;
    state.lab.picked = m; state.lab.scan = null; state.lab.target = null;
    $("#lm-list").querySelectorAll("[data-pick]").forEach((b) => b.classList.toggle("is-on", b.dataset.pick === id));
    $("#lm-picked").hidden = false;
    $("#lm-title").textContent = `${m.home} – ${m.away}`;
    $("#lm-sub").textContent = ` ${m.league_name}${m.time ? " · " + m.time : ""} · ${fmtDate(m.date)} · oran ${num(m.odds.h)} / ${num(m.odds.d)} / ${num(m.odds.a)}`;
    $("#lm-scan").innerHTML = ""; $("#lm-target").hidden = true; $("#lm-out").innerHTML = "";
    labQ(`<b>${esc(m.home)} – ${esc(m.away)}</b> maçında ne olur?`);
    if (!opts.quiet) $("#lm-picked").scrollIntoView({ behavior: "smooth", block: "nearest" });
  }

  const SCAN_ANCHOR = { pattern_all: "patterns", pattern_similar: "patterns", pattern_same_team: "patterns", twins: "twins",
                        combined: "combo", sequence: "fixture", movement: "move" };

  async function lmScan() {
    const m = state.lab.picked; if (!m) return;
    const box = $("#lm-scan"); const btn = $("#lm-go");
    btn.disabled = true; btn.textContent = "Taranıyor… (her motor çalışıyor)";
    box.innerHTML = `<p class="note">Form, güç, gol, ikiz, fikstür döngüsü ve oran hareketi motorları çalışıyor…</p>`;
    try {
      const d = await api(`/api/tarama/${encodeURIComponent(m.id)}`);
      state.lab.scan = d;
      renderScan(d, m);
      $("#lm-target").hidden = false;
      if (!state.lab.tp) state.lab.tp = tpBuild($("#lm-tp"), (key) => lmTarget(key));
      if (state.lab.pendingTarget) { const k = state.lab.pendingTarget; state.lab.pendingTarget = null; state.lab.tp.set(k); lmTarget(k); }
    } catch (e) {
      const msg = String(e.message || "");
      box.innerHTML = `<p class="note">${msg.startsWith("404") ? "Bu maç için durum tablosu hazır değil; günlük güncellemeden sonra görünür." : "Tarama yapılamadı: " + esc(msg)}</p>`;
    }
    btn.disabled = false; btn.textContent = "BU MAÇI ANALİZ ET";
  }


  /** What a finding means in this match's terms. Every measurement is taken from one side's state
      (the home side unless the scan says otherwise). The direction is the headline, not a sign to
      decode: "Nijmegen galibiyeti — beklenenden seyrek", never a bare "Kaybeder" with a minus somewhere. */
  function findingMeaning(f, m, side) {
    const team = side === "away" ? m.away : m.home, other = side === "away" ? m.home : m.away;
    const who = { win: `${team} galibiyeti`, loss: `${other} galibiyeti`, draw: "Beraberlik", over25: "3 ve üzeri gol", over15: "2 ve üzeri gol",
                  over35: "4 ve üzeri gol", btts: "Karşılıklı gol", ht_draw: "İlk yarı beraberlik", ht_win: `${team} ilk yarıda önde` }[f.outcome] || f.outcome_tr;
    const less = f.edge < 0;
    const dir = less ? "beklenenden seyrek" : "beklenenden sık";
    const sentence = `${team} bu durumdayken${f.detail ? ` (${f.detail})` : ""} geçmişteki ${f.n} maçta bu sonuç <b>${pctv(f.actual)}</b> gelmiş;
      piyasa <b>${pctv(f.market)}</b> bekliyordu. Yani "${who}" bu durumda piyasanın sandığından <b>${less ? "daha az" : "daha çok"}</b> olmuş
      — oranı ${less ? "pahalı" : "ucuz"} kalmış. Bu, kim kazanır demek değildir.`;
    return { who, dir, less, sentence, team };
  }

  function findingCard(f, m, side = "home") {
    const solid = f.ci && f.ci[0] != null && (f.ci[0] > 0 || f.ci[1] < 0);
    const mean = findingMeaning(f, m, side);
    return `<div class="lab-card">
      <div class="lab-card-top"><span>${esc(f.source_tr)}</span>${evBadge(f.evidence_tr)}</div>
      <div class="lab-card-body"><span class="lab-big">${esc(mean.who)}</span>
        <span class="lab-dir ${mean.less ? "is-less" : "is-more"}">${mean.less ? "↓" : "↑"} ${mean.dir}</span>
        <span>geçmişte <b>${pctv(f.actual)}</b> · piyasa <b>${pctv(f.market)}</b> <small class="muted">N = ${f.n}</small></span>
        <span class="${solid ? "yes" : ""}">Δ <b>${ppv(f.edge)}</b> <small class="muted">${ciTxt(f.ci)} · q=${num(f.q, 3)}</small></span>
        <small class="muted">${mean.sentence}</small></div>
      <button type="button" class="btn ghost" data-open="${esc(SCAN_ANCHOR[f.source] || "twins")}">İncele</button></div>`;
  }


  function contextCard(c, m) {
    const go = c.source === "sequence"
      ? `<button type="button" class="btn ghost" data-cycle="${esc(c.data?.now?.match_id || m.id)}">Döngüyü aç</button>`
      : c.source === "note" ? `<button type="button" class="btn ghost" data-open="nesine">Notları aç</button>`
      : `<button type="button" class="btn ghost" data-open="move">İncele</button>`;
    return `<div class="lab-card is-ctx">
      <div class="lab-card-top"><span>${esc(c.source_tr)}</span><span class="ev ev-ctx">BAĞLAM</span></div>
      <div class="lab-card-body"><span class="lab-big">${esc(c.label)}</span><span>${c.source === "sequence" ? "Benzerlik " : ""}<b>${esc(c.value)}</b></span>
        <small class="muted">${esc(c.note)}</small></div>${go}</div>`;
  }

  function renderScan(d, m) {
    const box = $("#lm-scan");
    const n = d.after_correction, ctx = (d.context || []).length;
    const verdict = `<div class="lab-verdict">${evBadge(n ? "KEŞİF" : "FARK YOK")}<p><b>${d.scanned} pattern tarandı, ${n + ctx} araştırılabilir durum bulundu.</b>
        ${d.too_thin} ölçüm 200 maçın altında kaldı; gerisi bu maçın tek ailesinde çoklu test düzeltmesinden geçti.
        ${n === 0 ? (ctx ? "Bulunanların hepsi bağlam — fiyattan ayrılan bir ölçüm yok; çoğu maçta doğru cevap budur." : "Bu maçta piyasadan ayrılan bir ölçüm yok; bu bir hata değil, çoğu maçta doğru cevap budur.") : "Bunlar sinyal değil, araştırılabilir durumdur: havuzda sıfırı dışlıyor, o kadar."}
        <small class="muted">Hiçbir kart kazananı söylemez. Her kart <b>${esc(d.match?.side === "away" ? m.away : m.home)}</b>'ın bugünkü durumundan bakar ve o durumdaki bir sonucun geçmişte fiyata göre daha sık mı, daha seyrek mi geldiğini ölçer.</small></p></div>`;
    const cards = (d.findings || []).map((f) => findingCard(f, m, d.match?.side)).join("") + (d.context || []).map((c) => contextCard(c, m)).join("");
    const near = (d.near_misses || []);
    const dom = fpDomain(near);
    box.innerHTML = verdict + `<div class="lab-cards">${cards || ""}</div>` + (near.length
      ? `<details class="ex-more"><summary>Eşiğe en çok yaklaşanlar <span class="muted">— gösterilmeyen ${near.length} ölçüm</span></summary>
         <div class="table-wrap"><table><thead><tr><th>Kaynak</th><th>Sonuç</th><th class="num">N</th><th class="num">Δ</th><th class="fp-h">${fpAxis(dom)}</th><th class="num">q</th></tr></thead><tbody>
         ${near.map((f) => `<tr class="thin"><td class="wrap">${esc(f.source_tr)}</td><td>${esc(f.outcome_tr)}</td><td class="num">${f.n}</td>
           <td class="num">${pp1(f.edge)}</td><td class="fp-td">${fpCell(f.edge, f.ci, dom)}</td><td class="num">${num(f.q, 3)}</td></tr>`).join("")}</tbody></table></div>
         <p class="note">q, Benjamini-Hochberg ile düzeltilmiş p değeri: bu maçın ${d.scanned} ölçümlük ailesinde ${d.alpha} eşiğini geçmedi.</p></details>` : "");
    box.querySelectorAll("[data-open]").forEach((b) => (b.onclick = () => openSheetAt(m, b.dataset.open)));
    box.querySelectorAll("[data-cycle]").forEach((b) => (b.onclick = () => { labShow("cycle"); lcRun(d.match.home, b.dataset.cycle); }));
  }

  async function openSheetAt(m, anchor) {
    let mm = m._m || m;
    if (!m._m && m.source === "nesine") {
      if (!m._sheet) {
        if (!m.code) { toast("Bu maçın nesine kodu yok."); return; }
        try {
          const d = await api(`/api/nesine-analiz?code=${m.code}&k=25`);
          mm = d.match; mm.id = m.id; mm.source = "nesine-state";       // the state row exists: every engine may run
          mm._analogues = d.analogues; mm._analogueK = 25; mm._teams = d.teams; mm._nesine = d.nesine;
          mm.league_name = m.league_name; m._sheet = mm;
        } catch (e) { toast("Maç açılamadı: " + e.message); return; }
      }
      mm = m._sheet;
    }
    openSheet(mm);
    const target = $("#sheet-body").querySelector(`[data-anchor="${anchor}"]`);
    if (target) setTimeout(() => target.scrollIntoView({ behavior: "smooth", block: "start" }), 60);
  }


  async function lmTarget(key) {
    const m = state.lab.picked; if (!m) return;
    const box = $("#lm-out");
    const t = (state.lab.targets?.groups || []).flatMap((g) => g.targets).find((x) => x.key === key) || { label: key };
    labQ(`<b>${esc(m.home)} – ${esc(m.away)}</b> maçı <b>${esc(t.label)}</b> olur mu? <span class="muted">— ${esc(t.explain || "")}</span>`);
    box.innerHTML = `<p class="note">Katmanlar bu sonuç için yeniden ölçülüyor…</p>`;
    try {
      const d = await api(`/api/lab/hedef/${encodeURIComponent(m.id)}?target=${encodeURIComponent(key)}`);
      state.lab.target = d;
      box.innerHTML = targetHTML(d, m);
      box.querySelectorAll("[data-open]").forEach((b) => (b.onclick = () => openSheetAt(m, b.dataset.open)));
      box.querySelectorAll("[data-cycle]").forEach((b) => (b.onclick = () => { labShow("cycle"); lcRun(d.match.home, b.dataset.cycle); }));
    } catch (e) { box.innerHTML = `<p class="note">Hesaplanamadı: ${esc(e.message)}</p>`; }
  }

  const REF_TR = { market: "piyasa", matched: "benzer fiyatlı maçlar" };


  function layerRows(layers, dom) {
    return layers.map((l) => `<tr class="${l.n < 200 ? "thin" : ""}"><td class="wrap">${esc(l.label)}${l.note ? `<br><small class="muted">${esc(l.note)}</small>` : ""}</td>
        <td class="num">${l.n || "–"}</td><td class="num">${pctv(l.actual)}</td>
        <td class="num">${pctv(l.expected)}${l.reference ? `<br><small class="muted">${REF_TR[l.reference]}</small>` : ""}</td>
        <td class="num ${l.ci && l.ci[0] != null && (l.ci[0] > 0 || l.ci[1] < 0) ? "yes" : ""}"><b>${l.edge == null ? "–" : pp1(l.edge)}</b><br><small class="muted">${ciTxt(l.ci)}</small></td>
        <td class="fp-td">${fpCell(l.edge, l.ci, dom)}</td><td>${evBadge(l.evidence_tr)}</td></tr>`).join("");
  }


  function targetHTML(d, m) {
    const t = d.target, mk = d.market, est = d.estimate, sim = d.similarity;
    const dci = d.difference_ci || [null, null];
    const clear = dci[0] != null && (dci[0] > 0 || dci[1] < 0);
    const sentence = mk.p == null
      ? `Bu market için bugün fiyat yok; katmanlar ${est ? `<b>${pctv(est.p)}</b> diyor, kıyas benzer fiyatlı maçlar` : "200 maça ulaşmıyor"}.`
      : est ? `Piyasa <b>${pctv(mk.p)}</b> bekliyor; katmanlar <b>${pctv(est.p)}</b> diyor — fark <b>${ppv(d.difference)}</b>, aralık ${ciTxt(dci)} ${clear ? "sıfırı dışlıyor" : "<b>sıfırı içeriyor</b>, yani fiyattan ayırt edilemiyor"}.`
        : `Piyasa <b>${pctv(mk.p)}</b> bekliyor; 200 maça ulaşan katman olmadığı için pattern tahmini yok.`;
    const verdict = `<div class="lab-verdict">${evBadge(d.evidence.label)}<p>${sentence} <span class="muted">${esc(d.evidence.why)}.</span></p></div>`;
    const fig = `<div class="lab-fig">
      <div class="lab-stat"><small>PİYASA OLASILIĞI</small><b class="is-market">${mk.p == null ? "yok" : pctv(mk.p)}</b>
        <span class="muted">${mk.p == null ? esc(mk.note || "") : mk.source === "nesine" ? `nesine oranı ${num(mk.odds)}, marj çıkarılmış` : mk.odds ? `konsensüs oranı ${num(mk.odds)}` : "Football-Data konsensüsü"}</span></div>
      <div class="lab-stat"><small>PATTERN TAHMİNİ</small><b class="is-pattern">${est ? pctv(est.p) : "–"}</b><span class="muted">${est ? esc(est.basis) : "200 maça ulaşan katman yok"}</span></div>
      <div class="lab-stat"><small>FARK</small><b class="${clear ? "yes" : ""}">${d.difference == null ? "–" : pp1(d.difference)}</b><span class="muted">puan · %95 aralık ${ciTxt(dci)}</span></div>
    </div>
    ${dumbbell(mk.p, est)}
    <div class="lab-sec">Pattern benzerliği <i class="tip" title="${esc(SIM_TIP)}" aria-hidden="true">?</i></div>${meter(sim?.median)}
    <p class="note">${sim ? `En yakın ${sim.k} ikizin ortanca benzerliği; ${sim.n_above_90} tanesi 90'ın üstünde. ` : ""}${esc(SIM_TIP)}</p>`;
    const dom = fpDomain(d.layers);
    const table = `<div class="lab-sec">Katmanlar</div>
      <div class="table-wrap"><table><thead><tr><th>Katman</th><th class="num">N</th><th class="num">Gerçekleşen</th><th class="num">Beklenti</th>
        <th class="num">Δ · %95</th><th class="fp-h">${fpAxis(dom)}</th><th>Kanıt</th></tr></thead><tbody>${layerRows(d.layers, dom)}</tbody></table></div>
      <p class="note"><b>Beklenti</b>: fiyatı olan marketlerde o maçların kendi fiyatı; olmayanlarda (İY, İY/MS, 1,5/3,5 üst, KG) <b>aynı fiyattaki maçlarda</b>
        aynı şeyin ne sıklıkta olduğu. Çizim tek ölçekte (±${dom} puan); renkli nokta aralığın sıfırı dışladığı satır. Gri satırlar 200 maçın altında.</p>`;
    const reasons = `<div class="lab-sec">Neden?</div><div class="lab-why"><div><h4>Destekleyenler</h4>${d.reasons.pro.length ? `<ul class="pro">${d.reasons.pro.map((x) => `<li>${esc(x)}</li>`).join("")}</ul>` : `<p class="note">Fiyattan ayrılan bir katman yok.</p>`}</div>
      <div><h4>Dikkat edilmesi gerekenler</h4>${d.reasons.con.length ? `<ul class="con">${d.reasons.con.map((x) => `<li>${esc(x)}</li>`).join("")}</ul>` : `<p class="note">—</p>`}</div></div>`;
    const mv = d.movement ? `<p class="note"><b>Oran hareketi:</b> ${esc((MOVE_TR[d.movement.type] || [d.movement.type])[0])}${d.movement.total_pp != null ? ` (${pp1(d.movement.total_pp)} puan)` : ""}
        · ${esc(d.movement.note)} <button type="button" class="linkbtn" data-open="move">ayrıntı</button></p>` : "";
    const seq = d.sequence ? `<p class="note"><b>Fikstür döngüsü:</b> ${esc(d.sequence.kind_tr)} · ±${d.sequence.window} · benzerlik %${d.sequence.similarity} (${d.sequence.past.season.slice(0, 2)}/${d.sequence.past.season.slice(2)})
        — benzerlik, olasılık değildir <button type="button" class="linkbtn" data-cycle="${esc(m.id)}">döngüyü aç</button></p>` : "";
    const disc = d.discovery ? `<p class="note"><b>Keşif taraması (hedefe göre):</b> bu hedefle ilgili ${d.discovery.n_claims} iddia üç pencereden geçirildi;
        ${d.discovery.survived.length ? `sağ kalan: ${d.discovery.survived.map((s) => `${esc(s.label)} (${pp1(s.edge)} puan, q=${num(s.q, 3)})`).join(" · ")}` : "hiçbiri üç pencereden de geçemedi"}.
        Ayrıntı aşağıdaki "Desen taraması" bölümünde.</p>` : `<p class="note"><b>Keşif taraması:</b> bu hedef için çevrimdışı tarama sonucu yok.</p>`;
    return verdict + fig + table + reasons + mv + seq + disc + `<ul class="lab-notes">${(d.notes || []).map((x) => `<li>${esc(x)}</li>`).join("")}</ul>`;
  }

  // ---------------------------------------------------------------- MOD 2 — bu sonuca uyan maç bul
  function lfInit() {
    state.lab.lfTp = tpBuild($("#lf-tp"), (key) => { state.lab.find.target = key; $("#lf-go").disabled = false; });
    labDates($("#lf-date"), () => {});
    $("#lf-go").onclick = lfGo;
  }


  async function lfGo() {
    const target = state.lab.find.target, date = $("#lf-date").value;
    if (!target) return;
    clearInterval(state.lab.find.timer);
    const t = (state.lab.targets?.groups || []).flatMap((g) => g.targets).find((x) => x.key === target) || { label: target };
    labQ(`${fmtDate(date)}: hangi maçlar <b>${esc(t.label)}</b> için araştırmaya değer? <span class="muted">— ${esc(t.explain || "")}</span>`);
    const box = $("#lf-out");
    box.innerHTML = `<p class="note">Tarama başlatılıyor…</p>`;
    try { await api(`/api/lab/tara?date=${date}&target=${encodeURIComponent(target)}`, { method: "POST" }); }
    catch (e) { box.innerHTML = `<p class="note">Başlatılamadı: ${esc(e.message)}</p>`; return; }
    const poll = async () => {
      try {
        const d = await api(`/api/lab/tara?date=${date}&target=${encodeURIComponent(target)}`);
        renderFind(d, target, date);
        if (d.state === "done" || d.state === "none") clearInterval(state.lab.find.timer);
      } catch (e) { box.innerHTML = `<p class="note">Okunamadı: ${esc(e.message)}</p>`; clearInterval(state.lab.find.timer); }
    };
    state.lab.find.timer = setInterval(poll, 1500);
    poll();
  }


  /** A target in this match's terms: "ft_2" is "Villarreal kazanır", never a bare "2". */
  function targetMeaning(key, home, away) {
    const ft = { "1": `${home} galibiyeti`, X: "beraberlik", "2": `${away} galibiyeti` };
    const ht = { "1": `${home} önde`, X: "berabere", "2": `${away} önde` };
    if (key.startsWith("ft_")) return ft[key.slice(3)] || key;
    if (key.startsWith("ht_")) return `ilk yarı ${ht[key.slice(3)] || key}`;
    if (key.startsWith("htft_")) { const [h, f] = key.slice(5).split("/"); return `İY ${ht[h]} → MS ${ft[f]}`; }
    return { over15: "en az 2 gol", over25: "en az 3 gol", over35: "en az 4 gol", btts: "iki takım da gol atar" }[key] || key;
  }

  /** What a row's Δ says, in words: the outcome came more or less often than priced, or nothing. */
  function deltaMeaning(diff, ci) {
    if (diff == null || !ci || ci[0] == null) return "";
    if (ci[0] > 0) return "↑ <b>beklenenden sık</b> gelmiş — oranı ucuz kalmış";
    if (ci[1] < 0) return "↓ <b>beklenenden seyrek</b> gelmiş — oranı pahalı kalmış";
    return "fiyattan ayırt edilemiyor";
  }

  function renderFind(d, target, date) {
    const box = $("#lf-out");
    const tLabel = ((state.lab.targets?.groups || []).flatMap((g) => g.targets).find((x) => x.key === target) || {}).label || target;
    const rows = (d.rows || []).slice().sort((a, b) => (b.relevance?.score || 0) - (a.relevance?.score || 0));
    const running = d.state === "running";
    const clearN = rows.filter((r) => r.difference_ci?.[0] != null && (r.difference_ci[0] > 0 || r.difference_ci[1] < 0)).length;
    const verdict = `<div class="lab-verdict">${evBadge(running ? "YETERSİZ VERİ" : clearN ? "KEŞİF" : "FARK YOK")}<p>${running
        ? `<b>${d.done} / ${d.total} maç tarandı…</b> Her maçta takım, rakip, benzer durumlar ve ikizler ölçülüyor; satırlar geldikçe sıralanır.`
        : `<b>Bu tarama: ${d.total} maç${d.errors ? `, ${d.errors} tanesi hesaplanamadı` : ""}.</b> ${clearN ? `${clearN} maçta birleşik aralık sıfırı dışlıyor — keşif, doğrulama değil.` : "Hiçbir maçta birleşik aralık sıfırı dışlamıyor."}
        <small class="muted">Hiçbir satır kazananı söylemez. Her satır, o maçın bugünkü durumunda <b>${esc(tLabel)}</b> sonucunun geçmişte fiyata göre daha sık mı, daha seyrek mi geldiğini ölçer; Δ artıysa fiyat ucuz, eksiyse pahalı kalmış demektir.</small>`}</p></div>`;
    if (!rows.length) { box.innerHTML = verdict + (d.state === "done" ? `<div class="day-empty">Bu günde durum tablosu hazır olan maç yok.</div>` : ""); return; }
    const dom = fpDomain(rows.map((r) => ({ edge: r.difference, ci: r.difference_ci })));
    box.innerHTML = verdict + `<div class="table-wrap"><table><thead><tr><th>Maç</th><th class="hide-md">Lig</th><th class="num hide-md">Saat</th><th class="num">Oran</th>
        <th class="num">Piyasa</th><th class="num">Pattern</th><th class="num">Δ · %95</th><th class="fp-h">${fpAxis(dom)}</th><th class="num" title="${esc(SIM_TIP)}">Benzerlik</th><th>Kanıt</th><th></th></tr></thead><tbody>
        ${rows.map((r) => `<tr class="${r.n_layers ? "" : "thin"}"><td class="wrap"><b>${esc(r.home)} – ${esc(r.away)}</b><br>
            <small class="muted">${esc(targetMeaning(target, r.home, r.away))}${deltaMeaning(r.difference, r.difference_ci) ? " · " + deltaMeaning(r.difference, r.difference_ci) : ""}</small></td>
          <td class="hide-md nw">${esc(r.league_name || r.league || "")}</td><td class="num hide-md">${esc(r.time || "")}</td>
          <td class="num">${r.market?.odds != null ? num(r.market.odds) : "–"}</td>
          <td class="num">${r.market?.p == null ? "<small class=\"muted\">yok</small>" : pctv(r.market.p)}</td>
          <td class="num">${r.estimate ? pctv(r.estimate.p) : "–"}</td>
          <td class="num ${r.difference_ci?.[0] != null && (r.difference_ci[0] > 0 || r.difference_ci[1] < 0) ? "yes" : ""}"><b>${r.difference == null ? "–" : pp1(r.difference)}</b><br><small class="muted">${ciTxt(r.difference_ci)}</small></td>
          <td class="fp-td">${fpCell(r.difference, r.difference_ci, dom)}</td>
          <td class="num">${r.similarity == null ? "–" : pctv(r.similarity, 0)}</td>
          <td>${evBadge(r.evidence?.label)}</td>
          <td><button type="button" class="btn ghost" data-detail="${esc(r.id)}">Detay</button></td></tr>`).join("")}
      </tbody></table></div>
      <p class="note">${esc(d.note || "")} Piyasa sütunu boşsa o market için fiyat yok (İY ve İY/MS fiyatları yalnızca nesine bülteninden gelir).
        Benzerlik, maçın geçmiş koşullara ne kadar benzediğidir — sonucun olasılığı değil. Çizim tek ölçekte (±${dom} puan).</p>`;
    box.querySelectorAll("[data-detail]").forEach((b) => (b.onclick = () => labOpenTarget(b.dataset.detail, date, target)));
  }

  async function labOpenTarget(id, date, target) {
    labShow("match");
    if ($("#lm-date").value !== date) { $("#lm-date").value = date; await lmLoad(date); }
    if (!state.lab.dayList.some((m) => m.id === id)) { toast("Maç bu günün listesinde bulunamadı."); return; }
    lmPick(id);
    state.lab.pendingTarget = target;
    lmScan();
  }

  // ---------------------------------------------------------------- MOD 3 — kendi patternini test et
  // The old explorer's engine (/api/desen) is kept; this is its wider front: team, opponent, match,
  // goals and market conditions, each added as its own row so the reader sees what moved the number.
  const EX_LET = { W: "G", D: "B", L: "M", "?": "?" };
  const EX_WORD = { W: "kazanmış", D: "berabere kalmış", L: "kaybetmiş", "?": "farketmez" };
  const EX_STR = { weak: "zayıf", mid: "orta", strong: "güçlü", top: "çok güçlü" };
  const EX_GOALS = [["gf5", "Attığı gol (toplam)"], ["ga5", "Yediği gol (toplam)"], ["btts5", "Karşılıklı gol olan maç"],
                    ["ov15_5", "1,5 üst biten maç"], ["ov25_5", "2,5 üst biten maç"], ["ov35_5", "3,5 üst biten maç"]];
  const EX_PRESETS = [
    ["Üst üste 3 galibiyet", { side: "home", seq: "WWW" }],
    ["3 maçtır kazanamıyor", { side: "home", seq: "??DL" }],
    ["Son 3'ünü kazanan güçlü ev sahibi", { side: "home", seq: "WWW", str: "strong" }],
    ["Deplasmanda 3 mağlubiyet", { side: "away", seq: "LLL", venue: true }],
    ["Güçlü favori (oran 1,20–1,50)", { side: "home", seq: "", o_lo: 1.2, o_hi: 1.5 }],
    ["Çok güçlü takım, zayıf rakip", { side: "home", seq: "", str: "top", ostr: "weak" }],
    ["Son 5'te hep KG, oran düştü", { side: "home", seq: "", goals: { btts5: [4, 5] }, move: "steam" }],
  ];
  state.ex = { asked: 0, cleared: 0, side: "home", seq: "WWW", vseq: "", oseq: "", ovseq: "", str: "", ostr: "", role: "", move: "", outcome: "win" };

  function exWire() {
    const go = $("#ex-go");
    if (!go || go._wired) return;
    go._wired = true;
    const presets = $("#ex-presets");
    EX_PRESETS.forEach(([label, cfg]) => {
      const b = el("button", "chip", label); b.type = "button";
      b.onclick = () => {
        Object.assign(state.ex, { side: cfg.side || "home", seq: cfg.seq || "", vseq: "", oseq: "", ovseq: "", str: cfg.str || "", ostr: cfg.ostr || "", role: cfg.role || "", move: cfg.move || "" });
        $("#ex-venue").checked = !!cfg.venue; $("#ex-slack").checked = false;
        $("#ex-o-lo").value = cfg.o_lo ?? ""; $("#ex-o-hi").value = cfg.o_hi ?? ""; $("#ex-gap-lo").value = ""; $("#ex-gap-hi").value = "";
        EX_GOALS.forEach(([k]) => { const r = (cfg.goals || {})[k]; $(`#ex-g-${k}-lo`).value = r ? r[0] : ""; $(`#ex-g-${k}-hi`).value = r ? r[1] : ""; });
        exPaint(); exRun();
      };
      presets.appendChild(b);
    });
    $("#ex-goals").innerHTML = EX_GOALS.map(([k, label]) => `<div class="ex-goal"><span>${label}</span>
      <div class="ex-pair"><input id="ex-g-${k}-lo" type="number" min="0" max="30" inputmode="numeric" placeholder="en az">
      <span>–</span><input id="ex-g-${k}-hi" type="number" min="0" max="30" inputmode="numeric" placeholder="en çok"></div></div>`).join("");
    const seg = (id, key, attr) => $(id).querySelectorAll("button").forEach((b) => (b.onclick = () => {
      state.ex[key] = b.dataset[attr]; $(id).querySelectorAll("button").forEach((x) => x.classList.toggle("is-on", x === b)); exPaint();
    }));
    seg("#ex-side-seg", "side", "v"); seg("#ex-str", "str", "s"); seg("#ex-ostr", "ostr", "s"); seg("#ex-role", "role", "r"); seg("#ex-move", "move", "m");
    const keys = (attr, key) => document.querySelectorAll(`#lab-own [data-${attr}]`).forEach((b) => (b.onclick = () => {
      const v = b.dataset[attr]; state.ex[key] = v === "del" ? state.ex[key].slice(0, -1) : (state.ex[key] + v).slice(-6); exPaint();
    }));
    keys("k", "seq"); keys("vk", "vseq"); keys("ok", "oseq"); keys("ovk", "ovseq");
    const lg = $("#ex-league");
    Object.entries(state.meta?.leagues || {}).sort((a, b) => a[1].localeCompare(b[1], "tr")).forEach(([code, name]) => { const o = el("option", "", esc(name)); o.value = code; lg.appendChild(o); });
    document.querySelectorAll("#lab-own input, #lab-own select").forEach((n) => { n.oninput = n.onchange = exPaint; });
    go.onclick = exRun;
    exPaint();
  }

  function exChips(seq, id) {
    const box = $(id); if (!box) return;
    box.innerHTML = seq ? seq.split("").map((c) => `<span class="fchip f-${c}">${EX_LET[c] || c}</span>`).join("") : `<span class="muted">boş — koşul yok</span>`;
  }

  const exWords = (s) => s.split("").map((c) => EX_WORD[c]).join(", ");

  /** The query, written back in Turkish. If this sentence is not what you meant, the answer is not either. */
  function exSentence() {
    const s = state.ex, who = s.side === "home" ? "Ev sahibi" : "Deplasman";
    const venue = $("#ex-venue")?.checked, bits = [];
    if (s.seq) bits.push(`son ${s.seq.length} ${venue ? (s.side === "home" ? "iç saha " : "deplasman ") : ""}maçında sırayla ${exWords(s.seq)}`);
    if (s.vseq) bits.push(`kendi sahasındaki son ${s.vseq.length} maçında ${exWords(s.vseq)}`);
    if (s.str) bits.push(`liginde ${EX_STR[s.str]} bir takım`);
    if (s.oseq) bits.push(`rakibi son ${s.oseq.length} maçında ${exWords(s.oseq)}`);
    if (s.ovseq) bits.push(`rakibi kendi sahasında ${exWords(s.ovseq)}`);
    if (s.ostr) bits.push(`rakibi ${EX_STR[s.ostr]}`);
    const gl = $("#ex-gap-lo")?.value, gh = $("#ex-gap-hi")?.value;
    if (gl !== "" && gh !== "" && gl != null && gh != null) bits.push(`güç farkı ${gl} ile ${gh} puan arasında`);
    const lg = $("#ex-league")?.value; if (lg) bits.push(`${leagueName(lg)} liginde`);
    EX_GOALS.forEach(([k, label]) => { const lo = $(`#ex-g-${k}-lo`)?.value, hi = $(`#ex-g-${k}-hi`)?.value; if (lo !== "" && hi !== "") bits.push(`son 5'te ${label.toLocaleLowerCase("tr")} ${lo}–${hi}`); });
    if (s.role) bits.push(s.role === "favorite" ? "piyasanın favorisi" : "piyasanın sürpriz adayı");
    const ol = $("#ex-o-lo")?.value, oh = $("#ex-o-hi")?.value; if (ol && oh) bits.push(`oranı ${ol}–${oh} arasında`);
    if (s.move) bits.push({ steam: "oranı kapanışa doğru düşmüş", drift: "oranı kapanışa doğru yükselmiş", stable: "oranı sabit kalmış" }[s.move]);
    if ($("#ex-slack")?.checked) bits.push("<span class=\"muted\">(dizide bir maç tutmasa da sayılır)</span>");
    return bits.length ? `<b>Soru:</b> ${who}, ${bits.join(" · ")} olan maçlarda ne olmuş?`
      : `<b>Soru:</b> hiç koşul yok — veritabanındaki bütün maçlar. Yukarıdan bir şeyler seç.`;
  }


  function exPaint() {
    exChips(state.ex.seq, "#ex-seq"); exChips(state.ex.vseq, "#ex-vseq"); exChips(state.ex.oseq, "#ex-oseq"); exChips(state.ex.ovseq, "#ex-ovseq");
    const q = $("#ex-q"); if (q) q.innerHTML = exSentence();
    if (state.lab.mode === "own") labQ(exSentence());
  }

  function exQuery() {
    const s = state.ex;
    const q = new URLSearchParams({ side: s.side, approx: $("#ex-slack")?.checked ? "1" : "0" });
    if (s.seq) { if ($("#ex-venue")?.checked && !s.vseq) q.set("venue_form", s.seq); else q.set("form", s.seq); }
    if (s.vseq) q.set("venue_form", s.vseq);
    if (s.str) q.set("strength", s.str);
    if (s.oseq) q.set("opp_form", s.oseq);
    if (s.ovseq) q.set("opp_venue_form", s.ovseq);
    if (s.ostr) q.set("opp_strength", s.ostr);
    const gl = $("#ex-gap-lo")?.value, gh = $("#ex-gap-hi")?.value;
    if (gl !== "" && gh !== "") { q.set("gap_lo", gl); q.set("gap_hi", gh); }
    const lg = $("#ex-league")?.value; if (lg) q.set("leagues", lg);
    const goals = EX_GOALS.map(([k]) => { const lo = $(`#ex-g-${k}-lo`)?.value, hi = $(`#ex-g-${k}-hi`)?.value; return lo !== "" && hi !== "" ? `${k}:${lo}-${hi}` : null; }).filter(Boolean);
    if (goals.length) q.set("goals", goals.join(","));
    if (s.role) q.set("role", s.role);
    const ol = Number($("#ex-o-lo")?.value), oh = Number($("#ex-o-hi")?.value);
    if (ol > 1 && oh > 1) { q.set("p_lo", (1 / Math.max(ol, oh)).toFixed(4)); q.set("p_hi", (1 / Math.min(ol, oh)).toFixed(4)); }
    if (s.move) q.set("movement", s.move);
    if (s.outcome && !EX_OUT[s.outcome]) q.set("outcome", s.outcome);
    return q;
  }

  async function exRun() {
    const out = $("#ex-out");
    out.innerHTML = `<p class="note">Ölçülüyor… koşullar tek tek ekleniyor.</p>`;
    try {
      const d = await api(`/api/lab/kendi?${exQuery()}`);
      state.ex.asked++;
      state.ex.last = d;
      renderOwn(d);
    } catch (err) { out.innerHTML = `<p class="note">Ölçülemedi: ${esc(err.message)}</p>`; }
  }


  function renderOwn(d) {
    const oc = state.ex.outcome in EX_OUT || d.outcomes.includes(state.ex.outcome) ? state.ex.outcome : "win";
    const cell = (x) => {
      if (!x || !x.n) return { edge: null, ci: [null, null] };
      return { edge: x.edge != null ? x.edge : x.vs_ref, ci: x.edge_ci || x.vs_ref_ci || [null, null], x };
    };
    const nmax = d.rows[0].n;
    const domC = fpDomain(d.rows.map((r) => cell(r.outcomes[oc])));
    const casc = d.rows.map((r, i) => {
      const c = cell(r.outcomes[oc]); const x = c.x || {};
      const solid = c.ci[0] != null && (c.ci[0] > 0 || c.ci[1] < 0);
      return `<tr class="${(x.n || 0) < 200 ? "thin" : ""}"><td class="wrap">${i ? "↓ " : ""}${esc(r.step)}</td>
        <td class="num">${nbar(r.n, nmax, r.n < 200)}${r.n_lost ? `<br><small class="muted">−${r.n_lost.toLocaleString("tr")}</small>` : ""}</td>
        <td class="num">${x.actual == null ? "–" : "%" + num(x.actual, 1)}</td>
        <td class="num">${(x.market ?? x.ref) == null ? "–" : "%" + num(x.market ?? x.ref, 1)}</td>
        <td class="num ${solid ? "yes" : ""}"><b>${c.edge == null ? "–" : pp1(c.edge)}</b><br><small class="muted">${ciTxt(c.ci)}</small></td>
        <td class="fp-td">${fpCell(c.edge, c.ci, domC)}</td></tr>`;
    }).join("");
    const last = d.rows[d.rows.length - 1];
    const domA = fpDomain(d.outcomes.map((o) => cell(last.outcomes[o])));
    const allRows = d.outcomes.map((o) => {
      const c = cell(last.outcomes[o]); const x = c.x; if (!x) return "";
      const solid = c.ci[0] != null && (c.ci[0] > 0 || c.ci[1] < 0);
      return `<tr class="${x.n < 200 ? "thin" : ""}"><td>${esc(EX_OUT[o] || (state.lab.targets?.groups || []).flatMap((g) => g.targets).find((t) => t.key === o)?.label || o)}</td>
        <td class="num hide-sm">${x.n}</td><td class="num">%${num(x.actual, 1)}</td><td class="num">${(x.market ?? x.ref) == null ? "–" : "%" + num(x.market ?? x.ref, 1)}</td>
        <td class="num ${solid ? "yes" : ""}"><b>${c.edge == null ? "–" : pp1(c.edge)}</b><br><small class="muted">${ciTxt(c.ci)}</small></td><td class="fp-td">${fpCell(c.edge, c.ci, domA)}</td></tr>`;
    }).join("");
    const solidN = d.outcomes.filter((o) => { const c = cell(last.outcomes[o]); return c.ci[0] != null && (c.ci[0] > 0 || c.ci[1] < 0); }).length;
    state.ex.cleared += solidN;
    const tests = state.ex.asked * d.outcomes.length;
    const chips = d.outcomes.map((o) => `<button type="button" data-oc="${esc(o)}" class="${o === oc ? "is-on" : ""}">${esc(EX_OUT[o] || o)}</button>`).join("");
    const lc = cell(last.outcomes[oc]);
    const RES = { H: "1", D: "X", A: "2" };
    const sample = (last.sample || []);
    const who = (r) => (d.side === "home" ? r.home_team : r.away_team);
    const sampleHTML = sample.length ? `<div class="lab-sec">Bu tarife uyan maçlar <span class="muted">— en yeni ${sample.length}${last.n > sample.length ? ` / ${last.n.toLocaleString("tr")}` : ""}; kalın olan koşulun tarif ettiği takım</span></div>
      <div class="table-wrap"><table><thead><tr><th>Tarih</th><th class="hide-sm">Lig</th><th>Maç</th><th class="num">Skor</th><th class="num">MS</th><th class="hide-sm">Form (ev / dep)</th></tr></thead><tbody>
      ${sample.map((r) => `<tr><td class="num">${fmtShort(String(r.date).slice(0, 10))}</td><td class="hide-sm nw">${esc(leagueName(r.league))}</td>
        <td class="wrap">${d.side === "home" ? `<b>${esc(r.home_team)}</b> – ${esc(r.away_team)}` : `${esc(r.home_team)} – <b>${esc(r.away_team)}</b>`}</td>
        <td class="num">${r.fthg == null ? "–" : `${r.fthg}-${r.ftag}`}</td><td class="num res-${esc(r.ftr || "")}">${RES[r.ftr] || "–"}</td>
        <td class="hide-sm"><span class="fseq">${esc(String(r.h_form || "").slice(-5))}</span> / <span class="fseq">${esc(String(r.a_form || "").slice(-5))}</span></td></tr>`).join("")}
      </tbody></table></div>` : "";
    const verdict = `<div class="lab-verdict">${evBadge(last.n < 200 ? "YETERSİZ VERİ" : solidN ? "KEŞİF" : "FARK YOK")}<p><b>Son koşulda ${last.n.toLocaleString("tr")} maç kaldı</b>
        (${d.pool.toLocaleString("tr")} maçlık havuz, ${d.span[0]} – ${d.span[1]}). ${last.n < 200 ? "Örneklem 200'ün altında; son satırlar okunmamalı — hangi koşulun örneklemi bitirdiğine bak."
        : lc.edge != null ? `${esc(EX_OUT[oc] || oc)} için fark <b>${ppv(lc.edge)}</b>, aralık ${ciTxt(lc.ci)} ${lc.ci[0] > 0 || lc.ci[1] < 0 ? "sıfırı dışlıyor — bir aday, bulgu değil." : "sıfırı içeriyor — piyasanın bildiği bir şey."}` : ""}</p></div>`;
    $("#ex-out").innerHTML = verdict + `
      <div class="lab-sec">Koşulların etkisi</div>
      <div class="kseg ex-ocs">${chips}</div>
      <div class="table-wrap"><table><thead><tr><th>Koşul</th><th class="num">N</th><th class="num">Oldu</th><th class="num">Fiyat</th><th class="num">Fark · %95</th><th class="fp-h">${fpAxis(domC)}</th></tr></thead><tbody>${casc}</tbody></table></div>
      <p class="note">${esc(d.note)} N çubuğu ilk satıra göre; çizim tek ölçekte (±${domC} puan).</p>
      <div class="lab-sec">Son koşulda bütün sonuçlar</div>
      <div class="table-wrap"><table><thead><tr><th>Sonuç</th><th class="num hide-sm">N</th><th class="num">Oldu</th><th class="num">Fiyat</th><th class="num">Fark · %95</th><th class="fp-h">${fpAxis(domA)}</th></tr></thead><tbody>${allRows}</tbody></table></div>
      <p class="note"><b>Fiyat</b> sütunu: piyasanın fiyatı olan marketlerde (1X2, 2,5 üst) o maçların kendi fiyatı; olmayan marketlerde
        <b>aynı fiyattaki maçlarda</b> aynı şeyin ne sıklıkta olduğu — havuz ortalaması değil. Fark, havuz geneli sapma çıkarıldıktan sonradır.
        <b>Aralık sıfırı içeriyorsa desen, piyasanın zaten bildiği bir şeyi söylüyor.</b></p>
      ${sampleHTML}
      <p class="ex-warn">Bu oturumda <b>${state.ex.asked} sorgu</b> çalıştırdın, her biri ${d.outcomes.length} sonucu ölçtü: <b>${tests} test</b>.
        %95 aralıkla, hiçbir gerçek desen olmasa bile bunların yaklaşık <b>${Math.max(1, Math.round(tests * 0.05))} tanesinin</b> sıfırı dışlaması beklenir —
        şu ana kadar ${state.ex.cleared} tanesi dışladı. Buradan çıkan bir fikir bulgu değil, <b>adaydır</b> (KEŞİF): gerçek sınav üç pencereli tarama ve çoklu test düzeltmesidir.</p>`;
    $("#ex-out").querySelectorAll("[data-oc]").forEach((b) => (b.onclick = () => { state.ex.outcome = b.dataset.oc; renderOwn(state.ex.last); }));
  }

  // ---------------------------------------------------------------- MOD 4 — döngü ara
  function lcInit() {
    const q = $("#lc-q"), sug = $("#lc-suggest");
    let t = null;
    q.oninput = () => {
      state.lab.cycle.team = null; $("#lc-go").disabled = true;
      clearTimeout(t);
      const v = q.value.trim();
      if (v.length < 2) { sug.hidden = true; return; }
      t = setTimeout(async () => {
        try {
          const d = await api(`/api/lab/takimlar?q=${encodeURIComponent(v)}&limit=12`);
          if (q.value.trim() !== v || state.lab.cycle.team) return;      // typed on, or already chosen
          sug.hidden = !d.teams.length;
          sug.innerHTML = d.teams.map((x) => `<button type="button" data-team="${esc(x.team)}"><b>${esc(x.team)}</b><small class="muted">${esc(leagueName(x.league))} · ${x.n} maç · son ${fmtShort(x.last)}</small></button>`).join("");
          sug.querySelectorAll("[data-team]").forEach((b) => (b.onclick = () => lcChoose(b.dataset.team)));
        } catch (_) { sug.hidden = true; }
      }, 250);
    };
    $("#lc-go").onclick = () => lcRun(state.lab.cycle.team, $("#lc-centre").value);
  }

  async function lcChoose(team) {
    state.lab.cycle.team = team; $("#lc-q").value = team; $("#lc-suggest").hidden = true; $("#lc-go").disabled = false;
    const sel = $("#lc-centre"); sel.innerHTML = `<option value="">Otomatik — bu sezonun bütün maçları taranır</option>`;
    try {
      const d = await api(`/api/lab/takim-maclari?team=${encodeURIComponent(team)}`);
      d.matches.forEach((m) => {
        const o = el("option", "", `${esc(m.home)} – ${esc(m.away)} · ${fmtShort(m.date)}${m.played ? ` · ${esc(m.score)}` : " · oynanacak"}`);
        o.value = m.id; sel.appendChild(o);
      });
    } catch (_) {}
  }

  async function lcRun(team, matchId) {
    if (!team) return;
    state.lab.cycle.team = team; $("#lc-q").value = team; $("#lc-go").disabled = false;
    labQ(`<b>${esc(team)}</b> fikstürü geçmiş bir sezonu tekrarlıyor mu?`);
    const box = $("#lc-out");
    box.innerHTML = `<p class="note">±2, ±3, ±4 pencereleri, bütün geçmiş sezonlar, dört dizi türü taranıyor…</p>`;
    try {
      const d = await api(`/api/dongu?team=${encodeURIComponent(team)}${matchId ? `&match_id=${encodeURIComponent(matchId)}` : ""}&min_similarity=60`);
      state.lab.cycle.data = d;
      renderCycles(d);
    } catch (e) { box.innerHTML = `<p class="note">Aranamadı: ${esc(e.message)}</p>`; }
  }


  function renderCycles(d) {
    const box = $("#lc-out");
    const c = d.centre;
    const centre = c ? `${c.home ? `${esc(c.home)} – ${esc(c.away)}` : esc(c.opponent)} (${fmtShort(c.date)}, ${c.season.slice(0, 2)}/${c.season.slice(2)})` : "";
    if (!d.cycles.length) {
      box.innerHTML = `<div class="lab-verdict">${evBadge("FARK YOK")}<p><b>Döngü bulunamadı.</b> Merkez maç ${centre}; ${d.searched} geçmiş dizi ${d.windows.map((w) => "±" + w).join(" / ")} pencerelerinde dört türde karşılaştırıldı, %60'ın üstünde benzeyen yok. Bu da bir cevaptır: bu takımın fikstürü geçmiş sezonlarını tekrarlamıyor.</p></div>`;
      return;
    }
    const best = d.cycles[0];
    const bn = best.now;
    const bcentre = `${bn.home ? `${esc(bn.home)} – ${esc(bn.away)}` : esc(bn.opponents[bn.centre])} (${fmtShort(bn.date)}${bn.played === false ? ", oynanacak" : ""})`;
    const verdict = `<div class="lab-verdict"><span class="ev ev-ctx">BAĞLAM</span><p><b>${esc(best.kind_tr)}, ±${best.window} pencerede, %${best.similarity} benzerlik</b> — ${best.past.season.slice(0, 2)}/${best.past.season.slice(2)} sezonuyla, ${best.n_compared} pozisyon karşılaştırıldı.
        Merkez maç: <b>${bcentre}</b>. ${d.centres_searched > 1 ? `Bu sezonun ${d.centres_searched} maçı merkez olarak denendi, ` : ""}${d.searched} geçmiş dizi tarandı. <b>Bu bir fikstür benzerliğidir, sonuç olasılığı değil</b>; bir anlamı olup olmadığını aşağıdaki düğme ölçer.</p></div>`;
    const fig = `<div class="lab-fig">
      <div class="lab-stat"><small>DİZİ TÜRÜ</small><b style="font-size:1.25rem">${esc(best.kind_tr)}</b><span class="muted">${esc(best.kind.replace("_", " ").toLowerCase())}</span></div>
      <div class="lab-stat"><small>PENCERE</small><b>±${best.window}</b><span class="muted">${best.n_compared} pozisyon karşılaştırıldı</span></div>
      <div class="lab-stat"><small>KARŞILAŞTIRILAN SEZON</small><b style="font-size:1.25rem">${best.past.season.slice(0, 2)}/${best.past.season.slice(2)}</b><span class="muted">${fmtShort(best.past.date)}</span></div></div>
      <div class="lab-sec">Benzerlik <i class="tip" title="${esc(SIM_TIP)}" aria-hidden="true">?</i></div>
      ${meter(best.similarity)}
      <p class="note">Konum konum %${best.positional} · kanat %${best.wing}. <b>Konum konum</b>: aynı sıradaki rakip eşleşiyor mu; <b>kanat</b>: merkezden önceki ve sonraki kulüpler aynı mı, sıra fark etmeksizin. Grafikler ikinciyi %100 diye alıntılar; ikisini birden göstermek dürüst olanı.</p>
      ${mirror(best)}
      <div class="lab-actions"><button type="button" class="btn ex-go" data-measure="0">Bu döngü geçmişte işe yaramış mı?</button></div>
      <div id="lc-measure"></div>`;
    const others = d.cycles.length > 1 ? `<details class="ex-more"><summary>Bulunan bütün döngüler <span class="muted">— ${d.cycles.length} tane; her tür için en iyi üçü</span></summary>
      <div class="table-wrap"><table><thead><tr><th>Tür</th><th class="num">Pencere</th><th class="num">Benzerlik</th><th class="num hide-sm">Konum</th><th class="num hide-sm">Kanat</th><th class="num">Karş.</th><th>Geçmiş sezon</th><th>Merkez maç</th><th></th></tr></thead><tbody>
      ${d.cycles.map((x, i) => `<tr class="${i === 0 ? "ac-alive" : ""}"><td>${esc(x.kind_tr)}</td><td class="num">±${x.window}</td><td class="num"><b>%${x.similarity}</b></td>
        <td class="num hide-sm">%${x.positional}</td><td class="num hide-sm">%${x.wing}</td><td class="num">${x.n_compared}</td><td class="nw">${x.past.season.slice(0, 2)}/${x.past.season.slice(2)} · ${fmtShort(x.past.date)}</td><td class="nw">${esc(x.now.opponents[x.now.centre] || "")} · ${fmtShort(x.now.date)}</td>
        <td><button type="button" class="linkbtn" data-measure="${i}">ölç</button></td></tr>`).join("")}</tbody></table></div></details>` : "";
    const pairs = d.pairs || {};
    box.innerHTML = verdict + fig + others + (pairs.n_pairs ? `<p class="note">Döngü çiftleri tablosu: ${Number(pairs.n_pairs).toLocaleString("tr")} çift, ${pairs.generated_at ? ntAgo(pairs.generated_at) : ""}.</p>`
      : `<p class="note">Bütün veritabanı için döngü çiftleri tablosu henüz kurulmadı; ilk ölçüm isteği kurar (bir dakikaya kadar sürebilir).</p>`);
    box.querySelectorAll("[data-measure]").forEach((b) => (b.onclick = () => lcMeasure(d.cycles[Number(b.dataset.measure)], d)));
  }

  async function lcMeasure(cyc, d) {
    const box = $("#lc-measure");
    box.innerHTML = `<p class="note">Bütün veritabanı taranıyor: ${esc(cyc.kind_tr)}, ±${cyc.window}, benzerlik ≥ %${cyc.similarity} …</p>`;
    box.scrollIntoView({ behavior: "smooth", block: "nearest" });
    const tsi = cyc.now?.tsi ?? d.centre?.tsi;
    try {
      const q = new URLSearchParams({ kind: cyc.kind, window: cyc.window, similarity: cyc.similarity, team: d.team });
      if (tsi != null) q.set("tsi", tsi);
      const m = await api(`/api/lab/dongu-olc?${q}`);
      state.lab.cycle.measure = m;
      renderMeasure(m, cyc, d, m.bands[0]?.hypothesis);
    } catch (e) { box.innerHTML = `<p class="note">Ölçülemedi: ${esc(e.message)}</p>`; }
  }

  const RES_TR = { W: "G", D: "B", L: "M" };


  function renderMeasure(m, cyc, d, hyp) {
    const box = $("#lc-measure");
    const bands = m.bands || [];
    const first = bands[0];
    const all = first?.layers.find((l) => l.key === "all");
    const verdict = first ? `<div class="lab-verdict">${evBadge(all?.evidence_tr)}<p><b>${esc(first.hypothesis_tr)}</b> — ${first.n_pairs.toLocaleString("tr")} döngü çiftinde.
        ${all && all.n ? `Tüm takımlarda gerçekleşen ${pctv(all.actual)}, o sonucun piyasa fiyatı ${pctv(all.market ?? all.ref)}: fark <b>${ppv(all.edge)}</b>, aralık ${ciTxt(all.ci)}.` : "Bu benzerlik bandında ölçülecek çift yok."}
        ${cyc.kind === "EXACT_REVERSE" ? "Fikstür sırası tersine döndüyse merkez maçın sonucu da tersine dönüyor mu? Grafiklerin iması; doğru kabul edilmedi, veri üzerinde test edildi." : "Aynı dizi tekrarladıysa merkez maçın sonucu da tekrarlıyor mu?"}</p></div>` : "";
    const bandHTML = (b) => {
      const dom = fpDomain(b.layers);
      return `<div class="lab-band"><div class="lab-sec">Benzerlik ≥ %${b.min_similarity} <span class="muted">· ${b.n_pairs.toLocaleString("tr")} çift</span></div>
      <div class="table-wrap"><table><thead><tr><th>Katman</th><th class="num">N</th><th class="num">Gerçekleşen</th><th class="num">Piyasa</th><th class="num">Δ · %95</th><th class="fp-h">${fpAxis(dom)}</th><th>Kanıt</th></tr></thead><tbody>
      ${b.layers.map((l) => `<tr class="${l.n < 200 ? "thin" : ""}"><td>${esc(l.label)}</td><td class="num">${l.n}</td>
        <td class="num">${pctv(l.actual)}</td><td class="num">${pctv(l.market ?? l.ref)}${l.market == null && l.ref != null ? "<br><small class=\"muted\">havuz oranı</small>" : ""}</td>
        <td class="num ${l.ci && l.ci[0] != null && (l.ci[0] > 0 || l.ci[1] < 0) ? "yes" : ""}"><b>${l.edge == null ? "–" : pp1(l.edge)}</b><br><small class="muted">${ciTxt(l.ci)}</small></td>
        <td class="fp-td">${fpCell(l.edge, l.ci, dom)}</td><td>${evBadge(l.evidence_tr)}</td></tr>`).join("")}
      </tbody></table></div>
      ${b.ht_mirror ? `<p class="note"><b>İY/MS aynası</b> (${esc(b.ht_mirror.hypothesis_tr)}): önceki merkez maç 1/2 ya da 2/1 bittiyse yeni merkez maç bunun aynası oldu mu? N = ${b.ht_mirror.n}, gerçekleşen ${pctv(b.ht_mirror.actual)}, havuz oranı ${pctv(b.ht_mirror.ref)}, fark ${b.ht_mirror.edge == null ? "–" : pp1(b.ht_mirror.edge)} ${ciTxt(b.ht_mirror.ci)}.</p>` : ""}</div>`;
    };
    const ex = first?.examples || [];
    const examples = ex.length ? `<div class="lab-sec">Benzer döngüler <span class="muted">— gerçek örnekler, önce bu kulübünkiler</span></div>
      <div class="table-wrap"><table><thead><tr><th>Tarih</th><th>Takım</th><th class="hide-md">Sezon A</th><th class="hide-md">Sezon B</th><th>Tür</th><th class="num">Benz.</th><th class="num">Önceki merkez</th><th class="num">Yeni merkez</th><th class="num">Piyasa</th><th class="num">CLV</th></tr></thead><tbody>
      ${ex.map((r) => `<tr class="${r.own ? "ac-alive" : ""}"><td class="num">${fmtShort(r.date)}</td><td class="wrap">${esc(r.team)}<small class="muted"> – ${esc(r.opponent)}</small></td>
        <td class="hide-md">${r.season_a.slice(0, 2)}/${r.season_a.slice(2)}</td><td class="hide-md">${r.season_b.slice(0, 2)}/${r.season_b.slice(2)}</td><td class="nw">${esc(r.kind_tr)} ±${r.window}</td>
        <td class="num">%${r.similarity}</td><td class="num">${RES_TR[r.past_result] || "–"}${r.past_htft ? ` <small class="muted">${esc(r.past_htft)}</small>` : ""}</td>
        <td class="num">${RES_TR[r.new_result] || "–"}${r.new_htft ? ` <small class="muted">${esc(r.new_htft)}</small>` : ""} ${r.held == null ? "" : r.held ? '<span class="ok">✓</span>' : '<span class="bad">✗</span>'}</td>
        <td class="num">${r.market_p == null ? "–" : pctv(r.market_p)}</td><td class="num ${r.clv > 0 ? "pos" : r.clv < 0 ? "neg" : ""}">${r.clv == null ? "–" : signedPct(r.clv)}</td></tr>`).join("")}
      </tbody></table></div>
      <p class="note">Sonuçlar takımın gözünden (G/B/M); ✓ hipotezin tuttuğu satır. Piyasa: hipotezin söylediği sonucun o maçtaki fiyatı. CLV: o sonucun konsensüs oranının kapanış oranına göre değeri (2019/20'den beri kapanış oranı olan maçlar).</p>` : "";
    const other = hyp === "mirror" ? "repeat" : "mirror";
    box.innerHTML = verdict + `<p class="note">Her katmanda gerçekleşen, o maçlarda hipotezin söylediği sonucun <b>piyasa fiyatının</b> yanında. Kanıt: KEŞİF = havuzda sıfırı dışlıyor; DOĞRULANDI = doğrulama penceresinde aynı işaretle tekrarladı; İLERİ TESTTE = dokunulmamış test penceresinde de tuttu; YETERSİZ VERİ = 200 çiftin altı.
      <button type="button" class="linkbtn" data-hyp="${other}">${other === "mirror" ? "ayna hipotezini" : "tekrar hipotezini"} de ölç</button></p>
      ${bands.map(bandHTML).join("")}${examples}`;
    box.querySelector("[data-hyp]").onclick = async (ev) => {
      const b = ev.currentTarget; b.disabled = true;
      try {
        const q = new URLSearchParams({ kind: cyc.kind, window: cyc.window, similarity: cyc.similarity, team: d.team, hypothesis: other });
        const tsi2 = cyc.now?.tsi ?? d.centre?.tsi;
        if (tsi2 != null) q.set("tsi", tsi2);
        renderMeasure(await api(`/api/lab/dongu-olc?${q}`), cyc, d, other);
      } catch (e) { toast("Ölçülemedi: " + e.message); b.disabled = false; }
    };
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
    document.querySelectorAll("#view-scorecard [data-range]").forEach((b) => (b.onclick = () => { setRange(Number(b.dataset.range)); loadScorecard(); }));
    const onDates = () => {
      const f = $("#sc-from").value, t = $("#sc-to").value; if (!f || !t) return;
      state.sc.from = f <= t ? f : t; state.sc.to = f <= t ? t : f;
      document.querySelectorAll("#view-scorecard [data-range]").forEach((x) => x.classList.remove("is-on"));
      loadScorecard();
    };
    $("#sc-from").onchange = onDates; $("#sc-to").onchange = onDates;
    document.querySelectorAll("#view-paper [data-prange]").forEach((b) => (b.onclick = () => { setPRange(Number(b.dataset.prange)); loadPaper(); }));
    const onPDates = () => {
      const f = $("#pp-from").value, t = $("#pp-to").value; if (!f || !t) return;
      state.pp.from = f <= t ? f : t; state.pp.to = f <= t ? t : f;
      document.querySelectorAll("#view-paper [data-prange]").forEach((x) => x.classList.remove("is-on"));
      loadPaper();
    };
    $("#pp-from").onchange = onPDates; $("#pp-to").onchange = onPDates;
    $("#pp-edge").onchange = (e) => { state.pp.edge = Number(e.target.value); loadPaper(); };
    $("#nt-date").onchange = (e) => { state.nt.date = e.target.value; state.nt.leagues = new Set(); loadNotes(); };
    $("#nt-refresh").onclick = () => loadNotes(true);
    ntAutoPoll();
    // kick-offs pass while the page sits open: keep the played/in-play/to-come counts honest
    setInterval(() => {
      if (state.view !== "list" || !state.day || document.hidden) return;
      renderStatusChips();
      if (state.status.size !== STATUS.length) renderCards();
    }, 60000);
    const ntRe = () => { if (state.nt.data) renderNotes(); };
    document.querySelectorAll('input[name="nt-mode"]').forEach((r) => (r.onchange = () => { state.nt.mode = r.value; state.nt.leagues = new Set(); ntRe(); }));
    $("#nt-q").oninput = (e) => { state.nt.q = e.target.value; ntRe(); };
    $("#nt-sort").onchange = (e) => { state.nt.sort = e.target.value; ntRe(); };
    $("#nt-market").onchange = (e) => { state.nt.market = e.target.value; ntRe(); };
    const num2 = (v) => (v === "" || isNaN(Number(v)) ? null : Number(v));
    $("#nt-min").oninput = (e) => { state.nt.min = num2(e.target.value); ntRe(); };
    $("#nt-max").oninput = (e) => { state.nt.max = num2(e.target.value); ntRe(); };
    $("#nt-clear").onclick = () => {
      state.nt.market = ""; state.nt.min = null; state.nt.max = null; state.nt.q = "";
      $("#nt-market").value = ""; $("#nt-min").value = ""; $("#nt-max").value = ""; $("#nt-q").value = "";
      ntRe();
    };
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
