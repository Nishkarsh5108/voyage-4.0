"""Transfer test: apply the city-trained pair model, unchanged, to two real supplier feeds (MakeMyTrip x Goibibo, India, 2016).

Nothing is trained here. The model, its name vectorisers and its accept / reject thresholds come from
scripts/train/city_matcher.py (open data, 12 cities, none of them these feeds). There are no labels for these two feeds,
so the output is counts, examples and a sheet for people to label; any precision figure must come from that sheet.

Input : data/raw/makemytrip_hotels/*.csv, data/raw/goibibo_hotels/*.csv, data/processed/city_matcher/{model.lgb, featurizer_no_emb.joblib}
Output: data/processed/ota_matcher/{pairs.parquet, label_sheet.csv, label_sheet_key.csv}, reports/models/ota_matcher.{md,json}
Usage : python -I scripts/train/ota_matcher.py
"""
import json
import re
import sys
import time
from pathlib import Path

import joblib
import lightgbm as lgb
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from canon.match import block, prepare  # noqa: E402

RAW, CM = ROOT / "data" / "raw", ROOT / "data" / "processed" / "city_matcher"
OUT, REP = ROOT / "data" / "processed" / "ota_matcher", ROOT / "reports" / "models"
OUT.mkdir(parents=True, exist_ok=True)
T0 = time.time()
rng = np.random.default_rng(7)


def log(m):
    print(f"[{time.time() - T0:5.0f}s] {m}", flush=True)


def pin(addr):
    m = re.search(r"\b(\d{6})\b", addr) if isinstance(addr, str) else None
    return m.group(1) if m else None


def load(path, source, addr_col, star_fn):
    d = pd.read_csv(path, dtype=str, on_bad_lines="skip")
    d = d[d["property_id"].notna()].drop_duplicates("property_id")
    lat, lon = pd.to_numeric(d["latitude"], errors="coerce"), pd.to_numeric(d["longitude"], errors="coerce")
    ok = lat.between(6, 37.5) & lon.between(68, 97.5)  # inside India; zeros and swapped values become missing
    return pd.DataFrame({
        "source": source, "group": "india", "src_id": d["property_id"].to_numpy(), "name": d["property_name"].to_numpy(), "alt_names": None,
        "lat": lat.where(ok).to_numpy(), "lon": lon.where(ok).to_numpy(), "kind": "lodging", "street": d[addr_col].to_numpy(),
        "postcode": d[addr_col].map(pin).to_numpy(), "brand": None, "stars": star_fn(d).to_numpy(), "confidence": np.nan,
        "city": d["city"].str.lower().str.replace(r"[^a-z]", "", regex=True).to_numpy(), "state": d["state"].to_numpy(),
    })


# MakeMyTrip labels 57% of its catalogue "1 star", which reads as its default for unrated; treated as unknown here.
mmt = load(RAW / "makemytrip_hotels" / "makemytrip_com-travel_sample.csv", "makemytrip", "property_address",
           lambda d: pd.to_numeric(d["hotel_star_rating"].str.extract(r"(\d)", expand=False), errors="coerce").where(lambda s: s > 1))
gob = load(RAW / "goibibo_hotels" / "goibibo_com-travel_sample.csv", "goibibo", "address",
           lambda d: pd.to_numeric(d["hotel_star_rating"], errors="coerce").where(lambda s: s > 0))
G = prepare(pd.concat([mmt, gob], ignore_index=True).dropna(subset=["name"]))
log(f"records: {G.groupby('source').size().to_dict()}, with coordinates: {G.groupby('source')['lat'].count().to_dict()}")

art = joblib.load(CM / "featurizer_no_emb.joblib")
fz, FEATS, T_ACC, T_REJ = art["featurizer"], art["features"], art["t_accept"], art["t_reject"]
model = lgb.Booster(model_file=str(CM / "model.lgb"))
XC = fz.tf_char.transform(G["nn"])
C = block(G, XC, ["india"], ["makemytrip", "goibibo"], group_col="group", **art["blocking"])
F = fz.transform(G, C, src_pair_categories=art["src_pair_categories"])
C["p"] = model.predict(F[FEATS])
a, b = G.iloc[C["ra"].to_numpy()].reset_index(drop=True), G.iloc[C["rb"].to_numpy()].reset_index(drop=True)
C["has_xy"] = (a["lat"].notna() & b["lat"].notna()).to_numpy()
C["same_city"] = (a["city"].to_numpy() == b["city"].to_numpy())
for col in ("dist_m", "name_jw", "name_token_set", "name_tfidf_word", "street_token_set", "postcode_eq"):
    C[col] = F[col].to_numpy()
