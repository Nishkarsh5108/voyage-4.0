"""EDA: two real Indian OTA hotel feeds (MakeMyTrip and Goibibo, PromptCloud samples, 2016 crawls).

They are the closest public thing to two supplier feeds describing overlapping hotels, so this EDA
measures feed quality per supplier and estimates how many hotels the two feeds share.

Input : data/raw/makemytrip_hotels/*.csv, data/raw/goibibo_hotels/*.csv
Output: reports/eda/ota_hotels.md + figures + ota_hotels.json
Usage : python -I scripts/eda/eda_ota_hotels.py
"""
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import INK2, RAW, SERIES, Report, barh, connect, fig_for_bars, plt  # noqa: E402

r = Report("ota_hotels", "EDA — MakeMyTrip and Goibibo hotel feeds (two real suppliers, India)")
con = connect()
one = lambda sql: con.execute(sql).fetchone()  # noqa: E731
rows = lambda sql: con.execute(sql).fetchall()  # noqa: E731
con.execute("""CREATE MACRO hav(lat1, lon1, lat2, lon2) AS
    2 * 6371000 * asin(sqrt(pow(sin(radians(lat2 - lat1) / 2), 2)
        + cos(radians(lat1)) * cos(radians(lat2)) * pow(sin(radians(lon2 - lon1) / 2), 2)))""")
con.execute(r"""CREATE MACRO norm_name(s) AS trim(regexp_replace(regexp_replace(lower(s), '[^a-z0-9 ]', ' ', 'g'), '\s+', ' ', 'g'))""")
con.execute(r"""CREATE MACRO norm_city(s) AS regexp_replace(lower(s), '[^a-z]', '', 'g')""")
IN_INDIA = "lat BETWEEN 6 AND 37.5 AND lon BETWEEN 68 AND 97.5"

mmt_csv = (RAW / "makemytrip_hotels" / "makemytrip_com-travel_sample.csv").as_posix()
gob_csv = (RAW / "goibibo_hotels" / "goibibo_com-travel_sample.csv").as_posix()
con.execute(f"""CREATE TEMP TABLE mmt_raw AS SELECT * FROM read_csv_auto('{mmt_csv}', sample_size=-1, ignore_errors=true)""")
con.execute(f"""CREATE TEMP TABLE gob_raw AS SELECT * FROM read_csv_auto('{gob_csv}', sample_size=-1, ignore_errors=true)""")

# one row per property, common schema
con.execute(r"""CREATE TEMP TABLE mmt AS
    SELECT 'makemytrip' supplier, property_id::VARCHAR pid, any_value(property_name) name, any_value(property_address) address,
           any_value(city) city, any_value(state) state, any_value(latitude) lat, any_value(longitude) lon,
           try_cast(regexp_extract(any_value(hotel_star_rating), '(\d)', 1) AS INT) stars, any_value(property_type) ptype,
           any_value(hotel_overview) descr, any_value(image_urls) images, any_value(site_review_rating) rating,
           list(DISTINCT room_types) FILTER (room_types IS NOT NULL) rooms
    FROM mmt_raw WHERE property_id IS NOT NULL GROUP BY 2""")
con.execute(r"""CREATE TEMP TABLE gob AS
    SELECT 'goibibo' supplier, property_id::VARCHAR pid, any_value(property_name) name, any_value(address) address,
           any_value(city) city, any_value(state) state, any_value(latitude) lat, any_value(longitude) lon,
           any_value(hotel_star_rating)::INT stars, any_value(property_type) ptype,
           any_value(hotel_description) descr, any_value(image_count)::VARCHAR images, any_value(site_review_rating) rating,
           list(DISTINCT room_type) FILTER (room_type IS NOT NULL) rooms
    FROM gob_raw WHERE property_id IS NOT NULL GROUP BY 2""")
con.execute("CREATE TEMP TABLE h AS SELECT * FROM mmt UNION ALL SELECT * FROM gob")

