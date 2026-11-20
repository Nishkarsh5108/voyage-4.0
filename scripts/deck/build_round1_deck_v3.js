/* Round 1 deck, v3 design: cover + two content slides + thank-you (the rules allow two content slides).
 *
 * Content discipline as in build_round1_deck.js: every number is read from submission/round1/numbers.json, and every example
 * detail (pin distances, name similarity, the room string, the tour relations) from demo/data.js, so nothing is typed by hand.
 * Look: paper-white, near-black ink, one signal orange. Franklin Gothic (ships with Office on Windows and Mac) for headings and
 * canonical values, Consolas for raw supplier strings, Arial for the Arabic name. Status is shown by form, never by colour:
 * solid = measured on real data, hatched = tested with a simulated second supplier, outline = designed, not yet measured.
 * Hatching is drawn as three diagonal strokes per mark, so PowerPoint, Keynote, Google Slides and the PDF all show it the same way.
 *
 * Usage:  cd scripts/deck && node build_round1_deck_v3.js
 *         $env:CANON_TEAM = "Team X: A, B, C"; $env:CANON_LINK = "github.com/..."; node build_round1_deck_v3.js
 * Output: submission/round1/Canon_Round1_v3.pptx    Render: powershell -ExecutionPolicy Bypass -File render.ps1 -Deck Canon_Round1_v3.pptx -Out qa_v3
 */
const path = require("path");
const fs = require("fs");
const pptxgen = require("pptxgenjs");
const JSZip = require("jszip");

const ROOT = path.resolve(__dirname, "..", "..");
const R1 = path.join(ROOT, "submission", "round1");
const OUT = path.join(R1, process.env.CANON_OUT || "Canon_Round1_v3.pptx");
const N = JSON.parse(fs.readFileSync(path.join(R1, "numbers.json"), "utf8"));
const demoSrc = fs.readFileSync(path.join(ROOT, "demo", "data.js"), "utf8");
const D = JSON.parse(demoSrc.slice(demoSrc.indexOf("=") + 1).trim().replace(/;\s*$/, ""));
const TEAM = process.env.CANON_TEAM || "[ Team name  ·  Members ]";
const LINK = process.env.CANON_LINK || "[ Repository link ]";

/* ------------------------------------------------------------------ data */
const pct = (x, d = 0) => (x * 100).toFixed(d) + "%";
const p0 = x => Math.round(x * 100);
const num = x => Number(x).toLocaleString("en-US");
const must = (cond, msg) => { if (!cond) throw new Error("data check failed: " + msg); };

const M = N.matching, FAIR = M.fair_comparison, ALL = FAIR["all 12 cities"];
const CASC = M.cascade_shares;
const shareRules = CASC["Key rules"], shareModel = CASC["Cheap model, confident"], shareOn = CASC["Uncertain: cross-encoder, LLM, human"];
const cheap = shareRules + shareModel;
const F2 = N.fsq_v2, TH = N.sightseeing_heldout;
must(F2 && TH, "numbers.json lacks the 20 Nov keys (fsq_v2, sightseeing_heldout)");
const LLM_SIZE = (/(\d+(\.\d+)?B)\b/.exec(TH.llm) || [])[1]; // "Qwen/Qwen2.5-7B-Instruct" -> "7B"
must(LLM_SIZE, "LLM size in the model name");
must(Math.abs(shareRules + shareModel + shareOn - 1) < 1e-9, "cascade shares sum to 1");

// Example 1: Atlantis, The Palm in four sources (demo/data.js, real Dubai clusters)
const atl = D.matching.clusters.find(c => /^Atlantis, the Palm$/i.test(c.name));
must(atl && atl.members.length === 4, "Atlantis cluster with four members");
const SRCNAME = { overture: "Overture", wikidata: "Wikidata", wikivoyage: "Wikivoyage", osm: "OpenStreetMap" };
const atlMembers = ["overture", "wikidata", "wikivoyage", "osm"].map(s => atl.members.find(m => m.src === s));
const isArabic = s => /[\u0600-\u06FF]/.test(s);
const arab = atl.members.find(m => isArabic(m.name));
must(arab, "an Arabic member");
const atlMaxPin = Math.max(...atl.edges.map(e => e.d));
const arabEdges = atl.edges.filter(e => e.a === arab.rid || e.b === arab.rid);
const arabJw = Math.max(...arabEdges.map(e => e.jw));
must(arabEdges.some(e => e.key === "qid"), "Arabic member linked by a shared Wikidata ID");
must(atl.edges.some(e => !e.key && e.p >= D.matching.threshold), "a model-accepted edge in the Atlantis cluster");

// Example 2: TWN PARTIAL SV HB NRF (Hilton Diagonal Mar: real room list, second supplier simulated)
const ROOMSTR = "TWN PARTIAL SV HB NRF";
const hil = D.rooms.find(r => r.b.some(x => x.name === ROOMSTR));
must(hil, "room example");
const rb = hil.b.find(x => x.name === ROOMSTR), ra = hil.a[rb.true];
must(rb.mapped === rb.true, "the example room is mapped correctly");
const BOARD = { RO: "room only", BB: "breakfast", HB: "half board", FB: "full board", AI: "all inclusive" };
const rateTok = new Set([rb.parsed.board, rb.parsed.refundable === false ? "NRF" : null].filter(Boolean));
const roomToks = ROOMSTR.split(" ").filter(t => !rateTok.has(t)), rateToks = ROOMSTR.split(" ").filter(t => rateTok.has(t));
const cap1 = s => s.charAt(0).toUpperCase() + s.slice(1);
const roomCanon = cap1(`${rb.parsed.beds.join(" + ")} room, ${rb.parsed.view} view`);
const rateCanon = cap1([BOARD[rb.parsed.board], rb.parsed.refundable === false ? "non-refundable" : null].filter(Boolean).join(", "));

// Example 3: Universal Studios Singapore family (real Klook products; relations from canon/activities.py)
const uss = D.activities.find(a => a.family === "Universal Studios Singapore");
must(uss, "tour family");
const rel = (a, b) => uss.relations.find(r => r.a === a && r.b === b);
const rAB = rel(0, 1), rAC = rel(0, 2), rAD = rel(0, 3);
must(rAB.relation === "VARIANT_OF" && rAC.relation === "INCLUDED_IN" && rAD.relation === "DIFFERENT", "tour relations as drawn");
const tidy = s => s.replace(/->/g, "→").replace(/_/g, "-");
const diffAB = tidy(rAB.diff[0]), diffAC = tidy(rAC.diff[0]);

