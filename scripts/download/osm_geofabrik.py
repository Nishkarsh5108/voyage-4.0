"""OpenStreetMap lodging + attraction POIs per city, from Geofabrik regional extracts.

Used instead of Overpass: on 14 Nov 2026 all three public Overpass instances accepted connections but
never answered. Geofabrik serves static .osm.pbf files; DuckDB's spatial extension reads them directly.

Steps per city
  1. download the smallest Geofabrik extract containing the city  -> data/raw/osm_pbf/<region>.osm.pbf
  2. one scan: every node inside the bbox + every way/relation matching the tag filter
  3. second scan: member ways of the matching relations
  4. centre of a way / relation = mean of its node coordinates inside the bbox
Output: data/raw/osm/<city>.parquet  (osm_type, osm_id, lat, lon, tags MAP)
Licence: ODbL. Shippable with attribution and share-alike on derived databases.

Usage: python -I scripts/download/osm_geofabrik.py [--cities dubai,bangkok] [--keep-pbf]
"""
import argparse
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import duckdb
import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
from cities import CITIES, USER_AGENT  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
PBF = ROOT / "data" / "raw" / "osm_pbf"
OUT = ROOT / "data" / "raw" / "osm"
TMP = ROOT / "data" / "interim" / "duckdb_tmp"

REGIONS = {
    "dubai": "asia/gcc-states",
    "bangkok": "asia/thailand",
    "singapore": "asia/malaysia-singapore-brunei",
    "delhi": "asia/india/northern-zone",
    "mumbai": "asia/india/western-zone",
    "goa": "asia/india/western-zone",
    "london": "europe/united-kingdom/england/greater-london",
    "paris": "europe/france/ile-de-france",
    "amsterdam": "europe/netherlands/noord-holland",
    "barcelona": "europe/spain/cataluna",
    "vienna": "europe/austria",
    "milan": "europe/italy/nord-ovest",
}

TAG_FILTER = """(
     tags['tourism'] IS NOT NULL
  OR (tags['historic'] IS NOT NULL AND tags['name'] IS NOT NULL)
  OR tags['building'] = 'hotel'
  OR tags['attraction'] IS NOT NULL
  OR (tags['leisure'] IN ('water_park','amusement_arcade','garden','marina','beach_resort','nature_reserve','stadium','park')
      AND tags['name'] IS NOT NULL)
  OR (tags['amenity'] IN ('theatre','cinema','arts_centre','place_of_worship','planetarium','casino','nightclub','marketplace')
      AND tags['name'] IS NOT NULL)
  OR tags['shop'] = 'mall'
  OR (tags['natural'] = 'beach' AND tags['name'] IS NOT NULL)
)"""


def pbf_path(region: str) -> Path:
    return PBF / (region.replace("/", "__") + ".osm.pbf")


def download(region: str) -> str:
    dest = pbf_path(region)
    if dest.exists() and dest.stat().st_size > 1_000_000:
        return f"{region}: pbf exists ({dest.stat().st_size / 1e6:.0f} MB)"
    url = f"https://download.geofabrik.de/{region}-latest.osm.pbf"
    part = dest.with_suffix(".part")
    t0 = time.time()
    for attempt in range(4):
        try:
            with requests.get(url, stream=True, timeout=60, headers={"User-Agent": USER_AGENT}) as r:
                r.raise_for_status()
                with part.open("wb") as f:
                    for chunk in r.iter_content(1 << 20):
                        f.write(chunk)
            part.replace(dest)
            return f"{region}: downloaded {dest.stat().st_size / 1e6:.0f} MB in {time.time() - t0:.0f}s"
        except Exception as ex:  # noqa: BLE001
            err = repr(ex)[:200]
            time.sleep(10 * (attempt + 1))
    return f"{region}: DOWNLOAD FAILED {err}"


