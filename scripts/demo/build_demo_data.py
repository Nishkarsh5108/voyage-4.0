"""Export real pipeline outputs into one JavaScript data file for the validation demo (submission/round1/demo/index.html).

What is real and what is simulated in the bundle:
  real       listings, names, coordinates, clusters, pair scores, key evidence (Dubai, four open sources);
             Booking.com room names; Klook products, options, prices; every number under `evidence`
  simulated  the second supplier's room strings (rewrites), and every price / policy / reliability figure under `offers`
The demo page labels the simulated parts on screen.

Input : data/processed/city_matcher/*, data/interim/*, reports/models/*.json, kaggle/fsq_pair_model/output/metrics.json
Output: submission/round1/demo/data.js  (window.DEMO = {...})
Usage : python -I scripts/demo/build_demo_data.py
"""
import hashlib
import json
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from canon.activities import Gazetteer, norm as anorm, parse_activity, parse_policy, relate  # noqa: E402
from canon.rooms import parse_room  # noqa: E402

CM = ROOT / "data" / "processed" / "city_matcher"
CITY = "dubai"
SRC_LABEL = {"overture": "Overture", "osm": "OpenStreetMap", "wikidata": "Wikidata", "wikivoyage": "Wikivoyage"}
PRIORITY = {"wikivoyage": 0, "osm": 1, "wikidata": 2, "overture": 3}

# ============================================================================ 1. matching: Dubai lodging clusters
G = pd.read_parquet(CM / "clusters.parquet")
C = pd.read_parquet(CM / "pairs.parquet", columns=["ra", "rb", "city", "p", "y", "label_src", "dist_m", "name_jw", "name_token_set_alt"])
g = G[(G["city"] == CITY) & (G["kind"] == "lodging")].copy()
sizes = g.groupby("cluster").agg(n=("rid", "size"), ns=("source", "nunique"))
multi = sizes[sizes["ns"] >= 2].index
gm = g[g["cluster"].isin(multi)]
rid_set = set(gm["rid"])
E = C[(C["city"] == CITY) & C["ra"].isin(rid_set) & C["rb"].isin(rid_set)]
E = E.merge(gm[["rid", "cluster"]].rename(columns={"rid": "ra", "cluster": "ca"}), on="ra").merge(gm[["rid", "cluster"]].rename(columns={"rid": "rb", "cluster": "cb"}), on="rb")
E = E[E["ca"] == E["cb"]]


def latin(s):
    return bool(re.search(r"[A-Za-z]", s or ""))


clusters = []
for cid, mem in gm.groupby("cluster"):
    mem = mem.assign(pr=mem["source"].map(PRIORITY), lat_=mem["name"].map(latin)).sort_values(["lat_", "pr"], ascending=[False, True])
    edges = E[E["ca"] == cid]
    clusters.append({
        "id": int(cid), "name": mem.iloc[0]["name"], "lat": round(float(mem["lat"].mean()), 6), "lon": round(float(mem["lon"].mean()), 6),
        "members": [{"rid": int(r.rid), "src": r.source, "name": r.name, "lat": round(float(r.lat), 6), "lon": round(float(r.lon), 6),
                     "qid": r.qid if isinstance(r.qid, str) else None} for r in mem.itertuples()],
        "edges": [{"a": int(e.ra), "b": int(e.rb), "p": round(float(e.p), 3), "d": int(round(float(e.dist_m))), "jw": round(float(e.name_jw), 2),
                   "key": e.label_src if int(e.y) == 1 else None} for e in edges.itertuples()],
    })
clusters.sort(key=lambda c: (-len(c["members"]), c["name"]))

# a few pairs the model is unsure about: the review queue
unc = C[(C["city"] == CITY) & (C["y"] == -1) & (C["p"].between(0.35, 0.93))].sample(60, random_state=7)
unc = unc.merge(G[["rid", "name", "source", "kind"]].rename(columns=lambda c: c + "_a"), left_on="ra", right_on="rid_a") \
         .merge(G[["rid", "name", "source", "kind"]].rename(columns=lambda c: c + "_b"), left_on="rb", right_on="rid_b")