/* ------------------------------------------------------------------ look */
const C = { paper: "FBFAF7", ink: "15140F", ink2: "4F4B43", ink3: "8A857C", hair: "D9D4C9", hair2: "B5AFA2", signal: "FF4F00", signalText: "C03A00" };
const F = { head: "Franklin Gothic Medium", body: "Franklin Gothic Book", mono: "Consolas", arabic: "Arial" };
const MONO_W = pt => pt * 0.5498 / 72;           // Consolas advance per character, inches
const ARAB_W = (s, pt) => s.length * pt * 0.0047;  // Arial Arabic, measured on the renders
// rough line count for wrapped Franklin Gothic text (greedy word wrap); em = average advance in ems, calibrated on renders
function nlines(text, w, pt, em = 0.44) {
  const max = w / (pt * em / 72); let lines = 1, cur = 0;
  for (const word of String(text).split(/\s+/).filter(Boolean)) {
    const L = word.length + (cur ? 1 : 0);
    if (cur + L > max && cur > 0) { lines++; cur = word.length; } else cur += L;
  }
  return lines;
}
const LH = pt => pt * 1.14 / 72; // line height, inches

const pres = new pptxgen();
pres.layout = "LAYOUT_WIDE"; // 13.333 x 7.5 in
pres.theme = { headFontFace: F.head, bodyFontFace: F.body };
pres.title = "Canon: one product graph across suppliers";
pres.author = "VoyageHack 4.0 team";
pres.subject = "VoyageHack 4.0, Multi-Supplier Optimization, Round 1";
const S = pres.shapes;

pres.defineSlideMaster({
  title: "CANON_COVER", background: { color: C.paper },
  objects: [{ placeholder: { options: { name: "title", type: "title", x: 0.6, y: 1.5, w: 6.2, h: 1.3, fontFace: F.head, fontSize: 80, color: C.ink, align: "left", valign: "top", margin: 0 }, text: "" } }],
});
pres.defineSlideMaster({
  title: "CANON_CONTENT", background: { color: C.paper },
  objects: [
    { placeholder: { options: { name: "title", type: "title", x: 0.5, y: 0.28, w: 12.33, h: 0.5, fontFace: F.head, fontSize: 26, color: C.ink, align: "left", valign: "top", margin: 0 }, text: "" } },
    { placeholder: { options: { name: "body", type: "body", x: 0.5, y: 0.8, w: 12.33, h: 0.26, fontFace: F.body, fontSize: 12.5, color: C.ink2, align: "left", valign: "top", margin: 0 }, text: "" } },
  ],
});
pres.defineSlideMaster({
  title: "CANON_CLOSE", background: { color: C.paper },
  objects: [{ placeholder: { options: { name: "title", type: "title", x: 0.6, y: 0.7, w: 7, h: 0.9, fontFace: F.head, fontSize: 44, color: C.ink, align: "left", valign: "top", margin: 0 }, text: "" } }],
});

/* ------------------------------------------------------------------ drawing helpers */
const T = (s, text, o) => s.addText(text, { isTextBox: true, margin: 0, fontFace: F.body, fontSize: 11, color: C.ink, valign: "top", ...o });
const run = (text, o = {}) => ({ text, options: o });
const capLabel = (s, text, x, y, w, o = {}) => T(s, text.toUpperCase(), { x, y, w, h: 0.2, fontFace: F.head, fontSize: 10, color: C.ink2, charSpacing: 0.8, valign: "middle", ...o });
const hline = (s, x1, x2, y, o = {}, name) => s.addShape(S.LINE, { x: x1, y, w: x2 - x1, h: 0, line: { color: C.ink, width: 0.75, ...o }, objectName: name });
// a straight segment from (x1, y1) to (x2, y2); the flips keep start and end in place, so an arrowhead lands on (x2, y2)
function seg(s, x1, y1, x2, y2, ln, name) {
  s.addShape(S.LINE, { x: Math.min(x1, x2), y: Math.min(y1, y2), w: Math.abs(x2 - x1), h: Math.abs(y2 - y1), flipH: x2 < x1, flipV: y2 < y1, line: ln, objectName: name });
}
// four relation line styles, one per relation; fresh objects on every call (pptxgenjs mutates option objects)
const REL = {
  same: () => ({ color: C.ink, width: 2.25 }),
  variant: () => ({ color: C.ink, width: 1.5, dashType: "dash" }),
  includes: () => ({ color: C.ink, width: 1.25, endArrowType: "triangle" }),
  different: () => ({ color: C.ink2, width: 1.5, dashType: "sysDot" }),
};
const RATE_LINE = () => ({ color: C.signal, width: 2.25 });
// same-as link from the end of a raw string: level to a common elbow, then straight to the canonical node
function link(s, x1, y1, xe, xn, yn, name) {
  if (xe - x1 > 0.05) seg(s, x1, y1, xe, y1, REL.same(), name + " (level)");
  seg(s, Math.max(x1, xe), y1, xn, yn, REL.same(), name);
}
// status glyph: the one legend, used everywhere
function glyph(s, x, y, status, sz = 0.15, name) {
  const fill = status === "measured" ? C.ink : C.paper;
  s.addShape(S.RECTANGLE, { x, y, w: sz, h: sz, fill: { color: fill }, line: { color: C.ink, width: 0.75 }, objectName: name || `Status: ${status}` });
  if (status === "simulated") { // hatching as three drawn strokes: not every viewer draws pattern fills
    const k = sz / 2;
    seg(s, x, y + k, x + k, y, { color: C.ink, width: 0.75 }, "Hatch");
    seg(s, x, y + sz, x + sz, y, { color: C.ink, width: 0.75 }, "Hatch");
    seg(s, x + k, y + sz, x + sz, y + k, { color: C.ink, width: 0.75 }, "Hatch");
  }
}
const dot = (s, cx, cy, r = 0.055, color = C.ink, hollow = false, name) =>
  s.addShape(S.OVAL, { x: cx - r, y: cy - r, w: 2 * r, h: 2 * r, fill: { color: hollow ? C.paper : color }, line: { color, width: hollow ? 1.25 : 0.5 }, objectName: name });
// numbered marker: ties a "what is new" mechanism to the places it appears
const marker = (s, n, x, y) => s.addText(String(n), { isTextBox: true, shape: S.OVAL, x, y, w: 0.22, h: 0.22, fill: { color: C.ink }, line: { color: C.ink, width: 0.5 },
  fontFace: F.head, fontSize: 10, color: C.paper, align: "center", valign: "middle", margin: 0, objectName: `New ${n} marker` });

