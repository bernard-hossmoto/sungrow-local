/* sungrow-local: isometric scene with a generic house, PV roof, battery and grid.
   Coordinates are metres on the ground plan: a along the house, b across it (front +),
   h is the height. The scene scales itself into the 1180 x 600 view box. */

const RAD = Math.PI / 180, C30 = Math.cos(Math.PI / 6), PHI = -22 * RAD;
const CP = Math.cos(PHI), SP = Math.sin(PHI);
let S = 1, OX = 0, OY = 0;
const P = (a, b, h = 0) => {
  const x = a * CP - b * SP, y = a * SP + b * CP;
  return [OX + (x - y) * C30 * S, OY + (x + y) * 0.5 * S - h * S];
};
const PL = ps => ps.map(p => p[0].toFixed(1) + "," + p[1].toFixed(1)).join(" ");

const C = {
  grass1: "#3c6b48", grass2: "#28462f", soil: "#2f261c", soil2: "#241d15", path: "#6b675f",
  wall: "#ece6d8", wallSide: "#c9c0ad", roof: "#4f5458", roofDark: "#3a3e42", trim: "#80878a",
  glass: "#2a3c5e", door: "#5b4636", trunk: "#4a3a2a", leaf1: "#2e5a39", leaf2: "#3d7448", leaf3: "#4b8a56",
  sun: "#fbbf24", batt: "#34d399", grid: "#a78bfa", house: "#22d3ee"
};
const EDGE = 'stroke="#00000055" stroke-width="1.2" stroke-linejoin="round"';

const GROUND = [[-22, -9], [-8, -13], [10, -13], [21, -8], [23, 3], [16, 12], [2, 14], [-14, 12], [-23, 4]];
const HOUSE = { a0: -5.5, a1: 5.5, b0: -4.3, b1: 4.3, wall: 5.6, pitch: 38, over: 0.5 };
const BATTERY = { a: 7.6, b: 1.2 };
const POLE = { a: -15, b: 7 };
const TREES = [[-12, -7, 2.6], [-17, -2, 2.1], [10, -8, 2.8], [15, -3, 2.2], [17, 7, 1.9], [-9, 9.5, 1.6]];

let out = [];
const put = s => out.push(s);
const poly = (ps, fill, extra = "") => put(`<polygon points="${PL(ps)}" fill="${fill}" ${extra}/>`);
const line = (p, q, stroke, w = 1) => put(`<line x1="${p[0].toFixed(1)}" y1="${p[1].toFixed(1)}" x2="${q[0].toFixed(1)}" y2="${q[1].toFixed(1)}" stroke="${stroke}" stroke-width="${w}"/>`);
const label = (p, s, color, dy = 0) => put(`<text x="${p[0].toFixed(1)}" y="${(p[1] + dy).toFixed(1)}" font-size="11" fill="${color}" text-anchor="middle" letter-spacing=".4">${s}</text>`);

function fit() {
  const pts = [];
  for (const [a, b] of GROUND) pts.push([a, b, 0], [a, b, -3]);
  const H = HOUSE, ridge = H.wall + (H.b1 - H.b0) / 2 * Math.tan(H.pitch * RAD);
  pts.push([H.a0, 0, ridge], [H.a1, 0, ridge], [POLE.a, POLE.b, 8.5]);
  for (const [a, b, r] of TREES) pts.push([a, b, 5 + r]);
  S = 1; OX = 0; OY = 0;
  const q = pts.map(([a, b, h]) => P(a, b, h));
  const minX = Math.min(...q.map(p => p[0])), maxX = Math.max(...q.map(p => p[0]));
  const minY = Math.min(...q.map(p => p[1])), maxY = Math.max(...q.map(p => p[1]));
  S = Math.min((1180 - 120) / (maxX - minX), (600 - 110) / (maxY - minY));
  OX = 60 - minX * S + ((1180 - 120) - (maxX - minX) * S) / 2;
  OY = 70 - minY * S;
}