unc = unc[(unc["kind_a"] == "lodging") & (unc["kind_b"] == "lodging")].head(14)
review = [{"a": r.name_a, "sa": r.source_a, "b": r.name_b, "sb": r.source_b, "p": round(float(r.p), 2), "d": int(round(float(r.dist_m))),
           "jw": round(float(r.name_jw), 2)} for r in unc.itertuples()]

cm = json.loads((ROOT / "reports" / "models" / "city_matcher.json").read_text(encoding="utf-8"))
matching = {
    "city": CITY, "listings": int(len(g)), "entities": int(g["cluster"].nunique()), "multi_source_entities": int(len(multi)),
    "by_source": {SRC_LABEL[k]: int(v) for k, v in g.groupby("source").size().items()},
    "clusters": clusters, "review": review, "threshold": round(cm["cascade"]["t_accept"], 3),
}

# ============================================================================ 2. listing page + simulated offers
# The search: lodging near Dubai Marina / JBR. Cards before = one per source listing; after = one per canonical hotel.
box = dict(s=25.066, n=25.098, w=55.120, e=55.150)
area = [c for c in clusters if box["s"] <= c["lat"] <= box["n"] and box["w"] <= c["lon"] <= box["e"]]
area = sorted(area, key=lambda c: -len({m["src"] for m in c["members"]}))[:9]
SUPPLIERS = {  # simulated commercial behaviour of each feed
    "overture": {"label": "Supplier A", "markup": 0.00, "fail": 0.060, "chg": 0.12},
    "osm": {"label": "Supplier B", "markup": 0.035, "fail": 0.010, "chg": 0.03},
    "wikidata": {"label": "Supplier C", "markup": 0.06, "fail": 0.020, "chg": 0.05},
    "wikivoyage": {"label": "Supplier D", "markup": -0.01, "fail": 0.035, "chg": 0.08},
}
POLICIES = [("Free cancellation until 2 days before", 48), ("Free cancellation until 7 days before", 168), ("Non-refundable", None)]
listing = []
for c in area:
    h = int(hashlib.md5(c["name"].encode()).hexdigest(), 16)
    rs = np.random.default_rng(h % (2 ** 32))
    base = int(rs.integers(6500, 32000))
    offers, seen = [], set()
    for m in c["members"]:
        if m["src"] in seen:
            continue
        seen.add(m["src"])
        s = SUPPLIERS[m["src"]]
        pol = POLICIES[int(rs.integers(0, 3))]
        offers.append({"supplier": s["label"], "src": m["src"], "listed_as": m["name"],
                       "price": int(round(base * (1 + s["markup"] + rs.normal(0, 0.018)), -1)), "policy": pol[0], "cutoff_h": pol[1],
                       "pay": "Pay at hotel" if rs.random() < 0.3 else "Prepay", "fail": s["fail"], "chg": s["chg"]})
    listing.append({"id": c["id"], "name": c["name"], "lat": c["lat"], "lon": c["lon"], "offers": offers})
offers = {"note": "Simulated: prices, policies, payment terms and supplier reliability are generated. Names, pins and matches are real.",
          "suppliers": SUPPLIERS, "cards": listing, "params": {"fail_cost_share": 0.18, "price_jump_share": 0.07, "flex_value_share": 0.03}}

# ============================================================================ 3. rooms: real hotels, simulated second supplier
R = pd.read_parquet(ROOT / "data" / "interim" / "room_strings.parquet")
ABBR = [("double or twin", "DBL/TWN"), ("junior suite", "JR STE"), ("sea view", "SV"), ("city view", "CV"), ("garden view", "GV"), ("double", "DBL"),
        ("twin", "TWN"), ("single", "SGL"), ("triple", "TPL"), ("deluxe", "DLX"), ("standard", "STD"), ("superior", "SUP"), ("executive", "EXEC"),
        ("suite", "STE"), ("rooms", ""), ("room", ""), ("with", "")]
RATE = [("BB", "NRF"), ("RO", ""), ("HB", "NRF"), ("BB", ""), ("RO", "NRF")]


def rewrite(s, i):
    t = s.lower()
    for k, v in ABBR:
        t = re.sub(rf"\b{k}\b", v, t)
    b, r_ = RATE[i % len(RATE)]
    return re.sub(r"\s+", " ", f"{t} {b} {r_}").strip().upper()


