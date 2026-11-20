"""Room mapping: neural-embedding matchers on the same synthetic second supplier as rooms_benchmark.py.

The question a reviewer asks first: would an off-the-shelf multilingual sentence embedding do what the attribute parser
does? This script scores the exact 50,310 renamed strings that rooms_benchmark.py generated (saved to
data/interim/rooms_bench_queries.parquet) with:
  * zero-shot embedding matchers (multilingual-e5-small, multilingual-e5-base): nearest room of the same hotel by cosine,
    abstaining below a cosine floor or when the top two are too close;
  * the cascade the architecture proposes: the parser first, the embedding only where the parser abstains.
Thresholds are picked on a 20% split of hotels and reported on the other 80%, so no number is tuned on what it reports.

GPU env: C:\\Users\\nishk\\anaconda3\\envs\\torch_gpu\\python.exe -X utf8 scripts\\train\\rooms_semantic_baseline.py
Output : reports/models/rooms_semantic.{md,json}
"""
import json
import sys
import zlib
from pathlib import Path

import numpy as np
import pandas as pd
import torch
import torch.nn.functional as TF
from transformers import AutoModel, AutoTokenizer

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from canon.rooms import parse_room  # noqa: E402

REP = ROOT / "reports" / "models"
DEV = "cuda" if torch.cuda.is_available() else "cpu"
MODELS = ["intfloat/multilingual-e5-small", "intfloat/multilingual-e5-base"]

Q = pd.read_parquet(ROOT / "data" / "interim" / "rooms_bench_queries.parquet")
Q["dev"] = Q["hotel"].map(lambda h: zlib.crc32(h.encode()) % 5 == 0)
hotel_rooms = Q.groupby("hotel")["truth"].apply(lambda s: list(dict.fromkeys(s))).to_dict()
strings = sorted(set(Q["query"]) | set(Q["truth"]))
sid = {s: k for k, s in enumerate(strings)}
parsed = {s: parse_room(s) for s in set(Q["truth"]) | set(Q["query"])}


def parser_pick(q, rooms):
    sig = parsed[q].signature()
    hits = [r for r in rooms if parsed[r].signature() == sig]
    return hits[0] if len(hits) == 1 else None


def embed(name):
    tok = AutoTokenizer.from_pretrained(name)
    model = AutoModel.from_pretrained(name).to(DEV).eval()
    out = np.empty((len(strings), model.config.hidden_size), np.float32)
    with torch.no_grad(), torch.autocast(device_type="cuda", dtype=torch.float16, enabled=DEV == "cuda"):
        for s in range(0, len(strings), 512):
            b = tok(["query: " + x for x in strings[s:s + 512]], padding=True, truncation=True, max_length=48, return_tensors="pt").to(DEV)
            h = model(**b).last_hidden_state
            m = b["attention_mask"].unsqueeze(-1).to(h.dtype)
            out[s:s + 512] = TF.normalize(((h * m).sum(1) / m.sum(1).clamp(min=1)).float(), dim=-1).cpu().numpy()
    return out


def top2(E):
    """For every query: best room, its cosine, and the margin over the second-best room of the same hotel."""
    best, cos1, margin = [], np.empty(len(Q)), np.empty(len(Q))
    for k, (h, q) in enumerate(zip(Q["hotel"], Q["query"])):
        rooms = hotel_rooms[h]
        c = E[[sid[r] for r in rooms]] @ E[sid[q]]
        o = np.argsort(-c)
        best.append(rooms[o[0]])
        cos1[k] = c[o[0]]
        margin[k] = c[o[0]] - (c[o[1]] if len(o) > 1 else -1.0)
    return np.array(best, dtype=object), cos1, margin


def evaluate(pick, mask):
    mapped = np.array([p is not None for p in pick])[mask]
    correct = np.array([p is not None and p == t for p, t in zip(pick, Q["truth"])])[mask]
    return {"coverage": float(mapped.mean()), "precision": float(correct.sum() / max(mapped.sum(), 1)), "correct_of_all": float(correct.mean())}


def choose(best, cos1, margin, base=None, min_precision=0.99):
    """Cosine floor and margin picked on the dev hotels: most correct mappings at >= 99% precision."""
    dev = Q["dev"].to_numpy()
    top = (-1.0, 0.0, 0.0)
    for floor in np.round(np.arange(0.70, 0.99, 0.01), 2):
        for mg in (0.0, 0.01, 0.02, 0.03, 0.05, 0.08):
            pick = np.where((cos1 >= floor) & (margin >= mg), best, None)
            if base is not None:
                pick = np.where(base != None, base, pick)  # noqa: E711
            r = evaluate(pick, dev)
            if r["precision"] >= min_precision and r["correct_of_all"] > top[0]:
                top = (r["correct_of_all"], floor, mg)
    return top[1], top[2]


