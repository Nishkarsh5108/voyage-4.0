/* Round 1 deck: cover + two content slides + thank-you (the rules allow two content slides).
 * Every number is read from submission/round1/numbers.json (scripts/figures/round1_figures.py), so the deck cannot drift from the reports.
 * Usage: cd scripts/deck && npm install && node build_round1_deck.js
 * Output: submission/round1/Canon_Round1.pptx
 */
const path = require("path");
const fs = require("fs");
const pptxgen = require("pptxgenjs");

const ROOT = path.resolve(__dirname, "..", "..");
const R1 = path.join(ROOT, "submission", "round1");
const N = JSON.parse(fs.readFileSync(path.join(R1, "numbers.json"), "utf8"));
const TEAM = process.env.CANON_TEAM || "Team: add team name and members";
const LINK = process.env.CANON_LINK || "Demo, code and reports: add repository link";

const NAVY = "0B1F33", INK = "14202B", INK2 = "4A5560", MUTED = "7A8590", LINE = "DDE3EA", BG = "F3F6FA", WHITE = "FFFFFF";
const BLUE = "2A78D6", DEEP = "1C5CAB", ORANGE = "EB6834", AQUA = "128A5F", VIOLET = "6250D6", GRAY = "B9BDC4", AMBER = "9A6B00";
const pct = (x, d = 0) => (x * 100).toFixed(d) + "%";
const num = x => Number(x).toLocaleString("en-US");
const fair = N.matching.fair_comparison, all = fair["all 12 cities"];
const casc = N.matching.cascade_shares, cheap = casc["Key rules"] + casc["Cheap model, confident"];

const pres = new pptxgen();
pres.layout = "LAYOUT_WIDE"; // 13.33 x 7.5 in
pres.theme = { headFontFace: "Arial", bodyFontFace: "Calibri" };
pres.title = "Canon: one canonical product graph across suppliers";
pres.author = "VoyageHack 4.0 team";
pres.subject = "VoyageHack 4.0, Multi-Supplier Optimization, Round 1";

const FOOT = "Canon  ·  VoyageHack 4.0  ·  Multi-Supplier Optimization";
pres.defineSlideMaster({
  title: "COVER", background: { color: NAVY },
  objects: [
    { placeholder: { options: { name: "title", type: "title", x: 0.6, y: 2.0, w: 5.6, h: 1.2, fontFace: "Arial", fontSize: 60, bold: true, color: WHITE, align: "left", valign: "top", margin: 0 }, text: "" } },
    { placeholder: { options: { name: "body", type: "body", x: 0.6, y: 3.3, w: 5.6, h: 1.3, fontSize: 24, color: "CADCFC", align: "left", valign: "top", margin: 0 }, text: "" } },
  ],
});
pres.defineSlideMaster({
  title: "CONTENT", background: { color: WHITE }, margin: [0.3, 0.5, 0.5, 0.5],
  objects: [
    { placeholder: { options: { name: "title", type: "title", x: 0.5, y: 0.28, w: 12.33, h: 0.68, fontFace: "Arial", fontSize: 30, bold: true, color: INK, align: "left", valign: "middle", margin: 0 }, text: "" } },
    { placeholder: { options: { name: "body", type: "body", x: 0.5, y: 0.98, w: 12.33, h: 0.42, fontSize: 15, color: INK2, align: "left", valign: "middle", margin: 0 }, text: "" } },
    { text: { text: FOOT, options: { x: 0.5, y: 7.1, w: 8, h: 0.25, fontSize: 10, color: MUTED, margin: 0 } } },
  ],
  slideNumber: { x: 12.33, y: 7.1, w: 0.5, h: 0.25, fontSize: 10, color: MUTED, align: "right" },
});
pres.defineSlideMaster({
  title: "CLOSE", background: { color: NAVY },
  objects: [
    { placeholder: { options: { name: "title", type: "title", x: 0.6, y: 0.9, w: 6, h: 1.0, fontFace: "Arial", fontSize: 48, bold: true, color: WHITE, align: "left", valign: "top", margin: 0 }, text: "" } },
  ],
});