function legend(s, x, y, parts) {
  let cx = x;
  const lab = (text, w, o = {}) => { T(s, text, { x: cx, y: y - 0.1, w, h: 0.2, fontSize: 10, color: C.ink2, valign: "middle", ...o }); cx += w; };
  for (const p of parts) {
    if (p.head) { lab(p.head, p.w, { fontFace: F.head, color: C.ink }); continue; }
    if (p.line) { seg(s, cx, y, cx + 0.34, y, REL[p.line](), `Legend ${p.line}`); cx += 0.42; lab(p.text, p.w); continue; }
    if (p.status) { glyph(s, cx, y - 0.075, p.status, 0.15, `Legend ${p.status}`); cx += 0.22; lab(p.text, p.w); continue; }
    if (p.runs) { T(s, p.runs, { x: cx, y: y - 0.1, w: p.w, h: 0.2, fontSize: 10, color: C.ink2, valign: "middle" }); cx += p.w; }
  }
}
const STATUS_LEGEND = [
  { status: "measured", text: "measured on real data", w: 1.52 },
  { status: "simulated", text: "simulated second supplier", w: 1.8 },
  { status: "designed", text: "designed, not yet measured", w: 1.72 },
];

/* ================================================================== cover */
pres.addSection({ title: "Cover" });
{
  const s = pres.addSlide({ masterName: "CANON_COVER", sectionTitle: "Cover" });
  T(s, "VoyageHack 4.0  ·  Multi-Supplier Optimization  ·  Round 1 idea submission", { x: 0.6, y: 0.55, w: 8, h: 0.25, fontSize: 12, color: C.ink2 });
  s.addText("Canon", { placeholder: "title" });
  T(s, "One product graph across suppliers: duplicates found, differences kept.", { x: 0.6, y: 2.95, w: 5.9, h: 0.95, fontSize: 24, color: C.ink });
  T(s, TEAM, { x: 0.6, y: 5.5, w: 6.3, h: 0.3, fontSize: 14, fontFace: F.head, color: C.ink, objectName: "Team line" });
  T(s, `Runs today on ${num(N.data.listings_total)} real listings from ${N.data.sources} independent sources in ${N.data.cities} cities.`,
    { x: 0.6, y: 5.92, w: 6.4, h: 0.25, fontSize: 12, color: C.ink2 });

  // motif: four raw supplier strings resolve to one canonical hotel (the real Dubai cluster)
  const x0 = 7.25, rawX = x0 + 1.2, nodeX = 10.85, R = 12.83;
  capLabel(s, "Four sources send", x0, 2.0, 3);
  capLabel(s, "Canon keeps", nodeX + 0.15, 2.0, 1.8);
  hline(s, x0, R, 2.25);
  const ys = atlMembers.map((m, i) => 2.6 + i * 0.36), ny = ys.reduce((a, b) => a + b) / ys.length;
  const wOf = m => isArabic(m.name) ? ARAB_W(m.name, 15) : m.name.length * MONO_W(13);
  const elbow = rawX + Math.max(...atlMembers.map(wOf)) + 0.15;
  atlMembers.forEach((m, i) => {
    const ar = isArabic(m.name), fz = ar ? 15 : 13, w = wOf(m);
    T(s, SRCNAME[m.src], { x: x0, y: ys[i] - 0.12, w: 1.15, h: 0.24, fontSize: 11, color: C.ink2, valign: "middle" });
    T(s, m.name, { x: rawX, y: ys[i] - 0.14, w: w + 0.2, h: 0.28, fontFace: ar ? F.arabic : F.mono, fontSize: fz, valign: "middle" });
    link(s, rawX + w + 0.12, ys[i], elbow, nodeX, ny, `Same-as line ${i + 1}`);
  });
  dot(s, nodeX, ny, 0.07);
  T(s, "Atlantis, The Palm", { x: nodeX + 0.15, y: ny - 0.32, w: R - nodeX - 0.15, h: 0.64, fontFace: F.head, fontSize: 16, valign: "middle" });
  hline(s, x0, R, 4.15, { color: C.hair });
  T(s, `Real Dubai listings: four sources, two scripts, pins within ${atlMaxPin} m. One hotel.`, { x: x0, y: 4.25, w: R - x0, h: 0.25, fontSize: 11, color: C.ink2 });
  s.addNotes(
    "Canon turns many supplier feeds into one product graph: hotels with room types and rate plans, attractions with products and options. " +
    "The picture on the right is real data from our validation demo: Overture, Wikidata, Wikivoyage and OpenStreetMap each list Atlantis, The Palm in Dubai, " +
    "and OpenStreetMap names it in Arabic. Canon resolves the four listings to one hotel and keeps the evidence for each link. " +
    "In the video this is the opening frame, before tab 1 (0:00). Before submitting, replace the team line (or rebuild with CANON_TEAM)."
  );
}

