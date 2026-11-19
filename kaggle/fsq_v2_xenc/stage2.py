"""Foursquare Location Matching, pipeline v2, stage 2: cross-encoder re-ranking of the uncertain band.

Input: the output of kaggle/fsq_v2/stage1.py (records_{A,B}.parquet, pairs_{A,B}.parquet with out-of-sample stage-2 GBDT
scores p2). A multilingual cross-encoder reads both records as text (name | categories | address, city, state, plus the
distance) and is fine-tuned on world A's uncertain pairs to score world B's, and the reverse, one direction per GPU.
The GBDT score and the cross-encoder score are then combined by a small stacker, cross-fitted the same way, and the
cluster score is computed with thresholds picked on world A and reported on world B (as in stage 1).

Kaggle (GPU T4 x2, internet on; stage-1 kernel attached as a kernel source):  python stage2.py
Local smoke test:  CANON_SMOKE=1 python -I stage2.py <stage-1 output dir> <out dir> intfloat/multilingual-e5-small
"""
import gc
import json
import os
import subprocess
import sys
import time
import zlib
from pathlib import Path

import numpy as np
import pandas as pd

T0 = time.time()


def log(msg: str) -> None:
    print(f"[{time.time() - T0:7.0f}s] {msg}", flush=True)


SMOKE = os.environ.get("CANON_SMOKE") == "1"
WORKER = len(sys.argv) > 1 and sys.argv[1] == "--worker"
if WORKER:
    _, _, IN, OUT, BASE, T, S, DEVICE = sys.argv
    IN, OUT = Path(IN), Path(OUT)
else:
    if len(sys.argv) > 1:
        IN = Path(sys.argv[1])
    else:
        hits = list(Path("/kaggle/input").rglob("pairs_A.parquet"))
        if not hits:
            raise SystemExit("no stage-1 output under /kaggle/input")
        IN = hits[0].parent
    OUT = Path(sys.argv[2]) if len(sys.argv) > 2 else Path("/kaggle/working")
    BASE = sys.argv[3] if len(sys.argv) > 3 else "xlm-roberta-base"
OUT.mkdir(parents=True, exist_ok=True)
LO, HI = 0.01, 0.99            # the band the cross-encoder re-scores; outside it the GBDT score stands
MAX_TRAIN = 4000 if SMOKE else 900_000
MAX_LEN, BATCH, LR, EPOCHS = 128, 32, 2e-5, 1
SEED = 7


def band(p):
    return (p >= LO) & (p <= HI)


def text_of(R: pd.DataFrame):
    def s(c):
        return R[c].fillna("").astype(str)
    loc = (s("address") + ", " + s("city") + ", " + s("state")).str.replace(r"(, )+", ", ", regex=True).str.strip(", ")
    return (s("name") + " | " + s("categories") + " | " + loc).to_numpy()


def pair_texts(k: str, P: pd.DataFrame):
    R = pd.read_parquet(IN / f"records_{k}.parquet")
    tx = text_of(R)
    d = P["dist_m"].to_numpy()
    dist_s = np.where(d < 1000, (np.round(d / 10) * 10).astype(int).astype(str) + " m", (np.round(d / 100) / 10).astype(str) + " km")
    ta, tb = tx[P["i"].to_numpy()], tx[P["j"].to_numpy()]
    return [f"{x} ; {t}" for x, t in zip(dist_s, ta)], [str(t) for t in tb]


