"""Normalise the four open city sources into one canonical listing table (the "ingest" layer).

Each source plays the role of a supplier describing the same real hotels and attractions with its own
naming, geocoding and completeness habits.

Input : data/raw/{overture,osm,wikidata,wikivoyage}/<city>.*, data/raw/wikidata_classes/class_labels.json
Output: data/interim/listings.parquet
Usage : python -I scripts/build/build_listings.py
"""
import json
import sys
from pathlib import Path

import duckdb
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
RAW = (ROOT / "data" / "raw").as_posix()
OUT = ROOT / "data" / "interim" / "listings.parquet"
sys.path.insert(0, str(ROOT / "scripts" / "download"))
from cities import CITIES  # noqa: E402

LODGING_WD = r"(?i)\b(hotel|hostel|resort|motel|guest ?house|inn|bed and breakfast|ryokan|serviced apartment|lodging|aparthotel)\b"
ATTRACTION_WD = (r"(?i)\b(museum|monument|tourist attraction|park|garden|temple|church|mosque|palace|castle|theatre|theater|gallery|zoo"
                 r"|aquarium|landmark|memorial|shrine|cathedral|fort|fortress|tower|bridge|square|market|beach|stadium|statue|sculpture"
                 r"|fountain|shopping (mall|center|centre)|skyscraper|historic|heritage|amusement|theme park|opera|concert hall|synagogue"
                 r"|gurdwara|pagoda|stupa|mausoleum|tomb|observation|viewpoint|island|basilica|chapel|abbey|monastery|wat|souq|bazaar"
                 r"|cultural|archaeological|ruins|lighthouse|pier|promenade|botanical|planetarium|arena|racecourse|casino|ferris wheel"
                 r"|water park|cemetery|city gate|triumphal arch|obelisk|cable car|marina)\b")

con = duckdb.connect()
con.execute("SET memory_limit='2GB'; SET threads=3; SET preserve_insertion_order=false;")
con.execute("INSTALL spatial; LOAD spatial;")
CITY = r"regexp_extract(replace(filename, '\', '/'), '([a-z]+)\.[a-z]+$', 1)"

# ------------------------------------------------------------------ Overture
con.execute(f"""CREATE TEMP TABLE s_overture AS
SELECT 'overture' AS source,
       coalesce(list_filter(list_transform(sources, lambda s: s.dataset), lambda d: d <> 'Overture')[1], 'Overture') AS provider,
       {CITY} AS city, id AS src_id,
       CASE WHEN taxonomy.hierarchy[1] = 'lodging' THEN 'lodging' ELSE 'attraction' END AS kind,
       array_to_string(taxonomy.hierarchy, '/') AS category,
       names.primary AS name,
       coalesce(map_values(names.common), []::VARCHAR[]) AS alt_names,
       ST_Y(geometry) AS lat, ST_X(geometry) AS lon,
       addresses[1].freeform AS street, addresses[1].postcode AS postcode, addresses[1].locality AS addr_city,
       phones[1] AS phone_raw, websites[1] AS website, NULL::VARCHAR AS qid, brand.names.primary AS brand,
       NULL::DOUBLE AS stars, confidence, len(phones) AS n_phones, len(websites) AS n_websites
FROM read_parquet('{RAW}/overture/*.parquet', filename = true)
WHERE taxonomy.hierarchy[1] IN ('lodging', 'cultural_and_historic', 'arts_and_entertainment')
   OR (taxonomy.hierarchy[1] = 'sports_and_recreation' AND taxonomy.hierarchy[2] = 'park')""")

