"""Backend of the local Canon site (web/serve.py): presets, uploads, the matching pipeline, benches and HTTP handlers.

Everything runs on this machine. The pipeline calls the library (canon.match, canon.cascade, canon.rooms, canon.activities)
and the trained artefacts under data/processed/city_matcher; nothing here re-implements or replaces model output.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))  # the featurizer joblib unpickles canon.match.Featurizer

DATA = ROOT / "data"
CM = DATA / "processed" / "city_matcher"
LOCO_DIR = CM / "loco"
LISTINGS = DATA / "interim" / "listings.parquet"
KLOOK = DATA / "interim" / "klook_products.parquet"
OTA_FILES = {"makemytrip": DATA / "raw" / "makemytrip_hotels" / "makemytrip_com-travel_sample.csv",
             "goibibo": DATA / "raw" / "goibibo_hotels" / "goibibo_com-travel_sample.csv"}
REVIEW_DIR = DATA / "processed" / "web_review"
CACHE_DIR = DATA / "processed" / "web_cache"
STATIC = ROOT / "web" / "static"
NUMBERS = ROOT / "submission" / "round1" / "numbers.json"

PY = r".venv\Scripts\python.exe"
REBUILD_LISTINGS = rf"{PY} -I -X utf8 scripts\build\build_listings.py"
REBUILD_MODEL = rf"{PY} -I -X utf8 scripts\train\city_matcher.py"
REBUILD_LOCO = rf"{PY} -I -X utf8 scripts\train\loco_models.py"


class UserError(Exception):
    """A problem the visitor can fix; becomes an HTTP 4xx/5xx with a plain sentence."""

    def __init__(self, message: str, status: int = 400, fix: str | None = None, detail: str | None = None):
        super().__init__(message)
        self.status, self.fix, self.detail = status, fix, detail

    def payload(self) -> dict:
        out = {"error": str(self)}
        if self.detail:
            out["detail"] = self.detail
        if self.fix:
            out["fix"] = self.fix
        return out
