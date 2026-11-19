"""Sightseeing products: attribute extraction and typed relations between two products or options.

A product is not just "the same" or "different" from another supplier's product. This module answers with one of

    SAME_AS      same attractions, same experience, same key attributes        -> one card, several offers
    VARIANT_OF   same attractions; differs only in whitelisted attributes      -> one family, difference chips
    INCLUDES     A covers every attraction of B and at least one more (combo)  -> separate card, "also includes"
    INCLUDED_IN  the reverse
    DIFFERENT    anything else

Deterministic lexicon stage only (no model calls). `ActivityAttrs.confidence` flags strings for the model stage.

    >>> g = Gazetteer(["Singapore Flyer", "Gardens by the Bay"])
    >>> a = parse_activity("Singapore Flyer Ticket", gazetteer=g)
    >>> b = parse_activity("[Sale] Singapore Flyer Admission with Hotel Pickup", gazetteer=g)
    >>> relate(a, b).relation, relate(a, b).diff
    ('VARIANT_OF', ('+ transfer',))
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

from canon._trace import SpanTrace


def norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", (s or "").lower())
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = s.replace("&", " and ").replace("+", " plus ").replace("™", " ").replace("®", " ")
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]+", " ", s)).strip()


# ----------------------------------------------------------------------------- lexicon
PROMO = r"(klook exclusive|exclusive|online exclusive|limited offer|special promo|promo|sale|\d+ ?(percent|%) off|up to \d+ ?(percent|%)? ?off|discounted|discount|early bird|buy \d get \d|free gift|best seller|new|hot deal|flash deal|instant confirmation|e ?ticket|mobile ticket|open date(d)?)"
ACCESS = [(r"(skip the line|skip the queue|fast track|fast pass|priority (entry|access|pass)|direct entry|no queue)", "skip_the_line"),
          (r"express( unlimited)?( pass)?", "express"), (r"(vip|premium|premier|first class)", "vip"), (r"unlimited", "unlimited")]
INCLUSIONS = [(r"(hotel )?(pick ?up|drop ?off|transfers?|shuttle|round ?trip transport(ation)?|hotel delivery)", "transfer"),
              (r"(lunch|dinner|breakfast|buffet|meal|set menu|high tea|afternoon tea|bbq)", "meal"),
              (r"(drink|beverage|cocktail|coffee|ice cream|snack|toast|popcorn)", "snack_or_drink"),
              (r"(guided|with guide|tour guide|audio guide|guide)", "guide"),
              (r"(souvenir|luggage tag|gift|photo|cash voucher|voucher|coupon)", "extra"),
              (r"(tram ride|boat ride|cable car ride|ride)", "ride")]
AGE = [(r"(child(ren)?|kids?|junior)", "child"), (r"(senior|elderly)", "senior"), (r"(student|youth)", "student"), (r"(infant|toddler)", "infant"), (r"adults?", "adult")]
GROUP = [(r"private", "private"), (r"(shared|join in|joined|group of \d+)", "shared")]
RESIDENT = r"(mykad|malaysian|local resident|resident|singaporean|non malaysian|foreigner|international)"
TIME = [(r"(\d{1,2}(:| )?\d{0,2} ?(am|pm))( entry| slot| session| show)?", "slot"), (r"(morning|afternoon|evening|night|sunset|sunrise|day ?time)", "daypart"),
        (r"(weekday|weekend|peak|off peak|non peak|public holiday|school holiday)", "peak"),
        (r"valid (from|until|till|on) [a-z0-9 ]+", "validity")]
EXPERIENCE = [(r"(day trip|day tour|excursion)", "day_trip"), (r"(walking tour|city tour|sightseeing tour|bus tour|tour)", "tour"),
              (r"(cruise|boat|yacht|ferry)", "cruise"), (r"(show|concert|performance|musical)", "show"),
              (r"(airport transfer|car charter|car rental|sim card|wifi)", "transport_or_utility"),
              (r"(multi attraction|attractions pass|city pass|flexi pass|pass)", "pass"),
              (r"(admission|entry|entrance|ticket|tickets)", "ticket")]
COMBO_WORDS = r"(combo|bundle|package|plus| and | with )"
STOP = set("in at the a an of for to on by and with plus or ticket tickets admission entry entrance package combo bundle pass day one two 1 2 3 "
           "singapore malaysia kuala lumpur dubai bangkok sentosa city island experience visit including included include only".split())


class Gazetteer:
    """Known attraction names for a city; finds which of them a product text mentions (longest name first)."""

    def __init__(self, names):
        seen = {}
        for n in names:
            k = norm(n)
            if len(k) >= 6 and (len(k.split()) >= 2 or len(k) >= 9):
                seen.setdefault(k, n)
        self.names = sorted(seen, key=len, reverse=True)
        self.display = seen

    def find(self, text: str):
        """Return (frozenset of attraction keys found, text with those mentions removed)."""
        s, found = f" {text} ", []
        for k in self.names:
            if f" {k} " in s:
                found.append(k)
                s = s.replace(f" {k} ", " | ")
        return frozenset(found), s.strip()


@dataclass
class ActivityAttrs:
    raw: str
    attractions: frozenset = frozenset()
    experience: str = "ticket"
    access: str = "standard"
    inclusions: frozenset = frozenset()
    age_band: str | None = None
    group: str | None = None
    resident_only: bool = False
    time_window: tuple = ()
    duration_min: int | None = None
    is_combo_worded: bool = False
    promo_tags: tuple = ()
    core_tokens: frozenset = frozenset()
    confidence: float = 0.0
    extras: dict = field(default_factory=dict, repr=False)


def _take(s: str, pattern: str):
    m = re.search(rf"(?<![a-z0-9])(?:{pattern})(?![a-z0-9])", s)
    if not m:
        return None, s
    return m, s[:m.start()] + " " + s[m.end():]


HOURS_PAT, MINUTES_PAT, DAYS_PAT = r"(\d+(\.\d+)?) ?(hours?|hrs?|h)", r"(\d+) ?(minutes?|mins?)", r"(\d+) ?days?"


def _gazetteer_shadow(tr: SpanTrace, gazetteer: Gazetteer, s: str, found_s: str) -> None:
    """Follow Gazetteer.find's edits (pad, replace each name with ' | ', strip) with the position map; record each name found."""
    if tr.pos is None:
        return
    t, pos = f" {s} ", [-1] + tr.pos + [-1]
    for k in gazetteer.names:
        sub = f" {k} "
        if sub not in t:
            continue
        out, opos, i = [], [], 0
        while True:  # str.replace semantics: non-overlapping, left to right
            j = t.find(sub, i)
            if j < 0:
                break
            out.append(t[i:j])
            opos += pos[i:j]
            idx = [q for q in pos[j + 1:j + 1 + len(k)] if q >= 0]
            tr.out.append({"group": "GAZETTEER", "attr": "attractions", "value": gazetteer.display.get(k, k), "pattern": k, "matched": k,
                           "start": min(idx) if idx else None, "end": max(idx) + 1 if idx else None})
            out.append(" | ")
            opos += [-1, -1, -1]
            i = j + len(sub)
        out.append(t[i:])
        opos += pos[i:]
        t, pos = "".join(out), opos
    lead = len(t) - len(t.lstrip())
    stripped = t.strip()
    tr.pos = pos[lead:lead + len(stripped)] if stripped == found_s else None


