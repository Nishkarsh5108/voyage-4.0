"""Print the shape of a nested JSON file: top-level type, length, and a truncated first record.

Usage: python -I scripts/eda/peek_json.py <file> [<file> ...]
"""
import json
import sys


def trunc(o, depth=0):
    if isinstance(o, dict):
        if depth > 3:
            return f"{{...{len(o)} keys}}"
        return {k: trunc(v, depth + 1) for k, v in list(o.items())[:40]}
    if isinstance(o, list):
        if depth > 3:
            return f"[...{len(o)} items]"
        return [trunc(v, depth + 1) for v in o[:2]] + ([f"...(+{len(o) - 2})"] if len(o) > 2 else [])
    if isinstance(o, str) and len(o) > 140:
        return o[:140] + "..."
    return o


for path in sys.argv[1:]:
    with open(path, encoding="utf-8") as f:
        head = f.read(1)
        f.seek(0)
        if head in "[{":
            try:
                data = json.load(f)
            except json.JSONDecodeError:
                f.seek(0)
                data = [json.loads(line) for line in f if line.strip()]
        else:
            data = [json.loads(line) for line in f if line.strip()]
    print(f"\n=== {path}: {type(data).__name__} len={len(data)}")
    first = data[0] if isinstance(data, list) else {k: data[k] for k in list(data)[:3]}
    print(json.dumps(trunc(first), ensure_ascii=False, indent=1)[:3500])
