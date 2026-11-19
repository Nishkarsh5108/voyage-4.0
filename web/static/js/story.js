// 03 · How it works. A sticky stage with one beat per step; each beat draws real pipeline output from data/story.json.
// Step progress (0..1 while a step scrolls past) drives what each beat shows, so the reader controls the pace.

import { $, $$, el, esc, clamp, lerp, ease, fmt, reduced, mark, srcBadge, labelOf, shapeOf, drawMark, relSample, REL, tag, projector } from "./util.js";

const FEAT = {
  dist_m: "distance, m", log_dist: "log distance", geo_rank: "geo neighbour rank", by_geo: "found by geo", by_name: "found by name",
  name_jw: "name Jaro-Winkler", name_token_set: "name token set", name_token_sort: "name token sort", name_partial: "name partial", name_ratio: "name ratio",
  name_tfidf_char: "name char n-grams", name_tfidf_word: "name words", name_jw_alt: "best JW, all names", name_token_set_alt: "best token set, all names",
  has_alt: "has alternate names", name_len_min: "shorter name length", name_len_ratio: "name length ratio", script_mismatch: "scripts differ",
  same_kind: "same kind", both_lodging: "both lodging", street_token_set: "street similarity", postcode_eq: "same postcode", brand_sim: "brand similarity",
  stars_diff: "stars difference", decimals_min: "coordinate precision", overture_conf: "Overture confidence", src_pair: "source pair", n_near_max: "crowding within 300 m",
};
export const featName = f => FEAT[f] || f;

export function initStory(S, N) {
  const stage = $("#storyStage"), steps = $$("#story .step");
  const beats = {
    blocking: blockingBeat(S, N), evidence: evidenceBeat(S, N), cascade: cascadeBeat(S, N), cluster: clusterBeat(S, N),
    rooms: roomsBeat(S, N), tours: toursBeat(S, N), offers: offersBeat(S, N), ranking: rankingBeat(S, N),
  };
  let active = null;
  function activate(name) {
    if (name === active) return;
    $$(".beat", stage).forEach(b => b.classList.toggle("on", b.dataset.beat === name));
    if (active && beats[active].leave) beats[active].leave();
    active = name; if (beats[name].enter) beats[name].enter();
  }
  function onScroll() {
    const mid = innerHeight * (innerWidth < 960 ? 0.8 : 0.55);
    let cur = steps[0], p = 0;
    for (const s of steps) { const r = s.getBoundingClientRect(); if (r.top <= mid) { cur = s; p = clamp((mid - r.top) / Math.max(1, r.height)); } }
    activate(cur.dataset.beat);
    if (beats[active].progress) beats[active].progress(p);
  }
  addEventListener("scroll", onScroll, { passive: true });
  addEventListener("resize", () => { for (const b of Object.values(beats)) b.resize && b.resize(); onScroll(); });
  onScroll();
}

function stageBox() { const s = $("#storyStage"); return { w: s.clientWidth, h: s.clientHeight }; }
function hidpi(cv) {
  const dpr = Math.min(devicePixelRatio || 1, 2), w = cv.clientWidth, h = cv.clientHeight;
  cv.width = Math.round(w * dpr); cv.height = Math.round(h * dpr);
  const ctx = cv.getContext("2d"); ctx.setTransform(dpr, 0, 0, dpr, 0, 0); return { ctx, w, h, dpr };
}
function rng(seed) { let s = seed >>> 0; return () => ((s = Math.imul(s ^ (s >>> 15), 2246822507) ^ Math.imul(s ^ (s >>> 13), 3266489909), (s ^= s >>> 16) >>> 0) / 4294967296); }

