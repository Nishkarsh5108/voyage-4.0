"""Room mapping benchmark: real hotel room lists, synthetic second-supplier renamings.

For every hotel in the Booking.com review set, the real room names are "supplier A". Six surface rewrites imitate how
other suppliers name the same rooms (bedbank abbreviations, rate terms glued on, comma style, noise, synonyms, codes).
Task: map each rewritten string back to the right room of the same hotel, or abstain. Sibling rooms of the same hotel
("Deluxe Double" vs "Executive Deluxe Double") are the distractors, so string similarity is tested where it is weakest.

The rewrite rules live here and share no code with canon/rooms.py. They are still written by the same author, so the
result is a *synthetic-supplier* number: it shows the mechanism works, not accuracy on TBO feeds.

Input : data/interim/room_strings.parquet (scripts/eda/eda_rooms.py), raw MakeMyTrip / Goibibo csv
Output: reports/models/rooms.{md,json}
Usage : python -I scripts/train/rooms_benchmark.py
"""
import json
import random
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np
import pandas as pd
from rapidfuzz import fuzz

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts" / "eda"))
from canon.rooms import parse_room  # noqa: E402
from common import SERIES, plt  # noqa: E402

REP = ROOT / "reports" / "models"
(REP / "figures" / "rooms").mkdir(parents=True, exist_ok=True)
rnd = random.Random(7)
R = pd.read_parquet(ROOT / "data" / "interim" / "room_strings.parquet")
R = R[R["room"].str.len() > 2].reset_index(drop=True)

# ============================================================================ 1. parser coverage on real strings
uniq = R.groupby("room")["n"].sum().sort_values(ascending=False)
parsed = {s: parse_room(s) for s in uniq.index}
w = uniq.to_numpy()


def share(pred):
    m = np.array([pred(parsed[s]) for s in uniq.index])
    return float(m.mean()), float((m * w).sum() / w.sum())


cov = {
    "bed type found": share(lambda p: bool(p.beds)),
    "class found": share(lambda p: bool(p.room_class)),
    "non-default room type (suite, apartment, ...)": share(lambda p: p.room_type != "room"),
    "view found": share(lambda p: p.view is not None),
    "any feature (balcony, terrace, accessible, ...)": share(lambda p: bool(p.features)),
    "rate or package term split off": share(lambda p: bool(p.board or p.refundable is not None or p.inclusions or p.promo)),
    "fully understood (no leftover tokens)": share(lambda p: p.residual == ""),
    "confident (score >= 0.8)": share(lambda p: p.confidence >= 0.8),
    "needs the model stage (score < 0.5)": share(lambda p: p.confidence < 0.5),
}
left = Counter()
for s in uniq.index:
    for t in parsed[s].name_tokens:
        left[t] += 1

# Indian OTA strings
ind = []
for f, col in (("makemytrip_hotels/makemytrip_com-travel_sample.csv", "room_types"), ("goibibo_hotels/goibibo_com-travel_sample.csv", "room_type")):
    d = pd.read_csv(ROOT / "data" / "raw" / f, usecols=[col], dtype=str, on_bad_lines="skip")[col].dropna().str.strip()
    ind += list(d[d.str.len() > 2].unique())
ind = sorted(set(ind))
pi = [parse_room(s) for s in ind]
cov_ind = {"strings": len(ind), "class or bed or type found": float(np.mean([bool(p.beds or p.room_class or p.room_type != "room") for p in pi])),
           "AC / non-AC found": float(np.mean([("ac" in p.features or "non_ac" in p.features) for p in pi])),
           "confident (score >= 0.8)": float(np.mean([p.confidence >= 0.8 for p in pi])),
           "needs the model stage (score < 0.5)": float(np.mean([p.confidence < 0.5 for p in pi]))}

# ============================================================================ 2. what the signature merges inside real hotels
hotels = {h: list(g["room"]) for h, g in R.groupby("hotel")}
coll = Counter()
coll_ex = defaultdict(list)
n_pairs_same = 0
for h, rooms in hotels.items():
    by_sig = defaultdict(list)
    for r_ in rooms:
        by_sig[parsed[r_].signature()].append(r_)
    for sig, rs in by_sig.items():
        if len(rs) > 1:
            for i in range(len(rs)):
                for j in range(i + 1, len(rs)):
                    a, b = parsed[rs[i]], parsed[rs[j]]
                    n_pairs_same += 1
                    kind = ("rate / package / promotion differs" if a.rate_dict() != b.rate_dict() else
                            "occupancy wording differs" if a.occupancy != b.occupancy else
                            "bed count wording differs" if a.bed_count != b.bed_count else "formatting only")
                    coll[kind] += 1
                    if len(coll_ex[kind]) < 4:
                        coll_ex[kind].append((h, rs[i], rs[j]))

