"""Foursquare Location Matching, pipeline v2, stage 1: retrieval, pair features, two-stage GBDT, cluster scores.

What changed from v1 (kaggle/fsq_pair_model/train.py), following the published 1st-place recipe of the 2022 competition
and the dense-retrieval design of the BER v7 entity-resolution pipeline:
  * Evaluation at competition density: places are split 50 / 50 into worlds A and B (about 570k records each, close to the
    competition's hidden test of about 600k). Everything is cross-fitted: a model trained on A scores B and vice versa.
    Thresholds are picked on A and the headline score is B, so no number is tuned on the world it reports.
  * Retrieval: geo k-NN pool (100), the 10 nearest, the 10 most name-similar inside the pool by a fine-tuned multilingual
    encoder, a country-wide encoder search for far-away duplicates (top 6 within 100 km), and the exact-name key.
    The encoder (multilingual-e5-small) is fine-tuned contrastively on the *other* world's duplicates, so the embedding
    features of each world are out-of-sample.
  * About 60 pair features (v1 had 23), then a second GBDT on collective features: how strongly each record prefers
    its other candidates, ranks, and two-hop support through a shared neighbour.
  * Post-processing: per-record match lists with two-hop completion, compared with plain connected components.
Outputs per-world pair scores for stage 2 (cross-encoder re-ranking, kaggle/fsq_v2_xenc).

Kaggle (GPU kernel, internet on):  python stage1.py
Local smoke test:  CANON_SMOKE=1 python -I stage1.py <dir with train.parquet> <out dir> [model dir or hub id]
The data is under competition terms: this is a research benchmark, not a shippable artefact.
"""
import gc
import json
import os
import re
import subprocess
import sys
import time
import unicodedata
import zlib
from pathlib import Path

import numpy as np
import pandas as pd

T0 = time.time()


def log(msg: str) -> None:
    print(f"[{time.time() - T0:7.0f}s] {msg}", flush=True)


try:
    import rapidfuzz  # noqa: F401
except ImportError:
    subprocess.run([sys.executable, "-m", "pip", "install", "-q", "rapidfuzz"], check=True)
import scipy.sparse as sp  # noqa: E402
import torch  # noqa: E402
import torch.nn.functional as TF  # noqa: E402
from rapidfuzz import fuzz  # noqa: E402
from rapidfuzz.distance import JaroWinkler  # noqa: E402
from rapidfuzz.process import cpdist  # noqa: E402
from scipy.sparse.csgraph import connected_components  # noqa: E402
from sklearn.feature_extraction.text import TfidfVectorizer  # noqa: E402
from sklearn.metrics import average_precision_score, roc_auc_score  # noqa: E402
from sklearn.neighbors import NearestNeighbors  # noqa: E402
from transformers import AutoModel, AutoTokenizer  # noqa: E402

SMOKE = os.environ.get("CANON_SMOKE") == "1"
if len(sys.argv) > 1:
    IN = Path(sys.argv[1])
else:
    hits = list(Path("/kaggle/input").rglob("train.parquet"))
    if not hits:
        raise SystemExit("no train.parquet under /kaggle/input")
    IN = hits[0].parent
OUT = Path(sys.argv[2]) if len(sys.argv) > 2 else Path("/kaggle/working")
OUT.mkdir(parents=True, exist_ok=True)
ENC_BASE = sys.argv[3] if len(sys.argv) > 3 else "intfloat/multilingual-e5-small"
DEV = "cuda" if torch.cuda.is_available() else "cpu"
SEED = 7
K_POOL, K_GEO, K_EMB = 100, 10, 10          # geo pool, nearest kept, name-nearest kept from the pool
K_GLOB_SEARCH, K_GLOB, GLOB_RADIUS = 30, 6, 100_000.0
ENC_PAIRS_PER_PLACE, ENC_EPOCHS, ENC_BATCH, ENC_LEN = 4, 2, 256, 32
LODGING = r"(?i)hotel|hostel|resort|motel|bed & breakfast|guest ?house|vacation rental|lodge|\binns?\b"
ATTRACTION = (r"(?i)museum|monument|historic|landmark|theme park|zoo|aquarium|scenic|temple|church|mosque|shrine|palace|castle"
              r"|garden|beach|art gallery|theater|stadium|amusement|waterfall|national park|tourist")
rng = np.random.default_rng(SEED)
torch.manual_seed(SEED)
log(f"device={DEV} smoke={SMOKE} encoder={ENC_BASE}")


# ============================================================================ load and normalise
def norm_text(s):
    if not isinstance(s, str):
        return ""
    s = unicodedata.normalize("NFKD", s.lower())
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    return re.sub(r"\s+", " ", re.sub(r"[^\w ]+", " ", s)).strip()


df = pd.read_parquet(IN / "train.parquet")
if SMOKE:
    keep = df["point_of_interest"].drop_duplicates().sample(30000, random_state=SEED)
    df = df[df["point_of_interest"].isin(keep)].reset_index(drop=True)
log(f"records={len(df):,} places={df['point_of_interest'].nunique():,}")
for c in ("name", "address", "city", "state", "zip", "country", "url", "phone", "categories"):
    df[c] = df[c].where(df[c].notna(), None)