def parse_activity(title: str, option: str | None = None, gazetteer: Gazetteer | None = None, trace: list | None = None) -> ActivityAttrs:
    """Parse a product title, optionally with one of its option names, into comparable attributes.

    trace: optional list. When given, one dict per rule that fired is appended (group, attr, value, pattern, matched text and
    its [start, end) span in the normalised title, i.e. `norm` of the title with [bracket tags] removed; bracket tags are
    reported with their span in the raw title and `where: "raw"`). Tracing only observes: the result is the same without it.
    """
    a = ActivityAttrs(raw=title if not option else f"{title} :: {option}")
    tags = [norm(t) for t in re.findall(r"\[([^\]]+)\]", a.raw)]
    s = norm(re.sub(r"\[[^\]]+\]", " ", a.raw))
    tr = SpanTrace(s, trace) if trace is not None else None
    if tr is not None:
        for mt in re.finditer(r"\[([^\]]+)\]", a.raw):
            tr.out.append({"group": "TAG", "attr": "promo_tags", "value": norm(mt.group(1)), "pattern": r"\[...\]", "matched": mt.group(0),
                           "start": mt.start(), "end": mt.end(), "where": "raw"})
    n_tok = max(len(s.split()), 1)
    promo = list(tags)
    while True:
        m, s = _take(s, PROMO)
        if not m:
            break
        promo.append(m.group(0))
        if tr is not None:
            tr.hit(m, "PROMO", "promo_tags", m.group(0), PROMO)
    a.promo_tags = tuple(sorted(set(promo)))
    tag_text = " ".join(tags)
    if gazetteer:
        before = s
        a.attractions, s = gazetteer.find(s)
        if tr is not None:
            _gazetteer_shadow(tr, gazetteer, before, s)
    a.is_combo_worded = bool(re.search(COMBO_WORDS, f" {s} ")) or len(a.attractions) > 1
    if tr is not None and a.is_combo_worded:
        mc = re.search(COMBO_WORDS, f" {s} ")
        tr.note("COMBO_WORDS", "is_combo_worded", True, COMBO_WORDS, mc.group(0).strip() if mc else f"{len(a.attractions)} attractions")

    m, s = _take(s, HOURS_PAT)
    if m:
        a.duration_min = int(float(m.group(1)) * 60)
        if tr is not None:
            tr.hit(m, "DURATION", "duration_min", a.duration_min, HOURS_PAT)
    else:
        m, s = _take(s, MINUTES_PAT)
        if m:
            a.duration_min = int(m.group(1))
            if tr is not None:
                tr.hit(m, "DURATION", "duration_min", a.duration_min, MINUTES_PAT)
        else:
            m, s = _take(s, DAYS_PAT)
            if m:
                a.duration_min = int(m.group(1)) * 24 * 60
                if tr is not None:
                    tr.hit(m, "DURATION", "duration_min", a.duration_min, DAYS_PAT)
    for pat, val in ACCESS:
        m, s2 = _take(s + " " + tag_text, pat)
        if m:
            a.access = val
            m2, s = _take(s, pat)
            if tr is not None:
                if m2:
                    tr.hit(m2, "ACCESS", "access", val, pat)
                else:
                    tr.note("ACCESS", "access", val, pat, m.group(0), where="tag")
            break
    inc = []
    for pat, val in INCLUSIONS:
        m, s = _take(s, pat)
        if m:
            inc.append(val)
            if tr is not None:
                tr.hit(m, "INCLUSIONS", "inclusions", val, pat)
    a.inclusions = frozenset(inc)
    for pat, val in AGE:
        m, s = _take(s, pat)
        if m:
            a.age_band = val
            if tr is not None:
                tr.hit(m, "AGE", "age_band", val, pat)
            break
    for pat, val in GROUP:
        m, s = _take(s, pat)
        if m:
            a.group = val
            if tr is not None:
                tr.hit(m, "GROUP", "group", val, pat)
            break
    m, s = _take(s, RESIDENT)
    if m:
        a.resident_only = True
        if tr is not None:
            tr.hit(m, "RESIDENT", "resident_only", True, RESIDENT)
    tw = []
    for pat, val in TIME:
        m, s = _take(s, pat)
        if m:
            tw.append(f"{val}:{m.group(0).strip()}")
            if tr is not None:
                tr.hit(m, "TIME", "time_window", tw[-1], pat)
    a.time_window = tuple(tw)
    for pat, val in EXPERIENCE:
        m, _ = _take(s, pat)
        if m:
            a.experience = val
            if tr is not None:
                tr.hit(m, "EXPERIENCE", "experience", val, pat, consume=False)
            break
    if tr is not None:
        tr.check(s)
    rest = [t for t in s.replace("|", " ").split() if t not in STOP and not t.isdigit() and len(t) > 1]
    for pat, _ in EXPERIENCE:
        rest = [t for t in rest if not re.fullmatch(pat, t)]
    a.core_tokens = frozenset(rest)
    a.confidence = round(1 - len(rest) / n_tok, 3) if a.attractions else round(0.5 * (1 - len(rest) / n_tok), 3)
    return a


