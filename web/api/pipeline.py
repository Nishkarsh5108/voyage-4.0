"""One matching run: ingest -> block -> score -> route -> cluster -> canonical, in a worker thread, streamed as events.

Every stage calls the library the reported numbers came from:
  ingest     canon.match.prepare, canon.cascade.rare_keys (hub rule per group)
  block      canon.match.block with the blocking parameters saved next to the model
  score      canon.match.Featurizer.transform (chunked west -> east; the crowding feature n_near_max is computed once over the
             whole candidate set, as a single transform would) and the final LightGBM booster. For a preset city, pairs with a
             weak label are scored by the booster trained without that city, as city_matcher.py did (np.where(lab, oof, final)).
  route      canon.cascade.weak_labels and route
  cluster    canon.cascade.constrained_union_find
  canonical  one name and centroid per merged entity (Latin script first, then source priority, as build_demo_data.py)
"""
from __future__ import annotations

import base64
import csv
import math
import threading
import time
import traceback
from collections import OrderedDict
from datetime import datetime

import numpy as np
import pandas as pd

from canon.cascade import NO_COORDS_REVIEW, ROUTES, UNCERTAIN, constrained_union_find, rare_keys, route, weak_labels
from canon.match import block, haversine, prepare

from . import REVIEW_DIR, ROOT, UserError
from .artefacts import MODELS
from .jsonutil import dumps, scalar

PRIORITY = {"wikivoyage": 0, "osm": 1, "wikidata": 2, "overture": 3}  # build_demo_data.py
KEEP_RUNS = 3
CHUNKS = 32  # score events: about 3% of the candidates each
PIPELINE_LOCK = threading.Lock()  # one run computes at a time; others wait their turn
ARRAY_DTYPES = {"lat": np.float64, "lon": np.float64, "src": np.uint8, "kind": np.uint8, "qid": np.int32, "ra": np.int32, "rb": np.int32,
                "gen": np.uint8, "dist": np.float32, "p": np.float32, "model": np.uint8, "y": np.int8, "route": np.uint8, "cluster": np.int32}
ANSWERS = REVIEW_DIR / "answers.csv"
ANSWER_COLS = ["timestamp", "run_id", "input", "k", "decision", "p", "model", "route", "weak_label", "label_src", "dist_m",
               "a_source", "a_src_id", "a_name", "b_source", "b_src_id", "b_name"]
_answers_lock = threading.Lock()


def b64(a: np.ndarray) -> str:
    return base64.b64encode(np.ascontiguousarray(a).astype(a.dtype.newbyteorder("<"), copy=False).tobytes()).decode("ascii")