# ------------------------------------------------------------------ OSM
con.execute(f"""CREATE TEMP TABLE s_osm AS
SELECT 'osm' AS source, 'osm' AS provider, {CITY} AS city, osm_type || '/' || osm_id AS src_id,
       CASE WHEN tags['tourism'] IN ('hotel', 'hostel', 'guest_house', 'motel', 'apartment', 'resort', 'chalet', 'spa_resort')
                 OR tags['building'] = 'hotel' THEN 'lodging' ELSE 'attraction' END AS kind,
       coalesce('tourism=' || tags['tourism'], 'historic=' || tags['historic'], 'leisure=' || tags['leisure'], 'amenity=' || tags['amenity'],
                'shop=' || tags['shop'], 'natural=' || tags['natural'], 'attraction=' || tags['attraction'], 'building=' || tags['building']) AS category,
       coalesce(tags['name'], tags['name:en']) AS name,
       list_distinct(list_transform(list_filter(map_entries(tags),
            lambda e: e.key LIKE 'name:%' OR e.key IN ('alt_name', 'official_name', 'int_name', 'old_name', 'short_name')), lambda e: e.value)) AS alt_names,
       lat, lon,
       nullif(concat_ws(' ', tags['addr:housenumber'], tags['addr:street']), '') AS street, tags['addr:postcode'] AS postcode, tags['addr:city'] AS addr_city,
       coalesce(tags['phone'], tags['contact:phone']) AS phone_raw, coalesce(tags['website'], tags['contact:website'], tags['url']) AS website,
       tags['wikidata'] AS qid, coalesce(tags['brand'], tags['operator']) AS brand,
       try_cast(regexp_extract(tags['stars'], '(\\d(\\.\\d)?)', 1) AS DOUBLE) AS stars, NULL::DOUBLE AS confidence,
       (coalesce(tags['phone'], tags['contact:phone']) IS NOT NULL)::INT AS n_phones,
       (coalesce(tags['website'], tags['contact:website'], tags['url']) IS NOT NULL)::INT AS n_websites
FROM read_parquet('{RAW}/osm/*.parquet', filename = true)
WHERE coalesce(tags['name'], tags['name:en']) IS NOT NULL
  AND coalesce(tags['tourism'], '') NOT IN ('information', 'picnic_site', 'artwork', 'camp_site', 'caravan_site')""")

# ------------------------------------------------------------------ Wikidata
labels = json.loads((ROOT / "data" / "raw" / "wikidata_classes" / "class_labels.json").read_text(encoding="utf-8"))
cl = pd.DataFrame({"cq": list(labels), "clabel": list(labels.values())})  # noqa: F841 (used by DuckDB replacement scan)
con.execute(f"""CREATE TEMP TABLE s_wikidata AS
WITH agg AS (
    SELECT {CITY} AS city, regexp_extract(item, '(Q\\d+)$', 1) AS q, any_value(label) AS name, any_value(labelLocal) AS name_local,
           any_value(coord) AS coord, any_value(website) AS website, any_value(phone) AS phone_raw,
           max(try_cast(stars AS DOUBLE)) AS stars, string_agg(DISTINCT cl.clabel, '; ') AS classes
    FROM read_json_auto('{RAW}/wikidata/*.jsonl', filename = true, union_by_name = true) w
    LEFT JOIN cl ON cl.cq = regexp_extract(w.inst, '(Q\\d+)$', 1)
    GROUP BY 1, 2)
SELECT 'wikidata' AS source, 'wikidata' AS provider, city, q AS src_id,
       CASE WHEN regexp_matches(classes, '{LODGING_WD}') THEN 'lodging' ELSE 'attraction' END AS kind, classes AS category, name,
       CASE WHEN name_local IS NOT NULL AND name_local <> name THEN [name_local] ELSE []::VARCHAR[] END AS alt_names,
       try_cast(regexp_extract(coord, 'Point\\(([-\\d.]+) ([-\\d.]+)\\)', 2) AS DOUBLE) AS lat,
       try_cast(regexp_extract(coord, 'Point\\(([-\\d.]+) ([-\\d.]+)\\)', 1) AS DOUBLE) AS lon,
       NULL::VARCHAR AS street, NULL::VARCHAR AS postcode, NULL::VARCHAR AS addr_city, phone_raw, website, q AS qid, NULL::VARCHAR AS brand,
       stars, NULL::DOUBLE AS confidence, (phone_raw IS NOT NULL)::INT AS n_phones, (website IS NOT NULL)::INT AS n_websites
FROM agg
WHERE coalesce(name, name_local) IS NOT NULL
  AND (regexp_matches(classes, '{LODGING_WD}') OR regexp_matches(classes, '{ATTRACTION_WD}'))""")

