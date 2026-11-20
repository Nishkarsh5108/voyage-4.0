# Round 1 submission package

VoyageHack 4.0, Multi-Supplier Optimization. Idea round closes **20 Nov 2026, 11:59 PM IST**.
The round asks for a two-slide deck (cover and thank-you slides not counted) and a video explaining the idea.

## What is here

| File | What it is |
|---|---|
| `Canon_Round1_v3.pptx` | **The redesigned deck (20 Nov)**: cover, two content slides, thank-you, speaker notes on every slide. Slide 2 is the product graph drawn with real examples beside the pipeline; slide 3 is the evidence (a dumbbell of the 12 held-out cities and a table of what else is measured) with impact, feasibility and adoption. Every mark is a native, editable shape. Renders in `qa_v3/` |
| `Canon_Round1_v3.pdf` | The same deck as a PDF, for any viewer without Office fonts |
| `Canon_Round1.pptx` | The first deck (same content discipline, older look: tinted cards and KPI tiles). Kept until the user picks one. Renders in `qa/` |
| `Canon_Round1_v2.pptx` | The first deck with the 20 Nov numbers swapped in (`CANON_DECK_V2=1`) |
| `VIDEO_SCRIPT.md` | Timed shot list and narration for a 2 min 50 s video, tied to the demo's six tabs, plus what may and may not be claimed |
| `../../demo/index.html` | The validation demo to screen-record. Open it in a normal browser window. It works offline: data, map lines and the map library are all bundled in `demo/` |
| `screens/*.png` | Stills of every demo tab (3200 × 2000), as a fallback for the video and as extra slide art |
| `figures/*.png` | Seven slide-ready charts and three demo crops (`demo_match_evidence_crop.png` is the inset on the v3 thank-you slide) |
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
| Labelled POI benchmark (first deck) | cluster score 0.88 vs 0.78 for the best rule | Competition labels, 1.14 million records, unseen places | `reports/models/fsq_pair_model.md` |
| Public place-matching benchmark (v3 deck) | IoU 0.917, level with the published 1st place (0.917 on their own CV); best rule 0.76 | Competition labels (research use); 570k-record half never trained on. The splits differ: "level with", never "beat" | `reports/models/fsq_v2.md` |
| Tour relations on new phrasings (v3 deck, beside the in-sample 96%) | rules 74%, 87% with an open 7B LLM | Same products; rewrite templates written after the rules were frozen | `reports/models/activities_heldout.md`, `activities_llm.md` |
| Two real Indian OTA feeds | 484 hotels matched, no retraining | **No labels yet** | `reports/models/ota_matcher.md` |

Not measured, and the slide says so: offer choice (the demo panel is a simulation) and ranking (the benchmark data needs a Kaggle rules acceptance).
On the v3 deck the example details (pins within 22 m, name similarity 0.38, the room string, the tour relations) are read from `demo/data.js`, the same data the demo shows.

## Before you submit

1. **Pick the deck** (v3 or the first one). v3 already carries the team line (Team Hent-AI: Nishkarsh Singhal, Hirak Biswas) and the
   repository link (`github.com/Nishkarsh5108/voyage-4.0`), plus the live website (`voyage-story-demo.vercel.app`); both links are clickable
   in the PPTX and the PDF. The first deck still has placeholders. To change any of these lines on v3, from `scripts\deck`:
   `$env:CANON_TEAM = "..."; $env:CANON_LINK = "..."; $env:CANON_SITE = "..."; node build_round1_deck_v3.js`, then
   `powershell -ExecutionPolicy Bypass -File render.ps1 -Deck Canon_Round1_v3.pptx -Out qa_v3 -Width 2000 -Height 1125 -Pdf` to refresh the PNGs and the PDF.
   (For the first deck: the same variables, `node build_round1_deck.js`.)
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
cd scripts\deck; npm install; node build_round1_deck.js                   # the first deck
node build_round1_deck_v3.js                                              # the v3 deck
powershell -ExecutionPolicy Bypass -File render.ps1                       # first deck -> qa\*.PNG (needs PowerPoint)
powershell -ExecutionPolicy Bypass -File render.ps1 -Deck Canon_Round1_v3.pptx -Out qa_v3 -Width 2000 -Height 1125 -Pdf   # v3 -> qa_v3\*.PNG + PDF
```

The decks read every number from `numbers.json` (and v3 its example details from `demo/data.js`), so re-running the models and then these
steps keeps slides, demo and script in step. The v3 generator stops with an error if an example no longer matches what the slide draws
(for instance, if the Atlantis cluster loses a member), if a block would run off the slide, or if any text would need more lines than
its box holds at the widths of a substitute font (see the design notes).

## Design notes

- Two content slides have to carry idea, innovation, evidence, impact, feasibility and adoption, so they are dense. The smallest text is 10 to 12 pt; they are meant to be read on a screen, not projected to a hall.
- The demo marks its simulated parts with a yellow tag on screen. Keep those tags visible in the video.

v3 design, in short:

- Each content slide is one exhibit. Slide 2: the product graph with three real examples (Atlantis, The Palm in four sources and two scripts;
  `TWN PARTIAL SV HB NRF` split into room and rate; the Universal Studios Singapore family), with the pipeline as a spine on the right and the
  cascade drawn to scale (13% key rules, 60% small model, 27% sent on). Slide 3: a dumbbell of the 12 held-out cities (rule to model at equal
  precision) next to a table of everything else, each row with what it was measured against.
- Headlines are claims: "It is not deduplication. It is a product graph." and "It already runs on real data. TBO can start it in shadow mode."
  Every judging criterion has a labelled place: "What is new" (slide 2), "Impact for TBO", "Technical feasibility", "Adoption risk, contained" (slide 3).
- Status by form, one legend everywhere: solid = measured on real data, hatched = simulated second supplier, outline = designed, not yet measured.
  Four line styles for the four relations (solid same as, dashed variant of, arrow includes, dotted different); room attributes in ink, rate attributes in orange.
  On slide 2 the legend is split by what it explains: relations under the graph, status stacked under the pipeline, where most status marks are.
- Type: Franklin Gothic Medium / Book for headings and canonical values, Consolas for raw supplier strings, Arial for the Arabic name. All three
  ship with Office on Windows and Mac, so nothing needs embedding; the PDF covers any other viewer. Colours follow the website: paper `FBFAF7`,
  ink `15140F`, signal orange `FF4F00` (`C03A00` for orange text).
- The hatching is drawn as three short diagonal line shapes in each mark, not a pattern fill: some viewers (Google Slides, web previews)
  draw pattern fills as solid, which would make "simulated" look like "measured".
- Sized for viewers without the Office fonts. Google Slides, Keynote and most web previews have no Franklin Gothic or Consolas and
  substitute Arial / Helvetica and Courier New / Menlo, which are wider. The generator measures every text with Arial's character widths
  (plus 5%) and monospace at 0.6 em, so each box holds the substitute, and one-line labels are set not to wrap. Checked by rendering a copy
  of the deck with those fonts swapped in: no text collides on any slide. In PowerPoint the slides show the real fonts, a little airier.
  The PDF embeds the real fonts, so it looks the same everywhere.