const T = (slide, text, o) => slide.addText(text, { isTextBox: true, margin: 0, fontSize: 14, color: INK, valign: "top", ...o });
const box = (slide, x, y, w, h, fill, name) => slide.addShape(pres.ShapeType.roundRect, { x, y, w, h, rectRadius: 0.06, fill: { color: fill }, line: { color: fill, width: 0 }, objectName: name });
const pill = (slide, text, x, y, w, color, name) => slide.addText(text, { isTextBox: true, shape: pres.ShapeType.roundRect, rectRadius: 0.1, x, y, w, h: 0.28, fill: { color }, line: { color, width: 0 },
  fontSize: 10.5, bold: true, color: WHITE, align: "center", valign: "middle", margin: 0, charSpacing: 0.5, objectName: name });
const label = (slide, text, x, y, w) => T(slide, text, { x, y, w, h: 0.26, fontSize: 11, bold: true, color: DEEP, charSpacing: 1.2 });

/* ------------------------------------------------------------------ cover */
pres.addSection({ title: "Cover" });
{
  const s = pres.addSlide({ masterName: "COVER", sectionTitle: "Cover" });
  s.addText("Canon", { placeholder: "title" });
  s.addText("One canonical product graph across suppliers", { placeholder: "body" });
  T(s, "VoyageHack 4.0  ·  Multi-Supplier Optimization  ·  Idea submission", { x: 0.6, y: 4.75, w: 5.6, h: 0.3, fontSize: 14, color: "9FB3C8" });
  T(s, TEAM, { x: 0.6, y: 5.15, w: 5.6, h: 0.3, fontSize: 14, color: WHITE, objectName: "Team line" });
  const img = path.join(R1, "figures", "demo_match_crop.png");
  if (fs.existsSync(img)) {
    s.addShape(pres.ShapeType.roundRect, { x: 6.55, y: 1.3, w: 6.3, h: 2.92, rectRadius: 0.05, fill: { color: WHITE }, line: { color: WHITE, width: 0 }, shadow: { type: "outer", color: "000000", opacity: 0.35, blur: 12, offset: 4, angle: 90 } });
    s.addImage({ path: img, x: 6.65, y: 1.4, w: 6.1, h: 2.62, altText: "Validation demo: four listings of Atlantis, The Palm from four sources merged into one hotel, with the evidence for each pair" });
    T(s, "From the validation demo: four sources list one Dubai hotel four ways, one of them in Arabic. Canon merges them and shows why.", { x: 6.55, y: 4.4, w: 6.3, h: 0.6, fontSize: 14, color: "CADCFC" });
  }
  T(s, `${num(N.data.listings_total)} real listings  ·  ${N.data.cities} cities  ·  ${N.data.sources} independent sources  ·  measured before Round 1`, { x: 0.6, y: 6.55, w: 12.1, h: 0.3, fontSize: 14, color: "9FB3C8" });
  s.addNotes("Canon turns many supplier feeds into one canonical product graph: hotels with rooms and rate plans, attractions with products and options. " +
    "The picture is from our validation demo: Overture, OpenStreetMap, Wikidata and Wikivoyage each list Atlantis, The Palm; OpenStreetMap names it in Arabic. " +
    "They are merged into one hotel and the demo shows the evidence for each pair. Replace the team line before submitting.");
}