function ground() {
  put(`<linearGradient id="lawn" x1="0" y1="0" x2="0.7" y2="1"><stop offset="0" stop-color="${C.grass1}"/><stop offset="1" stop-color="${C.grass2}"/></linearGradient>`);
  for (let i = 0; i < GROUND.length; i++) {
    const [a1, b1] = GROUND[i], [a2, b2] = GROUND[(i + 1) % GROUND.length];
    poly([P(a1, b1), P(a2, b2), P(a2, b2, -2.6), P(a1, b1, -2.6)], (a1 + b1 + a2 + b2) / 2 > -6 ? C.soil : C.soil2);
  }
  poly(GROUND.map(([a, b]) => P(a, b)), "url(#lawn)");
  poly([[-3.0, 4.3], [-1.2, 4.3], [-0.2, 13.6], [-2.4, 13.8]].map(([a, b]) => P(a, b)), C.path, 'opacity=".75"');
  poly([[-5.5, 4.3], [5.5, 4.3], [5.5, 6.6], [-5.5, 6.6]].map(([a, b]) => P(a, b)), "#5d5a52", 'opacity=".55"');
}

function tree(a, b, r) {
  const k = P(a, b, 3.3 + r);
  line(P(a, b), P(a, b, 2.8 + r * 0.4), C.trunk, 0.35 * S);
  put(`<ellipse cx="${k[0].toFixed(1)}" cy="${k[1].toFixed(1)}" rx="${(r * S).toFixed(1)}" ry="${(r * S * 0.85).toFixed(1)}" fill="${C.leaf1}"/>`);
  put(`<ellipse cx="${(k[0] - r * S * .28).toFixed(1)}" cy="${(k[1] - r * S * .3).toFixed(1)}" rx="${(r * S * .6).toFixed(1)}" ry="${(r * S * .5).toFixed(1)}" fill="${C.leaf2}"/>`);
  put(`<ellipse cx="${(k[0] - r * S * .42).toFixed(1)}" cy="${(k[1] - r * S * .52).toFixed(1)}" rx="${(r * S * .28).toFixed(1)}" ry="${(r * S * .22).toFixed(1)}" fill="${C.leaf3}" opacity=".8"/>`);
}

