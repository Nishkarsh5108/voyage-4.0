# Data sources: what was checked, what was downloaded, what is blocked

Checked on 14 November 2026 from the build machine. This replaces the *check* marks in `research/04-datasets.md` for the Multi-Supplier statement with what actually happened when each source was tried.
Everything downloaded sits under `data/raw/<source>/` (gitignored); the script that fetched it is named in each row.

## Summary

- **Downloaded and usable now: nine sources**, about 1.1 GB. They cover property and attraction matching (four open sources in 12 cities, plus a labelled benchmark of 1.14 million records), room names (2,383 real strings, plus about 6,000 Indian ones) and two real overlapping hotel feeds.
- **Blocked, and it matters: Expedia ICDM 2013.** The ranking track cannot start until someone accepts the competition rules on Kaggle (one click, details below).
- **Thin: product-level sightseeing data.** 192 Klook products and 192 Viator summaries are all that is public. Viator's free API needs a sign-up.
- **Three things turned out differently from the research notes**: Overpass was down, so OSM comes from Geofabrik extracts; Foursquare OS Places is now gated, but Overture already includes Foursquare records; the Foursquare matching competition no longer serves its files, so a community mirror was used.

## Downloaded

| Source | What we have | Size | Licence | Fetched by | Used for |
|---|---|---:|---|---|---|
| **Overture Maps Places**, release 2026-10-21.0 | 2,898,597 places in 12 city boxes; 231,775 are lodging or attractions. Every record names its upstream provider (Meta 70%, BrightQuery 18%, Microsoft 9%, Foursquare 2% of lodging) | 530 MB | CDLA-Permissive-2.0, shippable | `scripts/download/overture_places.py` | Supplier 1 in the matching benchmark |
| **OpenStreetMap** (Geofabrik extracts of 14 Nov) | 84,745 tourism, historic and leisure POIs with full tag maps; 55,836 named lodging or attraction listings | 5 MB after filtering | ODbL, shippable with attribution and share-alike | `scripts/download/osm_geofabrik.py` | Supplier 2; its `wikidata` tags are a cross-source key |
| **Wikidata** | 171,016 items with a coordinate inside the boxes; 36,298 are hotels or attractions | 49 MB | CC0, shippable | `wikidata_bbox.py`, `wikidata_class_labels.py` | Supplier 3; the QID is the cleanest truth key |
| **Wikivoyage listings** | 8,438 listings from 12 city guides and their district pages; 3,947 see / do / sleep | 4 MB | CC BY-SA, shippable with attribution and share-alike | `wikivoyage_listings.py` | Supplier 4: noisy, human-written, often with a phone and URL |
| **Foursquare Location Matching** (Kaggle 2022) | 1,138,812 POI records of 739,972 real places with the true place ID; 578,907 labelled pairs | 206 MB | Competition terms: **research only** | Kaggle dataset `robikscube/foursquare-location-matching-parquet` | Largest labelled benchmark for the pair model |
| **515K Booking.com hotel reviews** | 515,738 reviews of 1,492 hotels in six European cities; each carries the booked room name | 238 MB | CC0 | Kaggle `jiashenliu/515k-hotel-reviews-data-in-europe` | 2,383 real room-name strings, weighted by bookings |
| **MakeMyTrip hotels** (PromptCloud, 2016) | 20,046 rows, 15,168 properties, 733 cities, room-type strings | 38 MB | CC BY-SA 4.0 | Kaggle `PromptCloudHQ/hotels-on-makemytrip` | Real supplier feed A (India) |
| **Goibibo hotels** (PromptCloud, 2016) | 4,000 properties, 555 cities, room types, facilities, descriptions | 10 MB | CC BY-SA 4.0 | Kaggle `PromptCloudHQ/hotels-on-goibibo` | Real supplier feed B (India); 587 likely twins of feed A |
| **Klook activity crawl** (Singapore, Malaysia; 2019) | 192 products with 467 package options, prices, coordinates, cancellation text | 11 MB | None stated: **research only** | `scripts/download/hf_public.py` (Hugging Face `malaysia-ai/crawl-klook`) | Real product and option strings for the sightseeing schema |
| **Viator tracker sample** | 192 product summaries in 8 cities | 0.1 MB | "Other": research only | Kaggle `kenmutisya/viator-tours-tracker-sample` | Field names only; too small to model |

