// 04 · The workbench. Runs the real pipeline (web/serve.py → canon/) on a preset or on uploaded feeds and draws each stage from
// the run's own intermediate outputs: records, candidate pairs, streamed model scores, routes, clusters, canonical entities.

import { MapGL, hexRGBA } from "./gl.js";
import { $, $$, el, esc, clamp, fmt, reduced, getJSON, mark, srcBadge, labelOf, shapeOf, SHAPE_ID, showReveal, hideReveal, revealHTML, relSample, REL, tag, projector } from "./util.js";
import { featName } from "./story.js";

const ROUTES = ["key_match", "key_reject", "model_accept", "model_reject", "uncertain", "no_coords_review"];
const ROUTE_TXT = { key_match: "key rule: match", key_reject: "key rule: conflict", model_accept: "model: accept", model_reject: "model: reject", uncertain: "uncertain", no_coords_review: "no coordinates: review" };
const STAGES = [["ingest", "Ingest"], ["block", "Block"], ["score", "Score"], ["cluster", "Cluster"], ["canonical", "Canonical"]];
const PRIORITY = { wikivoyage: 0, osm: 1, wikidata: 2, overture: 3 };
const W = {}; // the current run
window.__canonWB = W; // inspection handle for debugging in the browser console

export async function initWorkbench(N) {
  const status = $("#wbStatus");
  let st;
  try { st = await getJSON("/api/status"); }
  catch (e) {
    status.innerHTML = `<span class="signal">The local API is not running.</span> Start the site with <span class="mono">.venv\\Scripts\\python.exe -X utf8 web\\serve.py</span> to use the workbench.`;
    $("#presets").innerHTML = ""; return;
  }
  W.st = st; W.tAcc = st.t_accept; W.tRej = st.t_reject; W.t = st.t_accept;
  status.innerHTML = st.model && st.model.ready
    ? `Model ready: LightGBM pair model + featurizer from the 12-city run. ${st.loco && st.loco.ready ? "Leave-one-city-out models present, so labelled pairs of a preset city are scored by a model that never saw that city." : `<span class="signal">Leave-one-city-out models missing</span> (labelled pairs will be scored in-sample). Rebuild: <span class="mono">${esc(st.loco.rebuild)}</span>`}`
    : `<span class="signal">Model files missing: ${esc((st.model.missing || []).join(", "))}.</span> Rebuild with <span class="mono">${esc(st.model.rebuild)}</span>`;
  initMap(); initTimeline(); initPresets(st); initUpload(); initThreshold(); initBenches(); initGates();
}

// ===================================================================================================== map
function initMap() {
  const cv = $("#wbCanvas");
  W.map = new MapGL(cv, { ink: hexRGBA("#ece7da", 1), sig: hexRGBA("#ff5a14", 1), dim: hexRGBA("#a7a193", .9) });
  Object.assign(W.map.u, { size: 3.4, alpha: .82, dur: .5, grow: 0, fadeMerged: 0, t: 0, wscale: 1 });
  const ro = new ResizeObserver(() => { W.map.resize(); draw(); }); ro.observe($("#wbMap"));
  let drag = null;
  cv.addEventListener("wheel", e => { if (!W.n) return; e.preventDefault(); zoomAt(...local(e), Math.exp(-e.deltaY * 0.0015)); }, { passive: false });
  cv.addEventListener("pointerdown", e => { drag = { x: e.clientX, y: e.clientY, cx: W.map.view.cx, cy: W.map.view.cy, moved: false }; try { cv.setPointerCapture(e.pointerId); } catch { /* synthetic pointer */ } });
  cv.addEventListener("pointermove", e => {
    if (drag) { const dx = e.clientX - drag.x, dy = e.clientY - drag.y; if (Math.abs(dx) + Math.abs(dy) > 3) drag.moved = true;
      W.map.view.cx = drag.cx - dx / W.map.view.scale; W.map.view.cy = drag.cy + dy / W.map.view.scale; draw(); return; }
    hover(e);
  });
  cv.addEventListener("pointerup", e => { const d = drag; drag = null; if (d && !d.moved) click(e); });
  cv.addEventListener("pointerleave", () => { hideReveal(); setHover(-1); });
  $("#zin").onclick = () => zoomAt(W.map.w / 2, W.map.h / 2, 1.6);
  $("#zout").onclick = () => zoomAt(W.map.w / 2, W.map.h / 2, 1 / 1.6);
  $("#zfit").onclick = () => { fitView(); draw(); };
  // drag-and-drop feeds onto the map
  const box = $("#wbMap");
  box.addEventListener("dragover", e => { e.preventDefault(); box.classList.add("drag"); });
  box.addEventListener("dragleave", () => box.classList.remove("drag"));
  box.addEventListener("drop", e => { e.preventDefault(); box.classList.remove("drag"); handleFiles(e.dataTransfer.files); });
}
function zoomAt(sx, sy, k) {
  const m = W.map, [dx, dy] = m.toData(sx, sy);
  m.view.scale = clamp(m.view.scale * k, 2, 5e6);
  const [nx, ny] = m.toData(sx, sy); m.view.cx += dx - nx; m.view.cy += dy - ny; draw();
}
let raf = 0;
function local(e) { const r = W.map.canvas.getBoundingClientRect(); return [e.clientX - r.left, e.clientY - r.top]; }
function draw() {
  if (raf) return;
  raf = requestAnimationFrame(() => {
    raf = 0; if (!W.map) return;
    // marks grow a little as you zoom in, so street level stays readable
    const z = W.fitScale ? W.map.view.scale / W.fitScale : 1;
    W.map.u.size = (W.baseSize || 3.4) * clamp(1 + Math.log2(Math.max(z, 1)) * 0.22, 1, 2.3);
    W.map.draw(); coordsHud(); labels();
  });
}
// Street-level labels: raw names in mono; once clustered, the canonical name of each entity (raw names stay one hover away)
function labels() {
  const cv = $("#wbLabels"), m = W.map, dpr = m.dpr;
  if (cv.width !== m.canvas.width || cv.height !== m.canvas.height) { cv.width = m.canvas.width; cv.height = m.canvas.height; }
  const ctx = cv.getContext("2d"); ctx.setTransform(dpr, 0, 0, dpr, 0, 0); ctx.clearRect(0, 0, m.w, m.h);
  if (!W.n || m.view.scale < 30000 || !W.names) return; // closer than about 370 m per 100 px
  const snap = (W.shown === "cluster" || W.shown === "canonical") && W.root, seen = new Set(), cand = [];
  for (let i = 0; i < W.n; i++) {
    if (!W.has[i]) continue;
    const r = snap ? W.root[i] : i, multi = snap && W.size[r] > 1;
    if (multi && seen.has(r)) continue; if (multi) seen.add(r);
    const [sx, sy] = m.toScreen(multi ? W.cx[r] : W.X[i], multi ? W.cy[r] : W.Y[i]);
    if (sx < 0 || sy < 0 || sx > m.w || sy > m.h) continue;
    cand.push([sx, sy, multi ? r : -1, i, (sx - m.w / 2) ** 2 + (sy - m.h / 2) ** 2]);
  }
  cand.sort((a, b) => a[4] - b[4]);
  const boxes = [];
  for (const [sx, sy, r, i] of cand.slice(0, 260)) {
    const canon = r >= 0, text = canon ? canonName(membersOf(i)) : W.names[i];
    ctx.font = canon ? "600 11.5px Archivo, sans-serif" : "500 10.5px 'Plex Mono', 'Plex Arabic', 'Plex Thai', 'Plex Devanagari', monospace";
    const t = text.length > 34 ? text.slice(0, 33) + "…" : text, w = ctx.measureText(t).width, bx = sx + 7, by = sy - 7;
    if (boxes.some(b => bx < b[0] + b[2] + 4 && bx + w + 4 > b[0] && by < b[1] + 14 && by + 14 > b[1])) continue;
    boxes.push([bx, by, w]);
    ctx.fillStyle = "rgba(18,17,13,.78)"; ctx.fillRect(bx - 2, by - 1, w + 4, 14);
    ctx.fillStyle = canon ? "#ece7da" : "#a7a193"; ctx.textBaseline = "top"; ctx.fillText(t, bx, by + 1);
    if (canon) { ctx.fillStyle = "#ff7a3d"; ctx.font = "500 9.5px 'Plex Mono', monospace"; ctx.fillText("×" + W.size[r], bx + w + 6, by + 2); }
  }
}
function coordsHud() {
  if (!W.proj) return;
  const [x, y] = W.map.toData(W.map.w / 2, W.map.h / 2);
  const per100 = 111320 / W.map.view.scale * 100;
  $("#wbCoords").textContent = `${(y + W.oy).toFixed(4)}°, ${W.proj.lon(x + W.ox).toFixed(4)}° · 100 px = ${per100 < 1000 ? Math.round(per100) + " m" : (per100 / 1000).toFixed(per100 < 10000 ? 1 : 0) + " km"}`;
}
function fitView() {
  if (!W.n) return;
  const xs = [], ys = [];
  for (let i = 0; i < W.n; i++) if (W.has[i]) { xs.push(W.X[i]); ys.push(W.Y[i]); }
  if (!xs.length) return;
  xs.sort((a, b) => a - b); ys.sort((a, b) => a - b);
  const q = (a, f) => a[Math.min(a.length - 1, Math.max(0, Math.round(f * (a.length - 1))))];
  W.map.fit(q(xs, .01), q(ys, .01), q(xs, .99), q(ys, .99), 30, "contain");
}