function house() {
  const H = HOUSE, bm = (H.b0 + H.b1) / 2, st = Math.tan(H.pitch * RAD);
  const ridge = H.wall + (H.b1 - H.b0) / 2 * st, ov = H.over, eave = H.wall - ov * st;
  poly([P(H.a0 + 1.4, H.b0 + 1), P(H.a1 + 1.4, H.b0 + 1), P(H.a1 + 1.4, H.b1 + 1), P(H.a0 + 1.4, H.b1 + 1)], "#0b1a14", 'opacity=".4"');

  // front wall and gable
  poly([P(H.a0, H.b1), P(H.a1, H.b1), P(H.a1, H.b1, H.wall), P(H.a0, H.b1, H.wall)], C.wall);
  poly([P(H.a1, H.b0), P(H.a1, H.b1), P(H.a1, H.b1, H.wall), P(H.a1, bm, ridge), P(H.a1, H.b0, H.wall)], C.wallSide);
  poly([P(H.a0, H.b1, 0), P(H.a1, H.b1, 0), P(H.a1, H.b1, 0.45), P(H.a0, H.b1, 0.45)], C.trim, 'opacity=".6"');

  const win = (a, h, w, ht, fill = C.glass) => {
    poly([P(a - w / 2 - .12, H.b1, h - .12), P(a + w / 2 + .12, H.b1, h - .12), P(a + w / 2 + .12, H.b1, h + ht + .12), P(a - w / 2 - .12, H.b1, h + ht + .12)], C.trim);
    poly([P(a - w / 2, H.b1, h), P(a + w / 2, H.b1, h), P(a + w / 2, H.b1, h + ht), P(a - w / 2, H.b1, h + ht)], fill);
  };
  const gwin = (b, h, w, ht) => {
    poly([P(H.a1, b - w / 2 - .12, h - .12), P(H.a1, b + w / 2 + .12, h - .12), P(H.a1, b + w / 2 + .12, h + ht + .12), P(H.a1, b - w / 2 - .12, h + ht + .12)], C.trim);
    poly([P(H.a1, b - w / 2, h), P(H.a1, b + w / 2, h), P(H.a1, b + w / 2, h + ht), P(H.a1, b - w / 2, h + ht)], C.glass);
  };
  win(-2.1, 0.45, 1.05, 2.15, C.door);
  for (const a of [-4.0, 0.6, 3.4]) win(a, 1.0, 1.25, 1.35);
  for (const a of [-3.4, 0, 3.4]) win(a, 3.4, 1.25, 1.25);
  for (const b of [-1.9, 1.9]) { gwin(b, 1.0, 1.1, 1.35); gwin(b, 3.4, 1.1, 1.25); }
  gwin(0, 6.4, 0.9, 0.9);

  // chimney
  const ch = [-3.2, -1.2];
  poly([P(ch[0] + .35, ch[1] + .35, ridge - 1.2), P(ch[0] + .35, ch[1] - .35, ridge - 1.2), P(ch[0] + .35, ch[1] - .35, ridge + 0.9), P(ch[0] + .35, ch[1] + .35, ridge + 0.9)], C.wallSide);
  poly([P(ch[0] - .35, ch[1] + .35, ridge - 1.2), P(ch[0] + .35, ch[1] + .35, ridge - 1.2), P(ch[0] + .35, ch[1] + .35, ridge + 0.9), P(ch[0] - .35, ch[1] + .35, ridge + 0.9)], C.wall);
  poly([P(ch[0] - .45, ch[1] - .45, ridge + 0.9), P(ch[0] + .45, ch[1] - .45, ridge + 0.9), P(ch[0] + .45, ch[1] + .45, ridge + 0.9), P(ch[0] - .45, ch[1] + .45, ridge + 0.9)], C.roofDark);
  // roof: the back face is hidden at this pitch, the front face carries the PV array
  poly([P(H.a0 - ov, bm, ridge), P(H.a1 + ov, bm, ridge), P(H.a1 + ov, H.b1 + ov, eave), P(H.a0 - ov, H.b1 + ov, eave)], C.roof, EDGE);
  line(P(H.a0 - ov, bm, ridge), P(H.a1 + ov, bm, ridge), "#ffffff40", 1.6);
  line(P(H.a0 - ov, H.b1 + ov, eave), P(H.a1 + ov, H.b1 + ov, eave), "#00000055", 1.4);

  const slope = (H.b1 - bm) / Math.cos(H.pitch * RAD), pw = 1.13, ph = 1.72, cols = 8, rows = 2;
  const left = (H.a0 + H.a1) / 2 + (cols * (pw + .03)) / 2;
  let mid = null;
  for (let r = 0; r < rows; r++) for (let c = 0; c < cols; c++) {
    const v0 = (0.55 + r * (ph + .05)) / slope, v1 = v0 + ph / slope;
    const u1 = left - c * (pw + .03), u0 = u1 - pw;
    const pt = (u, v) => P(u, H.b1 + v * (bm - H.b1), H.wall + v * (ridge - H.wall));
    poly([pt(u0, v0), pt(u1, v0), pt(u1, v1), pt(u0, v1)], "url(#pvGlass)", 'stroke="#5b7fc7" stroke-width=".7" stroke-opacity=".6"');
    if (r === 1 && c === 3) mid = pt(u0, (v0 + v1) / 2);
  }
  return mid;
}