// =====================================================================================================  3.1 blocking
function blockingBeat(S, N) {
  const B = S.blocking, cv = $("#cvBlocking"), cap = $("#blkCap"), cnt = $("#blkCount");
  const n = B.records, total = n * (n - 1) / 2;
  const P = projector((B.box.s + B.box.n) / 2);
  let G = null, haze = null, hazeShown = 0, order = null, p = 0;
  // shuffled order of all pairs so the haze builds up evenly
  function buildOrder() {
    order = new Uint32Array(total); let k = 0;
    for (let i = 0; i < n; i++) for (let j = i + 1; j < n; j++) order[k++] = i * n + j;
    const r = rng(7); for (let i = order.length - 1; i > 0; i--) { const j = Math.floor(r() * (i + 1)); const t = order[i]; order[i] = order[j]; order[j] = t; }
  }
  const deg = new Array(n).fill(0); B.cand.forEach(([a, b]) => { deg[a]++; deg[b]++; });
  const focus = deg.indexOf(Math.max(...deg));
  function geom() {
    G = hidpi(cv);
    const pad = 46, top = 44, w = G.w - 2 * pad, h = G.h - top - 70;
    const x0 = P.x(B.box.w), x1 = P.x(B.box.e), y0 = P.y(B.box.s), y1 = P.y(B.box.n);
    const sc = Math.min(w / (x1 - x0), h / (y1 - y0));
    const ox = pad + (w - (x1 - x0) * sc) / 2, oy = top + (h - (y1 - y0) * sc) / 2 + (y1 - y0) * sc;
    G.sc = sc; G.xy = B.lat.map((la, i) => [ox + (P.x(B.lon[i]) - x0) * sc, oy - (P.y(la) - y0) * sc]);
    G.kmPx = sc * (1 / 111.32); // 1 km in pixels (degrees of latitude)
    haze = document.createElement("canvas"); haze.width = cv.width; haze.height = cv.height;
    const hc = haze.getContext("2d"); hc.setTransform(G.dpr, 0, 0, G.dpr, 0, 0); hc.strokeStyle = "rgba(21,20,15,.022)"; hc.lineWidth = .6; hazeShown = 0;
  }
  function growHaze(k) {
    if (!order) buildOrder();
    const hc = haze.getContext("2d");
    if (k < hazeShown) { hc.setTransform(1, 0, 0, 1, 0, 0); hc.clearRect(0, 0, haze.width, haze.height); hc.setTransform(G.dpr, 0, 0, G.dpr, 0, 0); hazeShown = 0; }
    for (let s = hazeShown; s < k; s += 4000) {
      hc.beginPath();
      for (let q = s; q < Math.min(k, s + 4000); q++) { const v = order[q], i = Math.floor(v / n), j = v % n; hc.moveTo(G.xy[i][0], G.xy[i][1]); hc.lineTo(G.xy[j][0], G.xy[j][1]); }
      hc.stroke();
    }
    hazeShown = k;
  }
  function draw() {
    if (!G) geom();
    const { ctx, w, h } = G; ctx.clearRect(0, 0, w, h);
    const f1 = clamp(p / 0.42), f2 = ease(clamp((p - 0.48) / 0.3));
    if (f2 < 1) { growHaze(Math.round(total * (reduced() ? (p < 0.48 ? 1 : 0) : f1))); ctx.globalAlpha = 1 - f2; ctx.drawImage(haze, 0, 0, w, h); ctx.globalAlpha = 1; }
    if (f2 > 0) {
      // the 1 km geo radius around one listing
      const [fx, fy] = G.xy[focus];
      ctx.save(); ctx.globalAlpha = f2; ctx.setLineDash([3, 4]); ctx.strokeStyle = "#15140f"; ctx.lineWidth = 1;
      ctx.beginPath(); ctx.arc(fx, fy, G.kmPx, 0, Math.PI * 2); ctx.stroke(); ctx.setLineDash([]);
      ctx.fillStyle = "#15140f"; ctx.font = "500 10px 'Plex Mono', monospace"; ctx.fillText("1 km", fx + G.kmPx * .72 + 4, fy - G.kmPx * .72);
      for (const [a, b, g] of B.cand) {
        const [x1, y1] = G.xy[a], [x2, y2] = G.xy[b], isFocus = a === focus || b === focus;
        if (g & 1) { ctx.strokeStyle = isFocus ? "rgba(21,20,15,.95)" : "rgba(21,20,15,.42)"; ctx.lineWidth = isFocus ? 1.3 : .7; ctx.beginPath(); ctx.moveTo(x1, y1); ctx.lineTo(x2, y2); ctx.stroke(); }
        if (g & 2) {
          const mx = (x1 + x2) / 2, my = (y1 + y2) / 2, dx = x2 - x1, dy = y2 - y1;
          ctx.strokeStyle = isFocus ? "rgba(255,79,0,1)" : "rgba(255,79,0,.62)"; ctx.lineWidth = isFocus ? 1.6 : .9; ctx.beginPath(); ctx.moveTo(x1, y1);
          ctx.quadraticCurveTo(mx - dy * .14, my + dx * .14, x2, y2); ctx.stroke();
        }
      }
      ctx.restore();
    }
    ctx.fillStyle = "#15140f";
    B.lat.forEach((_, i) => drawMark(ctx, shapeOf(S.sources[B.src[i]]), G.xy[i][0], G.xy[i][1], i === focus && f2 > 0 ? 4.5 : 2.4));
    if (f2 > 0.4) {
      const [fx, fy] = G.xy[focus]; ctx.font = "500 11px 'Plex Mono', monospace"; ctx.fillStyle = "rgba(239,235,225,.9)";
      const t = B.name[focus]; const tw = ctx.measureText(t).width; ctx.fillRect(fx + 8, fy - 18, tw + 8, 15); ctx.fillStyle = "#15140f"; ctx.fillText(t, fx + 12, fy - 7);
    }
    const geoN = B.cand.filter(c => c[2] & 1).length, nameN = B.cand.filter(c => c[2] & 2).length;
    if (f2 < 0.5) { cap.textContent = "Dubai Marina · every pair"; cnt.textContent = `${fmt.int(Math.round(total * f1))} of ${fmt.int(total)} comparisons · ${n} listings`; }
    else { cap.textContent = "Dubai Marina · candidate pairs only"; cnt.textContent = `${fmt.int(B.cand.length)} candidates · ${(B.cand.length / n).toFixed(1)} per listing in this frame · ${fmt.int(B.cand_outside)} more leave it`; }
    $("#blkLegend").innerHTML = f2 > 0.3 ? `<div class="readout" style="padding:8px 10px"><div style="display:grid;grid-template-columns:44px 1fr;gap:6px 10px;align-items:center;font:400 11px/1.3 var(--mono)">
      <svg width="44" height="8"><line x1="0" y1="4" x2="44" y2="4" stroke="#15140f" stroke-width="1.2"/></svg><span>geo · ${fmt.int(geoN)} · ${B.params.k_geo} nearest per source within ${B.params.r_geo / 1000} km</span>
      <svg width="44" height="10"><path d="M0 9Q22 -3 44 9" fill="none" stroke="#ff4f00" stroke-width="1.3"/></svg><span>name · ${fmt.int(nameN)} · ${B.params.k_name} closest names, cosine ≥ ${B.params.min_cos}</span></div></div>` : "";
  }
  return { progress(v) { p = v; draw(); }, enter() { draw(); }, resize() { G = null; if ($("#storyStage .beat[data-beat=blocking]").classList.contains("on")) draw(); } };
}