log(f"candidates={len(C):,}, both sides geocoded: {int(C['has_xy'].sum()):,}")

# decision bands; a pair without coordinates on both sides is never auto-accepted (distance is the model's second-strongest feature)
C["band"] = np.where(~C["has_xy"], np.where(C["p"] >= T_REJ, "name-only: review", "reject"),
                     np.where(C["p"] >= T_ACC, "accept", np.where(C["p"] >= T_REJ, "uncertain", "reject")))
# one-to-one view of accepted pairs: best partner first; leftovers point at duplicates inside one feed
acc = C[C["band"] == "accept"].sort_values("p", ascending=False)
used_a, used_b, keep = set(), set(), []
for i, ra, rb in zip(acc.index, acc["ra"], acc["rb"]):
    if ra not in used_a and rb not in used_b:
        used_a.add(ra); used_b.add(rb); keep.append(i)
C["one_to_one"] = C.index.isin(keep)
is_g = (G["source"] == "goibibo").to_numpy()
gob_ids = lambda frame: set(np.where(is_g[frame["ra"].to_numpy()], frame["ra"], frame["rb"]))  # noqa: E731
n_g, n_m = int(is_g.sum()), int((~is_g).sum())
accepted = C[C["band"] == "accept"]
naive = C[C["has_xy"] & (C["name_jw"] >= 0.92) & (C["dist_m"] < 1000)]
stats = {
    "records": {"makemytrip": n_m, "goibibo": n_g}, "candidates": len(C), "bands": C["band"].value_counts().to_dict(),
    "t_accept": T_ACC, "t_reject": T_REJ, "accepted_pairs": len(accepted), "accepted_one_to_one": len(keep),
    "goibibo_with_accepted_twin": len(gob_ids(accepted)), "goibibo_with_naive_rule_twin": len(gob_ids(naive)),
    "accepted_not_found_by_naive_rule": int((~accepted.index.isin(naive.index)).sum()),
    "naive_rule_pairs_not_accepted": int((~naive.index.isin(accepted.index)).sum()),
    "accepted_same_city_share": float(accepted["same_city"].mean()), "accepted_median_dist_m": float(accepted["dist_m"].median()),
    "accepted_p90_dist_m": float(accepted["dist_m"].quantile(0.9)), "accepted_name_jw_lt_0.85": float((accepted["name_jw"] < 0.85).mean()),
    "uncertain_goibibo": len(gob_ids(C[C["band"] == "uncertain"]) - gob_ids(accepted)),
}
log(json.dumps(stats))
C.to_parquet(OUT / "pairs.parquet")
(REP / "ota_matcher.json").write_text(json.dumps(stats, indent=1), encoding="utf-8")


def rows(frame, k):
    frame = frame.sample(min(k, len(frame)), random_state=7)
    out = []
    for ra, rb, p, dm, band, jw in zip(frame["ra"], frame["rb"], frame["p"], frame["dist_m"], frame["band"], frame["name_jw"]):
        x, y = G.iloc[ra], G.iloc[rb]
        out.append({"pair_id": f"{x['src_id']}|{y['src_id']}", "band": band, "p": round(float(p), 4), "name_jw": round(float(jw), 2),
                    "dist_m": None if pd.isna(dm) else int(dm),
                    "source_a": x["source"], "name_a": x["name"], "city_a": x["city"], "address_a": x["street"],
                    "source_b": y["source"], "name_b": y["name"], "city_b": y["city"], "address_b": y["street"], "human_label": ""})
    return out


sheet = pd.DataFrame(rows(accepted, 120) + rows(C[C["band"] == "uncertain"], 80) + rows(naive[~naive.index.isin(accepted.index)], 40)
                     + rows(C[C["band"] == "name-only: review"], 40)).drop_duplicates("pair_id").sample(frac=1.0, random_state=7)
sheet.drop(columns=["band", "p", "name_jw"]).to_csv(OUT / "label_sheet.csv", index=False, encoding="utf-8-sig")
sheet[["pair_id", "band", "p"]].to_csv(OUT / "label_sheet_key.csv", index=False)