/* ------------------------------------------------------------------ slide 1: the idea */
pres.addSection({ title: "Idea" });
{
  const s = pres.addSlide({ masterName: "CONTENT", sectionTitle: "Idea" });
  s.addText("It is not deduplication. It is a product graph", { placeholder: "title" });
  s.addText("Suppliers describe the same hotels, rooms and tours differently. Merging look-alikes is not enough: the differences are the product.", { placeholder: "body" });

  // left: four relations with real examples, plus the room / rate split
  label(s, "FOUR RELATIONS, REAL EXAMPLES", 0.5, 1.58, 4.3);
  const cards = [
    ["SAME AS", DEEP, "Atlantis, The Palm  =  فندق أتلانتس", "One hotel, two scripts, pins 18 m apart"],
    ["VARIANT OF", VIOLET, "Universal Studios ticket  vs  Express Pass", "Same park, access: standard → express"],
    ["INCLUDES", ORANGE, "Flyer + Gardens combo  ⊃  Flyer ticket", "The combo adds a second attraction"],
    ["DIFFERENT", MUTED, "Universal Studios ticket  vs  VIP Tour", "Same venue, different experience"],
  ];
  cards.forEach(([rel, col, l1, l2], i) => {
    const y = 1.9 + i * 0.93;
    box(s, 0.5, y, 4.3, 0.81, BG, `Relation card ${i + 1}`);
    pill(s, rel, 0.64, y + 0.12, 1.12, col, `Relation badge ${i + 1}`);
    T(s, l1, { x: 1.9, y: y + 0.09, w: 2.82, h: 0.3, fontSize: 12, bold: true, valign: "middle" });
    T(s, l2, { x: 1.9, y: y + 0.42, w: 2.82, h: 0.3, fontSize: 12, color: INK2, valign: "middle" });
  });
  const yr = 1.9 + 4 * 0.93;
  box(s, 0.5, yr, 4.3, 1.12, BG, "Room and rate card");
  pill(s, "ROOM ≠ RATE", 0.64, yr + 0.12, 1.12, AQUA, "Room badge");
  T(s, "DLX DBL SV BB NRF", { x: 1.9, y: yr + 0.09, w: 2.82, h: 0.3, fontSize: 12, bold: true, fontFace: "Courier New", valign: "middle" });
  T(s, [{ text: "Room: ", options: { bold: true } }, { text: "deluxe · double · sea view", options: { breakLine: true } },
        { text: "Rate: ", options: { bold: true, color: ORANGE } }, { text: "breakfast · non-refundable", options: { color: ORANGE } }],
    { x: 1.9, y: yr + 0.43, w: 2.82, h: 0.6, fontSize: 12, color: INK2 });

  // right: the pipeline
  const X0 = 5.15, W = 7.68;
  label(s, "ONE PIPELINE, CHEAPEST TOOL FIRST", X0, 1.58, W);
  const stages = [
    ["Ingest and profile", "One schema. Score each feed's pins, phones and gaps.", AQUA],
    ["Block", `Geo and name candidates: ${pct(N.matching.blocking_recall, 1)} recall, ${N.matching.candidates_per_record.toFixed(1)} pairs per record.`, AQUA],
    ["Match cascade", "Key rules → small model → cross-encoder → LLM → human.", AQUA],
    ["Product graph", "Hotel → room → rate. Attraction → product → option.", AMBER],
    ["Offer choice", "Reliability-adjusted price across suppliers.", MUTED],
    ["Ranking", "Canonical cards, bias-corrected learning to rank.", MUTED],
  ];
  const gap = 0.2, bw = (W - gap * 5) / 6;
  stages.forEach(([name, desc, col], i) => {
    const x = X0 + i * (bw + gap), y = 1.9;
    box(s, x, y, bw, 1.86, BG, `Stage ${i + 1}`);
    s.addShape(pres.ShapeType.ellipse, { x: x + 0.12, y: y + 0.12, w: 0.2, h: 0.2, fill: { color: col }, line: { color: col, width: 0 }, objectName: `Stage ${i + 1} status` });
    T(s, String(i + 1), { x: x + 0.4, y: y + 0.1, w: 0.4, h: 0.24, fontSize: 11, bold: true, color: MUTED, valign: "middle" });
    T(s, name, { x: x + 0.1, y: y + 0.4, w: bw - 0.2, h: 0.5, fontSize: 13, bold: true, valign: "top" });
    T(s, desc, { x: x + 0.1, y: y + 0.9, w: bw - 0.2, h: 0.92, fontSize: 10.5, color: INK2 });
    if (i < 5) T(s, "›", { x: x + bw, y: y + 0.65, w: gap, h: 0.4, fontSize: 18, color: MUTED, align: "center", valign: "middle" });
  });
  [[AQUA, "measured on real data"], [AMBER, "tested with a simulated second supplier"], [MUTED, "designed, not yet measured"]].forEach(([col, txt], i) => {
    const x = X0 + [0, 2.0, 5.15][i];
    s.addShape(pres.ShapeType.ellipse, { x, y: 3.93, w: 0.16, h: 0.16, fill: { color: col }, line: { color: col, width: 0 } });
    T(s, txt, { x: x + 0.24, y: 3.87, w: 3.0, h: 0.28, fontSize: 11, color: INK2, valign: "middle" });
  });
  T(s, "In the cascade, the key rules and the small model are measured; the later stages are designed.", { x: X0, y: 4.16, w: W, h: 0.26, fontSize: 11, color: MUTED, valign: "middle" });

  label(s, "WHAT IS NEW", X0, 4.55, W);
  const news = [
    ["Typed relations, not merge or don't merge", "Each pair gets a relation and a difference chip, so variants stay comparable instead of vanishing."],
    ["Room and rate split before matching", "Board, refund terms and promotions leave the room name first; rooms are then matched on attributes."],
    ["Reliability is priced, not labelled", "Failure and price-jump risk enter the offer price, so the cheapest offer is not first by default."],
    ["Cost follows hard cases", `Rules and a small model settle ${pct(cheap)} of candidate pairs. Expensive models see only the rest.`],
  ];
  const cw = (W - 0.2) / 2;
  news.forEach(([h, d], i) => {
    const x = X0 + (i % 2) * (cw + 0.2), y = 4.85 + Math.floor(i / 2) * 0.98;
    box(s, x, y, cw, 0.88, BG, `New ${i + 1}`);
    T(s, h, { x: x + 0.14, y: y + 0.08, w: cw - 0.28, h: 0.28, fontSize: 13, bold: true, valign: "middle" });
    T(s, d, { x: x + 0.14, y: y + 0.37, w: cw - 0.28, h: 0.47, fontSize: 11, color: INK2 });
  });
  s.addNotes("The statement asks for duplicates to be found without losing meaningful differences. So the unit is a relation, not a merge. " +
    "All four examples are real: the Dubai hotel is listed in Arabic by one source and English by three; the Universal Studios, Singapore Flyer and VIP tour products are real Klook listings. " +
    "The room example shows why room mapping fails on raw strings: the supplier glued the rate plan to the room. " +
    "The pipeline runs the cheapest tool first: identifiers and phones as rules, then a small gradient-boosted model, and only the uncertain pairs go to a cross-encoder, an LLM or a person. " +
    "Green stages are measured on real data, amber ones with a simulated second supplier, grey is design. " +
    "It is built to sit beside an existing hotel-mapping vendor: vendor IDs come in as one more key, are audited where errors cost money, and rooms, tours, offers and ranking are added on top.");
}

