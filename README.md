# Canon

**VoyageHack 4.0 · Multi-Supplier Optimization.**

Suppliers describe the same hotels, rooms and tours differently. Canon works out when they mean the same thing, and when
they don't. It matches listings across sources with blocking, a gradient-boosted pair model and constrained clustering,
splits rate plans out of room names, and types the relation between tours (same, variant, includes, different) instead
of merging look-alikes.

**Which folder is what:**

| Folder | What it is | Use it when |
|---|---|---|
| `canon/` | The Python library: matching, the cascade, the room/rate parser, tour relations | You want the algorithms; everything else imports this |
| `web/` | The website: `web/static/` (the pages) and `web/api/` (the local server that runs `canon/`) | You want to see or run Canon. **Start here** |
| `submission/round1/` | The Round 1 package: deck, video script, `numbers.json`, and `demo/`, the older six-tab validation demo the video is recorded from | You need the submission files |

There are three ways to look at it, from quickest to most complete:

| | What you see | What you need |
|---|---|---|
| **1. Public story page** | The explainer: the Dubai collapse, the problem, the method, the evidence | A browser: https://voyage-story-demo.vercel.app |
| **2. Website, run locally** | The same story, plus the **workbench** that runs the real pipeline live | Python 3.12, and the data and model files (see below) |
| **3. Validation demo** | The six-tab demo the Round 1 video is recorded from | A browser: open `submission/round1/demo/index.html` |

---

## 1. Quick look: the public story page

https://voyage-story-demo.vercel.app

This is the static part of the site in `web/static/`: no server and no database. The workbench section on that page says
that it runs locally, because it needs the Python pipeline and about 1 GB of data.

## 2. Run the website locally

### Story only (works straight after cloning)

The story sections ship their data in the repository (`web/static/data/*.json` and `web/static/numbers.json`), so any static
file server works:

```bash
cd web/static
python -m http.server 8765 --bind 127.0.0.1
```

Then open http://127.0.0.1:8765/. Opening `index.html` by double-clicking does **not** work, because browsers block the data
files for pages opened from disk.

### Full site with the workbench

