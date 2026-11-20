"""Uploaded feeds: read CSV / JSON / GeoJSON, map columns by synonym, validate, and report problems in plain sentences.

The output is a record frame with the columns canon.match.prepare and canon.cascade expect. Phone, website and QID are
kept only for the stage-0 key rules and weak labels; they never become model features. Keys are normalised exactly as
scripts/build/build_listings.py does (phone8: last 8 digits of the first number; domain and url_key from the website).
"""
from __future__ import annotations

import base64
import binascii
import csv
import io
import json
import math
import re
import threading
from collections import Counter, OrderedDict
from pathlib import PurePath

import numpy as np
import pandas as pd

from canon.match import norm

from . import UserError

MAX_TOTAL_BYTES = 40 * 1024 * 1024
MAX_RECORDS = 150_000
KEEP_UPLOADS = 8
SYNONYMS = {  # canonical field -> accepted column names (case-insensitive; spaces and hyphens read as underscores), first wins
    "name": ["name", "property_name", "hotel_name", "title"],
    "lat": ["lat", "latitude"],
    "lon": ["lon", "lng", "long", "longitude"],
    "source": ["source", "supplier", "feed"],
    "id": ["id", "src_id", "property_id", "code"],
    "street": ["street", "address", "address_line", "property_address"],
    "postcode": ["postcode", "zip", "postal_code", "pincode"],
    "city": ["city"],
    "brand": ["brand", "chain"],
    "stars": ["stars", "star_rating", "hotel_star_rating", "rating"],
    "alt_names": ["alt_names", "aliases"],
    "kind": ["kind", "type"],
    "qid": ["qid", "wikidata"],
    "phone": ["phone", "telephone"],
    "website": ["website", "url"],
}
LODGING_WORDS = {"lodging", "hotel", "hotels", "hostel", "resort", "motel", "guest_house", "guesthouse", "guest house", "apartment",
                 "accommodation", "inn", "bnb", "b&b", "homestay", "villa", "property"}
ATTRACTION_WORDS = {"attraction", "attractions", "poi", "sight", "sightseeing", "activity", "museum", "landmark", "tour", "park", "monument"}
FEATURE_EFFECT = {
    "street": "street_token_set is missing for every pair; the model treats it as unknown.",
    "postcode": "postcode_eq is missing for every pair; the model treats it as unknown.",
    "brand": "brand_sim is missing for every pair; the model treats it as unknown.",
    "stars": "stars_diff is missing for every pair; the model treats it as unknown.",
    "alt_names": "No alternate names: name_jw_alt and name_token_set_alt equal the main-name scores and has_alt is 0.",
}
TRAIN_SOURCES = {"overture", "osm", "wikidata", "wikivoyage"}


def _colkey(c) -> str:
    return re.sub(r"[\s\-]+", "_", str(c).strip().lower())


def _rows_text(rows: list, limit: int = 6) -> str:
    shown = ", ".join(str(r) for r in rows[:limit])
    return f"row {shown}" if len(rows) == 1 else f"rows {shown}" + (", …" if len(rows) > limit else "")


def _plural(n: int, one: str, many: str | None = None) -> str:
    return f"{n:,} {one if n == 1 else (many or one + 's')}"


# ---------------------------------------------------------------------------- key normalisation (build_listings.py)
def phone8(raw) -> str | None:
    if not isinstance(raw, str) or not raw.strip():
        return None
    digits = re.sub(r"[^0-9]", "", raw.split(";")[0])
    return digits[-8:] if len(digits) >= 8 else None


def domain_of(website) -> str | None:
    if not isinstance(website, str):
        return None
    m = re.match(r"^(?:https?://)?(?:www\.)?([^/?#:]+)", website.lower())
    return m.group(1) if m and m.group(1) else None


def url_key_of(website) -> str | None:
    if not isinstance(website, str):
        return None
    m = re.match(r"^(?:https?://)?(?:www\.)?([^?#]+)", website.lower())
    k = m.group(1).rstrip("/") if m else ""
    return k or None