r.p("Source: Kaggle `PromptCloudHQ/hotels-on-makemytrip` and `PromptCloudHQ/hotels-on-goibibo` (CC BY-SA 4.0, crawled mid-2016). "
    "Both are samples, so the overlap measured here is a lower bound on what the two full catalogues share. "
    "Old data, but the feed defects are the ones the statement is about.")

# ---------------------------------------------------------------- 1. size
r.h("1. Size")
sz = rows("""SELECT supplier, count(*), count(DISTINCT norm_city(city)), count(DISTINCT state),
             sum(len(rooms))::BIGINT FROM h GROUP BY 1 ORDER BY 1 DESC""")
raw_n = {"makemytrip": one("SELECT count(*) FROM mmt_raw")[0], "goibibo": one("SELECT count(*) FROM gob_raw")[0]}
r.table(["Supplier", "Raw rows", "Properties", "Cities", "States", "Room-type strings"],
        [[s[0], raw_n[s[0]], s[1], s[2], s[3], s[4] or 0] for s in sz])
r.stat("size", {s[0]: {"rows": raw_n[s[0]], "properties": s[1], "cities": s[2]} for s in sz})
city_var = rows("""SELECT norm_city(city) k, list(DISTINCT city) v FROM h WHERE supplier = 'makemytrip' GROUP BY 1
                   HAVING count(DISTINCT city) > 1 ORDER BY count(*) DESC LIMIT 6""")
if city_var:
    r.p("City names are not normalised even inside one feed, for example: " + "; ".join(" = ".join(f"`{x}`" for x in v[1]) for v in city_var) + ".")

# ---------------------------------------------------------------- 2. completeness
r.h("2. Field completeness per supplier (property level)")
fields = {
    "name": "name IS NOT NULL AND length(trim(name)) > 0",
    "address": "address IS NOT NULL AND length(trim(address)) > 3",
    "coordinates in India": f"lat IS NOT NULL AND {IN_INDIA}",
    "star rating (1-5)": "stars BETWEEN 1 AND 5",
    "property type": "ptype IS NOT NULL",
    "description": "descr IS NOT NULL AND length(descr) > 30",
    "images": "images IS NOT NULL AND images NOT IN ('0', '')",
    "review rating": "rating IS NOT NULL AND rating > 0",
    "room type": "len(rooms) > 0",
    "state": "state IS NOT NULL",
}
comp = rows("SELECT supplier, " + ", ".join(f"avg(({e})::INT)" for e in fields.values()) + " FROM h GROUP BY 1 ORDER BY 1 DESC")
cm = {c[0]: c[1:] for c in comp}
r.table(["Field", "MakeMyTrip", "Goibibo"], [[f, f"{cm['makemytrip'][i]:.1%}", f"{cm['goibibo'][i]:.1%}"] for i, f in enumerate(fields)])
r.stat("completeness", {s: dict(zip(fields, v)) for s, v in cm.items()})
fig, ax = plt.subplots(figsize=(7.5, 0.48 * len(fields) + 1.2))
y = np.arange(len(fields))[::-1]
ax.barh(y + 0.19, [v * 100 for v in cm["makemytrip"]], height=0.34, color=SERIES[0], label="MakeMyTrip")
ax.barh(y - 0.19, [v * 100 for v in cm["goibibo"]], height=0.34, color=SERIES[1], label="Goibibo")
ax.set_yticks(y, list(fields)); ax.grid(axis="y", visible=False); ax.set_xlim(0, 100)
ax.set_xlabel("% of properties with a usable value"); ax.set_title("Two suppliers, two different sets of gaps")
ax.legend(loc="lower center", bbox_to_anchor=(0.5, 1.08), ncol=2)
r.fig(fig, "completeness", "Each feed is complete where the other is thin, which is why a golden record needs field-level survivorship.")

# ---------------------------------------------------------------- 3. coordinate quality
r.h("3. Coordinate quality")
cq = rows(f"""WITH v AS (SELECT *, {IN_INDIA} ok FROM h WHERE lat IS NOT NULL),
      d AS (SELECT supplier, lat, lon, count(*) n FROM v WHERE ok GROUP BY 1, 2, 3)
      SELECT v.supplier, count(*), avg((NOT ok)::INT),
             avg((length(regexp_extract(lat::VARCHAR, '\\.(\\d+)', 1)) <= 3)::INT) FILTER (ok),
             (SELECT sum(n) FILTER (n > 1) / sum(n) FROM d WHERE d.supplier = v.supplier),
             (SELECT max(n) FROM d WHERE d.supplier = v.supplier)
      FROM v GROUP BY 1 ORDER BY 1 DESC""")
