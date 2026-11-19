"""Build the Kaggle dataset for the city-matcher cross-encoder (kaggle/city_xenc).

records.parquet: rid, city, text. The text is what the cross-encoder reads: name, up to three alternate names, kind and
category, street. Phone, website and Wikidata QID are left out on purpose: they define the weak labels.
pairs.parquet: the labelled candidate pairs (y in {0, 1}) with their out-of-city stage-1 score, the stage-2 score from
city_matcher_stage2.py (nested, never saw the pair's city) and the distance.

Usage : .venv\\Scripts\\python.exe -I -X utf8 scripts\\train\\city_xenc_data.py
Output: data/interim/kaggle_city_pairs/{records,pairs}.parquet + dataset-metadata.json
"""
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
CM = ROOT / "data" / "processed" / "city_matcher"
OUT = ROOT / "data" / "interim" / "kaggle_city_pairs"
OUT.mkdir(parents=True, exist_ok=True)

G = pd.read_parquet(CM / "clusters.parquet", columns=["rid", "source", "src_id", "city", "kind", "name"])
L = pd.read_parquet(ROOT / "data" / "interim" / "listings.parquet", columns=["source", "src_id", "category", "alt_names", "street"])
L = L.drop_duplicates(["source", "src_id"])
G = G.merge(L, on=["source", "src_id"], how="left")


def alts(row):
    xs = row["alt_names"]
    if xs is None or (isinstance(xs, float) and np.isnan(xs)):
        return ""
    xs = [a for a in dict.fromkeys(xs) if isinstance(a, str) and a and a != row["name"]][:3]
    return (" / " + " / ".join(xs)) if xs else ""


cat = G["category"].fillna("").astype(str).str.replace(r"^[a-z_]+=", "", regex=True).str.replace("_", " ")
G["text"] = (G["name"].astype(str) + G.apply(alts, axis=1) + " | " + G["kind"].fillna("") + ": " + cat + " | " + G["street"].fillna("").astype(str)).str.strip(" |:")
G[["rid", "city", "text"]].to_parquet(OUT / "records.parquet", index=False)

P = pd.read_parquet(CM / "pairs.parquet", columns=["ra", "rb", "city", "y", "p", "dist_m"])
S = pd.read_parquet(CM / "stage2_oof.parquet", columns=["ra", "rb", "p_stage2_oof"])
P = P.merge(S, on=["ra", "rb"], how="left")
P = P[P["y"] >= 0].rename(columns={"p": "p1", "p_stage2_oof": "p2"}).reset_index(drop=True)
P.to_parquet(OUT / "pairs.parquet", index=False)
(OUT / "dataset-metadata.json").write_text('{"title": "canon-city-pairs", "id": "nishkarshsinghal/canon-city-pairs", "licenses": [{"name": "other"}]}')
print(len(G), "records;", len(P), "labelled pairs;", int(P["p2"].isna().sum()), "without stage-2 score")
print(G["text"].sample(5, random_state=1).tolist())
