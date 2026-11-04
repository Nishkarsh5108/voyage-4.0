# Execution plan

Written on 4 November 2026. Dates come from the Unstop listing via search; confirm them on the page.

## 1. Timeline

| When | What |
|---|---|
| 4-6 Nov | Choose the statement. Assign roles. Anyone eligible applies for academic data (STR SHARE, Trivago RecSys 2019, OpenSky). Sign up for Viator affiliate Basic Access and Hotelbeds evaluation keys. Email the organisers the questions in [`01-hackathon-intel.md`](01-hackathon-intel.md#6-questions-to-send-the-organisers) |
| **by 12 Nov** | **Register the team on Unstop (registration closes)** |
| 6-14 Nov | Proof spike (section 2): real numbers for the slides |
| 14-18 Nov | Write the two slides, record the video, dry-run with someone outside the team |
| **20 Nov** | **Submit Round 1** |
| Shortlist to Round 2 deadline (dates to be announced) | Four-week prototype build (section 4) |
| 8 Jan 2027 | Finale |

## 2. Proof spike (about one week, two or three people)

The aim is a few numbers from real data. "Precision 99.2% on 1,400 labelled Dubai hotel pairs" is far more persuasive on a slide than any adjective.

**If Multi-Supplier**

1. **Dubai hotel matching.** Pull Dubai hotels from OSM, Overture and Foursquare OS Places. Create weak labels from Wikidata QIDs, website domains and phones. Hand-label 300 to 500 pairs in a quick notebook UI.
   Run Splink, then LightGBM on the full feature set. Report precision and recall, and the share of pairs each stage resolves.
2. **Ranking on Expedia ICDM 2013.** LambdaMART baseline vs. an inverse-propensity-weighted version, with NDCG@5 on the randomised slice.
   Then inject cross-supplier duplicates and report unique properties in the top 10, with and without collapsing duplicates.
3. **Stretch: sightseeing families.** About 20 Dubai attractions from Viator Basic Access. Extract attributes with an LLM, group products into `SAME_AS` / `VARIANT_OF` / `INCLUDES` families, and check by hand.

**If Inventory**

1. **Unconstraining check.** Take the Antonio et al. hotel bookings, impose artificial capacities, and compare how much censored demand the funnel model and EM recover.
2. **Forecast backtest.** Seasonal naive vs. LightGBM-quantile vs. Chronos-2 on the Monash tourism monthly series and daily arrivals from the Antonio data. Report WAPE, pinball loss and interval coverage.
3. **Toy optimizer.** 30 items, 3 contract types, 200 scenarios. Show the value of the stochastic solution (VSS) and the CVaR frontier.

## 3. Round 1: the two slides

Only two content slides are allowed, so every element must earn its place. Each slide should carry one diagram, one number and one sentence a TBO executive would repeat.

### Multi-Supplier version

**Slide 1: what TBO actually needs, and the system.**

- Left third, the insight: "It is not deduplication. It is a three-level product graph." Show the Burj Khalifa example as four small cards: identical / variant (+ hotel pickup) / combo (+ Aquarium) / different (Level 148).
  One line on rooms vs. rates: "Deluxe King Sea View, Breakfast, Non-Refundable" splits into a room and a rate.
- Right two-thirds, the architecture strip: Ingest → Block → Cascade (rules → Fellegi-Sunter → GBDT → cross-encoder → LLM → human) → Canonical graph → Rooms and activities → Offers (reliability-adjusted price) → Ranking. Tag it "consumes existing Vervotech IDs".

**Slide 2: evidence, impact, adoption.**

- Spike results: matching precision and recall, NDCG uplift, unique properties in the top 10, LLM calls per 1,000 records.
- Impact chain: fewer duplicate cards → clearer choice → the cheapest *reliable* offer shown → higher conversion and fewer failed bookings.
- Feasibility: stack (all Apache, MIT or BSD), latency budget, cost per million records.
- Adoption: shadow mode, per-destination rollout, review thresholds as configuration, audit log.
- One line on Round 2: what will be demoed.

### Inventory version

**Slide 1.** The insight: "Demand is censored, inventory comes as contracts, and sell-outs must be measured across suppliers." A sketch of bookings flattening during sell-outs while searches rise.
Then the architecture strip: Signals → Unconstrain → Probabilistic forecast → Scenarios → Stochastic MILP (contracts, prices, suppliers, CVaR) → Planner with approval.

**Slide 2.** Spike results (unconstraining recovery, forecast WAPE and coverage, VSS), the impact chain (risk-adjusted profit, availability, shadow price of budget), feasibility (HiGHS, solve time), adoption (decision support with human approval; weekly re-planning; exposure caps).

### Video (2-3 minutes)

30 s problem → 60 s architecture → 45 s evidence → 30 s adoption and next steps. Record a screen capture of the spike notebooks or a rough UI; do not just read the slides.

## 4. Round 2: four-week prototype

### Multi-Supplier

| Week | Deliverables |
|---|---|
| 1 | Canonical schemas; benchmark builder (real sources plus synthetic suppliers with ground truth); property-matching cascade v1; review console skeleton |
| 2 | Room/rate extraction and matching; sightseeing relation classifier and product families; image pipeline and golden record |
| 3 | Supplier reliability simulator and offer arbitration (RAEP); debiased ranking; listing page before/after |
| 4 | Evaluation report; measured cost and latency; tests; demo polish; 10-slide deck; video; README with setup, data sources and licences, and the AI assistants used |

Suggested repository layout:

```
canon/            ingest, schema, block, score, cluster, rooms, activities, content, offers, rank, review, api
eval/             benchmark builders, metrics, reports
web/              demo listing page and review console
tests/
data/             gitignored; download scripts only
docs/
```

### Inventory

| Week | Deliverables |
|---|---|
| 1 | Calibrated simulator with planted truth; data loaders for the public datasets; unconstraining |
| 2 | Forecasting stack (booking curves, LightGBM-quantile, Chronos-2, conformal, reconciliation); cancellation and price-response models |
| 3 | Scenario generator; stochastic MILP with contracts, price ladder, supplier integration and CVaR; timing |
| 4 | Backtest harness (VSS, EVPI, regret, ablations); planner UI; LLM analyst with tool calls; deck, video, README |

```
hedge/            data, unconstrain, forecast, scenarios, optimize, timing, analyst, api
eval/             backtests, ablations, reports
web/              planner UI
tests/
```

### Ten-slide deck outline (Multi-Supplier)

1. Problem and insight
2. Architecture
3. Hotel matching (with evidence UI)
4. Rooms and rates
5. Sightseeing families
6. Offers and supplier reliability
7. Ranking
8. Results against baselines
9. Adoption, governance and cost
10. Roadmap and what TBO would need to pilot it

## 5. Roles (for 2 to 5 people)

1. **Data and matching lead**: blocking, cascade, clustering, benchmark.
2. **NLP and LLM lead**: attribute extraction, sightseeing relations, grounded descriptions, cost tracking.
3. **Ranking and evaluation lead**: LTR, debiasing, offline evaluation, the results slide.
4. **Product and demo lead**: UI, storyboard, deck, video.
5. Optional **inventory bridge**: sell-out and coverage-gap analytics across suppliers, the link to the other statement.

With two or three people, merge roles 1 and 2 and drop role 5.

## 6. Engineering rules (taken from TBO's other statements)

- Every library, model and shipped dataset under a commercial-use licence, listed in the README. Research-only datasets used only for benchmarks, and labelled as such.
- Thresholds, policies and the model provider live in configuration, not code.
- Every automated decision is logged with its inputs, model version and reason, and can be reversed.
- Cost and latency are measured from real runs and reported.
- Clean commit history with individual authorship, since finalists are questioned on what they built. Note which AI coding assistants were used and for what.

## 7. Main risks

| Risk | Mitigation |
|---|---|
| Missing the 12 November registration | Register first, before any build work |
| Spike numbers not ready by 18 November | Scope the spike to experiment 1 alone if needed; one solid number beats three shaky ones |
| Round 2 dates are short | The four-week plan has a working end-to-end slice by the end of week 2; weeks 3 and 4 deepen it |
| Data access refused (academic sources) | Every module has an open fallback in [`04-datasets.md`](04-datasets.md) |
