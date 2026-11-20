"""Rule-based benches with literal explanations: room / rate strings (canon.rooms) and tour titles (canon.activities).

Each answer lists the lexicon rules that fired, the text each matched and where (from the parsers' `trace` argument, which
only observes). Room strings are also aligned back to the raw tokens the visitor typed (raw token -> normalised tokens
through the ABBREV table); when that alignment cannot be reproduced exactly, tokens are given without raw positions.
"""
from __future__ import annotations

import re
import threading
import unicodedata

from canon.activities import Gazetteer, norm as anorm, parse_activity, relate
from canon.rooms import ABBREV, STOP, normalise, parse_room

from . import UserError
from .artefacts import CITY_ORDER
from .presets import CITY_LABEL, PRESETS

RATE_GROUPS = {"BOARD", "REFUND", "INCLUSIONS", "PROMO"}
NOT_IN_SIGNATURE = {"SIZE", "OCCUPANCY"} | RATE_GROUPS
SIGNATURE_FIELDS = ["room_type", "room_class", "beds", "multi_bed_count", "bedrooms", "view", "features", "name_tokens"]
MAX_LINES, MAX_CHARS = 200, 300


# ============================================================================ rooms: raw <-> normalised alignment
def _sub(pattern: str, repl: str, s: str, org: list):
    out, oorg, last = [], [], 0
    for m in re.finditer(pattern, s):
        out.append(s[last:m.start()])
        oorg += org[last:m.start()]
        seg = org[m.start():m.end()]
        span = (min(o[0] for o in seg), max(o[1] for o in seg))
        out.append(repl)
        oorg += [span] * len(repl)
        last = m.end()
    out.append(s[last:])
    oorg += org[last:]
    return "".join(out), oorg


def align_room_text(text: str):
    """Reproduce canon.rooms.normalise step by step, tracking where each character came from.

    Returns [(raw_start, raw_end, [(norm_token, norm_start, norm_end), ...]), ...] per pre-expansion token, or None when the
    step-by-step result differs from normalise(text) (then the caller reports tokens without raw positions).
    """
    chars, org = [], []
    for i, ch in enumerate(text):
        piece = "".join(c for c in unicodedata.normalize("NFKD", ch.lower()) if not unicodedata.combining(c))
        chars.append(piece)
        org += [(i, i)] * len(piece)
    s = "".join(chars)
    ref = "".join(c for c in unicodedata.normalize("NFKD", text.lower()) if not unicodedata.combining(c))
    if s != ref:
        return None
    for old, new in (("a/c", "ac"), ("w/", "with "), ("&", " and "), ("+", " and ")):
        s, org = _sub(re.escape(old), new, s, org)
    s, org = _sub(r"non[\s-]*a\s*c\b", "nonac", s, org)
    s, org = _sub(r"[^a-z0-9 ]+", " ", s, org)
    groups, words, pos = [], [], 0
    for m in re.finditer(r"\S+", s):
        seg = org[m.start():m.end()]
        expanded = ABBREV.get(m.group(0), m.group(0)).split()
        toks = []
        for w in expanded:
            if words:
                pos += 1
            toks.append((w, pos, pos + len(w)))
            words.append(w)
            pos += len(w)
        groups.append((min(o[0] for o in seg), max(o[1] for o in seg) + 1, toks))
    if " ".join(words) != normalise(text):
        return None
    return groups


def _rule(e: dict) -> str:
    return f"{e['group']} {e['pattern']}"


def _fired(e: dict, align) -> dict:
    out = {"side": "rate" if e["group"] in RATE_GROUPS else "room", "group": e["group"], "attr": e["attr"], "value": e["value"],
           "rule": _rule(e), "matched": e["matched"], "start": e["start"], "end": e["end"], "in_signature": e["group"] not in NOT_IN_SIGNATURE}
    for k in ("bed_count", "note"):
        if k in e:
            out[k] = e[k]
    if align and e["start"] is not None:
        raw = [(a, b) for a, b, toks in align if any(ns >= e["start"] and ne <= e["end"] for _, ns, ne in toks)]
        if raw:
            out["raw_start"], out["raw_end"] = min(a for a, _ in raw), max(b for _, b in raw)
    return out


def _token_view(word: str, ns: int, ne: int, trace: list) -> dict:
    for e in trace:
        if e["start"] is not None and e["start"] <= ns and ne <= e["end"]:
            return {"side": "rate" if e["group"] in RATE_GROUPS else "room", "attr": e["attr"], "value": e["value"], "rule": _rule(e)}
    if word in STOP or word.isdigit():
        return {"side": "stop", "attr": None, "value": None, "rule": "STOP word or bare number: dropped"}
    return {"side": "left", "attr": "name_tokens", "value": word, "rule": "left over: kept as part of the room's identity"}


def room_view(text: str) -> dict:
    if not isinstance(text, str) or not text.strip():
        raise UserError("Send a room string in \"text\".")
    if len(text) > MAX_CHARS:
        raise UserError(f"Room strings are limited to {MAX_CHARS} characters.")
    trace: list = []
    p = parse_room(text, trace=trace)
    normalised = normalise(text)
    align = align_room_text(text)
    tokens = []
    if align:
        for a, b, toks in align:
            parts = [{"norm": w, "start": ns, "end": ne, **_token_view(w, ns, ne, trace)} for w, ns, ne in toks]
            main = next((x for x in parts if x["side"] in ("room", "rate")), parts[0])
            tok = {"raw": text[a:b], "start": a, "end": b, "norm": [x["norm"] for x in parts], "side": main["side"], "attr": main["attr"],
                   "value": main["value"], "rule": main["rule"]}
            if len({(x["side"], x["rule"]) for x in parts}) > 1:
                tok["parts"] = parts
            tokens.append(tok)
    else:
        pos = 0
        for w in normalised.split():
            ns = normalised.index(w, pos)
            pos = ns + len(w)
            tokens.append({"raw": None, "start": None, "end": None, "norm": [w], **_token_view(w, ns, pos, trace)})
    sig = p.signature()
    return {"raw": text, "normalised": normalised, "aligned": align is not None, "tokens": tokens,
            "fired": [_fired(e, align) for e in trace], "room": p.room_dict(), "rate": p.rate_dict(),
            "signature": list(sig), "signature_fields": SIGNATURE_FIELDS, "confidence": p.confidence, "residual": p.residual}


