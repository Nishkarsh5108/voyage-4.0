"""Fetch English labels for every class QID that appears as `inst` (P31) in data/raw/wikidata/<city>.jsonl.

Output: data/raw/wikidata_classes/class_labels.json  {"Q27686": "hotel", ...}
Usage : python -I scripts/download/wikidata_class_labels.py
"""
import json
import sys
import time
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
from cities import USER_AGENT  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "data" / "raw" / "wikidata"
OUT = ROOT / "data" / "raw" / "wikidata_classes"
OUT.mkdir(parents=True, exist_ok=True)
dest = OUT / "class_labels.json"

qids = set()
for f in SRC.glob("*.jsonl"):
    with f.open(encoding="utf-8") as fh:
        for line in fh:
            inst = json.loads(line).get("inst")
            if inst:
                qids.add(inst.rsplit("/", 1)[-1])
labels = json.loads(dest.read_text(encoding="utf-8")) if dest.exists() else {}
todo = sorted(q for q in qids if q not in labels and q.startswith("Q"))
print(f"{len(qids)} classes, {len(todo)} to fetch", flush=True)
s = requests.Session()
s.headers["User-Agent"] = USER_AGENT
for i in range(0, len(todo), 50):
    batch = todo[i : i + 50]
    for attempt in range(6):
        r = s.get("https://www.wikidata.org/w/api.php", params={
            "action": "wbgetentities", "ids": "|".join(batch), "props": "labels", "languages": "en", "format": "json"}, timeout=60)
        if r.status_code == 200:
            for q, e in r.json().get("entities", {}).items():
                labels[q] = e.get("labels", {}).get("en", {}).get("value", "")
            break
        time.sleep(max(int(r.headers.get("Retry-After", "0") or 0), 10 * (attempt + 1)))
    time.sleep(1.0)
    if i % 500 == 0:
        dest.write_text(json.dumps(labels, ensure_ascii=False), encoding="utf-8")
dest.write_text(json.dumps(labels, ensure_ascii=False), encoding="utf-8")
print(f"done: {len(labels)} labels", flush=True)
