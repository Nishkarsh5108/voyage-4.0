"""City matcher, third stage: a multilingual cross-encoder, evaluated leave-cities-out, stacked on the stage-2 score.

Data (Kaggle dataset nishkarshsinghal/canon-city-pairs, built by scripts/train/city_xenc_data.py): the labelled candidate
pairs of the 12-city open-data benchmark (weak labels from Wikidata QID / rare phone / URL), their out-of-city stage-1 score
and the nested stage-2 score, and one text per record (name, alternate names, kind and category, street). Phone, website
and QID never reach the cross-encoder.

Protocol: the 12 cities form 3 folds of 4. For each fold, xlm-roberta-base is fine-tuned on the pairs of the 8 other cities
(the uncertain band of stage 2 plus half of the rest) and scores every labelled pair of the fold's cities. A small stacker
(LightGBM on stage-2 score, cross-encoder logit, stage-1 score, distance) is then fitted the same way, fold by fold.
Every reported number is on cities that neither the cross-encoder nor the stacker trained on.
Outputs: metrics_city_xenc.json, city_matcher_xenc.md (the report), xenc_scores.parquet
"""
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

T0 = time.time()
FOLDS = [["dubai", "delhi", "london", "barcelona"], ["bangkok", "mumbai", "paris", "vienna"], ["singapore", "goa", "amsterdam", "milan"]]
CITY_ORDER = ["dubai", "bangkok", "singapore", "delhi", "mumbai", "goa", "london", "paris", "amsterdam", "barcelona", "vienna", "milan"]
BASE, MAX_LEN, BATCH, LR, EPOCHS, SEED = "xlm-roberta-base", 96, 32, 2e-5, 2, 7
LO, HI = 0.01, 0.99
SMOKE = os.environ.get("CANON_SMOKE") == "1"


def log(m):
    print(f"[{time.time() - T0:6.0f}s] {m}", flush=True)


def find_in():
    hits = list(Path("/kaggle/input").rglob("pairs.parquet")) if Path("/kaggle/input").exists() else []
    return hits[0].parent if hits else Path("data/interim/kaggle_city_pairs")


IN = find_in()
OUT = Path("/kaggle/working") if Path("/kaggle/working").exists() else Path("data/interim/city_xenc_out")
OUT.mkdir(parents=True, exist_ok=True)


def texts(P, R):
    t = R.set_index("rid")["text"]
    d = P["dist_m"].to_numpy()
    ds = np.where(d < 1000, (np.round(d / 10) * 10).astype(int).astype(str) + " m", (np.round(d / 100) / 10).astype(str) + " km")
    return [f"{x} ; {a}" for x, a in zip(ds, t.reindex(P["ra"]).fillna("").to_numpy())], [str(b) for b in t.reindex(P["rb"]).fillna("").to_numpy()]


