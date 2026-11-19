"""Second-stage (collective) matcher for the 12-city benchmark, evaluated leave-one-city-out with strict nesting.

Stage 1 is the pair model of scripts/train/city_matcher.py. Stage 2 adds what one pair cannot see on its own and the
Foursquare v2 pipeline found decisive (kaggle/fsq_v2/stage1.py): how strongly each record prefers its *other* candidates
from the same partner source (one record has at most one twin per source), its rank among them, and two-hop support
(Overture-OSM and OSM-Wikidata both strong makes Overture-Wikidata likely).

Leakage control. For held-out city c, every stage-1 score that feeds stage 2 comes from a booster that never saw c:
  * pairs of city c are scored by the stored leave-c-out booster (data/processed/city_matcher/loco/model_c.lgb);
  * pairs of every training city c' are scored by a booster trained without c and without c' (132 nested boosters),
    so the training rows of stage 2 carry out-of-city stage-1 scores too.
Stage 2 then trains on the labelled pairs of the 11 other cities (early stopping on the same validation-city rule as
stage 1) and scores c. Same weak labels, same protocol, so the comparison with stage 1 is like for like.

Input : data/processed/city_matcher/{pairs.parquet, clusters.parquet, featurizer_no_emb.joblib, loco/}
Output: reports/models/city_matcher_stage2.{md,json}, data/processed/city_matcher/stage2_oof.parquet
Usage : .venv\\Scripts\\python.exe -I -X utf8 scripts\\train\\city_matcher_stage2.py
"""
import json
import sys
import time
from pathlib import Path

import joblib
import lightgbm as lgb
import numpy as np
import pandas as pd
import scipy.sparse as sp
from sklearn.metrics import average_precision_score, precision_recall_curve, roc_auc_score

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
CM = ROOT / "data" / "processed" / "city_matcher"
REP = ROOT / "reports" / "models"
CITY_ORDER = ["dubai", "bangkok", "singapore", "delhi", "mumbai", "goa", "london", "paris", "amsterdam", "barcelona", "vienna", "milan"]
SEED = 7
PARAMS = dict(objective="binary", learning_rate=0.05, num_leaves=63, min_data_in_leaf=40, feature_fraction=0.8, bagging_fraction=0.8,
              bagging_freq=1, lambda_l2=1.0, verbose=-1, seed=SEED, num_threads=6)
T0 = time.time()


def log(m):
    print(f"[{time.time() - T0:6.0f}s] {m}", flush=True)


def val_city_of(city, pool):
    """Same rule as stage 1: the city five places on in CITY_ORDER, skipping cities outside the pool."""
    k = CITY_ORDER.index(city)
    for step in range(5, 5 + len(CITY_ORDER)):
        c = CITY_ORDER[(k + step) % len(CITY_ORDER)]
        if c in pool and c != city:
            return c
    raise ValueError(city)


def collective(n, ra, rb, part_a, part_b, p):
    """Per-pair features from a stage-1 score vector p over all candidate pairs (records 0..n-1)."""
    m = len(p)
    src = np.concatenate([ra, rb])
    partner_src = np.concatenate([part_b, part_a])   # the source of the record on the other end
    pp = np.concatenate([p, p])
    out = {}
    for name, key in (("any", src.astype(np.int64)), ("src", src.astype(np.int64) * 16 + partner_src)):
        o = np.lexsort((-pp, key))
        k_s, p_s = key[o], pp[o]
        start = np.r_[0, np.flatnonzero(np.diff(k_s)) + 1]
        size = np.diff(np.r_[start, len(k_s)])
        first = np.repeat(start, size)
        rank_s = np.arange(len(k_s)) - first + 1
        top = np.repeat(p_s[start], size)
        second = np.repeat(np.where(size >= 2, p_s[np.minimum(start + 1, len(p_s) - 1)], 0.0), size)
        rank = np.empty(len(key), np.int32)
        rank[o] = rank_s
        other = np.empty(len(key), np.float64)
        other[o] = np.where(rank_s == 1, second, top)
        cnt = np.empty(len(key), np.float64)
        cnt[o] = np.repeat(np.add.reduceat((p_s > 0.5).astype(float), start), size)
        ra_rank, rb_rank = rank[:m], rank[m:]
        ra_oth, rb_oth = other[:m], other[m:]
        out[f"{name}_rank_min"], out[f"{name}_rank_max"] = np.minimum(ra_rank, rb_rank), np.maximum(ra_rank, rb_rank)
        out[f"{name}_other_min"], out[f"{name}_other_max"] = np.minimum(ra_oth, rb_oth), np.maximum(ra_oth, rb_oth)
        out[f"{name}_margin"] = p - np.maximum(ra_oth, rb_oth)
        out[f"{name}_cnt5_max"] = np.maximum(cnt[:m], cnt[m:])
    msk = p > 0.05
    A = sp.coo_matrix((p[msk], (ra[msk], rb[msk])), shape=(n, n)).tocsr()
    A = (A + A.T).tocsr()
    out["twohop_sum"] = np.asarray((A @ A).tocsr()[ra, rb]).ravel()
    B = (A > 0.5).astype(np.float32)
    out["twohop_cnt"] = np.asarray((B @ B).tocsr()[ra, rb]).ravel()
    out["p1"] = p
    out["p1_logit"] = np.log(np.clip(p, 1e-6, 1 - 1e-6) / np.clip(1 - p, 1e-6, 1))
    return pd.DataFrame(out)


