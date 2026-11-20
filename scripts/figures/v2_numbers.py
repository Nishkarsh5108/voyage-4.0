"""Numbers from the 20 Nov model upgrades, added to submission/round1/numbers.json under new keys only.

Existing keys are never changed here, so the deck (scripts/deck) and the site's current bindings read what they read before.
round1_figures.py calls add_v2() before it writes numbers.json; running this file applies it to the existing numbers.json.
A source that has not been produced yet is skipped, not filled in.

Usage: .venv\\Scripts\\python.exe -I -X utf8 scripts\\figures\\v2_numbers.py
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REP = ROOT / "reports" / "models"

# Published reference: 1st-place write-up of Foursquare Location Matching (Kaggle 2022), cross-validation IoU per stage.
FSQ_FIRST_PLACE_CV = {"lightgbm_stage": 0.875, "transformer_ensemble": 0.911, "with_post_processing": 0.9166, "retrieval_max_iou": 0.979}


def _read(p):
    p = Path(p)
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def add_v2(numbers: dict) -> dict:
    s1 = _read(ROOT / "kaggle" / "fsq_v2" / "output" / "metrics.json")
    s2 = _read(ROOT / "kaggle" / "fsq_v2_xenc" / "output" / "metrics_stage2.json")
    if s1:
        rB = s1["retrieval"]["B"]
        d = {"truth": "competition labels (research only); places split 50/50, thresholds picked on world A, scores on world B",
             "records_per_world": rB["records"], "candidates_per_record": rB["candidates_per_record"],
             "retrieval_ceiling_iou": rB["ceiling_cc_iou"], "retrieval_ceiling_direct_iou": rB["ceiling_list_iou_direct"],
             "v1_retrieval_ceiling_iou": rB["v1_ceiling_cc_iou"],
             "v1_recipe_iou": s1["v1_recipe"]["list"]["iou_B"], "v2_pair_model_iou": s1["stage1"]["list"]["iou_B"],
             "v2_collective_iou": s1["stage2"]["list"]["iou_B"], "v2_collective_auc": s1["stage2"]["auc_B"],
             "best_rule_iou": max(v["iou_cc_B"] for v in s1["rules"].values()), "published_first_place_cv": FSQ_FIRST_PLACE_CV}
        if s2:
            k = s2["chosen_on_A"]
            d["v2_cross_encoder_iou"] = s2[k]["list"]["iou_B"]
            d["cross_encoder"] = s2["base_model"]
        d["v2_best_iou"] = max(v for k, v in d.items() if k.startswith("v2_") and k.endswith("_iou"))
        numbers["fsq_v2"] = d
    cs2 = _read(REP / "city_matcher_stage2.json")
    if cs2:
        a, b = cs2["pooled"]["stage1"], cs2["pooled"]["stage2"]
        pc = cs2["per_city"]
        numbers["matching_stage2"] = {
            "truth": "same weak labels and leave-one-city-out protocol as matching; nested so stage 2 never sees the held-out city",
            "auc": [a["auc"], b["auc"]], "average_precision": [a["ap"], b["ap"]], "recall_at_99_precision": [a["recall@p0.99"], b["recall@p0.99"]],
            "precision_at_95_recall": [a["precision@r0.95"], b["precision@r0.95"]],
            "cities_with_higher_ap": sum(1 for v in pc.values() if v["stage2"]["ap"] > v["stage1"]["ap"]), "cities": len(pc)}
        x3 = _read(ROOT / "kaggle" / "city_xenc" / "output" / "metrics_city_xenc.json")
        if x3:  # stage 3: xlm-roberta cross-encoder stacked on stage 2, leave-four-cities-out
            s3 = x3["pooled"]["stage 3 (stage 2 + cross-encoder)"]
            numbers["matching_stage2"].update({"stage3_model": x3["base_model"], "stage3_average_precision": s3["ap"], "stage3_auc": s3["auc"],
                                               "stage3_precision_at_95_recall": s3["precision@r0.95"], "stage3_recall_at_99_precision": s3["recall@p0.99"]})
    rs = _read(REP / "rooms_semantic.json")
    if rs:
        m = rs["methods"]
        emb = next((v for k, v in m.items() if k.startswith("intfloat/multilingual-e5-small, abstains")), None)
        casc = next((v for k, v in m.items() if k.startswith("parser, then multilingual-e5-small")), None)
        par = m.get("attribute parser (canon.rooms)")
        if emb and casc and par:
            numbers["rooms_semantic"] = {
                "truth": "same simulated second supplier as rooms; thresholds on 20% of hotels, scores on the other 80%",
                "parser_correct": par["test"]["correct_of_all"], "parser_precision": par["test"]["precision"],
                "embedding_correct": emb["test"]["correct_of_all"], "embedding_precision": emb["test"]["precision"],
                "cascade_correct": casc["test"]["correct_of_all"], "cascade_precision": casc["test"]["precision"]}
    ah = _read(REP / "activities_heldout.json")
    if ah:
        d = {"truth": "same real products; second supplier simulated with templates written after the rules were frozen",
             "pairs": ah["pairs"], "rules_accuracy": ah["accuracy"], "rules_macro_f1": ah["macro_f1"]}
        llm = _read(REP / "activities_llm.json")  # scripts/train/activities_llm_report.py: cascade policy cross-fitted on held-out halves
        if llm:
            h = llm["heldout"]
            d.update({"llm": llm["model"], "llm_accuracy": h["llm"]["accuracy"], "llm_macro_f1": h["llm"]["macro_f1"],
                      "cascade_accuracy": h["cascade_cross_fitted"]["accuracy"], "cascade_macro_f1": h["cascade_cross_fitted"]["macro_f1"]})
        numbers["sightseeing_heldout"] = d
    return numbers


if __name__ == "__main__":
    path = ROOT / "submission" / "round1" / "numbers.json"
    n = json.loads(path.read_text(encoding="utf-8"))
    before = {k: json.dumps(v, sort_keys=True) for k, v in n.items()}
    n = add_v2(n)
    changed = [k for k in before if json.dumps(n[k], sort_keys=True) != before[k] and k not in
               ("fsq_v2", "matching_stage2", "rooms_semantic", "sightseeing_heldout")]
    assert not changed, f"existing keys changed: {changed}"
    path.write_text(json.dumps(n, indent=1), encoding="utf-8")
    print("numbers.json keys:", list(n))
