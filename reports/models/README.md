# Models: what each one is, what it was measured against, and how it compares

Every number below comes from a script in this repository and the report next to it. The "Truth" column says what each was
measured against; none of the matching numbers comes from hand labels yet.

| Task | Model (shipped / benchmarked) | Truth | Result | Report |
|---|---|---|---|---|
| Place matching, public benchmark | v2: fine-tuned multilingual-e5 retrieval + ~60 pair features + collective second stage (XGBoost) + xlm-roberta-base cross-encoder on the uncertain band | Foursquare competition labels, research use; 570k-record half never trained on | IoU **0.9165** (GBDT stages 0.897, v1 recipe 0.842, best rule 0.760); published 1st place: 0.875 GBDT stage, 0.9166 final (their CV) | `fsq_v2.md` |
| Hotel / attraction matching, 4 open sources, 12 cities | Stage 1: LightGBM pair model (the website runs this). Stage 2: + collective features. Stage 3: + xlm-roberta-base cross-encoder | Weak labels: shared Wikidata ID, or rare phone / URL plus proximity; each city held out | AP 0.976 -> **0.982** (stage 2) -> **0.983** (stage 3); recall at 99% precision 61% -> 70%; precision at 95% recall 89% -> 94% | `city_matcher.md`, `city_matcher_stage2.md`, `city_matcher_xenc.md` |
| Two real Indian OTA feeds | Stage-1 city model, no retraining | None (counts only) | 484 Goibibo hotels with a MakeMyTrip twin | `ota_matcher.md` |
| Room / rate mapping | Attribute parser (`canon/rooms.py`), then multilingual-e5 for what the parser leaves | Real room lists of 1,484 hotels, simulated second supplier | Correct mappings: parser 95.9% at 100% precision; **parser + embedding 99.8% at 99.8%**; embedding alone 80.7%; best fuzzy 59.6% | `rooms.md`, `rooms_semantic.md` |
| Sightseeing typed relations | Rules (`canon/activities.py`) + open LLM (Qwen2.5-7B-Instruct) | Real Klook products, simulated second supplier | In-sample (rules tuned there) 96.4%. **Held-out phrasings: rules 74.2%, LLM 87.4%, cascade 87.2%** | `activities.md`, `activities_heldout.md`, `activities_llm.md` |
| Offer arbitration, ranking | Designed, not measured | — | No number (ranking data waits on the Expedia rules being accepted on Kaggle) | — |

## Where the state of the art is, and where this sits

- **Place / POI matching.** The reference is Kaggle's Foursquare Location Matching (2022, 1,079 teams). Winning pipelines retrieve candidates
  by distance and by multilingual name embeddings, filter with a GBDT on ~100 similarity features, then re-rank with large multilingual
  transformers (xlm-roberta-large, mdeberta-v3) and merge matches transitively. The v2 pipeline follows the same structure at smaller cost:
  one fine-tuned e5-small retriever, a two-stage GBDT and one base-size cross-encoder instead of a large-model ensemble. Its GBDT stages
  score 0.897 (the winner reported 0.875 for its GBDT stage), and with the cross-encoder it reaches 0.9165, level with the winner's final
  0.9166. The CV splits differ, so read this as the same league, not a ranking.
- **Entity matching in general.** Pre-trained cross-encoders (Ditto and its successors) are the established supervised baseline;
  recent work shows fine-tuned small models and prompted open LLMs matching large proprietary ones on standard benchmarks. Both appear here:
  a fine-tuned xlm-roberta cross-encoder for hotels and places, and a prompted 7B open model for tour relations.
- **Design choice.** Cheap, explainable stages settle most pairs (91% of Foursquare candidates are rejected below p = 0.02 by the GBDT), and
  the transformer or LLM only sees the uncertain band. That keeps the expensive models proportional to the hard cases, not to the catalogue.

## Not measured yet

- Hotel matching against human labels: `data/processed/city_matcher/label_sheet.csv` (400 pairs) is prepared and not labelled.
- Rooms and tours on a real second supplier (needs Hotelbeds / Viator keys or a TBO sandbox).
- Ranking and offer arbitration.
