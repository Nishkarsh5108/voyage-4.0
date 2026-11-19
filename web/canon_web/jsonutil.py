"""JSON encoding for the API: numpy scalars and arrays become plain values, NaN / inf / pandas NA become null."""
from __future__ import annotations

import json
import math

import numpy as np


def clean(o):
    if o is None or isinstance(o, (str, bool)):
        return o
    if isinstance(o, (np.bool_,)):
        return bool(o)
    if isinstance(o, (int, np.integer)):
        return int(o)
    if isinstance(o, (float, np.floating)):
        f = float(o)
        return f if math.isfinite(f) else None
    if isinstance(o, dict):
        return {str(k): clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple, set, frozenset, np.ndarray)):
        return [clean(v) for v in (sorted(o) if isinstance(o, (set, frozenset)) else o)]
    try:
        import pandas as pd
        if o is pd.NA or o is pd.NaT:
            return None
    except ImportError:  # pragma: no cover
        pass
    return str(o)


def dumps(o) -> str:
    return json.dumps(clean(o), ensure_ascii=False, allow_nan=False, separators=(",", ":"))


def scalar(v):
    """One value from a pandas cell: None for missing, plain Python otherwise."""
    if v is None:
        return None
    if isinstance(v, (list, tuple, np.ndarray)):
        return [clean(x) for x in v]
    try:
        import pandas as pd
        if pd.isna(v):
            return None
    except (TypeError, ValueError):
        pass
    return clean(v)