def qid_of(v) -> str | None:
    if v is None:
        return None
    m = re.search(r"Q\d+", str(v), flags=re.I)
    return m.group(0).upper() if m else None


# ---------------------------------------------------------------------------- readers
class FileRead:
    def __init__(self, name: str):
        self.name, self.format = name, None
        self.header: list = []
        self.rows: list = []  # list of (row number as a person sees it, {column: value})
        self.problems: list = []
        self.geometry = False

    def add(self, level: str, text: str):
        self.problems.append({"level": level, "text": text})

    @property
    def fatal(self) -> bool:
        return any(p["level"] == "error" for p in self.problems)


def _decode(f: dict, fr: FileRead) -> str | None:
    if f.get("b64") is not None:
        try:
            raw = base64.b64decode(f["b64"], validate=True)
        except (binascii.Error, ValueError):
            fr.add("error", "The file content could not be decoded (bad base64 from the page).")
            return None
        if raw[:4] == b"PK\x03\x04":
            fr.add("error", "This is a zip or Excel workbook. Save the sheet as CSV (UTF-8) and upload that.")
            return None
        for enc, msg in (("utf-8-sig", None), ("cp1252", "The file is not UTF-8. It was read as Windows-1252 (Western European); "
                                                          "check that accented names look right, or save it as UTF-8."),
                         ("latin-1", "The file is not UTF-8. It was read as Latin-1; check that accented names look right, or save it as UTF-8.")):
            try:
                text = raw.decode(enc)
            except UnicodeDecodeError:
                continue
            if msg:
                fr.add("warn", msg)
            return text
    text = f.get("text")
    if not isinstance(text, str):
        fr.add("error", "The upload carries no file content.")
        return None
    if text.startswith("﻿"):
        text = text[1:]
    if text.startswith("PK\x03\x04"):
        fr.add("error", "This is a zip or Excel workbook. Save the sheet as CSV (UTF-8) and upload that.")
        return None
    bad = text.count("�")
    if bad:
        fr.add("warn", f"{_plural(bad, 'character')} could not be decoded and show as �: the file is probably not UTF-8. "
                       "Save it as UTF-8 and upload it again, or names with accents may not match.")
    return text


def _read_csv(text: str, fr: FileRead) -> None:
    lines = [ln for ln in text.splitlines() if ln.strip()]
    sample = "\n".join(lines[:60])
    best = None
    for delim in (",", ";", "\t"):
        try:
            counts = [len(r) for r in csv.reader(io.StringIO(sample), delimiter=delim) if any(c.strip() for c in r)]
        except csv.Error:
            continue
        if not counts:
            continue
        consistent = sum(c == counts[0] for c in counts) / len(counts)
        score = (counts[0] > 1, consistent >= 0.8, counts[0], consistent)
        if best is None or score > best[0]:
            best = (score, delim)
    if best is None:
        fr.add("error", "The file is empty.")
        return
    (multi, _, ncol, _), delim = best
    if not multi:
        head = lines[0] if lines else ""
        for other, label in (("|", "|"), (":", ":"), ("^", "^")):
            if head.count(other) >= 2:
                fr.add("error", f"The columns seem to be separated by '{label}'. Canon reads comma, semicolon or tab separated files: "
                                "save the file with commas between columns.")
                return
        fr.add("error", "Only one column was found. Canon needs at least a name and coordinates, in columns separated by commas, "
                        "semicolons or tabs.")
        return
    fr.format = {",": "csv", ";": "csv (semicolon)", "\t": "csv (tab)"}[delim]
    reader = csv.reader(io.StringIO(text), delimiter=delim)
    try:
        records = [r for r in reader]
    except csv.Error as e:
        fr.add("error", f"The CSV could not be read near line {reader.line_num}: {e}. This usually means a quote (\") is never closed.")
        return
    records = [(i + 1, r) for i, r in enumerate(records) if any(c.strip() for c in r)]
    if not records:
        fr.add("error", "The file is empty.")
        return
    hrow, header = records[0]
    seen = Counter()
    fr.header = []
    for j, h in enumerate(header):
        h = h.strip() or f"column_{j + 1}"
        seen[h] += 1
        fr.header.append(h if seen[h] == 1 else f"{h}_{seen[h]}")
    bad, runaway = [], []
    for rown, r in records[1:]:
        if any("\n" in c and c.count(delim) >= 2 and c.count("\n") >= 2 for c in r):
            runaway.append(rown)
        if len(r) != len(fr.header):
            bad.append((rown, len(r)))
            continue
        fr.rows.append((rown, dict(zip(fr.header, (c.strip() for c in r)))))
    if runaway:
        fr.add("error", f"A quote (\") is opened and never closed near {_rows_text(runaway)}: everything after it was read as one value. "
                        "Fix the quoting, or remove stray quote characters from names.")
        return
    if bad:
        n_rows = len(records) - 1
        example = f"row {bad[0][0]} has {bad[0][1]} fields, the header has {len(fr.header)}"
        if len(bad) > n_rows / 2:
            fr.add("error", f"Most rows do not have the same number of fields as the header ({example}). The delimiter or the quoting is wrong; "
                            "a comma inside a name needs quotes around the name.")
            return
        where = example if len(bad) == 1 else f"{example}; {_rows_text([b[0] for b in bad])}"
        fr.add("warn", f"{_plural(len(bad), 'row')} with a different number of fields from the header {'was' if len(bad) == 1 else 'were'} skipped "
                       f"({where}). A comma inside a name needs quotes around the name.")
    if not fr.rows:
        fr.add("error", "The file has a header row but no data rows.")


