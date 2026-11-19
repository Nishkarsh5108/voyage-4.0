"""Offline vector basemap for the demo's map tab: coastline, water and main roads of the demo city, from OpenStreetMap.

Why: public tile servers refuse a page opened as a local file (tile.openstreetmap.org blocks it, others need an API key).
Drawing our own lines from the Geofabrik extract keeps the demo inside every usage policy and makes it work with no internet.

Input : Geofabrik extract for the city (downloaded on demand, removed afterwards)
Output: demo/basemap.js  (window.BASEMAP = {coast, water, major, primary, minor}; each a list of [[lat, lon], ...] lines)
Licence: map data © OpenStreetMap contributors, ODbL.
Usage : python -I scripts/demo/build_basemap.py [--city dubai] [--keep-pbf]
"""
import argparse
import json
import math
import sys
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "download"))
from cities import CITIES  # noqa: E402
from osm_geofabrik import PBF, REGIONS, TMP, download, pbf_path  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("--city", default="dubai")
ap.add_argument("--keep-pbf", action="store_true")
a = ap.parse_args()
for d in (PBF, TMP):
    d.mkdir(parents=True, exist_ok=True)
print(download(REGIONS[a.city]), flush=True)
src = pbf_path(REGIONS[a.city]).as_posix()
w, s, e, n = CITIES[a.city]["bbox"]

con = duckdb.connect()
con.execute(f"SET memory_limit='2GB'; SET threads=4; SET temp_directory='{TMP.as_posix()}'; SET preserve_insertion_order=false;")
con.execute("INSTALL spatial; LOAD spatial;")
con.execute(f"""CREATE TEMP TABLE raw AS
    SELECT kind::VARCHAR AS kind, id, tags, refs, lat, lon FROM st_readosm('{src}')
    WHERE (kind = 'node' AND lat BETWEEN {s} AND {n} AND lon BETWEEN {w} AND {e})
       OR (kind = 'way' AND (tags['natural'] IN ('coastline', 'water') OR tags['waterway'] IN ('canal', 'river', 'riverbank')
           OR tags['highway'] IN ('motorway', 'trunk', 'primary', 'secondary', 'tertiary', 'motorway_link', 'trunk_link', 'primary_link')))""")
rows = con.execute("""
    WITH wy AS (
        SELECT id, CASE WHEN tags['natural'] = 'coastline' THEN 'coast'
                        WHEN tags['natural'] = 'water' OR tags['waterway'] IS NOT NULL THEN 'water'
                        WHEN tags['highway'] IN ('motorway', 'trunk', 'motorway_link', 'trunk_link') THEN 'major'
                        WHEN tags['highway'] IN ('primary', 'primary_link') THEN 'primary' ELSE 'minor' END AS cls,
               unnest(refs) AS ref, unnest(range(len(refs))) AS pos
        FROM raw WHERE kind = 'way')
    SELECT any_value(wy.cls), list(nd.lat ORDER BY wy.pos), list(nd.lon ORDER BY wy.pos)
    FROM wy JOIN (SELECT id, lat, lon FROM raw WHERE kind = 'node') nd ON nd.id = wy.ref
    GROUP BY wy.id HAVING count(*) >= 2""").fetchall()
con.close()

TOL = {"coast": 6, "water": 8, "major": 8, "primary": 10, "minor": 14}  # metres between kept points


def thin(lats, lons, tol_m):
    k = math.cos(math.radians((s + n) / 2)) * 111_320
    out = [(lats[0], lons[0])]
    for la, lo in zip(lats[1:-1], lons[1:-1]):
        pla, plo = out[-1]
        if math.hypot((la - pla) * 111_320, (lo - plo) * k) >= tol_m:
            out.append((la, lo))
    out.append((lats[-1], lons[-1]))
    return [[round(la, 5), round(lo, 5)] for la, lo in out]


base = {k: [] for k in TOL}
for cls, lats, lons in rows:
    line = thin(lats, lons, TOL[cls])
    if len(line) >= (4 if cls == "water" else 2):
        base[cls].append(line)
out = ROOT / "demo" / "basemap.js"
out.write_text("window.BASEMAP = " + json.dumps(base, separators=(",", ":")) + ";\n", encoding="utf-8")
print(f"wrote {out} ({out.stat().st_size / 1e3:.0f} kB): " + ", ".join(f"{k} {len(v)} lines / {sum(len(x) for x in v):,} points" for k, v in base.items()))
if not a.keep_pbf:
    pbf_path(REGIONS[a.city]).unlink(missing_ok=True)
