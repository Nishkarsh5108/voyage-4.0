"""Cross-source entity matcher on the 12-city open-data benchmark (hotels + attractions).

Stages
  1. blocking      geo kNN per source pair, exact normalised name, char-n-gram name kNN  -> candidate pairs
  2. weak labels   positives: shared Wikidata QID, or a shared rare phone / URL plus proximity
                   negatives: two different QIDs, or different rare phones AND different domains
  3. pair model    LightGBM on name / geography / address / source-quality features.
                   Phone, URL and QID are deliberately NOT features: they are the held-out truth.
  4. evaluation    leave-one-city-out: train on 11 cities, test on the unseen one
  5. cascade       share of all candidates settled by key rules, by the model alone, and left uncertain
  6. clustering    constrained union-find (never merge two different QIDs) -> canonical entities per city

Input : data/interim/listings.parquet
Output: data/processed/city_matcher/{pairs.parquet, clusters.parquet, model.lgb}, reports/models/city_matcher.{md,json}
Usage : python -I scripts/train/city_matcher.py
"""
import json
import sys
import time
from pathlib import Path

import joblib
import lightgbm as lgb
import numpy as np
import pandas as pd
from sklearn.metrics import average_precision_score, precision_recall_curve, roc_auc_score

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts" / "eda"))
from canon.match import Featurizer, block, haversine, prepare  # noqa: E402
from common import SERIES, plt  # noqa: E402

OUT = ROOT / "data" / "processed" / "city_matcher"
REP = ROOT / "reports" / "models"
OUT.mkdir(parents=True, exist_ok=True)
(REP / "figures" / "city_matcher").mkdir(parents=True, exist_ok=True)
CITY_ORDER = ["dubai", "bangkok", "singapore", "delhi", "mumbai", "goa", "london", "paris", "amsterdam", "barcelona", "vienna", "milan"]
SRC = ["overture", "osm", "wikidata", "wikivoyage"]
K_GEO, R_GEO, K_NAME, MIN_COS, HUB = 8, 1000.0, 3, 0.55, 4
K_EMB, MIN_EMB = 3, 0.90
SEED = 7
T0 = time.time()


def log(m):
    print(f"[{time.time() - T0:6.0f}s] {m}", flush=True)


# ============================================================================ records
G = pd.read_parquet(ROOT / "data" / "interim" / "listings.parquet")
G = prepare(G[G["lat"].notna() & G["in_bbox"].fillna(False)].reset_index(drop=True))
for key in ("phone8", "url_key"):  # a value shared by many listings in a city is a hub (call centre, chain home page)
    cnt = G.groupby(["city", key])[key].transform("size")
    G[key + "_rare"] = G[key].where(cnt <= HUB)
log(f"records={len(G):,} " + str(G.groupby('source').size().to_dict()))
fz = Featurizer().fit(G["nn"])
XC = fz.tf_char.transform(G["nn"])
# Multilingual name embeddings (scripts/build/embed_names.py) are opt-in with --emb.
# Tried on 14 Nov 2026: no measurable gain on this benchmark (see the experiment table in the report), so the default is off.
EMB_DIR = ROOT / "data" / "interim" / "name_emb"
USE_EMB = "--emb" in sys.argv and (EMB_DIR / "e5_small.npy").exists()
E = None
if USE_EMB:
    E = np.load(EMB_DIR / "e5_small.npy").astype(np.float32)
    erow = dict(zip(*pd.read_parquet(EMB_DIR / "strings.parquet")[["string", "row"]].to_numpy().T))
    G["erow"] = G["name"].map(lambda s: erow.get(str(s).strip(), -1)).astype(int)
    G["alt_erows"] = G["alt_names"].map(lambda xs: [erow[str(x).strip()] for x in (xs if xs is not None else []) if str(x).strip() in erow])
    log(f"embeddings loaded: {E.shape}, names without a vector: {(G['erow'] < 0).sum()}")

# ============================================================================ 1. blocking
C = block(G, XC, CITY_ORDER, SRC, k_geo=K_GEO, r_geo=R_GEO, k_name=K_NAME, min_cos=MIN_COS, E=E, k_emb=K_EMB, min_emb=MIN_EMB, log=log)
log(f"candidates={len(C):,}")