def _flatten(v):
    if isinstance(v, (dict,)):
        return json.dumps(v, ensure_ascii=False)
    return v


def _read_json(text: str, fr: FileRead) -> None:
    try:
        obj = json.loads(text)
    except json.JSONDecodeError as e:
        fr.add("error", f"The JSON could not be read: {e.msg} (line {e.lineno}, column {e.colno}).")
        return
    shape = ("Canon reads a JSON array of objects, an object with a \"records\" array, or a GeoJSON FeatureCollection of Points.")
    if isinstance(obj, dict) and obj.get("type") == "Feature":
        obj = {"type": "FeatureCollection", "features": [obj]}
    if isinstance(obj, dict) and obj.get("type") == "FeatureCollection":
        feats = obj.get("features")
        if not isinstance(feats, list):
            fr.add("error", "The GeoJSON FeatureCollection has no \"features\" array. " + shape)
            return
        fr.format, fr.geometry = "geojson", True
        not_point = Counter()
        for i, ft in enumerate(feats, start=1):
            if not isinstance(ft, dict):
                not_point["not an object"] += 1
                continue
            props = dict(ft.get("properties") or {})
            geom = ft.get("geometry") or {}
            row = {k: _flatten(v) for k, v in props.items()}
            coords = geom.get("coordinates") if isinstance(geom, dict) else None
            if isinstance(geom, dict) and geom.get("type") == "Point" and isinstance(coords, list) and len(coords) >= 2:
                row["__geom_lon"], row["__geom_lat"] = coords[0], coords[1]
            else:
                not_point[geom.get("type", "no geometry") if isinstance(geom, dict) else "no geometry"] += 1
            fr.rows.append((i, row))
        if not_point:
            fr.add("warn", f"{_plural(sum(not_point.values()), 'feature')} {'is' if sum(not_point.values()) == 1 else 'are'} not a Point ("
                           + ", ".join(f"{k}: {v}" for k, v in not_point.items()) + "). They keep their properties but have no coordinates "
                           "unless the properties carry lat / lon.")
    else:
        if isinstance(obj, dict) and isinstance(obj.get("records"), list):
            items = obj["records"]
        elif isinstance(obj, list):
            items = obj
        elif isinstance(obj, dict):
            keys = ", ".join(list(obj)[:6])
            fr.add("error", f"The JSON is an object with keys {keys}, but no \"records\" array. " + shape)
            return
        else:
            fr.add("error", f"The JSON is a single {type(obj).__name__}. " + shape)
            return
        fr.format = "json"
        non_obj = 0
        for i, it in enumerate(items, start=1):
            if isinstance(it, dict):
                fr.rows.append((i, {str(k): _flatten(v) for k, v in it.items()}))
            else:
                non_obj += 1
        if non_obj and not fr.rows:
            fr.add("error", "The JSON array holds values, not objects (one object per hotel, with name / lat / lon keys). " + shape)
            return
        if non_obj:
            fr.add("warn", f"{_plural(non_obj, 'array item')} {'is' if non_obj == 1 else 'are'} not an object and {'was' if non_obj == 1 else 'were'} skipped.")
    if not fr.rows and not fr.fatal:
        fr.add("error", "The file holds no records.")
    keys = []
    for _, r in fr.rows:
        for k in r:
            if k not in keys:
                keys.append(k)
    fr.header = keys


