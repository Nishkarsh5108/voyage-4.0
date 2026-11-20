"""Write reports/models/fsq_v2.md from the Kaggle outputs of kaggle/fsq_v2 (stage 1) and kaggle/fsq_v2_xenc (stage 2).

Pull the outputs first:
    kaggle kernels output nishkarshsinghal/canon-fsq-v2-stage1 -p kaggle/fsq_v2/output
    kaggle kernels output nishkarshsinghal/canon-fsq-v2-xenc  -p kaggle/fsq_v2_xenc/output
Usage: .venv\\Scripts\\python.exe -I -X utf8 scripts\\train\\report_fsq_v2.py
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "figures"))
from v2_numbers import FSQ_FIRST_PLACE_CV  # noqa: E402

s1 = json.loads((ROOT / "kaggle" / "fsq_v2" / "output" / "metrics.json").read_text())
p2 = ROOT / "kaggle" / "fsq_v2_xenc" / "output" / "metrics_stage2.json"
s2 = json.loads(p2.read_text()) if p2.exists() else None
v1 = json.loads((ROOT / "kaggle" / "fsq_pair_model" / "output" / "metrics.json").read_text())
rA, rB = s1["retrieval"]["A"], s1["retrieval"]["B"]


def pc(v):
    return f"{v:.1%}"


def f4(v):
    return f"{v:.4f}"


rows = [("Rule: best of three name + distance rules (no training)", max(v["iou_cc_B"] for v in s1["rules"].values()), None, "cc"),
        ("v1 recipe at the same density (10 geo neighbours + exact name, 23 features)", s1["v1_recipe"]["list"]["iou_B"], s1["v1_recipe"]["auc_B"], "list"),
        ("v2 stage 1: encoder retrieval + ~60 pair features", s1["stage1"]["list"]["iou_B"], s1["stage1"]["auc_B"], "list"),
        ("v2 stage 2: + collective features (competing candidates, two-hop)", s1["stage2"]["list"]["iou_B"], s1["stage2"]["auc_B"], "list")]
if s2:
    k = s2["chosen_on_A"]
    rows.append((f"v2 + cross-encoder re-ranking ({s2['base_model']}, {k} chosen on A)", s2[k]["list"]["iou_B"], s2[k]["auc_B"], "list"))
best = max(r[1] for r in rows)

L = ["# Foursquare Location Matching, pipeline v2: retrieval, collective GBDT, cross-encoder", "",
     "Kaggle kernels `canon-fsq-v2-stage1` (`kaggle/fsq_v2/stage1.py`) and `canon-fsq-v2-xenc` (`kaggle/fsq_v2_xenc/stage2.py`), T4 GPUs. "
     "**Research benchmark only**: the data is under competition terms. Its job is to measure the matching method against a published "
     "state of the art on real labels; the shipped matcher is trained on open data only.", "",
     "## Protocol", "",
     f"- {s1['retrieval']['A']['records'] + rB['records']:,} records of {rA['places'] + rB['places']:,} places, split by place 50 / 50 into worlds A and B "
     f"({rB['records']:,} records in B, close to the competition's hidden test of about 600k). v1 used a 20% world, which has fewer near-duplicates "
     "per record and so flatters every method; the v1 recipe is re-run below at the new density so the comparison is like for like.",
     "- Everything is cross-fitted: the encoder that embeds world A is fine-tuned on world B's duplicates and the reverse, the GBDT trained on A scores B "
     "and the reverse. Thresholds are picked on A; **every headline number is world B**, which no model or threshold was tuned on.",
     "- Score: the competition metric, mean per-record IoU between the predicted match set (with itself) and the true set. Predicted sets are each record's "
     "accepted candidates plus two-hop neighbours through confident edges (thresholds picked on A); connected components are reported in the JSON.", "",
     "## Results on world B", "",
     "| Method | IoU | Pair AUC |", "|---|---:|---:|"]
for name, iou, auc, _ in rows:
    b = "**" if iou == best else ""
    L.append(f"| {name} | {b}{f4(iou)}{b} | {f4(auc) if auc else '—'} |")
L += [f"| Retrieval ceiling, every true candidate accepted, direct links only | {f4(rB['ceiling_list_iou_direct'])} | — |",
      f"| Retrieval ceiling, same, with transitive closure | {f4(rB['ceiling_cc_iou'])} | — |",
      f"| v1 retrieval ceiling at this density | {f4(rB['v1_ceiling_cc_iou'])} | — |", "",
      "Stability check, everything picked on B and scored on A: stage 2 IoU "
      f"{f4(s1['stage2']['swap']['list']['iou_A'])}" + (f", with the cross-encoder {f4(s2[s2['chosen_on_A']]['swap']['list']['iou_A'])}." if s2 else ".") , "",
      "## Against the published state of the art", "",
      "The 2022 competition had 1,079 teams. Leaderboard scores are inflated by a train/test overlap that participants found during the competition (top teams "
      "exploited it), so the comparable figures are the winners' own cross-validation scores on the training data:", "",
      "| | Published 1st place (CV) | This pipeline (world B) |", "|---|---:|---:|",
      f"| Retrieval max IoU | {FSQ_FIRST_PLACE_CV['retrieval_max_iou']} (about 40 candidates per record) | {f4(rB['ceiling_list_iou_direct'])} direct candidates only, "
      f"{f4(rB['ceiling_cc_iou'])} with transitive closure ({rB['candidates_per_record']:.1f} candidate pairs per record) |",
      f"| GBDT stage | {FSQ_FIRST_PLACE_CV['lightgbm_stage']} (LightGBM, ~120 features) | {f4(s1['stage2']['list']['iou_B'])} (XGBoost, two stages) |",
      f"| Transformer re-ranking, before post-processing | {FSQ_FIRST_PLACE_CV['transformer_ensemble']} (xlm-roberta-large + mdeberta-v3 + CatBoost) | not measured separately |",
      f"| Final, with post-processing | {FSQ_FIRST_PLACE_CV['with_post_processing']} (merge rule + xlm-roberta-large on new pairs) | "
      + (f"{f4(s2[s2['chosen_on_A']]['list']['iou_B'])} (one xlm-roberta-base cross-encoder, two-hop completion)" if s2 else "not run") + " |", "",
      "The CV splits are not identical (their folds, our 50/50 place split), so read the comparison as the same order of magnitude, not a ranking. "
      "Source: the 1st-place write-up (Kaggle discussion, team \"Re:waiwai\"), as reposted; the 7th-place write-up reports a 0.9778 retrieval ceiling.", "",
      "## Retrieval", "",
      "| | World A | World B |", "|---|---:|---:|"]
for k, lbl in (("records", "Records"), ("true_pairs", "True duplicate pairs"), ("candidates", "Candidate pairs"),
               ("candidates_per_record", "Candidates per record"), ("pair_recall", "Share of true pairs that are candidates"),
               ("ceiling_cc_iou", "Ceiling IoU"), ("v1_pair_recall", "v1 retrieval: share of true pairs"), ("v1_ceiling_cc_iou", "v1 retrieval: ceiling IoU")):
    a, b = rA[k], rB[k]
    fmt = (lambda v: f"{v:,}") if isinstance(a, int) else ((lambda v: f"{v:.2f}") if k == "candidates_per_record" else (pc if "recall" in k else f4))
    L.append(f"| {lbl} | {fmt(a)} | {fmt(b)} |")
L += ["", "True pairs found only by one generator (world B): " + ", ".join(f"{k} {v:,}" for k, v in rB["only_from_generator_true_pairs"].items())
      + ". `emb` is the fine-tuned encoder inside the 100-neighbour geo pool, `glob` the country-wide encoder search (within 100 km).", ""]
if s2:
    L += ["## Cross-encoder band", "", "| | World A | World B |", "|---|---:|---:|"]
    for k, lbl in (("pairs", "Pairs re-scored"), ("share_of_candidates", "Share of candidates"), ("auc_gbdt_in_band", "GBDT AUC inside the band"),
                   ("auc_xenc_in_band", "Cross-encoder AUC inside the band")):
        a, b = s2["band_A"][k], s2["band_B"][k]
        L.append(f"| {lbl} | {a:,} | {b:,} |" if isinstance(a, int) else f"| {lbl} | {f4(a) if 'auc' in k else pc(a)} | {f4(b) if 'auc' in k else pc(b)} |")
    L += [""]
L += ["## Feature importance, stage 2 trained on A (gain share, top 15)", "", "| Feature | Share |", "|---|---:|"]
L += [f"| {r['feature']} | {pc(r['gain_share'])} |" for r in s1["importance_stage2_trained_on_A"][:15]]
L += ["", "## Travel slices (world B, stage 2)", "", "| Slice (both records) | Pairs | Matches | AUC | Average precision |", "|---|---:|---:|---:|---:|"]
L += [f"| {k} | {v['pairs']:,} | {v['matches']:,} | {f4(v['auc'])} | {f4(v['ap'])} |" for k, v in s1["slices_B"].items()]
L += ["", "## What changed from v1, and what it bought", "",
      f"- v1 reported IoU {v1['test']['cluster']['iou']:.3f} on a 20% world. At competition density the same recipe scores {f4(s1['v1_recipe']['list']['iou_B'])}: "
      "the old figure was flattered by sparsity, not wrong. The v2 rows are measured at the harder density.",
      "- Retrieval is no longer the binding constraint: the fine-tuned encoder and the country-wide search lift the ceiling from "
      f"{f4(rB['v1_ceiling_cc_iou'])} to {f4(rB['ceiling_cc_iou'])}. (Encoder fine-tuning with in-batch negatives is the dense channel of the BER v7 "
      "entity-resolution pipeline built for the Amazon ML Challenge.)",
      f"- Increments on world B: retrieval and the richer pair features add {s1['stage1']['list']['iou_B'] - s1['v1_recipe']['list']['iou_B']:+.3f} IoU over the v1 recipe; "
      f"the collective stage (a pair judged together with each record's other candidates) adds {s1['stage2']['list']['iou_B'] - s1['stage1']['list']['iou_B']:+.3f}"
      + (f"; the cross-encoder adds {s2[s2['chosen_on_A']]['list']['iou_B'] - s1['stage2']['list']['iou_B']:+.3f}." if s2 else "."),
      f"- Run time: stage 1 {s1['seconds'] / 60:.0f} min on one T4" + (f", stage 2 {s2['seconds'] / 60:.0f} min on two T4s." if s2 else ".")]
(ROOT / "reports" / "models" / "fsq_v2.md").write_text("\n".join(L) + "\n", encoding="utf-8")
print("\n".join(L[:40]))