# ------------------------------------------------------------------ Wikivoyage
con.execute(f"""CREATE TEMP TABLE s_wikivoyage AS
SELECT 'wikivoyage' AS source, 'wikivoyage' AS provider, {CITY} AS city,
       md5(page || '|' || name || '|' || coalesce(lat::VARCHAR, '')) AS src_id,
       CASE WHEN kind = 'sleep' THEN 'lodging' ELSE 'attraction' END AS kind, kind || ' @ ' || page AS category,
       trim(regexp_replace(regexp_replace(name, '\\[\\[(?:[^|\\]]*\\|)?([^\\]]*)\\]\\]', '\\1', 'g'), '''{{2,}}', '', 'g')) AS name,
       CASE WHEN alt IS NOT NULL THEN [alt] ELSE []::VARCHAR[] END AS alt_names,
       try_cast(lat AS DOUBLE) AS lat, try_cast(long AS DOUBLE) AS lon,
       address AS street, NULL::VARCHAR AS postcode, NULL::VARCHAR AS addr_city, phone AS phone_raw, url AS website,
       regexp_extract(wikidata, '(Q\\d+)', 1) AS qid, NULL::VARCHAR AS brand, NULL::DOUBLE AS stars, NULL::DOUBLE AS confidence,
       (phone IS NOT NULL)::INT AS n_phones, (url IS NOT NULL)::INT AS n_websites
FROM read_json_auto('{RAW}/wikivoyage/*.jsonl', filename = true, union_by_name = true)
WHERE kind IN ('sleep', 'see', 'do') AND name IS NOT NULL""")

# ------------------------------------------------------------------ union + derived keys + bbox check
bbox = pd.DataFrame([{"city": c, "w": v["bbox"][0], "s": v["bbox"][1], "e": v["bbox"][2], "n": v["bbox"][3], "grp": v["group"]}
                     for c, v in CITIES.items()])  # noqa: F841
con.execute(f"""COPY (
WITH u AS (SELECT * FROM s_overture UNION ALL SELECT * FROM s_osm UNION ALL SELECT * FROM s_wikidata UNION ALL SELECT * FROM s_wikivoyage),
k AS (
    SELECT u.*, b.grp AS city_group,
           (lat BETWEEN b.s AND b.n AND lon BETWEEN b.w AND b.e) AS in_bbox,
           regexp_replace(string_split(phone_raw, ';')[1], '\\D', '', 'g') AS phone_digits,
           regexp_extract(lower(website), '^(?:https?://)?(?:www\\.)?([^/?#:]+)', 1) AS domain,
           rtrim(regexp_extract(lower(website), '^(?:https?://)?(?:www\\.)?([^?#]+)', 1), '/') AS url_key
    FROM u JOIN bbox b USING (city))
SELECT source, provider, city, city_group, src_id, kind, category, name, alt_names, lat, lon, in_bbox, street, postcode, addr_city,
       phone_raw, CASE WHEN length(phone_digits) >= 8 THEN right(phone_digits, 8) END AS phone8,
       website, nullif(domain, '') AS domain, nullif(url_key, '') AS url_key, nullif(qid, '') AS qid, brand, stars, confidence
FROM k WHERE name IS NOT NULL AND length(trim(name)) > 0
) TO '{OUT.as_posix()}' (FORMAT parquet, COMPRESSION zstd)""")

for row in con.execute(f"""SELECT source, kind, count(*) n, count(DISTINCT city) cities, round(avg((lat IS NOT NULL)::INT), 3) has_xy,
        round(avg((phone8 IS NOT NULL)::INT), 3) phone, round(avg((domain IS NOT NULL)::INT), 3) web, round(avg((qid IS NOT NULL)::INT), 3) qid
        FROM read_parquet('{OUT.as_posix()}') GROUP BY 1, 2 ORDER BY 1, 2""").fetchall():
    print(row)