// =====================================================================================================  3.2 evidence
function evidenceBeat(S, N) {
  const A = S.atlantis, root = $("#evidenceBeat");
  const byRid = Object.fromEntries(A.members.map(m => [m.rid, m]));
  const order = ["wikivoyage", "overture", "wikidata", "osm"];
  const mem = order.map(s => A.members.find(m => m.source === s)).filter(Boolean);
  let sel = A.pairs.findIndex(p => p.features.script_mismatch === 1 && p.route === "uncertain"); if (sel < 0) sel = 0;
  const pos = { wikivoyage: [320, 40], overture: [70, 120], wikidata: [570, 120], osm: [320, 200] };
  const focusPair = A.pairs[sel];
  $("#atlP").textContent = focusPair.p.toFixed(2);
  function graph() {
    const e = A.pairs.map((p, k) => {
      const a = pos[byRid[p.a].source], b = pos[byRid[p.b].source], mx = (a[0] + b[0]) / 2, my = (a[1] + b[1]) / 2;
      const key = p.route === "key_match", unc = p.route === "uncertain", on = k === sel;
      const stroke = unc ? "#ff4f00" : "#15140f";
      return `<g class="edge" data-k="${k}" style="cursor:pointer"><line x1="${a[0]}" y1="${a[1]}" x2="${b[0]}" y2="${b[1]}" stroke="transparent" stroke-width="16"/>
        <line x1="${a[0]}" y1="${a[1]}" x2="${b[0]}" y2="${b[1]}" stroke="${stroke}" stroke-width="${on ? 3.2 : key ? 2.2 : 1.3}" ${unc ? 'stroke-dasharray="1 0"' : ""}/>
        <rect x="${mx - 25}" y="${my - 9}" width="50" height="18" fill="${on ? "#15140f" : "#efebe1"}" stroke="${stroke}"/>
        <text x="${mx}" y="${my + 4}" text-anchor="middle" font-family="Plex Mono" font-size="11" font-weight="500" fill="${on ? "#efebe1" : unc ? "#c03a00" : "#15140f"}">${key ? "key" : p.p.toFixed(2)}</text></g>`;
    }).join("");
    const nodes = mem.map(m => {
      const [x, y] = pos[m.source];
      return `<g transform="translate(${x},${y})"><rect x="-8" y="-8" width="16" height="16" fill="#efebe1" stroke="#15140f"/>
        <g transform="translate(-5,-5)">${markInner(m.source)}</g>
        <text x="0" y="${y >= 200 ? 26 : y > 60 ? 26 : -16}" text-anchor="middle" font-family="Plex Mono, Plex Arabic" font-size="14" font-weight="500" fill="#15140f">${esc(m.name)}</text>
        <text x="0" y="${y >= 200 ? 41 : y > 60 ? 41 : -31}" text-anchor="middle" font-family="Archivo" font-size="9.5" letter-spacing="1.2" font-weight="600" fill="#4f4b43">${esc(labelOf(m.source).toUpperCase())}${m.qid ? " · " + m.qid : ""}</text></g>`;
    }).join("");
    return `<svg viewBox="-10 -24 660 274" style="width:100%;height:100%" preserveAspectRatio="xMidYMid meet">${e}${nodes}</svg>`;
  }
  function missing(a, b, field, what) { // say exactly which side lacks the value; the feature is then unknown to the model
    const has = [a, b].filter(r => r[field] !== null && r[field] !== undefined && r[field] !== "");
    if (!has.length) return `neither listing gives ${what}: unknown to the model`;
    return `only ${labelOf(has[0].source)} gives ${what} (${esc(String(has[0][field]))}${field === "stars" ? "★" : ""}): unknown to the model`;
  }
  function micro() {
    const p = A.pairs[sel], f = p.features, a = byRid[p.a], b = byRid[p.b];
    const ro = (k, v, unit, frac, sub, extra = "") => `<div class="readout"><div class="k"><span>${k}</span>${extra}</div><div class="v num">${v}<small>${unit}</small></div>
      ${frac === null ? "" : `<div class="scale"><span class="needle" data-left="${clamp(frac) * 100}%" style="left:0%"></span></div>`}<div class="sub">${sub}</div></div>`;
    const na = v => v === null || v === undefined;
    const bands = `<div class="scale" style="height:18px"><span class="ghost" style="left:${S.t_reject * 100}%"></span><span class="ghost" style="left:${S.t_accept * 100}%"></span>
      <span style="position:absolute;left:${S.t_accept * 100}%;right:0;top:4px;height:10px" class="hatched"></span><span class="needle" data-left="${p.p * 100}%" style="left:0%;height:18px"></span></div>`;
    const routeTxt = { key_match: "settled by a key rule: shared Wikidata ID", model_accept: "accepted by the model", uncertain: "uncertain: sent on to heavier judgement", model_reject: "rejected by the model", key_reject: "rejected by a key rule" }[p.route];
    let contrib = "";
    if (p.contrib) {
      const items = Object.entries(p.contrib).filter(([k, v]) => Math.abs(v) > 0.02).sort((x, y) => Math.abs(y[1]) - Math.abs(x[1])).slice(0, 7);
      const mx = Math.max(...items.map(x => Math.abs(x[1])), 1);
      contrib = `<div class="label ink" style="margin-top:14px">What moved the score <span class="tiny" style="text-transform:none;letter-spacing:0">· LightGBM contributions, log-odds; start ${p.bias.toFixed(2)}</span></div>
        <div class="shap">${items.map(([k, v]) => `<span class="fn">${esc(featName(k))}</span><span class="bar"><i class="${v < 0 ? "neg" : ""}" style="${v >= 0 ? `left:50%;width:${v / mx * 50}%` : `right:50%;width:${-v / mx * 50}%`}"></i></span><span class="fv">${v > 0 ? "+" : ""}${v.toFixed(2)}</span>`).join("")}</div>`;
    } else contrib = `<p class="tiny" style="margin-top:12px">Labelled pair: its score comes from the model trained without Dubai, as in the evaluation. Contributions for it appear once that model is rebuilt locally.</p>`;
    return `<div style="display:grid;grid-template-columns:1fr 1fr;gap:1px;background:var(--hair);border:1px solid var(--ink)">
        ${[a, b].map(r => `<div style="background:var(--paper);padding:9px 10px">${srcBadge(r.source)}<div class="raw" style="font-size:15px;margin:6px 0 4px">${esc(r.name)}</div>
          ${r.alt_names.length ? `<div class="tiny">also: ${r.alt_names.slice(0, 4).map(x => `<span class="raw" style="color:var(--ink-2)">${esc(x)}</span>`).join(" · ")}</div>` : `<div class="tiny">no alternate names</div>`}</div>`).join("")}
      </div>
      <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(130px,1fr));gap:8px;margin-top:10px">
        ${ro("Distance", fmt.int(f.dist_m), " m", f.dist_m / 1000, "scale: the 1 km geo radius")}
        ${ro("Name as written", f.name_jw.toFixed(2), "", f.name_jw, f.script_mismatch ? "scripts differ: Latin vs Arabic" : "Jaro-Winkler, same script")}
        ${ro("Best over all names", f.name_jw_alt.toFixed(2), "", f.name_jw_alt, f.has_alt ? "alternate names in any script" : "no alternate names")}
        ${ro("Brand", na(f.brand_sim) ? "—" : f.brand_sim.toFixed(2), "", na(f.brand_sim) ? null : f.brand_sim, na(f.brand_sim) ? missing(a, b, "brand", "a brand") : "token set")}
        ${ro("Stars", na(f.stars_diff) ? "—" : f.stars_diff.toFixed(0), "", null, na(f.stars_diff) ? missing(a, b, "stars", "stars") : "difference")}
        ${ro("Street", na(f.street_token_set) ? "—" : f.street_token_set.toFixed(2), "", na(f.street_token_set) ? null : f.street_token_set, na(f.street_token_set) ? "no street on one side" : "token set")}
      </div>
      <div class="readout" style="margin-top:8px"><div class="k"><span>Model score · ${p.model === "loco" ? "model trained without Dubai" : "final model"}</span><span>${p.route === "uncertain" ? '<span class="signal">uncertain</span>' : esc(p.route.replace("_", " "))}</span></div>
        <div class="v num">${p.p.toFixed(2)}</div>${bands}<div class="sub">reject below ${S.t_reject} · accept at ${S.t_accept.toFixed(3)} (hatched) · ${routeTxt}</div></div>
      ${contrib}`;
  }
  function render() {
    root.innerHTML = `<div style="display:grid;grid-template-rows:minmax(150px,34%) 1fr;height:100%;">
      <div style="position:relative;border-bottom:1px solid var(--hair);padding:14px 12px 16px"><div class="tiny" style="position:absolute;left:14px;bottom:6px">edge label: model score, or "key" for a key rule · click an edge</div>${graph()}</div>
      <div style="padding:12px 16px;overflow:auto">${micro()}
        <p class="tiny" style="margin-top:12px">Not features: phone, website, Wikidata ID. Three listings share <b style="color:var(--ink)">${esc(A.members.find(m => m.qid)?.qid || "")}</b>, so a key rule links them whatever the model says.</p></div></div>`;
    $$(".edge", root).forEach(g => g.addEventListener("click", () => { sel = +g.dataset.k; render(); }));
    setTimeout(() => $$(".needle", root).forEach(nd => { nd.style.left = nd.dataset.left; }), reduced() ? 0 : 80);
  }
  let drawn = false;
  return { enter() { if (!drawn) { render(); drawn = true; } } };
}
function markInner(src) {
  const sh = shapeOf(src);
  return { circle: '<circle cx="5" cy="5" r="4.4" fill="#15140f"/>', square: '<rect x="1" y="1" width="8" height="8" fill="#15140f"/>', triangle: '<path d="M5 .4 9.6 9.2H.4z" fill="#15140f"/>', diamond: '<path d="M5 0 10 5 5 10 0 5z" fill="#15140f"/>' }[sh] || "";
}

