"""Download small public (ungated) Hugging Face datasets used as supplier-shaped sightseeing content.

Output: data/raw/<target>/<file>
These are third-party crawls with no stated licence unless noted: research / benchmarking only.

Usage: python -I scripts/download/hf_public.py
"""
from pathlib import Path

from huggingface_hub import hf_hub_download

ROOT = Path(__file__).resolve().parents[2]

FILES = [
    # (repo_id, filename, target folder)
    ("malaysia-ai/crawl-klook", "full-singapore-klook.json", "klook_hf_malaysia_ai"),
    ("malaysia-ai/crawl-klook", "full-malaysia-klook.json", "klook_hf_malaysia_ai"),
    ("jsjang0104/klook_data_group6_2026-1", "klook_data.json", "klook_hf_group6"),
]

for repo, name, target in FILES:
    dest = ROOT / "data" / "raw" / target
    dest.mkdir(parents=True, exist_ok=True)
    if (dest / name).exists():
        print(f"{repo}/{name}: exists")
        continue
    p = hf_hub_download(repo_id=repo, filename=name, repo_type="dataset", local_dir=dest)
    print(f"{repo}/{name}: ok {Path(p).stat().st_size / 1e6:.1f} MB")
