/* sungrow-local: live values, tiles, energy flows, day chart and balance table. */

const I18N = {
  en: {
    production: "Production", storage: "Battery", consumption: "Consumption", grid: "Grid",
    generation: "Production", whole_house: "whole house", history: "History", balance: "Energy balance",
    produced: "Produced", direct: "Direct use", from_storage: "From battery", exported: "Exported",
    imported: "Imported", used: "Consumed", autarky: "Autarky", revenue: "Revenue",
    today: "Today", total: "Total", battery: "Battery",
    footer: "Read directly from the inverter over Modbus, no cloud",
    today_yield: "Today {v} kWh", charging: "charging {v}", supplying: "supplying {v}", idle: "idle",
    importing: "import", exporting: "export", balanced: "balanced",
    connecting: "connecting …", updated: "updated {v}", offline: "no connection to the inverter",
    no_values: "no readings yet", points: "{n} readings · {v} kWh produced",
    tariff_note: "Revenue at {v} per exported kWh", capacity: "battery {v} kWh",
    day: "Day", week: "Week", month: "Month", year: "Year", week_short: "Wk", to: "to",
    period_sum: "<b>{pv}</b> kWh produced · <b>{ex}</b> kWh exported",
    period_money: " · <b>{m}</b>", period_empty: "No daily values for this period yet",
    tip_produced: "Produced", tip_used: "Consumed", tip_exported: "Exported", tip_imported: "Imported",
    months: ["January","February","March","April","May","June","July","August","September","October","November","December"],
    months_short: ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"],
    weekdays: ["Mon","Tue","Wed","Thu","Fri","Sat","Sun"],
    house: "House", grid_label: "Grid", battery_label: "Inverter · Battery"
  },
  de: {
    production: "Erzeugung", storage: "Speicher", consumption: "Verbrauch", grid: "Netz",
    generation: "Erzeugung", whole_house: "ganzes Haus", history: "Verlauf", balance: "Energiebilanz",
    produced: "Erzeugt", direct: "Direkt", from_storage: "Aus Speicher", exported: "Eingespeist",
    imported: "Bezogen", used: "Verbrauch", autarky: "Autarkie", revenue: "Erlös",
    today: "Heute", total: "Gesamt", battery: "Batterie",
    footer: "Daten direkt vom Wechselrichter über Modbus, ohne Cloud",
    today_yield: "Heute {v} kWh", charging: "lädt mit {v}", supplying: "liefert {v}", idle: "Ruhe",
    importing: "Bezug", exporting: "Einspeisung", balanced: "ausgeglichen",
    connecting: "verbinde …", updated: "aktualisiert {v}", offline: "keine Verbindung zum Wechselrichter",
    no_values: "noch keine Messwerte", points: "{n} Messpunkte · {v} kWh erzeugt",
    tariff_note: "Erlös mit {v} je eingespeister kWh", capacity: "Speicher {v} kWh",
    day: "Tag", week: "Woche", month: "Monat", year: "Jahr", week_short: "KW", to: "bis",
    period_sum: "<b>{pv}</b> kWh erzeugt · <b>{ex}</b> kWh eingespeist",
    period_money: " · <b>{m}</b>", period_empty: "Für diesen Zeitraum gibt es noch keine Tageswerte",
    tip_produced: "Erzeugt", tip_used: "Verbraucht", tip_exported: "Eingespeist", tip_imported: "Bezogen",
    months: ["Jänner","Februar","März","April","Mai","Juni","Juli","August","September","Oktober","November","Dezember"],
    months_short: ["Jän","Feb","Mär","Apr","Mai","Jun","Jul","Aug","Sep","Okt","Nov","Dez"],
    weekdays: ["Mo","Di","Mi","Do","Fr","Sa","So"],
    house: "Haus", grid_label: "Netz", battery_label: "Wechselrichter · Speicher"
  }
};

let CFG = { plant_name: "sungrow-local", peak_power_kw: 10, feed_in_tariff: 0, currency: "€", language: "en" };
let L = I18N.en;
const $ = id => document.getElementById(id);
const t = (k, vars) => { let s = L[k] != null ? L[k] : k; for (const v in vars || {}) s = s.replace("{" + v + "}", vars[v]); return s; };
const num = (v, d = 1) => Number(v).toLocaleString(CFG.language === "de" ? "de-AT" : "en-GB",
  { minimumFractionDigits: d, maximumFractionDigits: d });
const W = v => Math.abs(v) >= 1000 ? num(v / 1000, 2) + " kW" : Math.round(v) + " W";
const money = v => CFG.language === "de" ? num(v, 2) + " " + CFG.currency : CFG.currency + num(v, 2);
window.APP = { t, num, W, money, get cfg() { return CFG; }, get lang() { return L; } };