# ============================================================================ 3. synthetic second-supplier rewrites (independent of the parser)
GEN_ABBR = [("double or twin", "DBL/TWN"), ("junior suite", "JR STE"), ("sea view", "SV"), ("city view", "CV"), ("garden view", "GV"),
            ("pool view", "PV"), ("mountain view", "MV"), ("double", "DBL"), ("twin", "TWN"), ("single", "SGL"), ("triple", "TPL"),
            ("quadruple", "QUAD"), ("deluxe", "DLX"), ("standard", "STD"), ("superior", "SUP"), ("executive", "EXEC"), ("suite", "STE"),
            ("apartment", "APT"), ("balcony", "BALC"), ("bedroom", "BDRM"), ("rooms", ""), ("room", ""), ("with", ""), ("and", "&")]
BOARDS = [("Breakfast Included", "BB"), ("Room Only", "RO"), ("Half Board", "HB"), ("Bed and Breakfast", "BB"), ("Full Board", "FB")]
REFUNDS = [("Non Refundable", False), ("Free Cancellation", True)]
BEDS = ["double or twin", "double", "twin", "king", "queen", "single", "triple", "quadruple"]


def s_abbrev(s):
    t = s.lower()
    for k, v in GEN_ABBR:
        t = re.sub(rf"\b{k}\b", v, t)
    return re.sub(r"\s+", " ", t).strip().upper(), None, None


def s_rate(s):
    b, r_ = rnd.choice(BOARDS), rnd.choice(REFUNDS + [None])
    return s + " - " + b[0] + ((" - " + r_[0]) if r_ else ""), b[1], (r_[1] if r_ else None)


def s_comma(s):
    head, _, tail = s.partition(" with ")
    low = head.lower()
    bed = next((b for b in BEDS if re.search(rf"\b{b}\b", low)), None)
    if bed:
        head = re.sub(rf"(?i)\b{bed}\b", "", head)
        head = re.sub(r"\s+", " ", head).strip() + ", " + bed.title()
    return head + ((", " + tail) if tail else ""), None, None


def s_noise(s):
    t = re.sub(r" with (.+)$", r" (\1)", s)
    t = re.sub(r"\bRoom\b", "Rm", t)
    t = t.replace(" or ", "/").replace(" and ", " & ")
    return (t.upper() if rnd.random() < 0.5 else t.lower()).replace(" ", "  ", 1), None, None


def s_synonym(s):
    t = s
    t = re.sub(r"\bDouble or Twin\b", "Twin/Double", t)
    t = re.sub(r"\b(Sea|City|Garden|Pool) View\b", lambda m: m.group(1) + "view", t)
    t = re.sub(r"^(.*)\bKing Room\b", r"\1Room, 1 King Bed", t)
    t = re.sub(r"^(.*)\bTwin Room\b", r"\1Room, 2 Single Beds", t)
    t = re.sub(r"^(.*)\bDouble Room\b", r"\1Room with Double Bed", t)
    t = re.sub(r"\bApartment\b", "Apt", t).replace("Non-Smoking", "Non Smoking")
    return t, None, None


def s_codes(s):
    t, _, _ = s_abbrev(s)
    b, r_ = rnd.choice([("BB", "BB"), ("RO", "RO"), ("HB", "HB")]), rnd.choice([("NRF", False), None])
    return t + " " + b[0] + ((" " + r_[0]) if r_ else ""), b[1], (r_[1] if r_ else None)


STYLES = {"bedbank abbreviations": s_abbrev, "rate terms appended": s_rate, "comma style": s_comma, "case and punctuation noise": s_noise,
          "synonyms and bed phrasing": s_synonym, "abbreviations + rate codes": s_codes}


def base_norm(s):
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]+", " ", s.lower())).strip()


def m_exact(q, rooms):
    hits = [r_ for r_ in rooms if base_norm(r_) == base_norm(q)]
    return hits[0] if len(hits) == 1 else None


def m_fuzzy(q, rooms, scorer, thr):
    sc = sorted(((scorer(base_norm(q), base_norm(r_)), r_) for r_ in rooms), reverse=True)
    if sc[0][0] < thr or (len(sc) > 1 and sc[0][0] == sc[1][0]):
        return None
    return sc[0][1]


def m_parser(q, rooms):
    sig = parse_room(q).signature()
    hits = [r_ for r_ in rooms if parsed[r_].signature() == sig]
    return hits[0] if len(hits) == 1 else None