// =====================================================================================================  3.3 cascade
function cascadeBeat(S, N) {
  const cv = $("#cvCascade"), sh = N.matching.cascade_shares, total = N.matching.candidate_pairs;
  const shares = [sh["Key rules"], sh["Cheap model, confident"], sh["Uncertain: cross-encoder, LLM, human"]];
  $("#cascCap").textContent = `${fmt.millions(total)} pairs · 12 cities · numbers.json`;
  let G = null, parts = [], raf = null, last = 0, seq = 0;
  // deterministic routing: every 1,000 particles split exactly by the published shares
  const cut1 = shares[0], cut2 = shares[0] + shares[1];
  const golden = 0.6180339887;
  function route(k) { const u = (k * golden) % 1; return u < cut1 ? 0 : u < cut2 ? 1 : 2; }
  const HW = 40; // half width of the chute
  function geom() {
    G = hidpi(cv); const { w, h } = G;
    G.cx = clamp(w * 0.3, 150, 300); G.g1 = 60 + (h - 200) * 0.26; G.g2 = 60 + (h - 200) * 0.58; G.bottom = h - 92;
    const x0 = G.cx + HW + 36, x1 = w - 18;
    G.bins = [{ x0, x1, y: G.g1, h: 64, label: "Key rules", sub: "shared or conflicting ID, phone, website" },
              { x0, x1, y: G.g2, h: 64, label: "Small model, confident", sub: "LightGBM · accept ≥ 0.956 · reject < 0.02" }];
    G.unc = { x0: Math.max(14, G.cx - 120), x1: Math.max(14, G.cx - 120) + 240, y: G.bottom - 6, h: 34 };
  }
  function spawn() { const k = seq++; parts.push({ k, r: route(k), x: G.cx + (((k * 0.37) % 1) - .5) * (HW * 1.6), y: 50, t: 0, ph: 0 }); }
  function step(dt) {
    for (const q of parts) {
      q.t += dt;
      if (q.ph === 0) {
        q.y += 150 * dt; const gate = q.r === 0 ? G.g1 : q.r === 1 ? G.g2 : Infinity;
        if (q.y >= gate) { q.ph = 1; q.y = gate; q.sx = q.x; q.t = 0; const b = G.bins[q.r]; q.tx = b.x0 + 8 + ((q.k * 0.53) % 1) * (b.x1 - b.x0 - 16); q.ty = b.y + 8 + ((q.k * 0.29) % 1) * (b.h - 16); }
        if (q.r === 2 && q.y >= G.unc.y + 4) { q.ph = 2; q.t = 0; q.tx = q.x; q.ty = q.y + ((q.k * 0.29) % 1) * 22; q.sy = q.y; q.sx = q.x; }
      } else if (q.ph === 1) { const u = ease(clamp(q.t / 0.8)); q.x = lerp(q.sx, q.tx, u); if (u >= 1) { q.ph = 2; q.t = 0; q.sy = q.y; q.sx = q.x; } }
      else if (q.ph === 2) { const u = ease(clamp(q.t / 0.35)); q.y = lerp(q.sy, q.ty, u); if (q.t > 1.4) q.ph = 4; }
    }
    parts = parts.filter(q => q.ph !== 4);
  }
  function draw() {
    const { ctx, w, h } = G; ctx.clearRect(0, 0, w, h);
    ctx.strokeStyle = "#15140f"; ctx.lineWidth = 1; ctx.fillStyle = "#15140f";
    ctx.beginPath(); ctx.moveTo(G.cx - HW, 52); ctx.lineTo(G.cx - HW, G.unc.y); ctx.moveTo(G.cx + HW, 52); ctx.lineTo(G.cx + HW, G.unc.y); ctx.stroke();
    ctx.textAlign = "right"; ctx.font = "600 9.5px Archivo"; ctx.letterSpacing = "1.3px";
    ctx.fillText("CANDIDATE", G.cx - HW - 8, 62); ctx.fillText("PAIRS", G.cx - HW - 8, 75);
    [[G.g1, "GATE 0", "KEY RULES", 0], [G.g2, "GATE 1", "PAIR MODEL", 1]].forEach(([y, t1, t2, i]) => {
      ctx.fillStyle = "#15140f"; ctx.fillRect(G.cx + HW, y - 1, G.bins[i].x0 - G.cx - HW, 2);
      ctx.fillText(t1, G.cx - HW - 8, y - 2); ctx.fillText(t2, G.cx - HW - 8, y + 11);
      ctx.beginPath(); ctx.moveTo(G.cx - HW - 5, y); ctx.lineTo(G.cx - HW, y); ctx.stroke();
    });
    ctx.letterSpacing = "0px"; ctx.textAlign = "left";
    G.bins.forEach((b, i) => {
      ctx.strokeStyle = "#15140f"; ctx.strokeRect(b.x0 + .5, b.y + .5, b.x1 - b.x0, b.h);
      ctx.fillStyle = "#15140f"; ctx.font = "760 30px Archivo"; const pc = fmt.pct0(shares[i]); ctx.fillText(pc, b.x0, b.y - 10);
      const pw = ctx.measureText(pc).width; ctx.font = "620 12.5px Archivo"; ctx.fillText(b.label, b.x0 + pw + 10, b.y - 12);
      ctx.font = "400 10.5px 'Plex Mono'"; ctx.fillStyle = "#87827a"; ctx.fillText(b.sub, b.x0, b.y + b.h + 15);
    });
    const U = G.unc;
    ctx.save(); ctx.setLineDash([4, 3]); ctx.strokeStyle = "#ff4f00"; ctx.strokeRect(U.x0 + .5, U.y + .5, U.x1 - U.x0, U.h); ctx.restore();
    ctx.fillStyle = "#c03a00"; ctx.font = "760 30px Archivo"; const pu = fmt.pct0(shares[2]); ctx.fillText(pu, U.x1 + 14, U.y + 28);
    const puw = ctx.measureText(pu).width; ctx.font = "620 12.5px Archivo"; ctx.fillText("Uncertain", U.x1 + 22 + puw, U.y + 14);
    ctx.font = "400 10.5px 'Plex Mono'"; ctx.fillStyle = "#87827a"; ctx.fillText("waits for heavier judgement", U.x1 + 22 + puw, U.y + 29);
    const nb = ["cross-encoder", "LLM", "human review"], y0 = U.y + U.h + 14;
    ctx.save(); ctx.setLineDash([3, 3]); ctx.strokeStyle = "#87827a"; ctx.font = "500 10.5px 'Plex Mono'";
    let x = U.x0; nb.forEach(t => { const tw = ctx.measureText(t).width + 16; ctx.strokeRect(x + .5, y0 + .5, tw, 22); ctx.fillStyle = "#87827a"; ctx.fillText(t, x + 8, y0 + 15); x += tw + 6; });
    ctx.restore(); ctx.fillStyle = "#87827a"; ctx.font = "600 9.5px 'Plex Mono'"; ctx.fillText("DESIGNED · NOT BUILT", x + 6, y0 + 15);
    for (const q of parts) { ctx.fillStyle = q.r === 2 && q.y > G.g2 + 4 ? "#ff4f00" : "#15140f"; ctx.globalAlpha = q.ph === 2 ? clamp(1.4 - q.t) : 1; ctx.fillRect(q.x - 1.6, q.y - 1.6, 3.2, 3.2); }
    ctx.globalAlpha = 1;
  }
  let acc = 0;
  function loop(ts) {
    const dt = Math.min(0.05, (ts - (last || ts)) / 1000); last = ts;
    acc += dt * 26; while (acc > 1) { spawn(); acc--; }
    step(dt); draw(); raf = requestAnimationFrame(loop);
  }
  return {
    enter() { geom(); if (reduced()) { draw(); return; } last = 0; cancelAnimationFrame(raf); raf = requestAnimationFrame(loop); },
    leave() { cancelAnimationFrame(raf); raf = null; parts = []; },
    resize() { if (raf) geom(); },
  };
}

