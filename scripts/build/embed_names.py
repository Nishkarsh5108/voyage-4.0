"""Multilingual embeddings of listing names (primary + alternate names), for cross-script matching.

Model: intfloat/multilingual-e5-small (MIT licence, 384 dimensions). Runs on a GPU if one is free, else CPU.
Needs torch + transformers, which the project venv does not carry; run with an environment that has them, e.g.
    C:\\Users\\nishk\\anaconda3\\envs\\torch_gpu\\python.exe -I scripts/build/embed_names.py

Input : data/interim/listings.parquet
Output: data/interim/name_emb/strings.parquet (string, row) and data/interim/name_emb/e5_small.npy (float16, L2-normalised)
"""
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
import torch
from transformers import AutoModel, AutoTokenizer

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "data" / "interim" / "name_emb"
OUT.mkdir(parents=True, exist_ok=True)
MODEL = sys.argv[1] if len(sys.argv) > 1 else "intfloat/multilingual-e5-small"

L = pd.read_parquet(ROOT / "data" / "interim" / "listings.parquet", columns=["name", "alt_names"])
strings = set(L["name"].dropna().astype(str))
for alts in L["alt_names"]:
    if alts is not None:
        strings.update(str(a) for a in alts if a)
strings = sorted(s.strip() for s in strings if s and s.strip())
print(f"{len(strings):,} distinct name strings", flush=True)

dev = "cuda" if torch.cuda.is_available() else "cpu"
tok = AutoTokenizer.from_pretrained(MODEL)
model = AutoModel.from_pretrained(MODEL).to(dev).eval()
if dev == "cuda":
    model = model.half()
order = np.argsort([len(s) for s in strings])  # length-sorted batches waste less padding
emb = np.zeros((len(strings), model.config.hidden_size), dtype=np.float16)
t0, bs = time.time(), 512
with torch.inference_mode():
    for s in range(0, len(strings), bs):
        idx = order[s:s + bs]
        batch = tok(["query: " + strings[i] for i in idx], padding=True, truncation=True, max_length=48, return_tensors="pt").to(dev)
        h = model(**batch).last_hidden_state
        m = batch["attention_mask"].unsqueeze(-1).to(h.dtype)
        v = torch.nn.functional.normalize((h * m).sum(1) / m.sum(1), dim=-1)
        emb[idx] = v.float().cpu().numpy().astype(np.float16)
        if s % (bs * 100) == 0:
            print(f"  {s:,}/{len(strings):,} {time.time() - t0:.0f}s", flush=True)
np.save(OUT / "e5_small.npy", emb)
pd.DataFrame({"string": strings, "row": np.arange(len(strings))}).to_parquet(OUT / "strings.parquet")
print(f"done on {dev} in {time.time() - t0:.0f}s -> {OUT}", flush=True)