Cities: Dubai, Bangkok, Singapore (core); Delhi, Mumbai, Goa (overlap with the Indian hotel feeds); London, Paris, Amsterdam, Barcelona, Vienna, Milan (overlap with the Booking.com reviews).
The four open sources are normalised into one table, `data/interim/listings.parquet`, by `scripts/build/build_listings.py`.

## Blocked or gated

| Source | What happened | What unblocks it | Effect |
|---|---|---|---|
| **Expedia ICDM 2013** (`expedia-personalized-sort`) | File listing works; the download returns **403** for both Kaggle accounts tried, because neither has accepted the competition rules | Sign in to Kaggle as the account whose token is used, open https://www.kaggle.com/competitions/expedia-personalized-sort/rules, accept. Then `kaggle competitions download -c expedia-personalized-sort -f data.zip -p data/raw/expedia_icdm2013` | **The whole ranking track waits on this**: LambdaMART, position-bias correction on the random-order slice, duplicate collapsing |
| **Foursquare OS Places** | Now a gated dataset on Hugging Face (`foursquare/fsq-os-places`); the old public S3 bucket lists nothing. No Hugging Face token on the build machine | A Hugging Face account that accepts Foursquare's terms, then `hf auth login` | Low. Overture already carries Foursquare-sourced records. A fifth independent supplier would be a bonus |
| **Foursquare Location Matching, official files** | The competition page now serves only `sample_submission.csv` | Nothing to do | None: a community parquet copy on Kaggle was used. It is the same competition data, so the competition terms still apply |
| **Overpass API** (OSM queries) | All three public instances accepted the TLS connection and never answered | Nothing to do | None: replaced by Geofabrik extracts parsed with DuckDB, which is also more reproducible |
| **Musement catalogue API** | Requires a partner application header | Partner agreement | Not pursued |
| **Viator Basic Access**, **Hotelbeds evaluation keys** | Need a person to sign up | Free affiliate sign-up (Viator); free registration (Hotelbeds) | **Medium to high.** These are the only real routes to product-depth sightseeing content and to live hotel room and rate content |

Not attempted yet: Hotels-50K and Hotel-ID (images, for Round 2), Trivago RecSys 2019 (needs an account), Expedia Hotel Recommendations 2016 (4 GB; belongs mostly to the inventory statement).

## What the downloads showed

1. **Four open sources give a real cross-supplier benchmark.** 34,482 pairs of listings from different sources share a Wikidata QID, a phone number or a URL. That is evidence the matcher never sees, so it can act as truth. Details in `reports/eda/city_sources.md`.
2. **Keys are noisy in ways worth knowing.** One reservation number is attached to 761 Goa listings. Wikidata holds duplicate items for many hotels. A hotel and the spa inside it share a phone. Each of these is a small version of a problem TBO's own feeds will have.
3. **Two real supplier feeds overlap.** 587 of 4,000 Goibibo properties (14.7%) have a likely twin in the MakeMyTrip sample; for those, the two suppliers' coordinates differ by a median of 74 m and by more than 300 m in 30% of cases. Details in `reports/eda/ota_hotels.md`.
4. **Room names are few and repeat.** 285 strings cover 90% of bookings in the Booking.com set; 9% of room names carry a rate or package term. Details in `reports/eda/rooms.md`.
5. **Sightseeing has a POI layer and almost no product layer.** 228,165 attraction listings against 192 products with options. Details in `reports/eda/sightseeing.md`.

## Licence position

- **Safe to train a shippable model on**: Overture, OpenStreetMap, Wikidata, Wikivoyage, the 515K reviews, MakeMyTrip, Goibibo. OSM and Wikivoyage carry attribution and share-alike duties for derived databases.
- **Benchmark only**: Foursquare Location Matching, the Klook crawl, the Viator sample. Models trained on these are reported as research results and are not the shipped artefact.

## Three actions for the team

1. **Accept the Expedia competition rules** with the Kaggle account in use. Two minutes; unblocks ranking.
2. **Sign up for Viator Basic Access** and, if possible, Hotelbeds evaluation keys. Ask the organisers whether a TBO sightseeing or hotel sandbox exists.
3. **Label the 400-pair sheet** at `data/processed/city_matcher/label_sheet.csv` (see `reports/models/city_matcher.md`). The matcher's precision is currently measured against keys; a few hundred human labels make the number defensible on a slide.
