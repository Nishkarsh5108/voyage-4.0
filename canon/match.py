"""Entity matching building blocks: record preparation, blocking, pair features.

Shared by training (scripts/train/city_matcher.py) and by any feed the trained pair model is applied to
(scripts/train/ota_matcher.py), so the features at inference are computed by the same code as in training.

Records are a pandas DataFrame with at least: source, city, name, alt_names (list or None), lat, lon, kind,
street, postcode, brand, stars, confidence. `prepare` adds the normalised columns the other functions need.

Phone, website and Wikidata QID are deliberately absent from the pair features: they are used as stage-0 rules
and as independent truth when the model is evaluated.
"""
from __future__ import annotations

import re
import unicodedata

import numpy as np
import pandas as pd
from rapidfuzz import fuzz
from rapidfuzz.distance import JaroWinkler
from rapidfuzz.process import cpdist
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.neighbors import BallTree


def norm(s) -> str:
    """Lower-case, strip accents and punctuation, collapse spaces. Non-Latin scripts are kept as they are."""
    if not isinstance(s, str):
        return ""
    s = unicodedata.normalize("NFKD", s.lower())
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    return re.sub(r"\s+", " ", re.sub(r"[^\w ]+", " ", s)).strip()


def haversine(lat1, lon1, lat2, lon2):
    p1, p2 = np.radians(lat1), np.radians(lat2)
    a = np.sin((p2 - p1) / 2) ** 2 + np.cos(p1) * np.cos(p2) * np.sin(np.radians(lon2 - lon1) / 2) ** 2
    return 2 * 6371000 * np.arcsin(np.sqrt(a))


def prepare(G: pd.DataFrame) -> pd.DataFrame:
    """Add normalised helper columns and a dense integer id `rid` (position in the returned frame)."""
    G = G.copy()
    G["nn"] = G["name"].map(norm)
    G = G[G["nn"].str.len() > 0].reset_index(drop=True)
    G["rid"] = np.arange(len(G))
    G["alts"] = G["alt_names"].map(lambda xs: [a for a in {norm(x) for x in (xs if xs is not None else [])} if a])
    G["decimals"] = G["lat"].map(lambda v: len(repr(float(v)).split(".")[-1]) if pd.notna(v) else 0).clip(upper=7)
    G["nstreet"] = G["street"].map(norm)
    G["npost"] = G["postcode"].fillna("").astype(str).str.replace(r"\W", "", regex=True).str.lower()
    G["nbrand"] = G["brand"].map(norm)
    G["latin"] = G["name"].map(lambda s: bool(re.search(r"[A-Za-z]", s)))
    return G


