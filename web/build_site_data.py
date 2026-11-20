"""Export the real pipeline outputs the website's story sections draw, into web/static/data/*.json.

Every record, edge, score and feature value here comes from the 12-city run of scripts/train/city_matcher.py
(data/processed/city_matcher/*) or from the validation demo bundle (submission/round1/demo/data.js, scripts/demo/build_demo_data.py).
Headline numbers are NOT written here: the page reads them from submission/round1/numbers.json at runtime.

What is simulated, and tagged as such on the page: offer prices, policies and supplier reliability (marina / offers).

Input : data/processed/city_matcher/{clusters,pairs}.parquet, model.lgb, featurizer_no_emb.joblib, [loco/model_<city>.lgb],
        data/interim/listings.parquet, submission/round1/demo/data.js, submission/round1/demo/basemap.js
Output: web/static/data/landing.json, web/static/data/story.json
Usage : .venv\\Scripts\\python.exe -I -X utf8 web\\build_site_data.py
"""
import json
import re
import sys
from pathlib import Path

import joblib
import lightgbm as lgb
import numpy as np
import pandas as pd
from rapidfuzz import fuzz
from shapely.geometry import LineString

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from canon.activities import norm as anorm  # noqa: E402
from canon.match import prepare  # noqa: E402

CM = ROOT / "data" / "processed" / "city_matcher"
OUT = ROOT / "web" / "static" / "data"
OUT.mkdir(parents=True, exist_ok=True)
SRC = ["overture", "osm", "wikidata", "wikivoyage"]
CITY = "dubai"
NUM = json.loads((ROOT / "submission" / "round1" / "numbers.json").read_text(encoding="utf-8"))

art = joblib.load(CM / "featurizer_no_emb.joblib")
FEATS, T_ACC, T_REJ = art["features"], art["t_accept"], art["t_reject"]
G = pd.read_parquet(CM / "clusters.parquet")
C = pd.read_parquet(CM / "pairs.parquet")
C = C[C["city"] == CITY].copy()
L = pd.read_parquet(ROOT / "data" / "interim" / "listings.parquet")
L = prepare(L[L["lat"].notna() & L["in_bbox"].fillna(False)].reset_index(drop=True))  # same rid as the training run
assert len(L) == len(G) and (L["name"].to_numpy() == G["name"].to_numpy()).all(), "listings no longer line up with clusters.parquet"


def route_of(y, p):
    if y == 1:
        return "key_match"
    if y == 0:
        return "key_reject"
    return "model_accept" if p >= T_ACC else ("model_reject" if p < T_REJ else "uncertain")


C["route"] = [route_of(y, p) for y, p in zip(C["y"], C["p"])]
C["accepted"] = C["route"].isin(["key_match", "model_accept"])

# ============================================================================ landing: Dubai lodging, real clusters
g = G[(G["city"] == CITY) & (G["kind"] == "lodging")].reset_index(drop=True)
assert len(g) == NUM["matching"]["dubai"]["lodging_listings"], (len(g), NUM["matching"]["dubai"])
assert g["cluster"].nunique() == NUM["matching"]["dubai"]["canonical_entities"]
pos = {r: i for i, r in enumerate(g["rid"])}
dense = {c: k for k, c in enumerate(pd.unique(g["cluster"]))}
g["cl"] = g["cluster"].map(dense)
cent = g.groupby("cl").agg(lat=("lat", "mean"), lon=("lon", "mean"), n=("rid", "size")).sort_index()
E = C[C["accepted"] & C["ra"].isin(pos) & C["rb"].isin(pos)]
E = E[E["ra"].map(g.set_index("rid")["cluster"]) == E["rb"].map(g.set_index("rid")["cluster"])]


def thin_line(pts, tol_deg):
    ls = LineString([(lon, lat) for lat, lon in pts]).simplify(tol_deg, preserve_topology=False)
    return [round(v, 5) for xy in ls.coords for v in xy]


bm = (ROOT / "submission" / "round1" / "demo" / "basemap.js").read_text(encoding="utf-8")
B = json.loads(bm[bm.index("=") + 1:].strip().rstrip(";"))
w, s, e, n = float(g["lon"].min()) - 0.02, float(g["lat"].min()) - 0.02, float(g["lon"].max()) + 0.02, float(g["lat"].max()) + 0.02


def inside(line):
    return any(w <= lo <= e and s <= la <= n for la, lo in line)


