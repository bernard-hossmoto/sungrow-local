/* sungrow-local: day / week / month / year switch for the history card.
   Week to year come from /api/days, one row per day from the inverter's counters. */
(async function () {
  await window.APP.ready;
  const { t, num, money } = window.APP;
  const card = document.getElementById("historycard");
  const head = card.querySelector(".chead"), title = card.querySelector(".ctitle");
  const daySvg = document.getElementById("daychart"), dayInfo = document.getElementById("day_info");
  const tip = document.getElementById("tip");
  const NS = "http://www.w3.org/2000/svg", X0 = 54, X1 = 1126, Y0 = 24, Y1 = 196;
  const L = window.APP.lang;
  let mode = "day", ref = new Date(), days = {};

  const css = document.createElement("style");
  css.textContent = `
    .pr-tabs{display:inline-flex;gap:2px;padding:2px;border-radius:9px;background:rgba(255,255,255,.05);border:1px solid var(--rand)}
    .pr-tabs button{background:none;border:0;color:var(--muted);font:inherit;font-size:12px;padding:4px 11px;border-radius:7px;cursor:pointer}
    .pr-tabs button:hover{color:var(--text)} .pr-tabs button.on{background:rgba(255,255,255,.1);color:var(--text)}
    .pr-right{margin-left:auto;display:none;align-items:center;gap:12px;font-size:12.5px;color:var(--muted);flex-wrap:wrap}
    .pr-nav{display:inline-flex;align-items:center;gap:6px}
    .pr-nav button{background:rgba(255,255,255,.05);border:1px solid var(--rand);color:var(--text);width:26px;height:26px;border-radius:7px;cursor:pointer;font-size:15px;line-height:1}
    .pr-nav button:disabled{opacity:.3;cursor:default}
    .pr-title{color:var(--text);min-width:150px;text-align:center}
    .pr-sum b{color:var(--text);font-weight:600}
    #periodchart{display:none;width:100%;height:auto}`;
  document.head.appendChild(css);

  const tabs = document.createElement("span");
  tabs.className = "pr-tabs";
  tabs.innerHTML = ["day", "week", "month", "year"].map(m => `<button data-m="${m}">${t(m)}</button>`).join("");
  title.after(tabs);
  const right = document.createElement("span");
  right.className = "pr-right";
  right.innerHTML = `<span class="pr-nav"><button data-d="-1" aria-label="back">‹</button><span class="pr-title"></span><button data-d="1" aria-label="forward">›</button></span><span class="pr-sum"></span>`;
  head.appendChild(right);
  const pTitle = right.querySelector(".pr-title"), pSum = right.querySelector(".pr-sum"), fwd = right.querySelector('[data-d="1"]');
  const svg = document.createElementNS(NS, "svg");
  svg.id = "periodchart"; svg.setAttribute("viewBox", "0 0 1140 230"); svg.setAttribute("role", "img");
  daySvg.after(svg);

  tabs.addEventListener("click", e => { const b = e.target.closest("button"); if (b) { mode = b.dataset.m; ref = new Date(); draw(); } });
  right.querySelector(".pr-nav").addEventListener("click", e => {
    const b = e.target.closest("button"); if (!b || b.disabled) return;
    const d = +b.dataset.d;
    if (mode === "week") ref.setDate(ref.getDate() + 7 * d);
    if (mode === "month") ref = new Date(ref.getFullYear(), ref.getMonth() + d, 1);
    if (mode === "year") ref = new Date(ref.getFullYear() + d, 0, 1);
    draw();
  });

  const de = () => window.APP.cfg.language === "de";
  const dm = d => de() ? `${d.getDate()}.${d.getMonth() + 1}.` : `${d.getDate()} ${L.months_short[d.getMonth()]}`;
  const longDay = (w, d) => de() ? `${w}, ${d.getDate()}. ${L.months[d.getMonth()]}` : `${w}, ${d.getDate()} ${L.months[d.getMonth()]}`;
  const iso = d => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
  function day(key) {
    const r = days[key]; if (!r) return null;
    const [pv, direct, charged, discharged, imported, exported] = r;
    return { pv, used: direct + discharged + imported, exported, imported };
  }
  function sum(list) {
    const s = { pv: 0, used: 0, exported: 0, imported: 0, n: 0 };
    for (const x of list) if (x) { s.pv += x.pv; s.used += x.used; s.exported += x.exported; s.imported += x.imported; s.n++; }
    return s.n ? s : null;
  }
  function isoWeek(d) {
    const u = new Date(Date.UTC(d.getFullYear(), d.getMonth(), d.getDate()));
    u.setUTCDate(u.getUTCDate() + 4 - (u.getUTCDay() || 7));
    return Math.ceil(((u - Date.UTC(u.getUTCFullYear(), 0, 1)) / 86400000 + 1) / 7);
  }

  function slots() {
    const today = new Date(); today.setHours(0, 0, 0, 0);
    if (mode === "week") {
      const mon = new Date(ref); mon.setHours(0, 0, 0, 0); mon.setDate(mon.getDate() - ((mon.getDay() + 6) % 7));
      const sun = new Date(mon); sun.setDate(mon.getDate() + 6);
      pTitle.textContent = `${t("week_short")} ${isoWeek(mon)} · ${dm(mon)} ${t("to")} ${dm(sun)}`;
      fwd.disabled = sun >= today;
      return L.weekdays.map((w, i) => { const d = new Date(mon); d.setDate(mon.getDate() + i);
        return { short: de() ? `${w} ${d.getDate()}.` : `${w} ${d.getDate()}`, long: longDay(w, d), v: day(iso(d)) }; });
    }
    if (mode === "month") {
      const y = ref.getFullYear(), m = ref.getMonth(), n = new Date(y, m + 1, 0).getDate();
      pTitle.textContent = `${L.months[m]} ${y}`;
      fwd.disabled = new Date(y, m + 1, 1) > today;
      return Array.from({ length: n }, (_, i) => { const d = new Date(y, m, i + 1);
        return { short: String(i + 1), long: longDay(L.weekdays[(d.getDay() + 6) % 7], d), v: day(iso(d)) }; });
    }
    const y = ref.getFullYear();
    pTitle.textContent = String(y);
    fwd.disabled = y >= today.getFullYear();
    return L.months_short.map((k, m) => ({ short: k, long: `${L.months[m]} ${y}`,
      v: sum(Array.from({ length: new Date(y, m + 1, 0).getDate() }, (_, i) => day(iso(new Date(y, m, i + 1))))) }));
  }

  const el = (n, a) => { const e = document.createElementNS(NS, n); for (const k in a) e.setAttribute(k, a[k]); return e; };
  function column(x, w, y, color) {
    const h = Y1 - y; if (h < 0.5) return null;
    const r = Math.min(3, w / 2, h);
    return el("path", { d: `M${x},${Y1} V${y + r} Q${x},${y} ${x + r},${y} H${x + w - r} Q${x + w},${y} ${x + w},${y + r} V${Y1} Z`, fill: color });
  }

  function draw() {
    tabs.querySelectorAll("button").forEach(b => b.classList.toggle("on", b.dataset.m === mode));
    const isDay = mode === "day";
    daySvg.style.display = isDay ? "" : "none"; dayInfo.style.display = isDay ? "" : "none";
    svg.style.display = isDay ? "none" : "block"; right.style.display = isDay ? "none" : "flex";
    tip.style.opacity = 0;
    if (isDay) return;

    const s = slots(), total = sum(s.map(x => x.v)), cfg = window.APP.cfg;
    pSum.innerHTML = total ? t("period_sum", { pv: num(total.pv, 1), ex: num(total.exported, 1) }) +
      (cfg.feed_in_tariff ? t("period_money", { m: money(total.exported * cfg.feed_in_tariff) }) : "") : "";
    svg.textContent = "";
    const peak = Math.max(1, ...s.map(x => x.v ? Math.max(x.v.pv, x.v.used) : 0));
    const max = [2, 4, 8, 12, 16, 20, 24, 40, 60, 80, 100, 120, 160, 200, 240, 400, 600, 800, 1000, 1200, 1600, 2000, 2400, 4000]
      .find(v => v >= peak * 1.08) || peak * 1.1;
    const y = v => Y1 - Math.min(v, max) / max * (Y1 - Y0);
    for (let i = 0; i <= 4; i++) {
      const v = max * i / 4, yy = y(v);
      svg.appendChild(el("line", { x1: X0, x2: X1, y1: yy, y2: yy, stroke: "#1b2740" }));
      const tx = el("text", { x: X0 - 10, y: yy + 4, "font-size": 11, fill: "#6c7c99", "text-anchor": "end" });
      tx.textContent = num(v, v % 1 ? 1 : 0); svg.appendChild(tx);
    }
    const unit = el("text", { x: X0 - 10, y: Y0 - 12, "font-size": 10.5, fill: "#55637d", "text-anchor": "end" });
    unit.textContent = "kWh"; svg.appendChild(unit);
    if (!total) {
      const tx = el("text", { x: (X0 + X1) / 2, y: (Y0 + Y1) / 2, "font-size": 13, fill: "#6c7c99", "text-anchor": "middle" });
      tx.textContent = t("period_empty"); svg.appendChild(tx);
    }
    const slot = (X1 - X0) / s.length, group = Math.min(slot * 0.72, 64), w = (group - 2) / 2;
    const every = s.length > 20 && slot < 30 ? 2 : 1;
    s.forEach((it, i) => {
      const xm = X0 + slot * (i + 0.5), xl = xm - group / 2, g = el("g", {});
      if (it.v) {
        const a = column(xl, w, y(it.v.pv), "#fbbf24"), b = column(xl + w + 2, w, y(it.v.used), "#22d3ee");
        if (a) g.appendChild(a); if (b) g.appendChild(b);
      }
      if (i % every === 0) {
        const tx = el("text", { x: xm, y: 216, "font-size": 11, fill: "#6c7c99", "text-anchor": "middle" });
        tx.textContent = it.short; g.appendChild(tx);
      }
      const hit = el("rect", { x: X0 + slot * i, y: Y0 - 6, width: slot, height: Y1 - Y0 + 30, fill: "transparent" });
      g.appendChild(hit);
      hit.addEventListener("mouseenter", () => showTip(it, xm, it.v ? y(Math.max(it.v.pv, it.v.used)) : Y1, g));
      hit.addEventListener("mouseleave", () => { tip.style.opacity = 0; svg.querySelectorAll("g").forEach(e => e.style.opacity = 1); });
      svg.appendChild(g);
    });
  }

  function showTip(it, x, yTop, g) {
    if (!it.v) { tip.style.opacity = 0; return; }
    svg.querySelectorAll("g").forEach(e => e.style.opacity = e === g ? 1 : 0.45);
    const r = svg.getBoundingClientRect(), rc = card.getBoundingClientRect(), k = 1140 / r.width, v = it.v, cfg = window.APP.cfg;
    const autarky = v.used ? Math.round((1 - v.imported / v.used) * 100) : null;
    tip.innerHTML = `<b>${it.long}</b><br>${t("tip_produced")} <b style="color:var(--sun)">${num(v.pv, 1)} kWh</b>` +
      `<br>${t("tip_used")} <b style="color:var(--house)">${num(v.used, 1)} kWh</b>` +
      `<br>${t("tip_exported")} <b style="color:var(--grid)">${num(v.exported, 1)} kWh</b>` +
      (cfg.feed_in_tariff ? ` · ${money(v.exported * cfg.feed_in_tariff)}` : "") +
      `<br>${t("tip_imported")} ${num(v.imported, 1)} kWh` + (autarky != null ? ` · ${t("autarky")} ${autarky} %` : "");
    tip.style.left = (r.left - rc.left + x / k) + "px";
    tip.style.top = (r.top - rc.top + yTop / k) + "px";
    tip.style.opacity = 1;
  }

  async function load() {
    try {
      const r = await fetch("api/days", { cache: "no-store" });
      if (!r.ok) return;
      days = {};
      for (const row of (await r.json()).days || []) days[row[0]] = row.slice(1);
      if (mode !== "day") draw();
    } catch (e) { /* keep the last state */ }
  }
  window.showPeriod = (m, date) => { mode = m; ref = date ? new Date(date) : new Date(); draw(); };
  draw(); await load(); setInterval(load, 300000);
})();
