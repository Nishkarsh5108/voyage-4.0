"""Slide-ready figures and a numbers file for the Round 1 deck and video.

Everything is computed from saved outputs, nothing is retrained:
  data/processed/city_matcher/pairs.parquet, reports/models/*.json, kaggle/fsq_pair_model/output/metrics.json
Output: submission/round1/figures/*.png, submission/round1/numbers.json
Usage : python -I scripts/figures/round1_figures.py
"""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.metrics import precision_recall_curve

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "eda"))
from common import INK, INK2, MUTED, SERIES, plt  # noqa: E402

OUT = ROOT / "submission" / "round1" / "figures"
OUT.mkdir(parents=True, exist_ok=True)
GRAY = "#c3c2b7"
plt.rcParams.update({"font.size": 13, "axes.titlesize": 15, "legend.fontsize": 12, "savefig.dpi": 200})
CORE = ["dubai", "bangkok", "singapore"]
CITY_ORDER = CORE + ["delhi", "mumbai", "goa", "london", "paris", "amsterdam", "barcelona", "vienna", "milan"]

cm = json.loads((ROOT / "reports" / "models" / "city_matcher.json").read_text(encoding="utf-8"))
rooms = json.loads((ROOT / "reports" / "models" / "rooms.json").read_text(encoding="utf-8"))
acts = json.loads((ROOT / "reports" / "models" / "activities.json").read_text(encoding="utf-8"))
ota = json.loads((ROOT / "reports" / "models" / "ota_matcher.json").read_text(encoding="utf-8"))
fsq = json.loads((ROOT / "kaggle" / "fsq_pair_model" / "output" / "metrics.json").read_text())
cs = json.loads((ROOT / "reports" / "eda" / "city_sources.json").read_text(encoding="utf-8"))

# ============================================================================ fair model-vs-rule comparison
# Rule: name Jaro-Winkler >= 0.9 and distance < 200 m. The model is read at the SAME precision as the rule (its recall there),
# and at the SAME recall as the rule (its precision there). Scores are out-of-city predictions.
P = pd.read_parquet(ROOT / "data" / "processed" / "city_matcher" / "pairs.parquet", columns=["city", "y", "p", "name_jw", "dist_m"])
P = P[P["y"] >= 0]


def compare(d):
    y, p = d["y"].to_numpy(), d["p"].to_numpy()
    rule = (d["name_jw"].to_numpy() >= 0.9) & (d["dist_m"].to_numpy() < 200)
    tp = int(y[rule].sum())
    rp, rr = tp / max(int(rule.sum()), 1), tp / max(int(y.sum()), 1)
    prec, rec, _ = precision_recall_curve(y, p)
    ok = np.where(prec[:-1] >= rp)[0]
    rec_at = float(rec[ok].max()) if len(ok) else 0.0
    ok2 = np.where(rec[:-1] >= rr)[0]
    prec_at = float(prec[ok2].max()) if len(ok2) else 0.0
    return {"matches": int(y.sum()), "non_matches": int((y == 0).sum()), "rule_precision": rp, "rule_recall": rr,
            "model_recall_at_rule_precision": rec_at, "model_precision_at_rule_recall": prec_at,
            "model_errors_at_rule_recall": 1 - prec_at, "rule_errors": 1 - rp}


fair = {c: compare(P[P["city"] == c]) for c in CITY_ORDER}
fair["all 12 cities"] = compare(P)
for k, v in fair.items():
    print(f"{k:14s} rule P={v['rule_precision']:.3f} R={v['rule_recall']:.3f} | model R@ruleP={v['model_recall_at_rule_precision']:.3f} P@ruleR={v['model_precision_at_rule_recall']:.4f}")

# ============================================================================ figures
def save(fig, name):
    fig.savefig(OUT / f"{name}.png")
    plt.close(fig)


