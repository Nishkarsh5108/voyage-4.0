"""Sightseeing typed relations: a held-out check of canon/activities.py on phrasings it was never tuned on.

reports/models/activities.md is in-sample: its rules were adjusted after reading errors on that same synthetic set.
This script builds a second synthetic supplier for the same 87 real Klook Singapore products with *new* rewrite
templates (written on 20 Nov 2026, after the rules were frozen, with a different seed) and scores the unchanged
relation function once. Nothing in canon/activities.py was edited after seeing this result.

Templates that differ from the in-sample set: new marketing noise and vouchers wording, new synonyms, new phrasings of the
same attribute families (transfer, meal, child, skip-the-line, private, guide) plus two families the in-sample set never
used (senior ticket, evening session), and four new combo formats.

Output: reports/models/activities_heldout.{md,json}
Usage : .venv\\Scripts\\python.exe -I -X utf8 scripts\\train\\activities_heldout.py
"""
import json
import random
import re
import sys
from collections import Counter
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from canon.activities import Gazetteer, norm, parse_activity, relate  # noqa: E402

REP = ROOT / "reports" / "models"
rnd = random.Random(2026)
P = pd.read_parquet(ROOT / "data" / "interim" / "klook_products.parquet")
P = P[(P["city"] == "Singapore") & P["lat"].notna()].reset_index(drop=True)

# gazetteer: identical construction to activities_benchmark.py (open data only, no Klook text)
L = pd.read_parquet(ROOT / "data" / "interim" / "listings.parquet")
L = L[(L["city"] == "singapore") & (L["kind"] == "attraction")]
keep = (L["source"].isin(["wikidata", "wikivoyage"])
        | ((L["source"] == "osm") & L["category"].fillna("").str.contains(r"tourism=(attraction|museum|theme_park|zoo|aquarium|gallery|viewpoint)|leisure=water_park")))
names = set(L.loc[keep, "name"].dropna())
for alts in L.loc[keep, "alt_names"]:
    if alts is not None:
        names.update(a for a in alts if isinstance(a, str) and re.search(r"[A-Za-z]", a))
alias = {re.sub(r"(?i)[ ,]+(singapore|sentosa)$", "", n).strip() for n in names}
GENERIC = {"singapore", "sentosa", "marina bay", "orchard road", "chinatown", "little india", "the garden", "city hall", "downtown core"}
gaz = Gazetteer([n for n in names | alias if norm(n) not in GENERIC])


def hav(a, b):
    p1, p2 = np.radians(a.lat), np.radians(b.lat)
    x = np.sin((p2 - p1) / 2) ** 2 + np.cos(p1) * np.cos(p2) * np.sin(np.radians(b.lon - a.lon) / 2) ** 2
    return 2 * 6371000 * np.arcsin(np.sqrt(x))


def clean(title):
    t = re.sub(r"\[[^\]]+\]", " ", title).replace("™", "")
    t = re.sub(r"(?i)\s+in\s+(singapore|sentosa)\s*$", "", t)
    return re.sub(r"\s+", " ", t).strip(" -:,")


# ---------------------------------------------------------------- held-out templates (none of these strings appear in the in-sample set)
SYN2 = [(r"(?i)\btickets?\b", "Pass"), (r"(?i)\badmission\b", "General Entry"), (r"(?i)\bentry\b", "Entrance")]
NOISE2 = ["{} [E-Voucher]", "Book Now: {}", "{} (Mobile Voucher)", "{} – Instant Booking", "Top Pick | {}", "{} Singapore"]
VARIANTS2 = [(" incl. Return Transfers", "transfer"), (" with Buffet Dinner", "meal"), (" - Kids Ticket", "child"),
             (" (Fast Track Entry)", "skip_the_line"), (" - Private Tour", "private"), (" + Guided Tour", "guide"),
             (" - Senior Ticket", "senior"), (" - Evening Session", "time")]
COMBOS = ["Combo: {a} & {b}", "{a} and {b} Bundle", "{a} + {b} Package", "2-in-1: {a} + {b}"]


def rename2(title):
    t = clean(title)
    for pat, rep in SYN2:
        if re.search(pat, t):
            t = re.sub(pat, rep, t, count=1)
            break
    if rnd.random() < 0.3:
        t = t.lower()
    return rnd.choice(NOISE2).format(t)


pairs = []
prods = list(P.itertuples())
for a in prods:
    far = [b for b in prods if hav(a, b) > 500]
    pairs.append((a.title, rename2(a.title), "SAME_AS", "rename"))
    pairs.append((a.title, rename2(a.title), "SAME_AS", "rename"))
    for suffix, what in rnd.sample(VARIANTS2, 3):
        pairs.append((a.title, rename2(a.title) + suffix, "VARIANT_OF", what))
    for b in rnd.sample(far, 2):
        pairs.append((a.title, rnd.choice(COMBOS).format(a=clean(a.title), b=clean(b.title)), "INCLUDES", "combo"))
    for b in rnd.sample(far, 2):
        pairs.append((a.title, rename2(b.title), "DIFFERENT", "other"))

