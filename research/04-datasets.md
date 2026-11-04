# Dataset catalogue

Public datasets for both statements, plus academic or gated sources that are substantially better where they exist.
Sizes and licences were checked through web and GitHub search in November 2026. Several hosts (Kaggle, Hugging Face, Zenodo) were not reachable from the research environment, so anything marked *check* should be confirmed on the source page before use.

## How to read the licence column

- **Shippable**: the licence allows commercial use (Apache-2.0, MIT, BSD, CC0, CC BY, CDLA-Permissive, ODbL with attribution and share-alike on derived databases). Safe to train models that TBO could run.
- **Research only**: non-commercial terms, competition rules or academic agreements. Use these to benchmark and validate methods, not to train what we would ship.

The DarwinBox statement in `ps/` requires that "any library or model you use must have a licence that allows commercial use". We assume TBO's judges apply the same instinct here, so we keep the two groups apart and say so in the README.

---

## A. Multi-supplier: hotel and attraction matching

| Dataset | What you get | Access and licence | Use |
|---|---|---|---|
| [Foursquare OS Places](https://opensource.foursquare.com/os-places/) | 100M+ commercial POIs with names, addresses, categories, coordinates ([release note](https://community.openstreetmap.org/t/foursquare-releases-100m-poi-dataset-under-apache-2-0/121883)) | Apache-2.0, **shippable** | One independent "supplier" view of hotels and attractions; candidate master |
| [Overture Maps Places](https://docs.overturemaps.org/guides/places/) | About 64M places (2025 GERS announcement) with GERS IDs and source attribution; on [AWS Open Data](https://registry.opendata.aws/overture/) | CDLA-Permissive-2.0 (OSM-derived parts excepted), **shippable** | Second independent view; GERS shows how global IDs are designed (and how ID churn hurts) |
| [OpenStreetMap](https://download.geofabrik.de/) (`tourism=hotel`, `tourism=attraction`, museums, viewpoints) | Crowd-mapped POIs, often with `wikidata`, `website`, `phone` tags | ODbL, **shippable** with attribution and share-alike on derived databases | Third view; its `wikidata` tags give weak match labels |
| [Wikidata](https://query.wikidata.org/) | QIDs, coordinates, official websites, chains for hotels and attractions | CC0, **shippable** | Cross-source join key and weak labels |
| Wikivoyage listings ("see", "do", "sleep") | Traveller-written listings with coordinates, phones, URLs; community CSV exports exist ([baturin/wikivoyage-listings](https://github.com/baturin/wikivoyage-listings), *check* freshness) or parse the dumps | CC BY-SA, shippable with attribution and share-alike | A noisy, human-written "supplier", good for hard cases |
| [Foursquare Location Matching](https://www.kaggle.com/competitions/foursquare-location-matching) (Kaggle 2022) | Over a million POI records with a `point_of_interest` label shared by duplicates | Competition terms, **research only** (*check*) | Largest labelled POI-matching set; benchmark the matcher |
| [World-POI](https://arxiv.org/abs/2510.21342) (2025) | Foursquare and OSM POIs linked by name and distance, as tabular and graph data | See paper | Extra weak labels across two sources |
| [Omni / NZER](https://arxiv.org/abs/2508.06584) (2025) | Geospatial entity-resolution benchmark with mixed geometries, plus existing point datasets | See paper, research | Compare against published geo-ER numbers |
| [PABench](https://liris.cnrs.fr/publis?id=7017) | Spatial entity matching of tourist POIs across location-service providers, with a taxonomy of inconsistencies | Research; download link not found, contact the LIRIS authors | Small, directly on-topic benchmark |
| [WDC Products](https://webdatacommons.org/largescaleproductcorpus/wdc-products/) (EDBT 2024) | Product-matching benchmark in 27 variants (share of corner cases, unseen entities, training-set size) ([arXiv 2301.09521](https://arxiv.org/abs/2301.09521)) | *check* dataset licence | Pre-train and stress-test the cross-encoder and LLM matcher on "unseen entity" generalisation |
| [DeepMatcher / Magellan datasets](https://github.com/anhaidgroup/deepmatcher/blob/master/Datasets.md) | Classic entity-matching benchmarks, including Fodors-Zagats (restaurants) | Research | Sanity checks against published numbers |

**How to pull a city.** Overture's CLI downloads places for a bounding box, for example
`overturemaps download --bbox=55.0,24.9,55.6,25.4 -f geoparquet --type=place -o dubai_places.parquet` (Dubai).
Geofabrik provides OSM country extracts. Foursquare OS Places is published as Parquet; see its docs for current access.

## B. Rooms, content and images

| Dataset | What you get | Access and licence | Use |
|---|---|---|---|
| [Hotels-50K](https://github.com/GWUvision/Hotels-50K) ([AAAI 2019](https://ojs.aaai.org/index.php/AAAI/article/view/3863)) | 1,027,871 images from 50,000 hotels and 92 chains, with hotel name, location and chain; TraffickCam test images from 5,000 hotels | Research (licence unclear, *check*) | Image-based hotel matching; train and test the image-overlap feature |
| [Hotel-ID 2021](https://www.kaggle.com/competitions/hotel-id-2021-fgvc8) and the 2022 FGVC9 edition | 97,527 room images from 7,770 hotels (2021); revised splits in [arXiv 2207.10200](https://arxiv.org/abs/2207.10200) | Competition terms, research only | Same, with harder interior shots |
| [515K Hotel Reviews Data in Europe](https://www.kaggle.com/datasets/jiashenliu/515k-hotel-reviews-data-in-europe) | About 515k Booking.com reviews of 1,493 hotels with coordinates; the `Tags` column is reported to include the room type booked (*check*) | Reported as CC0 (*check* on Kaggle) | Real room-name strings per hotel, to build and test the room-attribute extractor |
| [Inside Airbnb](https://insideairbnb.com/get-the-data/) | Listings (descriptions, amenities, photo URLs), daily calendars (availability, price), reviews, per city | CC BY 4.0, **shippable** with attribution; last 12 months free, older data by request ([policies](https://insideairbnb.com/data-policies/)) | Content-enrichment and grounded-description experiments |
| [Expedia lodging API enumerations](https://developers.expediagroup.com/supply/lodging/docs/property_mgmt_apis/product/reference/enumerations/) | Controlled vocabularies for bed types, bed sizes and related room attributes | Public documentation | Starting vocabulary for the room schema |
| Places365 (MIT CSAIL) | Scene categories such as hotel room, bathroom, swimming pool, lobby | Research use for the images (*check*) | Category list and optional fine-tuning for scene tags |
| [HotelRec](https://github.com/Diego999/HotelRec) ([LREC 2020](https://aclanthology.org/2020.lrec-1.605/)) | 50M TripAdvisor reviews with hotel URLs, ratings and sub-ratings | **Academic research only** | Quality and popularity signals; hotel ranking experiments |
| [UCSD Google Local (2021)](https://cseweb.ucsd.edu/~jmcauley/datasets.html#google_local) | 666M reviews over 4.96M US POIs, with coordinates, about 50k categories, hours and price | **Academic** (*check* terms) | Popularity features for attractions; another metadata "supplier" (US only) |

## C. Sightseeing content and supplier sandboxes

| Source | What you get | Access | Use |
|---|---|---|---|
| [Viator Partner API, Basic Access](https://docs.viator.com/partner-api/affiliate/technical) | Free on affiliate sign-up, no pre-authorisation. Condensed product summaries (title, description, main image, rating, price, availability schedules) and attraction endpoints (product codes per attraction, admission type, opening hours, address) ([affiliate page](https://partnerresources.viator.com/travel-commerce/affiliate/)) | Free; content and availability only, no booking at this tier | Real supplier-shaped activity content for the sightseeing benchmark |
| [Hotelbeds APItude evaluation keys](https://developer.hotelbeds.com/documentation/) | Test environment that mirrors production, 50 requests per day; hotel content and booking APIs. A third party says the Activities API has been sunset (*check*) | Free registration | Real hotel and room content for a handful of properties |
| [OCTO specification](https://docs.octo.travel/) | Open schema for tours and activities: supplier, product, option, unit, availability, bookings, cancellation cutoffs | Open standard | Canonical sightseeing schema |
| [Klook OpenAPI docs](https://klook.gitbook.io/openapi/api-core-mandatory/products) | OCTO-style product, option and unit definitions in practice | Docs public; data needs partnership | Schema reference |
| Amadeus Self-Service APIs | The self-service portal closed in July 2026 ([PhocusWire](https://www.phocuswire.com/amadeus-shut-down-self-service-apis-portal-developers)) | Gone | Do not plan on it; older tutorials still point to it |
| TBO's own APIs | Hotels and sightseeing APIs for registered partners | Ask the organisers whether a hackathon sandbox exists | Would make the demo far more convincing |

## D. Search ranking and conversion logs

| Dataset | What you get | Access and licence | Use |
|---|---|---|---|
| [Expedia ICDM 2013, "Personalize Expedia Hotel Searches"](https://www.kaggle.com/c/expedia-personalized-sort) | Training: 9,917,530 impressions in 399,344 searches; test: 6,622,629 in 266,230 ([arXiv 1311.7679](https://arxiv.org/abs/1311.7679)). Price, stars, review and location scores, historical price, promotions, **competitor price and availability for up to eight competitors**, a flag for searches shown in **random order**, click and booking labels | Competition terms, research only | The core LTR benchmark: debiasing on the randomised slice, and the competitor fields mimic a multi-supplier price comparison |
| [Expedia Hotel Recommendations](https://www.kaggle.com/c/expedia-hotel-recommendations) (Kaggle 2016) | About 38M click and booking events for 2013-2014, with destination ID, check-in and check-out dates, party; `destinations.csv` has 149 latent features per destination | Competition terms, research only | Look-to-book by destination and stay date; seasonality; destination embeddings |
| [Trivago RecSys Challenge 2019](https://tech.trivago.com/post/2019-03-11-recsyschallenge2019) | Session logs with listing impressions, displayed prices and clickouts, plus item metadata | Account and terms at `recsys.trivago.cloud` (*check* it is still served) | Closest public analogue of a real listing page |
| [Booking.com multi-destination trips (WSDM WebTour 2021)](https://github.com/bookingcom/ml-dataset-mdt) | 1,166,835 anonymised reservations grouped into trips (city, country, check-in and check-out, device, affiliate) | "May not be reused for commercial purposes", research only | Next-destination demand; destination similarity |

## E. Demand, bookings and cancellations (inventory statement)

| Dataset | What you get | Access and licence | Use |
|---|---|---|---|
| [Hotel booking demand](https://doi.org/10.1016/j.dib.2018.11.126) (Antonio, de Almeida, Nunes, *Data in Brief* 2019) | 119,390 bookings (resort hotel 40,060; city hotel 79,330) arriving July 2015 to August 2017, including cancelled ones: lead time, ADR, deposit type, segment, channel, agent, special requests ([repository](https://repositorio.iscte-iul.pt/handle/10071/16929)); Kaggle mirror `jessemostipak/hotel-booking-demand` | Open access (*check* the licence on the article) | Cancellation model, lead-time and booking-curve calibration, ADR seasonality |
| [Hotel Reservations](https://www.kaggle.com/datasets/ahsan81/hotel-reservations-classification-dataset) (Kaggle) | About 36k bookings with a cancellation label (*check*) | *check* | Second cancellation dataset, to test transfer |
| [Inside Airbnb calendars](https://insideairbnb.com/get-the-data/) | Per-listing daily availability and price | CC BY 4.0 | Occupancy and compression proxy per destination and night |
| [Monash Forecasting Repository](https://forecastingdata.org/): tourism | 366 monthly, 427 quarterly and 518 yearly tourism series from the Kaggle tourism competition ([Zenodo 4656096](https://zenodo.org/records/4656096)) | Open (*check* licence) | Forecasting benchmark with published baselines |
| [Eurostat tourism](https://ec.europa.eu/eurostat/databrowser/view/tour_occ_nim/default/table) (`tour_occ_nim` and related) | Monthly nights spent at tourist accommodation by country and region | Free reuse with attribution | Destination seasonality for European markets |
| [India Ministry of Tourism snapshots](https://tourism.gov.in/) | Monthly and annual bulletins: foreign tourist arrivals, Indian national departures, foreign exchange earnings (for example the [April 2026 snapshot](https://tourism.gov.in/sites/default/files/2026-06/Monthly%20Tourism%20Snapshot%20April%202026.pdf)) | Public (PDF) | Indian outbound demand, the market TBO's agents serve |
| UN Tourism data dashboard | Inbound and outbound arrivals by country | Free | Long-run market sizing |

## F. Flights: fares, seats and capacity

| Dataset | What you get | Access and licence | Use |
|---|---|---|---|
| [FlightPrices](https://www.kaggle.com/datasets/dilwong/flightprices) ([README](https://github.com/dilwong/FlightPrices)) | One-way Expedia itineraries searched 2022-04-16 to 2022-10-05: `searchDate`, `flightDate`, airports, fare basis, `baseFare`, `totalFare`, **`seatsRemaining`**, distance, segments. Very large | Kaggle (*check* licence) | Fare curves against days to departure; seat sell-down; when seats run out |
| [EaseMyTrip India flight prices](https://www.kaggle.com/datasets/shubhambathwal/flight-price-prediction) (2022) | About 300k domestic itineraries between India's busiest city pairs, economy and business, with `days_left` and price | Kaggle (*check* licence) | India-specific fare vs. days-left curves |
| [BTS T-100 and DB1B](https://www.transtats.bts.gov/) (US) | T-100: monthly seats, passengers and departures by carrier and route. DB1B: a 10% sample of tickets with fares, quarterly | Public domain | Load factors (sell-out proxy), capacity, fare distributions |
| [DGCA India traffic data](https://www.dgca.gov.in/) | Monthly domestic traffic and load factors by airline | Public | Indian capacity and seasonality |
| [OpenSky Network](https://openskynetwork.github.io/opensky-api/trino.html) | Historical ADS-B flight data via Trino | **Free for academic and government research** (apply); commercial licences exist | Route-level flight counts as a capacity signal |

## G. External signals

| Source | What you get | Access | Use |
|---|---|---|---|
| [Google Trends API](https://developers.google.com/search/apis/trends) (alpha since July 2025, [announcement](https://developers.google.com/search/blog/2025/07/trends-api)) | Search interest, five-year rolling window | Apply; small tester group | Destination interest; fall back to Wikipedia pageviews if not granted |
| [Wikimedia pageviews API](https://wikimedia.org/api/rest_v1/) | Daily views per article (destination and attraction pages) | Free | Interest proxy for destinations and attractions |
| [`holidays`](https://github.com/vacanza/holidays) | Public holidays by country and subdivision, India included | MIT | Holiday and long-weekend features |
| [Open-Meteo](https://open-meteo.com/en/docs/historical-weather-api) | Historical and forecast weather | CC BY 4.0 | Seasonality and weather shocks |
| ECB and RBI reference rates | Daily FX | Free | Price competitiveness across currencies |
| [PredictHQ](https://www.predicthq.com/support/can-i-use-predicthq-data-for-academic-research) | Verified events (concerts, sports, conferences, school holidays) with impact signals | Commercial; academics via the Dewey platform | Event-driven demand spikes |
| GDELT | Global news events | Free | Travel-advisory and unrest shocks for stress scenarios |

---

## H. Academic or gated access worth applying for now

These are clearly better than the open alternatives. Approval can take days, so apply this week if anyone on the team is eligible.

| Source | Why it is better | Who can get it | How |
|---|---|---|---|
| **STR SHARE Center** | Industry-standard hotel performance by market (occupancy, ADR, RevPAR), plus pipeline and P&L data. The best available signal for when destinations sell out | Faculty, staff and enrolled students of member schools (over 500 universities by 2015); data for classroom, student projects or research only ([STR workshop deck](https://the-ice.org/wp-content/uploads/2020/11/STR-SHARE-Center-workshop-THE-ICE-VIPoE.pdf), [Glion library guide](https://library.glion.edu/wp-content/uploads/2025/10/Search-tips-STR-Reports.pdf)) | Email `sharecenter@str.com` (a two-day turnaround was reported in 2020), or via the school's hospitality research centre ([Cornell example](https://business.cornell.edu/centers/chr/research-publications/exclusive-research-databases/)) |
| **Trivago RecSys 2019** | Real listing pages with prices and clickouts | Research terms | Account at `recsys.trivago.cloud` |
| **PredictHQ via Dewey** | Clean event data with attendance and rankings | Institutions on Dewey | PredictHQ support page above |
| **OpenSky historical** | Real flight activity by route | Academic and government researchers | Application form, then Trino |
| **HotelRec** | 50M hotel reviews | Academic only | GitHub link above |
| **UCSD Google Local** | 4.96M POIs with metadata and 666M reviews | Academic | McAuley lab page |
| **Inside Airbnb archive** | Multi-year calendars for long seasonality | Assessed by volume, intended use and requester | Archived data request form |
| **Foursquare Location Matching** | Largest labelled POI-matching set | Competition terms | Kaggle |

---

## I. Starter packs: what to download first

**Multi-supplier (about one day of data work)**

1. Overture, OSM and Foursquare OS Places extracts for Dubai, Bangkok and Singapore: hotels and attractions.
2. Wikidata QIDs, websites and phones for the same entities (weak labels).
3. Expedia ICDM 2013 (ranking and debiasing).
4. Hotels-50K metadata plus an image subset for the same chains.
5. Viator Basic Access attractions and products for the same three cities.
6. Hotelbeds test content for 20 to 50 hotels, for real room strings.

**Inventory (about one day of data work)**

1. Antonio et al. hotel bookings (cancellations, lead times, booking curves).
2. Expedia Hotel Recommendations 2016 (look-to-book by destination and date).
3. FlightPrices for a few routes, plus EaseMyTrip India.
4. Ministry of Tourism monthly snapshots and DGCA traffic for 2023-2026.
5. Eurostat nights spent and the Monash tourism series (forecast benchmarks).
6. `holidays` plus Wikipedia pageviews for 30 destinations TBO's agents sell.

Kaggle sets need the Kaggle CLI and accepting each competition's rules on the website first, for example
`kaggle competitions download -c expedia-personalized-sort` and `kaggle datasets download -d jessemostipak/hotel-booking-demand`.