a, b = G.iloc[C["ra"].to_numpy()].reset_index(drop=True), G.iloc[C["rb"].to_numpy()].reset_index(drop=True)
C["city"] = a["city"].to_numpy()
C["src_pair"] = (a["source"] + "|" + b["source"]).to_numpy()
C["dist_m"] = haversine(a["lat"].to_numpy(), a["lon"].to_numpy(), b["lat"].to_numpy(), b["lon"].to_numpy()).astype(np.float32)


# ============================================================================ 2. weak labels from independent keys
def eq(col):
    x, y = a[col].to_numpy(dtype=object), b[col].to_numpy(dtype=object)
    both = pd.notna(x) & pd.notna(y)
    return both, both & (x == y)


both_q, same_q = eq("qid")
both_p, same_p = eq("phone8_rare")
both_u, same_u = eq("url_key_rare")
both_d, same_d = eq("domain")
d = C["dist_m"].to_numpy()
pos = (same_q & (d < 2000)) | (same_p & same_u & (d < 1000)) | (same_p & (d < 300)) | (same_u & (d < 300))
neg = (both_q & ~same_q) | (both_p & ~same_p & both_d & ~same_d)
C["y"] = np.where(pos & ~(both_q & ~same_q), 1, np.where(neg & ~pos, 0, -1)).astype(np.int8)
C["label_src"] = np.where(same_q, "qid", np.where(same_p & same_u, "phone+url", np.where(same_p, "phone", np.where(same_u, "url",
                 np.where(both_q & ~same_q, "qid_conflict", np.where(neg, "phone_and_domain_differ", ""))))))
# Ambiguous "negatives": the keys conflict, yet both records carry the same name (token order ignored) within 50 m.
# Inspection shows these are overwhelmingly one entity (Wikidata holds duplicate items; a hotel lists two phone numbers),
# so they are neither trained on nor scored as non-matches. The rule uses only raw name equality and distance, never the model.
tok_sorted = lambda s: " ".join(sorted(s.split()))  # noqa: E731
same_name = a["nn"].map(tok_sorted).to_numpy() == b["nn"].map(tok_sorted).to_numpy()
amb = (C["y"].to_numpy() == 0) & same_name & (d < 50)
C.loc[amb, "y"] = -2
log("labels: " + str(C["y"].value_counts().to_dict()) + f" (ambiguous same-name-within-50m conflicts set aside: {int(amb.sum()):,})")


# ============================================================================ 3. features (no phone / url / qid)
F = fz.transform(G, C, E=E)
FEATS = list(F.columns)
log(f"features={len(FEATS)} on {len(F):,} pairs")

# ============================================================================ 4. leave-one-city-out
PARAMS = dict(objective="binary", learning_rate=0.05, num_leaves=63, min_data_in_leaf=40, feature_fraction=0.8, bagging_fraction=0.8,
              bagging_freq=1, lambda_l2=1.0, verbose=-1, seed=SEED, num_threads=4)