// =====================================================================================================  3.4 clustering
function clusterBeat(S, N) {
  const CL = S.cannot_link, root = $("#clusterBeat");
  const A = CL.clusters[0], Bc = CL.clusters[1];
  const nodes = [...A.members, ...Bc.members];
  const byRid = Object.fromEntries(nodes.map(m => [m.rid, m]));
  const events = [...A.edges.map(e => ({ ...e, w: e.route === "key_match" ? 2 : e.p })), { a: CL.refused.a, b: CL.refused.b, p: CL.refused.p, w: CL.refused.p, refused: true }]
    .sort((x, y) => y.w - x.w);
  const W = 720, H = 440, CX = 240, CY = 215;
  // start spread out; members of the accepted cluster pull towards one point as their pairs are accepted
  const start = {}, end = {};
  A.members.forEach((m, i) => { const an = -Math.PI / 2 + i * 2 * Math.PI / A.members.length; start[m.rid] = [CX + Math.cos(an) * 150, CY + Math.sin(an) * 150]; end[m.rid] = [CX + Math.cos(an) * 74, CY + Math.sin(an) * 74]; });
  Bc.members.forEach(m => { start[m.rid] = [545, CY]; end[m.rid] = [545, CY]; });
  let p = -1;
  function render(v) {
    const kShown = Math.floor(clamp(v / 0.85) * events.length + 0.0001);
    const accepted = events.slice(0, kShown).filter(e => !e.refused).length, totalAcc = events.filter(e => !e.refused).length;
    const pull = ease(accepted / totalAcc);
    const at = rid => { const s = start[rid], e = end[rid]; return A.members.some(m => m.rid === rid) ? [lerp(s[0], e[0], pull), lerp(s[1], e[1], pull)] : s; };
    const refusedOn = events.slice(0, kShown).some(e => e.refused);
    let svg = `<svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="xMidYMid meet">`;
    if (pull > 0.98) svg += `<circle cx="${CX}" cy="${CY}" r="122" fill="none" stroke="#15140f" stroke-dasharray="2 3"/><text x="${CX}" y="${CY - 128}" text-anchor="middle" font-family="Archivo" font-size="10" font-weight="600" letter-spacing="1.4" fill="#15140f">ONE ENTITY · ${A.members.length} LISTINGS</text>`;
    events.slice(0, kShown).forEach((e, i) => {
      const [x1, y1] = at(e.a), [x2, y2] = at(e.b);
      if (e.refused) {
        const mx = (x1 + x2) / 2 + 30, my = (y1 + y2) / 2;
        svg += `<line x1="${x1}" y1="${y1}" x2="${mx - 14}" y2="${my}" stroke="#ff4f00" stroke-width="2"/><line x1="${mx + 14}" y1="${my}" x2="${x2}" y2="${y2}" stroke="#ff4f00" stroke-width="2" stroke-dasharray="1.5 4" stroke-linecap="round"/>
          <circle cx="${mx}" cy="${my}" r="12" fill="#efebe1" stroke="#ff4f00" stroke-width="2"/><line x1="${mx - 8}" y1="${my + 8}" x2="${mx + 8}" y2="${my - 8}" stroke="#ff4f00" stroke-width="2"/>
          <text x="${mx}" y="${my + 34}" text-anchor="middle" font-family="Plex Mono" font-size="11" fill="#c03a00">model ${e.p.toFixed(3)} ≥ accept, refused</text>
          <text x="${mx}" y="${my + 49}" text-anchor="middle" font-family="Plex Mono" font-size="11" fill="#c03a00">${esc(qidOf(A))} ≠ ${esc(Bc.members[0].qid)}</text>`;
      } else svg += `<line x1="${x1}" y1="${y1}" x2="${x2}" y2="${y2}" stroke="#15140f" stroke-width="${e.route === "key_match" ? 2.4 : 1.3}"/>`;
    });
    nodes.forEach(m => {
      const [x, y] = at(m.rid);
      const right = x > CX + 1;
      svg += `<g transform="translate(${x},${y})"><rect x="-7" y="-7" width="14" height="14" fill="#efebe1" stroke="#15140f"/><g transform="translate(-4.5,-4.5) scale(.9)">${markInner(m.source)}</g>
        <text x="${right ? 12 : -12}" y="4" text-anchor="${right ? "start" : "end"}" font-family="Plex Mono, Plex Arabic" font-size="11.5" font-weight="500" fill="#15140f">${esc(m.name)}</text>
        ${m.qid ? `<text x="${right ? 12 : -12}" y="17" text-anchor="${right ? "start" : "end"}" font-family="Plex Mono" font-size="9.5" fill="#87827a">${m.qid}</text>` : ""}</g>`;
    });
    svg += `<text x="12" y="${H - 14}" font-family="Plex Mono" font-size="10.5" fill="#87827a">step ${kShown} of ${events.length} · pairs taken strongest first: key rules (weight 2), then model score</text></svg>`;
    root.innerHTML = svg;
  }
  return { progress(v) { if (Math.abs(v - p) > 0.004) { p = v; render(v); } }, enter() { render(Math.max(p, 0)); } };
}
function qidOf(c) { return (c.members.find(m => m.qid) || {}).qid || ""; }

