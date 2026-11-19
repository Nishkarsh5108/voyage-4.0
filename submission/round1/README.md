# Round 1 submission package

VoyageHack 4.0, Multi-Supplier Optimization. Idea round closes **20 Nov 2026, 11:59 PM IST**.
The round asks for a two-slide deck (cover and thank-you slides not counted) and a video explaining the idea.

## What is here

| File | What it is |
|---|---|
| `Canon_Round1.pptx` | The deck: cover, two content slides, thank-you. Speaker notes on every slide. Charts and shapes are native, so everything is editable in PowerPoint |
| `VIDEO_SCRIPT.md` | Timed shot list and narration for a 2 min 50 s video, tied to the demo's six tabs, plus what may and may not be claimed |
| `../../demo/index.html` | The validation demo to screen-record. Open it in a normal browser window. It works offline: data, map lines and the map library are all bundled in `demo/` |
| `screens/*.png` | Stills of every demo tab (3200 × 2000), as a fallback for the video and as extra slide art |
| `figures/*.png` | Seven slide-ready charts and two demo crops |
| `numbers.json` | Every number the deck, demo and script quote, with the kind of truth behind it |

## The idea in four sentences

Suppliers describe the same hotels, rooms and tours differently, and the statement asks for duplicates to be found *without losing meaningful differences*.
So Canon does not merge look-alikes: it builds a product graph with typed relations (same, variant, includes, different) over three levels: hotel, room, rate plan; and attraction, product, option.
It splits the rate plan out of the room name before matching, prices supplier reliability into the offer, and runs the cheapest tool first so cost follows the hard cases.
It is built to sit beside an existing hotel-mapping vendor: vendor IDs are one more input.

## Evidence behind each claim

| Claim on the slide | Value | Measured against | Where it comes from |
|---|---|---|---|
| Matches found at equal precision, unseen cities | 88% vs 58% for a name + distance rule | Independent keys (Wikidata ID, rare phone or URL). **Not hand labels** | `reports/models/city_matcher.md`, `scripts/figures/round1_figures.py` |
| Same, Bangkok held out | 91% vs 27% | Same | Same |
| Candidate pairs settled without an expensive model | 73% of 1.23 million | Measured on the 12-city run | `reports/models/city_matcher.md` |
| Dubai lodging listings to canonical hotels | 5,187 to 4,074 | Output of the pipeline | Same |
| Renamed room strings mapped to the right room | 96% vs 60% for the best fuzzy matcher | Real room lists of 1,484 hotels; **second supplier simulated** | `reports/models/rooms.md` |
| Tour variants a deduplicator would merge | 95% (combos: 100%) | 87 real Klook Singapore products; **second supplier simulated** | `reports/models/activities.md` |
| Typed relations accuracy | 96% over four relation types | Same; **in-sample** (rules were tuned on these pairs) | Same |
| Labelled POI benchmark | cluster score 0.88 vs 0.78 for the best rule | Competition labels, 1.14 million records, unseen places | `reports/models/fsq_pair_model.md` |
| Two real Indian OTA feeds | 484 hotels matched, no retraining | **No labels yet** | `reports/models/ota_matcher.md` |

Not measured, and the slide says so: offer choice (the demo panel is a simulation) and ranking (the benchmark data needs a Kaggle rules acceptance).

## Before you submit

1. **Fill in two placeholders in the deck**: the team line on the cover and the link line on the thank-you slide.
   Either edit them in PowerPoint, or rebuild with
   `$env:CANON_TEAM = "Team X: A, B, C"; $env:CANON_LINK = "github.com/..."; node scripts\deck\build_round1_deck.js`.
2. **Record the video** from `VIDEO_SCRIPT.md`.
3. **Check the submission format on Unstop** (zip or separate uploads, video length limit, file size). The 3.0 edition asked for a zip with the deck and video; 4.0's page should be read again.
4. Optional but worth it: label the 400 pairs in `data/processed/city_matcher/label_sheet.csv`. With that, the matching number can be stated against human labels.

## Rebuilding everything

```powershell
.venv\Scripts\python.exe -I -X utf8 scripts\figures\round1_figures.py     # charts + numbers.json
.venv\Scripts\python.exe -I -X utf8 scripts\demo\build_demo_data.py       # demo/data.js
.venv\Scripts\python.exe -I -X utf8 scripts\demo\build_basemap.py         # demo/basemap.js (offline map; downloads a 258 MB OSM extract, then deletes it)
powershell -File scripts\demo\screenshots.ps1                             # screens/*.png (headless Edge)
.venv\Scripts\python.exe -I -X utf8 scripts\figures\round1_figures.py     # again, to crop the fresh screenshots
cd scripts\deck; npm install; node build_round1_deck.js                   # the deck
powershell -File scripts\deck\render.ps1                                  # slide PNGs for a visual check (needs PowerPoint)
```

The deck reads every number from `numbers.json`, so re-running the models and then these steps keeps slides, demo and script in step.

## Design notes

- Two content slides have to carry idea, innovation, evidence, impact, feasibility and adoption, so they are dense. The smallest text is 10 to 12 pt; they are meant to be read on a screen, not projected to a hall.
- The demo marks its simulated parts with a yellow tag on screen. Keep those tags visible in the video.
