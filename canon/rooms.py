"""Room / rate disentanglement: parse a supplier room string into room attributes and rate attributes.

Stage 1 of room mapping (deterministic lexicon). A string the lexicon cannot place cleanly is flagged for the
model stage through `residual` and `confidence`; nothing here calls a model.

    >>> p = parse_room("DLX DBL SV - BB - NRF")
    >>> p.room_class, p.beds, p.view, p.board, p.refundable
    (('deluxe',), ('double',), 'sea', 'BB', False)

Two strings describe the same physical room when their `signature()` is equal; the signature ignores every
rate attribute (board, refundability, inclusions, promotions) and occupancy wording.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import asdict, dataclass, field

from canon._trace import SpanTrace

# ----------------------------------------------------------------------------- normalisation
ABBREV = {
    "dbl": "double", "dble": "double", "twn": "twin", "sgl": "single", "sngl": "single", "tpl": "triple", "trpl": "triple", "trp": "triple",
    "quad": "quadruple", "qdpl": "quadruple", "qd": "quadruple", "qn": "queen", "kg": "king",
    "dlx": "deluxe", "dx": "deluxe", "dlxe": "deluxe", "std": "standard", "stnd": "standard", "sup": "superior", "supr": "superior",
    "exec": "executive", "exe": "executive", "prem": "premium", "jr": "junior", "jnr": "junior", "ste": "suite", "apt": "apartment",
    "appt": "apartment", "rm": "room", "rms": "rooms", "fam": "family", "bfst": "breakfast", "bkfst": "breakfast", "brkfst": "breakfast",
    "incl": "included", "inc": "included", "bal": "balcony", "balc": "balcony", "bdrm": "bedroom", "br": "bedroom", "vw": "view",
    "seaview": "sea view", "oceanview": "ocean view", "cityview": "city view", "gardenview": "garden view", "poolview": "pool view",
    "nonrefundable": "non refundable", "nonref": "non refundable", "nrf": "non refundable", "nr": "non refundable",
    "sv": "sea view", "ov": "ocean view", "cv": "city view", "gv": "garden view", "pv": "pool view", "mv": "mountain view", "lv": "lake view",
    "bb": "bed and breakfast", "hb": "half board", "fb": "full board", "ai": "all inclusive", "ro": "room only",
    "ac": "air conditioned", "nonac": "non air conditioned", "wifi": "wifi", "w": "with",
}


def normalise(text: str) -> str:
    s = unicodedata.normalize("NFKD", text.lower())
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = s.replace("a/c", "ac").replace("w/", "with ").replace("&", " and ").replace("+", " and ")
    s = re.sub(r"non[\s-]*a\s*c\b", "nonac", s)
    s = re.sub(r"[^a-z0-9 ]+", " ", s)
    return " ".join(ABBREV.get(t, t) for t in s.split())


# ----------------------------------------------------------------------------- lexicon (pattern, value); longest first inside a group
BOARD = [(r"all inclusive", "AI"), (r"full board", "FB"), (r"half board", "HB"),
         (r"(bed and breakfast|breakfast (is )?included|(with|including|included|inclusive of|free|complimentary|daily) breakfast|breakfast)", "BB"),
         (r"(room only|without breakfast|no breakfast|no meals?)", "RO")]
REFUND = [(r"(non refundable|not refundable|no refunds?|no cancell?ation)", False),
          (r"(free cancell?ation|fully refundable|refundable|flexible rate|flexible)", True)]
INCLUSIONS = [(r"(club |executive )?lounge access", "lounge_access"), (r"spa access", "spa_access"), (r"(free |with )?parking", "parking"),
              (r"(free |with )?wifi", "wifi"), (r"airport (transfers?|pick ?up|shuttle)", "airport_transfer"), (r"(with |including )?dinner( included)?", "dinner")]
PROMO = r"(special offer|offer|special rate|promo(tion)?|deal|early bird|advance purchase|last minute|package|saver|discount(ed)?|sale|best (available )?rate|member rate)"
ROOM_TYPE = [(r"junior suite", "suite"), (r"suite", "suite"), (r"studio", "studio"), (r"apartment", "apartment"), (r"penthouse", "penthouse"),
             (r"villa", "villa"), (r"bungalow", "bungalow"), (r"cottage", "cottage"), (r"chalet", "chalet"), (r"cabin", "cabin"), (r"loft", "loft"),
             (r"duplex", "duplex"), (r"maisonette", "maisonette"), (r"townhouse", "townhouse"), (r"(dormitory|dorm)", "dormitory"),
             (r"tent", "tent"), (r"house ?boat", "houseboat"), (r"(camp|hut)", "hut")]
CLASS = ["super deluxe", "semi deluxe", "junior", "economy", "budget", "basic", "standard", "classic", "comfort", "superior", "deluxe", "premium",
         "premier", "executive", "club", "luxury", "prestige", "signature", "grand", "royal", "presidential", "privilege", "business", "family",
         "cosy", "cozy", "small", "compact", "large", "regular", "master", "honeymoon", "heritage"]
BED = [(r"double or twin|twin or double|double twin|twin double", ("double", "twin")), (r"king or twin|twin or king", ("king", "twin")),
       (r"queen or twin|twin or queen", ("queen", "twin")), (r"king", ("king",)), (r"queen", ("queen",)), (r"double", ("double",)),
       (r"twin", ("twin",)), (r"single", ("single",)), (r"triple", ("triple",)), (r"quadruple", ("quadruple",)), (r"quintuple", ("quintuple",)),
       (r"bunk", ("bunk",)), (r"sofa ?bed", ("sofa",))]
VIEW = r"(sea|ocean|city|garden|pool|mountain|lake|river|canal|park|courtyard|street|harbou?r|bay|beach|golf|valley|hill|lagoon|skyline|landmark|partial sea|partial ocean)"
FEATURES = [(r"(private|plunge) pool", "private_pool"), (r"balcony", "balcony"), (r"terrace", "terrace"), (r"patio", "patio"),
            (r"kitchenette|kitchen", "kitchen"), (r"jacuzzi|hot tub|spa bath|whirlpool", "jacuzzi"), (r"fireplace", "fireplace"), (r"sauna", "sauna"),
            (r"(inter)?connecting|adjoining|adjacent", "connecting"), (r"accessible|disabled|mobility access|wheelchair", "accessible"),
            (r"non air conditioned", "non_ac"), (r"air conditioned|air conditioning", "ac"), (r"non smoking", "non_smoking"), (r"smoking", "smoking"),
            (r"annexe?", "annex"), (r"ground floor", "ground_floor"), (r"(high|upper|top) floor", "high_floor"), (r"attic", "attic"),
            (r"basement|lower ground", "basement"), (r"shared bathroom", "shared_bathroom"), (r"(private|ensuite|en suite) bathroom", "private_bathroom"),
            (r"(sea|ocean|beach|lake|river) ?front", "waterfront"), (r"extra bed", "extra_bed"), (r"garden", "garden"), (r"courtyard", "courtyard")]
STOP = {"room", "rooms", "with", "and", "the", "a", "an", "of", "in", "bed", "beds", "for", "or", "at", "to", "included", "use", "occupancy",
        "type", "accommodation", "guest", "guestroom", "only", "access", "view", "views", "non", "is", "on", "rate", "plan", "1", "one"}


@dataclass
class ParsedRoom:
    raw: str
    room_type: str = "room"
    room_class: tuple = ()
    beds: tuple = ()
    bed_count: int | None = None
    bedrooms: int | None = None
    view: str | None = None
    features: tuple = ()
    occupancy: int | None = None
    size_m2: float | None = None
    name_tokens: tuple = ()
    # rate side
    board: str | None = None
    refundable: bool | None = None
    inclusions: tuple = ()
    promo: bool = False
    residual: str = ""
    confidence: float = 0.0
    spans: dict = field(default_factory=dict, repr=False)

    def signature(self) -> tuple:
        """Identity of the physical room: everything except rate attributes and occupancy wording."""
        multi_bed = self.bed_count if (self.bed_count or 0) > 1 else None  # "two double beds" is a different room from "double"
        return (self.room_type, self.room_class, self.beds, multi_bed, self.bedrooms, self.view, self.features, self.name_tokens)

    def room_dict(self) -> dict:
        d = asdict(self)
        return {k: d[k] for k in ("room_type", "room_class", "beds", "bed_count", "bedrooms", "view", "features", "occupancy", "size_m2", "name_tokens")}

    def rate_dict(self) -> dict:
        d = asdict(self)
        return {k: d[k] for k in ("board", "refundable", "inclusions", "promo")}


NUM = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6}


def _take(s: str, pattern: str):
    """Find the first match of `pattern` as whole words, return (match, string with it blanked out)."""
    m = re.search(rf"(?<![a-z0-9])(?:{pattern})(?![a-z0-9])", s)
    if not m:
        return None, s
    return m, s[:m.start()] + " " + s[m.end():]


SIZE_PAT = r"(\d{2,3}) ?(sqm|sq m|m2|square met(er|re)s?)"
OCC_PAT = r"(\d) (adults?|persons?|people|guests?|pax)( (and )?\d (child(ren)?|kids?))?"
OCC_USE_PAT = r"(single|double|triple) (use|occupancy)"
BEDROOMS_PAT = r"(\d|one|two|three|four|five|six) bedrooms?"
VIEW_PAT = rf"{VIEW} (and {VIEW} )?views?"
VIEW_ANY_PAT = r"(with |partial |side )?views?"
BED_COUNT_PAT = r"(\d|one|two|three|four) (king|queen|double|twin|single|bunk)( size)? beds?"
CLASS_MAP = {"cozy": "cosy", "premier": "premium", "compact": "small", "budget": "economy", "basic": "economy"}


def parse_room(text: str, trace: list | None = None) -> ParsedRoom:
    """Parse one supplier room string.

    trace: optional list. When given, one dict per rule that fired is appended (group, attr, value, the lexicon pattern,
    the matched text and its [start, end) span in `normalise(text)`), in the order the rules ran. Tracing only observes:
    the returned ParsedRoom is the same with or without it.
    """
    p = ParsedRoom(raw=text)
    s = normalise(text)
    tr = SpanTrace(s, trace) if trace is not None else None
    n_tokens = max(len(s.split()), 1)

    # ---- rate side first, so "breakfast" or "offer" never leaks into the room side
    for pat, val in BOARD:
        m, s = _take(s, pat)
        if m:
            p.board = val
            if tr is not None:
                tr.hit(m, "BOARD", "board", val, pat)
            break
    for pat, val in REFUND:
        m, s = _take(s, pat)
        if m:
            p.refundable = val
            if tr is not None:
                tr.hit(m, "REFUND", "refundable", val, pat)
            break
    inc = []
    for pat, val in INCLUSIONS:
        m, s = _take(s, pat)
        if m:
            inc.append(val)
            if tr is not None:
                tr.hit(m, "INCLUSIONS", "inclusions", val, pat)
    p.inclusions = tuple(sorted(inc))
    while True:
        m, s = _take(s, PROMO)
        if not m:
            break
        p.promo = True
        if tr is not None:
            tr.hit(m, "PROMO", "promo", True, PROMO)

    # ---- size, occupancy, counts
    m, s = _take(s, SIZE_PAT)
    if m:
        p.size_m2 = float(m.group(1))
        if tr is not None:
            tr.hit(m, "SIZE", "size_m2", p.size_m2, SIZE_PAT)
    m, s = _take(s, OCC_PAT)
    if m:
        p.occupancy = int(m.group(1))
        if tr is not None:
            tr.hit(m, "OCCUPANCY", "occupancy", p.occupancy, OCC_PAT)
    m, s = _take(s, OCC_USE_PAT)
    if m:
        p.occupancy = {"single": 1, "double": 2, "triple": 3}[m.group(1)]
        if tr is not None:
            tr.hit(m, "OCCUPANCY", "occupancy", p.occupancy, OCC_USE_PAT)
    m, s = _take(s, BEDROOMS_PAT)
    if m:
        p.bedrooms = NUM.get(m.group(1), None) or int(m.group(1))
        if tr is not None:
            tr.hit(m, "BEDROOMS", "bedrooms", p.bedrooms, BEDROOMS_PAT)

    # ---- view (before features, so "garden view" is a view and "garden" alone a feature)
    m, s = _take(s, VIEW_PAT)
    if m:
        p.view = m.group(1).replace("harbor", "harbour")  # "partial sea" stays distinct from "sea": hotels sell both
        if tr is not None:
            tr.hit(m, "VIEW", "view", p.view, VIEW_PAT)
    else:
        m, s = _take(s, VIEW_ANY_PAT)
        if m:
            p.view = "view"
            if tr is not None:
                tr.hit(m, "VIEW", "view", p.view, VIEW_ANY_PAT)
    feats = []
    for pat, val in FEATURES:
        m, s = _take(s, pat)
        if m:
            feats.append(val)
            if tr is not None:
                tr.hit(m, "FEATURES", "features", val, pat)
    p.features = tuple(sorted(set(feats)))

    # ---- beds: "2 queen beds", "1 king bed", then bare bed words
    beds = []
    m, s = _take(s, BED_COUNT_PAT)
    if m:
        p.bed_count = NUM.get(m.group(1), None) or int(m.group(1))
        beds.append(m.group(2))
        if p.bed_count == 2 and m.group(2) in ("single", "twin"):
            beds[-1], p.bed_count = "twin", None  # two single beds is what "twin" means
        if tr is not None:
            tr.hit(m, "BED_COUNT", "beds", beds[-1], BED_COUNT_PAT, bed_count=p.bed_count)
    for pat, val in BED:
        while True:
            m, s = _take(s, pat)
            if not m:
                break
            beds.extend(val)
            if tr is not None:
                tr.hit(m, "BED", "beds", list(val), pat)
    p.beds = tuple(sorted(set(beds)))

    # ---- room type and class
    for pat, val in ROOM_TYPE:
        m, s2 = _take(s, pat)
        if m:
            p.room_type = val
            if val != "suite" or "junior" not in m.group(0):
                if tr is not None:
                    tr.hit(m, "ROOM_TYPE", "room_type", val, pat)
                s = s2
            else:  # "junior suite": the type is suite and "junior" stays behind for the class lexicon
                if tr is not None:
                    i = s.find("junior suite")
                    a, b = tr.span(i + 7, i + 12)
                    tr.out.append({"group": "ROOM_TYPE", "attr": "room_type", "value": val, "pattern": pat, "matched": m.group(0),
                                   "start": a, "end": b, "note": "junior is left for the class lexicon"})
                    if tr.pos is not None:
                        tr.pos = tr.pos[:i + 6] + tr.pos[i + 12:]
                s = s.replace("junior suite", "junior", 1)
            break
    classes = []
    for c in CLASS:
        m, s = _take(s, c)
        if m:
            classes.append(CLASS_MAP.get(c, c))
            if tr is not None:
                tr.hit(m, "CLASS", "room_class", CLASS_MAP.get(c, c), c)
    p.room_class = tuple(sorted(set(classes)))
    if tr is not None:
        tr.check(s)

    # ---- what is left: proper names (kept as identity) and noise
    rest = [t for t in s.split() if t not in STOP and not t.isdigit()]
    p.name_tokens = tuple(sorted(set(rest)))
    p.residual = " ".join(rest)
    understood = n_tokens - len(rest)
    has_core = bool(p.beds or p.room_class or p.room_type != "room")
    p.confidence = round((understood / n_tokens) * (1.0 if has_core else 0.5), 3)
    return p


def same_room(a: ParsedRoom, b: ParsedRoom) -> bool:
    return a.signature() == b.signature()