def table(frame, k):
    L = ["| MakeMyTrip | Goibibo | Dist (m) | Name JW | p |", "|---|---|---:|---:|---:|"]
    for r_ in rows(frame, k):
        m_, g_ = (r_["name_a"], r_["name_b"]) if r_["source_a"] == "makemytrip" else (r_["name_b"], r_["name_a"])
        L.append(f"| {m_} ({r_['city_a']}) | {g_} | {r_['dist_m'] if r_['dist_m'] is not None else ''} | {r_['name_jw']:.2f} | {r_['p']:.3f} |")
    return L


bands = stats["bands"]
L = ["# Transfer test: the city-trained matcher on two real supplier feeds (MakeMyTrip x Goibibo)", "",
     "Generated by `scripts/train/ota_matcher.py`. **Nothing was trained on these feeds.** The pair model, its vectorisers and its thresholds come "
     "from the 12-city open-data benchmark (`reports/models/city_matcher.md`); none of those cities' data came from these suppliers. "
     "There are no labels here, so this report gives counts and examples. A precision figure needs the label sheet at "
     "`data/processed/ota_matcher/label_sheet.csv`.", "",
     "## Result", "",
     "| Measure | Value |", "|---|---:|",
     f"| MakeMyTrip properties / Goibibo properties | {n_m:,} / {n_g:,} |",
     f"| Candidate pairs after blocking | {len(C):,} |",
     f"| Accepted (p >= {T_ACC:.3f}, both sides geocoded) | {bands.get('accept', 0):,} |",
     f"| Uncertain (to the next cascade stage) | {bands.get('uncertain', 0):,} |",
     f"| Name-only candidates held for review (a side has no usable coordinates) | {bands.get('name-only: review', 0):,} |",
     f"| Rejected | {bands.get('reject', 0):,} |",
     f"| **Goibibo properties with an accepted MakeMyTrip twin** | **{stats['goibibo_with_accepted_twin']:,} ({stats['goibibo_with_accepted_twin'] / n_g:.1%})** |",
     f"| Goibibo properties with a twin under the naive rule (name JW >= 0.92 within 1 km) | {stats['goibibo_with_naive_rule_twin']:,} ({stats['goibibo_with_naive_rule_twin'] / n_g:.1%}) |",
     f"| Accepted pairs the naive rule misses | {stats['accepted_not_found_by_naive_rule']:,} |",
     f"| Naive-rule pairs the model does not accept | {stats['naive_rule_pairs_not_accepted']:,} |",
     f"| Accepted pairs after forcing one-to-one | {stats['accepted_one_to_one']:,} of {stats['accepted_pairs']:,} |", "",
     f"Accepted pairs: both feeds name the same city in {stats['accepted_same_city_share']:.1%} of them (city is not a model input, so this is an independent check); "
     f"median distance {stats['accepted_median_dist_m']:.0f} m, p90 {stats['accepted_p90_dist_m']:.0f} m; {stats['accepted_name_jw_lt_0.85']:.1%} have name similarity below 0.85.",
     f"The gap between {stats['accepted_pairs']:,} accepted pairs and {stats['accepted_one_to_one']:,} one-to-one pairs is duplicates inside a feed: "
     "one hotel listed under two property IDs by the same supplier.", "",
     "## Samples (random, not hand-checked)", "", "### Accepted", ""] + table(accepted, 14)
L += ["", "### Accepted although the naive rule misses them", ""] + table(accepted[~accepted.index.isin(naive.index)], 10)
L += ["", "### Naive rule says match, model does not accept", ""] + table(naive[~naive.index.isin(accepted.index)], 10)
L += ["", "### Uncertain band", ""] + table(C[C["band"] == "uncertain"], 10)
L += ["", "## Caveats", "",
      "- 2016 crawls, samples of each catalogue: the overlap is a lower bound on what the full feeds share.",
      "- 24% of MakeMyTrip properties have no usable coordinates. Their candidates come from name similarity alone and are held for review, never auto-accepted.",
      "- MakeMyTrip marks 57% of properties as 1 star, which looks like its default for unrated; those ratings are treated as unknown.",
      "- The accept threshold was calibrated for 99% precision on the open-data benchmark's weak labels. Whether it holds on these feeds is what the label sheet is for."]
(REP / "ota_matcher.md").write_text("\n".join(L) + "\n", encoding="utf-8")
log("wrote reports/models/ota_matcher.md")