def room_view(p):
    return {"type": p.room_type, "class": list(p.room_class), "beds": list(p.beds), "view": p.view, "features": list(p.features),
            "name_tokens": list(p.name_tokens), "board": p.board, "refundable": p.refundable, "inclusions": list(p.inclusions), "promo": p.promo}


rooms = []
for hotel in ["Hilton Diagonal Mar Barcelona", "Park Plaza Westminster Bridge London", "Hotel Arena", "InterContinental London The O2", "Grand Hotel Amr th Amsterdam"]:
    rr = R[R["hotel"] == hotel].sort_values("n", ascending=False).head(9)
    if len(rr) < 4:
        continue
    A = [{"name": r.room, "bookings": int(r.n), "parsed": room_view(parse_room(r.room))} for r in rr.itertuples()]
    sigA = [parse_room(a["name"]).signature() for a in A]
    B = []
    for i, a in enumerate(A):
        s = rewrite(a["name"], i)
        p = parse_room(s)
        hits = [j for j, sg in enumerate(sigA) if sg == p.signature()]
        B.append({"name": s, "true": i, "mapped": hits[0] if len(hits) == 1 else None, "parsed": room_view(p)})
    rooms.append({"hotel": hotel.replace("Amr th", "Amrâth"), "a": A, "b": B})
rb = json.loads((ROOT / "reports" / "models" / "rooms.json").read_text(encoding="utf-8"))

# ============================================================================ 4. sightseeing families (real Klook Singapore products)
P = pd.read_parquet(ROOT / "data" / "interim" / "klook_products.parquet")
O = pd.read_parquet(ROOT / "data" / "interim" / "klook_options.parquet")
P = P[(P["city"] == "Singapore") & P["lat"].notna()].reset_index(drop=True)
L = pd.read_parquet(ROOT / "data" / "interim" / "listings.parquet")
L = L[(L["city"] == "singapore") & (L["kind"] == "attraction")]
keep = (L["source"].isin(["wikidata", "wikivoyage"]) | ((L["source"] == "osm") & L["category"].fillna("").str.contains(
    r"tourism=(?:attraction|museum|theme_park|zoo|aquarium|gallery|viewpoint)|leisure=water_park")))
names = set(L.loc[keep, "name"].dropna())
names |= {re.sub(r"(?i)[ ,]+(singapore|sentosa)$", "", n).strip() for n in names}
gaz = Gazetteer([n for n in names if anorm(n) not in {"singapore", "sentosa", "marina bay", "orchard road", "chinatown", "little india", "the garden", "city hall"}])


def clean(t):
    return re.sub(r"\s+", " ", re.sub(r"\[[^\]]+\]", " ", t).replace("™", "")).strip(" -:,")


FAMILIES = {"Universal Studios Singapore": r"universal studios", "Singapore Flyer": r"singapore flyer", "Singapore Cable Car": r"cable car",
            "S.E.A. Aquarium": r"s\.e\.a\. aquarium", "Singapore Zoo and Night Safari": r"singapore zoo|night safari"}
activities = []
for fam, pat in FAMILIES.items():
    ps = P[P["title"].str.contains(pat, case=False, regex=True)].head(5)
    items = []
    for r in ps.itertuples():
        a = parse_activity(r.title, gazetteer=gaz)
        opts = list(O[O["product_id"] == r.id]["option"].head(4))
        items.append({"title": r.title, "clean": clean(r.title), "price": r.price, "currency": r.currency, "booked": int(r.booked or 0),
                      "policy": parse_policy(r.policy)["klass"], "tags": list(a.promo_tags), "attractions": sorted(a.attractions), "access": a.access,
                      "inclusions": sorted(a.inclusions), "options": opts})
    rel = []
    for i in range(len(items)):
        for j in range(i + 1, len(items)):
            x = relate(parse_activity(items[i]["title"], gazetteer=gaz), parse_activity(items[j]["title"], gazetteer=gaz))
            rel.append({"a": i, "b": j, "relation": x.relation, "diff": list(x.diff), "reason": x.reason})
    activities.append({"family": fam, "items": items, "relations": rel})
ab = json.loads((ROOT / "reports" / "models" / "activities.json").read_text(encoding="utf-8"))

