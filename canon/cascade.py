"""The cascade around the pair model: stage-0 key rules, routing of every candidate pair, constrained clustering.

This module mirrors scripts/train/city_matcher.py so a feed scored outside training is labelled, routed and clustered by the
same rules the reported numbers came from:

  step 2  weak labels   `rare_keys` (hub rule) and `weak_labels` (key match / key conflict / none, and the ambiguous
                        same-name-within-50 m conflicts that training set aside)
  step 5  cascade       `route`: key_match, key_reject, model_accept (p >= t_accept), model_reject (p < t_reject), uncertain.
                        Added from scripts/train/ota_matcher.py: a pair without coordinates on both sides is never
                        auto-accepted; it becomes `no_coords_review` when p >= t_reject.
  step 6  clustering    `constrained_union_find`: key matches (weight 2.0) and model accepts (weight p) merged in descending
                        weight order, never joining two different Wikidata QIDs.

Phone, website and QID are only ever used here, as rules and labels. They are never pair-model features (see canon/match.py).

One deliberate difference from city_matcher.py: training sorted the accepted edges with pandas' default (unstable) sort,
so the order among equal weights (every key match weighs 2.0) was whatever quicksort produced. Here the sort is stable and
ties are broken by candidate position, so a run is reproducible. Without the QID constraint the order would not matter at
all (union-find gives the same partition in any order); with it, it can only change which of two conflicting merges wins.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

HUB = 4  # a phone or URL shared by more than this many listings of one group is a hub (call centre, chain home page), not a key
ROUTES = ("key_match", "key_reject", "model_accept", "model_reject", "uncertain", "no_coords_review")
KEY_MATCH, KEY_REJECT, MODEL_ACCEPT, MODEL_REJECT, UNCERTAIN, NO_COORDS_REVIEW = range(6)


def rare_keys(G: pd.DataFrame, group_col: str = "city", keys=("phone8", "url_key"), hub: int = HUB) -> pd.DataFrame:
    """Add `<key>_rare`: the key where at most `hub` listings of the same group share it, else missing (city_matcher.py, records)."""
    for key in keys:
        if key not in G.columns:
            G[key] = None
        cnt = G.groupby([group_col, key])[key].transform("size")
        G[key + "_rare"] = G[key].where(cnt <= hub)
    return G


def _tok_sorted(s: str) -> str:
    return " ".join(sorted(s.split()))


def weak_labels(G: pd.DataFrame, ra: np.ndarray, rb: np.ndarray, dist_m: np.ndarray) -> dict:
    """Stage-0 key rules for candidate pairs (ra, rb) over prepared records G (city_matcher.py step 2).

    G needs qid, phone8_rare, url_key_rare, domain and nn. dist_m is the pair distance in metres (float32, NaN when unknown).
    Returns y (int8: 1 key match, 0 key conflict, -1 no evidence, -2 ambiguous conflict set aside), label_src (str) and amb (bool).
    """
    a, b = G.iloc[np.asarray(ra)].reset_index(drop=True), G.iloc[np.asarray(rb)].reset_index(drop=True)

    def eq(col):
        if col not in G.columns:
            z = np.zeros(len(a), dtype=bool)
            return z, z
        x, yv = a[col].to_numpy(dtype=object), b[col].to_numpy(dtype=object)
        both = pd.notna(x) & pd.notna(yv)
        return both, both & (x == yv)

    both_q, same_q = eq("qid")
    both_p, same_p = eq("phone8_rare")
    both_u, same_u = eq("url_key_rare")
    both_d, same_d = eq("domain")
    d = np.asarray(dist_m)
    pos = (same_q & (d < 2000)) | (same_p & same_u & (d < 1000)) | (same_p & (d < 300)) | (same_u & (d < 300))
    neg = (both_q & ~same_q) | (both_p & ~same_p & both_d & ~same_d)
    y = np.where(pos & ~(both_q & ~same_q), 1, np.where(neg & ~pos, 0, -1)).astype(np.int8)
    label_src = np.where(same_q, "qid", np.where(same_p & same_u, "phone+url", np.where(same_p, "phone", np.where(same_u, "url",
                         np.where(both_q & ~same_q, "qid_conflict", np.where(neg, "phone_and_domain_differ", ""))))))
    # keys conflict, yet both records carry the same name (token order ignored) within 50 m: neither trained on nor scored
    same_name = a["nn"].map(_tok_sorted).to_numpy() == b["nn"].map(_tok_sorted).to_numpy()
    amb = (y == 0) & same_name & (d < 50)
    y[amb] = -2
    return {"y": y, "label_src": label_src, "amb": amb}


def route(y: np.ndarray, p: np.ndarray, t_accept: float, t_reject: float, has_xy: np.ndarray | None = None) -> np.ndarray:
    """Route code per pair (index into ROUTES). Key rules first; the model settles the rest (city_matcher.py step 5).

    A pair without coordinates on both sides is never auto-accepted (scripts/train/ota_matcher.py): it is held for review
    when p >= t_reject and rejected otherwise.
    """
    y, p = np.asarray(y), np.asarray(p)
    has_xy = np.ones(len(y), dtype=bool) if has_xy is None else np.asarray(has_xy, dtype=bool)
    out = np.full(len(y), UNCERTAIN, dtype=np.uint8)
    rest = ~((y == 1) | (y == 0))
    out[y == 1] = KEY_MATCH
    out[y == 0] = KEY_REJECT
    out[rest & (p < t_reject)] = MODEL_REJECT
    out[rest & has_xy & (p >= t_accept)] = MODEL_ACCEPT
    out[rest & ~has_xy & (p >= t_reject)] = NO_COORDS_REVIEW
    return out


def constrained_union_find(n: int, ra: np.ndarray, rb: np.ndarray, routes: np.ndarray, p: np.ndarray, qid) -> dict:
    """Merge accepted pairs into entities, never joining two different Wikidata QIDs (city_matcher.py step 6).

    Edges: key matches with weight 2.0 and model accepts with weight p, processed in descending weight order (stable sort,
    ties by candidate position). qid: per record, a QID string or missing. Returns root (int32 cluster root per record),
    blocked (merges refused by the cannot-link rule), and order / outcome per accepted edge (0 merged, 1 already joined,
    2 refused).
    """
    routes = np.asarray(routes)
    acc = np.where((routes == KEY_MATCH) | (routes == MODEL_ACCEPT))[0]
    w = np.where(routes[acc] == KEY_MATCH, 2.0, np.asarray(p, dtype=float)[acc])
    order = acc[np.argsort(-w, kind="stable")]
    parent = np.arange(n)
    qid_of = [({q} if isinstance(q, str) else set()) for q in qid]
    blocked = 0
    outcome = np.zeros(len(order), dtype=np.int8)

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    ra, rb = np.asarray(ra), np.asarray(rb)
    for j, k in enumerate(order):
        x, yv = find(ra[k]), find(rb[k])
        if x == yv:
            outcome[j] = 1
            continue
        if qid_of[x] and qid_of[yv] and qid_of[x] != qid_of[yv]:
            blocked += 1  # cannot-link: two different Wikidata identities
            outcome[j] = 2
            continue
        parent[x] = yv
        qid_of[yv] = qid_of[yv] | qid_of[x]
    root = np.array([find(i) for i in range(n)], dtype=np.int32)
    return {"root": root, "blocked": blocked, "order": order, "outcome": outcome}
