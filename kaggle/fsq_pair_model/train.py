"""Stage-2 pair model of the matching cascade, trained and benchmarked on Foursquare Location Matching.

Pipeline: split places into train / valid / test worlds -> blocking inside each world (geo kNN + exact
normalised-name key) -> pair features -> LightGBM -> pair metrics, rule baselines, cluster IoU.

Runs on a Kaggle CPU kernel (dataset: robikscube/foursquare-location-matching-parquet) or locally:
    CANON_SMOKE=1 python -I kaggle/fsq_pair_model/train.py data/raw/foursquare_lm data/interim/fsq_smoke
The data is under competition terms: this model is a research benchmark, not a shippable artefact.
"""
import json
import os
import re
import subprocess
import sys
import time
import unicodedata
from pathlib import Path

import numpy as np
import pandas as pd

T0 = time.time()


def log(msg: str) -> None:
    print(f"[{time.time() - T0:7.0f}s] {msg}", flush=True)


try:
    import rapidfuzz  # noqa: F401
except ImportError:  # Kaggle image without it: needs internet enabled on the kernel
    subprocess.run([sys.executable, "-m", "pip", "install", "-q", "rapidfuzz"], check=True)
import lightgbm as lgb  # noqa: E402
from rapidfuzz import fuzz  # noqa: E402
from rapidfuzz.distance import JaroWinkler  # noqa: E402
from sklearn.feature_extraction.text import TfidfVectorizer  # noqa: E402
from sklearn.metrics import average_precision_score, precision_recall_curve, roc_auc_score  # noqa: E402
from sklearn.neighbors import NearestNeighbors  # noqa: E402

try:
    from rapidfuzz.process import cpdist
except ImportError:
    cpdist = None

SMOKE = os.environ.get("CANON_SMOKE") == "1"
if len(sys.argv) > 1:
    IN = Path(sys.argv[1])
else:  # the mount point of an attached dataset differs between Kaggle image generations, so look for the file
    hits = [p for p in Path("/kaggle/input").rglob("train.parquet")]
    if not hits:
        print("no train.parquet under /kaggle/input; contents:", [str(p) for p in Path("/kaggle/input").rglob("*")][:50], flush=True)
        raise SystemExit(1)
    IN = hits[0].parent
OUT = Path(sys.argv[2]) if len(sys.argv) > 2 else Path("/kaggle/working")
OUT.mkdir(parents=True, exist_ok=True)
K_GEO = 10
SEED = 7
LODGING = r"(?i)hotel|hostel|resort|motel|bed & breakfast|guest ?house|vacation rental|lodge|\binns?\b"
ATTRACTION = (r"(?i)museum|monument|historic|landmark|theme park|zoo|aquarium|scenic|temple|church|mosque|shrine|palace|castle"
              r"|garden|beach|art gallery|theater|stadium|amusement|waterfall|national park|tourist")


# ----------------------------------------------------------------------------- load and normalise
def norm_text(s):
    if s is None or (isinstance(s, float) and np.isnan(s)):
        return ""
    s = unicodedata.normalize("NFKD", str(s).lower())
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    return re.sub(r"\s+", " ", re.sub(r"[^\w ]+", " ", s)).strip()


df = pd.read_parquet(IN / "train.parquet")
if SMOKE:
    keep = df["point_of_interest"].drop_duplicates().sample(25000, random_state=SEED)
    df = df[df["point_of_interest"].isin(keep)].reset_index(drop=True)
log(f"records={len(df):,} places={df['point_of_interest'].nunique():,} smoke={SMOKE}")

df["nname"] = df["name"].map(norm_text)
df["naddr"] = df["address"].map(norm_text)
df["ncity"] = df["city"].map(norm_text)
df["nzip"] = df["zip"].fillna("").astype(str).str.replace(r"\W", "", regex=True).str.lower()
df["phone8"] = df["phone"].fillna("").astype(str).str.replace(r"\D", "", regex=True).str[-8:]
df.loc[df["phone8"].str.len() < 7, "phone8"] = ""
df["domain"] = df["url"].fillna("").astype(str).str.lower().str.extract(r"^(?:https?://)?(?:www\.)?([^/?#:]+)", expand=False).fillna("")
df["cats"] = df["categories"].fillna("").astype(str).str.lower()
df["country"] = df["country"].fillna("")
df["travel"] = np.where(df["cats"].str.contains(LODGING, regex=True), "lodging",
                        np.where(df["cats"].str.contains(ATTRACTION, regex=True), "attraction", "other"))

