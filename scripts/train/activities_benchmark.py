"""Sightseeing typed-relation benchmark on real Klook Singapore products with a synthetic second supplier.

Real: 87 Klook Singapore products (titles, options, coordinates) and a gazetteer of Singapore attractions from open data.
Synthetic: a second supplier's listing of each product, written by rewrite rules with a known relation to the original:
    SAME_AS      renamed only (tags stripped, synonyms, word order, marketing noise)
    VARIANT_OF   renamed + one attribute changed (pickup, meal, child ticket, skip-the-line, private)
    INCLUDES     bundled with another real product located more than 500 m away
    DIFFERENT    another real product located more than 500 m away, renamed
The truth for "another attraction" comes from Klook's coordinates, not from the text the parser reads.
The rewrite rules share no code with canon/activities.py but have the same author: a synthetic-supplier result.

Output: reports/models/activities.{md,json}
Usage : python -I scripts/train/activities_benchmark.py
"""
import json
import random
import re
import sys
from collections import Counter
from pathlib import Path

import numpy as np
import pandas as pd
from rapidfuzz import fuzz

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from canon.activities import Gazetteer, norm, parse_activity, parse_policy, relate  # noqa: E402

REP = ROOT / "reports" / "models"
rnd = random.Random(7)
P = pd.read_parquet(ROOT / "data" / "interim" / "klook_products.parquet")
O = pd.read_parquet(ROOT / "data" / "interim" / "klook_options.parquet")
P = P[(P["city"] == "Singapore") & P["lat"].notna()].reset_index(drop=True)

# ---------------------------------------------------------------- gazetteer from open data (Wikidata, Wikivoyage, OSM visitor attractions)
L = pd.read_parquet(ROOT / "data" / "interim" / "listings.parquet")
L = L[(L["city"] == "singapore") & (L["kind"] == "attraction")]
keep = (L["source"].isin(["wikidata", "wikivoyage"])
        | ((L["source"] == "osm") & L["category"].fillna("").str.contains(r"tourism=(attraction|museum|theme_park|zoo|aquarium|gallery|viewpoint)|leisure=water_park")))
names = set(L.loc[keep, "name"].dropna())
for alts in L.loc[keep, "alt_names"]:
    if alts is not None:
        names.update(a for a in alts if isinstance(a, str) and re.search(r"[A-Za-z]", a))
# aliases: the same name without a trailing place word, so "Madame Tussauds" finds "Madame Tussauds Singapore"
alias = set()
for n in names:
    m = re.sub(r"(?i)[ ,]+(singapore|sentosa)$", "", n).strip()
    if m != n:
        alias.add(m)
GENERIC = {"singapore", "sentosa", "marina bay", "orchard road", "chinatown", "little india", "the garden", "city hall", "downtown core"}
gaz = Gazetteer([n for n in names | alias if norm(n) not in GENERIC])

parsed = {r.id: parse_activity(r.title, gazetteer=gaz) for r in P.itertuples()}
anchored = sum(1 for a in parsed.values() if a.attractions)
multi = sum(1 for a in parsed.values() if len(a.attractions) > 1)


def hav(a, b):
    p1, p2 = np.radians(a.lat), np.radians(b.lat)
    x = np.sin((p2 - p1) / 2) ** 2 + np.cos(p1) * np.cos(p2) * np.sin(np.radians(b.lon - a.lon) / 2) ** 2
    return 2 * 6371000 * np.arcsin(np.sqrt(x))


# ---------------------------------------------------------------- synthetic second supplier
def clean(title):
    t = re.sub(r"\[[^\]]+\]", " ", title).replace("™", "")
    t = re.sub(r"(?i)\s+in\s+(singapore|sentosa)\s*$", "", t)
    return re.sub(r"\s+", " ", t).strip(" -:,")


SYN = [(r"(?i)\badmission ticket\b", "Entry Ticket"), (r"(?i)\bticket\b", "Admission"), (r"(?i)\badmission\b", "E-Ticket")]
NOISE = ["[Best Seller] {}", "{} (Instant Confirmation)", "Singapore: {}", "{} - Mobile Ticket", "{} | Open Date"]
VARIANTS = [(" with Hotel Pickup", "transfer"), (" + Lunch", "meal"), (" (Child)", "child"), (" - Skip the Line", "skip_the_line"),
            (" - Private", "private"), (" with Audio Guide", "guide")]


def rename(title):
    t = clean(title)
    for pat, rep in SYN:
        if re.search(pat, t):
            t = re.sub(pat, rep, t, count=1)
            break
    return rnd.choice(NOISE).format(t)