class Featurizer:
    """Name vectorisers fitted once on the training names, plus the pair-feature function."""

    def __init__(self):
        self.tf_char = TfidfVectorizer(analyzer="char_wb", ngram_range=(2, 4), min_df=2, dtype=np.float32, sublinear_tf=True)
        self.tf_word = TfidfVectorizer(analyzer="word", token_pattern=r"\S+", dtype=np.float32)

    def fit(self, names: pd.Series) -> "Featurizer":
        self.tf_char.fit(names)
        self.tf_word.fit(names)
        return self

    @staticmethod
    def _sc(x, y, fn):
        return cpdist(x, y, scorer=fn, workers=4, dtype=np.float32)

    @staticmethod
    def _rowdot(vec, x, y, chunk=300_000):
        out = np.empty(len(x), dtype=np.float32)
        for s in range(0, len(x), chunk):
            out[s:s + chunk] = np.asarray(vec.transform(x[s:s + chunk]).multiply(vec.transform(y[s:s + chunk])).sum(axis=1)).ravel()
        return out

    def transform(self, G: pd.DataFrame, C: pd.DataFrame, E=None, src_pair_categories=None) -> pd.DataFrame:
        """Pair features for candidate pairs C (columns ra, rb, geo_rank, by_geo, by_name[, by_emb]) over records G."""
        a, b = G.iloc[C["ra"].to_numpy()].reset_index(drop=True), G.iloc[C["rb"].to_numpy()].reset_index(drop=True)
        sc, rowdot = self._sc, self._rowdot
        d = haversine(a["lat"].to_numpy(dtype=float), a["lon"].to_numpy(dtype=float), b["lat"].to_numpy(dtype=float), b["lon"].to_numpy(dtype=float)).astype(np.float32)
        na, nb = a["nn"].to_numpy(), b["nn"].to_numpy()
        F = pd.DataFrame(index=C.index)
        F["dist_m"] = d
        F["log_dist"] = np.log1p(d)
        F["geo_rank"] = C["geo_rank"].to_numpy()
        F["by_geo"], F["by_name"] = C["by_geo"].to_numpy(), C["by_name"].to_numpy()
        F["name_jw"] = sc(na, nb, JaroWinkler.normalized_similarity)
        F["name_token_set"] = sc(na, nb, fuzz.token_set_ratio) / 100
        F["name_token_sort"] = sc(na, nb, fuzz.token_sort_ratio) / 100
        F["name_partial"] = sc(na, nb, fuzz.partial_ratio) / 100
        F["name_ratio"] = sc(na, nb, fuzz.ratio) / 100
        F["name_tfidf_char"] = rowdot(self.tf_char, na, nb)
        F["name_tfidf_word"] = rowdot(self.tf_word, na, nb)
        # best similarity over alternate / local-language names
        best_jw, best_ts = F["name_jw"].to_numpy().copy(), F["name_token_set"].to_numpy().copy()
        alt_a, alt_b = a["alts"].to_numpy(), b["alts"].to_numpy()
        has_alt = np.fromiter((len(x) > 0 or len(y) > 0 for x, y in zip(alt_a, alt_b)), dtype=bool, count=len(C))
        for i in np.where(has_alt)[0]:
            va, vb = [na[i]] + alt_a[i], [nb[i]] + alt_b[i]
            best_jw[i] = max(JaroWinkler.normalized_similarity(x, y) for x in va for y in vb)
            best_ts[i] = max(fuzz.token_set_ratio(x, y) for x in va for y in vb) / 100
        F["name_jw_alt"], F["name_token_set_alt"], F["has_alt"] = best_jw, best_ts, has_alt.astype(np.int8)
        if E is not None:  # optional multilingual embedding features (experiment; see reports/models/city_matcher.md)
            F["by_emb"] = C["by_emb"].to_numpy()
            ia, ib = a["erow"].to_numpy(), b["erow"].to_numpy()
            cos = np.empty(len(C), dtype=np.float32)
            for s in range(0, len(C), 200_000):
                cos[s:s + 200_000] = np.einsum("ij,ij->i", E[ia[s:s + 200_000]], E[ib[s:s + 200_000]])
            F["name_emb_cos"] = cos
            best = cos.copy()
            ea_alt, eb_alt = a["alt_erows"].to_numpy(), b["alt_erows"].to_numpy()
            for i in np.where(has_alt)[0]:
                best[i] = float((E[[ia[i]] + list(ea_alt[i])] @ E[[ib[i]] + list(eb_alt[i])].T).max())
            F["name_emb_cos_alt"] = best
        la, lb = a["nn"].str.len().to_numpy(), b["nn"].str.len().to_numpy()
        F["name_len_min"] = np.minimum(la, lb)
        F["name_len_ratio"] = np.minimum(la, lb) / np.maximum(la, lb)
        F["script_mismatch"] = (a["latin"].to_numpy() != b["latin"].to_numpy()).astype(np.int8)
        F["same_kind"] = (a["kind"].to_numpy() == b["kind"].to_numpy()).astype(np.int8)
        F["both_lodging"] = ((a["kind"].to_numpy() == "lodging") & (b["kind"].to_numpy() == "lodging")).astype(np.int8)
        sa_, sb_ = a["nstreet"].to_numpy(), b["nstreet"].to_numpy()
        both_s = (a["nstreet"].str.len().to_numpy() > 2) & (b["nstreet"].str.len().to_numpy() > 2)
        F["street_token_set"] = np.where(both_s, sc(sa_, sb_, fuzz.token_set_ratio) / 100, np.nan)
        pa, pb = a["npost"].to_numpy(), b["npost"].to_numpy()
        F["postcode_eq"] = np.where((pa != "") & (pb != ""), (pa == pb).astype(float), np.nan)
        ba, bb = a["nbrand"].to_numpy(), b["nbrand"].to_numpy()
        F["brand_sim"] = np.where((ba != "") & (bb != ""), sc(ba, bb, fuzz.token_set_ratio) / 100, np.nan)
        F["stars_diff"] = np.abs(a["stars"].to_numpy(dtype=float) - b["stars"].to_numpy(dtype=float))
        F["decimals_min"] = np.minimum(a["decimals"].to_numpy(), b["decimals"].to_numpy())
        F["overture_conf"] = np.fmin(a["confidence"].to_numpy(dtype=float), b["confidence"].to_numpy(dtype=float))
        pair = (a["source"] + "|" + b["source"]).to_numpy()
        F["src_pair"] = pd.Categorical(pair, categories=src_pair_categories) if src_pair_categories is not None else pd.Categorical(pair)
        # how crowded is the neighbourhood: candidates each record has within 300 m
        near = C[d < 300]
        cnt = pd.concat([near["ra"], near["rb"]]).value_counts()
        F["n_near_max"] = np.maximum(C["ra"].map(cnt).fillna(0).to_numpy(), C["rb"].map(cnt).fillna(0).to_numpy())
        return F