METHODS = {
    "exact string (normalised)": m_exact,
    "fuzzy token-set >= 90": lambda q, rs: m_fuzzy(q, rs, fuzz.token_set_ratio, 90),
    "fuzzy weighted ratio >= 90": lambda q, rs: m_fuzzy(q, rs, fuzz.WRatio, 90),
    "fuzzy token-sort >= 80": lambda q, rs: m_fuzzy(q, rs, fuzz.token_sort_ratio, 80),
    "attribute parser (canon.rooms)": m_parser,
}
res = {m_: {st: [0, 0, 0] for st in STYLES} for m_ in METHODS}  # mapped, correct, total
rate_ok, rate_n = 0, 0
changed = Counter()
errors = defaultdict(list)
QUERIES = []  # every renamed string with its hotel and true room, saved for other matchers (rooms_semantic_baseline.py)
for h, rooms in hotels.items():
    if len(rooms) < 2:
        continue
    for truth in rooms:
        for st, fn in STYLES.items():
            q, board, refund = fn(truth)
            changed[st] += int(base_norm(q) != base_norm(truth))
            QUERIES.append((h, st, q, truth))
            if board is not None and parsed[truth].board is None:
                pq = parse_room(q)
                rate_n += 1
                rate_ok += int(pq.board == board and (refund is None or parsed[truth].refundable is not None or pq.refundable == refund))
            for m_, f in METHODS.items():
                got = f(q, rooms)
                res[m_][st][2] += 1
                if got is not None:
                    res[m_][st][0] += 1
                    res[m_][st][1] += int(got == truth)
                    if got != truth and len(errors[m_]) < 6 and rnd.random() < 0.05:
                        errors[m_].append((q, got, truth))

pd.DataFrame(QUERIES, columns=["hotel", "style", "query", "truth"]).to_parquet(ROOT / "data" / "interim" / "rooms_bench_queries.parquet", index=False)
summary = {}
for m_ in METHODS:
    mp = sum(v[0] for v in res[m_].values()); ok = sum(v[1] for v in res[m_].values()); tot = sum(v[2] for v in res[m_].values())
    summary[m_] = {"coverage": mp / tot, "precision": ok / max(mp, 1), "correct_of_all": ok / tot,
                   "by_style": {st: {"coverage": v[0] / v[2], "precision": v[1] / max(v[0], 1)} for st, v in res[m_].items()}}
n_hotels = sum(1 for r_ in hotels.values() if len(r_) >= 2)
n_items = next(iter(res.values()))[next(iter(STYLES))][2]

# ============================================================================ report
fig, ax = plt.subplots(figsize=(8.0, 3.6))
names = list(METHODS)
y = np.arange(len(names))[::-1]
ax.barh(y + 0.19, [summary[m_]["precision"] * 100 for m_ in names], height=0.34, color=SERIES[0], label="precision of mapped")
ax.barh(y - 0.19, [summary[m_]["coverage"] * 100 for m_ in names], height=0.34, color=SERIES[1], label="coverage (share mapped)")
for i, m_ in enumerate(names):
    ax.text(summary[m_]["precision"] * 100 + 1, y[i] + 0.19, f"{summary[m_]['precision']:.1%}", va="center", fontsize=9, color="#52514e")
    ax.text(summary[m_]["coverage"] * 100 + 1, y[i] - 0.19, f"{summary[m_]['coverage']:.1%}", va="center", fontsize=9, color="#52514e")
ax.set_yticks(y, names); ax.set_xlim(0, 112); ax.grid(axis="y", visible=False); ax.set_xlabel("%")
ax.set_title("Mapping renamed rooms back to the right room of the same hotel"); ax.legend(loc="lower center", bbox_to_anchor=(0.5, 1.1), ncol=2)
fig.savefig(REP / "figures" / "rooms" / "methods.png"); plt.close(fig)

out = {"real_strings": len(uniq), "coverage_booking": {k: {"strings": a, "bookings": b} for k, (a, b) in cov.items()}, "coverage_india": cov_ind,
       "leftover_tokens_top": left.most_common(25), "same_signature_pairs": n_pairs_same, "same_signature_kinds": dict(coll),
       "benchmark": {"hotels": n_hotels, "rooms": n_items, "styles": list(STYLES), "methods": summary,
                     "rate_extraction": {"n": rate_n, "accuracy": rate_ok / max(rate_n, 1)}, "share_of_rewrites_that_changed_the_string": {k: v / n_items for k, v in changed.items()}}}
