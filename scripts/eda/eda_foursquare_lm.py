"""EDA: Foursquare Location Matching (Kaggle 2022) — the largest labelled POI-duplicate set.

Input : data/raw/foursquare_lm/{train,pairs}.parquet  (community parquet mirror of the competition files)
Output: reports/eda/foursquare_lm.md + figures + foursquare_lm.json
Usage : python -I scripts/eda/eda_foursquare_lm.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import RAW, SERIES, Report, barh, connect, fig_for_bars, plt  # noqa: E402

LODGING = r"(?i)hotel|hostel|resort|motel|bed & breakfast|guest ?house|vacation rental|lodge|\binns?\b"
ATTRACTION = (r"(?i)museum|monument|historic|landmark|theme park|zoo|aquarium|scenic|temple|church|mosque|shrine|palace|castle"
              r"|garden|beach|art gallery|theater|stadium|amusement|waterfall|national park|tourist")

r = Report("foursquare_lm", "EDA — Foursquare Location Matching (labelled POI duplicates)")
con = connect()
con.execute(f"CREATE VIEW t AS SELECT * FROM read_parquet('{(RAW / 'foursquare_lm' / 'train.parquet').as_posix()}')")
con.execute(f"CREATE VIEW p AS SELECT * FROM read_parquet('{(RAW / 'foursquare_lm' / 'pairs.parquet').as_posix()}')")
con.execute("""CREATE MACRO hav(lat1, lon1, lat2, lon2) AS
    2 * 6371000 * asin(sqrt(pow(sin(radians(lat2 - lat1) / 2), 2)
        + cos(radians(lat1)) * cos(radians(lat2)) * pow(sin(radians(lon2 - lon1) / 2), 2)))""")
one = lambda sql: con.execute(sql).fetchone()  # noqa: E731
rows = lambda sql: con.execute(sql).fetchall()  # noqa: E731

r.p("Source: Kaggle competition `foursquare-location-matching` (2022). The competition page no longer serves the files; "
    "this is the community parquet mirror `robikscube/foursquare-location-matching-parquet`. "
    "**Competition terms apply: research / benchmarking only, not for a shipped model.**")

# ---------------------------------------------------------------- 1. size and label structure
n, npoi = one("SELECT count(*), count(DISTINCT point_of_interest) FROM t")
con.execute("CREATE TEMP TABLE sz AS SELECT point_of_interest poi, count(*) n FROM t GROUP BY 1")
true_pairs, multi_poi, multi_rec = one("SELECT sum(n * (n - 1) / 2)::BIGINT, count(*) FILTER (n > 1), sum(n) FILTER (n > 1) FROM sz")
r.h("1. Size and label structure")
r.p(f"`train`: **{n:,} records** describing **{npoi:,} real places** (`point_of_interest`). "
    f"{multi_poi:,} places ({multi_poi / npoi:.1%}) have more than one record; those hold {multi_rec:,} records "
    f"({multi_rec / n:.1%}) and imply **{true_pairs:,} true duplicate pairs**. "
    f"All possible pairs number {n * (n - 1) // 2:.3e}, so a true pair is 1 in {n * (n - 1) // 2 // true_pairs:,}: "
    "blocking decides everything before any classifier runs.")
b = rows("""SELECT CASE WHEN n = 1 THEN '1' WHEN n = 2 THEN '2' WHEN n <= 5 THEN '3-5' WHEN n <= 10 THEN '6-10'
                        WHEN n <= 50 THEN '11-50' ELSE '51+' END b, count(*), sum(n)::BIGINT, min(n) o
            FROM sz GROUP BY 1 ORDER BY o""")
r.table(["Records per place", "Places", "Records", "Share of records"], [[x[0], x[1], x[2], f"{x[2] / n:.1%}"] for x in b])
fig, ax = fig_for_bars(len(b))
barh(ax, [x[0] for x in b], [x[2] for x in b], xlabel="records", title="Records by size of their duplicate cluster")
r.fig(fig, "cluster_size", "Most records sit in clusters of two to five; singletons are the negatives the matcher must leave alone.")
r.stat("records", n); r.stat("places", npoi); r.stat("true_pairs", true_pairs); r.stat("multi_record_places", multi_poi)
r.stat("largest_cluster", one("SELECT max(n) FROM sz")[0])

# ---------------------------------------------------------------- 2. completeness
cols = ["name", "latitude", "longitude", "address", "city", "state", "zip", "country", "url", "phone", "categories"]
comp = one("SELECT " + ", ".join(f"count({c}) / count(*)" for c in cols) + " FROM t")
r.h("2. Field completeness")
order = sorted(zip(cols, comp), key=lambda x: -x[1])
r.table(["Field", "Non-null share"], [[c, f"{v:.1%}"] for c, v in order])
fig, ax = fig_for_bars(len(order))
barh(ax, [c for c, _ in order], [v * 100 for _, v in order], value_fmt="{:.0f}%", xlabel="% of records with a value",
     title="Field completeness in the labelled POI set")
r.fig(fig, "completeness", "Name and coordinates are always there; phone and URL are missing for most records.")
r.stat("completeness", dict(order))

# ---------------------------------------------------------------- 3. geography, categories, scripts
r.h("3. Geography, categories and scripts")
top_c = rows("SELECT coalesce(country, '(null)'), count(*) c FROM t GROUP BY 1 ORDER BY c DESC LIMIT 15")
ncountry = one("SELECT count(DISTINCT country) FROM t")[0]
r.p(f"{ncountry} countries. Top 15:")
r.table(["Country", "Records", "Share"], [[c, v, f"{v / n:.1%}"] for c, v in top_c])
fig, ax = fig_for_bars(len(top_c))
barh(ax, [c for c, _ in top_c], [v for _, v in top_c], xlabel="records", title="Records by country (top 15)")
r.fig(fig, "countries", "The set is global, with the US, Turkey, Indonesia and Japan leading; names come in many scripts.")
cat = rows("""SELECT trim(c) cat, count(*) k FROM (SELECT unnest(string_split(categories, ',')) c FROM t WHERE categories IS NOT NULL)
              GROUP BY 1 ORDER BY k DESC LIMIT 15""")
r.table(["Category (top 15)", "Records"], cat)
nonascii, = one(r"SELECT avg(CASE WHEN regexp_matches(name, '[^\x00-\x7F]') THEN 1 ELSE 0 END) FROM t WHERE name IS NOT NULL")
r.p(f"**{nonascii:.1%}** of names contain non-ASCII characters (accents or a non-Latin script).")
r.stat("non_ascii_name_share", nonascii)
trav = rows(f"""SELECT kind, count(*) recs, count(DISTINCT point_of_interest) places FROM (
                 SELECT point_of_interest, CASE WHEN regexp_matches(categories, '{LODGING}') THEN 'lodging'
                        WHEN regexp_matches(categories, '{ATTRACTION}') THEN 'attraction' END kind FROM t) WHERE kind IS NOT NULL
                 GROUP BY 1 ORDER BY 1""")
r.p("Travel-relevant slice (category keyword match), which is the part closest to TBO's catalogue:")
r.table(["Slice", "Records", "Places"], trav)
r.stat("travel_slice", {k: {"records": a, "places": b_} for k, a, b_ in trav})

# ---------------------------------------------------------------- 4. how far apart are true duplicates
r.h("4. Geo-jitter between records of the same place")
con.execute("""CREATE TEMP TABLE jit AS
    SELECT hav(t.latitude, t.longitude, c.lat, c.lon) d
    FROM t JOIN (SELECT point_of_interest poi, median(latitude) lat, median(longitude) lon, count(*) n FROM t GROUP BY 1) c
      ON t.point_of_interest = c.poi WHERE c.n > 1""")
qs = one("SELECT quantile_cont(d, 0.5), quantile_cont(d, 0.75), quantile_cont(d, 0.9), quantile_cont(d, 0.95), quantile_cont(d, 0.99), "
         "avg((d > 1000)::INT), avg((d > 5000)::INT) FROM jit")
r.p("Distance from each record to the median coordinate of its place (multi-record places only):")
r.table(["p50", "p75", "p90", "p95", "p99", "> 1 km", "> 5 km"],
        [[f"{qs[0]:.0f} m", f"{qs[1]:.0f} m", f"{qs[2]:.0f} m", f"{qs[3]:.0f} m", f"{qs[4]:,.0f} m", f"{qs[5]:.1%}", f"{qs[6]:.1%}"]],
        align=["---:"] * 7)
r.p(f"A hard distance cut-off loses real matches: {qs[5]:.1%} of duplicate records sit more than 1 km from their place. "
    "Distance has to be a feature weighted by the source's coordinate quality, not a veto.")
r.stat("jitter_m", {"p50": qs[0], "p90": qs[2], "p95": qs[3], "p99": qs[4], "gt_1km": qs[5], "gt_5km": qs[6]})

# ---------------------------------------------------------------- 5. the supplied pairs file
r.h("5. Labelled pairs file (`pairs.parquet`)")
np_, mr = one("SELECT count(*), avg(match::INT) FROM p")
r.p(f"{np_:,} candidate pairs supplied by the organisers, **{mr:.1%} labelled as matches**. "
    "They were pre-selected to be plausible, so the non-matches are hard negatives.")
con.execute(r"""CREATE TEMP TABLE pf AS SELECT match,
        hav(latitude_1, longitude_1, latitude_2, longitude_2) d,
        jaro_winkler_similarity(lower(name_1), lower(name_2)) jw,
        lower(name_1) = lower(name_2) name_eq,
        regexp_replace(phone_1, '\D', '', 'g') ph1, regexp_replace(phone_2, '\D', '', 'g') ph2,
        regexp_extract(lower(url_1), '(?:https?://)?(?:www\.)?([^/?#]+)', 1) u1,
        regexp_extract(lower(url_2), '(?:https?://)?(?:www\.)?([^/?#]+)', 1) u2,
        categories_1 = categories_2 cat_eq, country_1 = country_2 ctry_eq,
        address_1 IS NOT NULL AND address_2 IS NOT NULL both_addr
    FROM p WHERE name_1 IS NOT NULL AND name_2 IS NOT NULL""")
summ = rows("""SELECT match, count(*), median(d), quantile_cont(d, 0.9), median(jw), quantile_cont(jw, 0.1), avg(name_eq::INT),
        avg((coalesce(length(ph1), 0) > 5 AND coalesce(length(ph2), 0) > 5)::INT),
        avg((ph1 = ph2)::INT) FILTER (length(ph1) > 5 AND length(ph2) > 5),
        avg((coalesce(length(u1), 0) > 3 AND coalesce(length(u2), 0) > 3)::INT),
        avg((u1 = u2)::INT) FILTER (length(u1) > 3 AND length(u2) > 3),
        avg(coalesce(cat_eq, false)::INT) FROM pf GROUP BY 1 ORDER BY 1 DESC""")
# how reliable are the "exact key" rules on this hard-negative-rich file?
rule = one("""SELECT count(*) FILTER (ph1 = ph2 AND length(ph1) > 5), avg(match::INT) FILTER (ph1 = ph2 AND length(ph1) > 5),
        count(*) FILTER (u1 = u2 AND length(u1) > 3), avg(match::INT) FILTER (u1 = u2 AND length(u1) > 3),
        count(*) FILTER (ph1 = ph2 AND length(ph1) > 5 AND d < 200), avg(match::INT) FILTER (ph1 = ph2 AND length(ph1) > 5 AND d < 200),
        count(*) FILTER (ph1 = ph2 AND length(ph1) > 5 AND d < 200 AND jw >= 0.85),
        avg(match::INT) FILTER (ph1 = ph2 AND length(ph1) > 5 AND d < 200 AND jw >= 0.85) FROM pf""")
hdr = ["", "Pairs", "Median dist", "p90 dist", "Median name JW", "p10 name JW", "Names equal", "Both have phone", "Phones equal (when both)",
       "Both have URL", "Domains equal (when both)", "Categories equal"]
r.table(hdr, [["match" if s[0] else "non-match", s[1], f"{s[2]:.0f} m", f"{s[3]:,.0f} m", f"{s[4]:.3f}", f"{s[5]:.3f}", f"{s[6]:.1%}",
               f"{s[7]:.1%}", f"{(s[8] or 0):.1%}", f"{s[9]:.1%}", f"{(s[10] or 0):.1%}", f"{(s[11] or 0):.1%}"] for s in summ])
r.stat("pairs", {("match" if s[0] else "non_match"): {"n": s[1], "median_dist_m": s[2], "median_jw": s[4], "names_equal": s[6],
                 "both_phone": s[7], "phones_equal_when_both": s[8], "both_url": s[9], "domains_equal_when_both": s[10]} for s in summ})
r.p("Precision of exact-key rules on this file (base rate of a match is "
    f"{mr:.1%}, and the negatives were chosen to be confusable):")
r.table(["Rule", "Pairs it fires on", "Share that are true matches"], [
    ["same phone", rule[0], f"{rule[1]:.1%}"],
    ["same website domain", rule[2], f"{rule[3]:.1%}"],
    ["same phone and < 200 m apart", rule[4], f"{rule[5]:.1%}"],
    ["same phone, < 200 m, name JW >= 0.85", rule[6], f"{rule[7]:.1%}"],
])
r.stat("rule_precision", {"same_phone": rule[1], "same_domain": rule[3], "same_phone_lt200m": rule[5], "same_phone_lt200m_jw085": rule[7]})

# distance histogram by label (share of each class per bin, log bins)
h = rows("""SELECT match, floor(log10(greatest(d, 1)) * 4) / 4 b, count(*) c FROM pf GROUP BY 1, 2 ORDER BY 2""")
fig, ax = plt.subplots(figsize=(7.5, 3.4))
for lab, col, name in ((True, SERIES[0], "match"), (False, SERIES[1], "non-match")):
    xs = [10 ** x[1] for x in h if x[0] == lab]
    tot = sum(x[2] for x in h if x[0] == lab)
    ys = [x[2] / tot * 100 for x in h if x[0] == lab]
    ax.plot(xs, ys, color=col, label=name)
ax.set_xscale("log"); ax.set_xlabel("distance between the two records (m, log scale)"); ax.set_ylabel("% of pairs in class")
ax.set_title("Distance separates the classes only partly"); ax.legend(loc="upper right")
r.fig(fig, "pair_distance", "Matches peak near 30 m but have a long tail; hard negatives are neighbours about 100 m away, so distance alone cannot decide.")

h = rows("SELECT match, floor(jw * 25) / 25 b, count(*) c FROM pf GROUP BY 1, 2 ORDER BY 2")
fig, ax = plt.subplots(figsize=(7.5, 3.4))
for lab, col, name in ((True, SERIES[0], "match"), (False, SERIES[1], "non-match")):
    tot = sum(x[2] for x in h if x[0] == lab)
    ax.plot([x[1] for x in h if x[0] == lab], [x[2] / tot * 100 for x in h if x[0] == lab], color=col, label=name)
ax.set_xlabel("Jaro-Winkler similarity of lower-cased names"); ax.set_ylabel("% of pairs in class")
ax.set_title("Name similarity: strong, with real overlap in the middle"); ax.legend(loc="upper left")
r.fig(fig, "pair_name_similarity", "Many true matches have dissimilar names (translations, abbreviations); many non-matches share a name (chains).")

hard_pos, = one("SELECT avg((jw < 0.8)::INT) FROM pf WHERE match")
hard_neg, = one("SELECT avg((jw > 0.95 AND d < 200)::INT) FROM pf WHERE NOT match")
r.stat("hard_positive_share_jw_lt_0.8", hard_pos); r.stat("hard_negative_share_jw_gt_0.95_within_200m", hard_neg)

# ---------------------------------------------------------------- 6. what this means for the build
r.h("6. What this means for the matcher")
r.bullets([
    f"**Blocking first.** Only 1 in {n * (n - 1) // 2 // true_pairs:,} possible pairs is a match. Candidate generation must combine "
    "geography with name similarity, because neither alone has both recall and a small candidate set.",
    f"**No distance veto.** {qs[5]:.1%} of duplicate records are over 1 km from their place and {qs[6]:.1%} over 5 km.",
    f"**Names are not enough.** {hard_pos:.1%} of true matches have name similarity below 0.8, while {hard_neg:.1%} of non-matches "
    "have near-identical names within 200 m (chains, branches, units inside one building).",
    f"**Exact keys are strong evidence, not proof.** A shared phone alone is a true match {rule[1]:.1%} of the time on these hard pairs "
    f"(a shared domain {rule[3]:.1%}): branches share call centres and chains share websites. Adding distance and name agreement lifts it to "
    f"{rule[7]:.1%}. So stage 0 rules must be conjunctions, and their precision measured, not assumed.",
    "**Use.** Train and benchmark the pair model here (grouped split by `point_of_interest`), then test transfer on the city benchmark. "
    "Because of the competition terms, a shippable model is retrained on the open city data.",
])
r.write()