**1. Create the Python environment** (Python 3.12). With [uv](https://docs.astral.sh/uv/):

```bash
uv venv --python 3.12 .venv
uv pip install --python .venv\Scripts\python.exe -r requirements.txt
```

Or with plain pip: `python -m venv .venv`, then `.venv\Scripts\pip install -r requirements.txt`.
On macOS or Linux, use `.venv/bin/python` wherever this README says `.venv\Scripts\python.exe`.

**2. Get the data and the trained model.** `data/` is not in the repository (see [What the workbench needs](#what-the-workbench-needs)).
If someone on the team has the folder, copy their `data/` into the repository root. Otherwise rebuild it as described in
[Rebuilding the data and models](#rebuilding-the-data-and-models).

**3. Start the server:**

```bash
.venv\Scripts\python.exe -X utf8 web\serve.py
```

It prints `Canon is running at http://127.0.0.1:8765/`. Open that address in Chrome or Edge, and keep the terminal open while
you use the site (Ctrl+C stops it). Use `--port 8766` if the port is taken.

The server binds to 127.0.0.1 only, so uploaded feeds never leave the machine. Nothing is fetched from the internet at runtime:
fonts, data and the map outline are all bundled.

If the model files are missing, the site still starts. The workbench then names the missing files and prints the command that
rebuilds them.

### A tour of the site

| Section | What to try |
|---|---|
| **01 Collapse** | Hover the map: the lens shows the raw listing names underneath. Scroll: matched listings draw together and the counter runs from 5,187 Dubai listings to 4,074 hotels, driven by the real clusters. |
| **02 Problem** | Hover a card to light up the same hotel from other feeds; switch to **Canonical** to stack 29 cards into 9 hotels. Prices here are simulated and tagged as such. |
| **03 Method** | Scroll through seven steps: blocking, evidence (the Atlantis pair, with the model's feature contributions), the cascade, clustering, rooms, tours, offers. |
| **04 Workbench** | Pick **Dubai** (about 15 s). Watch records appear, candidate pairs draw, scores stream in and clusters snap together. Step back and forth with the timeline. Click a point for its source records, or an edge for the pair inspector. Drag the accept threshold, answer pairs in the review queue, try the room and tour benches, export CSV or JSON. |
| **05 Evidence** | Every number carries a tag saying what it was measured against. |

To try an upload, use `web/static/samples/two_feeds_sample.csv` (338 real MakeMyTrip and Goibibo rows). Any CSV or JSON with a
name, latitude, longitude and source column works. The panel lists anything missing and what it changes.

Review answers are appended to `data/processed/web_review/answers.csv`. The existing label sheets are never touched.

### What the workbench needs

| Files | What uses them | Made by |
|---|---|---|
| `data/processed/city_matcher/model.lgb`, `featurizer_no_emb.joblib` | every workbench run | `scripts/train/city_matcher.py` |
| `data/processed/city_matcher/loco/model_<city>.lgb` | city presets: their labelled pairs are scored by a model that never saw that city | `scripts/train/loco_models.py` (about 30 s) |
| `data/interim/listings.parquet` | the 12 city presets, the tour bench's gazetteer | `scripts/build/build_listings.py` |
| `data/raw/makemytrip_hotels/*.csv`, `data/raw/goibibo_hotels/*.csv` | the Goibibo × MakeMyTrip preset | Kaggle, see below |

Run times on a laptop: Dubai about 15 s; London, the largest preset, about 2.5 minutes, most of it in blocking. One run computes at a time.

## 3. The validation demo and the Round 1 package

- `submission/round1/demo/index.html` is the six-tab validation demo the video is recorded from. It works offline when opened as a file, because
  its data, map outline and map library are bundled next to it.
- `submission/round1/` holds the deck, the video script and `numbers.json`. Its [README](submission/round1/README.md) explains
  each file and how to rebuild them.
- `submission/round1/numbers.json` is the single source of every figure quoted in the deck, the demo and the website.
  `submission/round1/VIDEO_SCRIPT.md` lists what may be claimed and with which qualifier.

## Rebuilding the data and models

Everything under `data/` is downloaded or generated; nothing in it is committed. Install the extra packages first:

```bash
uv pip install --python .venv\Scripts\python.exe -r requirements-pipeline.txt
```

Then run, in this order (each script skips what already exists). The OpenStreetMap step downloads regional extracts of several
GB in total (it deletes each one after use); the whole first run takes a while.

```bash
.venv\Scripts\python.exe -I -X utf8 scripts\download\overture_places.py
.venv\Scripts\python.exe -I -X utf8 scripts\download\osm_geofabrik.py
.venv\Scripts\python.exe -I -X utf8 scripts\download\wikidata_bbox.py
.venv\Scripts\python.exe -I -X utf8 scripts\download\wikivoyage_listings.py
.venv\Scripts\python.exe -I -X utf8 scripts\download\wikidata_class_labels.py
.venv\Scripts\python.exe -I -X utf8 scripts\build\build_listings.py
.venv\Scripts\python.exe -I -X utf8 scripts\train\city_matcher.py
.venv\Scripts\python.exe -I -X utf8 scripts\train\loco_models.py
```

`city_matcher.py` takes about 8 minutes and writes the model, the featurizer, the pairs and the clusters. `loco_models.py` rebuilds the
12 leave-one-city-out models; it checks that they reproduce the stored out-of-city scores.

For the Indian OTA preset, download two Kaggle datasets with the Kaggle CLI (needs a Kaggle API token):

```bash
kaggle datasets download -d PromptCloudHQ/hotels-on-makemytrip -p data/raw/makemytrip_hotels --unzip
kaggle datasets download -d PromptCloudHQ/hotels-on-goibibo -p data/raw/goibibo_hotels --unzip
```

Source details and licences are in `reports/data-sources.md`. After retraining, refresh the website's story data:

```bash
.venv\Scripts\python.exe -I -X utf8 web\build_site_data.py
```

This also copies `numbers.json` into `web/static/` for static hosting.

## Deploying the story page

`web/static/` is a self-contained static site with no build step. With the Vercel CLI:

```bash
npx vercel web/static --prod
```

Or import the repository at vercel.com with **Root Directory** set to `web/static` and the framework set to **Other**.

## What is measured, and what is not

- Hotel matching is measured against **independent keys** (a shared Wikidata ID, or a rare phone or website plus proximity) on
  cities held out from training. These are not hand labels; a sheet of pairs for people to label is prepared.
- Room and tour results use real catalogues and a **simulated second supplier**. The typed-relation accuracy is **in-sample**.
- Offer selection is a **simulated mechanism**, not a result. Ranking is designed and **not measured**.

The website tags every number this way, and reads every figure from `submission/round1/numbers.json`.

## Repository layout

```
canon/              the library: match.py (blocking, pair features), cascade.py (key rules, routing, clustering),
                    rooms.py (room / rate parser), activities.py (typed relations for tours)
web/                the website: serve.py (local server + API), api/ (pipeline around canon/),
                    static/ (the pages), build_site_data.py, API.md
scripts/            download/, build/, eda/, train/, figures/, demo/ (builds the Round 1 demo), deck/
reports/            data-sources.md, eda/, models/
submission/round1/  deck, video script, figures, numbers.json, demo/ (the Round 1 validation demo)
research/           problem research and architecture notes
data/               downloaded and generated data (not in git)
```

More detail: `PROGRESS.md` (build log and status), `web/api/README.md` (server, API and parity checks), `web/API.md`.

## Troubleshooting

| Symptom | Fix |
|---|---|
| Blank page, or "Could not load site data" | Start a server (above); don't open `web/static/index.html` from disk. |
| "Port 8765 is busy" | `.venv\Scripts\python.exe -X utf8 web\serve.py --port 8766` |
| Workbench says the model files are missing | Copy `data/` from a teammate, or run the rebuild steps; the message names the exact command. |
| The joblib featurizer fails to load | Install the pinned scikit-learn from `requirements.txt`. |
| Text looks odd when printing on Windows | Keep the `-X utf8` flag; supplier names include Arabic, Thai and Devanagari. |

Data credits: Overture Maps, © OpenStreetMap contributors (ODbL), Wikidata (CC0), Wikivoyage (CC BY-SA), Booking.com reviews (Kaggle, CC0),
MakeMyTrip and Goibibo samples (PromptCloud, CC BY-SA 4.0), Klook crawl (research use only).
