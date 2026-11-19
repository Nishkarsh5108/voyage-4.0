// 05 · Evidence. Every value is read from submission/round1/numbers.json; every number carries what it was measured against.
import { $, esc, fmt, tag } from "./util.js";

export function initEvidence(N) {
  dumbbell(N);
  const R = N.rooms, T = N.sightseeing, F = N.fsq_benchmark, O = N.ota_transfer, Dt = N.data, M = N.matching;
  const F2 = N.fsq_v2, M2 = N.matching_stage2, RS = N.rooms_semantic, TH = N.sightseeing_heldout;  // 20 Nov upgrades (absent keys: cells skipped)
  const bar = (label, v, cls = "", txt) => `<div class="hb"><span>${esc(label)}</span><span class="t"><i class="${cls}" style="width:${(v * 100).toFixed(1)}%"></i></span><b class="num">${txt ?? fmt.pct0(v)}</b></div>`;
  const cells = [
    { tag: tag("sim"), h: "Rooms: renamed rooms mapped to the right room", stat: `${fmt.pct0(R.parser_coverage)}<small>vs ${fmt.pct0(R.best_fuzzy_coverage)} best fuzzy matcher</small>`,
      body: `${bar("room/rate parser", R.parser_coverage)}${bar("best fuzzy", R.best_fuzzy_coverage, "alt")}`,
      p: `Real room lists of ${fmt.int(R.hotels)} hotels (${fmt.int(R.rooms)} rooms); the second supplier is ${fmt.int(R.renamed_strings)} rule-based rewrites. The headline is coverage, not a precision claim.` },
    { tag: tag("sim"), h: "Tours: what a plain deduplicator merges into the base product", stat: `${fmt.pct0(T.dedup_merges_variants)}<small>of variants · ${fmt.pct0(T.dedup_merges_combos)} of combos</small>`,
      body: `${bar("variants merged", T.dedup_merges_variants, "sig")}${bar("combos merged", T.dedup_merges_combos, "sig")}`,
      p: `${fmt.int(T.products)} real Klook Singapore products, ${fmt.int(T.pairs)} pairs against a simulated second supplier. Canon's typed relations score ${fmt.pct0(T.accuracy)} on the same pairs, but the rules were tuned on them: ${tag("insample")}` },
    F2 ? { tag: tag("comp"), h: "Labelled place-matching benchmark at competition density", stat: `${fmt.dec3(F2.v2_best_iou)}<small>IoU · 1st place of 1,079 teams: ${fmt.dec3(F2.published_first_place_cv.with_post_processing)} (their CV)</small>`,
      body: `${bar("Canon v2", F2.v2_best_iou, "", fmt.dec3(F2.v2_best_iou))}${bar("published 1st place", F2.published_first_place_cv.with_post_processing, "alt", fmt.dec3(F2.published_first_place_cv.with_post_processing))}${bar("our v1 recipe, same data", F2.v1_recipe_iou, "alt", fmt.dec3(F2.v1_recipe_iou))}${bar("best rule", F2.best_rule_iou, "alt", fmt.dec3(F2.best_rule_iou))}`,
      p: `Foursquare Location Matching (public competition, research use): ${fmt.int(F2.records_per_world)} records per half, split by place. Models and thresholds are fitted on one half and scored on the other. The winners' CV folds differ from ours, so read it as the same league, not a rank.` }
    : { tag: tag("comp"), h: "Labelled place-matching benchmark, unseen places", stat: `${fmt.dec2(F.model_iou)}<small>cluster IoU vs ${fmt.dec2(F.best_rule_iou)} best rule</small>`,
      body: `${bar("pair model", F.model_iou, "", fmt.dec2(F.model_iou))}${bar("best rule", F.best_rule_iou, "alt", fmt.dec2(F.best_rule_iou))}${bar("blocking ceiling", F.blocking_ceiling_iou, "alt", fmt.dec2(F.blocking_ceiling_iou))}`,
      p: `${fmt.int(F.records)} labelled places from a public competition (research use), ${fmt.int(F.test_records)} held-out test records. Blocking caps what any model can reach at ${fmt.dec2(F.blocking_ceiling_iou)}.` },
    { tag: tag("nolabel"), h: "Two real Indian OTA feeds, no retraining", stat: `${fmt.int(O.goibibo_with_twin)}<small>Goibibo hotels with a MakeMyTrip twin</small>`,
      body: `<div class="hbar"><div class="hb"><span>accepted pairs</span><span></span><b class="num">${fmt.int(O.accepted_pairs)}</b></div><div class="hb"><span>median distance</span><span></span><b class="num">${fmt.int(O.median_dist_m)} m</b></div><div class="hb"><span>naive rule misses</span><span></span><b class="num">${fmt.int(O.missed_by_naive_rule)}</b></div></div>`,
      p: `${fmt.int(O.makemytrip)} MakeMyTrip and ${fmt.int(O.goibibo)} Goibibo properties, matched by the model trained on open data only. There are no labels for these feeds yet, so no precision is quoted.` },
    { tag: tag("count"), h: "The open-data benchmark itself", stat: `${fmt.int(Dt.listings_total)}<small>listings · ${Dt.sources} sources · ${Dt.cities} cities</small>`,
      body: `<div class="hbar"><div class="hb"><span>lodging</span><span></span><b class="num">${fmt.int(Dt.lodging_listings)}</b></div><div class="hb"><span>attractions</span><span></span><b class="num">${fmt.int(Dt.attraction_listings)}</b></div><div class="hb"><span>key-linked pairs</span><span></span><b class="num">${fmt.int(Dt.key_linked_pairs)}</b></div></div>`,
      p: `Overture, OpenStreetMap, Wikidata and Wikivoyage. ${fmt.millions(M.candidate_pairs)} candidate pairs after blocking; ${fmt.pct0(M.cascade_shares["Key rules"] + M.cascade_shares["Cheap model, confident"])} settled without an expensive model.` },
    { tag: tag("notmeasured"), h: "Offer choice and ranking", stat: `—<small>nothing to report yet</small>`, body: "",
      p: `The offer panel shows the mechanism with simulated prices and failure rates. Ranking is designed and waits on a benchmark whose rules need accepting on Kaggle. Neither has a number, so neither gets one here.` },
  ];
  if (M2) cells.push({ tag: tag("keys"), h: "Second-stage matcher, each city held out", stat: `${fmt.pct0(M2.recall_at_99_precision[1])}<small>recall at 99% precision, was ${fmt.pct0(M2.recall_at_99_precision[0])}</small>`,
    body: `${bar("average precision, stage 2", M2.average_precision[1], "", fmt.dec3(M2.average_precision[1]))}${bar("average precision, stage 1", M2.average_precision[0], "alt", fmt.dec3(M2.average_precision[0]))}${bar("precision at 95% recall, stage 2", M2.precision_at_95_recall[1])}${bar("precision at 95% recall, stage 1", M2.precision_at_95_recall[0], "alt")}`,
    p: `A second model reads each pair together with the record's competing candidates and two-hop links. Better average precision in ${M2.cities_with_higher_ap} of ${M2.cities} held-out cities, same weak labels. The live workbench still runs stage 1.` });
  if (TH) cells.push({ tag: tag("sim"), h: "Tours on phrasings the rules never saw", stat: TH.cascade_accuracy != null ? `${fmt.pct0(TH.cascade_accuracy)}<small>rules + LLM · rules alone ${fmt.pct0(TH.rules_accuracy)}</small>` : `${fmt.pct0(TH.rules_accuracy)}<small>rules alone, held out</small>`,
    body: `${TH.cascade_accuracy != null ? bar("rules + LLM", TH.cascade_accuracy) + bar("LLM alone", TH.llm_accuracy, "alt") : ""}${bar("rules alone", TH.rules_accuracy, "alt")}${bar("rules, in-sample", T.accuracy, "alt")}`,
    p: `${fmt.int(TH.pairs)} pairs written with new templates after the rules were frozen. The gap to the in-sample ${fmt.pct0(T.accuracy)} is the size of the lexicon's blind spots${TH.llm ? `; an open model (${esc(TH.llm.split("/").pop())}) closes part of it` : ""}.` });
  if (RS) cells.push({ tag: tag("sim"), h: "Rooms: parser first, sentence embedding for the rest", stat: `${fmt.pct1(RS.cascade_correct)}<small>mapped right · precision ${fmt.pct1(RS.cascade_precision)}</small>`,
    body: `${bar("parser + embedding", RS.cascade_correct, "", fmt.pct1(RS.cascade_correct))}${bar("parser alone", RS.parser_correct, "alt", fmt.pct1(RS.parser_correct))}${bar("embedding alone", RS.embedding_correct, "alt", fmt.pct1(RS.embedding_correct))}`,
    p: `Same renamed rooms, thresholds picked on 20% of hotels and scored on the other 80%. On its own, a multilingual embedding confuses sibling rooms (twin vs double); behind the parser it only takes what the parser leaves.` });
  $("#evGrid").innerHTML = cells.map(c => `<div class="ev-cell">${c.tag}<h4>${c.h}</h4><div class="stat num">${c.stat}</div>${c.body ? `<div class="hbar">${c.body}</div>` : ""}<p>${c.p}</p></div>`).join("");
  $("#cannotList").innerHTML = [
    [tag("nolabel"), "No hotel-matching accuracy against human labels. The sheet of pairs for people to label is prepared and not labelled."],
    [tag("keys"), "Matching numbers are against independent keys (Wikidata ID, rare phone or website), at the rule's own precision, on cities held out from training."],
    [tag("sim"), "Room and tour numbers use real catalogues and a simulated second supplier. They measure robustness to renaming, not a live feed."],
    [tag("insample"), TH ? `The ${fmt.pct0(T.accuracy)} typed-relation accuracy is in-sample. On templates written after the rules were frozen the rules score ${fmt.pct0(TH.rules_accuracy)}.` : "The typed-relation accuracy is in-sample: its rules were tuned on the pairs it is scored on."],
    [tag("notmeasured"), "No ranking or conversion number, and the offer panel is not a result."],
    [tag("count"), `Counts such as Dubai's ${fmt.int(N.matching.dubai.lodging_listings)} listings becoming ${fmt.int(N.matching.dubai.canonical_entities)} hotels are pipeline output, not accuracy.`],
  ].map(([t, s]) => `<li>${t}<br>${esc(s)}</li>`).join("");
}

