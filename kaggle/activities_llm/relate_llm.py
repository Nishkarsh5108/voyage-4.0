"""Sightseeing typed relations, model stage: a zero-shot open LLM judges SAME_AS / VARIANT_OF / INCLUDES / DIFFERENT.

Inputs (Kaggle dataset nishkarshsinghal/canon-activity-pairs, written by scripts/train/activities_benchmark.py and
activities_heldout.py): every pair with its truth and the rules' answer (canon/activities.py), for
  * the in-sample set (the rules were tuned on it), used here to choose the prompt and the cascade policy, and
  * the held-out set (new templates written after the rules were frozen), scored once.
The LLM sees only the two product titles. It answers with one letter and is read as the probability of each letter
(no free-text generation), so the run is deterministic. Few-shot examples come from the in-sample set only.

Model: Qwen2.5-7B-Instruct (Apache-2.0), fp16 over two T4s; falls back to Qwen2.5-3B-Instruct if the 7B output is not finite.
Output: metrics_llm.json, predictions_{insample,heldout}.csv
"""
import json
import time
from pathlib import Path

import numpy as np
import pandas as pd
import torch
from transformers import AutoModelForCausalLM, AutoTokenizer

T0 = time.time()
hits = list(Path("/kaggle/input").rglob("activity_pairs_heldout.csv"))
IN = hits[0].parent if hits else Path("data/interim")
OUT = Path("/kaggle/working") if Path("/kaggle/working").exists() else Path("data/interim/activities_llm")
OUT.mkdir(parents=True, exist_ok=True)
LABELS = ["SAME_AS", "VARIANT_OF", "INCLUDES", "DIFFERENT"]
LETTER = dict(zip("ABCD", LABELS))


def log(m):
    print(f"[{time.time() - T0:6.0f}s] {m}", flush=True)


SYSTEM = (
    "You reconcile tour and attraction products that two travel suppliers list under different names. "
    "Given product X from supplier 1 and product Y from supplier 2, say how Y relates to X:\n"
    "A = SAME_AS: the same product. Only the wording differs: tags such as [Best Seller], marketing or booking notes "
    "(instant confirmation, mobile voucher, e-ticket, open date), ticket/admission/entry/pass wording, word order, case, the city name.\n"
    "B = VARIANT_OF: the same attraction and experience, but one bookable option differs: hotel pickup or transfers, a meal, "
    "a child, senior or other age ticket, skip-the-line or fast-track or express access, private instead of shared, a guide or "
    "audio guide, a time slot or session, a class or tier.\n"
    "C = INCLUDES: one of the two is a combo, bundle or package that contains the other product plus at least one other "
    "attraction or product.\n"
    "D = DIFFERENT: a different attraction or experience.\n"
    "Answer with a single letter: A, B, C or D."
)


def user_msg(a, b):
    return f"X: {a}\nY: {b}\nAnswer:"


def fewshot(df):
    """One in-sample example per relation, fixed by position so the prompt is reproducible."""
    shots = []
    for lab in LABELS:
        r = df[df["truth"] == lab].iloc[3]
        shots += [{"role": "user", "content": user_msg(r["a"], r["b"])}, {"role": "assistant", "content": "ABCD"[LABELS.index(lab)]}]
    return shots


def score(model, tok, df, shots, bs=8):
    letter_ids = [tok.encode(x, add_special_tokens=False)[0] for x in "ABCD"]
    prompts = [tok.apply_chat_template([{"role": "system", "content": SYSTEM}] + shots + [{"role": "user", "content": user_msg(a, b)}],
                                       tokenize=False, add_generation_prompt=True) for a, b in zip(df["a"], df["b"])]
    out = np.zeros((len(df), 4), np.float32)
    tok.padding_side = "left"
    with torch.no_grad():
        for s in range(0, len(prompts), bs):
            enc = tok(prompts[s:s + bs], return_tensors="pt", padding=True).to(model.device)
            logits = model(**enc).logits[:, -1, :].float()
            out[s:s + bs] = torch.log_softmax(logits[:, letter_ids], dim=-1).cpu().numpy()
    return out


