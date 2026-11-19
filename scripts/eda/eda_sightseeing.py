"""EDA: sightseeing / activity data — the thinnest part of the public data landscape.

Sources
  * Klook activity crawl (Singapore + Malaysia, 2019) from Hugging Face `malaysia-ai/crawl-klook`: products with package options.
  * Viator tracker sample (Kaggle, Nov 2026): 192 product summaries in 8 cities.
  * Wikivoyage see / do listings and the attraction rows of data/interim/listings.parquet (POI layer).
Output: reports/eda/sightseeing.md + figures + sightseeing.json, data/interim/klook_products.parquet, klook_options.parquet
Usage : python -I scripts/eda/eda_sightseeing.py
"""
import json
import re
import sys
from collections import Counter
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import INTERIM, RAW, SERIES, Report, barh, connect, fig_for_bars, plt  # noqa: E402

r = Report("sightseeing", "EDA — sightseeing products and attractions (Klook, Viator sample, Wikivoyage, open POIs)")
con = connect()

# ---------------------------------------------------------------- load Klook
prods, opts = [], []
for f in ("full-singapore-klook.json", "full-malaysia-klook.json"):
    for d in json.load(open(RAW / "klook_hf_malaysia_ai" / f, encoding="utf-8")):
        fd = d.get("full-description") or {}
        lat = lon = None
        m = re.match(r"\s*(-?\d+\.\d+)\s*,\s*(-?\d+\.\d+)", fd.get("address") or "")
        if m:
            lat, lon = float(m.group(1)), float(m.group(2))
        prods.append({"id": d["id"], "title": d.get("title"), "city": d.get("city_name"), "country": fd.get("country_name"),
                      "price": float(d.get("sell_price") or 0) or None, "market_price": float(d.get("market_price") or 0) or None,
                      "currency": d.get("currency"), "booked": d.get("participate"), "score": d.get("score") or None,
                      "reviews": d.get("review_total") or None, "lat": lat, "lon": lon, "address": fd.get("address_desc") or None,
                      "place_id": fd.get("place_id") or None, "policy": (fd.get("policy") or "").strip() or None,
                      "summary": fd.get("summary") or None, "has_detail": bool(fd)})
        for g in fd.get("spec") or []:
            for a in g.get("attr") or []:
                opts.append({"product_id": d["id"], "group": g.get("name"), "option": a.get("name")})
P, O = pd.DataFrame(prods).drop_duplicates("id"), pd.DataFrame(opts)
INTERIM.mkdir(parents=True, exist_ok=True)
P.to_parquet(INTERIM / "klook_products.parquet"); O.to_parquet(INTERIM / "klook_options.parquet")

r.p("Public data for *products* (tickets, tours, options, inclusions) is scarce: the large marketplaces expose it only through partner APIs. "
    "What could be downloaded without an agreement is small, so this report is as much a gap analysis as an EDA. "
    "The Klook crawl has no stated licence and the Viator sample is marked 'other': both are for research and schema design only.")

# ---------------------------------------------------------------- 1. inventory of what exists
r.h("1. What we have")
L = (INTERIM / "listings.parquet")
poi = {}
if L.exists():
    poi = dict(con.execute(f"SELECT source, count(*) FROM read_parquet('{L.as_posix()}') WHERE kind = 'attraction' GROUP BY 1").fetchall())
V = pd.read_csv(RAW / "viator_sample" / "viator_tours_tracker.csv")
r.table(["Layer", "Source", "Rows", "What it carries"], [
    ["product + option", "Klook crawl (SG, MY; 2019)", f"{len(P)} products, {len(O)} options",
     "title, price, bookings, coordinates, cancellation policy text, package options"],
    ["product", "Viator tracker sample (8 cities; 2026)", f"{len(V)} products", "title, duration, price, rating, free-cancellation flag; no inclusions or options"],
    ["attraction (POI)", "Overture", f"{poi.get('overture', 0):,}", "name, category, coordinates, phone, website"],
    ["attraction (POI)", "OpenStreetMap", f"{poi.get('osm', 0):,}", "name (multilingual), coordinates, Wikidata QID on some"],
    ["attraction (POI)", "Wikidata", f"{poi.get('wikidata', 0):,}", "QID, labels, class, website"],
    ["attraction (POI)", "Wikivoyage see / do", f"{poi.get('wikivoyage', 0):,}", "name, prose description, price and hours text, coordinates, QID on some"],
], align=["---", "---", "---:", "---"])
r.stat("rows", {"klook_products": len(P), "klook_options": len(O), "viator_products": len(V), "attraction_pois": poi})