/* ================================================================== slide 2: the solution */
pres.addSection({ title: "Solution" });
{
  const s = pres.addSlide({ masterName: "CANON_CONTENT", sectionTitle: "Solution" });
  s.addText("It is not deduplication. It is a product graph.", { placeholder: "title" });
  s.addText("Suppliers describe the same hotels, rooms and tours differently, and the statement asks for duplicates to be found “without losing meaningful differences”.", { placeholder: "body" });

  const EX = 0.5, EXR = 8.72, SRCW = 1.07, RAWX = EX + SRCW, NODEX = 4.72, CANX = 4.88, SX = 9.12, SXR = 12.83, TOP = 1.18;
  capLabel(s, "What suppliers send", EX, TOP, 3.2);
  capLabel(s, "What Canon keeps", CANX, TOP, 3.2);
  hline(s, EX, EXR, TOP + 0.24);
  capLabel(s, "The pipeline, in order", SX, TOP, 3.6);
  hline(s, SX, SXR, TOP + 0.24);

  const rawText = (txt, x, cy, fz = 10.5) => {
    const ar = isArabic(txt), w = ar ? ARAB_W(txt, 12) : txt.length * MONO_W(fz);
    T(s, txt, { x, y: cy - 0.11, w: w + 0.15, h: 0.22, fontFace: ar ? F.arabic : F.mono, fontSize: ar ? 12 : fz, valign: "middle" });
    return x + w; // right edge of the string
  };
  const srcText = (txt, cy, h = 0.2) => T(s, txt, { x: EX, y: cy - h / 2, w: SRCW - 0.06, h, fontSize: 10, color: C.ink2, valign: "middle" });
  const level = (status, text, y) => { glyph(s, CANX, y + 0.025, status, 0.15, `Row status: ${status}`); capLabel(s, text, CANX + 0.24, y, EXR - CANX - 0.24); };

  /* row 1: hotel */
  let y = TOP + 0.34;
  level("measured", "Hotel", y);
  const cys = atlMembers.map((m, i) => y + 0.14 + i * 0.235), ny = cys.reduce((a, b) => a + b) / cys.length;
  const ends = atlMembers.map((m, i) => { srcText(SRCNAME[m.src], cys[i]); return rawText(m.name, RAWX, cys[i]); });
  const elbow1 = Math.max(...ends) + 0.12;
  ends.forEach((xe, i) => link(s, xe + 0.1, cys[i], elbow1, NODEX, ny, `Hotel same-as ${i + 1}`));
  dot(s, NODEX, ny, 0.06, C.ink, false, "Hotel node");
  T(s, "Atlantis, The Palm", { x: CANX, y: ny - 0.16, w: 3.6, h: 0.3, fontFace: F.head, fontSize: 15, valign: "middle" });
  const note1 = `Two scripts, pins within ${atlMaxPin} m. A shared Wikidata ID and the pair model link them, though name similarity is only ${arabJw.toFixed(2)}.`;
  const n1h = nlines(note1, EXR - CANX, 10.5) * LH(10.5);
  T(s, note1, { x: CANX, y: ny + 0.15, w: EXR - CANX, h: n1h + 0.04, fontSize: 10.5, color: C.ink2 });
  y = Math.max(cys[3] + 0.2, ny + 0.15 + n1h + 0.05);
  hline(s, EX, EXR, y, { color: C.hair });

  /* row 2: room type and rate plan */
  y += 0.08;
  level("simulated", "Hotel → room type → rate plan", y);
  const hy = y + 0.33, ry = y + 0.59, py = y + 0.9;
  T(s, hil.hotel, { x: CANX, y: hy - 0.11, w: 3.6, h: 0.22, fontSize: 11, color: C.ink2, valign: "middle" });
  seg(s, NODEX, hy, NODEX, py, { color: C.ink3, width: 0.75 }, "Hierarchy: hotel, room type, rate plan");
  dot(s, NODEX, hy, 0.045, C.ink2, false, "Hotel node");
  srcText("Real room list", ry);
  const xa = rawText(ra.name, RAWX, ry);
  seg(s, xa + 0.1, ry, NODEX, ry, REL.same(), "Room same-as (real list)");
  srcText("Simulated supplier", py, 0.36);
  T(s, [run(roomToks.join(" ") + " ", { color: C.ink }), run(rateToks.join(" "), { color: C.signalText })],
    { x: RAWX, y: py - 0.11, w: ROOMSTR.length * MONO_W(10.5) + 0.15, h: 0.22, fontFace: F.mono, fontSize: 10.5, valign: "middle" });
  const xb = RAWX + ROOMSTR.length * MONO_W(10.5);
  seg(s, xb + 0.1, py, NODEX, ry, REL.same(), "Room same-as (renamed)");
  seg(s, xb + 0.1, py, NODEX, py, RATE_LINE(), "Rate plan split off");
  dot(s, NODEX, ry, 0.06, C.ink, false, "Room type node");
  dot(s, NODEX, py, 0.06, C.signal, false, "Rate plan node");
  T(s, roomCanon, { x: CANX, y: ry - 0.14, w: 3.0, h: 0.28, fontFace: F.head, fontSize: 13, valign: "middle" });
  T(s, rateCanon, { x: CANX, y: py - 0.14, w: 3.0, h: 0.28, fontFace: F.head, fontSize: 13, color: C.signalText, valign: "middle" });
  marker(s, 2, EXR - 0.22, ry - 0.11);
  y = py + 0.22;
  hline(s, EX, EXR, y, { color: C.hair });

  /* row 3: attraction, products, relations */
  y += 0.08;
  level("simulated", "Attraction → product → option", y);
  srcText("Klook", y + 0.1);
  const prod = [
    { name: "1-day ticket", rel: `${uss.family}: the base product` },
    { name: "Express Pass", rel: `variant of A  ·  ${diffAB}` },
    { name: "Combo packages in Sentosa", rel: `includes A  ·  ${diffAC}` },
    { name: "VIP Tour Experience", rel: "different from A  ·  a tour, not a pass" },
  ];
  const TX0 = EX + 0.22, TW = NODEX - 0.55 - TX0; // raw title column
  const pitch = 0.355, pys = prod.map((_, i) => y + 0.36 + i * pitch);
  prod.forEach((p, i) => {
    const cy = pys[i], L = "ABCD"[i];
    T(s, L, { x: EX, y: cy - 0.09, w: 0.2, h: 0.18, fontFace: F.head, fontSize: 10.5, color: C.ink2 });
    T(s, uss.items[i].title, { x: TX0, y: cy - 0.095, w: TW, h: 0.32, fontFace: F.mono, fontSize: 10, color: C.ink, lineSpacingMultiple: 0.92 });
    dot(s, NODEX, cy, 0.05, C.ink, false, `Product ${L}`);
    T(s, [run(L + "  ", { fontFace: F.head, color: C.ink2 }), run(p.name, { fontFace: F.head, color: C.ink, breakLine: true }), run(p.rel, { fontSize: 10.5, color: C.ink2 })],
      { x: CANX, y: cy - 0.1, w: EXR - CANX - 0.3, h: 0.34, fontSize: 11.5 });
  });
  // relations from A, as nested brackets left of the product nodes
  for (const [i, off, kind] of [[1, 0.12, "variant"], [2, 0.24, "includes"], [3, 0.36, "different"]]) {
    const xL = NODEX - 0.08 - off, a = pys[0], b = pys[i];
    if (kind === "includes") { // C includes A: drawn from C, the arrow ends on A
      seg(s, NODEX - 0.07, b, xL, b, { color: C.ink, width: 1.25 }, "Includes, from C");
      seg(s, xL, b, xL, a, { color: C.ink, width: 1.25 }, "Includes, up");
      seg(s, xL, a, NODEX - 0.08, a, REL.includes(), "Includes, to A");
    } else {
      seg(s, NODEX - 0.07, a, xL, a, REL[kind](), `${kind}, from A`);
      seg(s, xL, a, xL, b, REL[kind](), `${kind}, down`);
      seg(s, xL, b, NODEX - 0.07, b, REL[kind](), `${kind}, to ${"ABCD"[i]}`);
    }
  }
  marker(s, 1, EXR - 0.22, pys[1] - 0.11);

  /* what is new: four mechanisms, numbered where they appear */
  y = pys[3] + 0.31;
  hline(s, EX, EXR, y);
  capLabel(s, "What is new: four mechanisms, numbered where they appear", EX, y + 0.05, 7);
  const NEW = [
    ["Typed relations, not merge-or-don't. ", "Same as, variant of, includes or different, with the difference named."],
    ["Rate plan out of the room name first. ", "Board and refund terms are split off, so rooms match on room attributes."],
    ["Supplier reliability is priced. ", "Each offer's price carries its expected cost of a failed booking and of a price change."],
    ["Cost follows the hard cases. ", `Key rules and a small model settle ${pct(cheap)} of pairs; only the rest reach costlier tools.`],
  ];
  const cw = (EXR - EX - 0.3) / 2;
  NEW.forEach(([h, d], i) => {
    const x = EX + (i % 2) * (cw + 0.3), yy = y + 0.33 + Math.floor(i / 2) * 0.44;
    marker(s, i + 1, x, yy);
    T(s, [run(h, { fontFace: F.head, color: C.ink }), run(d, { color: C.ink2 })], { x: x + 0.3, y: yy, w: cw - 0.3, h: 0.4, fontSize: 10.5 });
  });
  const newEnd = y + 0.33 + 0.44 + 0.38;

  /* the pipeline spine, stretched to end level with the band */
  const STAGES = [
    ["measured", "Ingest and profile.", "Each feed into one schema; each supplier's data quality profiled."],
    ["measured", "Block.", `Geo cells and name neighbours keep ${pct(M.blocking_recall, 1)} of known matches (${M.candidates_per_record.toFixed(1)} per listing).`],
    ["measured", "Score in a cascade.", "Key rules → small model (LightGBM) → cross-encoder → LLM → human."],
    ["measured", "Cluster.", "Union-find with cannot-link constraints; stable IDs between runs: designed."],
    ["simulated", "Split rate from room, map rooms.", "Board and refund terms leave the room name first."],
    ["simulated", "Relate tours.", "Same as, variant of, includes or different, with the difference named."],
    ["designed", "Golden record.", "Best value per field, with its source; duplicate images removed."],
    ["designed", "Choose offers.", "Reliability-adjusted price: failure and price-change risk priced in."],
    ["designed", "Rank listings.", "Canonical cards; position bias corrected (inverse-propensity LambdaMART)."],
  ];
  const MARK = { 2: 4, 4: 2, 5: 1, 7: 3 }; // stage index -> marker number (stage 3's marker sits on the cascade bar)
  const TX = SX + 0.3, TWs = SXR - TX - 0.3, FS = 10.5;
  const hs = STAGES.map(([, h, d], i) => nlines(`${i + 1}  ${h} ${d}`, TWs, FS, 0.43) * LH(FS));
  const console_ = ["Review console and audit log, beside every stage. ", "Uncertain pairs queue for a person; every merge is logged and reversible."];
  const conH = nlines(console_.join(""), SXR - TX, FS, 0.43) * LH(FS);
  const BAR = 0.44, y0s = TOP + 0.36;
  const content = hs.reduce((a, b) => a + b, 0) + BAR + 0.12 + conH;
  const gap = Math.max(0.06, (newEnd - y0s - content) / 10);
  // the spine line goes in first, so the status marks sit on top of it
  const gyPre = [];
  hs.reduce((t, h, i) => { gyPre.push(t); return t + h + gap + (i === 2 ? BAR : 0); }, y0s);
  seg(s, SX + 0.075, gyPre[0] + 0.18, SX + 0.075, gyPre[8] + 0.03, { color: C.ink, width: 0.75 }, "Spine");
  let sy = y0s;
  const gy = [];
  STAGES.forEach(([st, h, d], i) => {
    gy.push(sy);
    glyph(s, SX, sy + 0.03, st, 0.15, `Stage ${i + 1} status`);
    T(s, [run(`${i + 1}  ${h} `, { fontFace: F.head, color: C.ink }), run(d, { color: C.ink2 })], { x: TX, y: sy, w: TWs, h: hs[i] + 0.04, fontSize: FS });
    if (MARK[i] && i !== 2) marker(s, MARK[i], SXR - 0.22, sy);
    sy += hs[i] + gap;
    if (i === 2) { // the cascade, drawn to scale
      const bx = TX, bw = TWs, bh = 0.2, by = sy - gap / 2;
      const segs = [[shareRules, C.ink, C.paper, "key rules"], [shareModel, C.ink2, C.paper, "small model"], [shareOn, C.hair, C.ink, "sent on"]];
      let cx = bx;
      segs.forEach(([v, fill, tc, lab], k) => {
        const w = v * bw;
        s.addText(pct(v), { isTextBox: true, shape: S.RECTANGLE, x: cx, y: by, w, h: bh, fill: { color: fill }, line: { color: fill, width: 0 },
          fontFace: F.head, fontSize: 10, color: tc, align: "center", valign: "middle", margin: 0, objectName: `Cascade: ${lab}` });
        T(s, lab, { x: cx, y: by + bh + 0.02, w: k === 0 ? 0.8 : w, h: 0.18, fontSize: 10, color: C.ink2, align: k === 0 ? "left" : "center" });
        cx += w;
      });
      marker(s, 4, SXR - 0.22, by - 0.01);
      sy = by + BAR + gap / 2;
    }
  });
  must(gy.every((v, i) => Math.abs(v - gyPre[i]) < 1e-9), "spine pre-pass matches the stage positions");
  hline(s, SX, SXR, sy - gap / 2 + 0.02, { color: C.hair2, dashType: "dash" }, "Console divider");
  glyph(s, SX, sy + 0.1, "designed", 0.15, "Review console status");
  T(s, [run(console_[0], { fontFace: F.head, color: C.ink }), run(console_[1], { color: C.ink2 })], { x: TX, y: sy + 0.07, w: SXR - TX, h: conH + 0.04, fontSize: FS });

  /* one legend */
  const LY = Math.max(newEnd, sy + 0.07 + conH) + 0.19;
  legend(s, EX, LY, [
    { head: "Relations", w: 0.8 },
    { line: "same", text: "same as", w: 0.66 }, { line: "variant", text: "variant of", w: 0.8 },
    { line: "includes", text: "includes", w: 0.68 }, { line: "different", text: "different", w: 0.82 },
    { runs: [run("Attributes   ", { fontFace: F.head, color: C.ink }), run("room in ink, ", { color: C.ink }), run("rate in orange", { color: C.signalText })], w: 2.8 },
  ]);
  legend(s, EX, LY + 0.24, [{ head: "Status", w: 0.8 }, ...STATUS_LEGEND]);
    must(LY + 0.34 < 7.3, "slide 2 legend inside the slide");

  s.addNotes(
    "[Video 0:22 to 1:54, tabs 2 to 4.] The statement asks for duplicates to be found without losing meaningful differences, so Canon's unit is a typed relation, not a merge. " +
    `Top row: four independent sources list Atlantis, The Palm, and OpenStreetMap names it in Arabic. A shared Wikidata ID and the pair model link them; the Arabic name scores only ${arabJw.toFixed(2)} on name similarity, so a name rule alone would miss it. ` +
    "Middle row: a supplier's room string mixes the room with the rate plan. Canon splits them: twin and partial sea view are the room; half board and non-refundable are the rate. Then it matches on room attributes only. " +
    "The room list is the hotel's real one; the renamed string comes from a simulated second supplier, and the hatched mark says so. " +
    `Bottom row: real Klook products for Universal Studios Singapore. The Express Pass is a variant of the ticket, the combo includes it, the VIP tour is different. A plain deduplicator would merge ${pct(N.sightseeing.dedup_merges_variants)} of variants like these. ` +
    `Right: the pipeline in order. Identifiers and phones settle ${pct(shareRules)} of candidate pairs as rules, a small model settles ${pct(shareModel)}, and only ${pct(shareOn)} go on to a cross-encoder, an LLM or a person. ` +
    "[Video 1:54 to 2:12, tab 5.] Offers: reliability gets a price. Ignore risk and the cheapest offer wins; price it in and a supplier that fails less often can win. The demo's prices are simulated; the mechanism is what we show. " +
    "Solid marks are measured on real data, hatched ones with a simulated second supplier, outlines are designed and not yet measured. " +
    "If asked about credit: union-find, LightGBM, Fellegi-Sunter's accept / review / reject bands and the OCTO product model are established; ours is the system, the typed-relation framing and the evaluation."
  );
}

