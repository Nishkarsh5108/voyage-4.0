# Canon local site: backend

The backend of the local Canon site. One command starts it; everything runs on this machine.

```
.venv\Scripts\python.exe -X utf8 web\serve.py              # http://127.0.0.1:8765/
.venv\Scripts\python.exe -X utf8 web\serve.py --port 8770  # another port; --quiet stops per-request logging
```

It binds 127.0.0.1 only, so uploaded feeds never leave the machine. On Windows the port is bound exclusively: if another program
already listens on it, the server says so and exits instead of sharing the port. It serves `web/static/` (`Cache-Control: no-cache`,
explicit MIME types: `.js`/`.mjs` text/javascript, `.css`, `.json`, `.svg`, `.woff2` font/woff2, ...), `submission/round1/numbers.json`
at `/numbers.json` (read from disk on every request), and the JSON API in `web/API.md`.

## What it needs

| File | Made by | If it is missing |
|---|---|---|
| `data/interim/listings.parquet` | `scripts/build/build_listings.py` | city presets unavailable |
| `data/processed/city_matcher/{model.lgb, featurizer_no_emb.joblib}` | `scripts/train/city_matcher.py` | `/api/status` says `model.ready: false`; `POST /api/runs` answers 503 with the rebuild command |
| `data/processed/city_matcher/loco/model_<city>.lgb` | `scripts/train/loco_models.py` (about 30 s) | labelled pairs of a preset city are scored by the final model; the run's score event says `loco: "missing"` |
| `data/raw/{makemytrip,goibibo}_hotels/*.csv` | Kaggle (PromptCloudHQ) | the OTA preset is unavailable |
| `data/interim/listings.parquet` (attractions of the city) | as above | the tours bench has no gazetteer |

No new dependencies: the standard library's `http.server` plus what `.venv` already has (pandas, numpy, lightgbm, rapidfuzz, scikit-learn, joblib, pyarrow).

## Layout