def rooms_map(a_lines, b_lines) -> list:
    for nm, xs in (("a", a_lines), ("b", b_lines)):
        if not isinstance(xs, list) or not all(isinstance(x, str) for x in xs):
            raise UserError(f"\"{nm}\" must be a list of room strings.")
        if len(xs) > MAX_LINES:
            raise UserError(f"At most {MAX_LINES} lines per side.")
    a_lines = [x for x in a_lines if x.strip()]
    sig_a = [parse_room(x).signature() for x in a_lines]
    out = []
    for line in b_lines:
        if not line.strip():
            continue
        v = room_view(line)
        sig = parse_room(line).signature()
        hits = [j for j, sg in enumerate(sig_a) if sg == sig]  # same rule as rooms_benchmark.py / build_demo_data.py: a unique signature maps
        if len(hits) == 1:
            why = "unique signature match"
        elif len(hits) > 1:
            why = f"{len(hits)} rooms share this signature"
        elif v["confidence"] < 0.5:
            why = "low confidence"
        else:
            why = "no room with this signature"
        out.append({"text": line, "parsed": v, "match": hits[0] if len(hits) == 1 else None, "why": why, "hits": hits})
    return out


# ============================================================================ tours: gazetteer per city (build_demo_data.py)
SUFFIX = {"singapore": "singapore|sentosa", "delhi": "new delhi|delhi"}
GENERIC = {"singapore": {"singapore", "sentosa", "marina bay", "orchard road", "chinatown", "little india", "the garden", "city hall"}}
_gaz: dict = {}
_gaz_lock = threading.Lock()


def gazetteer(city: str) -> Gazetteer:
    """Attraction names of one city, built exactly as build_demo_data.py builds Singapore's (other cities: the city's own name
    is the place word stripped from the end of names and the one generic name excluded)."""
    city = (city or "singapore").lower()
    if city not in CITY_ORDER:
        raise UserError(f"No gazetteer for {city!r}. Cities: {', '.join(CITY_ORDER)}.", status=404)
    with _gaz_lock:
        if city in _gaz:
            return _gaz[city]
    L = PRESETS.raw_listings()
    L = L[(L["city"] == city) & (L["kind"] == "attraction")]
    keep = (L["source"].isin(["wikidata", "wikivoyage"]) | ((L["source"] == "osm") & L["category"].fillna("").str.contains(
        r"tourism=(?:attraction|museum|theme_park|zoo|aquarium|gallery|viewpoint)|leisure=water_park")))
    names = set(L.loc[keep, "name"].dropna())
    suffix = SUFFIX.get(city, re.escape(CITY_LABEL[city].lower()))
    names |= {re.sub(rf"(?i)[ ,]+({suffix})$", "", n).strip() for n in names}
    generic = GENERIC.get(city, {anorm(CITY_LABEL[city])})
    g = Gazetteer([n for n in names if anorm(n) not in generic])
    with _gaz_lock:
        _gaz[city] = g
    return g


def _activity_view(text: str, gaz: Gazetteer) -> dict:
    trace: list = []
    a = parse_activity(text, gazetteer=gaz, trace=trace)
    fired = [{"attr": e["attr"], "value": e["value"], "matched": e["matched"], "rule": f"{e['group']} {e['pattern']}", "group": e["group"],
              "start": e["start"], "end": e["end"], "where": e.get("where", "normalised")} for e in trace]
    return {"raw": a.raw, "normalised": anorm(re.sub(r"\[[^\]]+\]", " ", a.raw)), "attractions": sorted(a.attractions),
            "attraction_names": [gaz.display.get(k, k) for k in sorted(a.attractions)], "experience": a.experience, "access": a.access,
            "inclusions": sorted(a.inclusions), "age_band": a.age_band, "group": a.group, "resident_only": a.resident_only,
            "time_window": list(a.time_window), "duration_min": a.duration_min, "is_combo_worded": a.is_combo_worded,
            "promo_tags": list(a.promo_tags), "core_tokens": sorted(a.core_tokens), "confidence": a.confidence, "fired": fired}


def tours_relate(a: str, b: str, city: str | None) -> dict:
    for nm, x in (("a", a), ("b", b)):
        if not isinstance(x, str) or not x.strip():
            raise UserError(f"Send a product title in \"{nm}\".")
        if len(x) > MAX_CHARS:
            raise UserError(f"Titles are limited to {MAX_CHARS} characters.")
    gaz = gazetteer(city or "singapore")
    va, vb = _activity_view(a, gaz), _activity_view(b, gaz)
    r = relate(parse_activity(a, gazetteer=gaz), parse_activity(b, gazetteer=gaz))
    return {"a": va, "b": vb, "relation": r.relation, "diff": list(r.diff), "reason": r.reason,
            "gazetteer": {"city": (city or "singapore").lower(), "names": len(gaz.names),
                          "built_from": "Wikidata, Wikivoyage and OSM visitor attractions of the city (open data; no Klook text)"}}