/* ================================================================== slide 3: the proof and the path */
pres.addSection({ title: "Evidence" });
{
  const s = pres.addSlide({ masterName: "CANON_CONTENT", sectionTitle: "Evidence" });
  s.addText("It already runs on real data. TBO can start it in shadow mode.", { placeholder: "title" });
  s.addText(`Four open sources stand in for supplier feeds: ${num(N.data.listings_total)} real listings in ${N.data.cities} cities. Each result names the truth it was measured against.`, { placeholder: "body" });

  const TOP = 1.18, LX = 0.5, LXR = 6.55, RX = 6.95, RXR = 12.83;
  capLabel(s, "Matching on cities the model never saw", LX, TOP, 5.5);
  hline(s, LX, LXR, TOP + 0.24);
  capLabel(s, "What else is measured, and against what", RX, TOP, 5.5);
  hline(s, RX, RXR, TOP + 0.24);

  /* dumbbell: 12 held-out cities, rule -> model at the rule's precision */
  const cityName = { dubai: "Dubai", bangkok: "Bangkok", singapore: "Singapore", delhi: "Delhi", mumbai: "Mumbai", goa: "Goa", london: "London", paris: "Paris",
    amsterdam: "Amsterdam", barcelona: "Barcelona", vienna: "Vienna", milan: "Milan" };
  const cities = Object.keys(FAIR).filter(k => k !== "all 12 cities");
  must(cities.length === N.data.cities && cities.every(k => cityName[k]), "12 named cities in the fair comparison");
  const rows = cities.map(k => ({ k, name: cityName[k], r: FAIR[k].rule_recall, m: FAIR[k].model_recall_at_rule_precision }))
    .sort((a, b) => (b.m - b.r) - (a.m - a.r));
  const PX0 = 1.62, PX1 = 6.2, X = v => PX0 + v * (PX1 - PX0);
  T(s, "Share of true matches found in a city held out of training, at the rule's own precision", { x: LX, y: TOP + 0.31, w: LXR - LX, h: 0.22, fontSize: 10.5, color: C.ink2, valign: "middle" });
  const y0 = TOP + 0.9, rp = 0.222;
  const yEnd = y0 + (rows.length - 1) * rp, yAll = yEnd + 0.38;
  for (const g of [0, 0.25, 0.5, 0.75, 1]) {
    seg(s, X(g), y0 - 0.12, X(g), yAll + 0.15, { color: C.hair, width: 0.5 }, `Grid ${g * 100}%`);
    T(s, g === 1 ? "100%" : String(g * 100), { x: X(g) - 0.3, y: yAll + 0.18, w: 0.6, h: 0.18, fontSize: 10, color: C.ink2, align: "center" });
  }
  const drawRow = (r, cy, o = {}) => {
    const hi = o.hi, strong = o.strong, lc = hi ? C.signal : strong ? C.ink : C.ink3;
    T(s, r.name, { x: LX, y: cy - 0.1, w: 1.25, h: 0.2, fontSize: 11, fontFace: strong || hi ? F.head : F.body, color: C.ink, valign: "middle" });
    seg(s, X(r.r), cy, X(r.m), cy, { color: lc, width: hi || strong ? 2.5 : 1.5 }, `${r.name}: rule to model`);
    dot(s, X(r.r), cy, 0.06, C.ink, true, `${r.name}: rule`);
    dot(s, X(r.m), cy, 0.06, C.ink, false, `${r.name}: model`);
    const lo = { fontSize: 10.5, color: hi ? C.signalText : C.ink, fontFace: hi || strong ? F.head : F.body, valign: "middle" };
    T(s, String(p0(r.r)), { x: X(r.r) - 0.43, y: cy - 0.1, w: 0.33, h: 0.2, align: "right", ...lo });
    T(s, String(p0(r.m)), { x: X(r.m) + 0.1, y: cy - 0.1, w: 0.33, h: 0.2, align: "left", ...lo });
  };
  rows.forEach((r, i) => drawRow(r, y0 + i * rp, { hi: r.k === "bangkok" }));
  // direct labels on the first row, in place of a key
  const r0 = rows[0];
  T(s, "name + distance rule", { x: X(r0.r) - 0.8, y: y0 - 0.33, w: 1.6, h: 0.18, fontSize: 10, color: C.ink2, align: "center" });
  T(s, "Canon's pair model", { x: X(r0.m) - 0.8, y: y0 - 0.33, w: 1.6, h: 0.18, fontSize: 10, color: C.ink2, align: "center" });
  hline(s, LX, LXR, yEnd + 0.19, { color: C.hair });
  drawRow({ name: "All 12 cities", r: ALL.rule_recall, m: ALL.model_recall_at_rule_precision }, yAll, { strong: true });
  const bk = FAIR.bangkok;
  T(s, [run(`Bangkok, where names switch between Thai and Latin script: ${p0(bk.rule_recall)} → ${p0(bk.model_recall_at_rule_precision)}. `, { fontFace: F.head, color: C.signalText }),
        run("Truth: keys the model never sees (a shared Wikidata ID, or a rare phone or URL nearby), not hand labels.", { color: C.ink2 })],
    { x: LX, y: yAll + 0.42, w: LXR - LX, h: 0.5, fontSize: 10 });

  /* evidence table */
  const cols = [{ x: RX + 0.26, w: 2.05, h: "Tested" }, { x: RX + 2.42, w: 2.05, h: "Result" }, { x: RX + 4.6, w: RXR - RX - 4.6, h: "Measured against" }];
  cols.forEach(c => T(s, c.h, { x: c.x, y: TOP + 0.31, w: c.w, h: 0.2, fontSize: 10, color: C.ink2, valign: "middle" }));
  const EV = [
    ["measured", "Candidate pairs settled by key rules and a small model", `${pct(cheap)} of ${(M.candidate_pairs / 1e6).toFixed(2)} million`, "12-city run"],
    ["measured", `Public place-matching benchmark, ${Math.round(F2.records_per_world / 1000)}k records never trained on`,
      `IoU ${F2.v2_best_iou.toFixed(3)}, level with the published 1st place (${F2.published_first_place_cv.with_post_processing.toFixed(3)}, their own CV); best rule ${F2.best_rule_iou.toFixed(2)}`,
      "Competition labels (Foursquare)"],
    ["measured", "Two real Indian OTA feeds, no retraining", `${num(N.ota_transfer.goibibo_with_twin)} hotels matched`, "No labels yet"],
    ["simulated", `Renamed rooms mapped to the right room, ${num(N.rooms.hotels)} real hotels`, `${pct(N.rooms.parser_coverage)} vs ${pct(N.rooms.best_fuzzy_coverage)} for the best fuzzy matcher`, "Simulated second supplier"],
    ["simulated", "Tour variants a plain deduplicator would merge away", `${pct(N.sightseeing.dedup_merges_variants)}; combos ${pct(N.sightseeing.dedup_merges_combos)}`, "Simulated second supplier"],
    ["simulated", "Tour relations right, four types", `${pct(N.sightseeing.accuracy)} in-sample; ${pct(TH.rules_accuracy)} on new phrasings, ${pct(TH.cascade_accuracy)} with an open ${LLM_SIZE} LLM`, "Simulated second supplier"],
    ["designed", "Offer choice and listing ranking", "Not measured yet", "Ranking data awaits a Kaggle rules acceptance"],
  ];
  let ey = TOP + 0.58;
  hline(s, RX, RXR, ey - 0.04, { color: C.hair2 });
  EV.forEach(([st, what, res, truth], i) => {
    const nl = Math.max(nlines(what, cols[0].w, 10.5), nlines(res, cols[1].w, 10.5, 0.47), nlines(truth, cols[2].w, 10));
    const h = nl * LH(10.5) + 0.1;
    glyph(s, RX, ey + 0.045, st, 0.15, `Evidence ${i + 1} status`);
    T(s, what, { x: cols[0].x, y: ey + 0.02, w: cols[0].w, h: h - 0.06, fontSize: 10.5, color: C.ink });
    T(s, res, { x: cols[1].x, y: ey + 0.02, w: cols[1].w, h: h - 0.06, fontSize: 10.5, fontFace: F.head, color: C.ink });
    T(s, truth, { x: cols[2].x, y: ey + 0.02, w: cols[2].w, h: h - 0.06, fontSize: 10, color: C.ink2 });
    ey += h;
    hline(s, RX, RXR, ey - 0.02, { color: C.hair });
  });
  legend(s, RX, ey + 0.16, STATUS_LEGEND);
  must(ey + 0.3 < 5.84, "evidence table and legend clear the bottom band");

  /* impact, feasibility, adoption */
  const BY = 5.9, bw = (12.33 - 0.6) / 3;
  hline(s, 0.5, 12.83, BY - 0.08);
  const BLOCKS = [
    ["Impact for TBO", [
      ["Fewer duplicate cards: ", `Dubai's ${num(M.dubai.lodging_listings)} listings become ${num(M.dubai.canonical_entities)} hotels, every supplier's offer kept underneath.`],
      ["Like-for-like comparison: ", "rooms matched on room attributes; tour variants side by side, differences named."],
      ["Cheapest reliable offer first: ", "fewer failed bookings. Less manual mapping: people see only unsettled pairs."],
    ]],
    ["Technical feasibility", [
      ["Running code on a laptop CPU: ", `${num(N.data.listings_total)} real listings, ${N.data.sources} sources, ${N.data.cities} cities; GPU models see only the uncertain band.`],
      ["Permissive open source: ", "DuckDB, LightGBM, rapidfuzz, XLM-RoBERTa, Qwen2.5 (MIT or Apache-2.0)."],
      ["Established methods: ", "Fellegi–Sunter bands, union-find, OCTO's product model. Ours: the system, its framing and evaluation."],
    ]],
    ["Adoption risk, contained", [
      ["Beside TBO's hotel-mapping vendor: ", "its IDs become one more input; disagreements go to review, never overridden."],
      ["Thresholds in configuration; ", "uncertain pairs in a review queue; every merge logged and reversible."],
      ["Shadow mode first, ", "then live one destination at a time, once its numbers hold."],
    ]],
  ];
  BLOCKS.forEach(([head, items], i) => {
    const x = 0.5 + i * (bw + 0.3);
    T(s, head, { x, y: BY, w: bw, h: 0.22, fontFace: F.head, fontSize: 12, color: C.ink, valign: "middle" });
    const runs = [];
    items.forEach(([a, b], k) => { runs.push(run(a, { fontFace: F.head, color: C.ink })); runs.push(run(b, { color: C.ink2, breakLine: k < items.length - 1 })); });
    T(s, runs, { x, y: BY + 0.27, w: bw, h: 1.02, fontSize: 10.5, paraSpaceAfter: 2 });
  });

  s.addNotes(
    `[Video 2:12 to 2:38, tab 6.] What is measured today: on cities the model never saw, it finds ${pct(ALL.model_recall_at_rule_precision)} of true matches where a name-and-distance rule finds ${pct(ALL.rule_recall)}, at the same precision. ` +
    `In Bangkok, where names change script, ${pct(bk.model_recall_at_rule_precision)} against ${pct(bk.rule_recall)}. And ${pct(cheap)} of candidate pairs never reach an expensive model. ` +
    "Our truth for matching is independent identifiers, not hand labels, and the slide says so. " +
    "[Video 2:38 to 2:52.] Canon is built to sit beside existing hotel mapping: it takes those IDs as input, keeps thresholds in configuration, and logs every merge so it can be undone. It starts in shadow mode. " +
    `If asked, from the table: on the public Foursquare benchmark, ${Math.round(F2.records_per_world / 1000)}k records never trained on, IoU ${F2.v2_best_iou.toFixed(3)}, level with the published first place (${F2.published_first_place_cv.with_post_processing.toFixed(3)} on their own cross-validation; the splits differ, so never say "beat"). ` +
    `Rooms: ${pct(N.rooms.parser_coverage)} against ${pct(N.rooms.best_fuzzy_coverage)}, real room lists with a simulated second supplier. ` +
    `Tours: ${pct(N.sightseeing.accuracy)} is in-sample because the rules were tuned on those pairs; on phrasings written after the rules were frozen, rules score ${pct(TH.rules_accuracy)} and ${pct(TH.cascade_accuracy)} with an open ${LLM_SIZE} LLM added. ` +
    `Two Indian OTA feeds: ${num(N.ota_transfer.goibibo_with_twin)} hotels matched with no retraining, no labels yet, so no precision is claimed. Offer choice and ranking are designed, not measured.`
  );
}