# ============================================================================ worker: train on world T, score world S
if WORKER:
    import torch
    from transformers import AutoModelForSequenceClassification, AutoTokenizer, get_linear_schedule_with_warmup

    torch.manual_seed(SEED)
    rng = np.random.default_rng(SEED)
    PT, PS = pd.read_parquet(IN / f"pairs_{T}.parquet"), pd.read_parquet(IN / f"pairs_{S}.parquet")
    PT = PT[band(PT["p2"].to_numpy())].reset_index(drop=True)
    if len(PT) > MAX_TRAIN:
        PT = PT.sample(MAX_TRAIN, random_state=SEED).reset_index(drop=True)
    PS = PS[band(PS["p2"].to_numpy())]
    s_index = PS.index.to_numpy()
    PS = PS.reset_index(drop=True)
    if SMOKE:
        PS = PS.iloc[:3000]
        s_index = s_index[:3000]
    tok = AutoTokenizer.from_pretrained(BASE)
    model = AutoModelForSequenceClassification.from_pretrained(BASE, num_labels=1).to(DEVICE)
    aT, bT = pair_texts(T, PT)
    encT = tok(aT, bT, truncation="longest_first", max_length=MAX_LEN)
    yT = PT["y"].to_numpy().astype(np.float32)
    print(f"[{T}->{S}] train pairs {len(PT):,} (positives {yT.mean():.3f}), score pairs {len(PS):,}", flush=True)

    def collate(ids, enc, y=None):
        feats = [{"input_ids": enc["input_ids"][k], "attention_mask": enc["attention_mask"][k]} for k in ids]
        b = tok.pad(feats, return_tensors="pt")
        b = {k: v.to(DEVICE) for k, v in b.items()}
        return b, (torch.from_numpy(y[ids]).to(DEVICE) if y is not None else None)

    opt = torch.optim.AdamW(model.parameters(), lr=LR, weight_decay=0.01)
    steps = EPOCHS * (len(PT) // BATCH)
    sched = get_linear_schedule_with_warmup(opt, int(0.06 * steps), max(steps, 1))
    scaler = torch.amp.GradScaler("cuda", enabled=DEVICE.startswith("cuda"))
    lossf = torch.nn.BCEWithLogitsLoss()
    model.train()
    step, t0 = 0, time.time()
    for ep in range(EPOCHS):
        perm = rng.permutation(len(PT))
        for s in range(0, len(PT) - BATCH + 1, BATCH):
            b, y = collate(perm[s:s + BATCH], encT, yT)
            with torch.autocast(device_type="cuda", dtype=torch.float16, enabled=DEVICE.startswith("cuda")):
                logit = model(**b).logits.squeeze(-1)
            loss = lossf(logit.float(), y)
            opt.zero_grad(set_to_none=True)
            scaler.scale(loss).backward()
            scaler.unscale_(opt)
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            scaler.step(opt)
            scaler.update()
            sched.step()
            step += 1
            if step % 1000 == 0:
                el = time.time() - t0
                print(f"[{T}->{S}] step {step}/{steps} loss={loss.item():.4f} {el / step:.3f}s/step eta {el / step * (steps - step) / 60:.0f} min", flush=True)
    del encT
    gc.collect()
    aS, bS = pair_texts(S, PS)
    encS = tok(aS, bS, truncation="longest_first", max_length=MAX_LEN)
    order = np.argsort([len(x) for x in encS["input_ids"]])
    out = np.zeros(len(PS), np.float32)
    model.eval()
    with torch.no_grad(), torch.autocast(device_type="cuda", dtype=torch.float16, enabled=DEVICE.startswith("cuda")):
        for s in range(0, len(order), 256):
            ids = order[s:s + 256]
            b, _ = collate(ids, encS)
            out[ids] = model(**b).logits.squeeze(-1).float().cpu().numpy()
    np.save(OUT / f"xenc_logit_{S}.npy", out)
    np.save(OUT / f"xenc_index_{S}.npy", s_index)
    print(f"[{T}->{S}] done in {(time.time() - t0) / 60:.1f} min", flush=True)
    raise SystemExit(0)

# ============================================================================ main: run both directions, then stack and score
import scipy.sparse as sp  # noqa: E402
import torch  # noqa: E402
from scipy.sparse.csgraph import connected_components  # noqa: E402
from sklearn.metrics import average_precision_score, roc_auc_score  # noqa: E402

ngpu = torch.cuda.device_count()
log(f"gpus={ngpu} base={BASE} smoke={SMOKE}")
jobs = [("A", "B"), ("B", "A")]
procs = []
for k, (T, S) in enumerate(jobs):
    dev = f"cuda:{k % max(ngpu, 1)}" if ngpu else "cpu"
    cmd = [sys.executable, __file__, "--worker", str(IN), str(OUT), BASE, T, S, dev]
    if ngpu >= 2:
        procs.append(subprocess.Popen(cmd))
    else:
        subprocess.run(cmd, check=True)
for p in procs:
    if p.wait() != 0:
        raise SystemExit("a worker failed")
log("both cross-encoders done")

P = {k: pd.read_parquet(IN / f"pairs_{k}.parquet") for k in ("A", "B")}
R = {k: pd.read_parquet(IN / f"records_{k}.parquet") for k in ("A", "B")}
POI = {k: pd.factorize(R[k]["point_of_interest"].to_numpy())[0] for k in ("A", "B")}
X = {}
for k in ("A", "B"):
    lg = np.full(len(P[k]), np.nan, np.float32)
    lg[np.load(OUT / f"xenc_index_{k}.npy")] = np.load(OUT / f"xenc_logit_{k}.npy")
    P[k]["xenc_logit"] = lg


def logit(p):
    p = np.clip(p, 1e-6, 1 - 1e-6)
    return np.log(p / (1 - p))


def iou_cc(poi, i, j, keep):
    n = len(poi)
    A = sp.coo_matrix((np.ones(int(keep.sum()), np.int8), (i[keep], j[keep])), shape=(n, n))
    _, lab = connected_components(A, directed=False)
    t = pd.DataFrame({"root": lab, "poi": poi})
    inter = t.groupby(["root", "poi"])["poi"].transform("size").to_numpy()
    pred = t.groupby("root")["poi"].transform("size").to_numpy()
    true = t.groupby("poi")["poi"].transform("size").to_numpy()
    return float((inter / (pred + true - inter)).mean())


def iou_list(poi, i, j, p, t1, t2):
    n = len(poi)
    m1 = p > t1
    A1 = sp.coo_matrix((np.ones(int(m1.sum()), np.float32), (i[m1], j[m1])), shape=(n, n)).tocsr()
    Pm = A1 + A1.T + sp.identity(n, dtype=np.float32, format="csr")
    if t2 <= 1:
        m2 = p > t2
        A2 = sp.coo_matrix((np.ones(int(m2.sum()), np.float32), (i[m2], j[m2])), shape=(n, n)).tocsr()
        A2 = A2 + A2.T
        Pm = Pm + A2 @ A2
    Pm = Pm.tocoo()
    same = (poi[Pm.row] == poi[Pm.col]).astype(np.float64)
    inter = np.bincount(Pm.row, same, minlength=n)
    size = np.bincount(Pm.row, minlength=n)
    true = pd.Series(poi).map(pd.Series(poi).value_counts()).to_numpy()
    return float((inter / (size + true - inter)).mean())


def pick_and_score(pA, pB, a="A", b="B"):
    PA, PB = P[a], P[b]
    iA, jA, iB, jB = PA["i"].to_numpy(), PA["j"].to_numpy(), PB["i"].to_numpy(), PB["j"].to_numpy()
    cc = {float(t): iou_cc(POI[a], iA, jA, pA > t) for t in np.round(np.arange(0.2, 0.96, 0.05), 2)}
    t_cc = max(cc, key=cc.get)
    lst = {}
    for t1 in np.round(np.arange(0.3, 0.86, 0.1), 2):
        for t2 in [1.01] + [x for x in np.round(np.arange(0.5, 0.96, 0.1), 2) if x >= t1]:
            lst[(float(t1), float(t2))] = iou_list(POI[a], iA, jA, pA, t1, t2)
    t_l = max(lst, key=lst.get)
    return {"cc": {"threshold": t_cc, f"iou_{a}": cc[t_cc], f"iou_{b}": iou_cc(POI[b], iB, jB, pB > t_cc)},
            "list": {"t1": t_l[0], "t2": t_l[1], f"iou_{a}": lst[t_l], f"iou_{b}": iou_list(POI[b], iB, jB, pB, *t_l)}}


RES = {"base_model": BASE, "band": [LO, HI], "smoke": SMOKE}
for k in ("A", "B"):
    m = ~np.isnan(P[k]["xenc_logit"].to_numpy())
    y = P[k]["y"].to_numpy()[m]
    RES[f"band_{k}"] = {"pairs": int(m.sum()), "share_of_candidates": float(m.mean()), "positives": int(y.sum()),
                        "auc_gbdt_in_band": float(roc_auc_score(y, P[k]["p2"].to_numpy()[m])),
                        "auc_xenc_in_band": float(roc_auc_score(y, P[k]["xenc_logit"].to_numpy()[m]))}
log("band: " + json.dumps({k: RES[f"band_{k}"] for k in ("A", "B")}))

# (1) logit blend, weight picked on A by pair log-loss inside the band
def blend(k, wgt):
    p2 = P[k]["p2"].to_numpy()
    xl = P[k]["xenc_logit"].to_numpy()
    m = ~np.isnan(xl)
    z = logit(p2)
    z[m] = (1 - wgt) * z[m] + wgt * xl[m]
    return 1 / (1 + np.exp(-z))


mA = ~np.isnan(P["A"]["xenc_logit"].to_numpy())
best_w, best_ll = 0.0, 1e9
for wgt in np.round(np.arange(0, 1.01, 0.1), 1):
    pa = np.clip(blend("A", wgt)[mA], 1e-6, 1 - 1e-6)
    ya = P["A"]["y"].to_numpy()[mA]
    ll = float(-(ya * np.log(pa) + (1 - ya) * np.log(1 - pa)).mean())
    if ll < best_ll:
        best_w, best_ll = float(wgt), ll
RES["blend"] = {"weight_on_xenc": best_w, "logloss_A_band": best_ll}

# (2) stacker: GBDT on [p2, xenc logit, a few pair features] inside the band, cross-fitted between worlds
import lightgbm as lgb  # noqa: E402

SF = ["p2", "xenc_logit", "p1", "dist_m", "emb_cos", "name_jw", "name_token_set", "addr_token_set", "cat_token_set", "geo_rank", "emb_rank"]


def stacked(T, S):
    mT = ~np.isnan(P[T]["xenc_logit"].to_numpy())
    mS = ~np.isnan(P[S]["xenc_logit"].to_numpy())
    XT, yT = P[T].loc[mT, SF].to_numpy(np.float32), P[T]["y"].to_numpy()[mT]
    fold = np.array([zlib.crc32(str(int(v)).encode()) % 5 for v in POI[T][P[T]["i"].to_numpy()[mT]]])
    params = dict(objective="binary", learning_rate=0.05, num_leaves=63, min_data_in_leaf=100, feature_fraction=0.9, bagging_fraction=0.8,
                  bagging_freq=1, verbose=-1, seed=SEED)
    d_tr, d_va = lgb.Dataset(XT[fold != 0], yT[fold != 0]), lgb.Dataset(XT[fold == 0], yT[fold == 0])
    bst = lgb.train(params, d_tr, 300 if SMOKE else 3000, valid_sets=[d_va], callbacks=[lgb.early_stopping(100, verbose=False)])
    out = P[S]["p2"].to_numpy().copy()
    out[mS] = bst.predict(P[S].loc[mS, SF].to_numpy(np.float32), num_iteration=bst.best_iteration)
    return out


final = {"gbdt_only": {k: P[k]["p2"].to_numpy() for k in ("A", "B")},
         "blend": {k: blend(k, best_w) for k in ("A", "B")},
         "stack": {"B": stacked("A", "B"), "A": stacked("B", "A")}}
for nm, pp in final.items():
    r = pick_and_score(pp["A"], pp["B"])
    r["auc_B"], r["ap_B"] = float(roc_auc_score(P["B"]["y"], pp["B"])), float(average_precision_score(P["B"]["y"], pp["B"]))
    r["swap"] = pick_and_score(pp["B"], pp["A"], "B", "A")
    RES[nm] = r
    log(f"{nm}: " + json.dumps(r))
best = max(("blend", "stack"), key=lambda k: RES[k]["list"]["iou_A"])
RES["chosen_on_A"] = best
RES["seconds"] = time.time() - T0
(OUT / "metrics_stage2.json").write_text(json.dumps(RES, indent=1, default=float))
for k in ("A", "B"):
    o = P[k][["i", "j", "y", "p2", "xenc_logit"]].copy()
    o["p_final"] = final[best][k]
    o.to_parquet(OUT / f"final_pairs_{k}.parquet", index=False)
log("FINAL B list IoU: gbdt {:.4f}  {} {:.4f}".format(RES["gbdt_only"]["list"]["iou_B"], best, RES[best]["list"]["iou_B"]))
log("done")
