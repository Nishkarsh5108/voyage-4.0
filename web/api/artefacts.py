"""Trained artefacts: the featurizer joblib, the final booster and the 12 leave-one-city-out boosters. Loaded lazily, once."""
from __future__ import annotations

import json
import threading

import joblib
import lightgbm as lgb

from . import CM, LOCO_DIR, REBUILD_LOCO, REBUILD_MODEL, UserError

CITY_ORDER = ["dubai", "bangkok", "singapore", "delhi", "mumbai", "goa", "london", "paris", "amsterdam", "barcelona", "vienna", "milan"]
MODEL_FILES = ("model.lgb", "featurizer_no_emb.joblib")


class ModelStore:
    def __init__(self):
        self._lock = threading.Lock()
        self._art = None
        self._boosters: dict = {}
        self._predict_locks: dict = {}

    # ------------------------------------------------------------------ presence
    @staticmethod
    def missing() -> list:
        return [f"data/processed/city_matcher/{f}" for f in MODEL_FILES if not (CM / f).exists()]

    @staticmethod
    def loco_cities() -> list:
        return [c for c in CITY_ORDER if (LOCO_DIR / f"model_{c}.lgb").exists()]

    def require(self) -> None:
        miss = self.missing()
        if miss:
            raise UserError("The trained matcher is missing, so nothing can be scored.", status=503, fix=REBUILD_MODEL,
                            detail="missing: " + ", ".join(miss))

    # ------------------------------------------------------------------ loading
    def art(self) -> dict:
        self.require()
        with self._lock:
            if self._art is None:
                self._art = joblib.load(CM / "featurizer_no_emb.joblib")
            return self._art

    def booster(self, key: str):
        """key: "final" or a city name (its leave-one-city-out booster). Returns None when a LOCO file is absent."""
        with self._lock:
            if key in self._boosters:
                return self._boosters[key]
            path = CM / "model.lgb" if key == "final" else LOCO_DIR / f"model_{key}.lgb"
            if not path.exists():
                if key == "final":
                    raise UserError("The trained matcher is missing, so nothing can be scored.", status=503, fix=REBUILD_MODEL)
                return None
            self._boosters[key] = lgb.Booster(model_file=str(path))
            self._predict_locks[key] = threading.Lock()
            return self._boosters[key]

    def predict(self, key: str, X, **kw):
        b = self.booster(key)
        if b is None:
            raise UserError(f"The leave-one-city-out model for {key} is missing.", status=503, fix=REBUILD_LOCO)
        with self._predict_locks[key]:
            return b.predict(X, **kw)

    # ------------------------------------------------------------------ status
    def status(self) -> dict:
        miss = self.missing()
        out = {"model": {"ready": not miss, "missing": miss, "rebuild": REBUILD_MODEL},
               "loco": {"ready": len(self.loco_cities()) == len(CITY_ORDER), "cities": self.loco_cities(), "rebuild": REBUILD_LOCO,
                        "note": "Labelled pairs of a preset city are scored by the booster trained without that city, as in training."}}
        manifest = LOCO_DIR / "manifest.json"
        if manifest.exists():
            try:
                m = json.loads(manifest.read_text(encoding="utf-8"))
                out["loco"]["parity_max_abs_diff"] = m.get("max_abs_diff_all_cities")
                out["loco"]["built"] = m.get("built")
            except (OSError, ValueError):
                pass
        if not miss:
            try:
                art = self.art()
                out.update({"t_accept": art["t_accept"], "t_reject": art["t_reject"], "features": list(art["features"]),
                            "src_pair_categories": list(art["src_pair_categories"]), "blocking": dict(art["blocking"])})
            except Exception as e:  # noqa: BLE001 - a broken file is reported, not raised
                out["model"]["ready"] = False
                out["model"]["error"] = f"The model files exist but could not be loaded: {e}"
        return out


MODELS = ModelStore()
