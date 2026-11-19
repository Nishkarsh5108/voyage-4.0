"""EDA: real room-name strings — what a room/rate extractor has to parse.

Sources
  * 515K Booking.com reviews (Europe): the `Tags` column carries the room the guest booked.
  * MakeMyTrip + Goibibo room-type strings (India).
Output: reports/eda/rooms.md + figures + rooms.json, and data/interim/room_strings.parquet (hotel, room string, count)
Usage : python -I scripts/eda/eda_rooms.py
"""
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import INTERIM, RAW, SERIES, Report, barh, connect, fig_for_bars, plt  # noqa: E402

# A first-pass lexicon. Order matters inside a group: longer phrases first.
LEX = {
    "room class": r"\b(standard|classic|superior|deluxe|de luxe|premium|premier|executive|club|luxury|comfort|economy|budget|basic|privilege"
                  r"|business|prestige|signature|grand|royal|presidential|penthouse|junior suite|suite|studio|apartment|loft|duplex|villa"
                  r"|cottage|bungalow|maisonette|family|cosy|cozy|small|compact|large|super deluxe|semi deluxe)\b",
    "bed type": r"\b(double or twin|twin or double|double|twin|king|queen|single|triple|quadruple|quad|bunk|sofa ?bed|1 bed|2 beds|3 beds"
                r"|\d bedrooms?|one bedroom|two bedrooms?|three bedrooms?|dormitory|dorm)\b",
    "view / location": r"\b(\w+ view|view|sea ?front|ocean ?front|pool ?side|garden|courtyard|terrace|balcony|rooftop|top floor|ground floor"
                       r"|high floor|lake facing|sea facing|canal|river)\b",
    "occupancy": r"(\b\d\s*(adults?|persons?|people|guests?|children|kids|pax)\b|\bfor (1|2|3|4|one|two|three|four)\b|\bextra bed\b|\bsleeps \d)",
    "rate / package leaked into the name": r"\b(breakfast|half board|full board|all inclusive|non[- ]?refundable|refundable|free wifi|wifi"
                                           r"|spa access|lounge access|parking|offer|special|package|promo|deal|dinner|advance purchase|room only)\b",
    "accessibility / smoking": r"\b(disabled|accessible|accessibility|mobility|wheelchair|non[- ]?smoking|smoking)\b",
    "climate (India)": r"\b(non[- ]?a/?c|a/?c|air[- ]?condition(ed|ing)?|air[- ]?cooled?|cooler)\b",
}
LEXC = {k: re.compile(v, re.I) for k, v in LEX.items()}
NOT_ROOM = (r"^(Leisure trip|Business trip|Couple|Solo traveler|Group|Family with young children|Family with older children"
            r"|Travelers with friends|With a pet|Submitted from a mobile device|Stayed \d+ nights?|\d+ rooms?)$")

r = Report("rooms", "EDA — real room-name strings (Booking.com Europe, MakeMyTrip and Goibibo India)")
con = connect()
one = lambda sql: con.execute(sql).fetchone()  # noqa: E731
rows = lambda sql: con.execute(sql).fetchall()  # noqa: E731

import pandas as pd  # noqa: E402

# pandas' parser copes with the quoting in this file; only five columns are loaded to stay small in memory
rev_df = pd.read_csv(RAW / "hotel_reviews_515k" / "Hotel_Reviews.csv", usecols=["Hotel_Name", "Hotel_Address", "lat", "lng", "Tags"],
                     dtype={"Hotel_Name": "string", "Hotel_Address": "string", "Tags": "string"})
rev_df.columns = ["addr", "hotel", "tags", "lat", "lng"]
con.execute("CREATE TEMP TABLE rev AS SELECT hotel, addr, lat, lng, tags FROM rev_df")
del rev_df
nrev, nhot = one("SELECT count(*), count(DISTINCT hotel) FROM rev")
con.execute(f"""CREATE TEMP TABLE rr AS
    SELECT hotel, any_value(addr) addr, any_value(lat) lat, any_value(lng) lng, room, count(*) n FROM (
        SELECT hotel, addr, lat, lng, trim(unnest(regexp_extract_all(tags, '''([^'']+)''', 1))) room FROM rev)
    WHERE length(room) > 1 AND room NOT IN (',', ', ') AND NOT regexp_matches(room, '{NOT_ROOM}') AND room NOT LIKE '[%' AND room NOT LIKE '%]'
    GROUP BY hotel, room""")