# worlds: places (not records) are split, so no place straddles two worlds
pois = df["point_of_interest"].drop_duplicates().sample(frac=1.0, random_state=SEED).to_numpy()
n = len(pois)
world_of = {p: ("test" if i < 0.2 * n else "valid" if i < 0.3 * n else "train") for i, p in enumerate(pois)}
df["world"] = df["point_of_interest"].map(world_of)
log("worlds: " + str(df["world"].value_counts().to_dict()))

tf_char = TfidfVectorizer(analyzer="char_wb", ngram_range=(2, 4), min_df=2, dtype=np.float32, sublinear_tf=True).fit(df["nname"])
tf_word = TfidfVectorizer(analyzer="word", token_pattern=r"\S+", min_df=1, dtype=np.float32).fit(df["nname"])
log(f"tfidf vocab char={len(tf_char.vocabulary_):,} word={len(tf_word.vocabulary_):,}")


# ----------------------------------------------------------------------------- blocking
def block(w: pd.DataFrame):
    """Candidate pairs (i < j, positions inside `w`) from geo kNN and from an exact normalised-name key."""
    xy = np.radians(w[["latitude", "longitude"]].to_numpy())
    k = min(K_GEO + 1, len(w))
    nn = NearestNeighbors(n_neighbors=k, algorithm="ball_tree", metric="haversine", n_jobs=-1).fit(xy)
    _, idx = nn.kneighbors(xy)
    i = np.repeat(np.arange(len(w)), k - 1)
    j = idx[:, 1:].ravel()
    rank = np.tile(np.arange(1, k), len(w))
    geo = pd.DataFrame({"i": np.minimum(i, j), "j": np.maximum(i, j), "geo_rank": rank})
    geo = geo[geo["i"] != geo["j"]].groupby(["i", "j"], as_index=False)["geo_rank"].min()
    # same normalised name inside one country, small groups only (chains are left to the geo generator)
    g = pd.DataFrame({"pos": np.arange(len(w)), "key": (w["country"] + "|" + w["nname"]).to_numpy(), "len": w["nname"].str.len().to_numpy()})
    g = g[g["len"] >= 4]
    sizes = g.groupby("key")["pos"].transform("size")
    g = g[(sizes >= 2) & (sizes <= 20)]
    nm = g.merge(g, on="key")
    nm = nm[nm["pos_x"] < nm["pos_y"]][["pos_x", "pos_y"]].rename(columns={"pos_x": "i", "pos_y": "j"})
    nm["by_name"] = 1
    geo["by_geo"] = 1
    pairs = geo.merge(nm, on=["i", "j"], how="outer")
    pairs["geo_rank"] = pairs["geo_rank"].fillna(K_GEO + 5).astype(np.int16)
    pairs["by_geo"] = pairs["by_geo"].fillna(0).astype(np.int8)
    pairs["by_name"] = pairs["by_name"].fillna(0).astype(np.int8)
    return pairs.reset_index(drop=True)


def haversine(lat1, lon1, lat2, lon2):
    p1, p2 = np.radians(lat1), np.radians(lat2)
    a = np.sin((p2 - p1) / 2) ** 2 + np.cos(p1) * np.cos(p2) * np.sin(np.radians(lon2 - lon1) / 2) ** 2
    return 2 * 6371000 * np.arcsin(np.sqrt(a))


def scorer(a, b, fn):
    if cpdist is not None:
        return cpdist(a, b, scorer=fn, workers=-1, dtype=np.float32)
    return np.fromiter((fn(x, y) for x, y in zip(a, b)), dtype=np.float32, count=len(a))


def rowdot(vec, a, b, chunk=400_000):
    out = np.empty(len(a), dtype=np.float32)
    for s in range(0, len(a), chunk):
        A, B = vec.transform(a[s:s + chunk]), vec.transform(b[s:s + chunk])
        out[s:s + chunk] = np.asarray(A.multiply(B).sum(axis=1)).ravel()
    return out