# ---------------------------------------------------------------- 2. Klook products
r.h("2. Klook products")
bycity = P.groupby("city").agg(products=("id", "size"), with_coords=("lat", "count"), with_place_id=("place_id", "count"),
                               median_price=("price", "median")).sort_values("products", ascending=False)
r.table(["City", "Products", "With coordinates", "With Google place ID", "Median price (MYR)"],
        [[c, int(x.products), int(x.with_coords), int(x.with_place_id), float(x.median_price)] for c, x in bycity.iterrows()])
r.stat("klook", {"products": len(P), "with_coords": int(P["lat"].notna().sum()), "with_place_id": int(P["place_id"].notna().sum()),
                 "with_policy": int(P["policy"].notna().sum())})

# title markers: bracket tags and combo wording
tags = Counter(t.strip().lower() for title in P["title"].dropna() for t in re.findall(r"\[([^\]]+)\]", title))
combo = P["title"].str.contains(r"(?i)\bcombo\b|\bpackage\b|\+| and | & |\bbundle\b|\bpass\b", regex=True)
kinds = {
    "admission / ticket": r"(?i)ticket|admission|entry|entrance",
    "pass / multi-attraction": r"(?i)\bpass\b|\bcombo\b|bundle",
    "tour / day trip": r"(?i)\btour\b|day trip|excursion|walking|sightseeing",
    "transfer / transport": r"(?i)transfer|shuttle|airport|\bbus\b|train|ferry|cable car|car rental|charter",
    "cruise / boat": r"(?i)cruise|boat|yacht",
    "food / dining": r"(?i)buffet|dinner|lunch|dining|restaurant|afternoon tea|ice cream",
    "show / event": r"(?i)\bshow\b|concert|performance|festival|wonderland",
    "skip-the-line / express": r"(?i)skip|express|fast track|direct entry|priority",
}
kc = {k: int(P["title"].str.contains(v, regex=True).sum()) for k, v in kinds.items()}
r.p(f"Titles carry marketing tags in brackets ({sum(tags.values())} tags on {len(P)} products; most common: "
    + ", ".join(f"`{t}` ({c})" for t, c in tags.most_common(6)) + "), which must be stripped before matching and kept as attributes "
    "(for example *skip the line* is an access type, *sale* is not a product attribute at all).")
r.table(["Experience type (keyword in title)", "Products"], sorted(kc.items(), key=lambda x: -x[1]))
fig, ax = fig_for_bars(len(kc))
ks = sorted(kc.items(), key=lambda x: -x[1])
barh(ax, [k for k, _ in ks], [v for _, v in ks], xlabel="products (a title can match several types)", title="Klook products by experience type")
r.fig(fig, "klook_types", "Entry tickets dominate; a sizeable share are passes or combos, the INCLUDES case of the product graph.")
r.stat("klook_types", kc); r.stat("klook_combo_like_share", float(combo.mean()))

# ---------------------------------------------------------------- 3. options
r.h("3. Options: the level where products really differ")
per = O.groupby("product_id").size()
dist = Counter(min(int(x), 6) for x in per)
r.p(f"{len(per)} products expose {len(O)} package options: median {int(per.median())}, max {int(per.max())}. "
    f"{(per > 1).mean():.0%} of products have more than one option.")