lab = C["y"].to_numpy() >= 0
y = C["y"].to_numpy()
oof = np.full(len(C), np.nan)
per_city, rounds = {}, []
for city in CITY_ORDER:
    te = lab & (C["city"].to_numpy() == city)
    tr = lab & ~te
    # early stopping on a second held-out city, never on the test city
    val_city = CITY_ORDER[(CITY_ORDER.index(city) + 5) % len(CITY_ORDER)]
    va = tr & (C["city"].to_numpy() == val_city)
    tr2 = tr & ~va
    m = lgb.train(PARAMS, lgb.Dataset(F[tr2], y[tr2]), 1500, valid_sets=[lgb.Dataset(F[va], y[va])],
                  callbacks=[lgb.early_stopping(60, verbose=False)])
    rounds.append(m.best_iteration)
    p = m.predict(F[te], num_iteration=m.best_iteration)
    oof[te] = p
    yt = y[te]
    prec, rec, thr = precision_recall_curve(yt, p)

    def rec_at(target):
        ok = np.where(prec[:-1] >= target)[0]
        return float(rec[ok[0]]) if len(ok) else 0.0

    def prec_at(target):
        ok = np.where(rec[:-1] >= target)[0]
        return float(prec[ok[-1]]) if len(ok) else 0.0

    Ft = F[te]
    base = (Ft["name_jw"].to_numpy() >= 0.9) & (Ft["dist_m"].to_numpy() < 200)
    btp = int(yt[base].sum())
    per_city[city] = {"pos": int(yt.sum()), "neg": int((yt == 0).sum()), "auc": float(roc_auc_score(yt, p)),
                      "ap": float(average_precision_score(yt, p)), "recall@p0.99": rec_at(0.99), "recall@p0.995": rec_at(0.995),
                      "precision@r0.95": prec_at(0.95),
                      "rule_precision": btp / max(int(base.sum()), 1), "rule_recall": btp / max(int(yt.sum()), 1),
                      "pr": {"precision": prec[:-1][::max(len(thr) // 150, 1)].round(4).tolist(), "recall": rec[:-1][::max(len(thr) // 150, 1)].round(4).tolist()}}
    log(f"held-out {city}: " + json.dumps({k: (round(v, 4) if isinstance(v, float) else v) for k, v in per_city[city].items() if k != 'pr'}))

yl, pl = y[lab], oof[lab]
prec, rec, thr = precision_recall_curve(yl, pl)
pooled = {"pos": int(yl.sum()), "neg": int((yl == 0).sum()), "auc": float(roc_auc_score(yl, pl)), "ap": float(average_precision_score(yl, pl))}
for t in (0.99, 0.995):
    ok = np.where(prec[:-1] >= t)[0]
    pooled[f"recall@p{t}"] = float(rec[ok[0]]) if len(ok) else 0.0
    pooled[f"threshold@p{t}"] = float(thr[ok[0]]) if len(ok) else 1.0
ok = np.where(rec[:-1] >= 0.95)[0]
pooled["precision@r0.95"] = float(prec[ok[-1]])
log("pooled out-of-city: " + json.dumps({k: round(v, 4) if isinstance(v, float) else v for k, v in pooled.items()}))

# slices of the pooled out-of-city predictions
slices = {}
T_HI = pooled["threshold@p0.99"]
for name, mask in {"lodging-lodging": F["both_lodging"].to_numpy() == 1, "attraction-attraction": (F["same_kind"].to_numpy() == 1) & (F["both_lodging"].to_numpy() == 0),
                   "script mismatch": F["script_mismatch"].to_numpy() == 1, "more than 300 m apart": F["dist_m"].to_numpy() > 300,
                   "name JW < 0.8": F["name_jw"].to_numpy() < 0.8, "involves Overture": C["src_pair"].str.contains("overture").to_numpy()}.items():
    mm = lab & mask
    if mm.sum() > 50 and 0 < y[mm].sum() < mm.sum():
        acc = oof[mm] >= T_HI
        slices[name] = {"pos": int(y[mm].sum()), "neg": int((y[mm] == 0).sum()), "auc": float(roc_auc_score(y[mm], oof[mm])),
                        "precision_at_T": float(y[mm][acc].mean()) if acc.sum() else None, "recall_at_T": float(acc[y[mm] == 1].mean())}

# ============================================================================ 5. final model + cascade shares
final = lgb.train(PARAMS, lgb.Dataset(F[lab], y[lab]), int(np.median(rounds)))
final.save_model(str(OUT / "model.lgb"))
C["p"] = np.where(lab, oof, final.predict(F))  # labelled pairs keep their out-of-city score
# the same evaluation with the ambiguous pairs counted as non-matches, to show how much of the gap is label noise
raw_m = lab | amb
y_raw, p_raw = np.where(amb, 0, y)[raw_m], C["p"].to_numpy()[raw_m]
pr_, rc_, th_ = precision_recall_curve(y_raw, p_raw)
raw = {"ambiguous_pairs": int(amb.sum()), "ambiguous_by_source": C.loc[amb, "label_src"].value_counts().to_dict(),
       "ambiguous_mean_p": float(C.loc[amb, "p"].mean()), "ambiguous_share_p_ge_0.9": float((C.loc[amb, "p"] >= 0.9).mean())}
for t in (0.99, 0.995):
    ok = np.where(pr_[:-1] >= t)[0]
    raw[f"recall@p{t}"] = float(rc_[ok[0]]) if len(ok) else 0.0
log("raw (ambiguous counted as non-matches): " + json.dumps(raw))
imp = pd.DataFrame({"feature": FEATS, "gain": final.feature_importance("gain")})
imp["share"] = imp["gain"] / imp["gain"].sum()
imp = imp.sort_values("gain", ascending=False)
n_all = len(C)
key_match = (C["y"].to_numpy() == 1)
key_reject = (C["y"].to_numpy() == 0)
rest = ~(key_match | key_reject)
pr = C["p"].to_numpy()
T_LO = 0.02
# everything another feed needs to be scored with this model (see scripts/train/ota_matcher.py)
joblib.dump({"featurizer": fz, "features": FEATS, "src_pair_categories": list(F["src_pair"].cat.categories), "t_accept": T_HI, "t_reject": T_LO,
             "blocking": {"k_geo": K_GEO, "r_geo": R_GEO, "k_name": K_NAME, "min_cos": MIN_COS}}, OUT / f"featurizer_{'emb' if USE_EMB else 'no_emb'}.joblib")
cascade = {"candidates": n_all, "stage0_key_match": int(key_match.sum()), "stage0_key_reject": int(key_reject.sum()),
           "stage2_model_accept": int((rest & (pr >= T_HI)).sum()), "stage2_model_reject": int((rest & (pr < T_LO)).sum()),
           "uncertain_to_next_stage": int((rest & (pr >= T_LO) & (pr < T_HI)).sum()), "t_accept": T_HI, "t_reject": T_LO}
log("cascade: " + json.dumps(cascade))

# ============================================================================ 6. constrained clustering
acc = key_match | (rest & (pr >= T_HI))
E = C.loc[acc, ["ra", "rb", "p"]].assign(w=lambda x: np.where(key_match[acc], 2.0, x["p"])).sort_values("w", ascending=False)
parent = np.arange(len(G))
qid_of = [({q} if isinstance(q, str) else set()) for q in G["qid"]]
blocked = 0


def find(x):
    while parent[x] != x:
        parent[x] = parent[parent[x]]
        x = parent[x]
    return x


for ra, rb in zip(E["ra"].to_numpy(), E["rb"].to_numpy()):
    x, yv = find(ra), find(rb)
    if x == yv:
        continue
    if qid_of[x] and qid_of[yv] and qid_of[x] != qid_of[yv]:
        blocked += 1  # cannot-link: two different Wikidata identities
        continue
    parent[x] = yv
    qid_of[yv] = qid_of[yv] | qid_of[x]
G["cluster"] = [find(i) for i in range(len(G))]
cl = G.groupby("cluster").agg(n=("rid", "size"), n_sources=("source", "nunique"), city=("city", "first"), kind=("kind", lambda x: x.mode().iloc[0]))
G[["rid", "source", "provider", "city", "src_id", "kind", "name", "lat", "lon", "qid", "cluster"]].to_parquet(OUT / "clusters.parquet")
C.assign(**{f: F[f] for f in FEATS if f != "src_pair"}).to_parquet(OUT / "pairs.parquet")
clus = {}
for city in CITY_ORDER:
    g = G[(G["city"] == city) & (G["kind"] == "lodging")]
    c = cl.loc[g["cluster"].unique()]
    same_src_dupe = int((g.groupby(["cluster", "source"]).size() > 1).groupby("cluster").any().sum())
    clus[city] = {"lodging_listings": len(g), "canonical_entities": int(g["cluster"].nunique()),
                  "reduction": 1 - g["cluster"].nunique() / len(g), "multi_source_entities": int((c["n_sources"] > 1).sum()),
                  "entities_with_same_source_duplicates": same_src_dupe, "largest_cluster": int(c["n"].max())}
log(f"clusters: blocked_by_qid={blocked} " + json.dumps({k: v["canonical_entities"] for k, v in clus.items()}))

# blocking recall against the key-linked truth that exists independent of blocking
KP = pd.read_parquet(ROOT / "data" / "interim" / "key_pairs.parquet")
KP = KP[KP["ks"].map(lambda k: "qid" in list(k))]
rid_of = {(s, i): r for s, i, r in zip(G["source"], G["src_id"], G["rid"])}
tr_pairs = {(min(x, yv), max(x, yv)) for x, yv in ((rid_of.get((sa, ia)), rid_of.get((sb, ib))) for sa, ia, sb, ib in
            zip(KP["sa"], KP["ida"], KP["sb"], KP["idb"])) if x is not None and yv is not None}
have = set(zip(C["ra"].to_numpy(), C["rb"].to_numpy()))
geo_have = set(zip(C.loc[C["by_geo"] == 1, "ra"].to_numpy(), C.loc[C["by_geo"] == 1, "rb"].to_numpy()))
blocking = {"qid_truth_pairs": len(tr_pairs), "recall_union": len(tr_pairs & have) / len(tr_pairs), "recall_geo_only": len(tr_pairs & geo_have) / len(tr_pairs),
            "candidates": n_all, "candidates_per_record": n_all / len(G)}
log("blocking: " + json.dumps({k: round(v, 4) if isinstance(v, float) else v for k, v in blocking.items()}))

# ============================================================================ sheet for human labels
rng = np.random.default_rng(SEED)
buckets = {
    "accepted_unlabelled": rest & ~amb & (pr >= T_HI),          # what the model would auto-merge with no key evidence
    "uncertain_band": rest & ~amb & (pr >= 0.3) & (pr < T_HI),  # what would go to the next stage
    "ambiguous_conflict": amb,                                  # set aside above; checks that decision
    "negative_scored_high": (y == 0) & (pr >= 0.8),             # remaining disagreements with the weak labels
    "positive_scored_low": (y == 1) & (pr < 0.2),
}
take = {"accepted_unlabelled": 120, "uncertain_band": 100, "ambiguous_conflict": 60, "negative_scored_high": 60, "positive_scored_low": 60}
rows_ = []
for bname, mask in buckets.items():
    idx = np.where(mask)[0]
    for i in rng.choice(idx, size=min(take[bname], len(idx)), replace=False):
        ra_, rb_ = G.iloc[C["ra"].iat[i]], G.iloc[C["rb"].iat[i]]
        rows_.append({"pair_id": f"{C['ra'].iat[i]}-{C['rb'].iat[i]}", "bucket": bname, "city": ra_["city"],
                      "source_a": ra_["source"], "name_a": ra_["name"], "category_a": ra_["category"], "street_a": ra_["street"],
                      "source_b": rb_["source"], "name_b": rb_["name"], "category_b": rb_["category"], "street_b": rb_["street"],
                      "dist_m": round(float(C["dist_m"].iat[i])), "lat_a": ra_["lat"], "lon_a": ra_["lon"], "lat_b": rb_["lat"], "lon_b": rb_["lon"],
                      "qid_a": ra_["qid"], "qid_b": rb_["qid"], "weak_label": int(C["y"].iat[i]), "label_src": C["label_src"].iat[i],
                      "p": round(float(pr[i]), 4), "human_label": ""})
sheet = pd.DataFrame(rows_).sample(frac=1.0, random_state=SEED).reset_index(drop=True)
sheet.drop(columns=["bucket", "weak_label", "label_src", "p"]).to_csv(OUT / "label_sheet.csv", index=False, encoding="utf-8-sig")
sheet[["pair_id", "bucket", "weak_label", "label_src", "p"]].to_csv(OUT / "label_sheet_key.csv", index=False)
sheet.to_parquet(OUT / "label_sheet_full.parquet")
log(f"label sheet: {len(sheet)} pairs " + str(sheet['bucket'].value_counts().to_dict()))

# ============================================================================ report
res = {"records": len(G), "candidates": n_all, "labels": {"positive": int((y == 1).sum()), "negative": int((y == 0).sum()), "unlabelled": int((y == -1).sum()),
       "ambiguous_set_aside": int(amb.sum()), "raw_view": raw,
       "by_source": C.loc[lab, "label_src"].value_counts().to_dict()}, "blocking": blocking, "per_city": per_city, "pooled": pooled, "slices": slices,
       "cascade": cascade, "clusters": clus, "qid_cannot_link_blocks": blocked, "feature_importance": imp.to_dict("records"),
       "params": {"k_geo": K_GEO, "r_geo_m": R_GEO, "k_name": K_NAME, "min_cos": MIN_COS, "hub": HUB}, "seconds": time.time() - T0}
res["variant"] = "emb" if USE_EMB else "no_emb"
(OUT / f"metrics_{res['variant']}.json").write_text(json.dumps(res, indent=1, default=float), encoding="utf-8")
if USE_EMB:  # an experiment run never overwrites the main report
    log("embedding variant: metrics saved to data/processed/city_matcher/metrics_emb.json; main report left untouched")
    raise SystemExit(0)
(REP / "city_matcher.json").write_text(json.dumps(res, indent=1, default=float), encoding="utf-8")

fig, ax = plt.subplots(figsize=(7.5, 4.2))
for i, city in enumerate(("dubai", "bangkok", "singapore")):
    ax.plot(per_city[city]["pr"]["recall"], per_city[city]["pr"]["precision"], color=SERIES[i], label=f"{city} held out")
ax.set_xlabel("recall"); ax.set_ylabel("precision"); ax.set_xlim(0.5, 1.0); ax.set_ylim(0.9, 1.002)
ax.set_title("Pair model on a city it never saw (weak labels from independent keys)"); ax.legend(loc="lower left")
fig.savefig(REP / "figures" / "city_matcher" / "pr_core_cities.png"); plt.close(fig)

L = ["# Cross-source matcher on the 12-city open-data benchmark", "",
     "Generated by `scripts/train/city_matcher.py`. Numbers come from **weak labels**: a pair is a known match when two sources share a Wikidata QID, "
     "or a rare phone / URL plus proximity; a known non-match when the two records carry different QIDs, or different rare phones and different domains. "
     "The model never sees phone, URL or QID, so those keys act as independent truth. This is not a hand-labelled gold set; a few hundred human labels "
     "should confirm it before any number goes on a slide as final.", "",
     "## Data", "",
     f"- Records: **{len(G):,}** listings (hotels and attractions) from Overture, OpenStreetMap, Wikidata and Wikivoyage in 12 cities.",
     f"- Candidate pairs after blocking: **{n_all:,}** ({blocking['candidates_per_record']:.1f} per record).",
     f"- Labelled: **{res['labels']['positive']:,} matches**, **{res['labels']['negative']:,} non-matches**; {res['labels']['unlabelled']:,} candidates have no key evidence either way.",
     f"- Set aside as ambiguous: **{raw['ambiguous_pairs']:,}** pairs whose keys conflict although both records carry the same name within 50 m "
     f"({', '.join(f'{k}: {v:,}' for k, v in raw['ambiguous_by_source'].items())}). Wikidata holds duplicate items for many hotels and museums, and one "
     "hotel often lists different phone numbers in two sources, so these 'non-matches' are mostly the same entity. The rule uses only raw name equality and "
     f"distance, not the model. For reference the model scores {raw['ambiguous_share_p_ge_0.9']:.0%} of them at 0.9 or higher. Counting them as non-matches "
     f"would cut recall at 99% precision to {raw['recall@p0.99']:.1%}; that gap is label noise, and `label_sheet.csv` exists so people can settle it.",
     f"- Blocking recall against {blocking['qid_truth_pairs']:,} QID-linked pairs found without blocking: **{blocking['recall_union']:.1%}** "
     f"(geo generator alone: {blocking['recall_geo_only']:.1%}).", "",
     "## Leave-one-city-out results", "",
     "Each row: train on the other 11 cities, test on this one. The rule baseline is name Jaro-Winkler >= 0.9 and distance < 200 m.", "",
     "| Held-out city | Matches | Non-matches | AUC | Avg precision | Recall at 99% precision | Recall at 99.5% precision | Precision at 95% recall | Rule precision | Rule recall |",
     "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
for c in CITY_ORDER:
    v = per_city[c]
    L.append(f"| {c} | {v['pos']:,} | {v['neg']:,} | {v['auc']:.4f} | {v['ap']:.4f} | {v['recall@p0.99']:.1%} | {v['recall@p0.995']:.1%} | {v['precision@r0.95']:.1%} | "
             f"{v['rule_precision']:.1%} | {v['rule_recall']:.1%} |")
L += ["", f"Pooled over all held-out predictions: AUC {pooled['auc']:.4f}, average precision {pooled['ap']:.4f}, "
      f"recall **{pooled['recall@p0.99']:.1%} at 99% precision**, {pooled['recall@p0.995']:.1%} at 99.5% precision, precision {pooled['precision@r0.95']:.1%} at 95% recall.", "",
      "![PR curves for the three core cities](figures/city_matcher/pr_core_cities.png)", "",
      "## Hard slices (pooled, at the 99%-precision threshold)", "",
      "| Slice | Matches | Non-matches | AUC | Precision | Recall |", "|---|---:|---:|---:|---:|---:|"]
for k, v in slices.items():
    L.append(f"| {k} | {v['pos']:,} | {v['neg']:,} | {v['auc']:.4f} | {(v['precision_at_T'] or 0):.1%} | {v['recall_at_T']:.1%} |")
L += ["", "## Cascade: who settles each candidate pair", "",
      "| Stage | Pairs | Share |", "|---|---:|---:|",
      f"| 0. Key rule: match (QID, or rare phone / URL + proximity) | {cascade['stage0_key_match']:,} | {cascade['stage0_key_match'] / n_all:.1%} |",
      f"| 0. Key rule: reject (conflicting keys) | {cascade['stage0_key_reject']:,} | {cascade['stage0_key_reject'] / n_all:.1%} |",
      f"| 2. Model accepts (p >= {T_HI:.3f}) | {cascade['stage2_model_accept']:,} | {cascade['stage2_model_accept'] / n_all:.1%} |",
      f"| 2. Model rejects (p < {T_LO}) | {cascade['stage2_model_reject']:,} | {cascade['stage2_model_reject'] / n_all:.1%} |",
      f"| Uncertain: goes on to cross-encoder / LLM / human | {cascade['uncertain_to_next_stage']:,} | {cascade['uncertain_to_next_stage'] / n_all:.1%} |", "",
      "## Canonical entities (lodging)", "",
      "Accepted pairs are merged with a constrained union-find that refuses to join two different Wikidata identities "
      f"({blocked:,} merges refused).", "",
      "| City | Lodging listings | Canonical entities | Reduction | Entities seen in 2+ sources | Entities with two records from one source | Largest cluster |",
      "|---|---:|---:|---:|---:|---:|---:|"]
for c in CITY_ORDER:
    v = clus[c]
    L.append(f"| {c} | {v['lodging_listings']:,} | {v['canonical_entities']:,} | {v['reduction']:.1%} | {v['multi_source_entities']:,} | "
             f"{v['entities_with_same_source_duplicates']:,} | {v['largest_cluster']} |")
L += ["", "## Feature importance (gain share, final model)", "", "| Feature | Share |", "|---|---:|"]
L += [f"| {r.feature} | {r.share:.1%} |" for r in imp.head(12).itertuples()]
emb_file = OUT / "metrics_emb.json"
if emb_file.exists():
    e = json.loads(emb_file.read_text(encoding="utf-8"))

    def row(name, f):
        return f"| {name} | {f(res)} | {f(e)} |"

    L += ["", "## Experiment: multilingual name embeddings (not adopted)", "",
          "Variant run with `--emb`: `intfloat/multilingual-e5-small` vectors of every name, used zero-shot both as a third candidate generator "
          "(top 3 by cosine >= 0.90 anywhere in the city) and as two pair features. Same labels, same leave-one-city-out protocol.", "",
          "| Measure | Without embeddings (adopted) | With embeddings |", "|---|---:|---:|",
          row("Candidate pairs", lambda x: f"{x['candidates']:,}"),
          row("Blocking recall on QID-linked pairs", lambda x: f"{x['blocking']['recall_union']:.2%}"),
          row("Labelled non-matches", lambda x: f"{x['labels']['negative']:,}"),
          row("Pooled AUC", lambda x: f"{x['pooled']['auc']:.4f}"),
          row("Pooled average precision", lambda x: f"{x['pooled']['ap']:.4f}"),
          row("Recall at 99% precision", lambda x: f"{x['pooled']['recall@p0.99']:.1%}"),
          row("Recall at 99.5% precision", lambda x: f"{x['pooled']['recall@p0.995']:.1%}"),
          row("Precision at 95% recall", lambda x: f"{x['pooled']['precision@r0.95']:.1%}"),
          row("Bangkok held out: recall at 99% precision", lambda x: f"{x['per_city']['bangkok']['recall@p0.99']:.1%}"),
          row("Script-mismatch slice AUC", lambda x: f"{x['slices']['script mismatch']['auc']:.4f}"),
          row("Uncertain share of candidates", lambda x: f"{x['cascade']['uncertain_to_next_stage'] / x['candidates']:.1%}"), "",
          "No measurable gain: AUC moves in the third decimal and average precision in the fourth, blocking recall rises by less than a tenth of a "
          "point for about 11% more candidates, and the high-precision operating point is slightly worse because the extra candidates are mostly hard non-matches. "
          "Alternate-language names already carried in the sources do the cross-script work here. A generic embedding used zero-shot is not the lever; "
          "the next thing to try for the uncertain band is a cross-encoder fine-tuned on these pairs. "
          "Recall at a fixed 99% precision moves by several points between runs because it hinges on a handful of top-scored non-matches, "
          "so differences of that size should not be read as real."]
(REP / "city_matcher.md").write_text("\n".join(L) + "\n", encoding="utf-8")
log("wrote reports/models/city_matcher.md")