INTERIM.mkdir(parents=True, exist_ok=True)
con.execute(f"COPY rr TO '{(INTERIM / 'room_strings.parquet').as_posix()}' (FORMAT parquet)")

r.p("Sources: Kaggle `jiashenliu/515k-hotel-reviews-data-in-europe` (CC0; Booking.com reviews of luxury hotels in London, Paris, Amsterdam, "
    "Barcelona, Vienna and Milan, 2015-2017) and the two PromptCloud OTA samples. "
    "Each Booking review carries the name of the room that was booked, which gives real room names weighted by how often they sell.")

# ---------------------------------------------------------------- 1. size
r.h("1. Size")
tagged, uniq, uniq_lower, pairs = one("SELECT sum(n)::BIGINT, count(DISTINCT room), count(DISTINCT lower(room)), count(*) FROM rr")
r.table(["Reviews", "Hotels", "Reviews with a room tag", "Hotel x room combinations", "Distinct room strings", "Distinct after lower-casing"],
        [[nrev, nhot, f"{tagged:,} ({tagged / nrev:.1%})", pairs, uniq, uniq_lower]], align=["---:"] * 6)
r.stat("booking", {"reviews": nrev, "hotels": nhot, "tagged": tagged, "hotel_room_pairs": pairs, "distinct_strings": uniq})

# ---------------------------------------------------------------- 2. zipf
r.h("2. A few names cover most bookings, and the tail is long")
freq = rows("SELECT room, sum(n)::BIGINT c, count(DISTINCT hotel) h FROM rr GROUP BY 1 ORDER BY c DESC")
tot = sum(f[1] for f in freq)
r.table(["Room string (top 20)", "Reviews", "Hotels using it"], [list(f) for f in freq[:20]])
fig, ax = fig_for_bars(20)
barh(ax, [f[0] for f in freq[:20]], [f[1] for f in freq[:20]], xlabel="reviews", title="Most-booked room names (Booking.com, Europe)")
r.fig(fig, "top_rooms", "Generic names dominate: the same string means a different physical room in every hotel.")
cum, acc = [], 0
for f in freq:
    acc += f[1]
    cum.append(acc / tot)
cov = {k: cum[min(k, len(cum)) - 1] for k in (10, 50, 100, 250, 500, 1000)}
r.table(["Top-k strings", "Share of bookings covered"], [[f"top {k}", f"{v:.1%}"] for k, v in cov.items()])
fig, ax = plt.subplots(figsize=(7.5, 3.2))
ax.plot(range(1, len(cum) + 1), [c * 100 for c in cum], color=SERIES[0])
ax.set_xscale("log"); ax.set_xlabel("room strings ranked by bookings (log scale)"); ax.set_ylabel("cumulative % of bookings")
ax.set_ylim(0, 101); ax.set_title(f"{len(freq):,} distinct room strings: coverage by rank")
k90 = next(i for i, c in enumerate(cum, 1) if c >= 0.9)
ax.scatter([k90], [90], s=46, color=SERIES[0], edgecolor="#fcfcfb", linewidth=2, zorder=3)
ax.annotate(f"{k90} strings cover 90%", (k90, 90), textcoords="offset points", xytext=(10, -14), color="#52514e", fontsize=9)
r.fig(fig, "coverage_curve", f"{k90} strings cover 90% of bookings; the other {len(freq) - k90:,} strings share the last 10%.")
single = sum(1 for f in freq if f[2] == 1)
multi10 = sum(1 for f in freq if f[2] >= 10)
r.p(f"{single:,} of {len(freq):,} strings ({single / len(freq):.1%}) are used by a single hotel; only {multi10} are used by ten or more hotels, "
    f"yet those {multi10} strings account for {sum(f[1] for f in freq if f[2] >= 10) / tot:.1%} of bookings. "
    "Caching extraction per unique string therefore pays off immediately, and model calls scale with the tail, not with the catalogue.")
r.stat("coverage", cov); r.stat("strings_for_90pct", k90); r.stat("single_hotel_strings", single)