r.table(["Supplier", "With coordinates", "Outside India / zero", "<= 3 decimals (>= ~100 m grid)", "Share on a coordinate shared with another property",
         "Most properties on one point"], [[c[0], c[1], f"{c[2]:.1%}", f"{c[3]:.1%}", f"{(c[4] or 0):.1%}", c[5]] for c in cq])
r.stat("coord_quality", {c[0]: {"outside": c[2], "low_precision": c[3], "shared_point": c[4], "max_on_point": c[5]} for c in cq})
r.p("A coordinate shared by many unrelated hotels is a locality centroid, not a location. "
    "The supplier profiler has to detect these so the matcher stops trusting distance for them.")

# ---------------------------------------------------------------- 4. stars and types
r.h("4. Star ratings and property types")
st = rows("SELECT supplier, coalesce(stars, 0) s, count(*) FROM h GROUP BY 1, 2 ORDER BY 2")
tot = {s: sum(x[2] for x in st if x[0] == s) for s in ("makemytrip", "goibibo")}
fig, ax = plt.subplots(figsize=(7.5, 3.2))
xs = np.arange(6)
for k, (s, lab) in enumerate((("makemytrip", "MakeMyTrip"), ("goibibo", "Goibibo"))):
    vals = [next((x[2] for x in st if x[0] == s and x[1] == i), 0) / tot[s] * 100 for i in range(6)]
    ax.bar(xs + (k - 0.5) * 0.36, vals, width=0.32, color=SERIES[k], label=lab)
ax.set_xticks(xs, ["unrated", "1", "2", "3", "4", "5"]); ax.grid(axis="x", visible=False)
ax.set_xlabel("star rating"); ax.set_ylabel("% of the supplier's properties"); ax.set_title("Star rating mix by supplier"); ax.legend()
r.fig(fig, "stars", "The two feeds disagree on how much of the catalogue is unrated, so a star difference is weak evidence against a match.")
r.table(["Stars", "MakeMyTrip", "Goibibo"], [["unrated" if i == 0 else str(i)] + [
    f"{next((x[2] for x in st if x[0] == s and x[1] == i), 0) / tot[s]:.1%}" for s in ("makemytrip", "goibibo")] for i in range(6)])
pt = rows("SELECT supplier, coalesce(ptype, '(null)'), count(*) c FROM h GROUP BY 1, 2 QUALIFY row_number() OVER (PARTITION BY supplier ORDER BY c DESC) <= 6 ORDER BY 1 DESC, c DESC")
r.table(["Supplier", "Property type (top 6)", "Properties"], pt)

# ---------------------------------------------------------------- 5. cross-supplier overlap
r.h("5. How many hotels do the two feeds share?")
common_city = one("""SELECT count(*) FROM (SELECT DISTINCT norm_city(city) c FROM mmt) a JOIN (SELECT DISTINCT norm_city(city) c FROM gob) b USING (c)""")[0]
r.p(f"{common_city} city names appear in both feeds after normalisation. Candidate pairs: one MakeMyTrip and one Goibibo property "
    "within about 1 km of each other (grid join on valid coordinates), scored by Jaro-Winkler on normalised names.")
con.execute(f"""CREATE TEMP TABLE cand AS
    WITH a AS (SELECT *, floor(lat * 100)::INT gy, floor(lon * 100)::INT gx, norm_name(name) nn FROM mmt WHERE {IN_INDIA}),
         b AS (SELECT *, floor(lat * 100)::INT gy, floor(lon * 100)::INT gx, norm_name(name) nn FROM gob WHERE {IN_INDIA}),
         o AS (SELECT * FROM (VALUES (-1), (0), (1)) t(dy), (VALUES (-1), (0), (1)) u(dx))
    SELECT a.pid mpid, b.pid gpid, a.name mname, b.name gname, a.city mcity, a.stars mstars, b.stars gstars,
           hav(a.lat, a.lon, b.lat, b.lon) d, jaro_winkler_similarity(a.nn, b.nn) jw, a.nn = b.nn name_eq
    FROM a JOIN o ON true JOIN b ON b.gy = a.gy + o.dy AND b.gx = a.gx + o.dx
    WHERE hav(a.lat, a.lon, b.lat, b.lon) < 1000""")
