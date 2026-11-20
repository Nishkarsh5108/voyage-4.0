"""Report for the sightseeing model stage: rules (canon/activities.py) vs an open LLM vs cascades, on held-out phrasings.

Reads the Kaggle kernel output kaggle/activities_llm/output/predictions_{insample,heldout}.csv (Qwen2.5-7B-Instruct letter
log-probabilities per pair) and the rules' answers stored with them.

Why the policy is chosen here and not in the kernel: the kernel picked its cascade on the in-sample set, where the rules were
tuned and so look better than they are; it chose to trust the rules almost everywhere. Here the held-out set is split by
original product into two halves: a policy is chosen on one half and scored on the other, both ways round, and the two
scores are averaged. No pair is scored by a policy chosen on it.

Output: reports/models/activities_llm.{md,json}
Usage : .venv\\Scripts\\python.exe -I -X utf8 scripts\\train\\activities_llm_report.py
"""
import json
import zlib
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
KO = ROOT / "kaggle" / "activities_llm" / "output"
REP = ROOT / "reports" / "models"
LABELS = ["SAME_AS", "VARIANT_OF", "INCLUDES", "DIFFERENT"]
km = json.loads((KO / "metrics_llm.json").read_text())


def metrics(truth, pred):
    truth, pred = np.asarray(truth), np.asarray(pred)
    f1 = {}
    for lab in LABELS:
        tp, fp, fn = ((pred == lab) & (truth == lab)).sum(), ((pred == lab) & (truth != lab)).sum(), ((pred != lab) & (truth == lab)).sum()
        p, r = tp / max(tp + fp, 1), tp / max(tp + fn, 1)
        f1[lab] = float(2 * p * r / max(p + r, 1e-9))
    return {"accuracy": float((truth == pred).mean()), "macro_f1": float(np.mean(list(f1.values()))), "f1": f1}


def policy(df, name, thr):
    rules, llm, conf = df["rules_pred"].to_numpy(), df["llm_pred"].to_numpy(), df["llm_conf"].to_numpy()
    if name == "rules":
        return rules
    if name == "llm":
        return llm
    if name == "llm when confident, else rules":
        return np.where(conf >= thr, llm, rules)
    if name == "rules decide attraction sets, LLM decides same vs variant":
        sets = np.isin(rules, ["INCLUDES", "DIFFERENT"])
        return np.where(sets & (conf < thr), rules, llm)
    raise ValueError(name)


POLICIES = [("rules", 0.0), ("llm", 0.0)] + [(p, t) for p in ("llm when confident, else rules", "rules decide attraction sets, LLM decides same vs variant")
                                              for t in (0.5, 0.6, 0.7, 0.8, 0.9, 0.95, 0.99, 1.01)]
H = pd.read_csv(KO / "predictions_heldout.csv")
I = pd.read_csv(KO / "predictions_insample.csv")
H["half"] = H["a"].map(lambda s: zlib.crc32(s.encode()) % 2)
res = {"model": km["model"], "pairs_heldout": len(H), "products": int(H["a"].nunique()), "folds": {}}
cascade_pred = np.empty(len(H), dtype=object)
for dev in (0, 1):
    D, T = H[H["half"] == dev], H[H["half"] != dev]
    scores = {f"{p}@{t}": metrics(D["truth"], policy(D, p, t))["macro_f1"] for p, t in POLICIES if p not in ("rules", "llm")}
    best = max(scores, key=scores.get)
    p, t = best.rsplit("@", 1)
    cascade_pred[T.index.to_numpy()] = policy(T, p, float(t))
    res["folds"][f"chosen_on_half_{dev}"] = {"policy": p, "threshold": float(t), "dev_macro_f1": scores[best]}
res["heldout"] = {"rules": metrics(H["truth"], H["rules_pred"]), "llm": metrics(H["truth"], H["llm_pred"]),
                  "cascade_cross_fitted": metrics(H["truth"], cascade_pred)}