df["nname"] = df["name"].map(norm_text)
df["naddr"] = df["address"].map(norm_text)
df["ncity"] = df["city"].map(norm_text)
df["nstate"] = df["state"].map(norm_text)
df["nzip"] = df["zip"].fillna("").astype(str).str.replace(r"\W", "", regex=True).str.lower()
df["phone8"] = df["phone"].fillna("").astype(str).str.replace(r"\D", "", regex=True).str[-8:]
df.loc[df["phone8"].str.len() < 7, "phone8"] = ""
df["domain"] = df["url"].fillna("").astype(str).str.lower().str.extract(r"^(?:https?://)?(?:www\.)?([^/?#:]+)", expand=False).fillna("")
df["cats"] = df["categories"].fillna("").astype(str).str.lower()
df["cat1"] = df["cats"].str.split(",").str[0].str.strip().fillna("")
df["country"] = df["country"].fillna("")
df["ndig"] = df["nname"].map(lambda s: " ".join(re.findall(r"\d+", s)))
df["nonascii"] = df["name"].fillna("").str.contains(r"[^\x00-\x7F]").astype(np.int8)
df["travel"] = np.where(df["cats"].str.contains(LODGING, regex=True), "lodging",
                        np.where(df["cats"].str.contains(ATTRACTION, regex=True), "attraction", "other"))