# ---------------------------------------------------------------------------- values
def _num(v):
    if v is None or isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        f = float(v)
        return f if math.isfinite(f) else None
    s = str(v).strip()
    if not s:
        return None
    if re.fullmatch(r"-?\d+,\d+", s):
        s = s.replace(",", ".")
    try:
        f = float(s)
    except ValueError:
        return None
    return f if math.isfinite(f) else None


def _text(v):
    if v is None:
        return None
    if isinstance(v, float) and not math.isfinite(v):
        return None
    s = str(v).strip()
    return s or None


def _stars(v):
    if v is None or isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        f = float(v)
    else:
        m = re.search(r"\d+(?:[.,]\d+)?", str(v))
        if not m:
            return None
        f = float(m.group(0).replace(",", "."))
    return f if 0 <= f <= 7 else None


def _alts(v):
    if v is None:
        return None
    if isinstance(v, list):
        xs = [str(x).strip() for x in v if x is not None and str(x).strip()]
    else:
        xs = [x.strip() for x in re.split(r"[|;]", str(v)) if x.strip()]
    return xs or None


def _kind(v):
    s = (_text(v) or "").lower()
    if not s or s in LODGING_WORDS:
        return "lodging", False
    if s in ATTRACTION_WORDS:
        return "attraction", False
    return "lodging", True