def features(w: pd.DataFrame, pairs: pd.DataFrame) -> pd.DataFrame:
    a, b = w.iloc[pairs["i"].to_numpy()], w.iloc[pairs["j"].to_numpy()]
    na, nb = a["nname"].to_numpy(), b["nname"].to_numpy()
    f = pd.DataFrame(index=pairs.index)
    d = haversine(a["latitude"].to_numpy(), a["longitude"].to_numpy(), b["latitude"].to_numpy(), b["longitude"].to_numpy())
    f["dist_m"] = d.astype(np.float32)
    f["log_dist"] = np.log1p(d).astype(np.float32)
    f["geo_rank"] = pairs["geo_rank"].to_numpy()
    f["by_name"] = pairs["by_name"].to_numpy()
    f["name_jw"] = scorer(na, nb, JaroWinkler.normalized_similarity)
    f["name_token_set"] = scorer(na, nb, fuzz.token_set_ratio) / 100
    f["name_token_sort"] = scorer(na, nb, fuzz.token_sort_ratio) / 100
    f["name_partial"] = scorer(na, nb, fuzz.partial_ratio) / 100
    f["name_ratio"] = scorer(na, nb, fuzz.ratio) / 100
    f["name_tfidf_char"] = rowdot(tf_char, na, nb)
    f["name_tfidf_word"] = rowdot(tf_word, na, nb)
    la, lb = a["nname"].str.len().to_numpy(), b["nname"].str.len().to_numpy()
    f["name_len_min"] = np.minimum(la, lb)
    f["name_len_ratio"] = (np.minimum(la, lb) / np.maximum(np.maximum(la, lb), 1)).astype(np.float32)
    f["name_nonascii"] = (a["name"].fillna("").str.contains(r"[^\x00-\x7F]").to_numpy() | b["name"].fillna("").str.contains(r"[^\x00-\x7F]").to_numpy()).astype(np.int8)
    aa, ab = a["naddr"].to_numpy(), b["naddr"].to_numpy()
    both_addr = (a["naddr"].str.len().to_numpy() > 0) & (b["naddr"].str.len().to_numpy() > 0)
    f["addr_token_set"] = np.where(both_addr, scorer(aa, ab, fuzz.token_set_ratio) / 100, np.nan).astype(np.float32)
    for col, name in (("ncity", "city_eq"), ("nzip", "zip_eq"), ("phone8", "phone_eq"), ("domain", "domain_eq"), ("country", "country_eq")):
        x, y = a[col].to_numpy(), b[col].to_numpy()
        both = (x != "") & (y != "")
        f[name] = np.where(both, (x == y).astype(np.float32), np.nan).astype(np.float32)
    ca, cb = a["cats"].to_numpy(), b["cats"].to_numpy()
    both_cat = (ca != "") & (cb != "")
    f["cat_token_set"] = np.where(both_cat, scorer(ca, cb, fuzz.token_set_ratio) / 100, np.nan).astype(np.float32)
    f["cat_eq"] = np.where(both_cat, (ca == cb).astype(np.float32), np.nan).astype(np.float32)
    f["n_missing"] = ((a[["naddr", "ncity", "nzip", "phone8", "domain", "cats"]].to_numpy() == "").sum(1)
                      + (b[["naddr", "ncity", "nzip", "phone8", "domain", "cats"]].to_numpy() == "").sum(1)).astype(np.int8)
    return f