pairs = []
prods = list(P.itertuples())
for a in prods:
    far = [b for b in prods if hav(a, b) > 500]
    pairs.append((a.title, rename(a.title), "SAME_AS", ""))
    pairs.append((a.title, clean(a.title).upper(), "SAME_AS", ""))
    for suffix, what in rnd.sample(VARIANTS, 3):
        pairs.append((a.title, rename(a.title) + suffix, "VARIANT_OF", what))
    for b in rnd.sample(far, 2):
        pairs.append((a.title, f"{clean(a.title)} + {clean(b.title)} Combo", "INCLUDES", ""))
    for b in rnd.sample(far, 2):
        pairs.append((a.title, rename(b.title), "DIFFERENT", ""))

LABELS = ["SAME_AS", "VARIANT_OF", "INCLUDES", "DIFFERENT"]
conf = Counter()
errors = []
fz_same = Counter()
dump = []  # every pair with the rules' answer, saved for the model stage (kaggle/activities_llm)
for x, y, truth, what in pairs:
    r = relate(parse_activity(x, gazetteer=gaz), parse_activity(y, gazetteer=gaz))
    pred = "INCLUDES" if r.relation in ("INCLUDES", "INCLUDED_IN") else r.relation
    dump.append((x, y, truth, what, pred, r.reason))
    conf[(truth, pred)] += 1
    if pred != truth and len(errors) < 400:
        errors.append((truth, pred, x, y, r.reason))
    # what a binary deduplicator would do with the same pair
    fz_same[(truth, fuzz.token_set_ratio(norm(clean(x)), norm(clean(y))) >= 85)] += 1

pd.DataFrame(dump, columns=["a", "b", "truth", "template", "rules_pred", "rules_reason"]).to_csv(
    ROOT / "data" / "interim" / "activity_pairs_insample.csv", index=False, encoding="utf-8")
f1 = {}
for lab in LABELS:
    tp = conf[(lab, lab)]
    fp = sum(conf[(t, lab)] for t in LABELS if t != lab)
    fn = sum(conf[(lab, p)] for p in LABELS if p != lab)
    pr, rc = tp / max(tp + fp, 1), tp / max(tp + fn, 1)
    f1[lab] = {"precision": pr, "recall": rc, "f1": 2 * pr * rc / max(pr + rc, 1e-9), "n": tp + fn}
macro = float(np.mean([v["f1"] for v in f1.values()]))
acc = sum(conf[(lab, lab)] for lab in LABELS) / len(pairs)
dedup = {lab: fz_same[(lab, True)] / max(fz_same[(lab, True)] + fz_same[(lab, False)], 1) for lab in LABELS}

# ---------------------------------------------------------------- real products at one location: what the function says (unlabelled)
P["cell"] = P["lat"].round(3).astype(str) + "," + P["lon"].round(3).astype(str)
real = []
for _, g in P.groupby("cell"):
    rows = list(g.itertuples())
    for i in range(len(rows)):
        for j in range(i + 1, len(rows)):
            r = relate(parsed[rows[i].id], parsed[rows[j].id])
            real.append((rows[i].title, rows[j].title, r.relation, ", ".join(r.diff)))
real_counts = Counter(r[2] for r in real)

# ---------------------------------------------------------------- real options inside one product
opt_rel = Counter()
opt_ex = []
for pid, g in O[O["product_id"].isin(P["id"])].groupby("product_id"):
    title = P.loc[P["id"] == pid, "title"].iloc[0]
    os_ = list(g["option"])
    for i in range(len(os_)):
        for j in range(i + 1, len(os_)):
            r = relate(parse_activity(title, os_[i], gazetteer=gaz), parse_activity(title, os_[j], gazetteer=gaz))
            opt_rel[r.relation] += 1
            if len(opt_ex) < 60:
                opt_ex.append((clean(title), os_[i], os_[j], r.relation, ", ".join(r.diff)))
pol = Counter(parse_policy(t)["klass"] for t in P["policy"])

out = {"products": len(P), "gazetteer_names": len(gaz.names), "anchored_by_name": anchored, "multi_attraction_titles": multi,
       "synthetic_pairs": len(pairs), "accuracy": acc, "macro_f1": macro, "per_class": f1,
       "confusion": {f"{t}->{p}": conf[(t, p)] for t in LABELS for p in LABELS if conf[(t, p)]},
       "binary_dedup_would_merge": dedup, "real_same_location_pairs": dict(real_counts), "real_option_pairs": dict(opt_rel), "policy_classes": dict(pol)}
(REP / "activities.json").write_text(json.dumps(out, indent=1), encoding="utf-8")