function cabinet(a, b) {
  const la = 1.3, lb = 0.8, h = 2.0, a0 = a - la / 2, a1 = a + la / 2, b0 = b - lb / 2, b1 = b + lb / 2;
  poly([P(a0 + .4, b0 + .3), P(a1 + .4, b0 + .3), P(a1 + .4, b1 + .3), P(a0 + .4, b1 + .3)], "#0b1a14", 'opacity=".45"');
  poly([P(a0, b1), P(a1, b1), P(a1, b1, h), P(a0, b1, h)], "#273350");
  poly([P(a1, b0), P(a1, b1), P(a1, b1, h), P(a1, b0, h)], "#1a2234");
  poly([P(a0, b0, h), P(a1, b0, h), P(a1, b1, h), P(a0, b1, h)], "#323f5e");
  for (let i = 0; i < 4; i++) {
    const h0 = .3 + i * .42;
    poly([P(a0 + .15, b1, h0), P(a1 - .15, b1, h0), P(a1 - .15, b1, h0 + .3), P(a0 + .15, b1, h0 + .3)], C.batt, 'class="cell" opacity=".2"');
  }
}

function pole(a, b, h = 8) {
  line(P(a, b), P(a, b, h), "#6b7280", 0.32 * S);
  line(P(a - 1.5, b, h - .6), P(a + 1.5, b, h - .6), "#6b7280", 0.22 * S);
  line(P(a, b - 1.3, h - 1.7), P(a, b + 1.3, h - 1.7), "#6b7280", 0.22 * S);
  for (const d of [-1.5, 0, 1.5]) { const q = P(a + d, b, h - .6); put(`<circle cx="${q[0].toFixed(1)}" cy="${q[1].toFixed(1)}" r="2.4" fill="#9aa5b5"/>`); }
  return P(a, b, h);
}

function buildScene(L) {
  fit();
  out = [];
  ground();
  const order = TREES.filter(([a, b]) => a + b < 0).concat([null]).concat(TREES.filter(([a, b]) => a + b >= 0));
  let pvMid = null, poleTop = null;
  for (const tr of order) {
    if (tr) { tree(...tr); continue; }
    poleTop = pole(POLE.a, POLE.b);
    pvMid = house();
    cabinet(BATTERY.a, BATTERY.b);
  }
  label(P(BATTERY.a, BATTERY.b + 1.4, 0), L.battery_label, "#7fd9b4", 14);
  label(poleTop, L.grid_label, "#9d8ad6", -16);
  document.getElementById("scene").innerHTML = out.join("\n");

  const pv = [pvMid[0], pvMid[1] - 4], houseP = P(-1.5, HOUSE.b1, 3.2), batt = P(BATTERY.a, BATTERY.b, 2.2);
  const arc = (p, q, lift, id, color) =>
    `<path id="${id}" d="M${p[0].toFixed(1)},${p[1].toFixed(1)} Q${((p[0] + q[0]) / 2).toFixed(1)},${((p[1] + q[1]) / 2 - lift).toFixed(1)} ${q[0].toFixed(1)},${q[1].toFixed(1)}" fill="none" stroke="${color}" stroke-width="3" stroke-linecap="round" class="off"/>`;
  document.getElementById("flows").innerHTML = [
    arc(pv, houseP, 40, "l_pv_house", C.sun),
    arc(pv, batt, 60, "l_pv_batt", C.sun),
    arc(pv, poleTop, 110, "l_pv_grid", C.sun),
    arc(batt, houseP, 70, "l_batt_house", C.batt),
    arc(poleTop, houseP, 50, "l_grid_house", C.grid),
    arc(poleTop, batt, 150, "l_grid_batt", C.grid)
  ].join("\n");

  const pill = (p, id, color, dx = 0, dy = 0) =>
    `<g transform="translate(${(p[0] + dx - 40).toFixed(1)},${(p[1] + dy - 14).toFixed(1)})"><rect width="80" height="28" rx="14" fill="#0a1222" fill-opacity=".85" stroke="${color}" stroke-opacity=".55"/><text id="${id}" x="40" y="19" font-size="13.5" font-weight="700" fill="${color}" text-anchor="middle">–</text></g>`;
  document.getElementById("pills").innerHTML = [
    pill(pv, "p_pv", C.sun, 0, -34),
    pill(batt, "p_batt", C.batt, 70, -10),
    pill(houseP, "p_house", C.house, -96, 40),
    pill(poleTop, "p_grid", C.grid, -62, -34)
  ].join("\n");
}
