# PROGRESS — Multi-Supplier Optimization build log / resume guide

This file is the hand-over between sessions. If a session ends mid-way, read this top to bottom,
then pick up at the first unchecked item under **Next steps**. Keep it updated as work lands.

Statement chosen: **Multi-Supplier Optimization** (see `research/02-multi-supplier-optimization.md`).
**Round 1 (idea round) closes 20 Nov 2026, 11:59 PM IST**: a two-slide deck (cover and thank-you not counted) plus a video.
The Round 1 package is built: see `submission/round1/README.md`.

## Ground rules for whoever continues

- **Commit as you go.** The user asked for this on 14 Nov. Work is committed on branch `round1-spike` (not `main`), in small logical commits.
  Do not push unless asked. **Commits carry the user's name only: no co-author or tool trailers in commit messages** (user's instruction, 14 Nov).
- **Compute.** Check before heavy work: `nvidia-smi` and CPU load. On 14 Nov at 03:05 the machine was busy with someone else's training
  job (never kill or throttle it); by 08:05 it was idle. When it is free, local runs are fine. When it is busy, do only downloads and
  memory-bounded DuckDB work locally and send training to Kaggle kernels.
- **Kaggle credentials.** Use `C:\Users\nishk\.kaggle\kaggle-api_friend.txt` (the friend's account) first.
  Fall back to `C:\Users\nishk\.kaggle\kaggle API.txt` (the user's account) only when the friend's quota is exhausted.
  Do not use any other credential file. Load it per command, never print it:
  `$env:KAGGLE_API_TOKEN = (Get-Content "C:\Users\nishk\.kaggle\kaggle-api_friend.txt" -Raw).Trim()`
- **Do not route around access gates.** If a source returns 403 or needs terms accepted, record it under
  Blockers and move on. No re-uploaded copies of gated data, no trying other credentials.
- **Python.** `.venv\Scripts\python.exe` (uv, CPython 3.12) for everything except GPU work. It has no torch.
  GPU scripts run with an existing conda env, read-only (install nothing into it):
  `C:\Users\nishk\anaconda3\envs\torch_gpu\python.exe` (torch + CUDA, transformers).
  Run scripts that read downloaded files with `-I -X utf8`.
- **Other tools on this machine.** Node 22 (deck generator, `scripts/deck`), Microsoft Edge (headless screenshots of the demo),
  PowerPoint (renders slides for visual checks). No LibreOffice.
- `data/` is gitignored: each downloaded source lives in `data/raw/<source>/`; nothing under `data/` is ever committed.
- **Report numbers honestly.** Matching numbers come from weak labels, room and sightseeing numbers from a simulated second supplier,
  the offer panel is a simulation. Say so wherever a number is quoted. `submission/round1/VIDEO_SCRIPT.md` lists what may be claimed.

## Layout

```
canon/              the library: match.py (blocking + pair features), rooms.py (room / rate parser), activities.py (typed relations)
scripts/download/   one script per source (re-runnable, skips what exists)
scripts/build/      build_listings.py (canonical listing table), embed_names.py (multilingual name vectors, GPU, experiment only)
scripts/eda/        EDA scripts -> reports/eda/<name>.md + .json + figures; common.py holds the chart style
scripts/train/      city_matcher.py, ota_matcher.py, rooms_benchmark.py, activities_benchmark.py, report_fsq.py
scripts/demo/       build_demo_data.py (-> demo/data.js), build_basemap.py (-> demo/basemap.js, offline map), screenshots.ps1 (-> submission/round1/screens)
scripts/figures/    round1_figures.py (-> submission/round1/figures + numbers.json)
scripts/deck/       build_round1_deck.js (pptxgenjs), render.ps1
kaggle/             kernel folders pushed with `kaggle kernels push -p kaggle/<name>`
demo/               index.html + data.js: the validation demo to screen-record
reports/            data-sources.md, eda/, models/
submission/round1/  deck, video script, figures, screens, numbers.json, README
data/raw|interim|processed   (gitignored)
```

## Status (last updated 14 Nov 2026, late morning)

### Phase 1 — data sources: DONE

Full assessment: **`reports/data-sources.md`**. Nine sources downloaded (about 1.1 GB): Overture Places, OpenStreetMap, Wikidata,
Wikivoyage (all for 12 cities), Foursquare Location Matching, 515K Booking.com reviews, MakeMyTrip, Goibibo, Klook crawl, Viator sample.
Cities: dubai, bangkok, singapore (core) · delhi, mumbai, goa (India) · london, paris, amsterdam, barcelona, vienna, milan (Europe).

Rebuild order from nothing: `scripts/download/*.py` → `scripts/download/wikidata_class_labels.py` → `scripts/build/build_listings.py`
→ EDA scripts → training scripts → `scripts/figures`, `scripts/demo`, `scripts/deck`.

### Blockers — need the user

1. **Expedia ICDM 2013** (`expedia-personalized-sort`): the download returns 403 for both Kaggle accounts.
   Someone must open https://www.kaggle.com/competitions/expedia-personalized-sort/rules and accept the rules with the account
   whose token is used. Then: `kaggle competitions download -c expedia-personalized-sort -f data.zip -p data/raw/expedia_icdm2013`.
   **The whole ranking track (LambdaMART, position-bias correction, duplicate collapsing) waits on this.**
2. **Deck placeholders**: team name and members on the cover, repository link on the thank-you slide (see `submission/round1/README.md`).
3. **Viator Basic Access / Hotelbeds evaluation keys** need a human sign-up. Product-level sightseeing data is the thinnest part of the data.
4. **Human labels.** `data/processed/city_matcher/label_sheet.csv` holds 400 pairs to label (same / part-of or variant / different / unsure);
   `data/processed/ota_matcher/label_sheet.csv` holds 280 for the two OTA feeds. The `_key.csv` files hold buckets and model scores:
   do not show them to the labeller.

### Phase 2 — EDA: DONE

| Report | Headline |
|---|---|
| `reports/eda/foursquare_lm.md` | 1.14 M records, 950 K true pairs; 12 % of duplicates sit more than 1 km from their place; a shared phone alone is a match 88 % of the time |
| `reports/eda/city_sources.md` | 99,691 lodging + 228,165 attraction listings from 4 sources; 34,482 key-linked cross-source pairs; hub phones (one number on 761 Goa listings) |
| `reports/eda/ota_hotels.md` | 587 of 4,000 Goibibo hotels have a likely MakeMyTrip twin by a naive rule; same hotel's pins differ by a median of 74 m |
| `reports/eda/rooms.md` | 2,383 room strings; 285 cover 90 % of bookings; 9 % carry a rate or package term |
| `reports/eda/sightseeing.md` | 192 Klook products with 467 options; product-level public data is thin |

### Phase 3 — models

| Model | Script | Status | Result |
|---|---|---|---|
| A. Pair model on Foursquare LM | `kaggle/fsq_pair_model/train.py` (private Kaggle CPU kernel `canon-fsq-pair-model`, 22 min) | done → `reports/models/fsq_pair_model.md` | Unseen places: cluster IoU **0.878** vs 0.74-0.78 for rule baselines. Blocking caps the score at 0.959 |
| B. Cross-source city matcher | `scripts/train/city_matcher.py` (local, ~8 min) | done → `reports/models/city_matcher.md` | Leave-one-city-out, weak labels: at the rule's precision the model finds **88 % of matches vs 58 %** for a name + distance rule (Bangkok 91 % vs 27 %); 61 % recall at 99 % precision; AUC 0.994 |
| B2. Transfer to two real OTA feeds | `scripts/train/ota_matcher.py` | done → `reports/models/ota_matcher.md` | No retraining: 546 accepted pairs, 484 Goibibo hotels with a MakeMyTrip twin. No labels yet |
| C. Room / rate parser | `canon/rooms.py`, `scripts/train/rooms_benchmark.py` | done → `reports/models/rooms.md` | Simulated second supplier on 1,484 real hotels: **96 % of renamed rooms mapped** vs 60 % for the best fuzzy matcher |
| D. Sightseeing typed relations | `canon/activities.py`, `scripts/train/activities_benchmark.py` | done, first pass → `reports/models/activities.md` | Simulated second supplier, in-sample: 96 % accuracy over four relations; a deduplicator merges 95 % of variants and 100 % of combos |
| E. Offer arbitration (RAEP) | demo panel only (`demo/index.html`, tab 5) | simulation, not a result | — |
| F. Ranking | — | **blocked** on Expedia rules | — |

Things to know:

- Model B's truth is **weak labels**: positives share a Wikidata QID, or a rare phone / URL plus proximity; negatives carry two different
  QIDs, or different rare phones and different domains. Phone, URL and QID are never model features.
- 242 "negatives" with the same name within 50 m were set aside as ambiguous (Wikidata duplicates, two phone numbers for one hotel).
  With them counted as non-matches, recall at 99 % precision falls from 61 % to 4 %: the top of the ranking is that sensitive to label noise.
- Multilingual name embeddings (`--emb`) were tried and not adopted: no measurable gain. The experiment table is in the model B report.
- Model D's rules were adjusted after reading errors on its own test set, so its score is in-sample. Its output on real Klook option
  pairs still shows mistakes; the report prints them.
- `scripts/train/city_matcher.py` saves `data/processed/city_matcher/{model.lgb, featurizer_no_emb.joblib}`; `ota_matcher.py` loads both.

### Phase 4 — Round 1 package: BUILT

`submission/round1/`: `Canon_Round1.pptx` (cover, two content slides, thank-you, speaker notes), `VIDEO_SCRIPT.md`, `figures/`, `screens/`,
`numbers.json`, `README.md`. Validation demo to screen-record: `demo/index.html` (six tabs; simulated parts are tagged on screen).
The demo uses no map tile server: tile.openstreetmap.org blocks pages opened as local files and CARTO needs an API key, so the map is drawn
from OSM data bundled in `demo/basemap.js` and Leaflet is vendored in `demo/vendor/`. Do not add a tile layer back.
Every number in the deck is read from `numbers.json`; rebuild steps are in the package README.

### Phase 5 — public website: BUILT (19 Nov 2026)

One command, offline, binds 127.0.0.1 only: `.venv\Scripts\python.exe -X utf8 web\serve.py` → http://127.0.0.1:8765/
(`--port` to change it). Rebuild the story data after any model re-run: `.venv\Scripts\python.exe -I -X utf8 web\build_site_data.py`.

- `web/static/`: no build step. Vanilla ES modules, hand-written WebGL2 map (`js/gl.js`), fonts self-hosted (Archivo variable for display,
  IBM Plex Mono + Plex Sans Arabic / Thai / Devanagari for raw supplier strings). Sections: landing collapse (5,187 → 4,074 from real
  clusters), the Marina problem, the method story (8 beats), the workbench (ink-dark), evidence, adoption.
- Every quoted figure is a `data-n` binding into `/numbers.json` (served live from `submission/round1/numbers.json`); an in-browser audit
  found 24 bindings, 0 mismatches. Simulated parts are hatched and tagged; truth tags on every evidence number.
- `web/serve.py` + `web/canon_web/`: the API in `web/API.md` around `canon/` (details and checks in `web/canon_web/README.md`).
  New library pieces: `canon/cascade.py` (key rules, routing, constrained union-find, mirroring city_matcher.py), `canon/_trace.py` and an
  optional `trace=` on `parse_room` / `parse_activity` (old vs new outputs identical on all real strings and benchmark rewrites).
- `scripts/train/loco_models.py` rebuilds the 12 leave-one-city-out boosters (into `data/processed/city_matcher/loco/`, ~30 s); they
  reproduce the stored out-of-city scores exactly, so preset runs score labelled pairs out of city, as the evaluation did.
- Parity: a live Dubai run reproduces pairs.parquet (42,605 candidates, features and p identical) and 5,187 → 4,074; London reproduces
  10,169 lodging entities; the OTA preset reproduces ota_matcher.py's bands. The browser worker's union-find matches the server's entity
  count on Dubai, London and an upload. London end to end takes ~150 s (blocking ~95 s); Dubai ~15 s.
- Review answers from the workbench go to `data/processed/web_review/answers.csv` (created on first answer); label sheets are never touched.
- Known limits: one run computes at a time; upload sources outside the four training sources reach the model as an unknown `src_pair`;
  only Dubai has a bundled basemap (other cities draw on a plain ground).

## Next steps

- [ ] User: fill the two deck placeholders, record the video from `VIDEO_SCRIPT.md`, check Unstop's upload format, submit by 20 Nov.
- [ ] User: accept the Expedia rules on Kaggle. Then model F: Expedia EDA, LambdaMART vs inverse-propensity-weighted, NDCG@5 on the
      random-order slice, duplicate injection. If it lands before the 20th, add one number to slide 2 and the script.
- [ ] Label the 400-pair sheet, then report model B against human labels and re-pick the accept threshold.
- [ ] Model A v2 on Kaggle: more blocking generators to lift the 0.959 ceiling; then a cross-encoder for the uncertain band (GPU).
- [ ] Model D on a second real supplier (Viator Basic Access) and a held-out set.
- [ ] Model E: supplier-reliability simulator with a cheapest-price baseline, reported with intervals.
- [ ] Round 2 scaffolding: review console, API, tests.