// =====================================================================================================  3.5 rooms
function roomsBeat(S, N) {
  const R = S.rooms, T = S.rooms_trace, root = $("#roomsBeat");
  const text = R.focus;
  let p = -1;
  function render(v) {
    if (!T) { root.innerHTML = `<p class="small" style="padding:20px">The parse trace for this beat is built by web/build_site_data.py from canon/rooms.py.</p>`; return; }
    const typed = Math.round(clamp(v / 0.3) * text.length), split = ease(clamp((v - 0.32) / 0.28)), lock = ease(clamp((v - 0.64) / 0.22));
    const toks = T.raw_tokens;
    const roomT = T.tokens.filter(t => t.side === "room"), rateT = T.tokens.filter(t => t.side === "rate"), leftT = T.tokens.filter(t => t.side === "left");
    const chip = t => `<span class="chip ${t.side === "rate" ? "rate" : t.side === "room" ? "room" : "left"}" title="${esc(t.rule)}" style="opacity:${split};transform:translateY(${(1 - split) * -26}px);transition:none"><small>${esc(t.attr)}</small>${esc(t.label)}</span>`;
    const caret = typed < text.length || v < 0.32 ? `<span style="display:inline-block;width:.6em;height:1.05em;background:#ff4f00;vertical-align:-3px;margin-left:2px"></span>` : "";
    const rawLine = split < 0.02 ? `<span>${esc(text.slice(0, typed))}</span>${caret}`
      : toks.map(t => `<span class="tok ${t.side}" style="transition:none;${t.side === "room" ? `background:rgba(21,20,15,${split})` : t.side === "rate" ? `background:rgba(255,79,0,${split})` : ""};color:${split > .5 && t.side === "room" ? "#efebe1" : "#15140f"}">${esc(t.raw)}</span>`).join(" ");
    const sig = T.signature_text;
    root.innerHTML = `<div style="padding:22px 26px;display:grid;grid-template-rows:auto auto 1fr;gap:18px;height:100%">
      <div><div class="label">Supplier B sends</div><div class="raw" style="font-size:clamp(26px,3.2vw,42px);font-weight:500;margin-top:10px;display:flex;flex-wrap:wrap;gap:8px;align-items:center;min-height:1.4em">${rawLine}</div>
        <div class="tiny" style="margin-top:8px;opacity:${split}">normalised: ${esc(T.normalised)}</div></div>
      <div class="lanes" style="opacity:${split > 0 ? 1 : 0.25}">
        <div class="lane"><div class="label ink">Room · identity</div><div class="chips">${roomT.map(chip).join("")}</div></div>
        <div class="lane rate"><div class="label ink">Rate plan · not identity</div><div class="chips">${rateT.map(chip).join("")}</div></div>
        ${leftT.length ? `<div class="tiny" style="grid-column:1/-1">left over: ${leftT.map(t => esc(t.raw)).join(" ")}</div>` : ""}
      </div>
      <div style="opacity:${0.25 + 0.75 * lock};min-height:0;overflow:hidden">
        <div style="display:flex;justify-content:space-between;align-items:baseline"><span class="label ink">${esc(R.hotel)} · supplier A's rooms</span><span class="tiny">signature: ${esc(sig)}</span></div>
        <div style="margin-top:8px;border-top:1px solid var(--ink)">${R.a.map((a, i) => {
          const hit = i === T.match && lock > 0.5;
          return `<div style="display:grid;grid-template-columns:22px 1fr auto;gap:8px;align-items:baseline;padding:6px 0;border-bottom:1px solid var(--hair);${hit ? "" : `opacity:${1 - 0.55 * lock}`}">
            <span class="mono" style="font-size:11px;color:${hit ? "#c03a00" : "var(--ink-3)"}">${hit ? "→" : String(i + 1).padStart(2, "0")}</span>
            <span class="canon-name" style="font-size:15.5px;${hit ? "box-shadow:inset 0 -3px 0 #ff4f00" : ""}">${esc(a.name)}</span>
            <span class="tiny">${esc(T.a_signatures[i])}</span></div>`;
        }).join("")}</div>
      </div></div>`;
  }
  return { progress(v) { if (Math.abs(v - p) > 0.003) { p = v; render(v); } }, enter() { render(Math.max(p, 0)); } };
}