// ===================================================================================================== presets, uploads, runs
async function initPresets(st) {
  const box = $("#presets");
  let presets = [];
  try { presets = await getJSON("/api/presets"); } catch (e) { box.innerHTML = `<p class="small signal">${esc(e.message)}</p>`; return; }
  box.innerHTML = presets.map(p => `<button data-id="${esc(p.id)}" class="${p.group === "ota" ? "wide" : ""}" ${st.model && st.model.ready ? "" : "disabled"} title="${esc(p.note || "")}">
    <span class="pn">${esc(p.label)}</span><span class="pc num">${fmt.int(p.records)}${p.group === "city" ? ` · ${fmt.int(p.lodging)} lodging` : " records"}</span></button>`).join("");
  box.addEventListener("click", e => { const b = e.target.closest("button[data-id]"); if (b && !W.busy) startRun({ preset: b.dataset.id }, presets.find(p => p.id === b.dataset.id).label, b); });
  $("#presetNote").textContent = `${presets.length} presets`;
}
function initUpload() {
  $("#fileIn").addEventListener("change", e => handleFiles(e.target.files));
  const d = $("#drop");
  d.addEventListener("dragover", e => { e.preventDefault(); d.style.borderColor = "var(--signal)"; });
  d.addEventListener("dragleave", () => d.style.borderColor = "");
  d.addEventListener("drop", e => { e.preventDefault(); d.style.borderColor = ""; handleFiles(e.dataTransfer.files); });
}
async function handleFiles(list) {
  const files = [...(list || [])]; if (!files.length) return;
  const rep = $("#vreport");
  const total = files.reduce((a, f) => a + f.size, 0);
  if (total > 40e6) { rep.innerHTML = `<div class="err">These files are ${(total / 1e6).toFixed(1)} MB together; the limit is 40 MB.</div>`; return; }
  rep.innerHTML = `<div class="warn">Reading ${files.length} file${files.length > 1 ? "s" : ""}…</div>`;
  // raw bytes, base64: the server detects the encoding (UTF-8, or a cp1252 fallback it reports as a warning)
  const toB64 = buf => { const u = new Uint8Array(buf); let s = ""; for (let i = 0; i < u.length; i += 0x8000) s += String.fromCharCode.apply(null, u.subarray(i, i + 0x8000)); return btoa(s); };
  const payload = { files: await Promise.all(files.map(async f => ({ name: f.name, b64: toB64(await f.arrayBuffer()) }))) };
  let res;
  try { res = await getJSON("/api/uploads", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) }); }
  catch (e) { res = e.body && e.body.report ? e.body : null; if (!res) { rep.innerHTML = `<div class="err">${esc(e.message)}</div>`; return; } }
  const R = res.report || {};
  const line = p => `<li class="${p.level === "error" ? "err" : p.level === "warn" ? "warn" : "ok"}">${esc(p.text)}</li>`;
  rep.innerHTML = `<div class="${res.ok ? "ok" : "err"}">${res.ok ? `✓ ${fmt.int(R.records || 0)} usable records from ${(R.sources || []).length} sources` : "✗ Not runnable yet"}</div>
    ${(R.files || []).map(f => `<div style="margin-top:6px"><b>${esc(f.name)}</b> · ${esc(f.format || "?")} · ${fmt.int(f.usable || 0)} of ${fmt.int(f.rows || 0)} rows usable · source ${f.source ? `<span class="raw">${esc(f.source)}</span>` : "from its source column"}
      ${(f.problems || []).length ? `<ul>${f.problems.map(line).join("")}</ul>` : ""}</div>`).join("")}
    ${(R.problems || []).length ? `<ul>${R.problems.map(line).join("")}</ul>` : ""}
    ${(R.missing || []).length ? `<div style="margin-top:6px">Missing optional fields:</div><ul>${R.missing.map(m => `<li class="warn"><b>${esc(m.field)}</b>: ${esc(m.effect)}</li>`).join("")}</ul>` : ""}
    ${res.ok ? `<button class="btn sm solid" id="runUpload" style="margin-top:8px">Run on these feeds</button>` : ""}`;
  if (res.ok) $("#runUpload").onclick = () => startRun({ upload_id: res.upload_id }, files.map(f => f.name).join(" + "), null);
}