# ----------------------------------------------------------------------------- cancellation policy
def parse_policy(text: str | None) -> dict:
    """Free-text cancellation policy -> {refundable, cutoff_hours, klass}."""
    s = norm(text or "")
    if not s:
        return {"refundable": None, "cutoff_hours": None, "klass": "unknown"}
    m = re.search(r"at least (\d+) (hours?|days?)", s)
    if m and "refund" in s:
        h = int(m.group(1)) * (24 if m.group(2).startswith("day") else 1)
        return {"refundable": True, "cutoff_hours": h, "klass": "free_cancellation"}
    if re.search(r"(prior to|before) redemption|unused", s):
        return {"refundable": True, "cutoff_hours": 0, "klass": "refundable_until_used"}
    if re.search(r"no cancell?ations?|non refundable|no refunds?|cannot be cancell?ed", s):
        return {"refundable": False, "cutoff_hours": None, "klass": "non_refundable"}
    if "full refund" in s:
        return {"refundable": True, "cutoff_hours": None, "klass": "free_cancellation"}
    return {"refundable": None, "cutoff_hours": None, "klass": "unparsed"}


# ----------------------------------------------------------------------------- typed relation
@dataclass
class Relation:
    relation: str
    diff: tuple = ()
    reason: str = ""


def _core_overlap(a: ActivityAttrs, b: ActivityAttrs) -> float:
    if not a.core_tokens and not b.core_tokens:
        return 1.0
    return len(a.core_tokens & b.core_tokens) / max(len(a.core_tokens | b.core_tokens), 1)


