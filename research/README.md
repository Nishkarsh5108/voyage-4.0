# VoyageHack 4.0 research: Multi-Supplier Optimization and Automated Inventory Optimization

Research for the team, 4 November 2026. Start here; each section links to the detailed document.

## Summary

1. **Format and dates.** Registration closes **12 Nov 2026**. Round 1 (due **20 Nov**) is a deck with only **two content slides**, plus, going by 3.0, a short video, in a zip.
   Round 2 is a 10-slide deck with code, documents and a video. The finale is listed for **8 Jan 2027**.
   Judging covers potential impact, technical feasibility, innovation, adoption risk, prototype quality and alignment with objectives. → [`01-hackathon-intel.md`](01-hackathon-intel.md)
2. **No data comes with either statement.** A competing team's repository says so explicitly. Credible evaluation on real public data will set an entry apart. → [`04-datasets.md`](04-datasets.md)
3. **Multi-supplier is not deduplication.** It is a three-level product graph with typed relations (`SAME_AS`, `VARIANT_OF`, `INCLUDES`), followed by room/rate disentanglement, reliability-aware offer selection and debiased ranking.
   TBO renewed Vervotech for AI hotel mapping in May 2026, so the entry should consume existing mapping, not compete with it, and win on sightseeing, offers and ranking. → [`02-multi-supplier-optimization.md`](02-multi-supplier-optimization.md)
4. **Inventory is not "forecast, then knapsack".** Demand is censored by sell-outs, searches are mostly machine traffic, sell-outs must be measured across all suppliers, and inventory comes as contracts with release options.
   The proposal is a two-stage stochastic MILP that chooses contract types, quantities, prices and supplier integrations with CVaR in the objective. → [`03-inventory-optimization.md`](03-inventory-optimization.md)
5. **The two statements share one foundation**: a canonical inventory graph. Demand and sell-outs only make sense on the real hotel, not on one supplier's listing. Say this in the pitch whichever statement you pick.
6. **Academic access that is clearly better than the open alternatives:** STR SHARE Center (hotel market performance), Trivago RecSys 2019 (listing-page logs), OpenSky (flight activity), PredictHQ via Dewey (events), HotelRec and UCSD Google Local (reviews and POIs). Apply this week if anyone is eligible.

## Recommendation: pick Multi-Supplier Optimization

Pick it unless the team's strongest skills are forecasting and operations research.

1. **Less competition is visible.** A polished inventory entry is already public ([Allotment Atlas](https://github.com/shanshantanusingh113-max/allotment-atlas)), and its authors rate multi-supplier "Skip: matching problem; mostly tables". No 4.0 multi-supplier project turned up on GitHub.
2. **It can be proven on real data.** Every module has a real, independent public benchmark: OSM, Overture and Foursquare for matching; Expedia ICDM 2013 for ranking; Hotels-50K for images; Viator and Hotelbeds for supplier-shaped content.
   Inventory has to rely on a simulator, because no public data describes TBO's pre-buy business.
3. **It touches TBO's core metrics.** Every search and booking passes through matching, offer selection and ranking. TBO already pays a vendor for part of this, which proves the pain and gives a clear complementary position.
4. **It fits the team.** Entity resolution, guarded LLM extraction and fact-checked generation are close to what the team built in roadScribe (the Plan-Ground-Realize protocol, claim verification against a ledger).

The main risk is a demo that looks like tables. The storyboard in [`02-multi-supplier-optimization.md` §7](02-multi-supplier-optimization.md#7-demo-storyboard-about-5-minutes) is built to be visual: before/after listing pages, map clusters, photo evidence and difference chips.

**If you choose Inventory instead**, differentiate on true demand across suppliers, contracts with recourse, CVaR optimized directly, joint pricing, the supplier-integration decision, and a simulator calibrated on named real data ([`03` §7](03-inventory-optimization.md#7-differentiation-from-the-visible-competitor)).

## Decision matrix

| Criterion | Multi-Supplier Optimization | Automated Inventory Optimization |
|---|---|---|
| Impact on TBO | High: every search and booking; conversion, price competitiveness, failed bookings | High, but limited to inventory TBO chooses to pre-buy |
| Credible evaluation on real data | Strong: real independent sources and real search logs | Medium: simulator calibrated on public data |
| Visible competition | None found | At least one polished public entry |
| Demo appeal | Medium; needs deliberate design | High: money and risk charts |
| Room for innovation | High: typed product graph, reliability-adjusted price, debiased duplicate-aware ranking | High: contract-aware stochastic CVaR, unconstraining, supplier integration |
| Adoption risk | Low to medium: works with the existing mapping vendor, shadow mode | Medium to high: commits capital, needs finance sign-off |
| Fit with the team's track record | Strong | Good |

## The two architectures at a glance

**Multi-Supplier ("Canon")**: ingest into a canonical schema (OCTO-shaped for activities) → blocking on H3 geo cells, name ANN and exact keys → scoring cascade (rules → Fellegi-Sunter → LightGBM → cross-encoder → LLM → human) → constrained clustering with stable IDs → canonical product graph → room/rate mapping and sightseeing families → golden record (images, grounded text) → offer arbitration on reliability-adjusted effective price → LambdaMART ranking with position-bias correction and duplicate collapsing.

**Inventory ("Hedge")**: clean and sessionize signals → unconstrain demand on canonical hotels → probabilistic, hierarchical, booking-curve-aware forecasts (LightGBM-quantile, Chronos-2, conformal) → correlated and stress scenarios → stochastic MILP over hard pre-buys, allotments with release and free-sale top-ups, with a price ladder, supplier integration and CVaR → planner with buy-by dates, risk frontier and budget shadow price → human approval → weekly re-plan.

## Documents

| File | Contents |
|---|---|
| [`01-hackathon-intel.md`](01-hackathon-intel.md) | Event facts, judging criteria, what TBO's other statements say about the judges, competitor and community scan, TBO context, questions for the organisers |
| [`02-multi-supplier-optimization.md`](02-multi-supplier-optimization.md) | Requirements → ML tasks, positioning, architecture, components, evaluation, data plan, demo storyboard |
| [`03-inventory-optimization.md`](03-inventory-optimization.md) | Requirements → decisions, architecture, the optimization model, evaluation, simulator calibration, competitor comparison |
| [`04-datasets.md`](04-datasets.md) | Public and academic datasets with access, licences and use, plus starter packs |
| [`05-execution-plan.md`](05-execution-plan.md) | Timeline, proof spike, the two Round 1 slides, the Round 2 build plan, roles |

## What could not be checked

From this environment, `unstop.com` (and its API and CDN), `hiretoday.in`, Kaggle, Hugging Face, arXiv, Zenodo, Reddit, LinkedIn and `tbo.com` were blocked.
Event details come from search-engine summaries of those pages, and the Unstop discussion threads could not be read. GitHub was reachable, which is how the competitor scan was done.
To let a future session read the Unstop discussions, add `unstop.com` and `api.unstop.com` under Allowed domains in the environment's network settings ([docs](https://code.claude.com/docs/en/cloud-environments#network-access)), or paste the threads into the chat.
