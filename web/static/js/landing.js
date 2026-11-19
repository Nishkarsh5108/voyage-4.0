// 01 · The collapse. 5,187 real Dubai lodging listings at their true coordinates; on scroll, the pairs the pipeline accepted draw
// as hairlines and every multi-record cluster slides into one canonical point. Positions, edges and clusters come from
// web/static/data/landing.json (clusters.parquet + pairs.parquet); the counter is computed from those clusters as they merge.

import { MapGL, hexRGBA, segmentsFrom } from "./gl.js";
import { $, el, esc, clamp, fmt, reduced, projector, SHAPE_ID, SOURCES, srcBadge, mark, drawMark, shapeOf, labelOf } from "./util.js";

const T0 = 0.14, T1 = 0.72, DUR = 0.11, LEAD = 0.12, T_END = T1 + DUR + 0.04;

export function initLanding(D, N) {
  const stage = $("#landing .stage"), canvas = $("#landingMap"), loupe = $("#landingLoupe"), section = $("#landing");
  let map;
  try { map = new MapGL(canvas, { ink: hexRGBA("#15140f", 1), sig: hexRGBA("#ff4f00", 1), dim: hexRGBA("#87827a", .7) }); }
  catch (e) { stage.append(el("div", "small", `<p style="position:absolute;left:30px;bottom:30px">${esc(e.message)}</p>`)); return; }

  const n = D.lat.length, nc = D.clusters.n.length;
  const lat0 = D.lat.reduce((a, b) => a + b, 0) / n, P = projector(lat0);
  const ox = P.x((D.bbox[0] + D.bbox[2]) / 2), oy = P.y((D.bbox[1] + D.bbox[3]) / 2);
  const X = new Float32Array(n), Y = new Float32Array(n);
  for (let i = 0; i < n; i++) { X[i] = P.x(D.lon[i]) - ox; Y[i] = P.y(D.lat[i]) - oy; }
  const CX = new Float32Array(nc), CY = new Float32Array(nc);
  for (let c = 0; c < nc; c++) { CX[c] = P.x(D.clusters.lon[c]) - ox; CY[c] = P.y(D.clusters.lat[c]) - oy; }

  // merge schedule: a west-to-east sweep over cluster centroids (the workbench scores pairs in the same order)
  const multi = []; for (let c = 0; c < nc; c++) if (D.clusters.n[c] > 1) multi.push(c);
  let xmin = Infinity, xmax = -Infinity; for (const c of multi) { xmin = Math.min(xmin, CX[c]); xmax = Math.max(xmax, CX[c]); }
  const ctau = new Float32Array(nc).fill(-1);
  for (const c of multi) ctau[c] = T0 + (CX[c] - xmin) / (xmax - xmin) * (T1 - T0);
  const sorted = multi.map(c => [ctau[c], D.clusters.n[c] - 1]).sort((a, b) => a[0] - b[0]);
  const cum = []; let acc = 0; for (const [, k] of sorted) { acc += k; cum.push(acc); }

  // assertions against numbers.json: the animation must end on the published counts
  const want0 = N.matching.dubai.lodging_listings, want1 = N.matching.dubai.canonical_entities;
  if (n !== want0 || nc !== want1) console.warn(`landing data (${n} → ${nc}) does not match numbers.json (${want0} → ${want1})`);

  // points: members (+ one canonical mark per multi cluster, shown once its members have arrived)
  const np = n + multi.length;
  const pos = new Float32Array(np * 2), tgt = new Float32Array(np * 2), tau = new Float32Array(np), shape = new Float32Array(np), state = new Float32Array(np);
  for (let i = 0; i < n; i++) {
    const c = D.cl[i], m = D.clusters.n[c] > 1;
    pos[2 * i] = X[i]; pos[2 * i + 1] = Y[i];
    tgt[2 * i] = m ? CX[c] : X[i]; tgt[2 * i + 1] = m ? CY[c] : Y[i];
    tau[i] = m ? ctau[c] : -1; shape[i] = SHAPE_ID[shapeOf(D.sources[D.src[i]])];
  }
  multi.forEach((c, k) => { const j = n + k; pos[2 * j] = tgt[2 * j] = CX[c]; pos[2 * j + 1] = tgt[2 * j + 1] = CY[c]; tau[j] = ctau[c]; shape[j] = 8; state[j] = 4; });
  map.setPoints({ pos, tgt, tau, shape, state });

  const ne = D.edges.length, pa = new Float32Array(ne * 2), pb = new Float32Array(ne * 2), ta = new Float32Array(ne * 2), etau = new Float32Array(ne);
  D.edges.forEach(([a, b], k) => {
    const c = D.cl[a];
    pa[2 * k] = X[a]; pa[2 * k + 1] = Y[a]; pb[2 * k] = X[b]; pb[2 * k + 1] = Y[b]; ta[2 * k] = CX[c]; ta[2 * k + 1] = CY[c]; etau[k] = ctau[c];
  });
  map.setEdges({ pa, pb, ta, tb: ta, tau: etau, w: new Float32Array(ne).fill(1.1), col: new Float32Array(ne), alpha: new Float32Array(ne).fill(.85) });
  const bm = D.basemap;
  map.setLines([
    { segs: segmentsFrom(bm.water, P, ox, oy), col: hexRGBA("#15140f", .16) },
    { segs: segmentsFrom(bm.major, P, ox, oy), col: hexRGBA("#15140f", .085) },
    { segs: segmentsFrom(bm.coast, P, ox, oy), col: hexRGBA("#15140f", .5) },
  ]);
  Object.assign(map.u, { dur: DUR, lead: LEAD, grow: 1, size: 3.2, alpha: .78, fadeMerged: 1, wscale: 1 });

  // legend with per-source counts (counted from the data shown)
  const bySrc = D.sources.map((s, i) => D.src.filter(v => v === i).length);
  $("#heroLegend").innerHTML = D.sources.map((s, i) => srcBadge(s, i, `<em class="num">${fmt.int(bySrc[i])}</em>`)).join("") +
    `<span class="src"><span class="mk"><svg viewBox="0 0 10 10"><circle cx="5" cy="5" r="4.3" fill="none" stroke="currentColor" stroke-width="1.4"/><circle cx="5" cy="5" r="1.4" fill="currentColor"/></svg></span>Canonical hotel</span>`;

  // ---------------------------------------------------------------- view + neatline ticks
  function layout() {
    map.resize();
    const ctx = loupe.getContext("2d"); loupe.width = map.w * map.dpr; loupe.height = map.h * map.dpr;
    // focus on the coastal strip; the sea (north-west) carries the title, as on a chart
    const fx0 = P.x(55.02) - ox, fx1 = P.x(55.44) - ox, fy0 = P.y(24.95) - oy, fy1 = P.y(25.33) - oy;
    const mobile = map.w < 760;
    map.fit(fx0, fy0, fx1, fy1, mobile ? 10 : 40, "contain");
    if (!mobile) { map.view.cx -= (fx1 - fx0) * 0.06; map.view.cy += (fy1 - fy0) * 0.04; map.view.scale *= 1.05; }
    else { map.view.scale *= 1.25; map.view.cy -= (fy1 - fy0) * 0.12; }
    ticks();
    dirty = true;
  }
  function ticks() {
    const neat = $("#landingNeat"); neat.innerHTML = "";
    const r = neat.getBoundingClientRect(), s = stage.getBoundingClientRect();
    const left = r.left - s.left, top = r.top - s.top;
    const [d0x] = map.toData(left, 0), [d1x] = map.toData(left + r.width, 0);
    const [, d0y] = map.toData(0, top + r.height), [, d1y] = map.toData(0, top);
    const step = map.w < 760 ? 0.1 : 0.05;
    for (let lon = Math.ceil(P.lon(d0x + ox) / step) * step; lon <= P.lon(d1x + ox); lon += step) {
      const [sx] = map.toScreen(P.x(lon) - ox, 0); const x = sx - left;
      if (x < 30 || x > r.width - 30) continue;
      for (const cls of ["top", "bot"]) { const t = el("span", "tk " + cls, lon.toFixed(2) + "°E"); t.style.left = x + "px"; neat.append(t); }
    }
    for (let la = Math.ceil(P.lat(d0y + oy) / step) * step; la <= P.lat(d1y + oy); la += step) {
      const [, sy] = map.toScreen(0, P.y(la) - oy); const y = sy - top;
      if (y < 20 || y > r.height - 20) continue;
      for (const cls of ["lft", "rgt"]) { const t = el("span", "tk " + cls, la.toFixed(2) + "°N"); t.style.top = y + "px"; neat.append(t); }
    }
  }

  // ---------------------------------------------------------------- scroll drives the collapse
  let target = 0, shown = 0, dirty = true, visible = true;
  function progress() {
    const r = section.getBoundingClientRect();
    const p = clamp(-r.top / Math.max(1, r.height - innerHeight));
    return clamp((p - 0.04) / 0.86) * T_END;
  }
  const counter = $("#heroCount"), what = $("#heroWhat");
  function mergedAt(t) { // records merged away at time t (cluster counted once its members have arrived)
    let lo = 0, hi = sorted.length; while (lo < hi) { const mid = (lo + hi) >> 1; if (sorted[mid][0] + DUR * 0.75 <= t) lo = mid + 1; else hi = mid; }
    return lo ? cum[lo - 1] : 0;
  }
  let lastCount = -1;
  function updateCounter(t) {
    const merged = mergedAt(t), count = n - merged;
    if (count === lastCount) return; lastCount = count;
    counter.textContent = fmt.int(count);
    if (merged === 0) what.innerHTML = `listings from ${D.sources.length} sources`;
    else if (count === nc) what.innerHTML = `hotels · <b>${fmt.int(merged)}</b> listings merged`;
    else what.innerHTML = `entities · <b>${fmt.int(merged)}</b> merged so far`;
  }
  function frame() {
    if (!visible) { requestAnimationFrame(frame); return; }
    target = progress();
    let next = reduced() ? (target > T_END * 0.5 ? T_END : 0) : shown + (target - shown) * 0.14;
    if (Math.abs(target - next) < 1e-4) next = target;
    if (next !== shown || dirty) {
      shown = next; map.u.t = shown; map.draw(); drawOverlay(); updateCounter(shown); dirty = false;
    }
    requestAnimationFrame(frame);
  }
  new IntersectionObserver(es => { visible = es[0].isIntersecting; dirty = true; }).observe(section);

  // ---------------------------------------------------------------- loupe: magnify a patch, raw names underneath
  const R = 96, Z = 7, list = $("#loupeList");
  let cursor = null;
  function currentXY(i) { // where record i is drawn right now
    const tt = tau[i]; if (tt < 0) return [X[i], Y[i]];
    const m = 1 - Math.pow(1 - clamp((shown - tt) / DUR), 3);
    return [X[i] + (tgt[2 * i] - X[i]) * m, Y[i] + (tgt[2 * i + 1] - Y[i]) * m];
  }
  function drawOverlay() {
    const ctx = loupe.getContext("2d"), dpr = map.dpr;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0); ctx.clearRect(0, 0, map.w, map.h);
    // merge front: the sweep position while clusters are merging
    if (shown > T0 - 0.02 && shown < T1 + DUR && !reduced()) {
      const fx = xmin + clamp((shown - T0 - DUR * 0.5) / (T1 - T0)) * (xmax - xmin);
      const [sx] = map.toScreen(fx, 0);
      ctx.strokeStyle = "rgba(255,79,0,.9)"; ctx.lineWidth = 1; ctx.beginPath(); ctx.moveTo(sx + .5, 52); ctx.lineTo(sx + .5, map.h - 22); ctx.stroke();
      ctx.fillStyle = "#c03a00"; ctx.font = "500 10px 'Plex Mono', monospace"; ctx.fillText("merging · " + P.lon(fx + ox).toFixed(3) + "°E", sx + 6, 66);
    }
    if (!cursor) { list.classList.remove("on"); return; }
    const [cx, cy] = cursor;
    const [dx, dy] = map.toData(cx, cy), rData = (R / Z) / map.view.scale;
    // collect what is under the lens (members not yet merged, plus canonical points of merged clusters)
    const hits = [], seenCl = new Set();
    for (let i = 0; i < n; i++) {
      const [x, y] = currentXY(i); const ddx = x - dx, ddy = y - dy; const d2 = ddx * ddx + ddy * ddy;
      if (d2 > rData * rData) continue;
      const c = D.cl[i], merged = tau[i] >= 0 && shown >= tau[i] + DUR * 0.75;
      if (merged) { if (!seenCl.has(c)) { seenCl.add(c); hits.push({ c, x, y, d2, canon: true }); } }
      else hits.push({ i, x, y, d2 });
    }
    hits.sort((a, b) => a.d2 - b.d2);
    // lens
    ctx.save(); ctx.beginPath(); ctx.arc(cx, cy, R, 0, Math.PI * 2); ctx.closePath();
    ctx.fillStyle = "rgba(239,235,225,.96)"; ctx.fill(); ctx.clip();
    ctx.strokeStyle = "rgba(21,20,15,.08)"; ctx.lineWidth = 1;
    for (let g = -R; g <= R; g += 16) { ctx.beginPath(); ctx.moveTo(cx + g + .5, cy - R); ctx.lineTo(cx + g + .5, cy + R); ctx.moveTo(cx - R, cy + g + .5); ctx.lineTo(cx + R, cy + g + .5); ctx.stroke(); }
    const toLens = (x, y) => { const [sx, sy] = map.toScreen(x, y); return [cx + (sx - cx) * Z, cy + (sy - cy) * Z]; };
    ctx.font = "500 10.5px 'Plex Mono', 'Plex Arabic', monospace"; ctx.textBaseline = "middle";
    const boxes = [];
    hits.slice(0, 90).forEach((h, k) => {
      const [lx, ly] = toLens(h.x, h.y);
      ctx.fillStyle = "#15140f"; ctx.strokeStyle = "#15140f"; ctx.lineWidth = 1.3;
      if (h.canon) { ctx.beginPath(); ctx.arc(lx, ly, 6, 0, Math.PI * 2); ctx.stroke(); ctx.beginPath(); ctx.arc(lx, ly, 2, 0, Math.PI * 2); ctx.fill(); }
      else drawMark(ctx, shapeOf(D.sources[D.src[h.i]]), lx, ly, 3.6);
      if (k < 14) {
        const label = h.canon ? canonName(h.c) : D.name[h.i];
        const w = Math.min(ctx.measureText(label).width, 150), bx = lx + 8, by = ly - 6;
        if (!boxes.some(b => bx < b[0] + b[2] && bx + w > b[0] && by < b[1] + 12 && by + 12 > b[1])) {
          boxes.push([bx, by, w]);
          ctx.fillStyle = "rgba(239,235,225,.85)"; ctx.fillRect(bx - 2, by, w + 4, 12);
          ctx.fillStyle = h.canon ? "#c03a00" : "#15140f"; ctx.fillText(label.length > 26 ? label.slice(0, 25) + "…" : label, bx, ly);
        }
      }
    });
    ctx.restore();
    ctx.strokeStyle = "#15140f"; ctx.lineWidth = 1.2; ctx.beginPath(); ctx.arc(cx, cy, R, 0, Math.PI * 2); ctx.stroke();
    for (let a = 0; a < 4; a++) { const an = a * Math.PI / 2; ctx.beginPath(); ctx.moveTo(cx + Math.cos(an) * R, cy + Math.sin(an) * R); ctx.lineTo(cx + Math.cos(an) * (R + 8), cy + Math.sin(an) * (R + 8)); ctx.stroke(); }
    ctx.fillStyle = "#15140f"; ctx.font = "400 10px 'Plex Mono', monospace"; ctx.textBaseline = "alphabetic";
    ctx.fillText(`${P.lat(dy + oy).toFixed(4)}°N ${P.lon(dx + ox).toFixed(4)}°E · ×${Z}`, cx - R, cy + R + 20);
    // the list beside the lens: raw names in mono; canonical entities show their members underneath
    const rows = hits.slice(0, 11).map(h => h.canon
      ? `<div class="ll-row canon">${markCanon()}<span>${esc(canonName(h.c))}</span></div>` + members(h.c).slice(0, 4).map(i => `<div class="ll-row" style="border-top:0;padding-left:18px">${mark(D.sources[D.src[i]])}<span>${esc(D.name[i])}</span></div>`).join("")
      : `<div class="ll-row">${mark(D.sources[D.src[h.i]])}<span>${esc(D.name[h.i])}</span></div>`).join("");
    const nRec = hits.reduce((a, h) => a + (h.canon ? D.clusters.n[h.c] : 1), 0);
    list.innerHTML = `<div class="ll-h"><span class="label ink">Under the lens</span><span class="tiny num">${hits.length} marks · ${nRec} listings</span></div>${rows || '<div class="tiny">No listings here.</div>'}`;
    let lx = cx + R + 26, ly = cy - R;
    if (lx + 320 > map.w - 20) lx = cx - R - 346;
    list.style.left = lx + "px"; list.style.top = clamp(ly, 56, map.h - list.offsetHeight - 24) + "px";
    list.classList.add("on");
  }
  const memo = new Map();
  function members(c) { if (!memo.has(c)) memo.set(c, D.cl.reduce((a, v, i) => (v === c && a.push(i), a), [])); return memo.get(c); }
  function canonName(c) { // canonical label: a Latin-script name, preferring Wikivoyage, OSM, Wikidata, Overture (as the pipeline does)
    const pr = { wikivoyage: 0, osm: 1, wikidata: 2, overture: 3 };
    const ms = members(c).slice().sort((a, b) => (/[A-Za-z]/.test(D.name[b]) - /[A-Za-z]/.test(D.name[a])) || pr[D.sources[D.src[a]]] - pr[D.sources[D.src[b]]]);
    return D.name[ms[0]];
  }
  const markCanon = () => `<span class="mk"><svg viewBox="0 0 10 10"><circle cx="5" cy="5" r="4.3" fill="none" stroke="#c03a00" stroke-width="1.4"/><circle cx="5" cy="5" r="1.4" fill="#c03a00"/></svg></span>`;

  const overCopy = t => t.closest(".hero-copy, .hero-count, .hero-legend, .topbar, .loupe-list");
  stage.addEventListener("pointermove", e => {
    if (e.pointerType !== "mouse" && !holding) return;
    const r = stage.getBoundingClientRect();
    cursor = overCopy(e.target) ? null : [e.clientX - r.left, e.clientY - r.top];
    stage.style.cursor = cursor ? "none" : ""; dirty = true;
  });
  stage.addEventListener("pointerleave", () => { cursor = null; dirty = true; });
  let holding = false, holdT = null, downAt = null;
  stage.addEventListener("pointerdown", e => {
    downAt = [e.clientX, e.clientY];
    if (e.pointerType !== "mouse" && !overCopy(e.target)) { holdT = setTimeout(() => { holding = true; const r = stage.getBoundingClientRect(); cursor = [e.clientX - r.left, e.clientY - r.top]; dirty = true; }, 220); }
  });
  stage.addEventListener("pointerup", e => {
    clearTimeout(holdT);
    if (holding) { holding = false; cursor = null; dirty = true; return; }
    // a click on the map (not on the copy) runs the collapse forward or back
    if (downAt && Math.hypot(e.clientX - downAt[0], e.clientY - downAt[1]) < 5 && !overCopy(e.target)) {
      const top = section.offsetTop, end = top + section.offsetHeight - innerHeight;
      window.scrollTo({ top: shown > T_END * 0.5 ? top : end, behavior: reduced() ? "auto" : "smooth" });
    }
  });

  addEventListener("resize", layout);
  layout(); updateCounter(0); requestAnimationFrame(frame);
}