# ============================================================================ 5. evidence numbers
fsq = json.loads((ROOT / "kaggle" / "fsq_pair_model" / "output" / "metrics.json").read_text())
ota = json.loads((ROOT / "reports" / "models" / "ota_matcher.json").read_text(encoding="utf-8"))
cs = json.loads((ROOT / "reports" / "eda" / "city_sources.json").read_text(encoding="utf-8"))
nb = json.loads((ROOT / "submission" / "round1" / "numbers.json").read_text(encoding="utf-8"))  # scripts/figures/round1_figures.py
evidence = {
    "fair": nb["matching"]["fair_comparison"],
    "matching": {
        "records": cm["records"], "candidates": cm["candidates"], "positives": cm["labels"]["positive"], "negatives": cm["labels"]["negative"],
        "auc": cm["pooled"]["auc"], "ap": cm["pooled"]["ap"], "recall_p99": cm["pooled"]["recall@p0.99"], "precision_r95": cm["pooled"]["precision@r0.95"],
        "blocking_recall": cm["blocking"]["recall_union"], "candidates_per_record": cm["blocking"]["candidates_per_record"],
        "per_city": {c: {k: v[k] for k in ("pos", "neg", "auc", "ap", "recall@p0.99", "rule_precision", "rule_recall")} for c, v in cm["per_city"].items()},
        "pr": {c: cm["per_city"][c]["pr"] for c in ("dubai", "bangkok", "singapore")},
        "cascade": cm["cascade"], "clusters": cm["clusters"], "label_note": "weak labels from independent keys (Wikidata QID, rare phone / URL); not hand-labelled",
    },
    "fsq": {"records": fsq["records"], "places": fsq["places"], "test_records": fsq["test"]["blocking"]["records"], "iou": fsq["test"]["cluster"]["iou"],
            "b3_f1": fsq["test"]["cluster"]["b3_f1"], "baselines": {k: v["cluster_iou"] for k, v in fsq["test"]["baselines"].items()},
            "ceiling": fsq["test"]["blocking_ceiling"]["cluster_iou"], "bands": fsq["test"]["confidence_bands"]},
    "ota": ota,
    "rooms": {"hotels": rb["benchmark"]["hotels"], "rooms": rb["benchmark"]["rooms"], "strings": rb["benchmark"]["rooms"] * len(rb["benchmark"]["styles"]),
              "methods": {k: {"coverage": v["coverage"], "precision": v["precision"]} for k, v in rb["benchmark"]["methods"].items()},
              "rate_accuracy": rb["benchmark"]["rate_extraction"]["accuracy"], "real_strings": rb["real_strings"],
              "note": "real hotel room lists; second supplier simulated by rewrite rules"},
    "activities": {"products": ab["products"], "pairs": ab["synthetic_pairs"], "accuracy": ab["accuracy"], "macro_f1": ab["macro_f1"],
                   "per_class": ab["per_class"], "dedup_merges": ab["binary_dedup_would_merge"],
                   "note": "real Klook Singapore products; second supplier simulated; score is in-sample"},
    "data": {"lodging_listings": cs["listings"]["lodging"], "attraction_listings": cs["listings"]["attraction"], "key_pairs": cs["key_pairs"]["total"],
             "hub_phone_listings": cs["hub_phones"]["largest_hub"], "cities": 12, "sources": 4},
}

DEMO = {"matching": matching, "offers": offers, "rooms": rooms, "activities": activities, "evidence": evidence, "sources": SRC_LABEL}
out = ROOT / "submission" / "round1" / "demo" / "data.js"
out.parent.mkdir(exist_ok=True)
out.write_text("window.DEMO = " + json.dumps(DEMO, ensure_ascii=False, separators=(",", ":")) + ";\n", encoding="utf-8")
print(f"wrote {out} ({out.stat().st_size / 1e3:.0f} kB): {len(clusters)} clusters, {len(listing)} listing cards, {len(rooms)} hotels, "
      f"{len(activities)} activity families, {len(review)} review pairs")
print("listing cards:", [(c["name"], len(c["offers"])) for c in listing])
print("activity families:", [(a["family"], len(a["items"]), [r["relation"] for r in a["relations"]]) for a in activities])
print("rooms:", [(r["hotel"], sum(1 for b in r["b"] if b["mapped"] == b["true"]), len(r["b"])) for r in rooms])