def extract(city: str) -> str:
    out = OUT / f"{city}.parquet"
    if out.exists() and out.stat().st_size > 1000:
        return f"{city}: exists"
    src = pbf_path(REGIONS[city]).as_posix()
    w, s, e, n = CITIES[city]["bbox"]
    t0 = time.time()
    con = duckdb.connect()
    con.execute(f"SET memory_limit='2GB'; SET threads=4; SET temp_directory='{TMP.as_posix()}'; SET preserve_insertion_order=false;")
    con.execute("INSTALL spatial; LOAD spatial;")
    con.execute(f"""
        CREATE TEMP TABLE raw AS
        SELECT kind::VARCHAR AS kind, id, tags, refs, ref_types::VARCHAR[] AS ref_types, lat, lon
        FROM st_readosm('{src}')
        WHERE (kind = 'node' AND lat BETWEEN {s} AND {n} AND lon BETWEEN {w} AND {e})
           OR (kind IN ('way', 'relation') AND {TAG_FILTER})
    """)
    con.execute("CREATE TEMP TABLE nb AS SELECT id, lat, lon FROM raw WHERE kind = 'node'")
    # relation members
    con.execute("""
        CREATE TEMP TABLE rm AS
        SELECT id AS rid, unnest(refs) AS ref, unnest(ref_types) AS rt FROM raw WHERE kind = 'relation'
    """)
    con.execute(f"""
        CREATE TEMP TABLE mw AS
        SELECT id, refs FROM st_readosm('{src}')
        WHERE kind = 'way' AND id IN (SELECT ref FROM rm WHERE rt = 'way')
    """)
    con.execute(f"""
        COPY (
            WITH way_c AS (
                SELECT x.id, avg(nb.lat) AS lat, avg(nb.lon) AS lon
                FROM (SELECT id, unnest(refs) AS ref FROM raw WHERE kind = 'way') x JOIN nb ON nb.id = x.ref
                GROUP BY x.id
            ),
            rel_nodes AS (
                SELECT rm.rid, nb.lat, nb.lon FROM rm JOIN nb ON rm.rt = 'node' AND nb.id = rm.ref
                UNION ALL
                SELECT rm.rid, nb.lat, nb.lon
                FROM rm JOIN (SELECT id, unnest(refs) AS ref FROM mw) m ON rm.rt = 'way' AND m.id = rm.ref
                        JOIN nb ON nb.id = m.ref
            ),
            rel_c AS (SELECT rid AS id, avg(lat) AS lat, avg(lon) AS lon FROM rel_nodes GROUP BY rid)
            SELECT 'node' AS osm_type, id AS osm_id, lat, lon, tags FROM raw WHERE kind = 'node' AND {TAG_FILTER}
            UNION ALL
            SELECT 'way', r.id, c.lat, c.lon, r.tags FROM raw r JOIN way_c c USING (id) WHERE r.kind = 'way'
            UNION ALL
            SELECT 'relation', r.id, c.lat, c.lon, r.tags FROM raw r JOIN rel_c c USING (id) WHERE r.kind = 'relation'
        ) TO '{out.as_posix()}' (FORMAT parquet, COMPRESSION zstd)
    """)
    stats = con.execute(f"SELECT osm_type, count(*) FROM read_parquet('{out.as_posix()}') GROUP BY 1 ORDER BY 1").fetchall()
    con.close()
    return f"{city}: ok {dict(stats)} in {time.time() - t0:.0f}s"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cities", default=",".join(CITIES))
    ap.add_argument("--keep-pbf", action="store_true", help="keep the regional .osm.pbf files after extraction")
    a = ap.parse_args()
    cities = a.cities.split(",")
    for d in (PBF, OUT, TMP):
        d.mkdir(parents=True, exist_ok=True)
    todo = [c for c in cities if not (OUT / f"{c}.parquet").exists()]
    regions = sorted({REGIONS[c] for c in todo})
    with ThreadPoolExecutor(3) as ex:
        for msg in ex.map(download, regions):
            print(msg, flush=True)
    for c in cities:
        try:
            print(extract(c), flush=True)
        except Exception as ex:  # noqa: BLE001
            print(f"{c}: EXTRACT FAILED {repr(ex)[:300]}", flush=True)
    if not a.keep_pbf and all((OUT / f"{c}.parquet").exists() for c in cities):
        for r in {REGIONS[c] for c in cities}:
            pbf_path(r).unlink(missing_ok=True)
        print("removed regional pbf files (re-download with --keep-pbf to retain)", flush=True)


if __name__ == "__main__":
    main()