r.table(["Options per product", "Products"], [[("6+" if k == 6 else str(k)), dist[k]] for k in sorted(dist)])
OPT = {
    "age band (adult / child / senior)": r"(?i)adult|child|kid|senior|infant|student|youth",
    "combo wording (+ / and / with / combo)": r"(?i)\+| and | & | with |combo|bundle",
    "meal included": r"(?i)lunch|dinner|buffet|meal|breakfast|tea|food|drink|ice cream|voucher",
    "transfer / pickup": r"(?i)transfer|pick ?up|drop ?off|shuttle|hotel|round trip|one way|return",
    "access type (express / skip / priority)": r"(?i)express|skip|fast|priority|vip|unlimited",
    "time / date window": r"(?i)am\b|pm\b|morning|afternoon|evening|night|sunset|weekday|weekend|peak|valid|\d{1,2} ?(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)",
    "duration": r"(?i)\bhours?\b|\bhrs?\b|\bday\b|\bmins?\b|minutes",
    "group type (private / shared)": r"(?i)private|shared|join|group",
    "resident / nationality pricing": r"(?i)mykad|malaysian|local|resident|foreigner|non-",
    "promotion wording": r"(?i)sale|promo|discount|early bird|special|exclusive|offer|free",
}
oc = {k: float(O["option"].str.contains(v, regex=True).mean()) for k, v in OPT.items()}
r.table(["Attribute signalled in the option name", "Share of options"], [[k, f"{v:.1%}"] for k, v in sorted(oc.items(), key=lambda x: -x[1])])
fig, ax = fig_for_bars(len(oc))
os_ = sorted(oc.items(), key=lambda x: -x[1])
barh(ax, [k for k, _ in os_], [v * 100 for _, v in os_], value_fmt="{:.0f}%", xlabel="% of option names", title="What distinguishes one option from another")
r.fig(fig, "option_attributes", "Option names encode exactly the differences the statement lists: inclusions, access type, time windows, who the ticket is for.")
r.stat("option_attribute_share", oc)
multi = per[per >= 3].index[:4]
ex = [[P.set_index("id").loc[pid, "title"], " · ".join(O[O["product_id"] == pid]["option"].head(5))] for pid in multi]
r.p("Examples of one product with several options (each option is a `VARIANT_OF` its siblings):")
r.table(["Product", "Options"], ex, align=["---", "---"])

# ---------------------------------------------------------------- 4. cancellation policy
r.h("4. Cancellation policy text")
pol = P["policy"].dropna()


def pol_class(t: str) -> str:
    s = t.lower()
    if re.search(r"no cancel+ations?|non[- ]refundable|no refunds?", s) and not re.search(r"full refund", s):
        return "non-refundable"
    m = re.search(r"at least (\d+) (hours?|days?)", s)
    if m:
        hrs = int(m.group(1)) * (24 if m.group(2).startswith("day") else 1)
        return "free cancellation, cutoff <= 24 h" if hrs <= 24 else "free cancellation, cutoff 25-72 h" if hrs <= 72 else "free cancellation, cutoff > 72 h"
    if re.search(r"prior to redemption|before redemption|unused", s):
        return "refundable until used"
    if re.search(r"full refund", s):
        return "free cancellation, other wording"
    return "other / unparsed"


pc = Counter(pol_class(t) for t in pol)
first_lines = pol.str.split("\n").str[0].str.strip()
r.p(f"{len(pol)} products have a policy; their first lines come in **{first_lines.nunique()} distinct wordings** "
    f"(four spellings of the same 'no cancellations' sentence alone), which a small parser maps to {len(pc)} classes:")
r.table(["Policy class", "Products", "Share"], [[k, v, f"{v / len(pol):.1%}"] for k, v in pc.most_common()])
fig, ax = fig_for_bars(len(pc))
barh(ax, [k for k, _ in pc.most_common()], [v for _, v in pc.most_common()], xlabel="products", title="Klook cancellation policies after normalisation")
r.fig(fig, "policy_classes", "Free text collapses into a handful of comparable classes with a cutoff in hours: the shape the canonical schema stores.")
r.stat("policy_classes", dict(pc)); r.stat("policy_distinct_first_lines", int(first_lines.nunique()))