pois = df["point_of_interest"].drop_duplicates().sample(frac=1.0, random_state=SEED).to_numpy()
world_of = {p: ("A" if k < len(pois) // 2 else "B") for k, p in enumerate(pois)}
df["world"] = df["point_of_interest"].map(world_of)
log("worlds: " + str(df["world"].value_counts().to_dict()))

# vectorisers are unsupervised, so they are fitted once on every record of both worlds
VEC = {
    "name_c": TfidfVectorizer(analyzer="char_wb", ngram_range=(2, 4), min_df=2, dtype=np.float32, sublinear_tf=True).fit(df["nname"]),
    "name_w": TfidfVectorizer(analyzer="word", token_pattern=r"\S+", dtype=np.float32, sublinear_tf=True).fit(df["nname"]),
    "addr_c": TfidfVectorizer(analyzer="char_wb", ngram_range=(2, 3), min_df=2, dtype=np.float32, sublinear_tf=True).fit(df["naddr"]),
    "cat_w": TfidfVectorizer(analyzer="word", token_pattern=r"[^,]+", dtype=np.float32).fit(df["cats"].str.replace(", ", ",")),
}
log("tf-idf fitted")


# ============================================================================ name encoder (fine-tuned on the other world)
def enc_texts(names):
    return ["query: " + (s if isinstance(s, str) else "") for s in names]


def encode(model, tok, texts, bs=1024):
    model.eval()
    out = np.empty((len(texts), model.config.hidden_size), dtype=np.float16)
    with torch.no_grad(), torch.autocast(device_type="cuda", dtype=torch.float16, enabled=DEV == "cuda"):
        for s in range(0, len(texts), bs):
            b = tok(texts[s:s + bs], padding=True, truncation=True, max_length=ENC_LEN, return_tensors="pt").to(DEV)
            h = model(**b).last_hidden_state
            m = b["attention_mask"].unsqueeze(-1).to(h.dtype)
            e = TF.normalize((h * m).sum(1) / m.sum(1).clamp(min=1), dim=-1)
            out[s:s + bs] = e.float().cpu().numpy().astype(np.float16)
    return out


def train_encoder(w: pd.DataFrame):
    """Symmetric InfoNCE on (record, duplicate) name pairs of one world, in-batch negatives."""
    tok = AutoTokenizer.from_pretrained(ENC_BASE)
    model = AutoModel.from_pretrained(ENC_BASE).to(DEV)
    g = w[["point_of_interest", "name"]].reset_index(drop=True)
    g = g[g["point_of_interest"].map(g["point_of_interest"].value_counts()) >= 2]
    g = g.sample(frac=1.0, random_state=SEED)
    a, b = [], []
    for _, grp in g.groupby("point_of_interest", sort=False):
        names = grp["name"].tolist()
        for k in range(min(len(names) - 1, ENC_PAIRS_PER_PLACE)):
            a.append(names[k])
            b.append(names[k + 1])
    a, b = np.array(enc_texts(a), dtype=object), np.array(enc_texts(b), dtype=object)
    n = len(a)
    steps = ENC_EPOCHS * (n // ENC_BATCH)
    opt = torch.optim.AdamW(model.parameters(), lr=5e-5, weight_decay=0.01)
    sched = torch.optim.lr_scheduler.OneCycleLR(opt, max_lr=5e-5, total_steps=max(steps, 1), pct_start=0.06, anneal_strategy="linear")
    scaler = torch.amp.GradScaler("cuda", enabled=DEV == "cuda")
    model.train()
    step, t0 = 0, time.time()
    for ep in range(ENC_EPOCHS):
        perm = rng.permutation(n)
        for s in range(0, n - ENC_BATCH + 1, ENC_BATCH):
            ix = perm[s:s + ENC_BATCH]
            ba = tok(list(a[ix]), padding=True, truncation=True, max_length=ENC_LEN, return_tensors="pt").to(DEV)
            bb = tok(list(b[ix]), padding=True, truncation=True, max_length=ENC_LEN, return_tensors="pt").to(DEV)
            with torch.autocast(device_type="cuda", dtype=torch.float16, enabled=DEV == "cuda"):
                def emb(x):
                    h = model(**x).last_hidden_state
                    m = x["attention_mask"].unsqueeze(-1).to(h.dtype)
                    return TF.normalize(((h * m).sum(1) / m.sum(1).clamp(min=1)).float(), dim=-1)
                ea, eb = emb(ba), emb(bb)
                logits = ea @ eb.T / 0.05
                lab = torch.arange(len(ix), device=DEV)
                loss = (TF.cross_entropy(logits, lab) + TF.cross_entropy(logits.T, lab)) / 2
            opt.zero_grad(set_to_none=True)
            scaler.scale(loss).backward()
            scaler.step(opt)
            scaler.update()
            sched.step()
            step += 1
            if step % 200 == 0:
                log(f"  encoder step {step}/{steps} loss={loss.item():.3f} ({(time.time() - t0) / step:.2f}s/step)")
    log(f"  encoder trained on {n:,} pairs, {step} steps")
    return model, tok


# ============================================================================ retrieval
def pool_knn(w):
    xy = np.radians(w[["latitude", "longitude"]].to_numpy(dtype=float))
    n = len(w)
    k = min(K_POOL + 1, n)
    nn = NearestNeighbors(n_neighbors=k, algorithm="ball_tree", metric="haversine", n_jobs=-1).fit(xy)
    dist, idx = nn.kneighbors(xy)
    self_m = idx == np.arange(n)[:, None]
    order = np.argsort(self_m, axis=1, kind="stable")  # self (if present) moves to the end
    idx = np.take_along_axis(idx, order, 1)[:, :k - 1].astype(np.int32)
    dist = (np.take_along_axis(dist, order, 1)[:, :k - 1] * 6371000).astype(np.float32)
    return idx, dist


def haversine(lat1, lon1, lat2, lon2):
    p1, p2 = np.radians(lat1), np.radians(lat2)
    a = np.sin((p2 - p1) / 2) ** 2 + np.cos(p1) * np.cos(p2) * np.sin(np.radians(lon2 - lon1) / 2) ** 2
    return 2 * 6371000 * np.arcsin(np.sqrt(np.clip(a, 0, 1)))


def retrieve(w, E):
    """Undirected candidate pairs (i < j) with generator bits (1 geo, 2 emb-in-pool, 4 country-wide emb, 8 exact name)
    and the rank lookups used as features."""
    n = len(w)
    idx, dist = pool_knn(w)
    K = idx.shape[1]
    Et = torch.from_numpy(E).to(DEV)
    if DEV == "cpu":
        Et = Et.float()
    cos_pool = np.empty((n, K), dtype=np.float32)
    for s in range(0, n, 4096):
        I = torch.from_numpy(idx[s:s + 4096].astype(np.int64)).to(DEV)
        cos_pool[s:s + 4096] = (Et[I] * Et[s:s + 4096, None, :]).sum(-1).float().cpu().numpy()
    emb_order = np.argsort(-cos_pool, axis=1, kind="stable")
    emb_rank = np.empty_like(emb_order)
    np.put_along_axis(emb_rank, emb_order, np.arange(1, K + 1)[None, :].repeat(n, 0), axis=1)
    geo_rank = np.arange(1, K + 1)[None, :].repeat(n, 0)
    src = np.arange(n)[:, None].repeat(K, 1)
    m_geo, m_emb = geo_rank <= K_GEO, emb_rank <= K_EMB
    di = [src[m_geo], src[m_emb]]
    dj = [idx[m_geo], idx[m_emb]]
    db = [np.full(m_geo.sum(), 1, np.int8), np.full(m_emb.sum(), 2, np.int8)]
    # country-wide encoder search: far-away duplicates the geo pool cannot reach
    lat, lon = w["latitude"].to_numpy(dtype=float), w["longitude"].to_numpy(dtype=float)
    gi, gj, gc_ = [], [], []
    for _, rows in w.groupby("country").indices.items():
        if len(rows) < 2:
            continue
        rows_t = torch.from_numpy(rows.astype(np.int64)).to(DEV)
        Ec = Et[rows_t]
        kk = min(K_GLOB_SEARCH, len(rows) - 1)
        for s in range(0, len(rows), 2048):
            S = Ec[s:s + 2048] @ Ec.T
            r = torch.arange(S.shape[0], device=DEV)
            S[r, s + r] = -10
            val, top = S.float().topk(kk, dim=1)
            gi.append(np.repeat(rows[s:s + 2048], kk))
            gj.append(rows[top.cpu().numpy()].ravel())
            gc_.append(val.cpu().numpy().ravel())
    if gi:
        gi, gj, gc_ = np.concatenate(gi), np.concatenate(gj), np.concatenate(gc_)
        ok = haversine(lat[gi], lon[gi], lat[gj], lon[gj]) <= GLOB_RADIUS
        g = pd.DataFrame({"i": gi[ok], "j": gj[ok], "c": gc_[ok]}).sort_values(["i", "c"], ascending=[True, False])
        g = g[g.groupby("i").cumcount() < K_GLOB]
        di.append(g["i"].to_numpy())
        dj.append(g["j"].to_numpy())
        db.append(np.full(len(g), 4, np.int8))
    # exact normalised name inside a country, small groups only
    e = pd.DataFrame({"pos": np.arange(n), "key": (w["country"] + "|" + w["nname"]).to_numpy(), "len": w["nname"].str.len().to_numpy()})
    e = e[e["len"] >= 3]
    e = e[e.groupby("key")["pos"].transform("size").between(2, 20)]
    ee = e.merge(e, on="key")
    ee = ee[ee["pos_x"] < ee["pos_y"]]
    di.append(ee["pos_x"].to_numpy())
    dj.append(ee["pos_y"].to_numpy())
    db.append(np.full(len(ee), 8, np.int8))
    i_, j_, b_ = np.concatenate(di).astype(np.int64), np.concatenate(dj).astype(np.int64), np.concatenate(db)
    keep = i_ != j_
    i_, j_, b_ = i_[keep], j_[keep], b_[keep]
    a, b = np.minimum(i_, j_), np.maximum(i_, j_)
    key = a * n + b
    o = np.argsort(key, kind="stable")
    key, b_ = key[o], b_[o]
    uk, start = np.unique(key, return_index=True)
    bits = np.bitwise_or.reduceat(b_, start)
    P = pd.DataFrame({"i": (uk // n).astype(np.int32), "j": (uk % n).astype(np.int32), "gen": bits})
    # rank lookups in both directions (rank K+1 = outside the pool)
    pk = (src.astype(np.int64) * n + idx).ravel()
    o = np.argsort(pk)
    pk_s, geo_s, emb_s = pk[o], geo_rank.ravel()[o], emb_rank.ravel()[o]

    def look(q, arr):
        pos = np.clip(np.searchsorted(pk_s, q), 0, len(pk_s) - 1)
        return np.where(pk_s[pos] == q, arr[pos], K + 1).astype(np.int16)

    qij = P["i"].to_numpy().astype(np.int64) * n + P["j"].to_numpy()
    qji = P["j"].to_numpy().astype(np.int64) * n + P["i"].to_numpy()
    P["geo_rank_ij"], P["geo_rank_ji"] = look(qij, geo_s), look(qji, geo_s)
    P["emb_rank_ij"], P["emb_rank_ji"] = look(qij, emb_s), look(qji, emb_s)
    kd = {"kd1": dist[:, 0], "kd5": dist[:, min(4, K - 1)], "kd20": dist[:, min(19, K - 1)]}
    del cos_pool, emb_order, emb_rank, geo_rank, src, pk, o, pk_s, geo_s, emb_s
    gc.collect()
    return P, kd


# ============================================================================ pair features
def slen(x):
    return pd.Series(x).str.len().fillna(0).to_numpy()


def sc(x, y, fn):
    return cpdist(x, y, scorer=fn, workers=-1, dtype=np.float32)


def rowdot(vec, x, y, chunk=400_000):
    out = np.empty(len(x), dtype=np.float32)
    for s in range(0, len(x), chunk):
        out[s:s + chunk] = np.asarray(vec.transform(x[s:s + chunk]).multiply(vec.transform(y[s:s + chunk])).sum(axis=1)).ravel()
    return out


def eq_feat(x, y):
    both = (x != "") & (y != "")
    return np.where(both, (x == y).astype(np.float32), np.nan).astype(np.float32)


def sim_feat(x, y, fn, min_len=1):
    lx, ly = slen(x), slen(y)
    both = (lx >= min_len) & (ly >= min_len)
    out = np.full(len(x), np.nan, dtype=np.float32)
    if both.any():
        out[both] = sc(x[both], y[both], fn)
    return out


def features(w, P, E, kd):
    i, j = P["i"].to_numpy(), P["j"].to_numpy()
    F = pd.DataFrame(index=P.index)
    lat, lon = w["latitude"].to_numpy(dtype=float), w["longitude"].to_numpy(dtype=float)
    d = haversine(lat[i], lon[i], lat[j], lon[j]).astype(np.float32)
    F["dist_m"], F["log_dist"] = d, np.log1p(d)
    for k in ("kd1", "kd5", "kd20"):
        a, b = kd[k][i], kd[k][j]
        F[f"{k}_min"], F[f"{k}_max"] = np.minimum(a, b), np.maximum(a, b)
    F["dist_rel5"] = d / (F["kd5_min"].to_numpy() + 1.0)
    F["dist_rel20"] = d / (F["kd20_max"].to_numpy() + 1.0)
    gr = np.stack([P["geo_rank_ij"].to_numpy(), P["geo_rank_ji"].to_numpy()])
    er = np.stack([P["emb_rank_ij"].to_numpy(), P["emb_rank_ji"].to_numpy()])
    F["geo_rank"], F["geo_rank_max"] = gr.min(0), gr.max(0)
    F["emb_rank"], F["emb_rank_max"] = er.min(0), er.max(0)
    g = P["gen"].to_numpy()
    F["by_geo"], F["by_emb"], F["by_glob"], F["by_name"] = (g & 1) > 0, (g & 2) > 0, (g & 4) > 0, (g & 8) > 0
    F[["by_geo", "by_emb", "by_glob", "by_name"]] = F[["by_geo", "by_emb", "by_glob", "by_name"]].astype(np.int8)
    cos = np.empty(len(P), dtype=np.float32)
    Ef = E.astype(np.float32)
    for s in range(0, len(P), 1_000_000):
        cos[s:s + 1_000_000] = np.einsum("ij,ij->i", Ef[i[s:s + 1_000_000]], Ef[j[s:s + 1_000_000]])
    F["emb_cos"] = cos
    na, nb = w["nname"].to_numpy()[i], w["nname"].to_numpy()[j]
    F["name_jw"] = sc(na, nb, JaroWinkler.normalized_similarity)
    F["name_token_set"] = sc(na, nb, fuzz.token_set_ratio) / 100
    F["name_token_sort"] = sc(na, nb, fuzz.token_sort_ratio) / 100
    F["name_partial"] = sc(na, nb, fuzz.partial_ratio) / 100
    F["name_ratio"] = sc(na, nb, fuzz.ratio) / 100
    F["name_wratio"] = sc(na, nb, fuzz.WRatio) / 100
    F["name_tfidf_char"] = rowdot(VEC["name_c"], na, nb)
    F["name_tfidf_word"] = rowdot(VEC["name_w"], na, nb)
    la, lb = slen(na), slen(nb)
    F["name_len_min"], F["name_len_max"] = np.minimum(la, lb), np.maximum(la, lb)
    F["name_len_ratio"] = (np.minimum(la, lb) / np.maximum(np.maximum(la, lb), 1)).astype(np.float32)
    F["name_prefix_eq"] = (pd.Series(na).str[:4].to_numpy() == pd.Series(nb).str[:4].to_numpy()).astype(np.int8)
    nonasc = w["nonascii"].to_numpy()
    F["name_nonascii"] = (nonasc[i] | nonasc[j]).astype(np.int8)
    F["name_nonascii_both"] = (nonasc[i] & nonasc[j]).astype(np.int8)
    F["name_num_eq"] = eq_feat(w["ndig"].to_numpy()[i], w["ndig"].to_numpy()[j])
    freq = w["nname"].map(w["nname"].value_counts()).to_numpy().astype(np.float32)
    F["name_freq_min"], F["name_freq_max"] = np.minimum(freq[i], freq[j]), np.maximum(freq[i], freq[j])
    aa, ab = w["naddr"].to_numpy()[i], w["naddr"].to_numpy()[j]
    F["addr_token_set"] = sim_feat(aa, ab, fuzz.token_set_ratio, 1) / 100
    F["addr_ratio"] = sim_feat(aa, ab, fuzz.ratio, 1) / 100
    F["addr_partial"] = sim_feat(aa, ab, fuzz.partial_ratio, 1) / 100
    both_addr = (slen(aa) > 0) & (slen(ab) > 0)
    F["addr_tfidf"] = np.where(both_addr, rowdot(VEC["addr_c"], aa, ab), np.nan).astype(np.float32)
    # name of one side inside the address of the other (venues inside malls, stations, airports)
    F["name_in_addr"] = np.maximum(sim_feat(na, ab, fuzz.partial_ratio, 3), sim_feat(nb, aa, fuzz.partial_ratio, 3)) / 100
    for col, nm in (("ncity", "city"), ("nstate", "state")):
        x, y = w[col].to_numpy()[i], w[col].to_numpy()[j]
        F[f"{nm}_eq"] = eq_feat(x, y)
        F[f"{nm}_jw"] = sim_feat(x, y, JaroWinkler.normalized_similarity, 1)
    za, zb = w["nzip"].to_numpy()[i], w["nzip"].to_numpy()[j]
    F["zip_eq"] = eq_feat(za, zb)
    F["zip_prefix3_eq"] = eq_feat(pd.Series(za).str[:3].to_numpy(), pd.Series(zb).str[:3].to_numpy())
    F["phone_eq"] = eq_feat(w["phone8"].to_numpy()[i], w["phone8"].to_numpy()[j])
    ua, ub = w["domain"].to_numpy()[i], w["domain"].to_numpy()[j]
    F["domain_eq"] = eq_feat(ua, ub)
    F["domain_jw"] = sim_feat(ua, ub, JaroWinkler.normalized_similarity, 1)
    F["country_eq"] = eq_feat(w["country"].to_numpy()[i], w["country"].to_numpy()[j])
    ca, cb = w["cats"].to_numpy()[i], w["cats"].to_numpy()[j]
    F["cat_token_set"] = sim_feat(ca, cb, fuzz.token_set_ratio, 1) / 100
    F["cat_eq"] = eq_feat(ca, cb)
    F["cat1_eq"] = eq_feat(w["cat1"].to_numpy()[i], w["cat1"].to_numpy()[j])
    both_cat = (slen(ca) > 0) & (slen(cb) > 0)
    F["cat_tfidf"] = np.where(both_cat, rowdot(VEC["cat_w"], pd.Series(ca).str.replace(", ", ",").to_numpy(),
                                                pd.Series(cb).str.replace(", ", ",").to_numpy()), np.nan).astype(np.float32)
    miss_cols = ["naddr", "ncity", "nstate", "nzip", "phone8", "domain", "cats"]
    miss = (w[miss_cols].to_numpy() == "").sum(1).astype(np.int8)
    F["n_missing"] = miss[i] + miss[j]
    F["n_missing_max"] = np.maximum(miss[i], miss[j])
    deg = np.bincount(i, minlength=len(w)) + np.bincount(j, minlength=len(w))
    F["cand_deg_min"], F["cand_deg_max"] = np.minimum(deg[i], deg[j]), np.maximum(deg[i], deg[j])
    return F


V1_FEATS = ["dist_m", "log_dist", "geo_rank", "by_name", "name_jw", "name_token_set", "name_token_sort", "name_partial", "name_ratio",
            "name_tfidf_char", "name_tfidf_word", "name_len_min", "name_len_ratio", "name_nonascii", "addr_token_set", "city_eq",
            "zip_eq", "phone_eq", "domain_eq", "country_eq", "cat_token_set", "cat_eq", "n_missing"]


# ============================================================================ collective features from a first-stage score
def collective(n, i, j, p):
    C = pd.DataFrame(index=np.arange(len(p)))
    src = np.concatenate([i, j])
    pp = np.concatenate([p, p])
    pair = np.concatenate([np.arange(len(p)), np.arange(len(p))])
    o = np.lexsort((-pp, src))
    s_src, s_p, s_pair = src[o], pp[o], pair[o]
    start = np.r_[0, np.flatnonzero(np.diff(s_src)) + 1]
    first = np.repeat(start, np.diff(np.r_[start, len(s_src)]))
    rank = np.arange(len(s_src)) - first + 1
    pmax = np.zeros(n, np.float32)
    pmax[s_src[start]] = s_p[start]
    second = np.zeros(n, np.float32)
    has2 = np.diff(np.r_[start, len(s_src)]) >= 2
    second[s_src[start[has2]]] = s_p[start[has2] + 1]
    rk = np.empty(len(src), np.int32)
    rk[o] = rank
    rk_i, rk_j = rk[:len(p)], rk[len(p):]
    psum = np.bincount(src, pp, minlength=n).astype(np.float32)
    cnt5 = np.bincount(src, (pp > 0.5).astype(float), minlength=n).astype(np.float32)
    # best competing candidate of each side, excluding this pair
    oth_i = np.where(rk_i == 1, second[i], pmax[i])
    oth_j = np.where(rk_j == 1, second[j], pmax[j])
    C["p1"] = p
    C["p1_logit"] = np.log(np.clip(p, 1e-6, 1 - 1e-6) / np.clip(1 - p, 1e-6, 1))
    C["rank_min"], C["rank_max"] = np.minimum(rk_i, rk_j), np.maximum(rk_i, rk_j)
    C["other_max_min"], C["other_max_max"] = np.minimum(oth_i, oth_j), np.maximum(oth_i, oth_j)
    C["p_minus_other"] = p - np.maximum(oth_i, oth_j)
    C["psum_min"], C["psum_max"] = np.minimum(psum[i], psum[j]), np.maximum(psum[i], psum[j])
    C["cnt5_min"], C["cnt5_max"] = np.minimum(cnt5[i], cnt5[j]), np.maximum(cnt5[i], cnt5[j])
    # two-hop support through shared neighbours
    m = p > 0.05
    A = sp.coo_matrix((p[m], (i[m], j[m])), shape=(n, n)).tocsr()
    A = (A + A.T).tocsr()
    S2 = (A @ A).tocsr()
    C["twohop_sum"] = np.asarray(S2[i, j]).ravel().astype(np.float32)
    B = (A > 0.5).astype(np.float32)
    B2 = (B @ B).tocsr()
    C["twohop_cnt"] = np.asarray(B2[i, j]).ravel().astype(np.float32)
    del o, s_src, s_p, s_pair, A, S2, B, B2
    return C


# ============================================================================ GBDT
try:
    import xgboost as xgb
    XGB_DEV = "cuda" if DEV == "cuda" else "cpu"
except ImportError:
    xgb = None


def fit(X, y, Xva=None, yva=None, rounds=None):
    params = dict(objective="binary:logistic", eval_metric="logloss", tree_method="hist", device=XGB_DEV, max_depth=9, eta=0.06,
                  subsample=0.8, colsample_bytree=0.7, min_child_weight=10, reg_lambda=2.0, max_bin=256, seed=SEED)
    dtr = xgb.QuantileDMatrix(X, y, enable_categorical=False)
    if rounds is None:
        dva = xgb.QuantileDMatrix(Xva, yva, ref=dtr)
        bst = xgb.train(params, dtr, num_boost_round=300 if SMOKE else 4000, evals=[(dva, "va")], early_stopping_rounds=100,
                        verbose_eval=500)
    else:
        bst = xgb.train(params, dtr, num_boost_round=rounds)
    return bst


def predict(bst, X):
    it = (0, bst.best_iteration + 1) if getattr(bst, "best_iteration", None) is not None and bst.num_boosted_rounds() > bst.best_iteration + 1 else (0, 0)
    return bst.inplace_predict(X, iteration_range=it).astype(np.float32)


def group_fold(poi_codes, k):
    return np.array([zlib.crc32(str(int(c)).encode()) % k for c in poi_codes])


def cross_fit_stage(XT, yT, foldT, XS):
    """Model on world T: early-stopped on a 10% place-grouped holdout; scores S; out-of-fold scores on T from two half models."""
    hold = foldT % 10 == 0
    bst = fit(XT[~hold], yT[~hold], XT[hold], yT[hold])
    rounds = bst.best_iteration + 1
    pS = predict(bst, XS)
    oof = np.zeros(len(yT), np.float32)
    half = foldT % 2
    for h in (0, 1):
        b = fit(XT[half != h], yT[half != h], rounds=rounds)
        oof[half == h] = predict(b, XT[half == h])
    return bst, pS, oof


# ============================================================================ cluster scores
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
    """Per-record match list: itself, every candidate above t1, and two-hop neighbours through edges above t2."""
    n = len(poi)
    m1 = p > t1
    A1 = sp.coo_matrix((np.ones(int(m1.sum()), np.float32), (i[m1], j[m1])), shape=(n, n)).tocsr()
    A1 = A1 + A1.T
    Pm = A1 + sp.identity(n, dtype=np.float32, format="csr")
    if t2 <= 1:
        m2 = p > t2
        A2 = sp.coo_matrix((np.ones(int(m2.sum()), np.float32), (i[m2], j[m2])), shape=(n, n)).tocsr()
        A2 = A2 + A2.T
        Pm = Pm + A2 @ A2
    Pm = Pm.tocoo()
    r, c = Pm.row, Pm.col
    same = (poi[r] == poi[c]).astype(np.float64)
    inter = np.bincount(r, same, minlength=n)
    size = np.bincount(r, minlength=n)
    true = pd.Series(poi).map(pd.Series(poi).value_counts()).to_numpy()
    return float((inter / (size + true - inter)).mean())


def pick_and_score(poiA, PA, pA, poiB, PB, pB):
    """Thresholds chosen on world A, the same thresholds applied to world B."""
    iA, jA, iB, jB = PA["i"].to_numpy(), PA["j"].to_numpy(), PB["i"].to_numpy(), PB["j"].to_numpy()
    grid = np.round(np.arange(0.20, 0.96, 0.05), 2)
    cc = {float(t): iou_cc(poiA, iA, jA, pA > t) for t in grid}
    t_cc = max(cc, key=cc.get)
    lst = {}
    for t1 in np.round(np.arange(0.3, 0.86, 0.1), 2):
        for t2 in [1.01] + [x for x in np.round(np.arange(0.5, 0.96, 0.1), 2) if x >= t1]:
            lst[(float(t1), float(t2))] = iou_list(poiA, iA, jA, pA, t1, t2)
    t_l = max(lst, key=lst.get)
    return {"cc": {"threshold": t_cc, "iou_A": cc[t_cc], "iou_B": iou_cc(poiB, iB, jB, pB > t_cc)},
            "list": {"t1": t_l[0], "t2": t_l[1], "iou_A": lst[t_l], "iou_B": iou_list(poiB, iB, jB, pB, *t_l)}}


# ============================================================================ run
W, P, F, E = {}, {}, {}, {}
for name in ("A", "B"):
    W[name] = df[df["world"] == name].reset_index(drop=True)
for name, other in (("A", "B"), ("B", "A")):
    log(f"encoder for world {name}: fine-tuned on world {other}")
    model, tok = train_encoder(W[other])
    E[name] = encode(model, tok, enc_texts(W[name]["name"].tolist()))
    if name == "A":
        model.save_pretrained(OUT / "encoder_trained_on_B")
        tok.save_pretrained(OUT / "encoder_trained_on_B")
    del model
    gc.collect()
    torch.cuda.empty_cache() if DEV == "cuda" else None

STATS = {}
for name in ("A", "B"):
    w = W[name]
    t0 = time.time()
    Pw, kd = retrieve(w, E[name])
    poi = w["point_of_interest"].to_numpy()
    Pw["y"] = (poi[Pw["i"].to_numpy()] == poi[Pw["j"].to_numpy()]).astype(np.int8)
    sz = w.groupby("point_of_interest").size().to_numpy()
    true_pairs = int((sz * (sz - 1) // 2).sum())
    g = Pw["gen"].to_numpy()
    v1_mask = (np.minimum(Pw["geo_rank_ij"], Pw["geo_rank_ji"]).to_numpy() <= 10) | ((g & 8) > 0)
    codes = pd.factorize(poi)[0]
    ii, jj, yy = Pw["i"].to_numpy(), Pw["j"].to_numpy(), Pw["y"].to_numpy()
    STATS[name] = {
        "records": len(w), "places": int(len(sz)), "true_pairs": true_pairs, "candidates": len(Pw), "candidates_per_record": len(Pw) / len(w),
        "pair_recall": float(yy.sum() / true_pairs), "seconds": time.time() - t0,
        "by_generator_true_pairs": {k: int(yy[(g & b) > 0].sum()) for k, b in (("geo", 1), ("emb", 2), ("glob", 4), ("name", 8))},
        "only_from_generator_true_pairs": {k: int(yy[g == b].sum()) for k, b in (("geo", 1), ("emb", 2), ("glob", 4), ("name", 8))},
        "ceiling_cc_iou": iou_cc(codes, ii, jj, yy == 1),
        "ceiling_list_iou_direct": iou_list(codes, ii, jj, yy.astype(np.float32), 0.5, 1.01),
        "v1_candidates": int(v1_mask.sum()), "v1_pair_recall": float(yy[v1_mask].sum() / true_pairs),
        "v1_ceiling_cc_iou": iou_cc(codes, ii[v1_mask], jj[v1_mask], yy[v1_mask] == 1),
    }
    log(f"world {name} retrieval: " + json.dumps({k: (round(v, 4) if isinstance(v, float) else v) for k, v in STATS[name].items()}))
    F[name] = features(w, Pw, E[name], kd)
    P[name] = Pw
    log(f"world {name} features {F[name].shape}")
    gc.collect()

FEATS = list(F["A"].columns)
POI = {k: pd.factorize(W[k]["point_of_interest"].to_numpy())[0] for k in ("A", "B")}
FOLD = {k: group_fold(POI[k][P[k]["i"].to_numpy()], 10) for k in ("A", "B")}
Y = {k: P[k]["y"].to_numpy() for k in ("A", "B")}
RES = {"smoke": SMOKE, "retrieval": STATS, "features": FEATS, "config": {"K_POOL": K_POOL, "K_GEO": K_GEO, "K_EMB": K_EMB, "K_GLOB": K_GLOB,
       "GLOB_RADIUS_m": GLOB_RADIUS, "encoder": ENC_BASE, "encoder_epochs": ENC_EPOCHS}}

# --- v1 recipe at the same density: v1 candidates and v1 features, same model class
log("v1 recipe baseline")
v1 = {}
for k in ("A", "B"):
    g = P[k]["gen"].to_numpy()
    v1[k] = (F[k]["geo_rank"].to_numpy() <= 10) | ((g & 8) > 0)
p_v1 = {}
for T, S in (("A", "B"), ("B", "A")):
    XT, yT, fT = F[T].loc[v1[T], V1_FEATS].to_numpy(np.float32), Y[T][v1[T]], FOLD[T][v1[T]]
    hold = fT % 10 == 0
    b = fit(XT[~hold], yT[~hold], XT[hold], yT[hold])
    p_v1[S] = predict(b, F[S].loc[v1[S], V1_FEATS].to_numpy(np.float32))
PvA, PvB = P["A"][v1["A"]].reset_index(drop=True), P["B"][v1["B"]].reset_index(drop=True)
RES["v1_recipe"] = pick_and_score(POI["A"], PvA, p_v1["A"], POI["B"], PvB, p_v1["B"])
RES["v1_recipe"]["auc_B"] = float(roc_auc_score(Y["B"][v1["B"]], p_v1["B"]))
log("v1 recipe: " + json.dumps(RES["v1_recipe"]))

# --- rule baselines on the v2 candidates (no training)
RES["rules"] = {}
for nm, fn in {"name_jw>=0.9 & dist<200m": lambda X: (X["name_jw"] >= 0.9) & (X["dist_m"] < 200),
               "name_token_set>=0.9 & dist<500m": lambda X: (X["name_token_set"] >= 0.9) & (X["dist_m"] < 500),
               "exact name & dist<1km": lambda X: (X["name_ratio"] >= 0.999) & (X["dist_m"] < 1000)}.items():
    RES["rules"][nm] = {"iou_cc_B": iou_cc(POI["B"], P["B"]["i"].to_numpy(), P["B"]["j"].to_numpy(), fn(F["B"]).to_numpy())}
log("rules: " + json.dumps(RES["rules"]))

# --- stage 1 (pair features) and stage 2 (plus collective features), cross-fitted
P1, P2, OOF1, BST = {}, {}, {}, {}
for T, S in (("A", "B"), ("B", "A")):
    log(f"stage 1: train {T} -> score {S}")
    bst, pS, oof = cross_fit_stage(F[T][FEATS].to_numpy(np.float32), Y[T], FOLD[T], F[S][FEATS].to_numpy(np.float32))
    P1[S], OOF1[T] = pS, oof
    BST[("s1", T)] = bst
    log(f"  stage-1 AUC on {S}: {roc_auc_score(Y[S], pS):.4f}  OOF AUC on {T}: {roc_auc_score(Y[T], oof):.4f}  rounds={bst.best_iteration + 1}")
for T, S in (("A", "B"), ("B", "A")):
    log(f"stage 2: train {T} -> score {S}")
    CT = collective(len(W[T]), P[T]["i"].to_numpy(), P[T]["j"].to_numpy(), OOF1[T])
    CS = collective(len(W[S]), P[S]["i"].to_numpy(), P[S]["j"].to_numpy(), P1[S])
    XT = np.hstack([F[T][FEATS].to_numpy(np.float32), CT.to_numpy(np.float32)])
    XS = np.hstack([F[S][FEATS].to_numpy(np.float32), CS.to_numpy(np.float32)])
    hold = FOLD[T] % 10 == 0
    bst = fit(XT[~hold], Y[T][~hold], XT[hold], Y[T][hold])
    P2[S] = predict(bst, XS)
    BST[("s2", T)] = bst
    STAGE2_FEATS = FEATS + list(CT.columns)
    log(f"  stage-2 AUC on {S}: {roc_auc_score(Y[S], P2[S]):.4f}  rounds={bst.best_iteration + 1}")
    del CT, CS, XT, XS
    gc.collect()

for nm, PP in (("stage1", P1), ("stage2", P2)):
    r = pick_and_score(POI["A"], P["A"], PP["A"], POI["B"], P["B"], PP["B"])
    r["auc_B"], r["ap_B"] = float(roc_auc_score(Y["B"], PP["B"])), float(average_precision_score(Y["B"], PP["B"]))
    r["auc_A"], r["ap_A"] = float(roc_auc_score(Y["A"], PP["A"])), float(average_precision_score(Y["A"], PP["A"]))
    # symmetric check: thresholds picked on B, scored on A
    r["swap"] = pick_and_score(POI["B"], P["B"], PP["B"], POI["A"], P["A"], PP["A"])
    RES[nm] = r
    log(f"{nm}: " + json.dumps(r))

# travel slices and confidence bands on world B, final stage
tv = W["B"]["travel"].to_numpy()
iB, jB = P["B"]["i"].to_numpy(), P["B"]["j"].to_numpy()
RES["slices_B"] = {}
for s in ("lodging", "attraction"):
    m = (tv[iB] == s) & (tv[jB] == s)
    if m.sum() > 100 and Y["B"][m].sum() > 10 and Y["B"][m].sum() < m.sum():
        RES["slices_B"][s] = {"pairs": int(m.sum()), "matches": int(Y["B"][m].sum()), "auc": float(roc_auc_score(Y["B"][m], P2["B"][m])),
                              "ap": float(average_precision_score(Y["B"][m], P2["B"][m]))}
pB = P2["B"]
RES["bands_B"] = {"reject_p<0.02": float((pB < 0.02).mean()), "accept_p>0.98": float((pB > 0.98).mean()),
                  "uncertain": float(((pB >= 0.02) & (pB <= 0.98)).mean())}
gain = BST[("s2", "A")].get_score(importance_type="gain")
names = {f"f{k}": v for k, v in enumerate(STAGE2_FEATS)}
imp = sorted(((names.get(k, k), v) for k, v in gain.items()), key=lambda x: -x[1])
tot = sum(v for _, v in imp)
RES["importance_stage2_trained_on_A"] = [{"feature": f, "gain_share": v / tot} for f, v in imp[:40]]
RES["seconds"] = time.time() - T0
(OUT / "metrics.json").write_text(json.dumps(RES, indent=1, default=float))
for k, bst in BST.items():
    bst.save_model(str(OUT / f"xgb_{k[0]}_trained_on_{k[1]}.json"))

# hand-off for stage 2 (cross-encoder): records and scored pairs per world
for k in ("A", "B"):
    W[k][["id", "name", "address", "city", "state", "zip", "country", "url", "phone", "categories", "latitude", "longitude",
          "point_of_interest", "travel"]].to_parquet(OUT / f"records_{k}.parquet", index=False)
    out = P[k][["i", "j", "y", "gen"]].copy()
    out["p1"], out["p2"] = P1[k], P2[k]
    for c in ("dist_m", "emb_cos", "name_jw", "name_token_set", "addr_token_set", "cat_token_set", "geo_rank", "emb_rank"):
        out[c] = F[k][c].to_numpy()
    out.to_parquet(OUT / f"pairs_{k}.parquet", index=False)
log("FINAL B: stage1 list IoU {:.4f}  stage2 list IoU {:.4f}  v1 recipe {:.4f}  ceiling cc {:.4f}".format(
    RES["stage1"]["list"]["iou_B"], RES["stage2"]["list"]["iou_B"], RES["v1_recipe"]["list"]["iou_B"], STATS["B"]["ceiling_cc_iou"]))
log("done")