function dumbbell(N) {
  const fc = N.matching.fair_comparison;
  const cities = Object.keys(fc).filter(c => c !== "all 12 cities").sort((a, b) => fc[b].model_recall_at_rule_precision - fc[a].model_recall_at_rule_precision);
  const rows = ["all 12 cities", ...cities];
  const svg = $("#dumbbell"), W = 620, rowH = 30, top = 56, left = 116, right = 70, H = top + rows.length * rowH + 30;
  const x = v => left + v * (W - left - right);
  const big = c => fc[c].model_recall_at_rule_precision - fc[c].rule_recall;
  const maxGap = Math.max(...cities.map(big));
  let s = `<g font-family="Plex Mono" font-size="10.5" fill="#87827a">`;
  for (const v of [0, .25, .5, .75, 1]) s += `<line x1="${x(v)}" y1="${top - 12}" x2="${x(v)}" y2="${H - 26}" stroke="rgba(21,20,15,.12)"/><text x="${x(v)}" y="${top - 18}" text-anchor="middle">${v * 100}%</text>`;
  s += `</g><text x="${left}" y="12" font-family="Archivo" font-size="10" font-weight="600" letter-spacing="1.4" fill="#4f4b43">RECALL AT THE RULE'S OWN PRECISION · EACH CITY HELD OUT</text>`;
  rows.forEach((c, i) => {
    const y = top + i * rowH + (i ? 10 : 0), v = fc[c], hot = c !== "all 12 cities" && big(c) === maxGap, all = c === "all 12 cities";
    const col = hot ? "#ff4f00" : "#15140f";
    s += `<g class="${all ? "all" : ""}"><text class="cn" x="${left - 12}" y="${y + 4}" text-anchor="end" font-size="${all ? 14 : 13}" ${hot ? 'fill="#c03a00"' : ""}>${esc(all ? "All 12 cities" : c[0].toUpperCase() + c.slice(1))}</text>
      <line x1="${x(v.rule_recall)}" y1="${y}" x2="${x(v.model_recall_at_rule_precision)}" y2="${y}" stroke="${col}" stroke-width="${all ? 3 : 2}"/>
      <circle cx="${x(v.rule_recall)}" cy="${y}" r="${all ? 6 : 5}" fill="#efebe1" stroke="${col}" stroke-width="1.6"/>
      <circle cx="${x(v.model_recall_at_rule_precision)}" cy="${y}" r="${all ? 6.5 : 5.5}" fill="${col}"/>
      <text x="${x(v.model_recall_at_rule_precision) + 10}" y="${y + 4}" ${hot ? 'fill="#c03a00"' : ""}>${fmt.pct0(v.model_recall_at_rule_precision)}</text>
      <text x="${x(v.rule_recall) - 10}" y="${y + 4}" text-anchor="end">${fmt.pct0(v.rule_recall)}</text>
      <text x="${W - 4}" y="${y + 4}" text-anchor="end" font-size="9.5">${fmt.int(v.matches)}</text></g>`;
    if (all) s += `<line x1="0" y1="${y + 18}" x2="${W}" y2="${y + 18}" stroke="#15140f"/>`;
  });
  s += `<g font-family="Plex Mono" font-size="10.5" fill="#4f4b43"><circle cx="${left + 4}" cy="${H - 8}" r="5" fill="#15140f"/><text x="${left + 14}" y="${H - 4}">pair model</text>
    <circle cx="${left + 104}" cy="${H - 8}" r="4.5" fill="#efebe1" stroke="#15140f" stroke-width="1.6"/><text x="${left + 114}" y="${H - 4}">name JW ≥ 0.9 and &lt; 200 m</text><text x="${W - 4}" y="${H - 4}" text-anchor="end">matches</text></g>`;
  svg.setAttribute("viewBox", `0 0 ${W} ${H}`); svg.innerHTML = s;
}