pc = lambda x: f"{x:.1%}"  # noqa: E731
M = ["# Sightseeing: typed relations between products", "",
     "Generated by `scripts/train/activities_benchmark.py`. Parser and relation function: `canon/activities.py` (deterministic, no model calls).", "",
     "## Setup", "",
     f"- **Real**: {len(P)} Klook Singapore products with coordinates, and a gazetteer of {len(gaz.names):,} Singapore attraction names taken from "
     "Wikidata, Wikivoyage and OpenStreetMap (the open POI layer; no Klook text went into it).",
     f"- The gazetteer finds at least one attraction in **{anchored} of {len(P)}** product titles ({pc(anchored / len(P))}); {multi} titles name two or more (combos).",
     f"- **Synthetic second supplier**: {len(pairs)} pairs, each a real product against a rewritten listing with a known relation.", "",
     "## Result on the synthetic second supplier", "",
     f"Accuracy **{pc(acc)}**, macro-F1 **{macro:.3f}** over four relation types.", "",
     "| Relation | Pairs | Precision | Recall | F1 |", "|---|---:|---:|---:|---:|"]
M += [f"| {lab} | {v['n']} | {pc(v['precision'])} | {pc(v['recall'])} | {v['f1']:.3f} |" for lab, v in f1.items()]
M += ["", "Confusion (rows: truth, columns: predicted):", "", "| | " + " | ".join(LABELS) + " |", "|---|" + "---:|" * len(LABELS)]
M += [f"| {t} | " + " | ".join(str(conf[(t, p)]) for p in LABELS) + " |" for t in LABELS]
M += ["", "### What a binary deduplicator does with the same pairs", "",
      "A string matcher can only say *same* or *not same*. Share of each true relation it would merge (token-set similarity >= 85):", "",
      "| True relation | Merged as duplicates |", "|---|---:|"]
M += [f"| {lab} | {pc(dedup[lab])} |" for lab in LABELS]
M += ["", f"It merges {pc(dedup['VARIANT_OF'])} of variants and {pc(dedup['INCLUDES'])} of combos into the base product, which loses the pickup, the meal or the second "
      "attraction. That is the difference the statement asks to keep.", "",
      "### Errors", ""]
ec = Counter((t, p) for t, p, *_ in errors)
M += [f"- {t} predicted as {p}: {c}" for (t, p), c in ec.most_common(6)]
M += ["", "| Truth | Predicted | Original | Second supplier | Reason given |", "|---|---|---|---|---|"]
shown = set()
for t, p, x, y, why in errors:
    if (t, p) not in shown or len(shown) >= 6:
        M.append(f"| {t} | {p} | {x} | {y} | {why} |")
        shown.add((t, p))
    if len(M) > 200:
        break
M += ["", "## Real Klook data, unlabelled", "",
      f"**Products at the same location** ({len(real)} pairs of real products within about 100 m): " + ", ".join(f"{k} {v}" for k, v in real_counts.most_common()) + ".", "",
      "| Product A | Product B | Relation | Difference |", "|---|---|---|---|"]
M += [f"| {a} | {b} | {r} | {d} |" for a, b, r, d in real[:18]]
M += ["", f"**Options inside one product** ({sum(opt_rel.values())} pairs of real sibling options): " + ", ".join(f"{k} {v}" for k, v in opt_rel.most_common()) + ".", "",
      "| Product | Option A | Option B | Relation | Difference |", "|---|---|---|---|---|"]
M += [f"| {t} | {a} | {b} | {r} | {d} |" for t, a, b, r, d in opt_ex[:16]]
M += ["", "These two tables are the function's output on real strings with nobody's labels attached; read them as a preview and a to-do list, not as a score.", "",
      "## Cancellation policy parser", "", "| Class | Products |", "|---|---:|"]
M += [f"| {k} | {v} |" for k, v in pol.most_common()]
M += ["", "## Reading the numbers", "",
      "- The four-way score is on a **synthetic second supplier**. It shows the mechanism (attraction set + attribute diff) separates the four relations where "
      "string similarity cannot; it is not accuracy on two real suppliers.",
      "- **The score is in-sample.** The relation rules were adjusted after reading the errors on this same set (first run: accuracy 85.1%, macro-F1 0.820, "
      "with combos under-detected). There is no held-out set yet, so expect a lower number on fresh data.",
      "- Real cross-supplier evaluation needs a second real source for the same city. Viator's free Basic Access API is the planned one.",
      "- Sibling options that come out as `SAME_AS` are the lexicon's blind spots (differences it has no word for); they are the queue for the model stage."]
(REP / "activities.md").write_text("\n".join(M) + "\n", encoding="utf-8")
print(json.dumps({k: out[k] for k in ("products", "gazetteer_names", "anchored_by_name", "multi_attraction_titles", "synthetic_pairs", "accuracy", "macro_f1")}, indent=1))
print("confusion", out["confusion"])
print("dedup merges", {k: round(v, 3) for k, v in dedup.items()})
print("real same-location", dict(real_counts), "| options", dict(opt_rel), "| policy", dict(pol))
