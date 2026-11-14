"""Quick, memory-bounded schema peek at any csv / parquet / json file.

Usage: python -I scripts/eda/peek.py <file> [<file> ...]
"""
import sys

import duckdb

con = duckdb.connect()
con.execute("SET memory_limit='1GB'; SET threads=2;")


def reader(path: str) -> str:
    p = path.replace("\\", "/")
    if p.endswith(".parquet"):
        return f"read_parquet('{p}')"
    if p.endswith((".json", ".jsonl")):
        return f"read_json_auto('{p}', maximum_object_size=200000000, sample_size=2000)"
    return f"read_csv_auto('{p}', sample_size=20000, ignore_errors=true)"


for path in sys.argv[1:]:
    src = reader(path)
    print(f"\n=== {path}")
    n = con.execute(f"SELECT count(*) FROM {src}").fetchone()[0]
    cols = con.execute(f"DESCRIBE SELECT * FROM {src}").fetchall()
    print(f"rows={n:,} cols={len(cols)}")
    row = con.execute(f"SELECT * FROM {src} LIMIT 1").fetchone()
    for (name, typ, *_), val in zip(cols, row):
        v = repr(val)
        print(f"  {name:<34} {typ:<12} {v[:110]}")