// =====================================================================================================  3.6 tours
function toursBeat(S, N) {
  const Tr = S.tours, root = $("#toursBeat");
  const L = ["A", "B", "C", "D"];
  const role = ["ticket", "Express pass", "combo", "VIP tour"];
  const P = [[170, 190], [520, 190], [170, 46], [170, 334]];
  let p = -1;
  // relations as the library returned them, oriented for drawing: INCLUDED_IN(a,b) is drawn as b INCLUDES a
  const rels = Tr.relations.map(r => r.relation === "INCLUDED_IN" ? { ...r, a: r.b, b: r.a, relation: "INCLUDES" } : r);
  function edge(r, faint) {
    const [x1, y1] = P[r.a], [x2, y2] = P[r.b], dx = x2 - x1, dy = y2 - y1, L0 = Math.hypot(dx, dy), ux = dx / L0, uy = dy / L0;
    const sx = x1 + ux * 34, sy = y1 + uy * 34, ex = x2 - ux * 34, ey = y2 - uy * 34;
    const st = REL[r.relation] || REL.DIFFERENT, col = faint ? "#87827a" : "#15140f";
    let s = `<line x1="${sx}" y1="${sy}" x2="${ex}" y2="${ey}" stroke="${col}" stroke-width="${r.relation === "DIFFERENT" ? 2 : 1.6}" stroke-dasharray="${st.dash}" ${r.relation === "DIFFERENT" ? 'stroke-linecap="round"' : ""} opacity="${faint ? .55 : 1}"/>`;
    if (st.arrow) s += `<path d="M${ex - ux * 10 - uy * 6} ${ey - uy * 10 + ux * 6} L${ex} ${ey} L${ex - ux * 10 + uy * 6} ${ey - uy * 10 - ux * 6}" fill="none" stroke="${col}" stroke-width="1.6"/>`;
    if (!faint) {
      const mx = (sx + ex) / 2, my = (sy + ey) / 2, lab = `${REL[r.relation].label.toUpperCase()}${r.diff.length ? " · " + r.diff.map(d => d.replace(/_/g, " ").replace("->", "→")).join(", ") : ""}`;
      s += `<rect x="${mx - lab.length * 3.2 - 6}" y="${my - 10}" width="${lab.length * 6.4 + 12}" height="19" fill="#efebe1" stroke="${col}"/><text x="${mx}" y="${my + 4}" text-anchor="middle" font-family="Plex Mono" font-size="10.5" fill="${col}">${esc(lab)}</text>`;
    }
    return s;
  }
  function node(i, x, y, dim = false, merged = null) {
    const it = Tr.items[i];
    const t = it.title.replace(/\[[^\]]+\]\s*/g, "").replace("™", "");
    return `<g transform="translate(${x},${y})" opacity="${dim ? .35 : 1}"><circle r="30" fill="#efebe1" stroke="#15140f" stroke-width="${merged ? 2.4 : 1.3}"/>
      <text y="-3" text-anchor="middle" font-family="Archivo" font-size="17" font-weight="760" fill="#15140f">${merged || L[i]}</text>
      <text y="13" text-anchor="middle" font-family="Archivo" font-size="9" font-weight="600" letter-spacing="1" fill="#4f4b43">${esc(role[i].toUpperCase())}</text></g>`;
  }
  function render(v) {
    const dd = v > 0.55;
    const base = rels.filter(r => r.a === 0 || r.b === 0), other = rels.filter(r => r.a !== 0 && r.b !== 0);
    let svg = `<svg viewBox="0 0 680 384" style="width:100%;height:auto;max-height:58%;flex:none" preserveAspectRatio="xMidYMid meet">`;
    if (!dd) { other.forEach(r => svg += edge(r, true)); base.forEach(r => svg += edge(r, false)); Tr.items.forEach((_, i) => svg += node(i, ...P[i])); }
    else {
      const merged = Tr.dedup.filter(d => d.merged);
      const inMerge = new Set(merged.flatMap(d => [d.a, d.b]));
      const mx = (P[0][0] + P[1][0]) / 2, my = (P[0][1] + P[1][1]) / 2;
      Tr.items.forEach((_, i) => { if (!inMerge.has(i)) svg += node(i, ...P[i], true); });
      if (inMerge.size) svg += node(0, mx, my, false, [...inMerge].map(i => L[i]).join("+")) +
        `<text x="${mx}" y="${my + 50}" text-anchor="middle" font-family="Plex Mono" font-size="11" fill="#c03a00">one product: the Express access is gone</text>`;
      Tr.dedup.forEach(d => { if (!d.merged && (d.a === 0 || d.b === 0)) { const [x, y] = P[d.a === 0 ? d.b : d.a]; svg += `<text x="${x}" y="${y + 48}" text-anchor="middle" font-family="Plex Mono" font-size="10.5" fill="#87827a">token set ${d.token_set} &lt; 85 · unrelated</text>`; } });
    }
    svg += `</svg>`;
    const list = Tr.items.map((it, i) => `<div style="display:grid;grid-template-columns:22px 1fr auto;gap:8px;padding:5px 0;border-top:1px solid var(--hair);align-items:baseline"><b style="font:760 13px Archivo">${L[i]}</b><span class="raw" style="font-size:12.5px">${esc(it.title)}</span><span class="tiny">${esc(it.currency)} ${it.price}</span></div>`).join("");
    root.innerHTML = `<div style="padding:12px 20px;height:100%;display:flex;flex-direction:column;gap:6px">
      <div style="display:flex;justify-content:space-between;align-items:center"><span class="label ink">${dd ? "What a plain deduplicator does · token set ≥ 85" : "Typed relations · canon/activities.py"}</span>
        <span class="legend" style="font:400 10.5px var(--mono);color:var(--ink-2);gap:4px 12px;justify-content:flex-end">${["SAME_AS", "VARIANT_OF", "INCLUDES", "DIFFERENT"].map(r => `<span style="display:inline-flex;gap:6px;align-items:center;white-space:nowrap">${relSample(r, 30)}${REL[r].label.toLowerCase()}</span>`).join("")}</span></div>
      ${svg}<div style="margin-top:auto">${list}<div class="tiny" style="margin-top:6px">Real Klook titles; relations are lexicon output, not hand-checked${dd ? "" : ". Faint lines: relations between the other products (B, C, D)"}.</div></div></div>`;
  }
  return { progress(v) { if ((v > 0.55) !== (p > 0.55) || p < 0) { p = v; render(v); } }, enter() { render(Math.max(p, 0)); } };
}