res = {"queries": len(Q), "hotels": int(Q["hotel"].nunique()), "dev_hotels": int(Q.loc[Q["dev"], "hotel"].nunique()), "methods": {}}
test = ~Q["dev"].to_numpy()
p_parser = np.array([parser_pick(q, hotel_rooms[h]) for h, q in zip(Q["hotel"], Q["query"])], dtype=object)
res["methods"]["attribute parser (canon.rooms)"] = {"test": evaluate(p_parser, test)}
for name in MODELS:
    try:
        E = embed(name)
    except Exception as e:  # a model that cannot be downloaded is reported, not faked
        res["methods"][name] = {"error": str(e)[:200]}
        continue
    best, cos1, margin = top2(E)
    res["methods"][f"{name} top-1, no abstention"] = {"test": evaluate(best, test)}
    fl, mg = choose(best, cos1, margin)
    pick = np.where((cos1 >= fl) & (margin >= mg), best, None)
    res["methods"][f"{name}, abstains (floor {fl}, margin {mg})"] = {"test": evaluate(pick, test), "floor": fl, "margin": mg}
    fl2, mg2 = choose(best, cos1, margin, base=p_parser)
    casc = np.where(p_parser != None, p_parser, np.where((cos1 >= fl2) & (margin >= mg2), best, None))  # noqa: E711
    res["methods"][f"parser, then {name.split('/')[-1]} where it abstains"] = {"test": evaluate(casc, test), "floor": fl2, "margin": mg2}
    by_style = {}
    for st in Q["style"].unique():
        m = test & (Q["style"].to_numpy() == st)
        by_style[st] = {"embedding_abstaining": evaluate(pick, m), "parser": evaluate(p_parser, m), "cascade": evaluate(casc, m)}
    res["methods"][f"{name}, abstains (floor {fl}, margin {mg})"]["by_style"] = by_style
    print(name, json.dumps({k: v["test"] for k, v in res["methods"].items() if "test" in v}), flush=True)
(REP / "rooms_semantic.json").write_text(json.dumps(res, indent=1), encoding="utf-8")


def pc(v):
    return f"{v:.1%}"


L = ["# Room mapping: neural-embedding matchers on the synthetic second supplier", "",
     "Generated by `scripts/train/rooms_semantic_baseline.py` on the exact renamed strings of `reports/models/rooms.md` "
     f"({res['queries']:,} strings, {res['hotels']:,} real hotels). Same task: map each renamed string to the right room of its own hotel, "
     "or abstain. Cosine floors and margins are picked on 20% of the hotels "
     f"({res['dev_hotels']:,}) for the most correct mappings at 99% precision, and every number below is on the other 80%.", "",
     "| Method | Coverage | Precision of mapped | Correct, as share of all |", "|---|---:|---:|---:|"]
for k, v in res["methods"].items():
    if "test" in v:
        t = v["test"]
        L.append(f"| {k} | {pc(t['coverage'])} | {pc(t['precision'])} | {pc(t['correct_of_all'])} |")
    else:
        L.append(f"| {k} | not run: {v['error'][:80]} | | |")
for k, v in res["methods"].items():
    if "by_style" in v:
        L += ["", f"By rewrite style, {k} (coverage / precision):", "", "| Style | Embedding | Parser | Cascade |", "|---|---:|---:|---:|"]
        for st, d in v["by_style"].items():
            L.append(f"| {st} | {pc(d['embedding_abstaining']['coverage'])} / {pc(d['embedding_abstaining']['precision'])} | "
                     f"{pc(d['parser']['coverage'])} / {pc(d['parser']['precision'])} | {pc(d['cascade']['coverage'])} / {pc(d['cascade']['precision'])} |")
L += ["", "## Reading the numbers", "",
      "- Same caveat as the parser benchmark: the second supplier is simulated by rewrite rules, so this measures robustness to renaming.",
      "- A sentence embedding has to put `Superior Twin Room` far from `Superior Double Room` and close to `SUP TWN`; the sibling rooms of one "
      "hotel are the distractors, which is exactly where general-purpose embeddings are weakest.",
      "- The cascade row is the design in the architecture: deterministic attributes first, a learned matcher only for what they leave."]
(REP / "rooms_semantic.md").write_text("\n".join(L) + "\n", encoding="utf-8")
print("wrote reports/models/rooms_semantic.md")