def scores(yt, p):
    prec, rec, thr = precision_recall_curve(yt, p)
    r = {"pos": int(yt.sum()), "neg": int((yt == 0).sum()), "auc": float(roc_auc_score(yt, p)), "ap": float(average_precision_score(yt, p))}
    for t in (0.99, 0.995):
        ok = np.where(prec[:-1] >= t)[0]
        r[f"recall@p{t}"] = float(rec[ok[0]]) if len(ok) else 0.0
    ok = np.where(rec[:-1] >= 0.95)[0]
    r["precision@r0.95"] = float(prec[ok[-1]]) if len(ok) else 0.0
    return r


def main():
    art = joblib.load(CM / "featurizer_no_emb.joblib")
    FEATS = art["features"]
    P = pd.read_parquet(CM / "pairs.parquet")
    G = pd.read_parquet(CM / "clusters.parquet", columns=["rid", "source"])
    src_code = pd.Series(pd.factorize(G.set_index("rid")["source"])[0], index=G["rid"].to_numpy())
    F = P[[f for f in FEATS if f != "src_pair"]].copy()
    F["src_pair"] = pd.Categorical(P["src_pair"].to_numpy(), categories=art["src_pair_categories"])
    F = F[FEATS]
    y = P["y"].to_numpy()
    city = P["city"].to_numpy()
    lab = y >= 0
    ra, rb = P["ra"].to_numpy(), P["rb"].to_numpy()
    n = int(max(ra.max(), rb.max())) + 1
    part_a, part_b = src_code.reindex(ra).to_numpy(), src_code.reindex(rb).to_numpy()
    manifest = json.loads((CM / "loco" / "manifest.json").read_text())
    rounds_med = int(np.median([v["best_iteration"] for v in manifest["cities"].values()]))
    log(f"pairs={len(P):,} labelled={int(lab.sum()):,} records={n:,} stage-1 rounds (median)={rounds_med}")

    # stage-1 scores that never saw city c, for every pair of city c (stored boosters)
    p_out = np.zeros(len(P))
    for c in CITY_ORDER:
        m = city == c
        p_out[m] = lgb.Booster(model_file=str(CM / "loco" / f"model_{c}.lgb")).predict(F[m])
    # nested boosters: without c and without c'
    nested = {}
    for c in CITY_ORDER:
        for c2 in CITY_ORDER:
            if c2 == c:
                continue
            tr = lab & (city != c) & (city != c2)
            b = lgb.train(PARAMS, lgb.Dataset(F[tr], y[tr]), rounds_med)
            m = city == c2
            nested[(c, c2)] = b.predict(F[m])
        log(f"nested boosters for held-out {c} done")

    oof2 = np.full(len(P), np.nan)
    per_city = {}
    imp = None
    for c in CITY_ORDER:
        p1 = p_out.copy()
        for c2 in CITY_ORDER:
            if c2 != c:
                p1[city == c2] = nested[(c, c2)]
        X = pd.concat([F.reset_index(drop=True), collective(n, ra, rb, part_a, part_b, p1)], axis=1)
        te = lab & (city == c)
        tr = lab & ~te
        pool = [x for x in CITY_ORDER if x != c]
        va = tr & (city == val_city_of(c, pool))
        tr2 = tr & ~va
        mdl = lgb.train(PARAMS, lgb.Dataset(X[tr2], y[tr2]), 2000, valid_sets=[lgb.Dataset(X[va], y[va])],
                        callbacks=[lgb.early_stopping(60, verbose=False)])
        oof2[te] = mdl.predict(X[te], num_iteration=mdl.best_iteration)
        per_city[c] = {"stage1": scores(y[te], P["p"].to_numpy()[te]), "stage2": scores(y[te], oof2[te])}
        g = pd.Series(mdl.feature_importance("gain"), index=X.columns)
        imp = g if imp is None else imp + g
        log(f"{c:<10} AP {per_city[c]['stage1']['ap']:.4f} -> {per_city[c]['stage2']['ap']:.4f}   "
            f"R@P99 {per_city[c]['stage1']['recall@p0.99']:.3f} -> {per_city[c]['stage2']['recall@p0.99']:.3f}")

    pooled = {"stage1": scores(y[lab], P["p"].to_numpy()[lab]), "stage2": scores(y[lab], oof2[lab])}
    kinds = {"lodging-lodging": F["both_lodging"].to_numpy() == 1, "name JW < 0.8": F["name_jw"].to_numpy() < 0.8,
             "more than 300 m apart": F["dist_m"].to_numpy() > 300, "script mismatch": F["script_mismatch"].to_numpy() == 1}
    slices = {}
    for k, msk in kinds.items():
        mm = lab & msk
        if mm.sum() > 50 and 0 < y[mm].sum() < mm.sum():
            slices[k] = {"stage1": scores(y[mm], P["p"].to_numpy()[mm]), "stage2": scores(y[mm], oof2[mm])}
    imp = (imp / imp.sum()).sort_values(ascending=False)
    res = {"pooled": pooled, "per_city": per_city, "slices": slices, "importance": imp.head(20).round(4).to_dict(),
           "nested_boosters": len(nested), "stage1_rounds": rounds_med, "seconds": time.time() - T0}
    (REP / "city_matcher_stage2.json").write_text(json.dumps(res, indent=1))
    pd.DataFrame({"ra": ra, "rb": rb, "y": y, "p_stage1": P["p"].to_numpy(), "p_stage2_oof": oof2}).to_parquet(CM / "stage2_oof.parquet")
    log("pooled: " + json.dumps({k: {m: round(v, 4) for m, v in d.items()} for k, d in pooled.items()}))

    def pct(v):
        return f"{v:.1%}"
    L = ["# Second-stage (collective) matcher on the 12-city benchmark", "",
         "Generated by `scripts/train/city_matcher_stage2.py`. Same **weak labels** and the same leave-one-city-out protocol as "
         "`reports/models/city_matcher.md`; stage 1 below is that report's model, unchanged.",
         "",
         "Stage 2 adds collective features computed from stage-1 scores: each record's best competing candidate from the same partner "
         "source (a record has at most one twin per source), its rank among them, how many strong candidates it has, and two-hop support "
         "through a third record. Every stage-1 score that feeds stage 2 comes from a booster that never saw the held-out city: "
         f"{len(nested)} nested boosters (without the held-out city and without the scored training city) supply the training rows.",
         "", "## Pooled over the 12 held-out cities", "",
         "| Measure | Stage 1 (pair model) | Stage 2 (+ collective) |", "|---|---:|---:|"]
    for k, lbl in (("auc", "AUC"), ("ap", "Average precision"), ("recall@p0.99", "Recall at 99% precision"),
                   ("recall@p0.995", "Recall at 99.5% precision"), ("precision@r0.95", "Precision at 95% recall")):
        a, b = pooled["stage1"][k], pooled["stage2"][k]
        L.append(f"| {lbl} | {a:.4f} | **{b:.4f}** |" if k in ("auc", "ap") else f"| {lbl} | {pct(a)} | **{pct(b)}** |")
    L += ["", "## Per held-out city", "", "| City | Matches | AP stage 1 | AP stage 2 | R@P99 stage 1 | R@P99 stage 2 |", "|---|---:|---:|---:|---:|---:|"]
    for c in CITY_ORDER:
        s1, s2 = per_city[c]["stage1"], per_city[c]["stage2"]
        L.append(f"| {c} | {s1['pos']:,} | {s1['ap']:.4f} | {s2['ap']:.4f} | {pct(s1['recall@p0.99'])} | {pct(s2['recall@p0.99'])} |")
    L += ["", "## Hard slices (pooled)", "", "| Slice | Matches | AP stage 1 | AP stage 2 | AUC stage 1 | AUC stage 2 |", "|---|---:|---:|---:|---:|---:|"]
    for k, d in slices.items():
        L.append(f"| {k} | {d['stage1']['pos']:,} | {d['stage1']['ap']:.4f} | {d['stage2']['ap']:.4f} | {d['stage1']['auc']:.4f} | {d['stage2']['auc']:.4f} |")
    L += ["", "## Feature importance (gain share, summed over the 12 stage-2 models)", "", "| Feature | Share |", "|---|---:|"]
    L += [f"| {k} | {v:.1%} |" for k, v in list(imp.head(12).items())]
    L += ["", "## Reading the numbers", "",
          "- The labels are weak (shared Wikidata QID, or rare phone / URL plus proximity), as in the stage-1 report. Both stages are scored "
          "against the same labels, so the difference between the columns is a fair comparison; the absolute values still need the human label sheet.",
          "- Recall at a fixed 99% precision hinges on a handful of top-scored non-matches and moves by several points between runs; "
          "average precision and AUC are the steadier measures.",
          "- The website still runs stage 1. Stage 2 needs stage-1 scores for every candidate in a city before it can score any pair, "
          "which fits the batch pipeline; wiring it into the live preset runs is listed in PROGRESS.md."]
    (REP / "city_matcher_stage2.md").write_text("\n".join(L) + "\n", encoding="utf-8")
    log("wrote reports/models/city_matcher_stage2.md")


if __name__ == "__main__":
    main()
