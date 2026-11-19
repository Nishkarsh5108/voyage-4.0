// Shared helpers: DOM, formatting, numbers.json binding, source marks, relation lines, the reveal ("raw underneath") interaction.

export const $ = (s, r = document) => r.querySelector(s);
export const $$ = (s, r = document) => [...r.querySelectorAll(s)];
export const el = (tag, cls, html) => { const e = document.createElement(tag); if (cls) e.className = cls; if (html !== undefined) e.innerHTML = html; return e; };
export const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
export const clamp = (x, a = 0, b = 1) => Math.min(b, Math.max(a, x));
export const lerp = (a, b, t) => a + (b - a) * t;
export const ease = t => 1 - Math.pow(1 - clamp(t), 3);              // damped, no overshoot
export const easeIO = t => { t = clamp(t); return t < .5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2; };
const mq = matchMedia("(prefers-reduced-motion: reduce)");
export const reduced = () => mq.matches;
export const sleep = ms => new Promise(r => setTimeout(r, ms));

export async function getJSON(url, opts) {
  const r = await fetch(url, opts);
  let body = null;
  try { body = await r.json(); } catch { /* not json */ }
  if (!r.ok) { const e = new Error((body && body.error) || `${r.status} ${r.statusText}`); e.body = body; e.status = r.status; throw e; }
  return body;
}

// ---------------------------------------------------------------- numbers.json: the only source of quoted figures
export function get(obj, path) { return path.split(".").reduce((o, k) => (o == null ? undefined : o[k]), obj); }
const nf = new Intl.NumberFormat("en-US");
export const fmt = {
  int: v => nf.format(Math.round(v)),
  pct0: v => Math.round(v * 100) + "%",
  pct1: v => (v * 100).toFixed(1) + "%",
  dec1: v => Number(v).toFixed(1),
  dec2: v => Number(v).toFixed(2),
  dec3: v => Number(v).toFixed(3),
  millions: v => (v / 1e6).toFixed(2).replace(/\.?0+$/, "") + " million",
  millionsShort: v => (v / 1e6).toFixed(2) + "M",
  billions: v => (v / 1e9).toFixed(1) + " billion",
};
export function auto(v) { return Number.isInteger(v) ? fmt.int(v) : fmt.dec2(v); }
export function bindNumbers(N, root = document) {
  for (const node of $$("[data-n]", root)) {
    const v = get(N, node.dataset.n);
    if (v === undefined || v === null) { node.textContent = "?"; node.title = "missing in numbers.json: " + node.dataset.n; node.classList.add("signal"); console.warn("numbers.json has no", node.dataset.n); continue; }
    const f = node.dataset.f;
    node.textContent = typeof v === "number" ? (f ? fmt[f](v) : auto(v)) : String(v);
    node.title = node.title || `numbers.json · ${node.dataset.n}`;
  }
}
// derived values are computed from numbers.json at runtime, never typed
export function derive(N) {
  const n = N.matching.records;
  N.calc = { all_pairs: fmt.billions(n * (n - 1) / 2) };
  return N;
}

// ---------------------------------------------------------------- source marks: four sources, four shapes
export const SOURCES = {
  overture: { label: "Overture", shape: "circle" },
  osm: { label: "OpenStreetMap", shape: "square" },
  wikidata: { label: "Wikidata", shape: "triangle" },
  wikivoyage: { label: "Wikivoyage", shape: "diamond" },
  makemytrip: { label: "MakeMyTrip", shape: "circle" },
  goibibo: { label: "Goibibo", shape: "square" },
};
export const SHAPES = ["circle", "square", "triangle", "diamond", "ring", "box", "plus", "cross"];
export const SHAPE_ID = Object.fromEntries(SHAPES.map((s, i) => [s, i]));
export function shapeOf(src, i = 0) { return (SOURCES[src] || {}).shape || SHAPES[i % SHAPES.length]; }
export function labelOf(src) { return (SOURCES[src] || {}).label || src; }
export function markSVG(shape, color = "currentColor") {
  const f = `fill="${color}"`, s = `fill="none" stroke="${color}" stroke-width="1.6"`;
  const body = {
    circle: `<circle cx="5" cy="5" r="4.4" ${f}/>`,
    square: `<rect x="1" y="1" width="8" height="8" ${f}/>`,
    triangle: `<path d="M5 .4 9.6 9.2H.4z" ${f}/>`,
    diamond: `<path d="M5 0 10 5 5 10 0 5z" ${f}/>`,
    ring: `<circle cx="5" cy="5" r="3.7" ${s}/>`,
    box: `<rect x="1.6" y="1.6" width="6.8" height="6.8" ${s}/>`,
    plus: `<path d="M5 .5v9M.5 5h9" ${s}/>`,
    cross: `<path d="M1.5 1.5l7 7M8.5 1.5l-7 7" ${s}/>`,
  }[shape] || "";
  return `<svg viewBox="0 0 10 10" aria-hidden="true">${body}</svg>`;
}
export const mark = (src, i) => `<span class="mk" title="${esc(labelOf(src))}">${markSVG(shapeOf(src, i))}</span>`;
export const srcBadge = (src, i, extra = "") => `<span class="src">${mark(src, i)}${esc(labelOf(src))}${extra}</span>`;
export function drawMark(ctx, shape, x, y, r) {
  ctx.beginPath();
  if (shape === "circle" || shape === "ring") ctx.arc(x, y, r, 0, Math.PI * 2);
  else if (shape === "square" || shape === "box") ctx.rect(x - r * .88, y - r * .88, r * 1.76, r * 1.76);
  else if (shape === "triangle") { ctx.moveTo(x, y - r * 1.05); ctx.lineTo(x + r * 1.02, y + r * .82); ctx.lineTo(x - r * 1.02, y + r * .82); ctx.closePath(); }
  else if (shape === "diamond") { ctx.moveTo(x, y - r * 1.15); ctx.lineTo(x + r * 1.15, y); ctx.lineTo(x, y + r * 1.15); ctx.lineTo(x - r * 1.15, y); ctx.closePath(); }
  else if (shape === "plus") { ctx.moveTo(x - r, y); ctx.lineTo(x + r, y); ctx.moveTo(x, y - r); ctx.lineTo(x, y + r); }
  else if (shape === "cross") { ctx.moveTo(x - r * .8, y - r * .8); ctx.lineTo(x + r * .8, y + r * .8); ctx.moveTo(x + r * .8, y - r * .8); ctx.lineTo(x - r * .8, y + r * .8); }
  if (shape === "ring" || shape === "box" || shape === "plus" || shape === "cross") ctx.stroke(); else ctx.fill();
}