function applyLanguage() {
  L = I18N[CFG.language] || I18N.en;
  document.documentElement.lang = CFG.language;
  document.querySelectorAll("[data-t]").forEach(el => el.textContent = t(el.dataset.t));
  $("plant").textContent = CFG.plant_name;
  document.title = CFG.plant_name;
  $("sub").textContent = num(CFG.peak_power_kw, 1) + " kWp";
  $("status").textContent = t("connecting");
  if (!CFG.feed_in_tariff) document.querySelectorAll(".rev").forEach(el => el.style.display = "none");
}

/* ---------- live values ---------- */

// Moving average over the last three readings for the instantaneous powers only,
// so the numbers do not jump around. Counters and state of charge stay raw.
const smooth = { pv: [], batt: [], grid: [] };
function avg(series, value) { series.push(value); if (series.length > 3) series.shift(); return series.reduce((a, b) => a + b, 0) / series.length; }
const THRESHOLD = 20;   // watts before an energy flow is drawn

function flow(id, on, power) {
  const el = $(id); if (!el) return;
  el.classList.toggle("off", !on);
  el.classList.toggle("flow", on);
  if (on) {
    el.style.strokeWidth = (2.5 + Math.min(4, power / 1200 * 4)).toFixed(1);
    el.style.animationDuration = Math.max(0.35, 1.4 - Math.min(1, power / 5000)).toFixed(2) + "s";
  }
}

function show(d) {
  const pv = avg(smooth.pv, d.pv), batt = avg(smooth.batt, d.battery), grid = avg(smooth.grid, d.grid);
  const house = Math.max(0, pv + batt + grid);      // batt > 0 discharging, grid > 0 import
  const peak = CFG.peak_power_kw * 1000;

  $("p_pv").textContent = W(pv); $("p_batt").textContent = W(Math.abs(batt));
  $("p_house").textContent = W(house); $("p_grid").textContent = W(Math.abs(grid));

  $("v_pv").innerHTML = Math.round(pv) + "<small>W</small>";
  $("v_soc").innerHTML = num(d.soc, 1) + "<small>%</small>";
  $("v_house").innerHTML = Math.round(house) + "<small>W</small>";
  $("v_grid").innerHTML = Math.round(Math.abs(grid)) + "<small>W</small>";
  $("n_pv").textContent = t("today_yield", { v: num(d.today.pv, 1) });
  $("n_batt").textContent = batt < -5 ? t("charging", { v: W(-batt) }) : batt > 5 ? t("supplying", { v: W(batt) }) : t("idle");
  $("n_grid").textContent = grid > THRESHOLD ? t("importing") : grid < -THRESHOLD ? t("exporting") : t("balanced");

  $("b_pv").style.width = Math.min(100, pv / peak * 100) + "%";
  $("b_soc").style.width = d.soc + "%";
  $("b_house").style.width = Math.min(100, house / 6000 * 100) + "%";
  $("b_grid").style.width = Math.min(100, Math.abs(grid) / 6000 * 100) + "%";

  flow("l_pv_house", pv > THRESHOLD && house > THRESHOLD, Math.min(pv, house));
  flow("l_pv_batt", pv > THRESHOLD && batt < -THRESHOLD, -batt);
  flow("l_pv_grid", pv > THRESHOLD && grid < -THRESHOLD, -grid);
  flow("l_batt_house", batt > THRESHOLD, batt);
  flow("l_grid_house", grid > THRESHOLD, grid);
  flow("l_grid_batt", grid > THRESHOLD && batt < -THRESHOLD, -batt);
  $("sun").style.opacity = pv > 5 ? 1 : 0.22;
  document.querySelectorAll(".cell").forEach((c, i) => c.style.opacity = d.soc >= (i + 1) * 25 - 12 ? 0.95 : 0.16);

  balance(d);
  $("f_bv").textContent = num(d.battery_voltage, 1) + " V";
  $("f_bt").textContent = num(d.battery_temp, 1) + " °C";
  $("status").textContent = t("updated", { v: (d.time || "").slice(11, 16) });
  $("led").className = "dot";
}

const kwh = v => v == null ? "–" : (v >= 1000 ? num(v / 1000, 2) + "<small>MWh</small>" : num(v, 1) + "<small>kWh</small>");
function balance(d) {
  for (const [p, part] of [["t", d.today], ["g", d.total]]) {
    for (const k of ["pv", "direct", "discharged", "exported", "imported", "consumption"]) $(p + "_" + k).innerHTML = kwh(part[k]);
    $(p + "_autarky").innerHTML = part.autarky == null ? "–" : Math.round(part.autarky) + "<small>%</small>";
    $(p + "_revenue").innerHTML = money(part.revenue);
  }
  $("bal_info").textContent = (CFG.feed_in_tariff ? t("tariff_note", { v: money(CFG.feed_in_tariff) }) + " · " : "") +
    t("capacity", { v: num(d.battery_capacity, 1) });
}

/* ---------- day chart ---------- */