async function startRun(body, label, btn) {
  if (W.busy) return;
  $$("#presets button").forEach(b => b.classList.toggle("on", b === btn));
  resetRun(label);
  let r;
  try { r = await getJSON("/api/runs", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }); }
  catch (e) { hud(`<span class="signal">${esc(e.message)}</span>${e.body && e.body.fix ? ` · <span class="mono">${esc(e.body.fix)}</span>` : ""}`); W.busy = false; return; }
  W.id = r.run_id; W.busy = true;
  const es = new EventSource(`/api/runs/${W.id}/events`); W.es = es;
  const runId = W.id;
  es.addEventListener("queued", e => { if (W.id === runId) { const d = JSON.parse(e.data); hud(`${esc(W.label)} · queued · ${esc(d.note || "another run is computing")}`); } });
  es.addEventListener("stage", e => { if (W.id === runId) onStage(JSON.parse(e.data)); });
  es.addEventListener("score", e => { if (W.id === runId) onScore(JSON.parse(e.data)); });
  es.addEventListener("done", e => { if (W.id !== runId) return; const d = JSON.parse(e.data); W.busy = false; es.close(); hud(`${esc(W.label)} · done in ${d.seconds.toFixed(1)} s`); loadQueue(); });
  es.addEventListener("error", e => { if (W.id !== runId) return; if (e.data) { const d = JSON.parse(e.data); hud(`<span class="signal">${esc(d.error)}</span>${d.fix ? ` · <span class="mono">${esc(d.fix)}</span>` : ""}`); } W.busy = false; es.close(); });
}
function resetRun(label) {
  if (W.es) W.es.close();
  Object.assign(W, { label, id: null, n: 0, ne: 0, ready: new Set(), shown: null, P: null, root: null, route: null, selected: -1, hoverI: -1, canon: null, startT: performance.now() });
  W.map.setPoints({ pos: new Float32Array(0), shape: new Float32Array(0) }); W.map.setEdges({ pa: new Float32Array(0), pb: new Float32Array(0), w: new Float32Array(0), col: new Float32Array(0), alpha: new Float32Array(0) });
  $("#wbEmpty").style.display = "none"; $("#thr").disabled = true; $("#prGrid").innerHTML = ""; $("#prNote").textContent = "";
  $("#inspector").innerHTML = `<h4><span class="label ink">Inspector</span></h4><p class="small">Click a point for its records, or an edge for the pair.</p>`;
  $("#queue").innerHTML = `<p class="small">The queue fills when the run finishes.</p>`;
  hud(`${esc(label)} · starting`); renderTimeline(); gates(); draw();
}
function hud(html) { $("#wbHud").innerHTML = `<span class="tag" style="background:var(--bg)">${html}</span>`; }

async function arr(name) {
  const r = await fetch(`/api/runs/${W.id}/array/${name}`);
  if (!r.ok) throw new Error(`array ${name}: ${r.status}`);
  const buf = await r.arrayBuffer(), dt = r.headers.get("X-Dtype");
  return new ({ int32: Int32Array, float32: Float32Array, uint8: Uint8Array, int8: Int8Array, float64: Float64Array }[dt])(buf);
}

async function onStage(d) {
  const t = d.t != null ? ` · ${d.t.toFixed(1)} s` : "";
  if (d.status === "start") { W.running = d.stage; renderTimeline(); hud(`${esc(W.label)} · ${d.stage}${d.stage === "block" && W.n > 40000 ? " · a large city: blocking takes a minute or two" : ""}${d.stage === "score" && d.loco ? ` · labelled pairs: ${d.loco === "used" ? "model without this city" : d.loco}` : ""}${t}`); return; }
  W.running = null; W.ready.add(d.stage); W.ev = W.ev || {}; W.ev[d.stage] = d;
  if (d.stage === "ingest") await onIngest(d);
  else if (d.stage === "block") await onBlock(d);
  else if (d.stage === "score") { show("score"); }
  else if (d.stage === "route") await onRoute(d);
  else if (d.stage === "cluster") await onCluster(d);
  else if (d.stage === "canonical") await onCanonical(d);
  renderTimeline(); gates();
  hud(`${esc(W.label)} · ${d.stage} done${t}`);
}
async function onIngest(d) {
  const [lat, lon, src, kind, qid, rec] = await Promise.all([arr("lat"), arr("lon"), arr("src"), arr("kind"), arr("qid"), getJSON(`/api/runs/${W.id}/records`)]);
  const n = lat.length; W.n = n; W.sources = rec.sources; W.names = rec.name; W.srcId = rec.src_id; W.lat = lat; W.lon = lon; W.src = src; W.kind = kind; W.qid = qid;
  let s = 0, c = 0; for (let i = 0; i < n; i++) if (lat[i] === lat[i]) { s += lat[i]; c++; }
  W.proj = projector(c ? s / c : 0); W.oy = c ? s / c : 0;
  let sx = 0; for (let i = 0; i < n; i++) if (lon[i] === lon[i]) sx += W.proj.x(lon[i]); W.ox = c ? sx / c : 0;
  W.X = new Float32Array(n); W.Y = new Float32Array(n); W.has = new Uint8Array(n);
  for (let i = 0; i < n; i++) { const ok = lat[i] === lat[i] && lon[i] === lon[i]; W.has[i] = ok; W.X[i] = ok ? W.proj.x(lon[i]) - W.ox : 0; W.Y[i] = ok ? lat[i] - W.oy : 0; }
  W.shape = new Float32Array(n); for (let i = 0; i < n; i++) W.shape[i] = SHAPE_ID[shapeOf(W.sources[src[i]], src[i])];
  W.baseSize = n > 40000 ? 2.4 : n > 12000 ? 2.9 : 3.4;
  fitView(); W.fitScale = W.map.view.scale; show("ingest");
}
async function onBlock(d) {
  const [ra, rb, gen, dist] = await Promise.all([arr("ra"), arr("rb"), arr("gen"), arr("dist")]);
  Object.assign(W, { ra, rb, gen, dist, ne: ra.length, P: new Float32Array(ra.length).fill(NaN) });
  W.scored = 0;
  show("block");
}
function onScore(d) {
  if (!W.P) return;
  const idx = new Int32Array(b64(d.idx_b64)), p = new Float32Array(b64(d.p_b64));
  for (let i = 0; i < idx.length; i++) W.P[idx[i]] = p[i];
  W.scored = d.done; W.scoreTotal = d.total;
  if (W.shown === "block" || W.shown === "score") {
    if (W.shown !== "score") show("score"); else { styleEdges("score", idx); }
  }
  hud(`${esc(W.label)} · scoring ${fmt.int(d.done)} / ${fmt.int(d.total)}`);
  gates(); renderTimeline();
}
function b64(s) { const bin = atob(s), u = new Uint8Array(bin.length); for (let i = 0; i < bin.length; i++) u[i] = bin.charCodeAt(i); return u.buffer; }
async function onRoute(d) {
  const [p, route, y, model] = await Promise.all([arr("p"), arr("route"), arr("y"), arr("model")]);
  Object.assign(W, { P: p, routeSrv: route, route, y, model, routeCounts: d.counts });
  W.labelled = d.labelled || { pos: 0, neg: 0 };
  // hand the arrays to the worker for live re-clustering
  W.worker && W.worker.terminate();
  W.worker = new Worker("js/wb-worker.js");
  W.worker.onmessage = e => onWorker(e.data);
  W.worker.postMessage({ type: "init", n: W.n, ra: W.ra, rb: W.rb, p: W.P, y, dist: W.dist, qid: W.qid, t_reject: W.tRej });
}
async function onCluster(d) {
  W.rootSrv = await arr("cluster");
  W.root = W.rootSrv; W.clusterInfo = d;
  centroids(); show("cluster");
  $("#thr").disabled = false; $("#thr").value = W.tAcc; W.t = W.tAcc; thrLabel();
  W.worker.postMessage({ type: "recluster", t: W.t });
}
async function onCanonical() {
  try { W.canon = await getJSON(`/api/runs/${W.id}/canonical`); W.canonByRoot = new Map(W.canon.entities.map(e => [e.id, e])); } catch { W.canon = null; }
  show("canonical");
}
function onWorker(m) {
  if (m.type !== "clusters") return;
  const first = !W.workerChecked;
  if (first) { // the port must reproduce the server's clustering at the default threshold
    W.workerChecked = true;
    const srv = W.ev.cluster.entities;
    W.parity = srv === m.entities ? `matches the server's ${fmt.int(srv)} entities` : `<span class="signal">worker ${fmt.int(m.entities)} vs server ${fmt.int(srv)} entities</span>`;
  }
  if (Math.abs(m.t - W.t) > 1e-9) return;
  W.root = m.root; W.route = m.route; W.routeCounts = Object.fromEntries(ROUTES.map((r, i) => [r, m.counts[i]]));
  W.prNow = m; centroids();
  if (W.shown === "cluster" || W.shown === "canonical") show(W.shown, true);
  gates(); prPanel();
}

