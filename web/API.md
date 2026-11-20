# Canon site: local API contract

The site is served by `web/serve.py` (Python stdlib `http.server`, no extra dependencies) on `http://127.0.0.1:8765`.
It binds to 127.0.0.1 only: uploaded feeds never leave the machine. Static files come from `web/static/`.
Everything below is what the frontend (`web/static/js/*`) relies on. Change it only together with the frontend.

## Conventions

- JSON responses use `Content-Type: application/json; charset=utf-8`, UTF-8, `ensure_ascii=False`.
- Errors: HTTP 4xx/5xx with `{"error": "<plain sentence>", "detail": "<optional>", "fix": "<optional command or step>"}`.
- Binary arrays: `GET /api/runs/<id>/array/<name>` returns the raw little-endian bytes of one typed array,
  `Content-Type: application/octet-stream`, header `X-Dtype: int32|float32|uint8|int8|float64`, header `X-Length: <n>`.
- Record index `i` = position in the run's prepared record frame (`rid` after `canon.match.prepare`).
  Candidate index `k` = position in the run's candidate frame (order as returned by `canon.match.block`).

## Status and presets

`GET /api/status`
```json
{"model": {"ready": true, "missing": [], "rebuild": ".venv\\Scripts\\python.exe -I -X utf8 scripts\\train\\city_matcher.py"},
 "loco": {"ready": true, "cities": ["dubai", "..."], "rebuild": ".venv\\Scripts\\python.exe -I -X utf8 scripts\\train\\loco_models.py"},
 "data": {"listings": true, "ota": true, "klook": true},
 "t_accept": 0.9556, "t_reject": 0.02, "features": ["dist_m", "..."]}
```

