"""Preset inputs: the 12 benchmark cities (four open sources) and the two real Indian OTA feeds.

A city preset is exactly the slice of training data for that city: listings.parquet with the training filter
(`lat` known and inside the city's bounding box), every kind (lodging and attractions, so blocking and the crowding
feature see what training saw), rows in file order. The OTA preset is scripts/train/ota_matcher.py's `load`, ported as is.
"""
from __future__ import annotations

import json
import re
import threading

import numpy as np
import pandas as pd

from canon.match import norm

from . import CACHE_DIR, LISTINGS, OTA_FILES, REBUILD_LISTINGS, UserError
from .artefacts import CITY_ORDER

SRC = ["overture", "osm", "wikidata", "wikivoyage"]  # training order (canon.match.block iterates source pairs in this order)
CITY_LABEL = {"dubai": "Dubai", "bangkok": "Bangkok", "singapore": "Singapore", "delhi": "Delhi", "mumbai": "Mumbai", "goa": "Goa",
              "london": "London", "paris": "Paris", "amsterdam": "Amsterdam", "barcelona": "Barcelona", "vienna": "Vienna", "milan": "Milan"}
SRC_LABEL = {"overture": "Overture", "osm": "OpenStreetMap", "wikidata": "Wikidata", "wikivoyage": "Wikivoyage"}
OTA_ID = "ota_india"


class Ingest:
    """What a run ingests: records before `prepare`, the blocking group column and the source order."""

    def __init__(self, frame, group_col, sources, label, preset=None, upload_id=None, loco_city=None, kind="city"):
        self.frame, self.group_col, self.sources, self.label = frame, group_col, sources, label
        self.preset, self.upload_id, self.loco_city, self.kind = preset, upload_id, loco_city, kind


# ---------------------------------------------------------------------------- OTA feeds (scripts/train/ota_matcher.py)
def _pin(addr):
    m = re.search(r"\b(\d{6})\b", addr) if isinstance(addr, str) else None
    return m.group(1) if m else None


def _load_ota(path, source, addr_col, star_fn):
    d = pd.read_csv(path, dtype=str, on_bad_lines="skip")
    d = d[d["property_id"].notna()].drop_duplicates("property_id")
    lat, lon = pd.to_numeric(d["latitude"], errors="coerce"), pd.to_numeric(d["longitude"], errors="coerce")
    ok = lat.between(6, 37.5) & lon.between(68, 97.5)  # inside India; zeros and swapped values become missing
    return pd.DataFrame({
        "source": source, "group": "india", "src_id": d["property_id"].to_numpy(), "name": d["property_name"].to_numpy(), "alt_names": None,
        "lat": lat.where(ok).to_numpy(), "lon": lon.where(ok).to_numpy(), "kind": "lodging", "street": d[addr_col].to_numpy(),
        "postcode": d[addr_col].map(_pin).to_numpy(), "brand": None, "stars": star_fn(d).to_numpy(), "confidence": np.nan,
        "city": d["city"].str.lower().str.replace(r"[^a-z]", "", regex=True).to_numpy(), "state": d["state"].to_numpy(),
    })


def ota_frame() -> pd.DataFrame:
    miss = [str(p) for p in OTA_FILES.values() if not p.exists()]
    if miss:
        raise UserError("The MakeMyTrip / Goibibo feeds are not on this machine.", status=503,
                        fix="kaggle datasets download -d PromptCloudHQ/hotels-on-makemytrip -p data/raw/makemytrip_hotels --unzip; "
                            "kaggle datasets download -d PromptCloudHQ/hotels-on-goibibo -p data/raw/goibibo_hotels --unzip",
                        detail=", ".join(miss))
    # MakeMyTrip labels 57% of its catalogue "1 star", which reads as its default for unrated; treated as unknown (as in ota_matcher.py)
    mmt = _load_ota(OTA_FILES["makemytrip"], "makemytrip", "property_address",
                    lambda d: pd.to_numeric(d["hotel_star_rating"].str.extract(r"(\d)", expand=False), errors="coerce").where(lambda s: s > 1))
    gob = _load_ota(OTA_FILES["goibibo"], "goibibo", "address",
                    lambda d: pd.to_numeric(d["hotel_star_rating"], errors="coerce").where(lambda s: s > 0))
    return pd.concat([mmt, gob], ignore_index=True).dropna(subset=["name"])