LABELS = ["SAME_AS", "VARIANT_OF", "INCLUDES", "DIFFERENT"]
conf, by_what, errors, dump = Counter(), Counter(), [], []
for x, y, truth, what in pairs:
    r = relate(parse_activity(x, gazetteer=gaz), parse_activity(y, gazetteer=gaz))
    pred = "INCLUDES" if r.relation in ("INCLUDES", "INCLUDED_IN") else r.relation
    dump.append((x, y, truth, what, pred, r.reason))
    conf[(truth, pred)] += 1
    by_what[(truth, what, pred == truth)] += 1
    if pred != truth and len(errors) < 30 and rnd.random() < 0.5:
        errors.append((truth, pred, x, y, r.reason))
pd.DataFrame(dump, columns=["a", "b", "truth", "template", "rules_pred", "rules_reason"]).to_csv(
    ROOT / "data" / "interim" / "activity_pairs_heldout.csv", index=False, encoding="utf-8")
f1 = {}
for lab in LABELS:
    tp = conf[(lab, lab)]
    fp = sum(conf[(t, lab)] for t in LABELS if t != lab)
    fn = sum(conf[(lab, p)] for p in LABELS if p != lab)
    pr, rc = tp / max(tp + fp, 1), tp / max(tp + fn, 1)
    f1[lab] = {"precision": pr, "recall": rc, "f1": 2 * pr * rc / max(pr + rc, 1e-9), "n": tp + fn}
macro = float(np.mean([v["f1"] for v in f1.values()]))
acc = sum(conf[(lab, lab)] for lab in LABELS) / len(pairs)
insample = json.loads((REP / "activities.json").read_text(encoding="utf-8")) if (REP / "activities.json").exists() else {}
whats = sorted({(t, w) for t, w, _ in by_what})
res = {"pairs": len(pairs), "products": len(prods), "accuracy": acc, "macro_f1": macro, "per_relation": f1,
       "confusion": {f"{t}->{p}": c for (t, p), c in conf.items()},
       "by_template": {f"{t}/{w}": by_what[(t, w, True)] / max(by_what[(t, w, True)] + by_what[(t, w, False)], 1) for t, w in whats}}
(REP / "activities_heldout.json").write_text(json.dumps(res, indent=1), encoding="utf-8")


def pc(v):
    return f"{v:.1%}"


ins_acc = insample.get("benchmark", {}).get("accuracy") if isinstance(insample.get("benchmark"), dict) else insample.get("accuracy")
M = ["# Sightseeing typed relations: held-out phrasings", "",
     "Generated by `scripts/train/activities_heldout.py`. Same 87 real Klook Singapore products and the same open-data gazetteer as "
     "`activities.md`, but a second synthetic supplier written with **new templates** after the rules were frozen (different seed, new noise, "
     "synonyms, attribute phrasings, two attribute families the in-sample set never used, four new combo formats). The relation function "
     "was run once on this set and not changed afterwards.", "",
     f"**Accuracy {pc(acc)}, macro-F1 {macro:.3f}** over {len(pairs):,} pairs"
     + (f" (in-sample set: accuracy {pc(ins_acc)})." if ins_acc else "."), "",
     "| Relation | Pairs | Precision | Recall | F1 |", "|---|---:|---:|---:|---:|"]
M += [f"| {lab} | {f1[lab]['n']} | {pc(f1[lab]['precision'])} | {pc(f1[lab]['recall'])} | {f1[lab]['f1']:.3f} |" for lab in LABELS]
M += ["", "Confusion (rows: truth, columns: predicted):", "", "| | " + " | ".join(LABELS) + " |", "|---|" + "---:|" * len(LABELS)]
M += [f"| {t} | " + " | ".join(str(conf[(t, p)]) for p in LABELS) + " |" for t in LABELS]
M += ["", "Share right, by template family:", "", "| Truth / template | Right |", "|---|---:|"]
M += [f"| {k} | {pc(v)} |" for k, v in res["by_template"].items()]
M += ["", "Sample of errors:", "", "| Truth | Predicted | Original | Second supplier | Reason given |", "|---|---|---|---|---|"]
M += [f"| {t} | {p} | {x} | {y} | {why} |" for t, p, x, y, why in errors[:12]]
M += ["", "## Reading the numbers", "",
      "- Still a synthetic second supplier, so this measures robustness to unseen phrasings, not accuracy on a real feed.",
      "- The gap to the in-sample score is the honest size of the lexicon's blind spots; the template rows show which phrasings the "
      "lexicon has no word for (they go to the model stage in the cascade)."]
(REP / "activities_heldout.md").write_text("\n".join(M) + "\n", encoding="utf-8")
print(json.dumps({"accuracy": round(acc, 4), "macro_f1": round(macro, 4), "by_template": {k: round(v, 3) for k, v in res["by_template"].items()}}, indent=1))