// ===================================================================================================== stage views (driven by the run's own outputs)
function centroids() {
  const n = W.n, sx = new Float64Array(n), sy = new Float64Array(n), c = new Int32Array(n), size = new Int32Array(n);
  for (let i = 0; i < n; i++) { const r = W.root[i]; size[r]++; if (W.has[i]) { sx[r] += W.X[i]; sy[r] += W.Y[i]; c[r]++; } }
  W.size = size; W.cx = new Float32Array(n); W.cy = new Float32Array(n);
  for (let r = 0; r < n; r++) if (c[r]) { W.cx[r] = sx[r] / c[r]; W.cy[r] = sy[r] / c[r]; }
}
function show(stage, quiet = false) {
  W.shown = stage; renderTimeline();
  const n = W.n, snap = stage === "cluster" || stage === "canonical";
  const multi = snap ? (() => { let k = 0; for (let r = 0; r < n; r++) if (W.root[r] === r && W.size[r] > 1) k++; return k; })() : 0;
  const np = n + multi;
  const pos = new Float32Array(np * 2), tgt = new Float32Array(np * 2), tau = new Float32Array(np).fill(-1), shape = new Float32Array(np), state = new Float32Array(np);
  for (let i = 0; i < n; i++) {
    pos[2 * i] = W.X[i]; pos[2 * i + 1] = W.Y[i]; shape[i] = W.shape[i]; state[i] = W.has[i] ? 0 : -1;
    const r = snap ? W.root[i] : i;
    if (snap && W.size[r] > 1 && W.has[i]) { tgt[2 * i] = W.cx[r]; tgt[2 * i + 1] = W.cy[r]; tau[i] = 0; } else { tgt[2 * i] = W.X[i]; tgt[2 * i + 1] = W.Y[i]; }
  }
  if (snap) { let k = n; for (let r = 0; r < n; r++) if (W.root[r] === r && W.size[r] > 1) { pos[2 * k] = tgt[2 * k] = W.cx[r]; pos[2 * k + 1] = tgt[2 * k + 1] = W.cy[r]; tau[k] = 0; shape[k] = 8; state[k] = 4; k++; } }
  W.map.setPoints({ pos, tgt, tau, shape, state }); W.pointState = state;
  if (stage !== "ingest" && W.ne) {
    const ne = W.ne, pa = new Float32Array(ne * 2), pb = new Float32Array(ne * 2), ta = new Float32Array(ne * 2), tb = new Float32Array(ne * 2), etau = new Float32Array(ne).fill(snap ? 0 : -1);
    for (let k = 0; k < ne; k++) {
      const a = W.ra[k], b = W.rb[k];
      pa[2 * k] = W.X[a]; pa[2 * k + 1] = W.Y[a]; pb[2 * k] = W.X[b]; pb[2 * k + 1] = W.Y[b];
      const A = snap && W.size[W.root[a]] > 1 && W.has[a], B = snap && W.size[W.root[b]] > 1 && W.has[b];
      ta[2 * k] = A ? W.cx[W.root[a]] : W.X[a]; ta[2 * k + 1] = A ? W.cy[W.root[a]] : W.Y[a];
      tb[2 * k] = B ? W.cx[W.root[b]] : W.X[b]; tb[2 * k + 1] = B ? W.cy[W.root[b]] : W.Y[b];
    }
    const s = styleArrays(stage);
    W.map.setEdges({ pa, pb, ta, tb, tau: etau, ...s }); W.edgeStyle = s;
  } else W.map.setEdges({ pa: new Float32Array(0), pb: new Float32Array(0), w: new Float32Array(0), col: new Float32Array(0), alpha: new Float32Array(0) });
  W.map.u.fadeMerged = snap ? 1 : 0;
  if (snap && !quiet && !reduced()) { const t0 = performance.now(); const anim = () => { const u = clamp((performance.now() - t0) / 1100); W.map.u.t = u; W.map.draw(); if (u < 1) requestAnimationFrame(anim); }; W.map.u.t = 0; requestAnimationFrame(anim); }
  else W.map.u.t = snap ? 1 : 0;
  draw();
}
function edgeLook(stage, k) {
  const p = W.P ? W.P[k] : NaN;
  if (stage === "block" || (stage === "score" && p !== p)) return [0.8, 2, 0.16, 0];
  if (stage === "score") return p >= W.t ? [1.5, 0, 0.9, 0] : p >= W.tRej ? [1.1, 1, 0.85, 0] : [0.6, 2, 0.05, 0];
  const r = W.route[k];
  if (r === 0) return [2.2, 0, 1, 0];                         // key match
  if (r === 2) return [1.5, 0, 0.9, 0];                       // model accept
  if (r === 4) return [1.1, 1, 0.9, 0];                       // uncertain: the signal colour
  if (r === 5) return [1.1, 1, 0.75, 1];                      // no coordinates: dashed
  if (r === 1) return [0.9, 2, stage === "canonical" ? 0 : 0.4, 2]; // key conflict: dotted
  return [0.5, 2, stage === "canonical" ? 0 : 0.035, 0];       // model reject
}
function styleArrays(stage) {
  const ne = W.ne, w = new Float32Array(ne), col = new Float32Array(ne), alpha = new Float32Array(ne), pat = new Float32Array(ne);
  for (let k = 0; k < ne; k++) { const s = edgeLook(stage, k); w[k] = s[0]; col[k] = s[1]; alpha[k] = s[2]; pat[k] = s[3]; }
  return { w, col, alpha, pat };
}
function styleEdges(stage, idx) {
  const s = W.edgeStyle; if (!s) return;
  for (const k of idx) { const v = edgeLook(stage, k); s.w[k] = v[0]; s.col[k] = v[1]; s.alpha[k] = v[2]; s.pat[k] = v[3]; }
  W.map.updateEdges("w", s.w); W.map.updateEdges("col", s.col); W.map.updateEdges("alpha", s.alpha); W.map.updateEdges("pat", s.pat); draw();
}

