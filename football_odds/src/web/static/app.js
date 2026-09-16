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


  // ---------------------------------------------------------------- kendi desenini sor
  // The research tab has always said an idea can be tested in seconds against 180.000 matches, and
  // there was no control that did it. This is that control — and it is a p-hacking machine by
  // construction, so it keeps count: ask twenty questions and one clears zero because that is what
  // a 95 % interval means. The counter is the denominator the reader needs.
  state.ex = { asked: 0, cleared: 0 };
  const EX_OUT = { win: "Kazanır", draw: "Berabere", loss: "Kaybeder", over25: "2,5 üst", btts: "KG var",
                   over15: "1,5 üst", over35: "3,5 üst", ht_draw: "İY berabere", ht_win: "İY önde" };

  // The form used to demand W/D/L typed into a text box while every other screen shows G/B/M
  // chips, and asked for a probability band while the reader thinks in odds. Both are now the
  // reader's own units, the sequence is tapped rather than typed (this is read on a phone), and
  // the question is written back as a Turkish sentence before it is asked.
  const EX_LET = { W: "G", D: "B", L: "M", "?": "?" };
  const EX_WORD = { W: "kazanmış", D: "berabere kalmış", L: "kaybetmiş", "?": "farketmez" };
  const EX_PRESETS = [
    ["Üst üste 3 galibiyet", { side: "home", seq: "WWW" }],
    ["3 maçtır kazanamıyor", { side: "home", seq: "??", seq2: "DL" }],
    ["Deplasmanda 3 mağlubiyet", { side: "away", seq: "LLL", venue: true }],
    ["Güçlü favori (oran 1,20–1,50)", { side: "home", seq: "", o_lo: 1.2, o_hi: 1.5 }],
    ["Ligin en güçlüsü, kötü formda", { side: "home", seq: "LL", tsi_lo: 85, tsi_hi: 100 }],
  ];
  state.ex = { asked: 0, cleared: 0, side: "home", seq: "WWW", oseq: "" };

  function exWire() {
    const card = $("#ex-go");
    if (!card || card._wired) return;
    card._wired = true;

    const presets = $("#ex-presets");
    EX_PRESETS.forEach(([label, cfg]) => {
      const b = el("button", "chip", label); b.type = "button";
      b.onclick = () => {
        state.ex.side = cfg.side || "home";
        state.ex.seq = (cfg.seq || "") + (cfg.seq2 || "");
        state.ex.oseq = "";
        $("#ex-venue").checked = !!cfg.venue;
        $("#ex-slack").checked = false;
        $("#ex-tsi-lo").value = cfg.tsi_lo ?? ""; $("#ex-tsi-hi").value = cfg.tsi_hi ?? "";
        $("#ex-o-lo").value = cfg.o_lo ?? ""; $("#ex-o-hi").value = cfg.o_hi ?? "";
        $("#ex-side-seg").querySelectorAll("button").forEach((x) => x.classList.toggle("is-on", x.dataset.v === state.ex.side));
        exPaint(); exRun();
      };
      presets.appendChild(b);
    });

    $("#ex-side-seg").querySelectorAll("button").forEach((b) => {
      b.onclick = () => {
        state.ex.side = b.dataset.v;
        $("#ex-side-seg").querySelectorAll("button").forEach((x) => x.classList.toggle("is-on", x === b));
        exPaint();
      };
    });
    const scope = $("#ex-go").closest(".rs-block") || document;
    scope.querySelectorAll("[data-k]").forEach((b) => {
      b.onclick = () => {
        state.ex.seq = b.dataset.k === "del" ? state.ex.seq.slice(0, -1) : (state.ex.seq + b.dataset.k).slice(-6);
        exPaint();
      };
    });
    scope.querySelectorAll("[data-ok]").forEach((b) => {
      b.onclick = () => {
        state.ex.oseq = b.dataset.ok === "del" ? state.ex.oseq.slice(0, -1) : (state.ex.oseq + b.dataset.ok).slice(-6);
        exPaint();
      };
    });
    ["#ex-venue", "#ex-slack", "#ex-tsi-lo", "#ex-tsi-hi", "#ex-o-lo", "#ex-o-hi"].forEach((id) => {
      const n = $(id); if (n) n.oninput = n.onchange = exPaint;
    });
    $("#ex-go").onclick = exRun;
    exPaint();
  }

  function exChips(seq, id) {
    const box = $(id);
    if (!box) return;
    box.innerHTML = seq
      ? seq.split("").map((c) => `<span class="fchip f-${c}">${EX_LET[c] || c}</span>`).join("")
      : `<span class="muted">boş — hepsi dahil</span>`;
  }

  /** The query, written back in Turkish. If this sentence is not what you meant, the answer is not either. */
  function exSentence() {
    const who = state.ex.side === "home" ? "Ev sahibi" : "Deplasman";
    const venue = $("#ex-venue")?.checked;
    const bits = [];
    if (state.ex.seq) {
      const n = state.ex.seq.length;
      const words = state.ex.seq.split("").map((c) => EX_WORD[c]).join(", ");
      bits.push(`son ${n} ${venue ? (state.ex.side === "home" ? "iç saha " : "deplasman ") : ""}maçında sırayla ${words}`);
    }
    if (state.ex.oseq) bits.push(`rakibi ${state.ex.oseq.split("").map((c) => EX_WORD[c]).join(", ")}`);
    const lo = $("#ex-tsi-lo")?.value, hi = $("#ex-tsi-hi")?.value;
    if (lo && hi) bits.push(`ligindeki gücü %${lo}–%${hi} diliminde`);
    const ol = $("#ex-o-lo")?.value, oh = $("#ex-o-hi")?.value;
    if (ol && oh) bits.push(`oranı ${ol}–${oh} arasında`);
    if ($("#ex-slack")?.checked) bits.push("<span class=\"muted\">(bir maç tutmasa da sayılır)</span>");
    return bits.length
      ? `<b>Soru:</b> ${who}, ${bits.join(" · ")} olan maçlarda ne olmuş?`
      : `<b>Soru:</b> hiç koşul yok — veritabanındaki bütün maçlar. Yukarıdan bir şeyler seç.`;
  }

  function exPaint() {
    exChips(state.ex.seq, "#ex-seq");
    exChips(state.ex.oseq, "#ex-oseq");
    const q = $("#ex-q"); if (q) q.innerHTML = exSentence();
  }

  async function exRun() {
    const out = $("#ex-out");
    const q = new URLSearchParams({ form: state.ex.seq, side: state.ex.side,
                                    approx: $("#ex-slack")?.checked ? "1" : "0" });
    if ($("#ex-venue")?.checked) q.set("venue", "true");
    if (state.ex.oseq) q.set("opp_form", state.ex.oseq);
    const tl = $("#ex-tsi-lo")?.value, th = $("#ex-tsi-hi")?.value;
    if (tl && th) { q.set("tsi_lo", tl); q.set("tsi_hi", th); }
    // the reader thinks in odds; the engine filters on the margin-free probability
    const ol = Number($("#ex-o-lo")?.value), oh = Number($("#ex-o-hi")?.value);
    if (ol > 1 && oh > 1) { q.set("p_lo", (1 / Math.max(ol, oh)).toFixed(4)); q.set("p_hi", (1 / Math.min(ol, oh)).toFixed(4)); }
    out.innerHTML = `<p class="note">Ölçülüyor…</p>`;
    try {
      const d = await api(`/api/desen?${q}`);
      state.ex.asked++;
      renderExplore(d);
    } catch (err) {
      out.innerHTML = `<p class="note">Ölçülemedi: ${esc(err.message)}</p>`;
    }
  }

  function renderExplore(d) {
    const rows = (d.outcomes_order || []).map((o) => {
      const x = d.outcomes[o] || {};
      if (!x.n) return "";
      const edge = x.edge != null ? x.edge : x.vs_ref;
      const ci = x.edge_ci || x.vs_ref_ci || [null, null];
      const solid = ci[0] != null && (ci[0] > 0 || ci[1] < 0);
      return `<tr class="${x.n < 200 ? "thin" : ""}"><td>${EX_OUT[o] || o}</td>
        <td class="num hide-sm">${x.n}</td><td class="num">%${num(x.actual, 1)}</td>
        <td class="num">${(x.market ?? x.ref) == null ? "–" : "%" + num(x.market ?? x.ref, 1)}</td>
        <td class="num ${solid ? "yes" : ""}"><b>${edge == null ? "–" : pp1(edge)}</b></td>
        <td class="num hide-sm">${ci[0] == null ? "–" : `[${pp1(ci[0])}, ${pp1(ci[1])}]`}</td>
        <td>${ciBar(edge, ci[0], ci[1])}</td></tr>`;
    }).join("");
    const solidN = (d.outcomes_order || []).filter((o) => {
      const c = (d.outcomes[o] || {}).edge_ci || (d.outcomes[o] || {}).vs_ref_ci || [null, null];
      return c[0] != null && (c[0] > 0 || c[1] < 0);
    }).length;
    state.ex.cleared += solidN;
    const tests = state.ex.asked * (d.outcomes_order || []).length;
    $("#ex-out").innerHTML = `<p class="sentence">${exSentence()}</p>
      <p class="sentence">Bu tarife uyan <b>${d.n.toLocaleString("tr")} maç</b> bulundu
${d.n_exact !== d.n ? ` (tam eşleşen ${d.n_exact.toLocaleString("tr")})` : ""} —
        ${d.pool.toLocaleString("tr")} maçlık havuzda, ${d.span[0]} ile ${d.span[1]} arası.</p>
      ${d.n < 200 ? `<p class="ex-warn">Örneklem 200'ün altında. Bu satırlardan hiçbiri okunmamalı.</p>` : ""}
      <div class="table-wrap"><table><thead><tr><th>Sonuç</th><th class="num hide-sm">N</th><th class="num">Oldu</th>
        <th class="num">Fiyat</th><th class="num">Fark</th><th class="num hide-sm">%95 aralık</th><th>Sıfıra göre</th>
        </tr></thead><tbody>${rows || `<tr><td colspan="7">Bu desene uyan maç yok.</td></tr>`}</tbody></table></div>
      <p class="note"><b>Fiyat</b> sütunu: piyasanın fiyatı olan marketlerde (1X2, 2,5 üst) o maçların kendi fiyatı;
        olmayan marketlerde (İY, 1,5/3,5 üst, KG) <b>aynı fiyattaki maçlarda</b> aynı şeyin ne sıklıkta olduğu —
        havuz ortalaması değil, çünkü iyi takım seçen her desen havuz ortalamasını zaten geçer.
        Fark, havuz geneli sapma çıkarıldıktan sonradır. <b>Aralık sıfırı içeriyorsa desen, piyasanın zaten
        bildiği bir şeyi söylüyor.</b></p>
      <p class="ex-warn">Bu oturumda <b>${state.ex.asked} sorgu</b> çalıştırdın, her biri ${(d.outcomes_order || []).length}
        sonucu ölçtü: <b>${tests} test</b>. %95 aralıkla, hiçbir gerçek desen olmasa bile bunların yaklaşık
        <b>${Math.max(1, Math.round(tests * 0.05))} tanesinin</b> sıfırı dışlaması beklenir — şu ana kadar
        ${state.ex.cleared} tanesi dışladı. Üstelik bu dokuz test <b>bağımsız değil</b> — kazanır/berabere/kaybeder
        birbirini tamamlar, 1,5/2,5/3,5 üst aynı maçın gol sayısına bakar — yani birkaçının birlikte hareket etmesi
        beklenen bir şeydir, birbirini doğrulamaz. Buradan çıkan bir fikir bulgu değil, <b>adaydır</b>: gerçek sınav
        aşağıdaki üç pencereli tarama ve çoklu test düzeltmesidir.</p>`;
  }

  function renderResearch() {
    exWire();
    const d = state.rs || {};
    const sum = (d.models?.summary) || [];
    const market = sum.find((r) => r.model.startsWith("A"));
    const best = sum.filter((r) => r.brier_diff != null).sort((a, b) => a.brier_diff - b.brier_diff)[0];
    const st = d.state || {};
    $("#rs-verdict").innerHTML = market
      ? `Havuz: <b>${st.matches?.toLocaleString("tr")} maç</b> (${st.from} – ${st.to}). ${market.n.toLocaleString("tr")} maçlık
         ileriye dönük testte <b>hiçbir motor piyasayı geçemedi</b>; en iyisi ${esc(best?.model || "–")} ve o bile piyasadan
         ${pp1(1000 * (best?.brier_diff ?? 0))} binde Brier kadar geride. Bu sekmedeki her şey bu cümlenin altında okunmalı.`
      : `Havuz: <b>${st.matches?.toLocaleString("tr") || "?"} maç</b>. Model karşılaştırması henüz çalıştırılmadı.`;

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

    const notes = d.notes || [];
    $("#rs-notes").innerHTML = notes.length
      ? notes.map((r) => `<div class="rs-note"><h4>${r.no}. ${esc(r.title)} <small class="muted">· ${esc(r.side)} · N=${r.n}</small></h4>
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
      <section data-anchor="combo"><h3>İki takım birlikte <small class="muted">(koşul koşul)</small></h3>${whatFor("combo")}<div data-combo>Yükleniyor…</div></section>
      <section><h3>Nesine oranları ve defter notları</h3><div data-nesine>Yükleniyor…</div></section>
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