/* ================================================================== thank you */
pres.addSection({ title: "Close" });
{
  const s = pres.addSlide({ masterName: "CANON_CLOSE", sectionTitle: "Close" });
  s.addText("Thank you", { placeholder: "title" });
  T(s, "What Round 2 adds, marked by where each part stands today", { x: 0.6, y: 1.85, w: 7.2, h: 0.35, fontSize: 18, color: C.ink });
  const NEXT = [
    ["designed", "Ranking on real hotel search logs, with position bias corrected"],
    ["designed", "Offer choice measured against a cheapest-price baseline"],
    ["simulated", "Rooms and tours against a second, real supplier feed"],
    ["measured", "Hotel matching scored against human labels (the label sheet is ready)"],
    ["designed", "Review console with audit log; cost per 1,000 records measured"],
  ];
  hline(s, 0.6, 7.75, 2.38);
  NEXT.forEach(([st, t], i) => {
    const y = 2.55 + i * 0.46;
    glyph(s, 0.6, y + 0.05, st, 0.17, `Round 2 item ${i + 1} status`);
    T(s, t, { x: 0.98, y, w: 6.8, h: 0.28, fontSize: 13, color: C.ink });
  });
  hline(s, 0.6, 7.75, 4.95, { color: C.hair });
  T(s, [run("Code, demo and model reports   ", { fontFace: F.head }), run(LINK, { color: C.ink2 })], { x: 0.6, y: 5.12, w: 7.2, h: 0.3, fontSize: 14, objectName: "Link line" });
  T(s, TEAM, { x: 0.6, y: 5.55, w: 7.2, h: 0.3, fontSize: 12, color: C.ink2, objectName: "Team line" });
  legend(s, 0.6, 6.85, [{ head: "Status", w: 0.6 }, ...STATUS_LEGEND]);

  const img = path.join(R1, "figures", "demo_match_evidence_crop.png");
  if (fs.existsSync(img)) {
    const w = 3.9, h = w * 1212 / 918, x = 12.83 - w, y = 0.75;
    s.addImage({ path: img, x, y, w, h, altText: "Validation demo: the four listings of Atlantis, The Palm and, for each pair, distance, name similarity, score and what decided the merge" });
    s.addShape(S.RECTANGLE, { x, y, w, h, fill: { type: "none" }, line: { color: C.ink3, width: 0.75 }, objectName: "Inset frame" });
    T(s, "From the validation demo, which runs offline from the repository: why the four Atlantis listings were merged.",
      { x, y: y + h + 0.1, w, h: 0.4, fontSize: 10, color: C.ink2 });
  }
  s.addNotes(
    "[Video 2:38 to 2:52.] Round two adds ranking on real search logs and a second real supplier for tours. Thank you. " +
    "Round 2 turns the designed and simulated parts into measured ones: ranking on the Expedia search logs once the Kaggle rules are accepted, offer choice against a cheapest-price baseline, " +
    "a second real supplier for rooms and tours, human labels for hotel matching, and the review console with the cost of each cascade stage measured. " +
    "The inset is the validation demo's evidence table for the Atlantis merge. Before submitting, replace the link and team lines (or rebuild with CANON_LINK and CANON_TEAM)."
  );
}