def block(G: pd.DataFrame, XC, groups: list, sources: list, group_col: str = "city", k_geo: int = 8, r_geo: float = 1000.0,
          k_name: int = 3, min_cos: float = 0.55, E=None, k_emb: int = 3, min_emb: float = 0.90, log=None) -> pd.DataFrame:
    """Candidate pairs between records of different sources inside each group (a city).

    Generators: `geo` (k nearest of the other source within r metres), `name` (top k by character n-gram cosine anywhere in the
    group), `exact` (same normalised name), and optionally `emb` (top k by embedding cosine). XC is the char TF-IDF matrix of G["nn"].
    Records without coordinates take part in the name generators only.
    """
    cand = []
    for g in groups:
        sub = G[G[group_col] == g]
        by_src = {s: sub[sub["source"] == s] for s in sources}
        for a_i, sa in enumerate(sources):
            for sb in sources[a_i + 1:]:
                A, B = by_src[sa], by_src[sb]
                if len(A) == 0 or len(B) == 0:
                    continue
                if len(A) > len(B):
                    A, B = B, A
                Ag, Bg = A[A["lat"].notna()], B[B["lat"].notna()]
                if len(Ag) and len(Bg):
                    tree = BallTree(np.radians(Bg[["lat", "lon"]].to_numpy(dtype=float)), metric="haversine")
                    k = min(k_geo, len(Bg))
                    dist, idx = tree.query(np.radians(Ag[["lat", "lon"]].to_numpy(dtype=float)), k=k)
                    ok = dist * 6371000 <= r_geo
                    cand.append(pd.DataFrame({"ra": np.repeat(Ag["rid"].to_numpy(), k)[ok.ravel()], "rb": Bg["rid"].to_numpy()[idx.ravel()][ok.ravel()],
                                              "geo_rank": np.tile(np.arange(1, k + 1), len(Ag))[ok.ravel()], "gen": "geo"}))
                xa, xb = XC[A["rid"].to_numpy()], XC[B["rid"].to_numpy()].T.tocsr()
                for s in range(0, len(A), 400):
                    S = (xa[s:s + 400] @ xb).toarray()
                    kk = min(k_name, S.shape[1])
                    top = np.argpartition(-S, kk - 1, axis=1)[:, :kk]
                    m = np.take_along_axis(S, top, axis=1) >= min_cos
                    cand.append(pd.DataFrame({"ra": np.repeat(A["rid"].to_numpy()[s:s + 400], kk)[m.ravel()],
                                              "rb": B["rid"].to_numpy()[top.ravel()][m.ravel()], "geo_rank": 99, "gen": "name"}))
                if E is not None:
                    ea, eb = E[A["erow"].to_numpy()], E[B["erow"].to_numpy()].T
                    for s in range(0, len(A), 2000):
                        S = ea[s:s + 2000] @ eb
                        kk = min(k_emb, S.shape[1])
                        top = np.argpartition(-S, kk - 1, axis=1)[:, :kk]
                        m = np.take_along_axis(S, top, axis=1) >= min_emb
                        cand.append(pd.DataFrame({"ra": np.repeat(A["rid"].to_numpy()[s:s + 2000], kk)[m.ravel()],
                                                  "rb": B["rid"].to_numpy()[top.ravel()][m.ravel()], "geo_rank": 99, "gen": "emb"}))
        e = sub[sub["nn"].str.len() >= 4][["rid", "nn", "source"]]
        e = e[e.groupby("nn")["rid"].transform("size").between(2, 30)]
        ee = e.merge(e, on="nn")
        ee = ee[(ee["source_x"] != ee["source_y"]) & (ee["rid_x"] < ee["rid_y"])]
        cand.append(pd.DataFrame({"ra": ee["rid_x"].to_numpy(), "rb": ee["rid_y"].to_numpy(), "geo_rank": 99, "gen": "exact"}))
        if log:
            log(f"blocked {g}")
    C = pd.concat(cand, ignore_index=True)
    lo, hi = np.minimum(C["ra"], C["rb"]), np.maximum(C["ra"], C["rb"])
    C["ra"], C["rb"] = lo, hi
    return C.groupby(["ra", "rb"], as_index=False).agg(geo_rank=("geo_rank", "min"), by_geo=("gen", lambda x: int("geo" in set(x))),
                                                      by_name=("gen", lambda x: int(bool({"name", "exact"} & set(x)))),
                                                      by_emb=("gen", lambda x: int("emb" in set(x))))