(REP / "rooms.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
pc = lambda x: f"{x:.1%}"  # noqa: E731
L = ["# Room and rate mapping: lexicon parser and synthetic-supplier benchmark", "",
     "Generated by `scripts/train/rooms_benchmark.py`. Parser: `canon/rooms.py` (deterministic, no model calls).", "",
     "## 1. Parser coverage on real room names", "",
     f"{len(uniq):,} distinct Booking.com room names from 1,492 European hotels, weighted by how often each was booked.", "",
     "| What the parser extracts | Share of distinct strings | Share of bookings |", "|---|---:|---:|"]
L += [f"| {k} | {pc(a)} | {pc(b)} |" for k, (a, b) in cov.items()]
L += ["", "Most common leftover tokens (kept as part of the room's identity, and the input to the model stage): "
      + ", ".join(f"`{t}` ({c})" for t, c in left.most_common(18)) + ".", "",
      f"Indian OTA strings ({cov_ind['strings']:,} distinct, MakeMyTrip + Goibibo): class, bed or type found in {pc(cov_ind['class or bed or type found'])}; "
      f"AC / non-AC in {pc(cov_ind['AC / non-AC found'])}; confident in {pc(cov_ind['confident (score >= 0.8)'])}; "
      f"{pc(cov_ind['needs the model stage (score < 0.5)'])} need the model stage.", "",
      "## 2. What the room signature merges inside real hotels", "",
      f"Across the hotels, **{n_pairs_same:,} pairs of different room names** in the same hotel get the same signature (room attributes equal once rate terms and "
      "occupancy wording are removed). By what differs between the two names:", "", "| Difference between the two names | Pairs |", "|---|---:|"]
L += [f"| {k} | {v:,} |" for k, v in coll.most_common()]
L += ["", "Examples:", "", "| Kind | Hotel | Name A | Name B |", "|---|---|---|---|"]
for k, exs in coll_ex.items():
    L += [f"| {k} | {h} | {a} | {b} |" for h, a, b in exs[:3]]
L += ["", "Rate-only differences are the intended merges (one room, two rate plans). Occupancy-only differences are one room sold at two occupancies, "
      "which belongs on the rate plan too. These are the pairs a string matcher keeps apart and a room/rate split puts together.", "",
      "## 3. Synthetic second-supplier benchmark", "",
      f"**{n_hotels:,} real hotels, {n_items:,} real rooms, six rewrite styles = {n_items * len(STYLES):,} renamed strings.** "
      "Each must be mapped to the right room of its own hotel or left unmapped. Rooms of the same hotel are the distractors.", "",
      "| Method | Coverage (share mapped) | Precision of mapped | Correct, as share of all |", "|---|---:|---:|---:|"]
L += [f"| {m_} | {pc(v['coverage'])} | {pc(v['precision'])} | {pc(v['correct_of_all'])} |" for m_, v in summary.items()]
L += ["", "![Precision and coverage by method](figures/rooms/methods.png)", "", "By rewrite style (coverage / precision):", "",
      "| Style | " + " | ".join(METHODS) + " |", "|---|" + "---:|" * len(METHODS)]
for st in STYLES:
    L.append(f"| {st} | " + " | ".join(f"{pc(summary[m_]['by_style'][st]['coverage'])} / {pc(summary[m_]['by_style'][st]['precision'])}" for m_ in METHODS) + " |")
L += ["", f"Rate extraction on the two styles that append rate terms: board basis and refundability recovered exactly in **{pc(rate_ok / max(rate_n, 1))}** of {rate_n:,} strings.", "",
      "Examples the fuzzy matchers get wrong (renamed string -> chosen room, true room):", ""]
for m_ in ("fuzzy token-set >= 90", "fuzzy weighted ratio >= 90"):
    L += [f"- `{q}` -> *{got}* (true: *{truth}*)" for q, got, truth in errors[m_][:3]]
if errors["attribute parser (canon.rooms)"]:
    L += ["", "Parser errors:", ""] + [f"- `{q}` -> *{got}* (true: *{truth}*)" for q, got, truth in errors["attribute parser (canon.rooms)"][:5]]
L += ["", "## Reading the numbers", "",
      "- This is a **synthetic-supplier** result: the room lists and names are real, the second supplier is simulated by rewrite rules. "
      "It shows that attribute extraction survives abbreviation, re-ordering and glued-on rate terms where string similarity does not. "
      "It is not a measurement on TBO feeds; that needs real second-supplier room lists (Hotelbeds test keys, or a TBO sandbox).",
      "- Unmapped strings are the precision-first design at work: when two rooms of a hotel share a signature, or the parser leaves tokens over, the string "
      "goes to the model stage instead of being guessed.",
      "- Next: an LLM extraction stage for strings below the confidence bar, cached per unique string; then the price-band sanity check once offers exist."]
(REP / "rooms.md").write_text("\n".join(L) + "\n", encoding="utf-8")
print(json.dumps({m_: {k: round(v[k], 4) for k in ("coverage", "precision", "correct_of_all")} for m_, v in summary.items()}, indent=1))
print("rate extraction", rate_ok, rate_n, "| same-signature pairs", n_pairs_same, dict(coll))
print("wrote reports/models/rooms.md")