// ===================================================================================================== timeline scrubber
function initTimeline() {
  $("#timeline").innerHTML = STAGES.map(([id, nm], i) => `<button data-s="${id}"><span class="tn">0${i + 1}</span><span class="tt">${nm}</span><span class="tv" id="tv-${id}">—</span></button>`).join("");
  $("#timeline").addEventListener("click", e => { const b = e.target.closest("button"); if (!b || !W.ready || !canShow(b.dataset.s)) return; show(b.dataset.s); gates(); });
  addEventListener("keydown", e => {
    if (!W.shown || !["ArrowLeft", "ArrowRight"].includes(e.key) || !e.target.closest || !e.target.closest("#timeline")) return;
    const i = STAGES.findIndex(s => s[0] === W.shown) + (e.key === "ArrowRight" ? 1 : -1);
    if (STAGES[i] && canShow(STAGES[i][0])) { show(STAGES[i][0]); $(`#timeline button[data-s=${STAGES[i][0]}]`).focus(); }
  });
}
function canShow(s) { return s === "score" ? W.ready.has("block") && W.scored > 0 : s === "cluster" ? W.ready.has("cluster") && W.route : W.ready.has(s); }
function renderTimeline() {
  if (!W.ready) return;
  const ev = W.ev || {};
  const val = {
    ingest: ev.ingest ? `${fmt.int(ev.ingest.records)} records` : "",
    block: ev.block ? `${fmt.int(ev.block.candidates)} pairs · ${ev.block.per_record.toFixed(1)}/record` : "",
    score: W.scoreTotal ? `${fmt.int(W.scored)} / ${fmt.int(W.scoreTotal)} scored` : "",
    cluster: W.prNow ? `${fmt.int(W.prNow.entities)} entities` : ev.cluster ? `${fmt.int(ev.cluster.entities)} entities` : "",
    canonical: ev.canonical || W.canon ? `${fmt.int((W.prNow || ev.cluster || {}).multi || (W.canon ? W.canon.entities.length : 0))} merged · export` : "",
  };
  for (const [id] of STAGES) {
    const b = $(`#timeline button[data-s=${id}]`); if (!b) continue;
    b.classList.toggle("ready", canShow(id)); b.classList.toggle("cur", W.shown === id); b.classList.toggle("run", W.running === id || (id === "score" && W.running === "score"));
    $(`#tv-${id}`).textContent = val[id] || (W.running === id ? "running…" : "—");
  }
}

// ===================================================================================================== cascade gates
function initGates() { gates(); }
function gates() {
  const box = $("#gates"); if (!box) return;
  const total = W.ne || 0;
  const c = W.routeCounts || null;
  let rows;
  if (c) {
    rows = [["Gate 0 · key rules", c.key_match + c.key_reject, `match ${fmt.int(c.key_match)} · conflict ${fmt.int(c.key_reject)}`, ""],
            ["Gate 1 · pair model", c.model_accept + c.model_reject, `accept ≥ ${W.t.toFixed(3)}: ${fmt.int(c.model_accept)} · reject < ${W.tRej}: ${fmt.int(c.model_reject)}`, ""],
            ["Uncertain → next stage", c.uncertain + (c.no_coords_review || 0), `${fmt.int(c.uncertain)} uncertain${c.no_coords_review ? ` · ${fmt.int(c.no_coords_review)} without coordinates` : ""}`, "unc"]];
  } else if (W.P && W.scored) {
    let a = 0, u = 0, r = 0; for (let k = 0; k < W.ne; k++) { const p = W.P[k]; if (p !== p) continue; if (p >= W.t) a++; else if (p >= W.tRej) u++; else r++; }
    rows = [["Gate 0 · key rules", null, "applied after scoring", ""], ["Gate 1 · pair model", a + r, `accept ${fmt.int(a)} · reject ${fmt.int(r)} (provisional)`, ""], ["Uncertain → next stage", u, "provisional, before key rules", "unc"]];
  } else rows = [["Gate 0 · key rules", null, "Wikidata ID, rare phone or website", ""], ["Gate 1 · pair model", null, `LightGBM on ${(W.st && W.st.features || []).length} features`, ""], ["Uncertain → next stage", null, "", "unc"]];
  box.innerHTML = rows.map(([nm, v, sub, cls]) => `<div class="gate ${cls}"><span class="gn">${nm}</span><span class="gc num">${v === null ? "—" : fmt.int(v)}</span>
    <span class="gs">${sub}</span><span class="gbar"><i style="width:${v && total ? (v / total * 100).toFixed(2) : 0}%"></i></span></div>`).join("") +
    `<div class="gate notbuilt"><span class="gn">Cross-encoder · LLM · human</span><span class="gc">${tag("notbuilt", "Not built")}</span><span class="gs">the uncertain share would go here; the review queue below is the human step, by hand</span></div>`;
  $("#gateTotal").textContent = total ? `${fmt.int(total)} candidate pairs` : "";
}

// ===================================================================================================== threshold + precision / recall
function initThreshold() {
  const s = $("#thr");
  let pend = 0;
  s.addEventListener("input", () => { W.t = +s.value; thrLabel(); cancelAnimationFrame(pend); pend = requestAnimationFrame(() => W.worker && W.worker.postMessage({ type: "recluster", t: W.t })); });
  thrLabel();
  $("#expCsv").onclick = () => exportCanonical("csv");
  $("#expJson").onclick = () => exportCanonical("json");
}
function thrLabel() { $("#thrVal").textContent = `p ≥ ${(+$("#thr").value).toFixed(3)}${Math.abs(+$("#thr").value - (W.tAcc || 0)) < 5e-4 ? " · default" : ""}`; }
function prPanel() {
  const m = W.prNow; if (!m) return;
  const { tp, fp, fn, pos, neg } = m.pr;
  const ro = (k, v, sub) => `<div class="readout"><div class="k"><span>${k}</span></div><div class="v num">${v}</div><div class="sub">${sub}</div></div>`;
  const has = pos + neg > 0;
  $("#prGrid").innerHTML = ro("Entities", fmt.int(m.entities), `${fmt.int(m.multi)} merged · ${fmt.int(m.blocked)} refused`) +
    ro("Precision", has && tp + fp ? fmt.pct1(tp / (tp + fp)) : "—", has ? `${fmt.int(fp)} wrong of ${fmt.int(tp + fp)}` : "no labels") +
    ro("Recall", has && pos ? fmt.pct1(tp / pos) : "—", has ? `${fmt.int(tp)} of ${fmt.int(pos)} matches` : "no labels");
  const loco = W.ev && W.ev.score && W.ev.score.loco;
  $("#prNote").innerHTML = has
    ? `The pair model alone, against this run's weak labels: ${fmt.int(pos)} key matches, ${fmt.int(neg)} key conflicts. ${loco === "used" ? "Those pairs are scored by the model trained without this city." : "<span class='signal'>Labelled pairs scored in-sample.</span>"} Clustering ${W.parity || ""}. ${tag("keys")}`
    : `This feed has no independent keys, so precision and recall cannot be measured here. ${tag("nolabel")}`;
}

