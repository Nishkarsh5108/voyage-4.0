"""Download OpenStreetMap lodging + attraction POIs per city through the Overpass API.

Output: data/raw/osm/<city>.json (raw Overpass JSON, `out center tags`).
Licence: ODbL. Shippable with attribution and share-alike on derived databases.

Usage: python -I scripts/download/osm_overpass.py [--cities dubai,bangkok]
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
OUT = ROOT / "data" / "raw" / "osm"
ENDPOINTS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
]

QUERY = """
[out:json][timeout:240][maxsize:1073741824];
(
  nwr["tourism"]({s},{w},{n},{e});
  nwr["historic"]["name"]({s},{w},{n},{e});
  nwr["building"="hotel"]({s},{w},{n},{e});
  nwr["attraction"]({s},{w},{n},{e});
  nwr["leisure"~"^(water_park|amusement_arcade|garden|marina|beach_resort|nature_reserve|stadium|park)$"]["name"]({s},{w},{n},{e});
  nwr["amenity"~"^(theatre|cinema|arts_centre|place_of_worship|planetarium|casino|nightclub|marketplace)$"]["name"]({s},{w},{n},{e});
  nwr["shop"="mall"]({s},{w},{n},{e});
  nwr["natural"="beach"]["name"]({s},{w},{n},{e});
);
out center tags;
"""


def fetch(city: str) -> str:
    out = OUT / f"{city}.json"
    if out.exists() and out.stat().st_size > 100:
        return f"{city}: exists ({out.stat().st_size / 1e6:.1f} MB)"
    w, s, e, n = CITIES[city]["bbox"]
    q = QUERY.format(s=s, w=w, n=n, e=e)
    last = ""
    for attempt in range(6):
        url = ENDPOINTS[attempt % len(ENDPOINTS)]
        try:
            r = requests.post(url, data={"data": q}, headers={"User-Agent": USER_AGENT}, timeout=300)
            if r.status_code == 200 and r.text.lstrip().startswith("{"):
                data = r.json()
                if "elements" in data and not data.get("remark"):
                    out.write_text(json.dumps(data), encoding="utf-8")
                    return f"{city}: ok {len(data['elements'])} elements, {out.stat().st_size / 1e6:.1f} MB ({url})"
                last = f"remark={data.get('remark')}"
            else:
                last = f"http {r.status_code}"
        except Exception as ex:  # noqa: BLE001
            last = repr(ex)[:200]
        time.sleep(10 * (attempt + 1))
    return f"{city}: FAILED {last}"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cities", default=",".join(CITIES))
    a = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    for c in a.cities.split(","):
        print(fetch(c), flush=True)
        time.sleep(3)  # be polite to the public endpoint


if __name__ == "__main__":
    main()