res["insample"] = {"rules": metrics(I["truth"], I["rules_pred"]), "llm": metrics(I["truth"], I["llm_pred"])}
H["cascade"] = cascade_pred
H["template"] = H["template"].fillna("")
res["heldout_by_template"] = {f"{t}/{w}": {"n": int(len(g)), "rules": float((g["rules_pred"] == t).mean()), "llm": float((g["llm_pred"] == t).mean()),
                                         "cascade": float((g["cascade"] == t).mean())} for (t, w), g in H.groupby(["truth", "template"])}
(REP / "activities_llm.json").write_text(json.dumps(res, indent=1), encoding="utf-8")


def pc(v):
    return f"{v:.1%}"


hr, hl, hc = res["heldout"]["rules"], res["heldout"]["llm"], res["heldout"]["cascade_cross_fitted"]
L = ["# Sightseeing typed relations: model stage (open LLM) on held-out phrasings", "",
     f"Kaggle kernel `canon-activities-llm` (`kaggle/activities_llm/relate_llm.py`) scores every pair with **{km['model']}** (Apache-2.0, fp16 on two T4s), "
     "zero-shot with four in-sample examples, reading the probability of each answer letter (no free text, deterministic). "
     "This script (`scripts/train/activities_llm_report.py`) compares it with the rules on the held-out set of `activities_heldout.md`: "
     f"{len(H):,} pairs over {H['a'].nunique()} real Klook products, second supplier simulated with templates written after the rules were frozen.", "",
     "| Method | Held-out accuracy | Held-out macro-F1 | In-sample accuracy |", "|---|---:|---:|---:|",
     f"| Rules (`canon/activities.py`) | {pc(hr['accuracy'])} | {hr['macro_f1']:.3f} | {pc(res['insample']['rules']['accuracy'])} (tuned on it) |",
     f"| LLM alone | {pc(hl['accuracy'])} | {hl['macro_f1']:.3f} | {pc(res['insample']['llm']['accuracy'])} |",
     f"| Cascade, policy cross-fitted on held-out halves | **{pc(hc['accuracy'])}** | **{hc['macro_f1']:.3f}** | — |", "",
     "The cascade's policy and threshold are chosen on one half of the held-out products and scored on the other, both ways round:", ""]
L += [f"- chosen on half {k[-1]}: {v['policy']} (confidence threshold {v['threshold']})" for k, v in res["folds"].items()]
L += ["", "Share right by template family (held out):", "", "| Truth / template | Pairs | Rules | LLM | Cascade |", "|---|---:|---:|---:|---:|"]
L += [f"| {k} | {v['n']} | {pc(v['rules'])} | {pc(v['llm'])} | {pc(v['cascade'])} |" for k, v in res["heldout_by_template"].items()]
L += ["", "## Reading the numbers", "",
      "- The rules are precise where their lexicon has the word (attraction sets from the open-data gazetteer, meals) and blind where it does not "
      "(\"private tour\", \"guided tour\", new marketing noise). The LLM reads phrasing it has never seen but is looser on some attribute words. "
      "The cascade keeps the gazetteer's set logic and lets the model judge what the lexicon cannot.",
      "- The kernel's own cascade was chosen on the in-sample set, where the rules were tuned; it trusted the rules and scored "
      f"{pc(km['heldout']['cascade']['accuracy'])} held out. That number is in `kaggle/activities_llm/output/metrics_llm.json` and is not used.",
      "- Synthetic second supplier: this measures robustness to unseen phrasings, not accuracy on a live feed. Cost: one forward pass per pair "
      f"for {len(H) + len(I):,} pairs took about {km['seconds'] / 60:.0f} minutes including the model download; in the cascade only pairs the rules "
      "cannot settle need it."]
(REP / "activities_llm.md").write_text("\n".join(L) + "\n", encoding="utf-8")
print(json.dumps({"rules": hr["accuracy"], "llm": hl["accuracy"], "cascade": hc["accuracy"], "folds": res["folds"]}, indent=1))