/* ------------------------------------------------------------------ slide 2: evidence, impact, feasibility, adoption */
pres.addSection({ title: "Evidence" });
{
  const s = pres.addSlide({ masterName: "CONTENT", sectionTitle: "Evidence" });
  s.addText("Tested on real public data before Round 1", { placeholder: "title" });
  s.addText(`${num(N.data.listings_total)} listings from ${N.data.sources} independent sources in ${N.data.cities} cities stand in for supplier feeds. Each card names the truth it was measured against.`, { placeholder: "body" });

  const stats = [
    [`${pct(all.model_recall_at_rule_precision)} vs ${pct(all.rule_recall)}`, "of true hotel and attraction matches found, model vs a name + distance rule at equal precision, on cities never seen in training", "Truth: independent keys, not hand labels", BLUE],
    [`${pct(N.rooms.parser_coverage)} vs ${pct(N.rooms.best_fuzzy_coverage)}`, `of renamed room strings mapped to the right room, parser vs best fuzzy matcher, across ${num(N.rooms.hotels)} real hotels`, "Truth: simulated second supplier", AQUA],
    [`${pct(N.sightseeing.dedup_merges_variants)}`, `of tour variants a deduplicator would merge away. Typed relations keep them apart: ${pct(N.sightseeing.accuracy)} accuracy over four relation types`, "Truth: simulated second supplier, in-sample", VIOLET],
    [`${pct(cheap)}`, `of ${(N.matching.candidate_pairs / 1e6).toFixed(2)} million candidate pairs settled by rules and a small model; the rest go to costlier stages`, "Measured on the 12-city run", ORANGE],
  ];
  const sw = (12.33 - 0.2 * 3) / 4;
  stats.forEach(([big, txt, truth, col], i) => {
    const x = 0.5 + i * (sw + 0.2), y = 1.55;
    box(s, x, y, sw, 1.72, BG, `Stat ${i + 1}`);
    T(s, big, { x: x + 0.16, y: y + 0.1, w: sw - 0.32, h: 0.55, fontSize: 30, bold: true, color: col, fontFace: "Arial", valign: "middle" });
    T(s, txt, { x: x + 0.16, y: y + 0.68, w: sw - 0.32, h: 0.72, fontSize: 11.5, color: INK });
    T(s, truth, { x: x + 0.16, y: y + 1.42, w: sw - 0.32, h: 0.24, fontSize: 10, italic: true, color: MUTED, valign: "middle" });
  });

  // native chart: model vs rule per held-out city
  const cities = ["dubai", "bangkok", "singapore", "all 12 cities"], names = ["Dubai", "Bangkok", "Singapore", "All 12 cities"];
  s.addChart(pres.charts.BAR, [
    { name: "Pair model", labels: names, values: cities.map(c => Math.round(fair[c].model_recall_at_rule_precision * 100)) },
    { name: "Name + distance rule", labels: names, values: cities.map(c => Math.round(fair[c].rule_recall * 100)) },
  ], {
    x: 0.5, y: 3.42, w: 6.4, h: 2.95, barDir: "col", barGrouping: "clustered", barGapWidthPct: 60, chartColors: [BLUE, GRAY],
    showTitle: true, title: "True matches found at equal precision, held-out city (%)", titleFontSize: 12, titleColor: INK, titleFontFace: "Calibri",
    showValue: true, dataLabelPosition: "outEnd", dataLabelFontSize: 11, dataLabelColor: INK, dataLabelFontFace: "Calibri",
    catAxisLabelColor: INK2, catAxisLabelFontSize: 11, catAxisLabelFontFace: "Calibri", valAxisLabelColor: MUTED, valAxisLabelFontSize: 10, valAxisLabelFontFace: "Calibri",
    valAxisMinVal: 0, valAxisMaxVal: 100, valAxisMajorUnit: 25, valGridLine: { color: LINE, size: 0.75 }, catGridLine: { style: "none" },
    showLegend: true, legendPos: "b", legendFontSize: 11, legendColor: INK2, legendFontFace: "Calibri", objectName: "Matching chart",
  });
  T(s, [{ text: "Also measured: ", options: { bold: true } },
        { text: `${(N.fsq_benchmark.records / 1e6).toFixed(2)} million labelled places, cluster score ${N.fsq_benchmark.model_iou.toFixed(2)} vs ${N.fsq_benchmark.best_rule_iou.toFixed(2)} for the best rule. ` +
                `Two real Indian OTA feeds: ${num(N.ota_transfer.goibibo_with_twin)} hotels matched across them with no retraining (no labels yet).` }],
    { x: 0.5, y: 6.4, w: 6.4, h: 0.5, fontSize: 11.5, color: INK2 });

  // right: impact, feasibility, adoption
  const bx = 7.2, bwid = 5.63;
  const blocks = [
    ["IMPACT", BLUE, `Fewer duplicate cards (Dubai: ${num(N.matching.dubai.lodging_listings)} listings become ${num(N.matching.dubai.canonical_entities)} hotels), like-for-like rooms and tours, the cheapest reliable offer first: more conversion, fewer failed bookings.`],
    ["FEASIBILITY", AQUA, `Running code on open-source tools with permissive licences (DuckDB, LightGBM, rapidfuzz). ${num(N.matching.records)} listings blocked, scored and clustered in under nine minutes on a laptop CPU.`],
    ["ADOPTION", ORANGE, "Takes existing mapping IDs as input. Thresholds in configuration, a review queue for uncertain pairs, every merge logged and reversible, shadow-mode rollout."],
  ];
  blocks.forEach(([tag, col, txt], i) => {
    const y = 3.42 + i * 0.99;
    box(s, bx, y, bwid, 0.89, BG, `${tag} block`);
    pill(s, tag, bx + 0.14, y + 0.12, 1.3, col, `${tag} tag`);
    T(s, txt, { x: bx + 1.58, y: y + 0.06, w: bwid - 1.7, h: 0.77, fontSize: 11.5, color: INK, valign: "middle" });
  });
  T(s, "Not yet measured: offer choice and ranking (designed; ranking benchmark queued), and matching against hand labels (a 400-pair sheet is ready).",
    { x: bx, y: 6.42, w: bwid, h: 0.5, fontSize: 11.5, color: MUTED });
  s.addNotes("We ran the idea on real public data before writing this slide. Four independent open sources play the role of supplier feeds in twelve cities. " +
    "Matching: trained on eleven cities and tested on the twelfth, the pair model finds " + pct(all.model_recall_at_rule_precision) + " of true matches where a name-and-distance rule finds " + pct(all.rule_recall) +
    " at the same precision; in Bangkok, where names switch script, " + pct(fair.bangkok.model_recall_at_rule_precision) + " against " + pct(fair.bangkok.rule_recall) + ". " +
    "The truth here is independent keys such as a shared Wikidata ID, which the model never sees; it is not hand-labelled, and we say so. " +
    "Rooms and tours use real catalogues with a simulated second supplier. " +
    "The cascade number is the cost story: most pairs never reach an expensive model. " +
    "Offer choice and ranking are designed and shown in the demo with simulated prices; they are not results yet.");
}