class Run:
    def __init__(self, run_id: str, spec: dict, make_ingest, label: str):
        self.id, self.spec, self.make_ingest, self.label = run_id, spec, make_ingest, label
        self.events: list = []
        self.cond = threading.Condition()
        self.finished = self.failed = False
        self.arrays: dict = {}
        self.t0 = time.time()
        self.created = datetime.now().isoformat(timespec="seconds")
        self.ing = self.G = self.C = self.F = None
        self.p64 = self.model_of = self.y = self.label_src = self.routes = self.root = self.has_xy = None
        self.sources: list = []
        self.canonical = None
        self.loco_city, self.loco_state = None, "not_applicable"
        self.timings: dict = {}

    # ------------------------------------------------------------------ events
    def emit(self, typ: str, data: dict) -> None:
        with self.cond:
            self.events.append((len(self.events), typ, dumps(data)))
            self.cond.notify_all()

    def stage(self, name: str, status: str, **extra) -> None:
        t = round(time.time() - self.t0, 3)
        if status == "start":
            self.timings[name] = t
        else:
            self.timings[name] = round(t - self.timings.get(name, t), 3)
        self.emit("stage", {"stage": name, "status": status, "t": t, **extra})

    def array(self, name: str, values) -> None:
        self.arrays[name] = np.ascontiguousarray(np.asarray(values).astype(ARRAY_DTYPES[name]))

    def info(self) -> dict:
        return {"run_id": self.id, "label": self.label, "input": self.spec, "created": self.created, "finished": self.finished,
                "failed": self.failed, "arrays": sorted(self.arrays), "loco": self.loco_state, "loco_city": self.loco_city,
                "stage_seconds": self.timings}

    # ------------------------------------------------------------------ helpers for the handlers
    def need(self, what: str):
        v = getattr(self, what)
        if v is None:
            raise UserError(f"Run {self.id} has not reached that stage yet ({what}).", status=409)
        return v

    def record(self, i: int) -> dict:
        G = self.need("G")
        if not 0 <= i < len(G):
            raise UserError(f"Record {i} does not exist; this run has {len(G)} records.", status=404)
        r = G.iloc[i]
        out = {"i": i, "rid": i}
        for col in ("source", "src_id", "name", "alt_names", "street", "postcode", "city", "state", "brand", "stars", "lat", "lon", "kind"):
            if col in G.columns:
                out[col] = scalar(r[col])
        if isinstance(out.get("alt_names"), list) and not out["alt_names"]:
            out["alt_names"] = []
        for key, col in (("qid", "qid"), ("phone", "phone_raw"), ("website", "website")):
            out[key] = scalar(r[col]) if col in G.columns else None
        out["keys_used_as"] = "stage-0 rules and weak labels only; never model features"
        if self.root is not None:
            out["cluster"] = int(self.root[i])
        return out

    def short(self, i: int) -> dict:
        G = self.G
        return {"i": int(i), "name": G["name"].iat[i], "source": G["source"].iat[i]}


# ============================================================================ stages
def _ingest(run: Run) -> None:
    run.stage("ingest", "start")
    ing = run.make_ingest()
    run.ing, run.loco_city = ing, ing.loco_city
    G = prepare(ing.frame)
    if len(G) == 0:
        raise UserError("No record has a usable name, so there is nothing to match.")
    for col in ("qid", "phone8", "url_key", "domain", "phone_raw", "website"):
        if col not in G.columns:
            G[col] = None
    G = rare_keys(G, group_col=ing.group_col)
    run.G = G
    run.sources = [s for s in ing.sources if (G["source"] == s).any()]
    src_ix = {s: i for i, s in enumerate(run.sources)}
    run.array("lat", G["lat"].to_numpy(dtype=float))
    run.array("lon", G["lon"].to_numpy(dtype=float))
    run.array("src", G["source"].map(src_ix).to_numpy())
    run.array("kind", (G["kind"].to_numpy() != "lodging").astype(np.uint8))
    q = G["qid"].to_numpy(dtype=object)
    has_q = np.array([isinstance(v, str) for v in q])
    codes = np.full(len(G), -1, dtype=np.int32)
    if has_q.any():
        codes[has_q] = pd.factorize(pd.Series(q[has_q], dtype=object))[0]
    run.array("qid", codes)
    by_source = G.groupby("source").size().to_dict()
    run.stage("ingest", "done", records=len(G), sources=run.sources, by_source={s: int(by_source[s]) for s in run.sources},
              lodging=int((G["kind"] == "lodging").sum()), label=ing.label, groups=int(G[ing.group_col].nunique()),
              with_coordinates=int(G["lat"].notna().sum()), dropped_empty_names=int(len(ing.frame) - len(G)))