`GET /api/presets`
```json
[{"id": "dubai", "label": "Dubai", "group": "city", "records": 12270, "lodging": 5187, "sources": ["overture","osm","wikidata","wikivoyage"],
  "note": "Overture, OpenStreetMap, Wikidata, Wikivoyage. Hotels and attractions."},
 {"id": "ota_india", "label": "Goibibo × MakeMyTrip", "group": "ota", "records": 19168, "lodging": 19168, "sources": ["makemytrip","goibibo"],
  "note": "Two real Indian OTA feeds (2016 crawls). No labels."}]
```
Counts are what a run will ingest (after `prepare`). Cached after first computation (memory, and `data/processed/web_cache/presets.json`
keyed on the input files' size and time). Each preset also has `by_source`; the OTA preset has `with_coordinates`.
`/api/status` also returns `runs` (as `GET /api/runs`), `src_pair_categories`, `blocking`, and under `loco`: `note`, `built`,
`parity_max_abs_diff` (from `data/processed/city_matcher/loco/manifest.json`). When the model files are missing, `model.ready` is false,
`t_accept` / `features` are absent, and `POST /api/runs` answers 503 with `fix` = the rebuild command.

## Uploads

`POST /api/uploads` body JSON `{"files": [{"name": "feed_a.csv", "text": "<file contents>"}]}` (max 40 MB total; HTTP 413 above that).
A file may instead carry `"b64": "<base64 of the raw bytes>"` in place of `text`: the server then decodes UTF-8 and falls back to
Windows-1252 / Latin-1 with a warning. With `text`, characters the browser could not decode (U+FFFD) produce a warning.
Spreadsheets (.xlsx etc.) are refused with a sentence asking for CSV.
Each file is CSV (comma, semicolon or tab; sniffed), JSON (array of objects, `{"records": [...]}`, or GeoJSON FeatureCollection of Points).
Response:
```json
{"ok": true, "upload_id": "u3",
 "report": {"files": [{"name": "feed_a.csv", "format": "csv", "rows": 1200, "usable": 1187, "source": "feed_a",
                       "columns": {"name": "hotel_name", "lat": "latitude", "lon": "longitude", "source": null, "...": "..."},
                       "ignored_columns": ["foo"], "problems": [{"level": "error|warn|info", "text": "13 rows have no usable coordinates (row 4, 9, 12, ...)"}]}],
            "records": 2380, "sources": ["feed_a", "feed_b"],
            "missing": [{"field": "stars", "effect": "stars_diff is missing for every pair; the model treats it as unknown."}],
            "keys": {"qid": false, "phone": true, "website": false},
            "problems": [{"level": "error", "text": "Canon matches across sources, and this upload has one source. Add a second feed or a `source` column."}]}}
```
`ok` is false when any `error` level problem exists; then no `upload_id`.
Also in the report: per file `sources` (all source values found; `source` is null when there are several), and at the top
`by_source`, `with_coordinates`, `keys_note`. `missing` can also hold `{"field": "src_pair", ...}` when the source names are not the
four training sources (the model then sees src_pair as an unknown category). Rows that are kept but lose their coordinates
(non-numeric, out of range, 0,0) are matched by name only and never auto-accepted (route `no_coords_review`).
Groups: records are compared only within the same `city` value (lower-cased); without a city column everything is one group.
Column synonyms (case-insensitive): name/property_name/hotel_name/title; lat/latitude; lon/lng/long/longitude;
source/supplier/feed (missing: the file name stem is the source); id/src_id/property_id/code; street/address/address_line/property_address;
postcode/zip/postal_code/pincode; city; brand/chain; stars/star_rating/hotel_star_rating/rating (numeric 0-7 else unknown); alt_names/aliases (CSV: `|` or `;` separated);
kind/type (lodging|attraction, default lodging); keys used only as stage-0 rules, never as model features: qid/wikidata, phone/telephone, website/url.

## Runs

`POST /api/runs` body `{"preset": "dubai"}` or `{"upload_id": "u3"}` → `{"run_id": "r7"}`. The pipeline starts at once in a worker thread.

`GET /api/runs/<id>/events` → `text/event-stream`. Each message is `id: <n>\nevent: <type>\ndata: <json>\n\n`. Replays all past events on connect
(or those after `Last-Event-ID` when the browser reconnects), then streams; `: keep-alive` comments every 15 s.
After `done` or `error` the server sends `retry: 86400000` and closes the stream, so call `es.close()` on `done` / `error`.
An extra event `queued` (`{"note": ...}`) is sent when another run is computing; runs compute one at a time.
Stage events may carry more fields than listed below (e.g. ingest `label`, `groups`, `with_coordinates`; score start `total`, `chunks`,
`loco` = `used|missing|not_applicable`, `loco_pairs`; cluster done `merged_edges` and lodging `multi_source_entities`,
`entities_with_same_source_duplicates`, `largest_cluster`; route done `labelled.ambiguous_set_aside`; done `stage_seconds`).

`GET /api/runs` → the runs in memory (`run_id`, `label`, `input`, `finished`, `failed`, `arrays`, `loco`, `stage_seconds`);
`GET /api/runs/<id>` → the same for one run.

| event | data |
|---|---|
| `stage` | `{"stage": "ingest|block|score|route|cluster|canonical", "status": "start|done", "t": seconds_since_run_start, ...}` |
| ingest done | `{"records": n, "sources": [...], "by_source": {...}, "lodging": n_lodging}` |
| block done | `{"candidates": n, "by_gen": {"geo": n, "name": n, "exact": n}, "per_record": x, "naive_pairs": n*(n-1)/2 cross-source}` |
| `score` | `{"start": s, "end": e, "done": n_done, "total": n, "order": "sweep", "idx_b64": "<int32 candidate indices>", "p_b64": "<float32 scores>"}` (chunks of ~2-4% of candidates, scored in west→east order of pair midpoints) |
| route done | `{"counts": {"key_match": n, "key_reject": n, "model_accept": n, "model_reject": n, "uncertain": n, "no_coords_review": n}, "t_accept": x, "t_reject": x, "labelled": {"pos": n, "neg": n}}` |
| cluster done | `{"entities": n, "multi_source": n, "cannot_link_blocked": n, "largest": n, "lodging": {"listings": n, "entities": n}}` |
| `done` | `{"seconds": x}` |
| `error` | `{"error": "...", "fix": "..."}` |

Arrays (available once their stage is done):

| name | dtype | length | meaning |
|---|---|---|---|
| `lat`, `lon` | float64 | records | NaN when unknown |
| `src` | uint8 | records | index into `sources` |
| `kind` | uint8 | records | 0 lodging, 1 attraction |
| `qid` | int32 | records | dense id of the Wikidata QID, -1 when none (for the cannot-link rule) |
| `ra`, `rb` | int32 | candidates | record indices, ra < rb |
| `gen` | uint8 | candidates | bit 1 geo, bit 2 name (the model's `by_name`: name kNN or exact name), bit 4 exact name |
| `dist` | float32 | candidates | metres, NaN when a side has no coordinates |
| `p` | float32 | candidates | model probability (NaN before scoring) |
| `model` | uint8 | candidates | 0 final model, 1 leave-this-city-out model (labelled pairs of a preset city) |
| `y` | int8 | candidates | weak label: 1 key match, 0 key conflict, -1 none, -2 ambiguous (set aside, as in training) |
| `route` | uint8 | candidates | 0 key_match, 1 key_reject, 2 model_accept, 3 model_reject, 4 uncertain, 5 no_coords_review |
| `cluster` | int32 | records | cluster root record index after constrained union-find at `t_accept` |

`GET /api/runs/<id>/records` → `{"n": n, "sources": [...], "name": [...], "kind": [...], "src_id": [...]}` (columnar; names as given, any script;
`kind` holds the strings `lodging` / `attraction`).

`GET /api/runs/<id>/record/<i>` → every field of one record: source, src_id, name, alt_names, street, postcode, city, brand, stars, lat, lon, kind,
and key presence (`qid`, `phone`, `website` values when present, else null). Also `i`, `cluster` (once clustered), `state` (OTA preset only).

`GET /api/runs/<id>/pair/<k>` → pair inspector:
```json
{"k": 123, "a": {record}, "b": {record}, "p": 0.61, "model": "final|loco:dubai", "route": "uncertain", "y": -1, "label_src": "",
 "features": [{"name": "name_token_set_alt", "value": 1.0}, ...],
 "contrib": [{"name": "name_token_set_alt", "value": 2.31}, ...], "bias": -3.2, "logit": 0.45}
```
`contrib` comes from LightGBM `predict(..., pred_contrib=True)` of the same booster that produced `p` (log-odds; `bias + sum(contrib) == logit(p)`).
Also returned: `dist`, `gen` (`{"geo", "name", "exact"}` booleans) and `check` (`{"bias_plus_contrib", "raw_score", "abs_diff_vs_logit_p", "ok"}`,
ok when the difference is below 1e-4). `features[].value` of `src_pair` is the category string (null when the source pair is not one the model knows).

`GET /api/runs/<id>/canonical` → `{"entities": [{"id": root, "name": canonical name, "lat": x, "lon": x, "n": members, "sources": [...], "members": [i, ...]}]}`
for every cluster with 2+ members, plus `"singletons": n`. Entities are sorted by size; each also has `kind` (most common member kind);
`members[0]` is the record whose name was chosen; `rule` states the naming rule.

`GET /api/runs/<id>/review?limit=60` → pairs routed `uncertain` or `no_coords_review`, most informative first (|p − 0.5| ascending):
`[{"k": 1, "p": 0.52, "dist": 31, "route": "uncertain", "a": {"i": 4, "name": "...", "source": "..."}, "b": {...}}]`

`POST /api/review` body `{"run_id": "r7", "k": 123, "decision": "same|different|unsure"}` →
`{"saved": "data/processed/web_review/answers.csv", "count": 14}` (`count` = rows now in the file). Appends one row with columns
timestamp, run_id, input (preset id or `upload:u3`), k, decision, p, model, route, weak_label, label_src, dist_m, a_source, a_src_id, a_name,
b_source, b_src_id, b_name. Never touches `data/processed/*/label_sheet*.csv`.

## Benches (rule-based; literal explanations)

`POST /api/rooms/parse` `{"text": "TWN PARTIAL SV HB NRF"}` →
```json
{"raw": "...", "normalised": "twin partial sea view half board non refundable",
 "tokens": [{"raw": "TWN", "start": 0, "end": 3, "norm": ["twin"], "side": "room|rate|left|stop", "attr": "beds", "value": "twin", "rule": "BED twin"}],
 "fired": [{"side": "rate", "attr": "board", "value": "HB", "rule": "BOARD half board", "matched": "half board"}],
 "room": {...room_dict...}, "rate": {...rate_dict...}, "signature": [...], "confidence": 0.95, "residual": ""}
```
Parse details: `rule` is the lexicon group plus the pattern exactly as written in `canon/rooms.py` (long regexes included). `value` of a bed rule is a
list (`["double", "twin"]` for "double or twin"). `fired[]` also has `group`, `start`/`end` (span in `normalised`), `raw_start`/`raw_end` (span in
`raw`), `in_signature` (false for rate terms, size and occupancy). A token whose normalised words fall under different rules has `parts`
(one entry per normalised word). `aligned` is false when the raw ↔ normalised alignment could not be reproduced; tokens then have `raw: null`.
`signature_fields` names the eight signature positions.

`POST /api/rooms/map` `{"a": ["King Room with City View", ...], "b": ["KING CV BB", ...]}` → a JSON **list**, one item per non-empty `b` line:
`{"text", "parsed": {...same as parse...}, "match": index|null, "hits": [indices of a lines with the same signature], "why": "unique signature match|no room with this signature|2 rooms share this signature|low confidence"}`.
A line maps only when exactly one `a` line has its signature (the rule of `rooms_benchmark.py`). `low confidence` replaces
`no room with this signature` when the `b` parse has confidence below 0.5. At most 200 lines per side, 300 characters per line.

`POST /api/tours/relate` `{"a": "title A", "b": "title B", "city": "singapore"}` →
`{"a": {"raw", "attractions": [...], "experience", "access", "inclusions", "age_band", "group", "time_window", "duration_min", "promo_tags", "core_tokens", "confidence", "fired": [{"attr","value","matched","rule"}]}, "b": {...}, "relation": "VARIANT_OF", "diff": [...], "reason": "...", "gazetteer": {"city": "singapore", "names": 1435}}`
Also per side: `normalised`, `attraction_names` (display names), `resident_only`, `is_combo_worded`; `fired[]` has `group`, `start`/`end` and `where`
(`normalised`: span in `normalised`; `raw`: a [bracket tag], span in `raw`; `tag`: an access word found only in a tag, no span).
The gazetteer is built per city exactly as `scripts/demo/build_demo_data.py` builds Singapore's (1,435 names; the benchmark's own gazetteer,
which also takes alternate names, has 1,506). Cities: the 12 preset cities; default singapore.