ncand, = one("SELECT count(*) FROM cand")
tiers = one("""SELECT count(*) FILTER (name_eq), count(*) FILTER (jw >= 0.92 AND NOT name_eq), count(*) FILTER (jw >= 0.85 AND jw < 0.92),
               count(DISTINCT gpid) FILTER (jw >= 0.92), count(DISTINCT mpid) FILTER (jw >= 0.92) FROM cand""")
ng, nm = one("SELECT count(*) FROM gob")[0], one("SELECT count(*) FROM mmt")[0]
r.table(["Candidate tier (within 1 km)", "Pairs"], [
    ["all candidate pairs", ncand], ["normalised names identical", tiers[0]],
    ["name JW >= 0.92, not identical (likely same hotel, different spelling)", tiers[1]],
    ["name JW 0.85-0.92 (ambiguous band, needs more evidence)", tiers[2]]])
r.p(f"At JW >= 0.92, **{tiers[3]:,} of {ng:,} Goibibo properties ({tiers[3] / ng:.1%})** have a likely MakeMyTrip twin "
    f"({tiers[4]:,} MakeMyTrip properties involved). These are unverified likely matches, to be confirmed by the matcher and a labelled sample.")
r.stat("overlap", {"candidates_1km": ncand, "name_identical": tiers[0], "jw_ge_092_not_identical": tiers[1], "jw_085_092": tiers[2],
                   "goibibo_with_likely_twin": tiers[3], "goibibo_total": ng, "mmt_total": nm})
dq = one("SELECT quantile_cont(d, 0.5), quantile_cont(d, 0.75), quantile_cont(d, 0.9), avg((d > 300)::INT), avg((mstars IS DISTINCT FROM gstars)::INT), "
         "avg((abs(mstars - gstars) >= 2)::INT) FILTER (mstars IS NOT NULL AND gstars IS NOT NULL) FROM cand WHERE jw >= 0.92")
r.p(f"For those likely-same pairs the two suppliers' coordinates differ by a median of **{dq[0]:.0f} m** (p75 {dq[1]:.0f} m, p90 {dq[2]:.0f} m; "
    f"{dq[3]:.1%} over 300 m), and the star rating differs in {dq[4]:.1%} of pairs ({(dq[5] or 0):.1%} by two or more stars where both are rated).")
r.stat("likely_pairs", {"median_dist_m": dq[0], "p90_dist_m": dq[2], "gt_300m": dq[3], "stars_differ": dq[4]})
hd = rows("SELECT floor(d / 50) * 50 b, count(*) FROM cand WHERE jw >= 0.92 GROUP BY 1 ORDER BY 1")
fig, ax = plt.subplots(figsize=(7.5, 3.2))
ax.bar([x[0] + 25 for x in hd], [x[1] for x in hd], width=44, color=SERIES[0])
ax.grid(axis="x", visible=False); ax.set_xlabel("distance between the two suppliers' coordinates (m)"); ax.set_ylabel("likely-same pairs")
ax.set_title("Same hotel, two suppliers: how far apart are the pins?")
r.fig(fig, "pair_distance", "Even for the same hotel the two feeds rarely agree on the pin; a tail runs out to the 1 km search radius.")
ex = rows("""SELECT mname, gname, round(d)::INT, round(jw, 3), mstars, gstars FROM cand
             WHERE jw >= 0.86 AND NOT name_eq QUALIFY row_number() OVER (PARTITION BY mpid ORDER BY jw DESC) = 1
             ORDER BY hash(mpid) LIMIT 14""")