// ===================================================================================================== hover, click, inspector
function nearestPoint(sx, sy, maxPx = 9) {
  if (!W.n) return -1;
  const [dx, dy] = W.map.toData(sx, sy), r = maxPx / W.map.view.scale; let best = -1, bd = r * r;
  const snap = (W.shown === "cluster" || W.shown === "canonical") && W.root;
  for (let i = 0; i < W.n; i++) {
    if (!W.has[i]) continue;
    let x = W.X[i], y = W.Y[i];
    if (snap && W.size[W.root[i]] > 1) { x = W.cx[W.root[i]]; y = W.cy[W.root[i]]; }
    const d = (x - dx) ** 2 + (y - dy) ** 2; if (d < bd) { bd = d; best = i; }
  }
  return best;
}
function membersOf(i) {
  if (!W.root) return [i];
  if (W._mbFor !== W.root) { // one pass per clustering, then O(1) lookups
    const m = new Map(); for (let j = 0; j < W.n; j++) { const r = W.root[j]; let a = m.get(r); if (!a) m.set(r, a = []); a.push(j); }
    W._mb = m; W._mbFor = W.root;
  }
  return W._mb.get(W.root[i]) || [i];
}
function canonName(ms) {
  const sorted = ms.slice().sort((a, b) => (/[A-Za-z]/.test(W.names[b]) - /[A-Za-z]/.test(W.names[a])) || ((PRIORITY[W.sources[W.src[a]]] ?? 9) - (PRIORITY[W.sources[W.src[b]]] ?? 9)));
  return W.names[sorted[0]];
}
let hoverRaf = 0;
function hover(e) {
  if (hoverRaf) return;
  hoverRaf = requestAnimationFrame(() => {
    hoverRaf = 0;
    const i = nearestPoint(...local(e));
    if (i < 0) { hideReveal(); setHover(-1); return; }
    const snap = W.shown === "cluster" || W.shown === "canonical";
    const ms = snap ? membersOf(i) : [i];
    const title = ms.length > 1 ? canonName(ms) : W.names[i];
    showReveal(revealHTML(title, ms.slice(0, 9).map(j => ({ src: W.sources[W.src[j]], i: W.src[j], name: W.names[j] })),
      ms.length > 1 ? `${ms.length} listings · canonical on top, raw underneath${ms.length > 9 ? ` · ${ms.length - 9} more` : ""}` : `${labelOf(W.sources[W.src[i]])} · ${W.srcId[i]}`), e.clientX, e.clientY, true);
    setHover(i);
  });
}
function setHover(i) { W.hoverI = i; }
function click(e) {
  const i = nearestPoint(...local(e));
  if (i >= 0) { inspectCluster(i); return; }
  const k = nearestEdge(...local(e)); if (k >= 0) inspectPair(k);
}
function nearestEdge(sx, sy) {
  if (!W.ne || !W.edgeStyle || W.shown === "ingest") return -1;
  const m = W.map, s = W.edgeStyle, snap = W.shown === "cluster" || W.shown === "canonical";
  let best = -1, bd = 36;
  for (let k = 0; k < W.ne; k++) {
    if (s.alpha[k] < 0.06) continue;
    const a = W.ra[k], b = W.rb[k]; if (!W.has[a] || !W.has[b]) continue;
    let ax = W.X[a], ay = W.Y[a], bx = W.X[b], by = W.Y[b];
    if (snap) { if (W.size[W.root[a]] > 1) { ax = W.cx[W.root[a]]; ay = W.cy[W.root[a]]; } if (W.size[W.root[b]] > 1) { bx = W.cx[W.root[b]]; by = W.cy[W.root[b]]; } }
    const [x1, y1] = m.toScreen(ax, ay), [x2, y2] = m.toScreen(bx, by);
    const dx = x2 - x1, dy = y2 - y1, L = dx * dx + dy * dy; if (L < 4) continue;
    const t = clamp(((sx - x1) * dx + (sy - y1) * dy) / L), px = x1 + t * dx - sx, py = y1 + t * dy - sy, d = px * px + py * py;
    if (d < bd) { bd = d; best = k; }
  }
  return best;
}
function highlight(ms) {
  const st = W.pointState; if (!st) return;
  for (let i = 0; i < W.n; i++) if (st[i] !== -1) st[i] = 0;
  for (const j of ms) if (st[j] !== -1) st[j] = 2;
  W.map.updatePoints("state", st); draw();
}
function inspectCluster(i) {
  const ms = membersOf(i); highlight(ms);
  const inside = [];
  if (W.ne && ms.length > 1) { const set = new Set(ms); for (let k = 0; k < W.ne; k++) if (set.has(W.ra[k]) && set.has(W.rb[k])) inside.push(k); }
  inside.sort((a, b) => (W.P[b] || 0) - (W.P[a] || 0));
  $("#inspector").innerHTML = `<h4><span class="label ink">${ms.length > 1 ? "Canonical entity" : "Record"}</span><span class="tiny">${ms.length} listing${ms.length > 1 ? "s" : ""}</span></h4>
    <div class="canon-name" style="font-size:20px;line-height:1.15">${esc(ms.length > 1 ? canonName(ms) : W.names[i])}</div>
    <div class="tiny" style="margin:4px 0 8px">${W.lat[i] === W.lat[i] ? `${W.lat[i].toFixed(5)}, ${W.lon[i].toFixed(5)}` : "no coordinates"}</div>
    ${ms.map(j => `<div class="rec">${mark(W.sources[W.src[j]], W.src[j])}<span class="raw">${esc(W.names[j])}</span><span class="meta">${esc(labelOf(W.sources[W.src[j]]))} · ${esc(W.srcId[j])}</span></div>`).join("")}
    ${inside.length ? `<div class="label ink" style="margin-top:12px">Pairs inside · click one</div>
      <div style="margin-top:4px">${inside.slice(0, 30).map(k => `<div class="rec" style="grid-template-columns:1fr auto;cursor:pointer" data-k="${k}"><span class="mono" style="font-size:11.5px">${esc(shortName(W.ra[k]))} ↔ ${esc(shortName(W.rb[k]))}</span><span class="mono num" style="font-size:11.5px">${W.route ? esc(routeShort(W.route[k])) + " · " : ""}${(W.P[k] ?? NaN).toFixed(3)}</span></div>`).join("")}</div>` : ""}`;
  $$("#inspector [data-k]").forEach(r => r.onclick = () => inspectPair(+r.dataset.k));
}
const shortName = i => W.names[i].length > 22 ? W.names[i].slice(0, 21) + "…" : W.names[i];
const routeShort = r => ({ 0: "key", 1: "key ✗", 2: "accept", 3: "reject", 4: "uncertain", 5: "review" })[r];
async function inspectPair(k) {
  highlight([W.ra[k], W.rb[k]]);
  const box = $("#inspector");
  box.innerHTML = `<h4><span class="label ink">Pair inspector</span><span class="tiny">loading…</span></h4>`;
  let d; try { d = await getJSON(`/api/runs/${W.id}/pair/${k}`); } catch (e) { box.innerHTML += `<p class="small signal">${esc(e.message)}</p>`; return; }
  const rec = r => `<div>${srcBadge(r.source)}<span class="raw">${esc(r.name)}</span>
    <div class="kv">${[r.alt_names && r.alt_names.length ? "also: " + r.alt_names.slice(0, 3).join(" · ") : "", r.street, r.postcode, r.brand ? "brand " + r.brand : "", r.stars ? r.stars + "★" : "", r.qid ? "wikidata " + r.qid : "", r.phone ? "phone ✓" : "", r.website ? "web ✓" : ""].filter(Boolean).map(esc).join("<br>") || "no other fields"}</div></div>`;
  const items = d.contrib.slice().filter(c => Math.abs(c.value) > 1e-4).sort((a, b) => Math.abs(b.value) - Math.abs(a.value)).slice(0, 12);
  const mx = Math.max(...items.map(c => Math.abs(c.value)), 0.5);
  const fv = Object.fromEntries(d.features.map(f => [f.name, f.value]));
  const sum = d.bias + d.contrib.reduce((a, c) => a + c.value, 0);
  const route = W.route ? ROUTES[W.route[k]] : d.route;
  box.innerHTML = `<h4><span class="label ink">Pair inspector</span><span class="tiny">pair ${k}</span></h4>
    <div class="pairbox">${rec(d.a)}${rec(d.b)}</div>
    <div class="pscore"><b class="num">${d.p.toFixed(3)}</b><span class="tiny" style="text-align:right">${esc(ROUTE_TXT[route] || route)}<br>${esc(d.model.startsWith("loco") ? "model trained without " + d.model.split(":")[1] : "final model")}${d.y === 1 ? " · key match" : d.y === 0 ? " · key conflict" : ""}</span></div>
    <div class="label ink" style="margin-top:12px">Feature contributions <span class="tiny" style="text-transform:none;letter-spacing:0">· LightGBM pred_contrib, log-odds</span></div>
    <div class="shap">${items.map(c => `<span class="fn" title="${esc(c.name)} = ${fv[c.name] ?? "missing"}">${esc(featName(c.name))}</span><span class="bar"><i class="${c.value < 0 ? "neg" : ""}" style="${c.value >= 0 ? `left:50%;width:${c.value / mx * 50}%` : `right:50%;width:${-c.value / mx * 50}%`}"></i></span><span class="fv">${c.value > 0 ? "+" : ""}${c.value.toFixed(2)}</span>`).join("")}</div>
    <div class="tiny" style="margin-top:8px">start ${d.bias.toFixed(2)} + contributions = ${sum.toFixed(3)} = logit(${d.p.toFixed(3)}) ${Math.abs(sum - d.logit) < 1e-3 ? "✓" : "✗"} · hover a feature name for its value</div>`;
}

