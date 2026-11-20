"""Parity check: does a live preset run reproduce what training stored?

For each city given (default: dubai), runs the site's pipeline exactly as POST /api/runs would, then compares with
data/processed/city_matcher/{pairs.parquet, clusters.parquet} and submission/round1/numbers.json:
  - records: same listings in the same order as training's rids for that city
  - candidates: same set and order of pairs
  - features: every feature column, chunked scoring vs the stored values (and vs one unchunked Featurizer.transform)
  - p: max |live p - stored p| (labelled pairs: leave-one-city-out booster; others: final booster)
  - weak labels, cascade routes, and the lodging entity count / partition after constrained clustering
Usage : .venv\\Scripts\\python.exe -X utf8 web\\api\\parity.py [dubai london ...]
Writes: data/processed/web_cache/parity.json
"""
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from api import CACHE_DIR, CM, NUMBERS  # noqa: E402
from api.artefacts import MODELS  # noqa: E402
from api.pipeline import RUNS  # noqa: E402
from api.presets import CITY_LABEL, PRESETS  # noqa: E402


def canon_labels(x: np.ndarray) -> np.ndarray:
    """Relabel cluster ids by first appearance, so two partitions compare equal whatever their root ids."""
    _, first = np.unique(x, return_index=True)
    order = {v: i for i, v in enumerate(x[np.sort(first)])}
    return np.array([order[v] for v in x])


def check(city: str) -> dict:
    t = time.time()
    run = RUNS.start({"preset": city}, lambda: PRESETS.ingest(city), CITY_LABEL[city], background=False)
    wall = time.time() - t
    if run.failed:
        raise SystemExit(f"{city}: run failed: {run.events[-1]}")
    ev = {typ: json.loads(d) for _, typ, d in run.events if typ in ("done",)}
    G, C, F = run.G, run.C, run.F
    FEATS = MODELS.art()["features"]
    out = {"city": city, "seconds_wall": round(wall, 2), "stage_seconds": run.timings, "records": len(G), "candidates": len(C),
           "loco": run.loco_state}

    # ---- records: training rids of this city, in order
    K = pd.read_parquet(CM / "clusters.parquet")
    K = K[K["city"] == city].sort_values("rid").reset_index(drop=True)
    same_records = len(K) == len(G) and (K["source"].to_numpy() == G["source"].to_numpy()).all() and \
        (K["src_id"].to_numpy() == G["src_id"].astype(str).to_numpy()).all()
    out["records_same_as_training"] = bool(same_records)
    g2l = dict(zip(K["rid"].to_numpy(), np.arange(len(K))))

    # ---- candidates
    P = pd.read_parquet(CM / "pairs.parquet", filters=[("city", "==", city)])
    P = P.reset_index(drop=True)
    pra, prb = P["ra"].map(g2l).to_numpy(), P["rb"].map(g2l).to_numpy()
    out["stored_candidates"] = len(P)
    same_order = len(P) == len(C) and (pra == C["ra"].to_numpy()).all() and (prb == C["rb"].to_numpy()).all()
    out["candidates_same_set"] = set(zip(pra.tolist(), prb.tolist())) == set(zip(C["ra"].tolist(), C["rb"].tolist()))
    out["candidates_same_order"] = bool(same_order)
    if not same_order:
        return out

    # ---- features
    feat_diff = {}
    for f in FEATS:
        if f == "src_pair":
            feat_diff[f] = int((F[f].astype(str).to_numpy() != P["src_pair"].to_numpy()).sum())
            continue
        a, b = F[f].to_numpy(dtype=float), P[f].to_numpy(dtype=float)
        nan_mismatch = int((np.isnan(a) != np.isnan(b)).sum())
        both = ~np.isnan(a) & ~np.isnan(b)
        feat_diff[f] = float(np.max(np.abs(a[both] - b[both]))) if both.any() else 0.0
        if nan_mismatch:
            feat_diff[f] = f"{nan_mismatch} NaN mismatches"
    out["feature_max_abs_diff"] = feat_diff
    out["features_identical"] = all(v == 0 for v in feat_diff.values())
    F1 = MODELS.art()["featurizer"].transform(G, C, src_pair_categories=MODELS.art()["src_pair_categories"])[FEATS]
    out["chunked_equals_single_transform"] = bool(all(
        (F1[f].astype(str) == F[f].astype(str)).all() if f == "src_pair" else
        np.array_equal(F1[f].to_numpy(dtype=float), F[f].to_numpy(dtype=float), equal_nan=True) for f in FEATS))

    # ---- scores and labels
    lab = P["y"].to_numpy() >= 0
    dp = np.abs(run.p64 - P["p"].to_numpy())
    out["p_max_abs_diff"] = float(dp.max())
    out["p_max_abs_diff_labelled_loco"] = float(dp[lab].max()) if lab.any() else None
    out["p_max_abs_diff_unlabelled_final"] = float(dp[~lab].max()) if (~lab).any() else None
    out["weak_labels_identical"] = bool((run.y == P["y"].to_numpy()).all() and (run.label_src == P["label_src"].to_numpy()).all())
    out["labelled_pairs"] = int(lab.sum())

    # ---- routes vs the cascade training would compute from its stored p
    art = MODELS.art()
    y, ps = P["y"].to_numpy(), P["p"].to_numpy()
    rest = ~((y == 1) | (y == 0))
    trained = {"key_match": int((y == 1).sum()), "key_reject": int((y == 0).sum()), "model_accept": int((rest & (ps >= art["t_accept"])).sum()),
               "model_reject": int((rest & (ps < art["t_reject"])).sum()),
               "uncertain": int((rest & (ps >= art["t_reject"]) & (ps < art["t_accept"])).sum())}
    from canon.cascade import ROUTES
    live = {name: int((run.routes == i).sum()) for i, name in enumerate(ROUTES)}
    out["routes_live"], out["routes_from_stored_p"] = live, trained

    # ---- clusters
    lod = (G["kind"] == "lodging").to_numpy()
    out["lodging_listings"] = int(lod.sum())
    out["lodging_entities"] = int(len(np.unique(run.root[lod])))
    out["lodging_entities_training_clusters_parquet"] = int(K.loc[lod, "cluster"].nunique()) if same_records else None
    out["partition_identical_to_training"] = bool(same_records and np.array_equal(canon_labels(run.root), canon_labels(K["cluster"].to_numpy())))
    try:
        nb = json.loads(NUMBERS.read_text(encoding="utf-8"))["matching"].get(city)
        if nb:
            out["numbers_json"] = {"lodging_listings": nb["lodging_listings"], "canonical_entities": nb["canonical_entities"]}
    except (OSError, KeyError, ValueError):
        pass
    out["done_event"] = ev.get("done")
    return out


def main():
    cities = sys.argv[1:] or ["dubai"]
    res = {}
    for c in cities:
        r = check(c)
        res[c] = r
        print(json.dumps(r, indent=1, default=str), flush=True)
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    old = {}
    f = CACHE_DIR / "parity.json"
    if f.exists():
        try:
            old = json.loads(f.read_text(encoding="utf-8"))
        except ValueError:
            old = {}
    old.update(res)
    f.write_text(json.dumps(old, indent=1, default=str), encoding="utf-8")


if __name__ == "__main__":
    main()