def _block(run: Run) -> None:
    run.stage("block", "start")
    art = MODELS.art()
    G, ing = run.G, run.ing
    XC = art["featurizer"].tf_char.transform(G["nn"])
    groups = list(dict.fromkeys(G[ing.group_col].tolist()))
    C = block(G, XC, groups, ing.sources, group_col=ing.group_col, **art["blocking"])
    C = C.reset_index(drop=True)
    for col in ("ra", "rb", "geo_rank", "by_geo", "by_name", "by_emb"):
        C[col] = C[col].astype(np.int64)
    run.C = C
    ra, rb = C["ra"].to_numpy(), C["rb"].to_numpy()
    lat, lon = G["lat"].to_numpy(dtype=float), G["lon"].to_numpy(dtype=float)
    dist = haversine(lat[ra], lon[ra], lat[rb], lon[rb]).astype(np.float32)
    run.has_xy = ~(np.isnan(lat[ra]) | np.isnan(lat[rb]) | np.isnan(lon[ra]) | np.isnan(lon[rb]))
    # exact-name generator, recomputed with block()'s own rule: same nn (>= 4 chars) shared by 2-30 records of the group
    nn = G["nn"].to_numpy(dtype=object)
    long_nn = G["nn"].str.len() >= 4
    cnt = G[long_nn].groupby([ing.group_col, "nn"]).size()
    grp = G[ing.group_col].to_numpy(dtype=object)
    same = (nn[ra] == nn[rb]) & long_nn.to_numpy()[ra]
    exact = np.zeros(len(C), dtype=bool)
    if same.any():
        c = np.array([cnt.get((g, n), 0) for g, n in zip(grp[ra[same]], nn[ra[same]])])
        exact[np.where(same)[0]] = (c >= 2) & (c <= 30)
    gen = C["by_geo"].to_numpy() * 1 + C["by_name"].to_numpy() * 2 + exact * 4
    wl = weak_labels(G, ra, rb, dist)
    run.y, run.label_src = wl["y"], wl["label_src"]
    for name, v in (("ra", ra), ("rb", rb), ("gen", gen), ("dist", dist), ("y", wl["y"])):
        run.array(name, v)
    naive = 0
    for _, g in G.groupby(ing.group_col):
        n_s = g.groupby("source").size().to_numpy()
        naive += int((n_s.sum() ** 2 - (n_s ** 2).sum()) // 2)
    run.stage("block", "done", candidates=len(C), by_gen={"geo": int(C["by_geo"].sum()), "name": int(C["by_name"].sum()), "exact": int(exact.sum())},
              per_record=round(len(C) / len(G), 4), naive_pairs=naive, blocking=art["blocking"])


def _score(run: Run) -> None:
    art = MODELS.art()
    fz, FEATS, cats = art["featurizer"], art["features"], art["src_pair_categories"]
    G, C = run.G, run.C
    n = len(C)
    ra, rb = C["ra"].to_numpy(), C["rb"].to_numpy()
    lon = G["lon"].to_numpy(dtype=float)
    mid = np.where(run.has_xy, (lon[ra] + lon[rb]) / 2, np.nan)
    order = np.argsort(mid, kind="stable")  # west -> east; NaN (no coordinates) sorts last
    # n_near_max over the whole candidate set, with Featurizer.transform's own code, so chunking cannot change it
    d = run.arrays["dist"]
    near = C[d < 300]
    cnt = pd.concat([near["ra"], near["rb"]]).value_counts()
    nnm = np.maximum(C["ra"].map(cnt).fillna(0).to_numpy(), C["rb"].map(cnt).fillna(0).to_numpy())
    lab = run.y >= 0
    loco_key = None
    if run.loco_city:
        if MODELS.booster(run.loco_city) is not None:
            loco_key, run.loco_state = run.loco_city, "used"
        else:
            run.loco_state = "missing"
    run.model_of = np.zeros(n, dtype=np.uint8)
    if loco_key:
        run.model_of[lab] = 1
    size = max(500, math.ceil(n / CHUNKS)) if n else 1
    starts = list(range(0, n, size))
    run.stage("score", "start", total=n, chunks=len(starts), order="sweep", loco=run.loco_state, loco_city=run.loco_city,
              loco_pairs=int(lab.sum()) if loco_key else 0,
              loco_note=("Labelled pairs are scored by the booster trained without this city, as in training." if loco_key else
                         "Leave-one-city-out boosters are missing: every pair is scored by the final model, which saw this city's labels."
                         if run.loco_state == "missing" else None))
    p64 = np.full(n, np.nan)
    parts = []
    done = 0
    for s in starts:
        idx = order[s:s + size]
        Fc = fz.transform(G, C.iloc[idx], src_pair_categories=cats)
        Fc["n_near_max"] = nnm[idx]
        X = Fc[FEATS]
        pc = MODELS.predict("final", X)
        if loco_key:
            lm = lab[idx]
            if lm.any():
                pc[lm] = MODELS.predict(loco_key, X[lm])
        p64[idx] = pc
        parts.append(X)
        done += len(idx)
        run.emit("score", {"start": s, "end": s + len(idx), "done": done, "total": n, "order": "sweep",
                           "idx_b64": b64(idx.astype(np.int32)), "p_b64": b64(pc.astype(np.float32))})
    F = pd.concat(parts).sort_index() if parts else pd.DataFrame(columns=FEATS)
    if parts and not np.array_equal(F.index.to_numpy(), np.arange(n)):
        raise RuntimeError("feature chunks do not cover the candidate set exactly once")
    run.F, run.p64 = F, p64
    run.array("p", p64)
    run.array("model", run.model_of)
    run.stage("score", "done", scored=n, loco=run.loco_state)


def _route(run: Run) -> None:
    run.stage("route", "start")
    art = MODELS.art()
    run.routes = route(run.y, run.p64, art["t_accept"], art["t_reject"], run.has_xy)
    run.array("route", run.routes)
    counts = {name: int((run.routes == i).sum()) for i, name in enumerate(ROUTES)}
    run.stage("route", "done", counts=counts, t_accept=art["t_accept"], t_reject=art["t_reject"],
              labelled={"pos": int((run.y == 1).sum()), "neg": int((run.y == 0).sum()), "ambiguous_set_aside": int((run.y == -2).sum())})


def _cluster(run: Run) -> None:
    run.stage("cluster", "start")
    G, C = run.G, run.C
    res = constrained_union_find(len(G), C["ra"].to_numpy(), C["rb"].to_numpy(), run.routes, run.p64, G["qid"].to_numpy(dtype=object))
    run.root = res["root"]
    run.array("cluster", run.root)
    df = pd.DataFrame({"root": run.root, "source": G["source"].to_numpy(), "lodging": (G["kind"] == "lodging").to_numpy()})
    size = df.groupby("root").size()
    nsrc = df.groupby("root")["source"].nunique()
    lod = df[df["lodging"]]
    lod_roots = lod["root"].unique()
    same_src_dupe = int((lod.groupby(["root", "source"]).size() > 1).groupby("root").any().sum()) if len(lod) else 0
    run.stage("cluster", "done", entities=int(len(size)), multi_source=int((nsrc >= 2).sum()), cannot_link_blocked=int(res["blocked"]),
              largest=int(size.max()), merged_edges=int((res["outcome"] == 0).sum()),
              lodging={"listings": int(len(lod)), "entities": int(len(lod_roots)),
                       "multi_source_entities": int((nsrc.loc[lod_roots] >= 2).sum()) if len(lod) else 0,
                       "entities_with_same_source_duplicates": same_src_dupe,
                       "largest_cluster": int(size.loc[lod_roots].max()) if len(lod) else 0})


def _canonical(run: Run) -> None:
    run.stage("canonical", "start")
    G = run.G
    pr = {s: PRIORITY.get(s, 4 + i) for i, s in enumerate(run.sources)}
    root = run.root
    rid = np.arange(len(G))
    notlatin = ~G["latin"].to_numpy(dtype=bool)
    prio = G["source"].map(pr).to_numpy(dtype=np.int64)
    lat, lon = G["lat"].to_numpy(dtype=float), G["lon"].to_numpy(dtype=float)
    size = np.bincount(root, minlength=len(G))[root]
    is_lod = (G["kind"] == "lodging").to_numpy()
    ent_lod = (2 * np.bincount(root, weights=is_lod.astype(float), minlength=len(G)) >= np.bincount(root, minlength=len(G)))[root]
    offkind = is_lod != ent_lod  # the entity's kind is its members' majority (ties: lodging); its name comes from a member of that kind
    order = np.lexsort((rid, prio, notlatin, offkind, root))  # by cluster, own kind first, Latin script, source priority, record order
    order = order[size[order] >= 2]
    rs = root[order]
    starts = np.flatnonzero(np.r_[True, rs[1:] != rs[:-1]]) if len(order) else np.array([], dtype=int)
    ends = np.r_[starts[1:], len(order)]
    names, sources, kinds = G["name"].to_numpy(dtype=object), G["source"].to_numpy(dtype=object), G["kind"].to_numpy(dtype=object)
    ents = []
    for s, e in zip(starts, ends):
        mem = order[s:e]
        ok = ~np.isnan(lat[mem]) & ~np.isnan(lon[mem])
        ents.append({"id": int(rs[s]), "name": names[mem[0]], "lat": float(lat[mem][ok].mean()) if ok.any() else None,
                     "lon": float(lon[mem][ok].mean()) if ok.any() else None, "n": int(len(mem)),
                     "sources": sorted({sources[i] for i in mem}, key=lambda x: pr[x]),
                     "kind": "lodging" if ent_lod[mem[0]] else "attraction", "members": mem.tolist()})
    ents.sort(key=lambda e: (-e["n"], e["id"]))
    run.canonical = {"entities": ents, "singletons": int((size == 1).sum()),
                     "rule": "name: among members of the entity's kind (majority; ties: lodging), the first with a Latin-script name, "
                             "then source priority wikivoyage, osm, wikidata, overture, then other sources in feed order (as "
                             "build_demo_data.py); position: mean of the members with coordinates"}
    run.stage("canonical", "done", entities=len(ents), singletons=run.canonical["singletons"])


def execute(run: Run) -> None:
    try:
        if not PIPELINE_LOCK.acquire(blocking=False):
            run.emit("queued", {"note": "Another run is computing; this one starts when it finishes."})
            PIPELINE_LOCK.acquire()
        try:
            run.t0 = time.time()
            MODELS.require()
            for fn in (_ingest, _block, _score, _route, _cluster, _canonical):
                fn(run)
            run.emit("done", {"seconds": round(time.time() - run.t0, 3), "stage_seconds": run.timings})
        finally:
            PIPELINE_LOCK.release()
    except UserError as e:
        run.failed = True
        run.emit("error", e.payload())
    except Exception as e:  # noqa: BLE001 - reported to the page
        run.failed = True
        traceback.print_exc()
        run.emit("error", {"error": f"The run stopped with an internal error: {type(e).__name__}: {e}",
                           "detail": traceback.format_exc(limit=4)[-1500:], "fix": "See the server console for the full traceback."})
    finally:
        with run.cond:
            run.finished = True
            run.cond.notify_all()


# ============================================================================ registry
class RunStore:
    def __init__(self):
        self._lock = threading.Lock()
        self._runs: OrderedDict = OrderedDict()
        self._n = 0

    def start(self, spec: dict, make_ingest, label: str, background: bool = True) -> Run:
        with self._lock:
            self._n += 1
            run = Run(f"r{self._n}", spec, make_ingest, label)
            self._runs[run.id] = run
            while len(self._runs) > KEEP_RUNS:
                self._runs.popitem(last=False)
        if background:
            threading.Thread(target=execute, args=(run,), daemon=True, name=f"run-{run.id}").start()
        else:
            execute(run)
        return run

    def get(self, run_id: str) -> Run:
        with self._lock:
            run = self._runs.get(run_id)
        if run is None:
            raise UserError(f"Run {run_id} is not in memory. The server keeps the last {KEEP_RUNS} runs; start a new one.", status=404)
        return run

    def list(self) -> list:
        with self._lock:
            return [r.info() for r in self._runs.values()]


RUNS = RunStore()


# ============================================================================ per-pair views
def pair_detail(run: Run, k: int) -> dict:
    F = run.need("F")
    C = run.C
    if not 0 <= k < len(C):
        raise UserError(f"Pair {k} does not exist; this run has {len(C)} candidate pairs.", status=404)
    FEATS = MODELS.art()["features"]
    X = F.iloc[[k]][FEATS]
    key = run.loco_city if run.model_of[k] == 1 else "final"
    contrib = MODELS.predict(key, X, pred_contrib=True)[0]
    raw = float(MODELS.predict(key, X, raw_score=True)[0])
    p = float(run.p64[k])
    logit = math.log(p / (1 - p)) if 0 < p < 1 else raw
    feats = []
    for f in FEATS:
        v = X[f].iat[0]
        feats.append({"name": f, "value": (None if pd.isna(v) else str(v)) if f == "src_pair" else scalar(v)})
    bias = float(contrib[-1])
    total = bias + float(np.sum(contrib[:-1]))
    gen = int(run.arrays["gen"][k])
    return {"k": k, "a": run.record(int(C["ra"].iat[k])), "b": run.record(int(C["rb"].iat[k])), "p": p,
            "model": f"loco:{run.loco_city}" if key != "final" else "final",
            "route": ROUTES[int(run.routes[k])] if run.routes is not None else None, "y": int(run.y[k]), "label_src": str(run.label_src[k]),
            "dist": scalar(run.arrays["dist"][k]), "gen": {"geo": bool(gen & 1), "name": bool(gen & 2), "exact": bool(gen & 4)},
            "features": feats, "contrib": [{"name": f, "value": float(c)} for f, c in zip(FEATS, contrib[:-1])], "bias": bias, "logit": logit,
            "check": {"bias_plus_contrib": total, "raw_score": raw, "abs_diff_vs_logit_p": abs(total - logit), "ok": abs(total - logit) < 1e-4}}


def review_queue(run: Run, limit: int = 60) -> list:
    routes = run.need("routes")
    idx = np.where((routes == UNCERTAIN) | (routes == NO_COORDS_REVIEW))[0]
    idx = idx[np.argsort(np.abs(run.p64[idx] - 0.5), kind="stable")][:max(0, min(limit, 1000))]
    d = run.arrays["dist"]
    C = run.C
    return [{"k": int(k), "p": float(run.p64[k]), "dist": scalar(d[k]), "route": ROUTES[int(routes[k])],
             "a": run.short(int(C["ra"].iat[k])), "b": run.short(int(C["rb"].iat[k]))} for k in idx]


def save_answer(run: Run, k: int, decision: str) -> dict:
    if decision not in ("same", "different", "unsure"):
        raise UserError("decision must be one of same, different, unsure.")
    run.need("routes")
    C = run.C
    if not 0 <= k < len(C):
        raise UserError(f"Pair {k} does not exist in run {run.id}.", status=404)
    a, b = run.G.iloc[int(C["ra"].iat[k])], run.G.iloc[int(C["rb"].iat[k])]
    row = {"timestamp": datetime.now().isoformat(timespec="seconds"), "run_id": run.id,
           "input": run.spec.get("preset") or f"upload:{run.spec.get('upload_id')}", "k": k, "decision": decision,
           "p": round(float(run.p64[k]), 6), "model": f"loco:{run.loco_city}" if run.model_of[k] == 1 else "final",
           "route": ROUTES[int(run.routes[k])], "weak_label": int(run.y[k]), "label_src": str(run.label_src[k]),
           "dist_m": "" if np.isnan(run.arrays["dist"][k]) else round(float(run.arrays["dist"][k]), 1),
           "a_source": a["source"], "a_src_id": a["src_id"], "a_name": a["name"], "b_source": b["source"], "b_src_id": b["src_id"], "b_name": b["name"]}
    with _answers_lock:
        REVIEW_DIR.mkdir(parents=True, exist_ok=True)
        new = not ANSWERS.exists() or ANSWERS.stat().st_size == 0
        with open(ANSWERS, "a", encoding="utf-8-sig" if new else "utf-8", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=ANSWER_COLS)
            if new:
                w.writeheader()
            w.writerow(row)
        with open(ANSWERS, encoding="utf-8-sig", newline="") as fh:
            count = sum(1 for _ in csv.DictReader(fh))
    return {"saved": ANSWERS.relative_to(ROOT).as_posix(), "count": count}