/* ------------------------------------------------------------------ write, then post-process */
const THEME_XML = `<a:clrScheme name="Canon"><a:dk1><a:srgbClr val="${C.ink}"/></a:dk1><a:lt1><a:srgbClr val="FFFFFF"/></a:lt1>` +
  `<a:dk2><a:srgbClr val="${C.ink2}"/></a:dk2><a:lt2><a:srgbClr val="${C.paper}"/></a:lt2><a:accent1><a:srgbClr val="${C.signal}"/></a:accent1>` +
  `<a:accent2><a:srgbClr val="${C.ink}"/></a:accent2><a:accent3><a:srgbClr val="${C.ink3}"/></a:accent3><a:accent4><a:srgbClr val="${C.signalText}"/></a:accent4>` +
  `<a:accent5><a:srgbClr val="${C.ink2}"/></a:accent5><a:accent6><a:srgbClr val="${C.hair}"/></a:accent6><a:hlink><a:srgbClr val="${C.signalText}"/></a:hlink>` +
  `<a:folHlink><a:srgbClr val="${C.ink3}"/></a:folHlink></a:clrScheme>`;
pres.writeFile({ fileName: OUT }).then(async () => {
  const zip = await JSZip.loadAsync(fs.readFileSync(OUT)), clean = new JSZip();
  for (const [name, f] of Object.entries(zip.files)) {
    if (f.dir) continue; // pptxgenjs writes folder entries; some viewers refuse them
    let buf = await f.async("nodebuffer");
    if (name === "ppt/theme/theme1.xml") { // pptxgenjs writes Office's palette; give the theme Canon's colours
      const xml = buf.toString("utf8");
      must(/<a:clrScheme name="[^"]*">[\s\S]*?<\/a:clrScheme>/.test(xml), "theme colour scheme found");
      buf = Buffer.from(xml.replace(/<a:clrScheme name="[^"]*">[\s\S]*?<\/a:clrScheme>/, THEME_XML).replace(/name="Office Theme"/, 'name="Canon"'), "utf8");
    }
    clean.file(name, buf, { createFolders: false });
  }
  fs.writeFileSync(OUT, await clean.generateAsync({ type: "nodebuffer", compression: "DEFLATE" }));
  console.log(`wrote ${OUT}`);
});