/* ------------------------------------------------------------------ thank you */
pres.addSection({ title: "Close" });
{
  const s = pres.addSlide({ masterName: "CLOSE", sectionTitle: "Close" });
  s.addText("Thank you", { placeholder: "title" });
  T(s, "What Round 2 will show", { x: 0.6, y: 2.3, w: 6, h: 0.4, fontSize: 20, bold: true, color: "CADCFC" });
  const next = ["Ranking on real hotel search logs, with position-bias correction and duplicates collapsed",
                "Sightseeing matched against a second real supplier feed",
                "An LLM adjudicator for the uncertain pairs, with measured cost per 1,000 records",
                "A review console: every merge explained, logged and reversible"];
  T(s, next.map((t, i) => ({ text: t, options: { bullet: true, breakLine: i < next.length - 1, paraSpaceAfter: 8 } })), { x: 0.6, y: 2.85, w: 6.4, h: 2.6, fontSize: 16, color: WHITE });
  T(s, LINK, { x: 0.6, y: 6.2, w: 6.4, h: 0.3, fontSize: 14, color: "9FB3C8", objectName: "Link line" });
  const img = path.join(R1, "figures", "demo_acts_crop.png");
  if (fs.existsSync(img)) {
    s.addShape(pres.ShapeType.roundRect, { x: 7.45, y: 1.2, w: 5.4, h: 3.86, rectRadius: 0.05, fill: { color: WHITE }, line: { color: WHITE, width: 0 }, shadow: { type: "outer", color: "000000", opacity: 0.35, blur: 12, offset: 4, angle: 90 } });
    s.addImage({ path: img, x: 7.55, y: 1.3, w: 5.2, h: 3.66, altText: "Validation demo: real Klook products for Universal Studios Singapore and the typed relations between them" });
    T(s, "From the validation demo: one attraction's real products as a family, with the relation and the difference for each pair.", { x: 7.45, y: 5.25, w: 5.4, h: 0.6, fontSize: 14, color: "CADCFC" });
  }
  s.addNotes("Round 2 turns the designed stages into measured ones: ranking on real search logs, a second real supplier for sightseeing, the LLM stage with its cost measured, and the review console. Replace the link line before submitting.");
}

const out = path.join(R1, "Canon_Round1.pptx");
pres.writeFile({ fileName: out }).then(async () => {
  // pptxgenjs writes folder entries into the zip; some cloud viewers refuse those, so rewrite the package without them
  const JSZip = require("jszip");
  const zip = await JSZip.loadAsync(fs.readFileSync(out)), clean = new JSZip();
  for (const [name, f] of Object.entries(zip.files)) if (!f.dir) clean.file(name, await f.async("nodebuffer"), { createFolders: false });
  fs.writeFileSync(out, await clean.generateAsync({ type: "nodebuffer", compression: "DEFLATE" }));
  console.log("wrote", out);
});