# ---------------------------------------------------------------------------- main entry
def parse_upload(files) -> tuple:
    """files: [{"name", "text"} | {"name", "b64"}]. Returns (record frame or None, report)."""
    if not isinstance(files, list) or not files:
        raise UserError("Send {\"files\": [{\"name\": ..., \"text\": ...}]} with at least one file.")
    if len(files) > 12:
        raise UserError("Upload at most 12 files at a time.")
    total = sum(len(f.get("text") or "") + len(f.get("b64") or "") * 3 // 4 for f in files if isinstance(f, dict))
    if total > MAX_TOTAL_BYTES:
        raise UserError(f"The upload is {total / 1e6:.1f} MB; the limit is {MAX_TOTAL_BYTES // (1024 * 1024)} MB in total.", status=413)
    reports, frames, report_problems = [], [], []
    stems = Counter()
    for n, f in enumerate(files, start=1):
        if not isinstance(f, dict):
            raise UserError("Each entry of \"files\" must be an object with name and text.")
        name = str(f.get("name") or f"file{n}.csv")
        fr = FileRead(name)
        ext = PurePath(name).suffix.lower()
        stem = re.sub(r"\s+", "_", PurePath(name).stem.strip()) or f"file{n}"
        stems[stem] += 1
        if stems[stem] > 1:
            stem = f"{stem}_{stems[stem]}"
        rep = {"name": name, "format": None, "rows": 0, "usable": 0, "source": None, "sources": [], "columns": {}, "ignored_columns": [],
               "problems": fr.problems}
        reports.append(rep)
        if ext in (".xlsx", ".xls", ".xlsm", ".ods", ".parquet", ".zip", ".gz"):
            fr.add("error", f"{ext} files are not read here. Save the data as CSV (UTF-8) or JSON and upload that.")
            continue
        text = _decode(f, fr)
        if text is None:
            continue
        if not text.strip():
            fr.add("error", "The file is empty.")
            continue
        is_json = ext in (".json", ".geojson") or (ext not in (".csv", ".tsv", ".txt") and text.lstrip()[:1] in "[{")
        if is_json:
            _read_json(text, fr)
        else:
            _read_csv(text, fr)
        rep["format"] = fr.format
        rep["rows"] = len(fr.rows)
        if fr.fatal:
            continue
        frame = _map_rows(fr, stem, rep)
        if frame is not None:
            frames.append(frame)
    ok_files = not any(p["level"] == "error" for r in reports for p in r["problems"])
    frame = pd.concat(frames, ignore_index=True) if frames else None
    report = {"files": reports, "records": int(len(frame)) if frame is not None else 0, "sources": [], "missing": [], "keys": {},
              "problems": report_problems}
    if frame is not None and len(frame):
        _whole_upload_checks(frame, report)
    elif ok_files:
        report_problems.append({"level": "error", "text": "No usable records were found in the upload."})
    ok = not any(p["level"] == "error" for r in reports for p in r["problems"]) and not any(p["level"] == "error" for p in report_problems)
    return (frame if ok else None), report, ok


def _map_rows(fr: FileRead, stem: str, rep: dict):
    keys = {_colkey(h): h for h in reversed(fr.header)}  # first column wins on a clash
    cols = {}
    for field, syns in SYNONYMS.items():
        cols[field] = next((keys[s] for s in syns if s in keys), None)
    if fr.geometry:
        cols["lat"] = cols["lat"] or "__geom_lat"
        cols["lon"] = cols["lon"] or "__geom_lon"
    rep["columns"] = {k: ("geometry" if v in ("__geom_lat", "__geom_lon") else v) for k, v in cols.items()}
    used = set(v for v in cols.values() if v)
    rep["ignored_columns"] = [h for h in fr.header if h not in used and not h.startswith("__geom_")]
    if cols["name"] is None:
        fr.add("error", "No name column. Add a column called name (property_name, hotel_name and title also work).")
    if cols["lat"] is None or cols["lon"] is None:
        miss = " and ".join(x for x, c in (("latitude", cols["lat"]), ("longitude", cols["lon"])) if c is None)
        fr.add("error", f"No {miss} column. Canon needs coordinates: add lat and lon columns (latitude / longitude, lng and long also work).")
    if fr.fatal:
        return None
    if cols["source"] is None:
        fr.add("info", f"No source column: every row of this file is source \"{stem}\".")
    out, empty_name, no_name_text, no_xy, out_range, zero, swapped_fix, dup, odd_kind, comma_dec = [], [], [], [], [], [], 0, [], Counter(), 0
    seen_ids = {}
    for rown, r in fr.rows:
        name = _text(r.get(cols["name"]))
        if name is None:
            empty_name.append(rown)
            continue
        if not norm(name):
            no_name_text.append(rown)
            continue
        lat_raw, lon_raw = r.get(cols["lat"]), r.get(cols["lon"])
        if isinstance(lat_raw, str) and re.fullmatch(r"\s*-?\d+,\d+\s*", lat_raw or ""):
            comma_dec += 1
        lat, lon = _num(lat_raw), _num(lon_raw)
        if lat is None or lon is None:
            no_xy.append(rown)
            lat = lon = None
        elif lat == 0 and lon == 0:
            zero.append(rown)
            lat = lon = None
        elif not (-90 <= lat <= 90 and -180 <= lon <= 180):
            out_range.append(rown)
            if -90 <= lon <= 90 and -180 <= lat <= 180:
                swapped_fix += 1
            lat = lon = None
        source = _text(r.get(cols["source"])) if cols["source"] else None
        source = source or stem
        sid = _text(r.get(cols["id"])) if cols["id"] else None
        sid = sid or f"{stem}:{rown}"
        if (source, sid) in seen_ids:
            dup.append((rown, sid, seen_ids[(source, sid)]))
            continue
        seen_ids[(source, sid)] = rown
        kind, odd = _kind(r.get(cols["kind"])) if cols["kind"] else ("lodging", False)
        if odd:
            odd_kind[str(r.get(cols["kind"])).strip()] += 1
        phone_raw = _text(r.get(cols["phone"])) if cols["phone"] else None
        website = _text(r.get(cols["website"])) if cols["website"] else None
        city = _text(r.get(cols["city"])) if cols["city"] else None
        out.append({"source": source, "src_id": sid, "name": name, "alt_names": _alts(r.get(cols["alt_names"])) if cols["alt_names"] else None,
                    "lat": lat, "lon": lon, "kind": kind,
                    "street": _text(r.get(cols["street"])) if cols["street"] else None,
                    "postcode": _text(r.get(cols["postcode"])) if cols["postcode"] else None,
                    "city": city, "grp": re.sub(r"\s+", " ", city.lower()) if city else "upload",
                    "brand": _text(r.get(cols["brand"])) if cols["brand"] else None,
                    "stars": _stars(r.get(cols["stars"])) if cols["stars"] else None, "confidence": np.nan,
                    "qid": qid_of(r.get(cols["qid"])) if cols["qid"] else None, "phone_raw": phone_raw, "phone8": phone8(phone_raw),
                    "website": website, "domain": domain_of(website), "url_key": url_key_of(website), "file": fr.name, "row": rown})
    n_rows = len(fr.rows)
    if empty_name:
        fr.add("warn", f"{_plural(len(empty_name), 'row')} {'has' if len(empty_name) == 1 else 'have'} an empty name and "
                       f"{'was' if len(empty_name) == 1 else 'were'} skipped ({_rows_text(empty_name)}).")
    if no_name_text:
        fr.add("warn", f"{_plural(len(no_name_text), 'name')} {'has' if len(no_name_text) == 1 else 'have'} no letters or digits and "
                       f"{'was' if len(no_name_text) == 1 else 'were'} skipped ({_rows_text(no_name_text)}).")
    if dup:
        r0 = dup[0]
        fr.add("warn", f"{_plural(len(dup), 'row')} repeat{'s' if len(dup) == 1 else ''} an id already used by the same source and "
                       f"{'was' if len(dup) == 1 else 'were'} skipped (id {r0[1]!r} on rows {r0[2]} and {r0[0]}). Only the first row of each id is kept.")
    if no_xy:
        fr.add("warn", f"{_plural(len(no_xy), 'row')} {'has' if len(no_xy) == 1 else 'have'} no usable coordinates ({_rows_text(no_xy)}): "
                       "missing or not a number. They are matched by name only and never merged automatically.")
    if zero:
        fr.add("warn", f"{_plural(len(zero), 'row')} {'sits' if len(zero) == 1 else 'sit'} at latitude 0, longitude 0 ({_rows_text(zero)}), "
                       "which is a placeholder, not a place. Those coordinates were dropped.")
    if out_range:
        hint = " Latitude and longitude look swapped." if swapped_fix == len(out_range) else ""
        fr.add("warn", f"{_plural(len(out_range), 'row')} {'has' if len(out_range) == 1 else 'have'} coordinates out of range (latitude beyond ±90 "
                       f"or longitude beyond ±180) ({_rows_text(out_range)}). Those coordinates were dropped.{hint}")
    if comma_dec:
        fr.add("info", f"{_plural(comma_dec, 'coordinate')} used a decimal comma (25,2048) and {'was' if comma_dec == 1 else 'were'} read as 25.2048.")
    if odd_kind:
        ex = ", ".join(f"{k!r}" for k, _ in odd_kind.most_common(3))
        fr.add("warn", f"{_plural(sum(odd_kind.values()), 'row')} {'has' if sum(odd_kind.values()) == 1 else 'have'} a kind Canon does not know "
                       f"({ex}); treated as lodging. Use lodging or attraction.")
    rep["usable"] = len(out)
    if not out:
        fr.add("error", "No row of this file is usable (each needs a name).")
        return None
    with_xy = sum(1 for o in out if o["lat"] is not None)
    if with_xy == 0:
        fr.add("error", "No row of this file has usable coordinates. Canon needs latitude and longitude for at least some records "
                        "(decimal degrees, e.g. 25.2048 and 55.2708).")
        return None
    if with_xy < len(out) / 2:
        fr.add("warn", f"Only {with_xy:,} of {len(out):,} usable rows have coordinates; most pairs from this file will go to review.")
    df = pd.DataFrame(out)
    srcs = list(dict.fromkeys(df["source"]))
    rep["sources"] = srcs
    rep["source"] = srcs[0] if len(srcs) == 1 else None
    if n_rows and len(out) < n_rows:
        fr.add("info", f"{len(out):,} of {n_rows:,} rows are usable.")
    return df


def _whole_upload_checks(frame: pd.DataFrame, report: dict) -> None:
    probs = report["problems"]
    srcs = list(dict.fromkeys(frame["source"]))
    report["sources"] = srcs
    report["by_source"] = {s: int(v) for s, v in frame.groupby("source", sort=False).size().items()}
    # the same (source, id) in two files
    d = frame.duplicated(["source", "src_id"], keep="first")
    if d.any():
        ex = frame[d].iloc[0]
        probs.append({"level": "warn", "text": f"{_plural(int(d.sum()), 'record')} repeat an id of the same source found in another file "
                                               f"(e.g. {ex['src_id']!r} of {ex['source']}); only the first is kept."})
        frame.drop(index=frame.index[d], inplace=True)
        frame.reset_index(drop=True, inplace=True)
    report["records"] = int(len(frame))
    if len(srcs) < 2:
        probs.append({"level": "error", "text": "Canon matches across sources, and this upload has one source. Add a second feed or a `source` column."})
    if len(frame) > MAX_RECORDS:
        probs.append({"level": "error", "text": f"The upload has {len(frame):,} records; a local run is limited to {MAX_RECORDS:,}. Split it by city."})
    for field, effect in FEATURE_EFFECT.items():
        col = frame[field]
        if not col.notna().any():
            report["missing"].append({"field": field, "effect": effect})
    if not set(srcs) <= TRAIN_SOURCES:
        report["missing"].append({"field": "src_pair", "effect": "The model was trained on pairs of overture / osm / wikidata / wikivoyage "
                                  "records; other source names reach its src_pair feature as an unknown category (as in the "
                                  "MakeMyTrip × Goibibo transfer test)."})
    if not frame["city"].notna().any():
        probs.append({"level": "info", "text": "No city column: all records are compared as one group."})
    else:
        g = frame.groupby("grp")["source"].nunique()
        lonely = g[g < 2]
        if len(lonely):
            ex = ", ".join(repr(x) for x in list(lonely.index[:3]))
            probs.append({"level": "warn", "text": f"Records are compared only within the same city value. {_plural(len(lonely), 'city value')} "
                                                   f"({ex}) {'has' if len(lonely) == 1 else 'have'} records from one source only, so "
                                                   f"{'it has' if len(lonely) == 1 else 'they have'} nothing to be compared with. If the feeds spell "
                                                   "a city differently (Delhi / New Delhi), make the spellings agree or drop the city column."})
    report["keys"] = {"qid": bool(frame["qid"].notna().any()), "phone": bool(frame["phone8"].notna().any()),
                      "website": bool(frame["url_key"].notna().any())}
    report["keys_note"] = "Keys are used only as stage-0 rules (shared Wikidata QID, or rare phone / URL plus proximity) and weak labels; never as model features."
    report["with_coordinates"] = int(frame["lat"].notna().sum())


# ---------------------------------------------------------------------------- store
class UploadStore:
    def __init__(self):
        self._lock = threading.Lock()
        self._items: OrderedDict = OrderedDict()
        self._n = 0

    def add(self, frame: pd.DataFrame, report: dict) -> str:
        with self._lock:
            self._n += 1
            uid = f"u{self._n}"
            self._items[uid] = (frame, report)
            while len(self._items) > KEEP_UPLOADS:
                self._items.popitem(last=False)
            return uid

    def get(self, uid: str):
        with self._lock:
            item = self._items.get(uid)
        if item is None:
            raise UserError(f"Upload {uid} is not in memory (the server keeps the last {KEEP_UPLOADS}); upload the files again.", status=404)
        return item


UPLOADS = UploadStore()
