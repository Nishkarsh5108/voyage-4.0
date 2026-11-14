"""Download Overture Maps Places for every city bbox.

Output: data/raw/overture/<city>.parquet (GeoParquet, full place schema, all categories).
Licence: CDLA-Permissive-2.0 (OSM-derived parts excepted). Shippable.

Usage: python -I scripts/download/overture_places.py [--release 2026-10-21.0] [--cities dubai,bangkok]
"""
import argparse
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from cities import CITIES  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "data" / "raw" / "overture"
CLI = Path(sys.executable).with_name("overturemaps.exe" if sys.platform == "win32" else "overturemaps")


def fetch(city: str, release: str | None) -> str:
    out = OUT / f"{city}.parquet"
    if out.exists() and out.stat().st_size > 0:
        return f"{city}: exists ({out.stat().st_size / 1e6:.1f} MB)"
    w, s, e, n = CITIES[city]["bbox"]
    tmp = out.with_suffix(".parquet.part")
    cmd = [str(CLI), "download", f"--bbox={w},{s},{e},{n}", "-f", "geoparquet", "--type=place", "-o", str(tmp)]
    if release:
        cmd += ["-r", release]
    t0 = time.time()
    for attempt in range(3):
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode == 0 and tmp.exists() and tmp.stat().st_size > 0:
            tmp.replace(out)
            return f"{city}: ok {out.stat().st_size / 1e6:.1f} MB in {time.time() - t0:.0f}s"
        time.sleep(5 * (attempt + 1))
    return f"{city}: FAILED rc={r.returncode} {r.stderr[-400:]}"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--release", default=None)
    ap.add_argument("--cities", default=",".join(CITIES))
    ap.add_argument("--workers", type=int, default=3)
    a = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    with ThreadPoolExecutor(a.workers) as ex:
        for msg in ex.map(lambda c: fetch(c, a.release), a.cities.split(",")):
            print(msg, flush=True)


if __name__ == "__main__":
    main()