// =====================================================================================================  3.7 offers (simulated)
function offersBeat(S, N) {
  const root = $("#offersBeat"), M = S.marina, prm = M.params;
  const hotel = M.cards.find(c => /Hilton Dubai Jumeirah/.test(c.name)) || M.cards[0];
  let fc = 0.5;
  function render() {
    const rows = hotel.offers.map(o => { const flex = o.cutoff_h ? prm.flex_value_share * o.price : 0; return { ...o, adj: o.price + o.fail * fc * o.price + o.chg * prm.price_jump_share * o.price - flex }; });
    const cheapest = rows.reduce((a, b) => a.price <= b.price ? a : b), best = rows.reduce((a, b) => a.adj <= b.adj ? a : b);
    root.innerHTML = `<div class="hatched-soft" style="position:absolute;inset:0"></div><div style="position:relative;padding:20px 22px;background:transparent">
      <div class="canon-name" style="font-size:24px">${esc(hotel.name)}</div><div class="tiny" style="margin-top:4px">${hotel.offers.length} suppliers' offers for one canonical hotel · generated prices, policies and failure rates</div>
      <div style="margin-top:14px;border:1px solid var(--ink);background:var(--paper)">${rows.map(o => `<div style="display:grid;grid-template-columns:1.5fr .9fr 1.4fr .7fr 1fr;gap:10px;padding:9px 12px;border-bottom:1px solid var(--hair);align-items:baseline;${o === best ? "box-shadow:inset 4px 0 0 #ff4f00;background:var(--paper-2)" : ""}">
        <span>${srcBadge(o.src)}<div class="raw" style="font-size:12px;margin-top:4px">${esc(o.listed_as)}</div></span>
        <span class="num" style="font:640 17px var(--display)">${fmt.int(o.price)}</span>
        <span class="tiny">${esc(o.policy)}</span>
        <span class="tiny num">fails ${(o.fail * 100).toFixed(1)}%</span>
        <span class="num" style="font:${o === best ? 720 : 500} 15px var(--display);text-align:right">${fmt.int(Math.round(o.adj))}${o === best ? ' <span class="tiny signal">chosen</span>' : o === cheapest ? ' <span class="tiny">cheapest</span>' : ""}</span></div>`).join("")}</div>
      <div style="display:flex;gap:16px;align-items:center;margin-top:16px;flex-wrap:wrap"><label class="label ink" for="fcIn">Cost of a failed booking</label>
        <input id="fcIn" type="range" min="0" max="100" value="${Math.round(fc * 100)}" style="flex:1;min-width:180px;accent-color:#ff4f00"><b class="num mono">${Math.round(fc * 100)}% of price</b></div>
      <p class="tiny" style="margin-top:10px">adjusted = price + P(fail) × failure cost + P(price change) × expected jump − value of free cancellation</p>
      <p class="small" style="margin-top:6px;color:var(--ink)">${best === cheapest ? `Here the cheapest offer is also the best once risk is priced.` : `${esc(labelOf(best.src))}'s offer costs AED ${fmt.int(best.price - cheapest.price)} more on paper and wins once failure risk is priced.`}</p></div>`;
    $("#fcIn", root).addEventListener("input", e => { fc = e.target.value / 100; render(); $("#fcIn", root).focus(); });
  }
  let drawn = false;
  return { enter() { if (!drawn) { render(); drawn = true; } } };
}

// =====================================================================================================  3.8 ranking
function rankingBeat() {
  const root = $("#rankingBeat");
  root.innerHTML = `<svg viewBox="0 0 400 300" preserveAspectRatio="none" style="position:absolute;inset:24px;width:calc(100% - 48px);height:calc(100% - 48px)"><rect x=".5" y=".5" width="399" height="299" fill="none" stroke="#87827a" stroke-dasharray="3 3" vector-effect="non-scaling-stroke"/><line x1="0" y1="0" x2="400" y2="300" stroke="#dcd6c7" vector-effect="non-scaling-stroke"/><line x1="400" y1="0" x2="0" y2="300" stroke="#dcd6c7" vector-effect="non-scaling-stroke"/></svg>
    <div style="position:absolute;left:50%;top:50%;transform:translate(-50%,-50%);background:var(--paper);padding:16px 20px;border:1px solid var(--ink);max-width:360px">
    <div class="label ink">Intentionally empty</div><p class="small" style="margin:8px 0 0;color:var(--ink)">Ranking is designed (LambdaMART against a position-bias-corrected baseline) and not measured. No chart until there is a number.</p></div>`;
  return {};
}