// ===================================================================================================== review queue
async function loadQueue() {
  const q = $("#queue");
  let items; try { items = await getJSON(`/api/runs/${W.id}/review?limit=40`); } catch (e) { q.innerHTML = `<p class="small signal">${esc(e.message)}</p>`; return; }
  if (!items.length) { q.innerHTML = `<p class="small">No uncertain pairs in this run.</p>`; return; }
  q.innerHTML = items.map(it => `<div class="qitem" data-k="${it.k}">
    <div class="qn">${mark(it.a.source)}<span>${esc(it.a.name)}</span></div><div class="qn">${mark(it.b.source)}<span>${esc(it.b.name)}</span></div>
    <div class="qm">p ${it.p.toFixed(3)} · ${it.dist === null || it.dist === undefined ? "no distance" : fmt.int(it.dist) + " m"} · <a href="#" data-inspect="${it.k}">inspect</a></div>
    <div class="qa"><button data-d="same">Same</button><button data-d="different">Different</button><button data-d="unsure">Unsure</button></div></div>`).join("") + `<p class="tiny" id="qSaved" style="padding:8px 0"></p>`;
  q.onclick = async e => {
    const ins = e.target.closest("[data-inspect]"); if (ins) { e.preventDefault(); inspectPair(+ins.dataset.inspect); return; }
    const b = e.target.closest("button[data-d]"); if (!b) return;
    const item = b.closest(".qitem");
    try {
      const r = await getJSON("/api/review", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ run_id: W.id, k: +item.dataset.k, decision: b.dataset.d }) });
      item.querySelectorAll("button").forEach(x => x.classList.toggle("on", x === b)); item.classList.add("done");
      $("#qSaved").textContent = `Saved to ${r.saved} · ${r.count} answers in that file`;
    } catch (err) { $("#qSaved").innerHTML = `<span class="signal">${esc(err.message)}</span>`; }
  };
}