def worker(k, dev):
    import torch
    from transformers import AutoModelForSequenceClassification, AutoTokenizer, get_linear_schedule_with_warmup
    torch.manual_seed(SEED)
    rng = np.random.default_rng(SEED + k)
    P, R = pd.read_parquet(IN / "pairs.parquet"), pd.read_parquet(IN / "records.parquet")
    te = P["city"].isin(FOLDS[k]).to_numpy()
    band = ((P["p2"] >= LO) & (P["p2"] <= HI)).to_numpy()
    tr = ~te & (band | (rng.random(len(P)) < 0.5))
    PT, PS = P[tr].reset_index(drop=True), P[te]
    if SMOKE:
        PT, PS = PT.sample(2000, random_state=SEED), PS.iloc[:2000]
    tok = AutoTokenizer.from_pretrained(BASE)
    model = AutoModelForSequenceClassification.from_pretrained(BASE, num_labels=1).to(dev)
    a, b = texts(PT, R)
    enc = tok(a, b, truncation="longest_first", max_length=MAX_LEN)
    y = PT["y"].to_numpy().astype(np.float32)
    print(f"[fold {k}] train {len(PT):,} pairs ({y.mean():.3f} matches) on {sorted(set(CITY_ORDER) - set(FOLDS[k]))}; score {len(PS):,}", flush=True)

    def batch(ids, e):
        b_ = tok.pad([{"input_ids": e["input_ids"][i], "attention_mask": e["attention_mask"][i]} for i in ids], return_tensors="pt")
        return {kk: v.to(dev) for kk, v in b_.items()}

    opt = torch.optim.AdamW(model.parameters(), lr=LR, weight_decay=0.01)
    steps = EPOCHS * (len(PT) // BATCH)
    sch = get_linear_schedule_with_warmup(opt, int(0.06 * steps), max(steps, 1))
    scaler = torch.amp.GradScaler("cuda", enabled=dev.startswith("cuda"))
    lossf = torch.nn.BCEWithLogitsLoss()
    model.train()
    step, t0 = 0, time.time()
    for ep in range(EPOCHS):
        perm = rng.permutation(len(PT))
        for s in range(0, len(PT) - BATCH + 1, BATCH):
            ids = perm[s:s + BATCH]
            with torch.autocast(device_type="cuda", dtype=torch.float16, enabled=dev.startswith("cuda")):
                logit = model(**batch(ids, enc)).logits.squeeze(-1)
            loss = lossf(logit.float(), torch.from_numpy(y[ids]).to(dev))
            opt.zero_grad(set_to_none=True)
            scaler.scale(loss).backward()
            scaler.unscale_(opt)
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            scaler.step(opt)
            scaler.update()
            sch.step()
            step += 1
            if step % 1000 == 0:
                print(f"[fold {k}] step {step}/{steps} loss {loss.item():.4f} {(time.time() - t0) / step:.3f}s/step", flush=True)
    a, b = texts(PS, R)
    enc = tok(a, b, truncation="longest_first", max_length=MAX_LEN)
    order = np.argsort([len(x) for x in enc["input_ids"]])
    out = np.zeros(len(PS), np.float32)
    model.eval()
    with torch.no_grad(), torch.autocast(device_type="cuda", dtype=torch.float16, enabled=dev.startswith("cuda")):
        for s in range(0, len(order), 256):
            ids = order[s:s + 256]
            out[ids] = model(**batch(ids, enc)).logits.squeeze(-1).float().cpu().numpy()
    pd.DataFrame({"idx": PS.index.to_numpy(), "xenc_logit": out}).to_parquet(OUT / f"xenc_fold{k}.parquet", index=False)
    print(f"[fold {k}] done in {(time.time() - t0) / 60:.1f} min", flush=True)


def run_folds(folds, dev):
    for k in folds:
        worker(k, dev)

# ---------------------------------------------------------------------------- main
import multiprocessing as mp  # noqa: E402

import lightgbm as lgb  # noqa: E402
from sklearn.metrics import average_precision_score, precision_recall_curve, roc_auc_score  # noqa: E402


def gpu_count():
    """Counted with nvidia-smi so the parent never initialises CUDA before forking the workers."""
    try:
        return sum(1 for ln in subprocess.run(["nvidia-smi", "-L"], capture_output=True, text=True).stdout.splitlines() if ln.startswith("GPU"))
    except OSError:
        return 0


ngpu = gpu_count()
log(f"gpus={ngpu} input={IN}")
if ngpu >= 2 and os.name != "nt":
    ctx = mp.get_context("fork")
    procs = [ctx.Process(target=run_folds, args=(f, f"cuda:{g}")) for g, f in {0: [0, 2], 1: [1]}.items()]
    for p_ in procs:
        p_.start()
    for p_ in procs:
        p_.join()
        if p_.exitcode != 0:
            raise SystemExit("a worker failed")
else:
    run_folds([0, 1, 2], "cuda:0" if ngpu else "cpu")
log("cross-encoders done")

P = pd.read_parquet(IN / "pairs.parquet")
X = pd.concat([pd.read_parquet(OUT / f"xenc_fold{k}.parquet") for k in range(3)])
P["xenc_logit"] = np.nan
P.loc[X["idx"].to_numpy(), "xenc_logit"] = X["xenc_logit"].to_numpy()
P = P[P["xenc_logit"].notna()].reset_index(drop=True)
fold_of = {c: k for k, cs in enumerate(FOLDS) for c in cs}
P["fold"] = P["city"].map(fold_of)
SF = ["p2", "xenc_logit", "p1", "dist_m"]
P["p3"] = np.nan
for k in range(3):
    tr, te = P["fold"] != k, P["fold"] == k
    va = tr & (P["fold"] == (k + 1) % 3)
    tr2 = tr & ~va
    m = lgb.train(dict(objective="binary", learning_rate=0.05, num_leaves=31, min_data_in_leaf=100, verbose=-1, seed=SEED),
                  lgb.Dataset(P.loc[tr2, SF], P.loc[tr2, "y"]), 2000, valid_sets=[lgb.Dataset(P.loc[va, SF], P.loc[va, "y"])],
                  callbacks=[lgb.early_stopping(100, verbose=False)])
    P.loc[te, "p3"] = m.predict(P.loc[te, SF], num_iteration=m.best_iteration)


def scores(y, p):
    prec, rec, _ = precision_recall_curve(y, p)
    r = {"auc": float(roc_auc_score(y, p)), "ap": float(average_precision_score(y, p))}
    for t in (0.99, 0.995):
        ok = np.where(prec[:-1] >= t)[0]
        r[f"recall@p{t}"] = float(rec[ok[0]]) if len(ok) else 0.0
    ok = np.where(rec[:-1] >= 0.95)[0]
    r["precision@r0.95"] = float(prec[ok[-1]]) if len(ok) else 0.0
    return r


cols = {"stage 1 (pair model)": "p1", "stage 2 (+ collective)": "p2", "cross-encoder alone": "xenc_logit", "stage 3 (stage 2 + cross-encoder)": "p3"}
res = {"base_model": BASE, "folds": FOLDS, "pairs": len(P), "pooled": {k: scores(P["y"], P[c]) for k, c in cols.items()},
       "band": {k: scores(P.loc[(P["p2"] >= LO) & (P["p2"] <= HI), "y"], P.loc[(P["p2"] >= LO) & (P["p2"] <= HI), c]) for k, c in cols.items()},
       "band_pairs": int(((P["p2"] >= LO) & (P["p2"] <= HI)).sum()),
       "per_city": {c: {k: scores(g["y"], g[col])["ap"] for k, col in cols.items()} for c, g in P.groupby("city")}, "seconds": time.time() - T0}
(OUT / "metrics_city_xenc.json").write_text(json.dumps(res, indent=1))
P[["ra", "rb", "city", "y", "p1", "p2", "xenc_logit", "p3"]].to_parquet(OUT / "xenc_scores.parquet", index=False)


def pc(v):
    return f"{v:.1%}"


L = ["# City matcher, stage 3: multilingual cross-encoder on the 12-city benchmark", "",
     f"Kaggle kernel `canon-city-xenc` (`kaggle/city_xenc/city_xenc.py`), {BASE} fine-tuned on T4 GPUs. Same **weak labels** as "
     "`city_matcher.md`. The cross-encoder reads both records as text (name, alternate names, kind and category, street, and the distance); "
     "phone, website and Wikidata QID never reach it because they define the labels.", "",
     "Protocol: three folds of four cities " + "; ".join("/".join(f) for f in FOLDS) + ". Each fold's cities are scored by a cross-encoder and a "
     "stacker trained only on the other eight cities, and stage 2's scores are the nested out-of-city scores of `city_matcher_stage2.md`.", "",
     "## All labelled pairs, pooled over held-out cities", "", "| Model | AUC | Average precision | Recall at 99% precision | Recall at 99.5% precision | Precision at 95% recall |",
     "|---|---:|---:|---:|---:|---:|"]
for k, v in res["pooled"].items():
    L.append(f"| {k} | {v['auc']:.4f} | {v['ap']:.4f} | {pc(v['recall@p0.99'])} | {pc(v['recall@p0.995'])} | {pc(v['precision@r0.95'])} |")
L += ["", f"## Inside stage 2's uncertain band ({LO} <= p <= {HI}, {res['band_pairs']:,} labelled pairs)", "",
      "| Model | AUC | Average precision |", "|---|---:|---:|"]
L += [f"| {k} | {v['auc']:.4f} | {v['ap']:.4f} |" for k, v in res["band"].items()]
L += ["", "## Average precision per held-out city", "", "| City | " + " | ".join(cols) + " |", "|---|" + "---:|" * len(cols)]
L += [f"| {c} | " + " | ".join(f"{res['per_city'][c][k]:.4f}" for k in cols) + " |" for c in CITY_ORDER if c in res["per_city"]]
L += ["", "Weak labels carry the noise described in `city_matcher_stage2.md` (duplicate Wikidata items of one place), which caps the top of the ranking."]
(OUT / "city_matcher_xenc.md").write_text("\n".join(L) + "\n", encoding="utf-8")
log(json.dumps({k: {m: round(v, 4) for m, v in d.items()} for k, d in res["pooled"].items()}))
log("done")