basemap = {k: [thin_line(x, tol) for x in B[k] if len(x) >= 2 and inside(x)] for k, tol in (("coast", 0.00012), ("water", 0.00015), ("major", 0.0002))}
basemap = {k: [x for x in v if len(x) >= 4] for k, v in basemap.items()}
landing = {
    "city": CITY, "sources": SRC, "bbox": [w, s, e, n],
    "lat": g["lat"].round(5).tolist(), "lon": g["lon"].round(5).tolist(), "src": g["source"].map(SRC.index).tolist(),
    "name": g["name"].tolist(), "cl": g["cl"].tolist(),
    "clusters": {"lat": cent["lat"].round(5).tolist(), "lon": cent["lon"].round(5).tolist(), "n": cent["n"].tolist()},
    "edges": [[pos[a], pos[b]] for a, b in zip(E["ra"], E["rb"])],
    "edge_route": E["route"].map({"key_match": 0, "model_accept": 1}).tolist(),
    "basemap": basemap,
    "provenance": "data/processed/city_matcher/clusters.parquet + pairs.parquet (scripts/train/city_matcher.py); basemap: submission/round1/demo/basemap.js, © OpenStreetMap contributors",
}
(OUT / "landing.json").write_text(json.dumps(landing, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
print(f"landing: {len(g)} listings, {len(cent)} entities, {len(E)} edges, basemap " + ", ".join(f"{k} {len(v)}" for k, v in basemap.items()))

# ============================================================================ demo bundle (real names / matches; simulated offers)
dj = (ROOT / "submission" / "round1" / "demo" / "data.js").read_text(encoding="utf-8")
D = json.loads(dj[dj.index("=") + 1:].strip().rstrip(";"))
marina = {"cards": D["offers"]["cards"], "params": D["offers"]["params"], "suppliers": D["offers"]["suppliers"], "note": D["offers"]["note"]}

# ============================================================================ blocking: a real neighbourhood of Dubai, all kinds
box = dict(s=25.072, n=25.092, w=55.128, e=55.150)  # Dubai Marina / JBR walk
gd = G[G["city"] == CITY]
inb = gd[gd["lat"].between(box["s"], box["n"]) & gd["lon"].between(box["w"], box["e"])]
ids = set(inb["rid"])
cb = C[C["ra"].isin(ids) & C["rb"].isin(ids)]
bpos = {r: i for i, r in enumerate(inb["rid"])}
blocking = {
    "box": box, "records": len(inb), "lat": inb["lat"].round(6).tolist(), "lon": inb["lon"].round(6).tolist(),
    "src": inb["source"].map(SRC.index).tolist(), "kind": inb["kind"].tolist(), "name": inb["name"].tolist(),
    "cand": [[bpos[a], bpos[b], int(gg) | (2 * int(nn))] for a, b, gg, nn in zip(cb["ra"], cb["rb"], cb["by_geo"], cb["by_name"])],
    "cand_outside": int(len(C[(C["ra"].isin(ids)) ^ (C["rb"].isin(ids))])),
    "params": art["blocking"],
}
print(f"blocking box: {len(inb)} records, {len(cb)} candidates inside, {blocking['cand_outside']} leaving the box")

# ============================================================================ evidence: Atlantis, The Palm, four sources
final = lgb.Booster(model_file=str(CM / "model.lgb"))
loco_path = CM / "loco" / f"model_{CITY}.lgb"
loco = lgb.Booster(model_file=str(loco_path)) if loco_path.exists() else None
at = G[(G["city"] == CITY) & (G["name"].str.contains("Atlantis, The Palm|أتلانتس", regex=True))]
atl_cluster = at["cluster"].mode().iloc[0]
mem = G[(G["cluster"] == atl_cluster) & (G["kind"] == "lodging")]  # the four lodging listings; the cluster also holds a Wikivoyage attraction entry
ap = C[C["ra"].isin(mem["rid"]) & C["rb"].isin(mem["rid"])].copy()
Fa = ap[[f for f in FEATS if f != "src_pair"]].copy()
Fa.insert(FEATS.index("src_pair"), "src_pair", pd.Categorical(ap["src_pair"], categories=art["src_pair_categories"]))
Fa = Fa[FEATS]


def rec(rid):
    r = L.iloc[rid]
    alts = [a for a in (r["alt_names"] if r["alt_names"] is not None else []) if isinstance(a, str)]
    return {"rid": int(rid), "source": r["source"], "name": r["name"], "alt_names": alts[:6], "lat": round(float(r["lat"]), 6), "lon": round(float(r["lon"]), 6),
            "street": r["street"] if isinstance(r["street"], str) else None, "brand": r["brand"] if isinstance(r["brand"], str) else None,
            "stars": None if pd.isna(r["stars"]) else float(r["stars"]), "qid": r["qid"] if isinstance(r["qid"], str) else None,
            "has_phone": isinstance(r["phone8"], str), "has_website": isinstance(r["website"], str), "kind": r["kind"]}


pairs = []
for k, (idx, row) in enumerate(ap.iterrows()):
    labelled = int(row["y"]) >= 0
    booster = loco if (labelled and loco is not None) else (final if not labelled else None)
    item = {"a": int(row["ra"]), "b": int(row["rb"]), "p": round(float(row["p"]), 4), "y": int(row["y"]), "label_src": row["label_src"],
            "route": row["route"], "model": "loco" if labelled else "final",
            "features": {f: (None if pd.isna(row[f]) else round(float(row[f]), 4)) for f in FEATS if f != "src_pair"} | {"src_pair": row["src_pair"]}}
    if booster is not None:
        cz = booster.predict(Fa.iloc[[k]], pred_contrib=True)[0]
        pz = float(booster.predict(Fa.iloc[[k]])[0])
        assert abs(1 / (1 + np.exp(-cz.sum())) - pz) < 1e-6
        if abs(pz - float(row["p"])) > 1e-4:
            print(f"  warning: booster p {pz:.4f} differs from stored p {row['p']:.4f} for pair {row['ra']}-{row['rb']}; contributions dropped")
        else:
            item["contrib"] = {f: round(float(v), 4) for f, v in zip(FEATS, cz[:-1])}
            item["bias"] = round(float(cz[-1]), 4)
    pairs.append(item)
atlantis = {"members": [rec(r) for r in mem["rid"]], "pairs": pairs, "t_accept": T_ACC, "t_reject": T_REJ,
            "note": "features and scores from pairs.parquet; labelled pairs carry their leave-one-city-out score, as in training"}
print("atlantis:", [(m["source"], m["name"]) for m in atlantis["members"]], [(p["route"], p["p"], "contrib" in p) for p in pairs])

# ============================================================================ clustering: a merge the cannot-link rule refuses
y_all = None
CA = pd.read_parquet(CM / "pairs.parquet", columns=["ra", "rb", "p", "y", "city"])
key_match, key_reject = CA["y"].to_numpy() == 1, CA["y"].to_numpy() == 0
rest = ~(key_match | key_reject)
acc = key_match | (rest & (CA["p"].to_numpy() >= T_ACC))
EA = CA.loc[acc, ["ra", "rb", "p", "city"]].assign(w=lambda x: np.where(key_match[acc], 2.0, x["p"])).sort_values("w", ascending=False)
parent = np.arange(len(G))
qid_of = [({q} if isinstance(q, str) else set()) for q in G["qid"]]


def find(x):
    while parent[x] != x:
        parent[x] = parent[parent[x]]
        x = parent[x]
    return x


refused = []
for ra, rb, wt in zip(EA["ra"].to_numpy(), EA["rb"].to_numpy(), EA["w"].to_numpy()):
    x, yv = find(ra), find(rb)
    if x == yv:
        continue
    if qid_of[x] and qid_of[yv] and qid_of[x] != qid_of[yv]:
        refused.append((int(ra), int(rb), float(wt)))
        continue
    parent[x] = yv
    qid_of[yv] = qid_of[yv] | qid_of[x]
assert len(refused) == json.loads((ROOT / "reports" / "models" / "city_matcher.json").read_text(encoding="utf-8"))["qid_cannot_link_blocks"]
nm = G.set_index("rid")
pick = next((r for r in refused if nm.loc[r[0], "name"] == "Grand Hyatt Dubai" and "Residence" in nm.loc[r[1], "name"]), None)
assert pick is not None
ra, rb, wt = pick
ca_, cb_ = nm.loc[ra, "cluster"], nm.loc[rb, "cluster"]
side = []
for cid in (ca_, cb_):
    mm = G[G["cluster"] == cid]
    ee = C[C["ra"].isin(mm["rid"]) & C["rb"].isin(mm["rid"]) & C["accepted"]]
    side.append({"members": [rec(r) for r in mm["rid"]], "edges": [{"a": int(a), "b": int(b), "p": round(float(p), 3), "route": rt}
                                                                  for a, b, p, rt in zip(ee["ra"], ee["rb"], ee["p"], ee["route"])]})
cannot = {"refused": {"a": ra, "b": rb, "p": round(wt, 3)}, "clusters": side}
print("cannot-link:", nm.loc[ra, "name"], "<->", nm.loc[rb, "name"], wt, [len(s_["members"]) for s_ in side])

# ============================================================================ tours: Universal Studios Singapore (real Klook titles, library relations)
fam = next(f for f in D["activities"] if f["family"].startswith("Universal Studios"))
keep = [0, 1, 2, 3]  # ticket, Express pass, combo, VIP tour
items = [fam["items"][i] for i in keep]
rels = [r for r in fam["relations"] if r["a"] in keep and r["b"] in keep]


def clean(title):  # as scripts/train/activities_benchmark.py
    t = re.sub(r"\[[^\]]+\]", " ", title).replace("™", "")
    t = re.sub(r"(?i)\s+in\s+(singapore|sentosa)\s*$", "", t)
    return re.sub(r"\s+", " ", t).strip(" -:,")


dedup = []
for i in range(len(items)):
    for j in range(i + 1, len(items)):
        ts = fuzz.token_set_ratio(anorm(clean(items[i]["title"])), anorm(clean(items[j]["title"])))
        dedup.append({"a": i, "b": j, "token_set": round(ts, 1), "merged": bool(ts >= 85)})
tours = {"family": fam["family"], "items": items, "relations": rels, "dedup": dedup,
         "dedup_rule": "token-set similarity >= 85 on the cleaned title (scripts/train/activities_benchmark.py)"}
print("tours dedup:", [(d["a"], d["b"], d["token_set"], d["merged"]) for d in dedup])

# ============================================================================ rooms: one real hotel's room list (Booking.com) and the supplier strings
hotel = next(h for h in D["rooms"] if h["hotel"].startswith("Hilton Diagonal"))
rooms = {"hotel": hotel["hotel"], "a": [{"name": x["name"], "bookings": x["bookings"]} for x in hotel["a"]],
         "b": [{"name": x["name"], "true": x["true"], "mapped": x["mapped"]} for x in hotel["b"]], "focus": "TWN PARTIAL SV HB NRF"}

# the literal parse of the focus string, from the same code the workbench's room bench calls (web/api/benches.py)
sys.path.insert(0, str(ROOT / "web"))
from api.benches import room_view, rooms_map  # noqa: E402

BOARD = {"BB": "breakfast", "RO": "room only", "HB": "half board", "FB": "full board", "AI": "all inclusive"}


def chip_label(t):
    a, v = t["attr"], t["value"]
    if a == "beds":
        return "/".join(v) + " bed"
    if a == "view":
        return f"{v} view" if v != "view" else "view"
    if a == "board":
        return BOARD.get(v, v)
    if a == "refundable":
        return "free cancellation" if v else "non-refundable"
    if a in ("room_class", "features", "inclusions"):
        return str(v).replace("_", " ")
    return str(v).replace("_", " ") if v is not None else t["raw"]


def sig_text(room):
    parts = ([room["room_type"]] if room["room_type"] != "room" else []) + list(room["room_class"]) + ["/".join(room["beds"]) + " bed" if room["beds"] else ""]
    parts += [f"{room['view']} view" if room["view"] else ""] + [f.replace("_", " ") for f in room["features"]] + list(room["name_tokens"])
    return " · ".join(x for x in parts if x) or "room"


fv = room_view(rooms["focus"])
mp = rooms_map([a["name"] for a in rooms["a"]], [rooms["focus"]])[0]
seen = set()
toks = []
for t in fv["tokens"]:
    key = (t["side"], t["attr"], str(t["value"]))
    toks.append({"raw": t["raw"], "side": t["side"], "attr": (t["attr"] or "").replace("_", " "), "rule": t["rule"],
                 "label": chip_label(t) if t["side"] in ("room", "rate") else t["raw"], "first": key not in seen})
    seen.add(key)
rooms_trace = {"tokens": [t for t in toks if t["first"] or t["side"] not in ("room", "rate")], "raw_tokens": toks, "normalised": fv["normalised"],
               "signature_text": sig_text(fv["room"]), "match": mp["match"], "why": mp["why"],
               "a_signatures": [sig_text(room_view(a["name"])["room"]) for a in rooms["a"]]}
print("rooms trace:", [(t["raw"], t["side"], t["label"]) for t in toks], "->", rooms["a"][mp["match"]]["name"] if mp["match"] is not None else None, mp["why"])

story = {"rooms_trace": rooms_trace, "marina": marina, "blocking": blocking, "atlantis": atlantis, "cannot_link": cannot, "tours": tours, "rooms": rooms,
         "sources": SRC, "t_accept": T_ACC, "t_reject": T_REJ}
(OUT / "story.json").write_text(json.dumps(story, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
for f in ("landing.json", "story.json"):
    print(f, f"{(OUT / f).stat().st_size / 1e3:.0f} kB")

# static hosting (e.g. Vercel) has no /numbers.json route: ship an exact copy next to the page. The local server
# still serves the live file, which takes precedence; re-run this script whenever numbers.json changes.
import shutil  # noqa: E402
shutil.copyfile(ROOT / "submission" / "round1" / "numbers.json", ROOT / "web" / "static" / "numbers.json")
print("copied numbers.json into web/static for static hosting")