# ---------------------------------------------------------------- 3. rooms per hotel
r.h("3. Room names per hotel")
ph = rows("SELECT count(*) k FROM rr GROUP BY hotel")
ks = sorted(x[0] for x in ph)
q = lambda p: ks[int(p * (len(ks) - 1))]  # noqa: E731
r.table(["min", "p25", "median", "p75", "p90", "max"], [[ks[0], q(0.25), q(0.5), q(0.75), q(0.9), ks[-1]]], align=["---:"] * 6)
hist = Counter(min(k, 60) // 5 * 5 for k in ks)
fig, ax = plt.subplots(figsize=(7.5, 3.0))
ax.bar([b + 2.5 for b in sorted(hist)], [hist[b] for b in sorted(hist)], width=4.4, color=SERIES[0])
ax.grid(axis="x", visible=False); ax.set_xlabel("distinct room names seen for the hotel (60 = 60 or more)"); ax.set_ylabel("hotels")
ax.set_title("How many room names does one hotel expose?")
r.fig(fig, "rooms_per_hotel", f"A typical hotel has {q(0.5)} room names with reviews on this one channel (up to {ks[-1]}), "
      "before any second supplier adds its own names for the same rooms.")
r.stat("rooms_per_hotel", {"median": q(0.5), "p90": q(0.9), "max": ks[-1]})

# ---------------------------------------------------------------- 4. lexicon coverage
r.h("4. What a plain lexicon can and cannot extract")


def coverage(strings_with_weight):
    n = len(strings_with_weight)
    w = sum(x[1] for x in strings_with_weight)
    out = {}
    for k, rx in LEXC.items():
        hit = [(s, c) for s, c in strings_with_weight if rx.search(s)]
        out[k] = (len(hit) / n, sum(c for _, c in hit) / w)
    none = [(s, c) for s, c in strings_with_weight if not (LEXC["room class"].search(s) or LEXC["bed type"].search(s))]
    out["neither class nor bed found"] = (len(none) / n, sum(c for _, c in none) / w)
    return out, none


bk = [(f[0], f[1]) for f in freq]
cv, none = coverage(bk)
r.p("Share of Booking.com room strings in which each attribute group is detected by regular expressions:")
r.table(["Attribute group", "Share of distinct strings", "Share of bookings"], [[k, f"{a:.1%}", f"{b:.1%}"] for k, (a, b) in cv.items()])
fig, ax = fig_for_bars(len(cv))
barh(ax, list(cv), [a * 100 for a, _ in cv.values()], value_fmt="{:.0f}%", xlabel="% of distinct room strings", title="Lexicon hit rate by attribute group")
r.fig(fig, "lexicon_coverage", "Class and bed type are usually stated; rate and package terms leak into a visible share of room names.")
r.stat("lexicon_booking", {k: {"strings": a, "bookings": b} for k, (a, b) in cv.items()})
r.p("Strings where the lexicon finds neither a class nor a bed type (most booked first), the work left for the model stage:")
r.table(["Room string", "Reviews"], [[s, c] for s, c in none[:15]])
leak = [(s, c) for s, c in bk if LEXC["rate / package leaked into the name"].search(s)]
r.p(f"**Room and rate are tangled in the name**: {len(leak):,} strings ({len(leak) / len(bk):.1%}) carry a board, refund or package term. Examples:")
r.table(["Room string with a rate or package term", "Reviews"], [[s, c] for s, c in leak[:12]])

# ---------------------------------------------------------------- 5. confusable names inside one hotel
r.h("5. Confusable names inside one hotel")
con.execute(r"""CREATE TEMP TABLE tok AS SELECT hotel, room, n,
    list_sort(list_distinct(list_filter(string_split(regexp_replace(lower(room), '[^a-z0-9 ]', ' ', 'g'), ' '),
              lambda x: x NOT IN ('', 'room', 'rooms', 'with', 'and', 'the', 'a', 'or', 'of')))) t FROM rr""")
sub = one("""SELECT count(*), count(DISTINCT a.hotel) FROM tok a JOIN tok b ON a.hotel = b.hotel AND a.room < b.room
             WHERE len(a.t) > 0 AND len(b.t) > 0 AND a.t <> b.t AND (list_has_all(a.t, b.t) OR list_has_all(b.t, a.t))
               AND abs(len(a.t) - len(b.t)) = 1""")
same = one("SELECT count(*), count(DISTINCT a.hotel) FROM tok a JOIN tok b ON a.hotel = b.hotel AND a.room < b.room WHERE a.t = b.t AND len(a.t) > 0")
r.p(f"Within one hotel, **{sub[0]:,} pairs of room names differ by exactly one token** (for example *Double Room* vs *Superior Double Room*), "
    f"across {sub[1]:,} of {nhot:,} hotels. Another {same[0]:,} pairs in {same[1]:,} hotels have the same tokens in a different order or with "
    "different punctuation. The first kind must stay separate (the token is the difference); the second kind should merge. "
    "String similarity cannot tell the two apart, attribute extraction can.")
exs = rows("""SELECT a.hotel, a.room, b.room FROM tok a JOIN tok b ON a.hotel = b.hotel AND a.room < b.room
              WHERE len(a.t) > 1 AND a.t <> b.t AND (list_has_all(a.t, b.t) OR list_has_all(b.t, a.t)) AND abs(len(a.t) - len(b.t)) = 1
              ORDER BY hash(a.hotel || a.room) LIMIT 8""")
r.table(["Hotel", "Room name A", "Room name B"], exs, align=["---", "---", "---"])
r.stat("one_token_apart_pairs", sub[0]); r.stat("same_tokens_pairs", same[0])

# ---------------------------------------------------------------- 6. India OTA strings: does the lexicon transfer?
r.h("6. Indian OTA room strings: does the same lexicon transfer?")
mmt = (RAW / "makemytrip_hotels" / "makemytrip_com-travel_sample.csv").as_posix()
gob = (RAW / "goibibo_hotels" / "goibibo_com-travel_sample.csv").as_posix()
ind = rows(f"""SELECT 'MakeMyTrip' s, lower(trim(room_types)) k, count(*) c FROM read_csv_auto('{mmt}', sample_size=-1, ignore_errors=true)
               WHERE room_types IS NOT NULL GROUP BY 2
               UNION ALL SELECT 'Goibibo', lower(trim(room_type)), count(*) FROM read_csv_auto('{gob}', sample_size=-1, ignore_errors=true)
               WHERE room_type IS NOT NULL GROUP BY 2""")
tab = []
for s in ("MakeMyTrip", "Goibibo"):
    sw = [(k, c) for src, k, c in ind if src == s]
    c2, n2 = coverage(sw)
    tab.append([s, len(sw), f"{c2['room class'][0]:.1%}", f"{c2['bed type'][0]:.1%}", f"{c2['climate (India)'][0]:.1%}",
                f"{c2['rate / package leaked into the name'][0]:.1%}", f"{c2['neither class nor bed found'][0]:.1%}"])
    r.stat(f"lexicon_{s.lower()}", {k: v[0] for k, v in c2.items()})
    r.stat(f"unparsed_examples_{s.lower()}", [k for k, _ in sorted(n2, key=lambda x: -x[1])[:15]])
r.table(["Supplier", "Distinct strings", "Class found", "Bed type found", "AC / non-AC stated", "Rate term leaked", "Neither class nor bed"], tab)
unp = sorted([(k, c) for src, k, c in ind if not (LEXC["room class"].search(k) or LEXC["bed type"].search(k))], key=lambda x: -x[1])[:14]
r.p("Most common Indian strings the lexicon cannot place: " + ", ".join(f"`{k}` ({c})" for k, c in unp) + ".")
r.p("Bed type is rarely stated in the Indian feeds while air-conditioning is a first-class attribute, so the canonical room schema needs "
    "a market-specific attribute set and the extractor must not treat a missing bed type as a mismatch.")

r.h("7. What this means for room and rate mapping")
r.bullets([
    f"**Cache per unique string.** {k90} strings cover 90% of bookings in this set; extraction cost follows the tail.",
    f"**Lexicon first, model second.** Regular expressions already find a class or bed type in {1 - cv['neither class nor bed found'][0]:.1%} "
    f"of distinct strings ({1 - cv['neither class nor bed found'][1]:.1%} of bookings); the rest goes to the model stage.",
    f"**Split room from rate before matching.** {len(leak) / len(bk):.1%} of room names contain a board, refund or package term.",
    f"**Match on attributes, not string similarity.** {sub[0]:,} same-hotel name pairs differ by a single token that is the whole difference.",
    "**Schema is market-specific.** AC / non-AC matters in India and is absent in Europe; bed type is the reverse.",
])
r.write()