worlds = {}
for name in ("train", "valid", "test"):
    w = df[df["world"] == name].reset_index(drop=True)
    pairs = block(w)
    poi = w["point_of_interest"].to_numpy()
    pairs["y"] = (poi[pairs["i"].to_numpy()] == poi[pairs["j"].to_numpy()]).astype(np.int8)
    sz = w.groupby("point_of_interest").size().to_numpy()
    true_pairs = int((sz * (sz - 1) // 2).sum())
    geo_tp = int(pairs.loc[pairs["by_geo"] == 1, "y"].sum())
    # record-level recall: a record of a multi-record place is recoverable if at least one of its duplicates is a candidate
    multi = int(sz[sz > 1].sum())
    hit = pairs[pairs["y"] == 1]
    reachable = len(np.union1d(hit["i"].to_numpy(), hit["j"].to_numpy()))
    stats = {"records": len(w), "true_pairs": true_pairs, "candidates": len(pairs), "candidates_per_record": len(pairs) / len(w),
             "pair_recall_geo": geo_tp / true_pairs, "pair_recall_union": int(pairs["y"].sum()) / true_pairs,
             "record_recall_union": reachable / max(multi, 1), "candidate_match_rate": float(pairs["y"].mean())}
    log(f"{name}: {json.dumps({k: round(v, 4) if isinstance(v, float) else v for k, v in stats.items()})}")
    X = features(w, pairs)
    log(f"{name}: features {X.shape}")
    worlds[name] = (w, pairs, X, stats)

# ----------------------------------------------------------------------------- model
FEATS = list(worlds["train"][2].columns)
dtr = lgb.Dataset(worlds["train"][2], worlds["train"][1]["y"])
dva = lgb.Dataset(worlds["valid"][2], worlds["valid"][1]["y"], reference=dtr)
params = dict(objective="binary", learning_rate=0.06, num_leaves=127, min_data_in_leaf=60, feature_fraction=0.8, bagging_fraction=0.8,
              bagging_freq=1, lambda_l2=1.0, verbose=-1, seed=SEED, num_threads=os.cpu_count())
model = lgb.train(params, dtr, num_boost_round=200 if SMOKE else 3000, valid_sets=[dva],
                  callbacks=[lgb.early_stopping(80), lgb.log_evaluation(200)])
log(f"best_iteration={model.best_iteration}")
model.save_model(str(OUT / "fsq_pair_model.lgb"), num_iteration=model.best_iteration)


# ----------------------------------------------------------------------------- evaluation
def cluster_iou(w, pairs, keep_mask):
    """Competition-style score: connected components of accepted pairs, mean per-record IoU against the true place."""
    parent = np.arange(len(w))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for i, j in zip(pairs["i"].to_numpy()[keep_mask], pairs["j"].to_numpy()[keep_mask]):
        ri, rj = find(i), find(j)
        if ri != rj:
            parent[ri] = rj
    root = np.fromiter((find(x) for x in range(len(w))), dtype=np.int64, count=len(w))
    t = pd.DataFrame({"root": root, "poi": w["point_of_interest"].to_numpy()})
    inter = t.groupby(["root", "poi"])["poi"].transform("size")
    pred, true = t.groupby("root")["poi"].transform("size"), t.groupby("poi")["poi"].transform("size")
    b3p, b3r = float((inter / pred).mean()), float((inter / true).mean())
    B3.update(precision=b3p, recall=b3r, f1=2 * b3p * b3r / max(b3p + b3r, 1e-9))
    return float((inter / (pred + true - inter)).mean()), int(pred.max())


B3 = {}  # B-cubed scores of the most recent cluster_iou call


def pr_at(y, p, total_true, thr):
    keep = p >= thr
    tp = int(y[keep].sum())
    prec = tp / max(int(keep.sum()), 1)
    return {"threshold": float(thr), "precision": prec, "recall_of_candidates": tp / max(int(y.sum()), 1), "recall_end_to_end": tp / total_true,
            "accepted": int(keep.sum())}


def evaluate(name, thr_cluster=None):
    w, pairs, X, stats = worlds[name]
    y = pairs["y"].to_numpy()
    p = model.predict(X, num_iteration=model.best_iteration)
    res = {"blocking": stats, "auc": float(roc_auc_score(y, p)), "average_precision": float(average_precision_score(y, p))}
    prec, rec, thr = precision_recall_curve(y, p)
    res["operating_points"] = {}
    for target in (0.90, 0.95, 0.99, 0.995):
        ok = np.where(prec[:-1] >= target)[0]
        res["operating_points"][f"precision>={target}"] = pr_at(y, p, stats["true_pairs"], thr[ok[0]]) if len(ok) else None
    res["operating_points"]["threshold=0.5"] = pr_at(y, p, stats["true_pairs"], 0.5)
    # rule baselines on the same candidates
    base = {"name_jw>=0.9 & dist<200m": (X["name_jw"].to_numpy() >= 0.9) & (X["dist_m"].to_numpy() < 200),
            "name_token_set>=0.9 & dist<500m": (X["name_token_set"].to_numpy() >= 0.9) & (X["dist_m"].to_numpy() < 500),
            "exact normalised name & dist<1km": (X["name_ratio"].to_numpy() >= 0.999) & (X["dist_m"].to_numpy() < 1000)}
    res["baselines"] = {}
    for k, m in base.items():
        tp = int(y[m].sum())
        pr, rc = tp / max(int(m.sum()), 1), tp / stats["true_pairs"]
        iou, _ = cluster_iou(w, pairs, m)
        res["baselines"][k] = {"pair_precision": pr, "pair_recall_end_to_end": rc, "cluster_iou": iou, "b3": dict(B3)}
    # cluster score: threshold picked on the validation world, then applied unchanged to test
    if thr_cluster is None:
        grid = np.arange(0.30, 0.96, 0.05)
        scores = [cluster_iou(w, pairs, p >= t)[0] for t in grid]
        thr_cluster = float(grid[int(np.argmax(scores))])
        res["iou_by_threshold"] = {f"{t:.2f}": s for t, s in zip(grid, scores)}
    iou, biggest = cluster_iou(w, pairs, p >= thr_cluster)
    op = pr_at(y, p, stats["true_pairs"], thr_cluster)
    res["cluster"] = {"threshold": thr_cluster, "iou": iou, "b3_precision": B3["precision"], "b3_recall": B3["recall"], "b3_f1": B3["f1"],
                      "largest_predicted_cluster": biggest, **op}
    # the ceiling blocking allows: accept every true candidate pair, nothing else
    iou_ceiling, _ = cluster_iou(w, pairs, y == 1)
    res["blocking_ceiling"] = {"cluster_iou": iou_ceiling, "b3": dict(B3)}
    # travel slice: pairs where both records are lodging / attraction
    tv = w["travel"].to_numpy()
    res["slices"] = {}
    for s in ("lodging", "attraction"):
        m = (tv[pairs["i"].to_numpy()] == s) & (tv[pairs["j"].to_numpy()] == s)
        if m.sum() > 100 and y[m].sum() > 10:
            ys, ps = y[m], p[m]
            pr_, rc_, th_ = precision_recall_curve(ys, ps)
            ok = np.where(pr_[:-1] >= 0.99)[0]
            res["slices"][s] = {"pairs": int(m.sum()), "matches": int(ys.sum()), "auc": float(roc_auc_score(ys, ps)),
                                "average_precision": float(average_precision_score(ys, ps)),
                                "recall_of_candidates_at_precision_0.99": float(rc_[ok[0]]) if len(ok) else None}
    # cascade share: how many candidates the model settles with high confidence on its own
    res["confidence_bands"] = {"auto_reject_p<0.02": float((p < 0.02).mean()), "auto_accept_p>0.98": float((p > 0.98).mean()),
                               "uncertain_0.02-0.98": float(((p >= 0.02) & (p <= 0.98)).mean())}
    # keep a thin PR curve for plotting
    step = max(len(thr) // 200, 1)
    res["pr_curve"] = {"precision": prec[:-1][::step].round(5).tolist(), "recall": rec[:-1][::step].round(5).tolist(),
                       "threshold": thr[::step].round(5).tolist()}
    return res, thr_cluster


valid_res, thr = evaluate("valid")
test_res, _ = evaluate("test", thr)
imp = pd.DataFrame({"feature": FEATS, "gain": model.feature_importance("gain"), "split": model.feature_importance("split")})
imp["gain_share"] = imp["gain"] / imp["gain"].sum()
imp = imp.sort_values("gain", ascending=False)
out = {"smoke": SMOKE, "records": len(df), "places": int(df["point_of_interest"].nunique()), "k_geo": K_GEO, "features": FEATS,
       "best_iteration": int(model.best_iteration), "valid": valid_res, "test": test_res,
       "feature_importance": imp.to_dict("records"), "seconds": time.time() - T0}
(OUT / "metrics.json").write_text(json.dumps(out, indent=1))
log("TEST  " + json.dumps({"auc": round(test_res["auc"], 4), "ap": round(test_res["average_precision"], 4),
                           "cluster": {k: round(v, 4) if isinstance(v, float) else v for k, v in test_res["cluster"].items()},
                           "ceiling_iou": round(test_res["blocking_ceiling"]["cluster_iou"], 4),
                           "baselines": {k: round(v["cluster_iou"], 4) for k, v in test_res["baselines"].items()}}))
log("top features: " + ", ".join(f"{r.feature}={r.gain_share:.2f}" for r in imp.head(8).itertuples()))
log("done")