| File | Role |
|---|---|
| `web/serve.py` | entry point (`--port`, `--quiet`) |
| `handlers.py` | routes, static files, server-sent events |
| `pipeline.py` | one run: ingest, block, score, route, cluster, canonical (worker thread; the last 3 runs stay in memory; runs compute one at a time) |
| `presets.py` | the 12 city presets (training slice of `listings.parquet`) and the OTA preset (`ota_matcher.py`'s `load`, ported as is) |
| `feeds.py` | upload reading and validation (CSV / JSON / GeoJSON), plain-sentence problems |
| `benches.py` | room / rate parser and tour relation bench with literal explanations |
| `artefacts.py` | lazy loading of the joblib and the boosters |
| `parity.py` | the parity check below |
| `canon/cascade.py` (library) | stage-0 key rules, weak labels, routing and constrained union-find, mirroring `city_matcher.py` steps 2, 5, 6 |
| `scripts/train/loco_models.py` | rebuilds the 12 leave-one-city-out boosters that `city_matcher.py` trains and discards |

## How a run works

1. **ingest**: a preset city is `listings.parquet` with the training filter (`lat` known and `in_bbox`), every kind, rows in file order,
   then `canon.match.prepare` and the hub rule (a phone or URL shared by more than 4 listings of the city is not a key).
   The OTA preset is `ota_matcher.py`'s loader (group `india`). An upload is the validated records, grouped by their `city` value.
2. **block**: `canon.match.block` with the blocking parameters saved in the joblib, on `fz.tf_char.transform(nn)`.
3. **score**: `Featurizer.transform` in 32 chunks, west to east by pair midpoint (pairs without coordinates last). `n_near_max` is computed
   once over all candidates with the transform's own code, so chunking cannot change it. Final booster for every pair; for a preset city,
   pairs with a weak label are rescored with the booster trained without that city, as `city_matcher.py` did (`np.where(lab, oof, final)`).
4. **route** and **cluster**: `canon.cascade` (key rules first; model accept at `t_accept`, reject below `t_reject`; a pair without coordinates
   on both sides is never auto-accepted; union-find refuses to join two different Wikidata QIDs).
5. **canonical**: one name and centroid per merged entity (Latin script first, then source priority wikivoyage, osm, wikidata, overture,
   among members of the entity's majority kind, as `build_demo_data.py`).

Phone, website and QID are used only as stage-0 rules and weak labels, never as model features.

## Where review answers go

`POST /api/review` appends one row to `data/processed/web_review/answers.csv` (created with a header on first use): timestamp, run, input,
candidate index, decision, p, model, route, weak label, both records' source / id / name. The label sheets
(`data/processed/*/label_sheet*.csv`) are never touched.

## Parity checks (run on 19 Nov 2026)

`.venv\Scripts\python.exe -X utf8 webpi\parity.py dubai london` runs the site pipeline and compares it with what training stored
(`pairs.parquet`, `clusters.parquet`, `numbers.json`); results go to `data/processed/web_cache/parity.json`.

| Check | Dubai | London |
|---|---|---|
| Records, same listings in training's rid order | 12,259, yes | 65,754, yes |
| Candidate pairs, same set and order as `pairs.parquet` | 42,605, yes | 322,899, yes |
| All 28 features equal to `pairs.parquet` | yes (max abs diff 0) | yes (max abs diff 0) |
| Chunked features equal one unchunked transform | yes | yes |
| p, max abs diff vs stored p | 0 (4,044 labelled pairs by the LOCO booster, the rest by the final booster) | 0 (48,437 labelled) |
| Weak labels and label sources identical | yes | yes |
| Routes equal the cascade computed from the stored p | yes | yes |
| Lodging listings / entities | 5,187 / 4,074 (numbers.json: 5,187 / 4,074) | 12,458 / 10,169 (clusters.parquet: 10,169) |
| Record partition identical to `clusters.parquet` | 4 records differ | no (same entity count) |

The partition difference is the tie order of the union-find. Training sorted accepted edges with an unstable sort, so among the many edges
of weight 2.0 (key matches) the order was arbitrary; the site sorts stably by candidate position. Union-find gives the same partition in
any order except where the QID cannot-link rule decides which of two conflicting merges wins. In Dubai that is one hotel with two Wikidata
items (Canopy by Hilton Dubai Al Seef, Q111150457 and Q121315917): the OSM and Overture records join the other item. Entity counts are
unchanged in both cities.

Other checks:

- **LOCO boosters** (`scripts/train/loco_models.py`): all 12 reproduce training's out-of-city scores exactly (max |p - stored p| = 0 on
  every city's labelled pairs, also after save and reload); the median best iteration is 176, the tree count of the final `model.lgb`.
- **OTA preset**: the same 25,723 candidates in the same order as `data/processed/ota_matcher/pairs.parquet`, and the same bands
  (accept 546, uncertain 2,664, held for review without coordinates 1,917, reject 20,596); the float32 `p` array differs from the stored
  float64 p by at most 3e-8 (float32 rounding).
- **Canonical names**: 692 of the 693 multi-source Dubai lodging clusters in `submission/round1/demo/data.js` have the same members live (the other is the
  Canopy by Hilton case) and all 692 get the same canonical name.
- **Pair inspector**: `bias + sum(contrib)` equals `logit(p)` within 4e-14 on the pairs tested.
- **Parser trace hooks** (`canon/rooms.py`, `canon/activities.py`): the `trace` argument only observes. Old (commit f009fc4) vs new,
  with and without a trace, every field identical on all 2,383 distinct real room strings, 6,005 Indian OTA room strings and the 50,310
  regenerated benchmark rewrites (the regeneration reproduces `reports/models/rooms.json` coverage and precision for all five methods);
  and on 192 Klook titles plus 467 title+option strings with three gazetteer settings, the 783 regenerated sightseeing benchmark pairs
  and 9,808 within-city title pairs through `relate()`. 0 mismatches. (The regenerated sightseeing pairs score 754/783 with both the old and
  the new parser, one pair fewer than the 755 in `reports/models/activities.json`; that gap predates this change.)

## Timing (this machine, 19 Nov 2026)

| Run | End to end | Slowest stage |
|---|---:|---|
| Dubai preset | 12-22 s | block (`canon.match.block`) 5-11 s |
| OTA preset | 16 s | block 10 s |
| London preset (largest: 65,754 records, 322,899 candidates) | 161 s | block 107 s, score 52 s |

Under a profiler, about half of London's block time is the `groupby(...).agg(lambda ...)` at the end of `canon.match.block` and about
a third the sparse name-similarity products. The library was left as trained.

## Known limitations

- Weak labels, not human labels: every "match" count rests on shared Wikidata QIDs and rare phones / URLs.
- Uploads with source names other than the four training sources reach the model's `src_pair` feature as an unknown category
  (as in the OTA transfer test); the upload report says so.
- An upload's records are compared only within the same `city` value; different spellings of one city never meet (the report warns).
- The tours gazetteer for cities other than Singapore follows the same recipe with the city's own name as the stripped suffix and the
  only generic name; only Singapore's was used in the published numbers.
- One run computes at a time; others wait (`queued` event).

## Sample upload

`web/static/samples/two_feeds_sample.csv`: 338 real rows (MakeMyTrip 252, Goibibo 86) for Chennai from the two 2016 OTA crawls
(CC BY-SA 4.0), one row per property ID. Stars follow `ota_matcher.py` (MakeMyTrip "1 star" and Goibibo 0 left blank). 54 rows carry the
feeds' 0,0 placeholder coordinates; the upload report flags them.