# ---------------------------------------------------------------------------- store
class PresetStore:
    def __init__(self):
        self._lock = threading.Lock()
        self._listings = None
        self._raw_listings = None
        self._summary = None

    def listings(self) -> pd.DataFrame:
        """listings.parquet with the training filter, every city, file order (city_matcher.py `records`)."""
        with self._lock:
            if self._listings is None:
                if not LISTINGS.exists():
                    raise UserError("data/interim/listings.parquet is missing.", status=503, fix=REBUILD_LISTINGS)
                G = pd.read_parquet(LISTINGS)
                self._raw_listings = G
                self._listings = G[G["lat"].notna() & G["in_bbox"].fillna(False)].reset_index(drop=True)
            return self._listings

    def raw_listings(self) -> pd.DataFrame:
        """listings.parquet unfiltered (the tours gazetteer is built from it, as in build_demo_data.py)."""
        self.listings()
        return self._raw_listings

    def ingest(self, preset: str) -> Ingest:
        if preset == OTA_ID:
            return Ingest(ota_frame(), "group", ["makemytrip", "goibibo"], "Goibibo × MakeMyTrip", preset=preset, kind="ota")
        if preset not in CITY_ORDER:
            raise UserError(f"There is no preset called {preset!r}.", status=404, detail="presets: " + ", ".join(CITY_ORDER + [OTA_ID]))
        L = self.listings()
        frame = L[L["city"] == preset].reset_index(drop=True)
        return Ingest(frame, "city", SRC, CITY_LABEL[preset], preset=preset, loco_city=preset, kind="city")

    # ------------------------------------------------------------------ summary for GET /api/presets
    def _cache_key(self) -> str:
        parts = []
        for p in [LISTINGS, *OTA_FILES.values()]:
            parts.append(f"{p.name}:{p.stat().st_size}:{int(p.stat().st_mtime)}" if p.exists() else f"{p.name}:missing")
        return "|".join(parts)

    def summary(self) -> list:
        if self._summary is not None:
            return self._summary
        key = self._cache_key()
        cache = CACHE_DIR / "presets.json"
        try:
            c = json.loads(cache.read_text(encoding="utf-8"))
            if c.get("key") == key:
                self._summary = c["presets"]
                return self._summary
        except (OSError, ValueError):
            pass
        out = []
        if LISTINGS.exists():
            L = self.listings()
            nn_ok = L["name"].map(norm).str.len() > 0  # what prepare() keeps
            for city in CITY_ORDER:
                g = L[(L["city"] == city) & nn_ok]
                by_src = g.groupby("source").size().to_dict()
                out.append({"id": city, "label": CITY_LABEL[city], "group": "city", "records": int(len(g)),
                            "lodging": int((g["kind"] == "lodging").sum()), "sources": [s for s in SRC if by_src.get(s)],
                            "by_source": {s: int(by_src[s]) for s in SRC if by_src.get(s)},
                            "note": "Overture, OpenStreetMap, Wikidata, Wikivoyage. Hotels and attractions. "
                                    "Weak labels from shared Wikidata QIDs / rare phones / URLs; not hand-labelled."})
        try:
            o = ota_frame()
            o = o[o["name"].map(norm).str.len() > 0]
            by_src = o.groupby("source").size().to_dict()
            out.append({"id": OTA_ID, "label": "Goibibo × MakeMyTrip", "group": "ota", "records": int(len(o)), "lodging": int(len(o)),
                        "sources": ["makemytrip", "goibibo"], "by_source": {k: int(v) for k, v in by_src.items()},
                        "with_coordinates": int(o["lat"].notna().sum()),
                        "note": "Two real Indian OTA feeds (2016 crawls). No labels. Pairs without coordinates on both sides are never auto-accepted."})
        except UserError:
            pass
        self._summary = out
        try:
            CACHE_DIR.mkdir(parents=True, exist_ok=True)
            cache.write_text(json.dumps({"key": key, "presets": out}, ensure_ascii=False, indent=1), encoding="utf-8")
        except OSError:
            pass
        return out


PRESETS = PresetStore()