# F1 matching: recall at the rule's own precision
labels = ["Dubai", "Bangkok", "Singapore", "All 12 cities"]
keys = CORE + ["all 12 cities"]
fig, ax = plt.subplots(figsize=(8.2, 3.9))
y = np.arange(len(keys))[::-1]
m = [fair[k]["model_recall_at_rule_precision"] * 100 for k in keys]
r = [fair[k]["rule_recall"] * 100 for k in keys]
ax.barh(y + 0.2, m, height=0.36, color=SERIES[0], label="Pair model")
ax.barh(y - 0.2, r, height=0.36, color=GRAY, label="Name + distance rule")
for i in range(len(keys)):
    ax.text(m[i] + 1, y[i] + 0.2, f"{m[i]:.0f}%", va="center", color=INK, fontweight="bold")
    ax.text(r[i] + 1, y[i] - 0.2, f"{r[i]:.0f}%", va="center", color=INK2)
ax.set_yticks(y, [f"{l} held out" if l != "All 12 cities" else l for l in labels])
ax.set_xlim(0, 108); ax.grid(axis="y", visible=False); ax.set_xlabel("share of true matches found, at the rule's own precision")
ax.set_title("Cross-source matching on a city the model never saw")
ax.legend(loc="lower center", bbox_to_anchor=(0.5, 1.12), ncol=2)
save(fig, "matching_vs_rule")

# F2 rooms
meth = rooms["benchmark"]["methods"]
names = {"exact string (normalised)": "Exact string", "fuzzy token-set >= 90": "Fuzzy: token set", "fuzzy weighted ratio >= 90": "Fuzzy: weighted ratio",
         "fuzzy token-sort >= 80": "Fuzzy: token sort", "attribute parser (canon.rooms)": "Room / rate parser"}
order = sorted(meth, key=lambda k: meth[k]["coverage"])
fig, ax = plt.subplots(figsize=(8.2, 3.6))
vals = [meth[k]["coverage"] * 100 for k in order]
ax.barh([names[k] for k in order], vals, height=0.6, color=[SERIES[0] if k.startswith("attribute") else GRAY for k in order])
for i, v in enumerate(vals):
    ax.text(v + 1, i, f"{v:.0f}%", va="center", color=INK, fontweight="bold" if order[i].startswith("attribute") else "normal")
ax.set_xlim(0, 108); ax.grid(axis="y", visible=False); ax.set_xlabel("renamed room strings mapped to the right room (all methods >= 98.6% precise)")
ax.set_title("Room mapping across suppliers")
save(fig, "rooms_methods")

# F3 sightseeing: what a deduplicator merges
dd = acts["binary_dedup_would_merge"]
fig, ax = plt.subplots(figsize=(8.2, 2.9))
lab = ["True duplicates", "Combos (a second attraction added)", "Variants (pickup, meal, child ticket, skip-the-line)"]
val = [dd["SAME_AS"] * 100, dd["INCLUDES"] * 100, dd["VARIANT_OF"] * 100]
ax.barh(lab, val, height=0.6, color=[GRAY, SERIES[1], SERIES[1]])
for i, v in enumerate(val):
    ax.text(v + 1, i, f"{v:.0f}%", va="center", color=INK, fontweight="bold" if i else "normal")
ax.set_xlim(0, 112); ax.grid(axis="y", visible=False); ax.set_xlabel("share a string-similarity deduplicator merges into the base product")
ax.set_title("Deduplication erases the differences that matter")
save(fig, "activities_dedup")

# F4 cascade: one segmented bar
cz = cm["cascade"]
tot = cz["candidates"]
parts = [("Key rules", (cz["stage0_key_match"] + cz["stage0_key_reject"]) / tot, SERIES[0]),
         ("Cheap model, confident", (cz["stage2_model_accept"] + cz["stage2_model_reject"]) / tot, SERIES[2]),
         ("Uncertain: cross-encoder, LLM, human", cz["uncertain_to_next_stage"] / tot, SERIES[1])]
fig, ax = plt.subplots(figsize=(8.2, 2.1))
left = 0
for name, share, col in parts:
    ax.barh([0], [share * 100 - 0.6], left=left + 0.3, height=0.55, color=col, label=name)
    ax.text(left + share * 50, 0, f"{share:.0%}", ha="center", va="center", color="#0b0b0b" if col == SERIES[2] else "#ffffff", fontweight="bold", fontsize=14)
    left += share * 100
