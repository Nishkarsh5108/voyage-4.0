"""Download Wikivoyage listings (see / do / sleep / eat / drink / buy) for each city and its district pages.

Fetches wikitext through the MediaWiki API and parses the listing templates.

Output: data/raw/wikivoyage/<city>.jsonl  (one listing per line)
Licence: CC BY-SA. Shippable with attribution and share-alike.

Usage: python -I scripts/download/wikivoyage_listings.py [--cities dubai,bangkok]
"""
import argparse
import json
import sys
import time
from pathlib import Path

import mwparserfromhell
import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
from cities import CITIES, USER_AGENT, WIKIVOYAGE_EXTRA  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "data" / "raw" / "wikivoyage"
API = "https://en.wikivoyage.org/w/api.php"
LISTING_TEMPLATES = {"see", "do", "buy", "eat", "drink", "sleep", "listing", "go"}
S = requests.Session()
S.headers["User-Agent"] = USER_AGENT


def api(**params) -> dict:
    params |= {"format": "json", "formatversion": "2"}
    for attempt in range(8):
        r = S.get(API, params=params, timeout=60)
        if r.status_code == 200:
            time.sleep(1.0)  # stay well under the anonymous rate limit
            return r.json()
        wait = int(r.headers.get("Retry-After", "0") or 0) if r.status_code == 429 else 0
        time.sleep(max(wait, 15 * (attempt + 1)))
    r.raise_for_status()
    return {}


def subpages(title: str) -> list[str]:
    titles, cont = [title], {}
    while True:
        d = api(action="query", list="allpages", apprefix=f"{title}/", aplimit="500", apfilterredir="nonredirects", **cont)
        titles += [p["title"] for p in d.get("query", {}).get("allpages", [])]
        if "continue" not in d:
            return titles
        cont = d["continue"]


def wikitext(titles: list[str]) -> dict[str, str]:
    out = {}
    for i in range(0, len(titles), 20):
        d = api(action="query", prop="revisions", rvprop="content", rvslots="main", titles="|".join(titles[i : i + 20]))
        for p in d.get("query", {}).get("pages", []):
            revs = p.get("revisions")
            if revs:
                out[p["title"]] = revs[0]["slots"]["main"]["content"]
        time.sleep(0.5)
    return out


def parse(page: str, text: str) -> list[dict]:
    rows = []
    for t in mwparserfromhell.parse(text).filter_templates():
        kind = str(t.name).strip().lower()
        if kind not in LISTING_TEMPLATES:
            continue
        row = {"page": page, "kind": kind}
        for p in t.params:
            k = str(p.name).strip().lower()
            v = str(p.value).strip()
            if v:
                row[k] = v
        if kind == "listing" and row.get("type"):
            row["kind"] = row["type"].lower()
        if row.get("name"):
            rows.append(row)
    return rows


def fetch(city: str) -> str:
    out = OUT / f"{city}.jsonl"
    if out.exists() and out.stat().st_size > 100:
        return f"{city}: exists"
    titles = subpages(CITIES[city]["wikivoyage"]) + WIKIVOYAGE_EXTRA.get(city, [])
    texts = wikitext(sorted(set(titles)))
    rows = [r for page, text in texts.items() for r in parse(page, text)]
    with out.open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    kinds = {}
    for r in rows:
        kinds[r["kind"]] = kinds.get(r["kind"], 0) + 1
    return f"{city}: ok {len(texts)} pages, {len(rows)} listings {kinds}"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cities", default=",".join(CITIES))
    a = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    for c in a.cities.split(","):
        print(fetch(c), flush=True)


if __name__ == "__main__":
    main()