# ---------------------------------------------------------------- 5. product families around one attraction
r.h("5. Products cluster around attractions (families)")
Pg = P.dropna(subset=["lat"]).copy()
Pg["cell"] = (Pg["lat"].round(3)).astype(str) + "," + (Pg["lon"].round(3)).astype(str)
fam = Pg.groupby("cell").agg(n=("id", "size"), titles=("title", lambda x: " · ".join(list(x)[:4])), city=("city", "first")).sort_values("n", ascending=False)
r.p(f"Grouping the {len(Pg)} geocoded products by a ~100 m cell gives {len(fam)} locations; {(fam['n'] > 1).sum()} of them host more than one "
    f"product and those hold {int(fam.loc[fam['n'] > 1, 'n'].sum())} products ({fam.loc[fam['n'] > 1, 'n'].sum() / len(Pg):.0%}). "
    "Inside one supplier these are siblings; across suppliers the same structure repeats, which is where `SAME_AS`, `VARIANT_OF` and `INCLUDES` are decided.")
r.table(["City", "Products at one location", "Titles (first four)"], [[x.city, int(x.n), x.titles] for _, x in fam.head(8).iterrows()], align=["---", "---:", "---"])
r.stat("klook_families", {"locations": len(fam), "multi_product_locations": int((fam["n"] > 1).sum())})
if L.exists():
    con.register("pg", Pg[["id", "title", "city", "lat", "lon"]])
    anch = con.execute(f"""
        WITH a AS (SELECT * FROM read_parquet('{L.as_posix()}') WHERE kind = 'attraction' AND city = 'singapore' AND lat IS NOT NULL)
        SELECT count(DISTINCT p.id) FILTER (a.src_id IS NOT NULL), count(DISTINCT p.id)
        FROM pg p LEFT JOIN a ON abs(a.lat - p.lat) < 0.002 AND abs(a.lon - p.lon) < 0.002 WHERE p.city = 'Singapore'""").fetchone()
    r.p(f"Anchoring check: **{anch[0]} of {anch[1]}** geocoded Klook Singapore products have at least one open-data attraction listing "
        "within about 200 m, so linking products to canonical attractions by geography is feasible before any text is read.")
    r.stat("klook_sg_anchored", {"anchored": anch[0], "geocoded": anch[1]})

# ---------------------------------------------------------------- 6. Viator sample
r.h("6. Viator tracker sample")
vc = V.groupby("destinationName").agg(n=("productCode", "size"), price=("priceFrom", "median"), dur=("durationMinutes", "median"),
                                     free=("freeCancellation", "mean"), private=("privateTour", "mean")).sort_values("n", ascending=False)
r.table(["Destination", "Products", "Median price (USD)", "Median duration (min)", "Free cancellation", "Private tour"],
        [[c, int(x.n), float(x.price), float(x.dur) if pd.notna(x.dur) else None, f"{x.free:.0%}", f"{x.private:.0%}"] for c, x in vc.iterrows()])
r.p(f"{len(V)} products in {V['destinationName'].nunique()} cities, none of them a core TBO destination in this pull, and no inclusion or option fields. "
    "Useful only to confirm field names of Viator's listing summaries. **Viator's free Basic Access API is the real source and needs a sign-up.**")
r.stat("viator", {"products": len(V), "cities": int(V["destinationName"].nunique()), "free_cancellation_share": float(V["freeCancellation"].mean())})

# ---------------------------------------------------------------- 7. gap and plan
r.h("7. The gap, and how the build closes it")
r.bullets([
    "**POI layer is solved with open data.** Tens of thousands of attraction listings across four sources, with QIDs as cross-source keys.",
    f"**Product layer is thin.** {len(P)} Klook products with {len(O)} options and {len(V)} Viator summaries; no city has the same attraction "
    "sold by two public sources at product depth.",
    "**Next data actions (need a person):** Viator Basic Access sign-up for Dubai, Bangkok and Singapore; ask the organisers for a TBO sightseeing sandbox.",
    "**Until then:** build the option-attribute extractor and the policy parser on the Klook strings, and generate supplier variants of real "
    "products (rename, add pickup, add meal, change cutoff, bundle two attractions) with known relation labels. Report those numbers as "
    "synthetic-supplier results, never as real cross-supplier accuracy.",
])
r.write()