// ===================================================================================================== export
export function exportCanonical(kind) {
  if (!W.root || !W.n) return;
  const groups = new Map();
  for (let i = 0; i < W.n; i++) { const r = W.root[i]; if (!groups.has(r)) groups.set(r, []); groups.get(r).push(i); }
  const ents = [...groups.entries()].map(([r, ms], idx) => {
    const wc = ms.filter(j => W.has[j]);
    return { canonical_id: `c${idx + 1}`, name: canonName(ms), lat: wc.length ? +(wc.reduce((a, j) => a + W.lat[j], 0) / wc.length).toFixed(6) : null,
             lon: wc.length ? +(wc.reduce((a, j) => a + W.lon[j], 0) / wc.length).toFixed(6) : null, n: ms.length,
             members: ms.map(j => ({ source: W.sources[W.src[j]], src_id: W.srcId[j], name: W.names[j], lat: W.lat[j] === W.lat[j] ? W.lat[j] : null, lon: W.lon[j] === W.lon[j] ? W.lon[j] : null })) };
  });
  const meta = { run: W.id, input: W.label, accept_threshold: W.t, reject_threshold: W.tRej, entities: ents.length, records: W.n, exported: new Date().toISOString() };
  let blob, name;
  if (kind === "json") { blob = new Blob([JSON.stringify({ meta, entities: ents }, null, 1)], { type: "application/json" }); name = `canon_${W.id}.json`; }
  else {
    const q = v => v === null || v === undefined ? "" : /[",\n]/.test(String(v)) ? `"${String(v).replace(/"/g, '""')}"` : String(v);
    const rows = [["canonical_id", "canonical_name", "canonical_lat", "canonical_lon", "members", "source", "src_id", "name", "lat", "lon"].join(",")];
    for (const e of ents) for (const m of e.members) rows.push([e.canonical_id, e.name, e.lat, e.lon, e.n, m.source, m.src_id, m.name, m.lat, m.lon].map(q).join(","));
    blob = new Blob(["﻿" + rows.join("\n")], { type: "text/csv" }); name = `canon_${W.id}.csv`;
  }
  const a = el("a"); a.href = URL.createObjectURL(blob); a.download = name; document.body.append(a); a.click(); setTimeout(() => { URL.revokeObjectURL(a.href); a.remove(); }, 500);
}

// ===================================================================================================== benches (rule-based, literal)
const BOARD = { BB: "breakfast", RO: "room only", HB: "half board", FB: "full board", AI: "all inclusive" };
function chipText(attr, v) {
  if (attr === "beds") return [].concat(v).join("/") + " bed";
  if (attr === "view") return v === "view" ? "view" : v + " view";
  if (attr === "board") return BOARD[v] || v;
  if (attr === "refundable") return v ? "free cancellation" : "non-refundable";
  if (attr === "promo") return "promotion";
  if (Array.isArray(v)) return v.join(", ").replace(/_/g, " ");
  return String(v).replace(/_/g, " ");
}
function initBenches() {
  // room bench
  const inp = $("#roomIn"); let tmr;
  const run = async () => {
    const out = $("#roomOut");
    try { const d = await getJSON("/api/rooms/parse", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ text: inp.value }) }); out.innerHTML = roomHTML(d); }
    catch (e) { out.innerHTML = `<p class="small signal">${esc(e.message)}</p>`; }
  };
  inp.addEventListener("input", () => { clearTimeout(tmr); tmr = setTimeout(run, 160); });
  run();
  // pair two lists: prefilled with one real hotel's rooms and the simulated supplier's strings from the story
  fetch("data/story.json").then(r => r.json()).then(S => { $("#roomA").value = S.rooms.a.map(a => a.name).join("\n"); $("#roomB").value = S.rooms.b.map(b => b.name).join("\n"); });
  $("#roomMap").onclick = async () => {
    const out = $("#roomMapOut");
    try {
      const A = $("#roomA").value.split("\n"), B = $("#roomB").value.split("\n");
      const d = await getJSON("/api/rooms/map", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ a: A, b: B }) });
      const aClean = A.filter(x => x.trim());
      out.innerHTML = `<div style="margin-top:10px;border-top:1px solid var(--rule-2)">${d.map(r => `<div style="display:grid;grid-template-columns:1fr 18px 1fr;gap:6px;padding:6px 0;border-bottom:1px solid var(--rule);align-items:baseline">
        <span class="raw" style="font-size:12px">${esc(r.text)}</span><span class="mono" style="color:${r.match !== null ? "var(--fg)" : "var(--signal-text)"}">${r.match !== null ? "→" : "✗"}</span>
        <span>${r.match !== null ? `<span class="canon-name" style="font-size:13px">${esc(aClean[r.match])}</span>` : `<span class="tiny signal">${esc(r.why)}</span>`}
        <span class="tiny" style="display:block">${r.parsed.tokens.filter(t => t.side === "rate").map(t => esc(chipText(t.attr, t.value))).filter((v, i, a) => a.indexOf(v) === i).join(" · ") || ""}</span></span></div>`).join("")}</div>
        <p class="tiny" style="margin-top:6px">${d.filter(r => r.match !== null).length} of ${d.length} mapped by a unique room signature; rate terms (orange) never enter the signature.</p>`;
    } catch (e) { out.innerHTML = `<p class="small signal">${esc(e.message)}</p>`; }
  };
  // tour bench
  const cities = ["singapore", "dubai", "bangkok", "delhi", "mumbai", "goa", "london", "paris", "amsterdam", "barcelona", "vienna", "milan"];
  $("#tourCity").innerHTML = cities.map(c => `<option value="${c}">${c[0].toUpperCase() + c.slice(1)}</option>`).join("");
  const go = async () => {
    const out = $("#tourOut"); out.innerHTML = `<p class="tiny">relating…</p>`;
    try {
      const d = await getJSON("/api/tours/relate", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ a: $("#tourA").value, b: $("#tourB").value, city: $("#tourCity").value }) });
      out.innerHTML = tourHTML(d);
    } catch (e) { out.innerHTML = `<p class="small signal">${esc(e.message)}</p>`; }
  };
  $("#tourGo").onclick = go; go();
}
function roomHTML(d) {
  const toks = d.tokens.map(t => `<span class="tok ${t.side}" title="${esc(t.rule || "")}">${esc(t.raw ?? t.norm.join(" "))}</span>`).join("");
  const seen = new Set(), chips = side => d.tokens.filter(t => t.side === side).filter(t => { const k = side + t.attr + JSON.stringify(t.value); if (seen.has(k)) return false; seen.add(k); return true; })
    .map(t => `<span class="chip ${side === "rate" ? "rate" : side === "room" ? "room" : "left"}" title="${esc(t.rule)}"><small>${esc((t.attr || "").replace(/_/g, " "))}</small>${esc(side === "left" ? t.raw : chipText(t.attr, t.value))}</span>`).join("");
  return `<div class="tokline">${toks}</div>
    <div class="lanes"><div class="lane"><span class="label ink">Room</span><div class="chips">${chips("room") || '<span class="tiny">nothing found</span>'}</div></div>
      <div class="lane rate"><span class="label ink">Rate</span><div class="chips">${chips("rate") || '<span class="tiny">no rate terms</span>'}</div></div></div>
    ${d.tokens.some(t => t.side === "left") ? `<div style="margin-top:8px"><span class="label">Left over · kept as identity</span><div class="chips" style="display:flex;gap:5px;margin-top:5px">${chips("left")}</div></div>` : ""}
    <div class="rules">${d.fired.map(f => `<div><b>${esc(f.group)}</b> ${esc(String(chipText(f.attr, f.value)))} ← "${esc(f.matched)}"${f.raw_start != null ? ` <span>(raw ${f.raw_start}–${f.raw_end})</span>` : ""}</div>`).join("")}
      <div style="margin-top:4px">normalised: <span class="raw">${esc(d.normalised)}</span> · confidence ${d.confidence.toFixed(2)}${d.confidence < 0.5 ? ' · <span class="signal">low: goes to the model stage</span>' : ""}</div></div>`;
}
function tourHTML(d) {
  const side = (x, L) => `<div style="border-top:1px solid var(--rule-2);padding-top:6px"><span class="label ink">${L}</span>
    <div class="tiny" style="margin-top:4px">${[x.attractions.length ? "attractions: " + x.attractions.join(", ") : "no known attraction", "experience: " + x.experience, "access: " + x.access,
      x.inclusions.length ? "+ " + x.inclusions.join(", ") : "", x.age_band ? "age: " + x.age_band : "", x.group ? "group: " + x.group : "", x.promo_tags.length ? "promo: " + x.promo_tags.join(", ") : "",
      x.core_tokens.length ? "other words: " + x.core_tokens.join(" ") : ""].filter(Boolean).map(esc).join("<br>")}</div>
    <div class="rules">${x.fired.map(f => `<div><b>${esc(f.attr)}</b> ${esc(String(f.value))} ← "${esc(f.matched)}"</div>`).join("")}</div></div>`;
  return `<div style="margin-top:12px;display:flex;align-items:center;gap:12px;flex-wrap:wrap"><span class="relbadge">${relSample(d.relation, 54)}${esc((REL[d.relation] || {}).label || d.relation).toUpperCase()}</span>
    ${d.diff.map(x => `<span class="chip">${esc(x.replace(/_/g, " ").replace("->", "→"))}</span>`).join("")}</div>
    <p class="tiny" style="margin:6px 0 10px">${esc(d.reason)} · gazetteer: ${esc(d.gazetteer.city)}, ${fmt.int(d.gazetteer.names)} names</p>
    <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px">${side(d.a, "A")}${side(d.b, "B")}</div>`;
}