// ---------------------------------------------------------------- typed relations: four line styles
export const REL = {
  SAME_AS: { label: "Same as", dash: "", arrow: false },
  VARIANT_OF: { label: "Variant of", dash: "7 4", arrow: false },
  INCLUDES: { label: "Includes", dash: "", arrow: true },
  INCLUDED_IN: { label: "Included in", dash: "", arrow: true },
  DIFFERENT: { label: "Different", dash: "1.5 4", arrow: false },
};
export function relSample(rel, w = 54) {
  const r = REL[rel] || REL.DIFFERENT;
  const cap = rel === "DIFFERENT" ? ' stroke-linecap="round"' : "";
  const arrow = r.arrow ? `<path d="M${w - 7} 1 ${w} 5 ${w - 7} 9" fill="none" stroke="currentColor" stroke-width="1.5"/>` : "";
  return `<svg viewBox="0 0 ${w} 10" width="${w}" height="10" aria-hidden="true"><line x1="1" y1="5" x2="${w - (r.arrow ? 1 : 1)}" y2="5" stroke="currentColor" stroke-width="${rel === "DIFFERENT" ? 2 : 1.5}" stroke-dasharray="${r.dash}"${cap}/>${arrow}</svg>`;
}

// ---------------------------------------------------------------- reveal: any canonical thing opens to show its raw records
const rv = () => document.getElementById("reveal");
export function showReveal(html, x, y, dark = false) {
  const r = rv(); r.innerHTML = html; r.classList.toggle("dark", dark); r.classList.add("on");
  const w = r.offsetWidth, h = r.offsetHeight;
  let left = x + 18, top = y + 18;
  if (left + w > innerWidth - 8) left = x - w - 18;
  if (top + h > innerHeight - 8) top = y - h - 18;
  r.style.left = Math.max(8, left) + "px"; r.style.top = Math.max(8, top) + "px";
}
export function hideReveal() { rv().classList.remove("on"); }
export function revealHTML(title, rows, foot) {
  return `<div class="rv-h">${esc(title)}</div>${rows.map(r => `<div class="rv-row">${mark(r.src, r.i)}<span>${esc(r.name)}</span></div>`).join("")}${foot ? `<div class="rv-foot">${esc(foot)}</div>` : ""}`;
}
// Delegated: elements with data-reveal="<key>" look the key up in a registry of {title, rows, foot}
export const revealRegistry = new Map();
export function initReveal() {
  let holdTimer = null;
  const show = (t, x, y) => { const item = revealRegistry.get(t.dataset.reveal); if (item) showReveal(revealHTML(item.title, item.rows, item.foot), x, y, !!t.closest(".ink-ground")); };
  document.addEventListener("pointerover", e => { const t = e.target.closest("[data-reveal]"); if (t && e.pointerType === "mouse") show(t, e.clientX, e.clientY); });
  document.addEventListener("pointermove", e => { const t = e.target.closest("[data-reveal]"); if (t && e.pointerType === "mouse") show(t, e.clientX, e.clientY); });
  document.addEventListener("pointerout", e => { if (e.target.closest("[data-reveal]")) hideReveal(); });
  document.addEventListener("pointerdown", e => { const t = e.target.closest("[data-reveal]"); if (t && e.pointerType !== "mouse") { holdTimer = setTimeout(() => show(t, e.clientX, e.clientY), 260); } });
  document.addEventListener("pointerup", () => { clearTimeout(holdTimer); setTimeout(hideReveal, 1600); });
  document.addEventListener("focusin", e => { const t = e.target.closest("[data-reveal]"); if (t) { const b = t.getBoundingClientRect(); show(t, b.right, b.top); } });
  document.addEventListener("focusout", hideReveal);
}

// ---------------------------------------------------------------- truth tags
export const TAGS = {
  keys: "Independent keys", comp: "Competition labels", sim: "Simulated supplier", insample: "In-sample",
  nolabel: "Not labelled yet", notmeasured: "Not measured", count: "Pipeline output", notbuilt: "Designed, not built",
};
export const tag = (k, text) => `<span class="tag ${k}"><i></i>${esc(text || TAGS[k])}</span>`;

// ---------------------------------------------------------------- local projection for city-scale maps
export function projector(lat0) {
  const k = Math.cos(lat0 * Math.PI / 180);
  return { x: lon => lon * k, y: lat => lat, lon: x => x / k, lat: y => y, k };
}

// in-view callbacks
export function onVisible(node, cb, opts = { threshold: 0.01 }) {
  const io = new IntersectionObserver(es => es.forEach(e => cb(e.isIntersecting, e)), opts);
  io.observe(node); return io;
}
