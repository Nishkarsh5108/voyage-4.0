"""Download every Wikidata item with a coordinate inside each city bbox.

One row per (item, instance-of, label, website, ...) combination; aggregate downstream.
Tiles are split recursively when the public endpoint times out.

Output: data/raw/wikidata/<city>.jsonl
Licence: CC0. Shippable.

Usage: python -I scripts/download/wikidata_bbox.py [--cities dubai,bangkok]
"""
import argparse
import json
import sys
import time
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
from cities import CITIES, USER_AGENT  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "data" / "raw" / "wikidata"
ENDPOINT = "https://query.wikidata.org/sparql"

QUERY = """
SELECT ?item ?coord ?inst ?label ?labelLocal ?website ?phone ?tripadvisor ?sitelinks ?brand ?stars WHERE {{
  SERVICE wikibase:box {{
    ?item wdt:P625 ?coord .
    bd:serviceParam wikibase:cornerSouthWest "Point({w} {s})"^^geo:wktLiteral .
    bd:serviceParam wikibase:cornerNorthEast "Point({e} {n})"^^geo:wktLiteral .
  }}
  OPTIONAL {{ ?item wdt:P31 ?inst }}
  OPTIONAL {{ ?item rdfs:label ?label FILTER(LANG(?label) = "en") }}
  OPTIONAL {{ ?item rdfs:label ?labelLocal FILTER(LANG(?labelLocal) = "{lang}") }}
  OPTIONAL {{ ?item wdt:P856 ?website }}
  OPTIONAL {{ ?item wdt:P1329 ?phone }}
  OPTIONAL {{ ?item wdt:P3134 ?tripadvisor }}
  OPTIONAL {{ ?item wikibase:sitelinks ?sitelinks }}
  OPTIONAL {{ ?item wdt:P1716 ?brand }}
  OPTIONAL {{ ?item wdt:P10290 ?stars }}
}}
"""


def run(w: float, s: float, e: float, n: float, lang: str, depth: int = 0) -> list[dict]:
    q = QUERY.format(w=w, s=s, e=e, n=n, lang=lang)
    for attempt in range(3):
        try:
            r = requests.get(
                ENDPOINT,
                params={"query": q, "format": "json"},
                headers={"User-Agent": USER_AGENT, "Accept": "application/sparql-results+json"},
                timeout=90,
            )
            if r.status_code == 200:
                rows = r.json()["results"]["bindings"]
                return [{k: v["value"] for k, v in b.items()} for b in rows]
            if r.status_code == 429:
                time.sleep(int(r.headers.get("Retry-After", "20")))
                continue
            break  # 5xx / timeout page -> split
        except (requests.Timeout, requests.ConnectionError, ValueError):
            break
    if depth >= 6:
        print(f"  giving up on tile {w},{s},{e},{n}", flush=True)
        return []
    time.sleep(2)
    mx, my = (w + e) / 2, (s + n) / 2
    out: list[dict] = []
    for tw, ts, te, tn in ((w, s, mx, my), (mx, s, e, my), (w, my, mx, n), (mx, my, e, n)):
        out += run(tw, ts, te, tn, lang, depth + 1)
        time.sleep(1)
    return out


def fetch(city: str) -> str:
    out = OUT / f"{city}.jsonl"
    if out.exists() and out.stat().st_size > 100:
        return f"{city}: exists ({out.stat().st_size / 1e6:.1f} MB)"
    w, s, e, n = CITIES[city]["bbox"]
    # start from a 3x3 grid so a dense city never begins with one huge query
    rows: list[dict] = []
    xs = [w + (e - w) * i / 3 for i in range(4)]
    ys = [s + (n - s) * i / 3 for i in range(4)]
    for i in range(3):
        for j in range(3):
            rows += run(xs[i], ys[j], xs[i + 1], ys[j + 1], CITIES[city]["lang"])
            time.sleep(1)
    with out.open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    items = len({r["item"] for r in rows})
    return f"{city}: ok {len(rows)} rows, {items} items"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cities", default=",".join(CITIES))
    a = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    for c in a.cities.split(","):
        print(fetch(c), flush=True)


if __name__ == "__main__":
    main()