def metrics(truth, pred):
    truth, pred = np.asarray(truth), np.asarray(pred)
    f1 = {}
    for lab in LABELS:
        tp = int(((pred == lab) & (truth == lab)).sum())
        fp = int(((pred == lab) & (truth != lab)).sum())
        fn = int(((pred != lab) & (truth == lab)).sum())
        p, r = tp / max(tp + fp, 1), tp / max(tp + fn, 1)
        f1[lab] = 2 * p * r / max(p + r, 1e-9)
    return {"accuracy": float((truth == pred).mean()), "macro_f1": float(np.mean(list(f1.values()))), "f1": f1}


sets = {k: pd.read_csv(IN / f"activity_pairs_{k}.csv") for k in ("insample", "heldout")}
shots = fewshot(sets["insample"])
model_used, res = None, {}
for name in ("Qwen/Qwen2.5-7B-Instruct", "Qwen/Qwen2.5-3B-Instruct"):
    log(f"loading {name}")
    tok = AutoTokenizer.from_pretrained(name)
    if tok.pad_token is None:
        tok.pad_token = tok.eos_token
    dtype = torch.float16 if "7B" in name else torch.float32
    model = AutoModelForCausalLM.from_pretrained(name, torch_dtype=dtype, device_map="auto").eval()
    lp = {k: score(model, tok, df, shots) for k, df in sets.items()}
    if all(np.isfinite(v).all() for v in lp.values()):
        model_used = name
        break
    log(f"{name}: non-finite scores, trying the next model")
    del model
    torch.cuda.empty_cache()
log(f"scored with {model_used}")

for k, df in sets.items():
    df["llm_pred"] = [LABELS[i] for i in lp[k].argmax(1)]
    df["llm_conf"] = np.exp(lp[k].max(1))
    for j, lab in enumerate(LABELS):
        df[f"llm_lp_{lab}"] = lp[k][:, j]
    df.to_csv(OUT / f"predictions_{k}.csv", index=False)


# cascade policies, chosen on the in-sample set only
def policy(df, name, thr):
    rules, llm, conf = df["rules_pred"].to_numpy(), df["llm_pred"].to_numpy(), df["llm_conf"].to_numpy()
    if name == "rules":
        return rules
    if name == "llm":
        return llm
    if name == "llm_when_confident":       # the LLM overrides the rules when it is sure
        return np.where(conf >= thr, llm, rules)
    if name == "llm_on_same_or_variant":   # the rules decide the attraction sets; the LLM decides SAME vs VARIANT
        sv = np.isin(rules, ["SAME_AS", "VARIANT_OF"]) & np.isin(llm, ["SAME_AS", "VARIANT_OF"])
        return np.where(sv & (conf >= thr), llm, rules)
    raise ValueError(name)


cands = [("rules", 0.0), ("llm", 0.0)] + [(p, t) for p in ("llm_when_confident", "llm_on_same_or_variant") for t in (0.5, 0.6, 0.7, 0.8, 0.9, 0.95)]
ins = {f"{p}@{t}": metrics(sets["insample"]["truth"], policy(sets["insample"], p, t))["macro_f1"] for p, t in cands}
best = max([c for c in cands if c[0] not in ("rules", "llm")], key=lambda c: ins[f"{c[0]}@{c[1]}"])
res = {"model": model_used, "fewshot_from": "insample", "policies_insample_macro_f1": ins, "chosen_cascade": {"policy": best[0], "threshold": best[1]}}
for k, df in sets.items():
    res[k] = {"rules": metrics(df["truth"], policy(df, "rules", 0)), "llm": metrics(df["truth"], policy(df, "llm", 0)),
              "cascade": metrics(df["truth"], policy(df, *best))}
    res[k]["by_template"] = {}
    casc = policy(df, *best)
    for (t, w), g in df.groupby(["truth", "template"]):
        ix = g.index.to_numpy()
        res[k]["by_template"][f"{t}/{w}"] = {"n": int(len(g)), "rules": float((g["rules_pred"] == t).mean()),
                                            "llm": float((g["llm_pred"] == t).mean()), "cascade": float((casc[ix] == t).mean())}
    log(f"{k}: " + json.dumps({m: round(v["accuracy"], 4) for m, v in res[k].items() if m != "by_template"}))
res["seconds"] = time.time() - T0
(OUT / "metrics_llm.json").write_text(json.dumps(res, indent=1))
log("done")