ax.set_xlim(0, 100); ax.set_ylim(-0.5, 0.5); ax.axis("off")
ax.set_title(f"Who settles each of {tot / 1e6:.2f} million candidate pairs", loc="left")
ax.legend(loc="upper center", bbox_to_anchor=(0.5, 0.12), ncol=3, frameon=False)
save(fig, "cascade")

# F5 Foursquare benchmark
t = fsq["test"]
rows = [("Rule: exact name, < 1 km", t["baselines"]["exact normalised name & dist<1km"]["cluster_iou"], GRAY),
        ("Rule: name JW >= 0.9, < 200 m", t["baselines"]["name_jw>=0.9 & dist<200m"]["cluster_iou"], GRAY),
        ("Rule: token set >= 0.9, < 500 m", t["baselines"]["name_token_set>=0.9 & dist<500m"]["cluster_iou"], GRAY),
        ("Pair model (LightGBM)", t["cluster"]["iou"], SERIES[0])]
fig, ax = plt.subplots(figsize=(8.2, 3.2))
ax.barh([x[0] for x in rows], [x[1] for x in rows], height=0.6, color=[x[2] for x in rows])
for i, x in enumerate(rows):
    ax.text(x[1] + 0.008, i, f"{x[1]:.3f}", va="center", color=INK, fontweight="bold" if i == 3 else "normal")
ax.set_xlim(0.6, 1.0); ax.grid(axis="y", visible=False); ax.set_xlabel("cluster score (mean IoU) on 228K records of unseen places")
ax.set_title("Labelled benchmark: 1.14 million POI records")
save(fig, "fsq_benchmark")

# F6 canonical reduction per city
cl = cm["clusters"]
order = sorted(CITY_ORDER, key=lambda c: cl[c]["reduction"])
fig, ax = plt.subplots(figsize=(8.2, 4.6))
vals = [cl[c]["reduction"] * 100 for c in order]
ax.barh([c.title() for c in order], vals, height=0.62, color=SERIES[0])
for i, c in enumerate(order):
    ax.text(vals[i] + 0.5, i, f"{vals[i]:.0f}%   {cl[c]['lodging_listings']:,} → {cl[c]['canonical_entities']:,}", va="center", color=INK2, fontsize=11.5)
ax.set_xlim(0, max(vals) * 1.55); ax.grid(axis="y", visible=False); ax.set_xlabel("fewer hotel cards after merging four sources")
ax.set_title("Lodging listings → canonical hotels")
save(fig, "canonical_reduction")

# F7 precision-recall, three held-out cities
fig, ax = plt.subplots(figsize=(8.2, 4.3))
for i, c in enumerate(CORE):
    pr = cm["per_city"][c]["pr"]
    ax.plot(pr["recall"], pr["precision"], color=SERIES[i], label=f"{c.title()} held out")
    ax.scatter([fair[c]["rule_recall"]], [fair[c]["rule_precision"]], s=70, color=SERIES[i], edgecolor="#fcfcfb", linewidth=2, zorder=3)
ax.annotate("dots: the name + distance rule", (fair["bangkok"]["rule_recall"], fair["bangkok"]["rule_precision"]), textcoords="offset points",
            xytext=(12, -18), color=INK2, fontsize=11.5)
ax.set_xlabel("recall"); ax.set_ylabel("precision"); ax.set_xlim(0.2, 1.0); ax.set_ylim(0.85, 1.003)
ax.set_title("Precision vs recall on unseen cities"); ax.legend(loc="lower left")
save(fig, "pr_core_cities")