const X0 = 54, X1 = 1126, Y0 = 24, Y1 = 196;
let dayData = [], dayMax = 1000;
const dx = m => X0 + m / 1440 * (X1 - X0);
const dy = w => Y1 - Math.min(w, dayMax) / dayMax * (Y1 - Y0);
function path(ds, i, area) {
  if (!ds.length) return "";
  const p = ds.map((d, k) => (k ? "L" : "M") + dx(d[0]).toFixed(1) + "," + dy(d[i]).toFixed(1)).join(" ");
  return area ? p + ` L${dx(ds[ds.length - 1][0]).toFixed(1)},${Y1} L${dx(ds[0][0]).toFixed(1)},${Y1} Z` : p;
}

function drawDay(ds) {
  dayData = ds;
  if (!ds.length) { $("day_info").textContent = t("no_values"); return; }
  const peak = Math.max(...ds.map(d => Math.max(d[1], d[2])), 500);
  dayMax = ([2, 4, 6, 8, 10, 12, 16, 20, 24, 32, 40, 60].find(s => s * 1000 >= peak * 1.08) || 80) * 1000;
  let g = "";
  for (let i = 0; i <= 4; i++) {
    const w = dayMax * i / 4, y = dy(w);
    g += `<line x1="${X0}" y1="${y.toFixed(1)}" x2="${X1}" y2="${y.toFixed(1)}" stroke="#1b2740"/>`;
    g += `<text x="${X0 - 10}" y="${(y + 4).toFixed(1)}" font-size="11" fill="#6c7c99" text-anchor="end">${num(w / 1000, w % 1000 ? 1 : 0)}</text>`;
  }
  g += `<text x="${X0 - 10}" y="${Y0 - 12}" font-size="10.5" fill="#55637d" text-anchor="end">kW</text>`;
  $("d_grid").innerHTML = g;
  let a = "";
  for (let h = 0; h <= 24; h += 3) a += `<text x="${dx(h * 60).toFixed(1)}" y="216" font-size="11" fill="#6c7c99" text-anchor="middle">${h}:00</text>`;
  $("d_axis").innerHTML = a;
  $("d_pv_a").setAttribute("d", path(ds, 1, true)); $("d_house_a").setAttribute("d", path(ds, 2, true));
  $("d_pv_l").setAttribute("d", path(ds, 1, false)); $("d_house_l").setAttribute("d", path(ds, 2, false));
  const energy = ds.reduce((s, d, k) => k ? s + d[1] * (d[0] - ds[k - 1][0]) / 60000 : 0, 0);
  $("day_info").textContent = t("points", { n: ds.length, v: num(energy, 1) });
}

(function hover() {
  const svg = $("daychart"), hit = $("d_hit"), cur = $("d_cursor"), tip = $("tip"), card = $("historycard");
  const clock = m => String(Math.floor(m / 60)).padStart(2, "0") + ":" + String(m % 60).padStart(2, "0");
  hit.addEventListener("mousemove", e => {
    if (!dayData.length) return;
    const r = svg.getBoundingClientRect(), k = 1140 / r.width;
    const m = Math.max(0, Math.min(1440, ((e.clientX - r.left) * k - X0) / (X1 - X0) * 1440));
    let best = dayData[0];
    for (const d of dayData) if (Math.abs(d[0] - m) < Math.abs(best[0] - m)) best = d;
    const x = dx(best[0]);
    cur.style.display = "";
    $("d_cl").setAttribute("x1", x); $("d_cl").setAttribute("x2", x);
    $("d_cp").setAttribute("cx", x); $("d_cp").setAttribute("cy", dy(best[1]));
    $("d_ch").setAttribute("cx", x); $("d_ch").setAttribute("cy", dy(best[2]));
    tip.innerHTML = `<b>${clock(best[0])}</b><br>${t("generation")} <b style="color:var(--sun)">${W(best[1])}</b><br>${t("consumption")} <b style="color:var(--house)">${W(best[2])}</b>`;
    const rc = card.getBoundingClientRect();     // SVG elements have no offsetLeft
    tip.style.left = (r.left - rc.left + x / k) + "px";
    tip.style.top = (r.top - rc.top + dy(Math.max(best[1], best[2])) / k) + "px";
    tip.style.opacity = 1;
  });
  hit.addEventListener("mouseleave", () => { cur.style.display = "none"; tip.style.opacity = 0; });
})();

/* ---------- polling ---------- */

async function pollNow() {
  try {
    const r = await fetch("api/now", { cache: "no-store" });
    if (!r.ok) throw new Error(r.status);
    show(await r.json());
  } catch (e) {
    $("status").textContent = t("offline");
    $("led").className = "dot dead";
  }
}
async function pollDay() {
  try {
    const r = await fetch("api/day", { cache: "no-store" });
    if (r.ok) drawDay((await r.json()).points || []);
  } catch (e) { /* keep the last chart */ }
}

window.APP.ready = (async function start() {
  try { const r = await fetch("api/config"); if (r.ok) CFG = Object.assign(CFG, await r.json()); } catch (e) { }
  applyLanguage();
  buildScene(L);
  pollNow(); setInterval(pollNow, 10000);
  pollDay(); setInterval(pollDay, 120000);
})();
