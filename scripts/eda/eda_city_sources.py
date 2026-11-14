"""EDA: four independent open sources as "suppliers" of hotels and attractions in 12 cities.

Input : data/interim/listings.parquet (scripts/build/build_listings.py) + data/raw/overture/*.parquet
Output: reports/eda/city_sources.md + figures + city_sources.json, and data/interim/key_pairs.parquet
        (cross-source pairs linked by a shared Wikidata QID, phone or URL: the weak labels)
Usage : python -I scripts/eda/eda_city_sources.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import INTERIM, RAW, SERIES, Report, barh, connect, plt  # noqa: E402

SOURCES = ["overture", "osm", "wikidata", "wikivoyage"]
CITY_ORDER = ["dubai", "bangkok", "singapore", "delhi", "mumbai", "goa", "london", "paris", "amsterdam", "barcelona", "vienna", "milan"]

r = Report("city_sources", "EDA — four open sources as suppliers: Overture, OpenStreetMap, Wikidata, Wikivoyage (12 cities)")
con = connect(memory="2GB")
one = lambda sql: con.execute(sql).fetchone()  # noqa: E731
rows = lambda sql: con.execute(sql).fetchall()  # noqa: E731
con.execute("""CREATE MACRO hav(lat1, lon1, lat2, lon2) AS
    2 * 6371000 * asin(sqrt(pow(sin(radians(lat2 - lat1) / 2), 2)
        + cos(radians(lat1)) * cos(radians(lat2)) * pow(sin(radians(lon2 - lon1) / 2), 2)))""")
con.execute(r"""CREATE MACRO norm_name(s) AS trim(regexp_replace(regexp_replace(lower(strip_accents(s)), '[^\p{L}\p{N} ]', ' ', 'g'), '\s+', ' ', 'g'))""")
con.execute(f"CREATE TEMP TABLE L AS SELECT *, row_number() OVER () AS rid, norm_name(name) AS nn FROM read_parquet('{(INTERIM / 'listings.parquet').as_posix()}')")

r.p("Each source was built independently, so each behaves like a supplier with its own naming, geocoding and completeness habits. "
    "Overture Places (CDLA-Permissive-2.0, release 2026-10-21) blends Meta, Microsoft, Foursquare and smaller feeds; OpenStreetMap (ODbL) is "
    "crowd-mapped; Wikidata (CC0) is an encyclopaedic graph; Wikivoyage (CC BY-SA) is traveller-written prose listings. "
    "All four are commercially usable. The table `data/interim/listings.parquet` holds them in one canonical schema.")

# ---------------------------------------------------------------- 1. volume
r.h("1. Volume per city and source")
vol = rows("SELECT city, source, kind, count(*) FROM L GROUP BY ALL")
v = {(c, s, k): n for c, s, k, n in vol}
for kind in ("lodging", "attraction"):
    r.p(f"**{kind.capitalize()} listings**")
    r.table(["City"] + SOURCES + ["Total"], [[c] + [v.get((c, s, kind), 0) for s in SOURCES] + [sum(v.get((c, s, kind), 0) for s in SOURCES)]
                                            for c in CITY_ORDER])
tot = {k: sum(n for (c, s, kk), n in v.items() if kk == k) for k in ("lodging", "attraction")}
r.stat("listings", {"lodging": tot["lodging"], "attraction": tot["attraction"],
                    "by_source": {s: sum(n for (c, ss, k), n in v.items() if ss == s) for s in SOURCES}})
fig, axes = plt.subplots(2, 2, figsize=(10.5, 8.2))
for ax, s in zip(axes.ravel(), SOURCES):
    barh(ax, CITY_ORDER, [v.get((c, s, "lodging"), 0) for c in CITY_ORDER], xlabel="lodging listings", title=s)
fig.suptitle("Lodging listings per city, one panel per source (scales differ)", x=0.02, ha="left", fontsize=13, fontweight="bold")
fig.tight_layout(rect=(0, 0, 1, 0.96))
r.fig(fig, "lodging_by_source", "The sources differ by two orders of magnitude in coverage: Overture lists thousands of lodgings per city, Wikidata and Wikivoyage dozens.")
r.p(f"Total: **{tot['lodging']:,} lodging** and **{tot['attraction']:,} attraction** listings across the four sources.")

# ---------------------------------------------------------------- 2. Overture is itself multi-provider
r.h("2. Overture is already a blend of providers")
prov = rows("SELECT provider, count(*) FILTER (kind = 'lodging'), count(*) FILTER (kind = 'attraction') FROM L WHERE source = 'overture' GROUP BY 1 ORDER BY 2 DESC")
ol = sum(p[1] for p in prov)
r.table(["Provider behind the Overture record", "Lodging", "Share of lodging", "Attractions"], [[p[0], p[1], f"{p[1] / ol:.1%}", p[2]] for p in prov])
r.stat("overture_provider_lodging_share", {p[0]: p[1] / ol for p in prov})
r.p("Overture conflates its providers before release, so it counts as one supplier here, with the provider kept as an attribute. "
    "Its Foursquare share also makes the separate (now gated) Foursquare OS Places download optional.")
conf = one("""SELECT quantile_cont(confidence, 0.1), quantile_cont(confidence, 0.5), avg((confidence < 0.5)::INT) FROM L WHERE source = 'overture'""")
r.p(f"Overture's own existence confidence: p10 {conf[0]:.2f}, median {conf[1]:.2f}; {conf[2]:.1%} of its travel listings score below 0.5 "
    "(possibly closed or spurious). That score is a ready-made supplier-quality feature.")
r.stat("overture_confidence", {"p10": conf[0], "median": conf[1], "below_0.5": conf[2]})

# ---------------------------------------------------------------- 3. completeness
r.h("3. Field completeness by source (lodging)")
fields = {
    "alternate / local names": "len(alt_names) > 0", "coordinates": "lat IS NOT NULL", "street address": "street IS NOT NULL AND length(street) > 2",
    "postcode": "postcode IS NOT NULL", "phone": "phone8 IS NOT NULL", "website": "domain IS NOT NULL", "Wikidata QID": "qid IS NOT NULL",
    "brand / operator": "brand IS NOT NULL", "star rating": "stars IS NOT NULL",
}
comp = rows("SELECT source, count(*), " + ", ".join(f"avg(({e})::INT)" for e in fields.values()) + " FROM L WHERE kind = 'lodging' GROUP BY 1")
cm = {c[0]: c[2:] for c in comp}
r.table(["Field"] + SOURCES, [[f] + [f"{cm[s][i]:.1%}" for s in SOURCES] for i, f in enumerate(fields)])
r.stat("completeness_lodging", {s: dict(zip(fields, cm[s])) for s in SOURCES})
fig, axes = plt.subplots(1, 4, figsize=(12.5, 3.9), sharey=True)
for ax, s in zip(axes, SOURCES):
    barh(ax, list(fields), [x * 100 for x in cm[s]], value_fmt="{:.0f}%", title=s)
    ax.set_xlim(0, 125); ax.set_xticks([0, 50, 100])
fig.suptitle("Lodging field completeness, one panel per source", x=0.02, ha="left", fontsize=13, fontweight="bold")
fig.tight_layout(rect=(0, 0, 1, 0.93))
r.fig(fig, "completeness", "No source is complete: Overture has phones and websites but no IDs or stars; OSM has addresses and some QIDs; Wikidata has QIDs and little else.")

# ---------------------------------------------------------------- 4. coordinate quality
r.h("4. Coordinate quality by source")
cq = rows("""WITH x AS (SELECT *, length(regexp_extract(lat::VARCHAR, '\\.(\\d+)', 1)) dec FROM L WHERE lat IS NOT NULL),
      d AS (SELECT source, city, lat, lon, count(*) n FROM x GROUP BY ALL)
      SELECT x.source, count(*), avg((NOT in_bbox)::INT), avg((dec <= 3)::INT), avg((dec = 4)::INT), avg((dec >= 5)::INT),
             (SELECT sum(n) FILTER (n > 1) / sum(n) FROM d WHERE d.source = x.source), (SELECT max(n) FROM d WHERE d.source = x.source)
      FROM x GROUP BY 1""")
cqm = {c[0]: c for c in cq}
r.table(["Source", "With coordinates", "Outside the city bbox", "<= 3 decimals (~100 m)", "4 decimals (~10 m)", ">= 5 decimals (~1 m)",
         "On a point shared with another listing", "Most listings on one point"],
        [[s, cqm[s][1], f"{cqm[s][2]:.1%}", f"{cqm[s][3]:.1%}", f"{cqm[s][4]:.1%}", f"{cqm[s][5]:.1%}", f"{(cqm[s][6] or 0):.1%}", cqm[s][7]] for s in SOURCES])
r.stat("coord_quality", {s: {"outside_bbox": cqm[s][2], "le3_decimals": cqm[s][3], "shared_point": cqm[s][6], "max_on_point": cqm[s][7]} for s in SOURCES})
r.p("Decimal places and shared points are the two cheap signals the supplier profiler needs: they say how far a source's distance evidence can be trusted.")

# ---------------------------------------------------------------- 5. scripts
r.h("5. Scripts and languages in names")
sc = rows(r"""SELECT city, avg(regexp_matches(name, '[^\x00-\x7F]')::INT), avg(regexp_matches(name, '\p{Arabic}')::INT),
              avg(regexp_matches(name, '\p{Thai}')::INT), avg(regexp_matches(name, '\p{Han}')::INT), avg(regexp_matches(name, '\p{Devanagari}')::INT),
              avg((len(alt_names) > 0)::INT) FROM L GROUP BY 1""")
scm = {s[0]: s for s in sc}
r.table(["City", "Non-ASCII primary name", "Arabic", "Thai", "Han", "Devanagari", "Has an alternate-language name"],
        [[c] + [f"{x:.1%}" for x in scm[c][1:]] for c in CITY_ORDER])
r.stat("non_ascii_name_share", {c: scm[c][1] for c in CITY_ORDER})
r.p("Bangkok is the stress test: a large share of primary names are in Thai script in one source and romanised in another, "
    "so character similarity is zero for a true match unless alternate names or transliteration are used.")

# ---------------------------------------------------------------- 6. weak-label keys
r.h("6. Keys that link the same entity across sources (weak labels)")
keys = rows("""SELECT source, count(*), count(qid), count(phone8), count(url_key) FROM L WHERE lat IS NOT NULL AND in_bbox GROUP BY 1""")
km = {k[0]: k for k in keys}
r.table(["Source", "Listings (in bbox)", "With Wikidata QID", "With phone", "With website"], [[s] + list(km[s][1:]) for s in SOURCES])
con.execute("""CREATE TEMP TABLE G AS SELECT * FROM L WHERE lat IS NOT NULL AND in_bbox""")
con.execute("""CREATE TEMP TABLE dom AS SELECT city, domain, count(*) n FROM G WHERE domain IS NOT NULL GROUP BY ALL""")
con.execute("""CREATE TEMP TABLE kp AS
    WITH q AS (SELECT a.rid ra, b.rid rb, 'qid' k FROM G a JOIN G b ON a.city = b.city AND a.qid = b.qid AND a.source < b.source),
         p AS (SELECT a.rid ra, b.rid rb, 'phone' k FROM G a JOIN G b ON a.city = b.city AND a.phone8 = b.phone8 AND a.source < b.source),
         u AS (SELECT a.rid ra, b.rid rb, 'url' k FROM G a JOIN G b ON a.city = b.city AND a.url_key = b.url_key AND a.source < b.source
               JOIN dom ON dom.city = a.city AND dom.domain = a.domain
               WHERE position('/' IN a.url_key) > 0 OR dom.n <= 4)
    SELECT ra, rb, list_sort(list(DISTINCT k)) ks FROM (SELECT * FROM q UNION ALL SELECT * FROM p UNION ALL SELECT * FROM u) GROUP BY 1, 2""")
con.execute(f"""CREATE TEMP TABLE kpf AS
    SELECT kp.*, a.city, a.source sa, b.source sb, a.kind ka, b.kind kb, a.name na, b.name nb, a.src_id ida, b.src_id idb,
           hav(a.lat, a.lon, b.lat, b.lon) d, jaro_winkler_similarity(a.nn, b.nn) jw,
           greatest(jaro_winkler_similarity(a.nn, b.nn),
                    coalesce(list_max(list_transform(b.alt_names, lambda x: jaro_winkler_similarity(a.nn, norm_name(x)))), 0),
                    coalesce(list_max(list_transform(a.alt_names, lambda x: jaro_winkler_similarity(norm_name(x), b.nn))), 0)) jw_alt,
           (a.qid IS NOT NULL AND b.qid IS NOT NULL AND a.qid <> b.qid) qid_conflict
    FROM kp JOIN G a ON a.rid = kp.ra JOIN G b ON b.rid = kp.rb""")
con.execute(f"COPY kpf TO '{(INTERIM / 'key_pairs.parquet').as_posix()}' (FORMAT parquet)")
nk, = one("SELECT count(*) FROM kpf")
bykey = rows("SELECT array_to_string(ks, '+'), count(*) FROM kpf GROUP BY 1 ORDER BY 2 DESC")
r.p(f"Joining listings of *different* sources in the same city on an identical QID, phone (last 8 digits) or URL gives **{nk:,} key-linked pairs**. "
    "URLs count only when they carry a path or the domain is rare in the city, so a chain's home page does not link all its hotels.")
r.table(["Linking key(s)", "Pairs"], bykey)
bysrc = rows("SELECT sa || ' x ' || sb, count(*), count(*) FILTER (list_contains(ks, 'qid')), count(*) FILTER (list_contains(ks, 'phone')), "
             "count(*) FILTER (list_contains(ks, 'url')) FROM kpf GROUP BY 1 ORDER BY 2 DESC")
r.table(["Source pair", "Pairs", "via QID", "via phone", "via URL"], bysrc)
bycity = rows("SELECT city, count(*), count(*) FILTER (ka = 'lodging' AND kb = 'lodging') FROM kpf GROUP BY 1")
bc = {c[0]: c for c in bycity}
r.table(["City", "Key-linked pairs", "of which lodging-lodging"], [[c, bc.get(c, (c, 0, 0))[1], bc.get(c, (c, 0, 0))[2]] for c in CITY_ORDER])
r.stat("key_pairs", {"total": nk, "by_key": dict(bykey), "by_city": {c: bc.get(c, (c, 0, 0))[1] for c in CITY_ORDER}})

r.h("Not every shared key is evidence: hub phones", 3)
hub = one("""SELECT count(*) FILTER (c > 5), sum(c) FILTER (c > 5)::BIGINT, max(c), arg_max(city, c), arg_max(phone_raw, c) FROM (
             SELECT city, phone8, count(*) c, any_value(phone_raw) phone_raw FROM L WHERE phone8 IS NOT NULL GROUP BY 1, 2)""")
bk = rows("""SELECT array_to_string(ks, '+'), count(*), avg((d < 100)::INT), avg((d < 500)::INT), avg((d > 2000)::INT), avg((jw_alt >= 0.85)::INT)
             FROM kpf GROUP BY 1 ORDER BY 2 DESC""")
r.p(f"**{hub[0]:,} phone numbers are each attached to more than five listings** in one city, {hub[1]:,} listings in total. "
    f"The largest hub, in {hub[3]}, is one number on {hub[2]:,} listings: a chain's reservation call centre, not a hotel's front desk. "
    "A key that many listings share carries almost no evidence, so key strength has to be weighted by how rare the value is.")
r.table(["Linking key(s)", "Pairs", "Within 100 m", "Within 500 m", "Over 2 km", "Name JW >= 0.85 (incl. alternate names)"],
        [[b[0], b[1], f"{b[2]:.1%}", f"{b[3]:.1%}", f"{b[4]:.1%}", f"{b[5]:.1%}"] for b in bk])
r.stat("hub_phones", {"phones_over_5_listings": hub[0], "listings_on_hub_phones": hub[1], "largest_hub": hub[2], "largest_hub_city": hub[3]})
r.stat("key_quality", {b[0]: {"pairs": b[1], "within_500m": b[3], "over_2km": b[4]} for b in bk})
r.p("A shared QID is clean (almost every pair within 500 m). A shared phone alone is not: under half of those pairs are within 500 m. "
    "Two independent keys agreeing is nearly as clean as a QID.")

r.h("How hard are these real cross-source duplicates?", 3)
hd = one("""SELECT quantile_cont(d, 0.5), quantile_cont(d, 0.9), quantile_cont(d, 0.99), avg((d > 300)::INT), avg((d > 2000)::INT),
            quantile_cont(jw, 0.5), avg((jw < 0.8)::INT), avg((jw_alt < 0.8)::INT), avg((na = nb)::INT), avg(qid_conflict::INT) FROM kpf""")
r.table(["Median distance", "p90", "p99", "> 300 m", "> 2 km", "Median name JW", "Name JW < 0.8", "JW < 0.8 even with alternate names", "Names identical", "QIDs conflict"],
        [[f"{hd[0]:.0f} m", f"{hd[1]:.0f} m", f"{hd[2]:,.0f} m", f"{hd[3]:.1%}", f"{hd[4]:.1%}", f"{hd[5]:.3f}", f"{hd[6]:.1%}", f"{hd[7]:.1%}",
          f"{hd[8]:.1%}", f"{hd[9]:.1%}"]], align=["---:"] * 10)
r.stat("key_pair_difficulty", {"median_dist_m": hd[0], "p90_dist_m": hd[1], "gt_300m": hd[3], "gt_2km": hd[4], "median_jw": hd[5],
                               "jw_lt_0.8": hd[6], "jw_alt_lt_0.8": hd[7], "names_identical": hd[8], "qid_conflict": hd[9]})
r.p(f"A shared phone or URL is not proof ({hd[4]:.1%} of key-linked pairs are more than 2 km apart, and {hd[9]:.1%} carry two different QIDs: "
    "call centres, chains, a museum and the park around it). Weak labels therefore use the key **plus** a sanity condition, and the QID conflicts "
    "become trusted negatives.")
fig, axes = plt.subplots(1, 2, figsize=(11, 3.4))
h1 = rows("SELECT floor(log10(greatest(d, 1)) * 4) / 4 b, count(*) FROM kpf GROUP BY 1 ORDER BY 1")
axes[0].plot([10 ** x[0] for x in h1], [x[1] for x in h1], color=SERIES[0]); axes[0].set_xscale("log")
axes[0].set_xlabel("distance between the two sources' coordinates (m, log)"); axes[0].set_ylabel("key-linked pairs"); axes[0].set_title("Same entity, two sources: distance")
h2 = rows("SELECT floor(jw * 20) / 20 b, count(*) FROM kpf GROUP BY 1 ORDER BY 1")
axes[1].bar([x[0] + 0.025 for x in h2], [x[1] for x in h2], width=0.044, color=SERIES[0]); axes[1].grid(axis="x", visible=False)
axes[1].set_xlabel("Jaro-Winkler similarity of primary names"); axes[1].set_title("Same entity, two sources: name similarity")
fig.tight_layout()
r.fig(fig, "key_pair_difficulty", "Real cross-source duplicates: most sit within tens of metres, but a tail runs to kilometres, and a visible share have dissimilar primary names.")
ex = rows("""SELECT city, sa || ' / ' || sb, na, nb, round(d)::INT, round(jw, 2), array_to_string(ks, '+') FROM kpf
             WHERE jw < 0.75 AND d < 300 AND NOT qid_conflict ORDER BY hash(ra + rb) LIMIT 14""")
r.p("Key-linked pairs within 300 m whose primary names disagree (the cases that defeat string matching):")
r.table(["City", "Sources", "Name A", "Name B", "Dist (m)", "JW", "Key"], ex, align=["---", "---", "---", "---", "---:", "---:", "---"])

# ---------------------------------------------------------------- 7. overlap estimate, lodging
r.h("7. How much do the sources overlap? (lodging, OSM against Overture)")
con.execute("""CREATE TEMP TABLE ov AS
    WITH a AS (SELECT rid, city, nn, lat, lon, floor(lat * 200)::INT gy, floor(lon * 200)::INT gx FROM G WHERE source = 'osm' AND kind = 'lodging'),
         b AS (SELECT rid, city, nn, lat, lon, floor(lat * 200)::INT gy, floor(lon * 200)::INT gx FROM G WHERE source = 'overture' AND kind = 'lodging'),
         o AS (SELECT * FROM (VALUES (-1), (0), (1)) t(dy), (VALUES (-1), (0), (1)) u(dx))
    SELECT a.rid, a.city, max(jaro_winkler_similarity(a.nn, b.nn)) best_jw, count(*) n_cand
    FROM a JOIN o ON true JOIN b ON b.city = a.city AND b.gy = a.gy + o.dy AND b.gx = a.gx + o.dx
    WHERE hav(a.lat, a.lon, b.lat, b.lon) < 300 GROUP BY 1, 2""")
ovr = rows("""SELECT g.city, count(*), count(ov.rid), count(*) FILTER (ov.best_jw >= 0.9), avg(ov.n_cand)
              FROM G g LEFT JOIN ov ON ov.rid = g.rid WHERE g.source = 'osm' AND g.kind = 'lodging' GROUP BY 1""")
om = {o[0]: o for o in ovr}
r.table(["City", "OSM lodgings", "With any Overture lodging within 300 m", "With a name match (JW >= 0.9) within 300 m", "Mean Overture candidates within 300 m"],
        [[c, om[c][1], f"{om[c][2] / om[c][1]:.1%}", f"{om[c][3] / om[c][1]:.1%}", f"{(om[c][4] or 0):.1f}"] for c in CITY_ORDER if c in om])
tot_o = sum(o[1] for o in ovr); tot_m = sum(o[3] for o in ovr)
r.p(f"Across cities, **{tot_m / tot_o:.1%}** of OSM lodgings have an obvious Overture twin (same place, near-identical name). "
    "The rest are either missing from Overture, named differently, or geocoded further away: that remainder is what the matcher is for. "
    "The candidate counts also show why 300 m blocking alone is not enough in dense districts.")
r.stat("osm_overture_lodging_overlap", {"osm_lodgings": tot_o, "obvious_twin": tot_m, "share": tot_m / tot_o})

# ---------------------------------------------------------------- 8. duplicates inside Overture
r.h("8. Duplicates left inside a conflated source")
dup = rows("""SELECT least(a.provider, b.provider) || ' x ' || greatest(a.provider, b.provider), count(*) FROM G a JOIN G b
              ON a.source = 'overture' AND b.source = 'overture' AND a.city = b.city AND a.phone8 = b.phone8 AND a.rid < b.rid
              WHERE hav(a.lat, a.lon, b.lat, b.lon) < 200 AND jaro_winkler_similarity(a.nn, b.nn) >= 0.9 GROUP BY 1 ORDER BY 2 DESC LIMIT 8""")
ndup = sum(d[1] for d in dup)
r.p(f"Inside Overture alone, **{ndup:,} pairs** share a phone, sit within 200 m and have near-identical names: duplicates that survived Overture's own conflation.")
r.table(["Provider pair", "Likely duplicate pairs"], dup)
r.stat("overture_internal_duplicates", ndup)
r.p("Even a professionally conflated feed carries residual duplicates, which supports auditing an existing mapping instead of trusting it blindly.")

# ---------------------------------------------------------------- 9. category vocabularies
r.h("9. Category vocabularies do not line up")
for s in ("overture", "osm", "wikidata"):
    cat = rows(f"SELECT category, count(*) c FROM L WHERE source = '{s}' AND kind = 'attraction' GROUP BY 1 ORDER BY c DESC LIMIT 8")
    r.table([f"{s}: top attraction categories", "Listings"], cat)
r.p("Three taxonomies, three granularities, and noisy assignments (Overture labels many residential towers as historic sites). "
    "Category agreement can only be a soft feature after mapping to a small canonical type list.")

r.h("10. What this means for the build")
r.bullets([
    f"**A real benchmark exists.** {nk:,} cross-source pairs are linked by an independent key across 12 cities; after sanity filtering they are "
    "weak positives, and QID conflicts are trusted negatives. The pair model must be trained without the key features and judged against them.",
    f"**Geography and names both fail alone.** {hd[3]:.1%} of key-linked pairs are over 300 m apart and {hd[6]:.1%} have primary-name similarity below 0.8 "
    f"({hd[7]:.1%} even when alternate-language names are used).",
    "**Alternate names are worth carrying.** They recover a share of the cross-script matches for free; the rest needs transliteration or an embedding.",
    "**Profile the supplier first.** Completeness, decimal precision and shared-point rates differ sharply by source and should weight every feature.",
    "**Hold out by city.** Dubai, Bangkok and Singapore differ in script mix and density; train on some cities and report on an unseen one.",
])
r.write()