# ============================================================================ numbers the deck and script quote
numbers = {
    "data": {"cities": 12, "sources": 4, "lodging_listings": cs["listings"]["lodging"], "attraction_listings": cs["listings"]["attraction"],
             "listings_total": cs["listings"]["lodging"] + cs["listings"]["attraction"], "key_linked_pairs": cs["key_pairs"]["total"],
             "largest_hub_phone_listings": cs["hub_phones"]["largest_hub"]},
    "matching": {"truth": "weak labels from independent keys (Wikidata QID, rare phone / URL); not hand-labelled", "records": cm["records"],
                 "candidate_pairs": cm["candidates"], "labelled_matches": cm["labels"]["positive"], "labelled_non_matches": cm["labels"]["negative"],
                 "auc_unseen_city": cm["pooled"]["auc"], "recall_at_99_precision": cm["pooled"]["recall@p0.99"],
                 "blocking_recall": cm["blocking"]["recall_union"], "candidates_per_record": cm["blocking"]["candidates_per_record"],
                 "fair_comparison": fair, "cascade_shares": {n: s for n, s, _ in parts},
                 "dubai": cl["dubai"], "paris": cl["paris"]},
    "fsq_benchmark": {"truth": "competition labels (research only)", "records": fsq["records"], "test_records": t["blocking"]["records"],
                      "model_iou": t["cluster"]["iou"], "best_rule_iou": max(v["cluster_iou"] for v in t["baselines"].values()),
                      "b3_f1": t["cluster"]["b3_f1"], "blocking_ceiling_iou": t["blocking_ceiling"]["cluster_iou"]},
    "ota_transfer": {"truth": "none: counts only, label sheet prepared", "makemytrip": ota["records"]["makemytrip"], "goibibo": ota["records"]["goibibo"],
                     "accepted_pairs": ota["accepted_pairs"], "goibibo_with_twin": ota["goibibo_with_accepted_twin"],
                     "missed_by_naive_rule": ota["accepted_not_found_by_naive_rule"], "naive_pairs_not_accepted": ota["naive_rule_pairs_not_accepted"],
                     "median_dist_m": ota["accepted_median_dist_m"]},
    "rooms": {"truth": "real hotel room lists; second supplier simulated by rewrite rules", "hotels": rooms["benchmark"]["hotels"],
              "rooms": rooms["benchmark"]["rooms"], "renamed_strings": rooms["benchmark"]["rooms"] * len(rooms["benchmark"]["styles"]),
              "parser_coverage": meth["attribute parser (canon.rooms)"]["coverage"], "parser_precision": meth["attribute parser (canon.rooms)"]["precision"],
              "best_fuzzy_coverage": max(v["coverage"] for k, v in meth.items() if k.startswith("fuzzy")),
              "strings_for_90pct_bookings": 285, "real_strings": rooms["real_strings"]},
    "sightseeing": {"truth": "real Klook Singapore products; second supplier simulated; in-sample", "products": acts["products"], "pairs": acts["synthetic_pairs"],
                    "accuracy": acts["accuracy"], "macro_f1": acts["macro_f1"], "dedup_merges_variants": dd["VARIANT_OF"], "dedup_merges_combos": dd["INCLUDES"]},
}
sys.path.insert(0, str(ROOT / "scripts" / "figures"))
from v2_numbers import add_v2  # noqa: E402  (20 Nov upgrades, new keys only)

numbers = add_v2(numbers)
(ROOT / "submission" / "round1" / "numbers.json").write_text(json.dumps(numbers, indent=1), encoding="utf-8")

# crop of the demo's Match tab (map + evidence panel) for the cover slide; needs scripts/demo/screenshots.ps1 to have run
scr = ROOT / "submission" / "round1" / "screens" / "match.png"
if scr.exists():
    from PIL import Image
    im = Image.open(scr)
    k = im.size[0] / 1600  # screenshots are taken at 1600 px wide times a device scale factor
    im.crop(tuple(int(v * k) for v in (78, 345, 1522, 965))).save(OUT / "demo_match_crop.png")
    # the evidence panel alone (Atlantis, The Palm: listings and why they were merged), inset on the v3 deck's thank-you slide
    im.crop(tuple(int(v * k) for v in (1056, 350, 1515, 956))).save(OUT / "demo_match_evidence_crop.png", optimize=True)
print("figures:", sorted(p.name for p in OUT.glob("*.png")))