r.p("A sample of pairs with JW >= 0.86 whose names are not identical (best Goibibo candidate per MakeMyTrip hotel, not hand-verified). "
    "Character similarity is inflated by generic tokens such as *Hotel*, *Residency* or a deity or locality name shared by a whole street, "
    "so this band mixes real spelling variants with different hotels. The pair model needs token-weighted name features (rare tokens count, "
    "generic ones do not), not raw string similarity:")
r.table(["MakeMyTrip name", "Goibibo name", "Dist (m)", "JW", "MMT stars", "Goibibo stars"], ex,
        align=["---", "---", "---:", "---:", "---:", "---:"])
far = one(f"""SELECT count(*) FROM (SELECT norm_name(name) nn, norm_city(city) c, lat, lon FROM mmt WHERE {IN_INDIA}) a
              JOIN (SELECT norm_name(name) nn, norm_city(city) c, lat, lon FROM gob WHERE {IN_INDIA}) b
              ON a.nn = b.nn AND a.c = b.c WHERE hav(a.lat, a.lon, b.lat, b.lon) > 2000 AND length(a.nn) > 8""")[0]
r.p(f"The opposite failure also exists: **{far:,}** pairs share an identical normalised name and city but sit more than 2 km apart "
    "(a wrong geocode at one supplier, or two branches of one brand). Geo-blocking alone would never propose these pairs; "
    "a name-based blocking key is needed alongside the geographic one.")
r.stat("same_name_city_gt_2km", far)

# ---------------------------------------------------------------- 6. duplicates inside one supplier
r.h("6. Duplicates inside one supplier")
dup = rows("""SELECT supplier, count(*) FILTER (n > 1), sum(n) FILTER (n > 1)::BIGINT FROM (
              SELECT supplier, norm_name(name) nn, norm_city(city) c, round(lat, 3) la, round(lon, 3) lo, count(*) n FROM h
              WHERE name IS NOT NULL GROUP BY ALL) GROUP BY 1 ORDER BY 1 DESC""")
r.table(["Supplier", "Name + city + ~100 m cell used by more than one property ID", "Property IDs involved"], [[d[0], d[1] or 0, d[2] or 0] for d in dup])
r.p("Supplier-internal duplicates exist before any cross-supplier matching. The clustering step should flag clusters that hold two records from one supplier.")
r.stat("internal_duplicates", {d[0]: {"groups": d[1], "ids": d[2]} for d in dup})

# ---------------------------------------------------------------- 7. room strings
r.h("7. Room-type strings")
rm = rows("""SELECT supplier, count(*), count(DISTINCT s), count(DISTINCT lower(trim(s))),
             count(DISTINCT regexp_replace(lower(s), '[^a-z0-9]', '', 'g')) FROM (SELECT supplier, unnest(rooms) s FROM h) GROUP BY 1 ORDER BY 1 DESC""")
r.table(["Supplier", "Room strings (property x room)", "Distinct raw", "Distinct after lower/trim", "Distinct after removing punctuation and spaces"], rm)
top = rows("""SELECT supplier, lower(trim(s)) k, count(*) c FROM (SELECT supplier, unnest(rooms) s FROM h) GROUP BY 1, 2
              QUALIFY row_number() OVER (PARTITION BY supplier ORDER BY c DESC) <= 12 ORDER BY 1 DESC, c DESC""")
for s, lab in (("makemytrip", "MakeMyTrip"), ("goibibo", "Goibibo")):
    t = [x for x in top if x[0] == s]
    fig, ax = fig_for_bars(len(t))
    barh(ax, [x[1] for x in t], [x[2] for x in t], color=SERIES[0 if s == "makemytrip" else 1], xlabel="properties using the string",
         title=f"{lab}: most common room-type strings")
    r.fig(fig, f"rooms_{s}", f"{lab}: a handful of generic names cover most properties; the long tail is where extraction is needed.")
r.stat("room_strings", {x[0]: {"n": x[1], "distinct_raw": x[2], "distinct_lower": x[3], "distinct_alnum": x[4]} for x in rm})
r.p("Room strings are analysed with the Booking.com room names in `rooms.md`.")
r.write()
