# Hackathon intel: VoyageHack 4.0

**About the sources.** The research environment's network policy blocked `unstop.com` (including its API and CDN), `hiretoday.in`, Kaggle, Hugging Face, arXiv, Zenodo, Reddit, LinkedIn and `tbo.com`.
The facts below come from web-search summaries of those pages and from GitHub code search. Confirm dates and rules on the [Unstop page](https://unstop.com/competitions/crp-voyagehack-40-tbocom-1774031) before relying on them.

---

## 1. Event facts

| Item | Detail | Source |
|---|---|---|
| Organiser | TBO.com (TBO Tek) | [Unstop listing](https://unstop.com/competitions/crp-voyagehack-40-tbocom-1774031) |
| Team size | 2 to 5; each participant may join only one team; free registration | Unstop listing; [HireToday](https://www.hiretoday.in/competitiondetails/40000244) |
| Registration closes | **12 November 2026** | Unstop listing (via search) |
| Round 1: idea | 26 October to **20 November 2026**. A "2-slider PPT (excluding the cover slide and the 'Thank You' slide)", one submission per team. In 3.0 the deck had to cover potential impact, implementation and technical feasibility, innovation, and adoption risk/feasibility, with a recorded video explaining the idea, all in a .zip | Unstop 4.0 listing and [3.0 listing](https://unstop.com/competitions/crp-voyagehack-30-tbocom-1617332) (via search) |
| Round 2: prototype | A 10-slide presentation with code, supporting documents and/or a video pitch, explaining the solution and its alignment with the objectives. In 3.0, teams created a GitHub project and zipped its link with the explainer video and any extra resources | Same |
| Finale | Shortlisted teams present to a TBO jury; Unstop lists **8 January 2027** as the final date | Same |
| Prizes | ₹6 lakh pool plus pre-placement interviews (3.0 split ₹3L / ₹2L / ₹1L, with internship interviews for finalists) | Same |
| Contact | `voyagehacks@tbo.com` | HireToday (via search) |
| Judging criteria | Potential impact; implementation and technical feasibility; innovation; adoption risk and feasibility; prototype quality; alignment with project objectives. No weights published | HireToday (via search); the same first four appeared in [2.0](https://api.unstop.com/competitions/voyagehack-20-tbocom-1251347) |

**Today is 4 November 2026: 8 days to register and 16 days to the Round 1 deadline.**

## 2. What the criteria imply

| Criterion | What to show |
|---|---|
| Potential impact | Tie every component to TBO money: conversion, price competitiveness, failed bookings avoided, review effort (multi-supplier); risk-adjusted profit and availability (inventory) |
| Implementation and technical feasibility | Running code on real data before Round 1; a named stack; measured latency and cost |
| Innovation | Specific mechanisms, not adjectives: typed relation graph, reliability-adjusted price, contract-aware CVaR optimization |
| Adoption risk | How it fits TBO's current stack and processes: existing mapping vendor, human approvals, shadow mode, per-destination rollout |
| Prototype quality (Round 2) | A working demo on realistic data, tests, a README that runs |

## 3. What TBO's other problem statements reveal about the judges

The three other statements in `ps/` (Virtual Travel Agent, Fraud Prevention, Zendesk/DarwinBox) are longer and spell out TBO's evaluation culture. Assume the same people, or people with the same instincts, judge ours.

- **Measure, do not estimate.** The DarwinBox statement scores "measured cost per completed workflow" in INR from real runs and asks for a monthly projection.
- **Use the cheapest tool that works.** "Rule-based steps ... belong in code. Using an LLM where a rule would do counts against you." Route between small and large models with a justified confidence threshold.
- **Avoid lock-in.** "Changing the model provider must be a configuration change, not a rewrite."
- **Humans on consequential decisions.** Reserved decisions go to a named human; thresholds and policies are configuration; full audit trail; a kill switch; failures go to a human queue with context; retries never duplicate actions.
- **Precision and safety are weighted heavily.** Fraud: valid findings 30%, precision and noise control 20%, safety and scope 20%.
- **Engineering hygiene.** Commercial-use licences for every library and model, listed in the README; disclose which AI coding assistants were used and for what; clean commit history, because finalists are questioned individually.

Both architectures in this folder are built to these rules: cascades with measured cost, human review and approval, configurable thresholds, audit logs, and licence discipline.

## 4. Community and competitor scan

### Discussion threads

Unstop's discussion tab could not be fetched (blocked host). Web search found no Reddit or LinkedIn threads about the 4.0 problem statements.
To read the Unstop discussions in a later session, allow `unstop.com` and `api.unstop.com` under Allowed domains in the cloud environment's network settings ([how to](https://code.claude.com/docs/en/cloud-environments#network-access)), or paste the threads into the chat.

### Public repositories (GitHub search, 4 November 2026)

About 43 repositories mention "voyagehack". Almost all entries from previous editions are AI trip planners and travel-agent copilots.
For 4.0 so far:

- **[Allotment Atlas](https://github.com/shanshantanusingh113-max/allotment-atlas)** (created 28 October 2026) targets **Inventory Optimization**, which it calls "TBO Hackathon Problem 1". It is polished: synthetic data ("No dataset was provided"), quantile forecasts with conformal bands, newsvendor sizing, a budget knapsack, Monte Carlo risk, a 3D globe and plain-English commands. Details and how to beat it are in [`03-inventory-optimization.md`](03-inventory-optimization.md#7-differentiation-from-the-visible-competitor).
  Its walkthrough page rates the other statements:
  - "Agentic DAST: Runner-up. Hard, but strict rules of engagement and a less visual demo."
  - "Multi-supplier: **Skip**. Matching problem; mostly tables."
  - "Virtual Agent: **Crowded**. Most teams will build a chatbot."
- **[TBO-VoyAgent-AI](https://github.com/arshsri0513/TBO-VoyAgent-AI)** (created 31 October 2026): "Autonomous B2B Travel Copilot & Multi-Supplier Bundler", a copilot entry.

**Reading.** The copilot statement is likely the most crowded, inventory already has at least one strong entrant, and no multi-supplier project is visible. If other teams share Allotment Atlas's view that multi-supplier is "mostly tables", it will draw fewer entries, which is an opening for a team that can make it visual.

### Past editions

The format has stayed the same since 2.0: a short idea deck, then a prototype, then an on-site finale in Gurugram. An IIIT Bangalore team placed first runner-up at an earlier edition ([IIIT-B news](https://naviiina.iiitb.ac.in/?p=6983)). No public list of winners was found.

## 5. TBO context for the pitch

- **Business.** A B2B travel distribution platform: buyers are travel agencies, OTAs and tour operators; suppliers include hotels, airlines, transfers and sightseeing operators. TBO's investor materials describe about 159,000 travel buyers in 100+ countries. Q4 FY26 gross transaction value was reported at ₹10,079 crore ([Travel Trade Journal](https://traveltradejournal.com/tbo-tek-reports-%e2%82%b910079-crore-gtv-in-q4-fy26-revenue-surges-83-per-cent-yoy-adjusted-ebitda-at-%e2%82%b9111-crore/)).
- **Hotel mapping today.** TBO renewed its partnership with Vervotech for AI hotel mapping in May 2026 to "reduce duplication" across supplier feeds ([Travel Weekly](https://travelweekly.com.au/tbo-renews-deal-to-clean-up-hotel-data-across-supplier-feeds/)). The pain is real, and part of it is already being paid for.
- **Direct contracting.** HyperGuest describes supporting TBO's direct-contracting strategy ([HyperGuest](https://www.hyperguest.com/industry-blog/hyperguest-tbo-com-partnership)), and TBO hires contracting and loading staff for contracted hotel inventory. Contracted inventory exists; the scale of pre-buying is not public.
- **Sightseeing.** An offered product line; no public count of products was found.

## 6. Questions to send the organisers

Email `voyagehacks@tbo.com` or use the Unstop Q&A:

1. Will any data or sandbox APIs (supplier feeds, search logs, TBO hotel or sightseeing APIs) be provided for Round 2?
2. Is a video required in Round 1 of 4.0, and how long should it be?
3. May a submission focus on one statement and show how it connects to another?
4. Are public datasets with non-commercial licences acceptable for benchmarking if shipped models avoid them?
5. Are there weights for the judging criteria?
6. What are the Round 2 dates, and is the finale in person?
