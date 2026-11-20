"""Rebuild the 12 leave-one-city-out boosters of scripts/train/city_matcher.py (step 4) and save them.

city_matcher.py trains one booster per held-out city to score that city's labelled pairs (the out-of-city score `p` stored
in pairs.parquet), then throws the boosters away and keeps only the final model. The local site (web/serve.py) scores a
preset city's labelled pairs with the booster that never saw that city, exactly as training did, so it needs them on disk.

Nothing new is learned here: same pairs and features (read back from pairs.parquet, in file order), same PARAMS and seed,
same validation-city rule, early stopping 60, at most 1500 rounds, feature list and order and src_pair categories from the
featurizer joblib. The parity check compares each booster's predictions on its held-out city's labelled pairs with the
stored `p` and prints the largest absolute difference per city.

Input : data/processed/city_matcher/{pairs.parquet, featurizer_no_emb.joblib, model.lgb}
Output: data/processed/city_matcher/loco/{model_<city>.lgb, manifest.json}
Usage : .venv\\Scripts\\python.exe -I -X utf8 scripts\\train\\loco_models.py
"""
import json
import sys
import time
from pathlib import Path

import joblib
import lightgbm as lgb
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))  # the joblib holds a canon.match.Featurizer
CM = ROOT / "data" / "processed" / "city_matcher"
OUT = CM / "loco"
CITY_ORDER = ["dubai", "bangkok", "singapore", "delhi", "mumbai", "goa", "london", "paris", "amsterdam", "barcelona", "vienna", "milan"]
SEED = 7
PARAMS = dict(objective="binary", learning_rate=0.05, num_leaves=63, min_data_in_leaf=40, feature_fraction=0.8, bagging_fraction=0.8,
              bagging_freq=1, lambda_l2=1.0, verbose=-1, seed=SEED, num_threads=4)
T0 = time.time()


def log(m):
    print(f"[{time.time() - T0:6.0f}s] {m}", flush=True)


def main():
    missing = [p.name for p in (CM / "pairs.parquet", CM / "featurizer_no_emb.joblib") if not p.exists()]
    if missing:
        raise SystemExit(f"missing {missing}: run scripts/train/city_matcher.py first")
    art = joblib.load(CM / "featurizer_no_emb.joblib")
    FEATS = art["features"]
    P = pd.read_parquet(CM / "pairs.parquet")
    F = P[[f for f in FEATS if f != "src_pair"]].copy()
    F["src_pair"] = pd.Categorical(P["src_pair"].to_numpy(), categories=art["src_pair_categories"])
    F = F[FEATS]  # training column order
    y = P["y"].to_numpy()
    city_of = P["city"].to_numpy()
    stored = P["p"].to_numpy()
    lab = y >= 0
    log(f"pairs={len(P):,} labelled={int(lab.sum()):,} features={len(FEATS)}")
    OUT.mkdir(parents=True, exist_ok=True)
    manifest, rounds = {"params": PARAMS, "features": FEATS, "cities": {}}, []
    for city in CITY_ORDER:
        te = lab & (city_of == city)
        tr = lab & ~te
        val_city = CITY_ORDER[(CITY_ORDER.index(city) + 5) % len(CITY_ORDER)]
        va = tr & (city_of == val_city)
        tr2 = tr & ~va
        m = lgb.train(PARAMS, lgb.Dataset(F[tr2], y[tr2]), 1500, valid_sets=[lgb.Dataset(F[va], y[va])],
                      callbacks=[lgb.early_stopping(60, verbose=False)])
        rounds.append(m.best_iteration)
        p_mem = m.predict(F[te], num_iteration=m.best_iteration)
        path = OUT / f"model_{city}.lgb"
        m.save_model(str(path))  # saves up to best_iteration
        p_file = lgb.Booster(model_file=str(path)).predict(F[te])
        d_mem = float(np.max(np.abs(p_mem - stored[te]))) if te.any() else 0.0
        d_file = float(np.max(np.abs(p_file - stored[te]))) if te.any() else 0.0
        d_io = float(np.max(np.abs(p_file - p_mem))) if te.any() else 0.0
        manifest["cities"][city] = {"val_city": val_city, "best_iteration": int(m.best_iteration), "test_pairs": int(te.sum()),
                                    "max_abs_diff_vs_stored_p": d_file, "max_abs_diff_in_memory": d_mem, "save_load_diff": d_io,
                                    "n_diff_gt_1e-9": int((np.abs(p_file - stored[te]) > 1e-9).sum())}
        log(f"{city:<10} val={val_city:<10} best_iter={m.best_iteration:>4} test_pairs={int(te.sum()):>6,} "
            f"max|p - stored p| = {d_file:.3g} (in memory {d_mem:.3g}, save/load {d_io:.3g})")
    final = lgb.Booster(model_file=str(CM / "model.lgb")) if (CM / "model.lgb").exists() else None
    med = int(np.median(rounds))
    manifest["median_rounds"] = med
    manifest["final_model_trees"] = final.num_trees() if final is not None else None
    worst = max(v["max_abs_diff_vs_stored_p"] for v in manifest["cities"].values())
    manifest["max_abs_diff_all_cities"] = worst
    manifest["built"] = time.strftime("%Y-%m-%d %H:%M:%S")
    (OUT / "manifest.json").write_text(json.dumps(manifest, indent=1), encoding="utf-8")
    log(f"median best_iteration = {med} (final model.lgb has {manifest['final_model_trees']} trees; city_matcher.py trains it for that median)")
    log(f"largest |p - stored p| over all cities: {worst:.3g}; saved {len(CITY_ORDER)} boosters to {OUT}")


if __name__ == "__main__":
    main()