def relate(a: ActivityAttrs, b: ActivityAttrs) -> Relation:
    """Typed relation of b with respect to a, with human-readable difference chips."""
    # identity = named attractions plus whatever wording the lexicon could not explain (names the gazetteer does not know)
    ia, ib = set(a.attractions) | set(a.core_tokens), set(b.attractions) | set(b.core_tokens)
    extra_a, extra_b = ia - ib, ib - ia
    new_attr_a, new_attr_b = a.attractions - b.attractions, b.attractions - a.attractions
    if (ia or ib) and not (ia & ib):
        return Relation("DIFFERENT", (), "no shared attraction or wording")
    # named attractions decide first: a strict superset of known attractions is a combo whatever the leftover wording says
    if a.attractions and a.attractions < b.attractions:
        return Relation("INCLUDED_IN", tuple(f"+ {x}" for x in sorted(new_attr_b)), "b covers a's attractions and more")
    if b.attractions and b.attractions < a.attractions:
        return Relation("INCLUDES", tuple(f"+ {x}" for x in sorted(new_attr_a)), "a covers b's attractions and more")
    # one side keeps everything the other has and adds an attraction (known by name, or unknown wording joined by combo words)
    if extra_b and not extra_a and (new_attr_b or (b.is_combo_worded and b.inclusions == a.inclusions)):
        return Relation("INCLUDED_IN", tuple(f"+ {x}" for x in sorted(extra_b)), "b covers everything in a and adds more")
    if extra_a and not extra_b and (new_attr_a or (a.is_combo_worded and a.inclusions == b.inclusions)):
        return Relation("INCLUDES", tuple(f"+ {x}" for x in sorted(extra_a)), "a covers everything in b and adds more")
    if new_attr_a and new_attr_b:
        return Relation("DIFFERENT", (), "each side has an attraction the other lacks")
    if not a.attractions and not b.attractions and _core_overlap(a, b) < 0.5:
        return Relation("DIFFERENT", (), "no known attraction and little shared wording")
    if {a.experience, b.experience} - {"ticket", "pass"} and a.experience != b.experience:
        return Relation("DIFFERENT", (), f"experience type {a.experience} vs {b.experience}")
    if a.attractions == b.attractions and _core_overlap(a, b) < 0.34 and (a.core_tokens and b.core_tokens):
        return Relation("DIFFERENT", (), "same venue, different product wording")
    diff = []
    if a.access != b.access:
        diff.append(f"access: {a.access} -> {b.access}")
    diff += [f"+ {x}" for x in sorted(b.inclusions - a.inclusions)] + [f"- {x}" for x in sorted(a.inclusions - b.inclusions)]
    if a.age_band != b.age_band and (a.age_band or "adult") != (b.age_band or "adult"):
        diff.append(f"age: {a.age_band or 'adult'} -> {b.age_band or 'adult'}")
    if (a.group or "shared") != (b.group or "shared"):
        diff.append(f"group: {a.group or 'shared'} -> {b.group or 'shared'}")
    if a.resident_only != b.resident_only:
        diff.append("resident pricing differs")
    if a.time_window != b.time_window:
        diff.append("time window differs")
    if a.duration_min != b.duration_min and a.duration_min and b.duration_min:
        diff.append(f"duration: {a.duration_min} -> {b.duration_min} min")
    if diff:
        return Relation("VARIANT_OF", tuple(diff), "same attractions and experience; whitelisted attributes differ")
    return Relation("SAME_AS", (), "same attractions, experience and attributes")
