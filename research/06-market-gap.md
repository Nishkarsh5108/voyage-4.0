# Market gap for Multi-Supplier Optimization, and how Canon should change to fill it

Written 20 Nov 2026 for the VoyageHack 4.0 statement in `ps/Multi Supplier Optimization.pdf`. Sources are linked inline.
Where a source is a vendor's own marketing, or a claim could not be checked, the text says so.

## The short answer

**Hotel mapping is not a gap.** It is a mature product category that TBO already buys. **Room mapping and
post-booking rebooking are not gaps either:** several vendors sell them. The gap is in **sightseeing**: nobody we could find
sells cross-supplier matching of tours and activities. That is matching that understands options and inclusions, and that
can tell when two suppliers are reselling the same operator's product. That is the half of the statement Canon is already
strongest on, and the half where nobody else is. Canon should lead with it.

## 1. What is already well established (do not compete with it)

| Capability | Who sells it today | What that means for Canon |
|---|---|---|
| **Hotel mapping** (same property across suppliers) | **Vervotech**: TBO renewed its contract in May 2026 to match hotel entities and cut duplicate listings ([Travel Weekly](https://travelweekly.com.au/tbo-renews-deal-to-clean-up-hotel-data-across-supplier-feeds/), [Travolution](https://www.travolution.com/news/tbo-strengthens-hotel-mapping-with-vervotech-and-ai/)). **GIATA**: about 1.2 million properties and 124 million booking codes; its MultiCodes act as an industry ID ([AltexSoft overview](https://www.altexsoft.com/blog/cloud/hotel-mapping-tools-how-giata-gimmonix-databindr-and-other-solutions-work/)). Also Gimmonix, RateHawk ([GIATA × RateHawk](https://www.emergingtravel.com/press/release/detail/GIATA-and-RateHawk-Aim-to-Expand-the-Hotel-Mapping-Solution%E2%80%99s-Database)) | TBO has paid for this already. Canon's hotel matcher stays as an **audit and fill-in layer** that takes Vervotech IDs as input; it is not the pitch |
| **Room mapping** | Vervotech RoomMapping ([Vervotech](https://vervotech.com/es/vervotech-room-mapping/)), GIATA's dictionary-based room mapping, Gimmonix, Nuitée Cupid | Canon's room/rate split is a good technique, not a market gap. Keep it, say what it adds (the rate plan is separated before matching), don't lead with it |
| **Rebooking on price drops** | Vervotech's "profit maximizer" scans confirmed bookings for cheaper rates ([Vervotech](https://vervotech.com/blog/why-hotel-price-drops-often-go-unnoticed-how-to-capture-them/), [TravClan case study](https://vervotech.com/case-study/how-travclan-improved-booking-revenues-with-vervotechs-profit-maximizer/)) | Not ours to build |
| **Connectivity for tours and activities** | The OCTO open standard, with over 130 resellers and technology providers using it ([Travel Daily News](https://www.traveldailynews.com/special-interest-travel/octo-standard-surpasses-130-users-now-live-and-transforming-travel-experiences-industry/)); channel managers such as Ventrata, Rezdy and TourCMS map an operator's product to each reseller ([Ventrata](https://support.ventrata.com/en/articles/9526754-getyourguide-reseller-connection), [TourCMS](https://support.tourcms.com/hc/en-us/articles/7814910517521)) | This solves "connect supplier to reseller", one channel at a time. It does **not** tell a reseller that two of its suppliers sell the same thing |
| **Listing-page ranking** | Standard learning-to-rank; every large OTA does it | Generic. Keep it in the design, but it is not a differentiator, and ours is not measured |

## 2. The gaps, with the evidence for each

### Gap 1 (strong). Nobody sells cross-supplier matching for tours and activities

- **Mapping vendors stop at hotels.** Searching Vervotech's and GIATA's material turned up hotel and room products only; no
  activities or experiences mapping product. This is absence of evidence, so it should be stated carefully ("we found no
  vendor"), and checked with TBO.
- **Activity "mapping" in the industry means something else.** In the industry, mapping means linking an operator's own
  product codes to each reseller's codes. Viator maps supplier tour and option codes to its own products
  ([Viator supplier API](https://docs.viator.com/supplier-api/technical/sapi-manual-latest/)). GetYourGuide reports that about
  **35% of mapping attempts end in errors**, and built new endpoints to reduce that
  ([GetYourGuide connectivity blog](https://getconnected.getyourguide.com/blog/improved-product-mapping-with-our-new-api-endpoints)).
  That is supplier-side plumbing, not a reseller seeing duplicates across its suppliers.
- **The only cross-supplier grouping we found is internal.** Amadeus Discover says it uses machine learning to group
  activities "to enable deduplication" across its 300k-experience catalogue
  ([Amadeus Discover](https://amadeus-discover.com/content-catalog/)). It is part of Amadeus's own product, not a service sold
  to other aggregators, and it is described as grouping, which is a same/not-same decision.
- **Same/not-same is exactly what loses money in this category.** Products differ by options and inclusions (start time,
  language, with or without lunch, pickup), which Viator itself calls variants
  ([Viator partner guide](https://partnerresources.viator.com/?p=2251)). The statement asks to match "without losing
  meaningful differences". On our own benchmark, a plain deduplicator merges 95% of variants and 100% of combos into the base
  product (real Klook products, simulated second supplier; `reports/models/activities.md`).
- **The scale of the duplication is visible to consumers.** Arival notes that a Colosseum search returns over a thousand
  listings across OTAs ([Arival](https://arival.travel/?p=196157); an opinion piece by a firm that sells reports). OTAs took 37%
  of experience bookings in 2025, up from 28% in 2023 ([PhocusWire on Arival data](https://www.phocuswire.com/otas-increased-booking-share-experiences-arival-report)),
  so more of the same inventory reaches buyers through more resellers.
- **TBO is in this market as a buyer of several supply sources.** TBO sells sightseeing to agents through its B2B portal and
  packages ([TBO supplier docket](https://www.tbo.com:443/img/TBOSupplierdocket03.pdf)). B2B experience wholesalers sell to
  resellers like TBO: Hotelbeds alone offers over 23,000 experiences ([HBX Group](https://www.hbxgroup.com/news-room/blog/b2b-travel-solutions-mobility-experiences)),
  and TUI Musement gets almost half its revenue from B2B partners ([Skift](https://skift.com/2024/07/02/lastminute-com-to-sell-tui-musements-travel-experiences)).
  **Not verified:** which activity suppliers TBO actually integrates. That is the first question to ask TBO.

### Gap 2 (moderate). The same operator's tour reaches the buyer through several suppliers, at stacked margins

- The same operator's tour can be listed by several resellers on one marketplace "at two or three different price points"
  ([Finding the Universe review](https://www.findingtheuniverse.com/the-best-tour-booking-sites-getyourguide-viator-klook-tiqets-and-toursbylocals-compared/), a consumer blog).
- Distribution runs operator → wholesaler → retailer, and commission is split along the chain: an agent keeps part and passes
  part to its intermediary ([TrekkSoft](https://www.trekksoft.com/en/blog/how-much-commission-should-you-pay-for-distribution);
  partners take up to about 30%, [Tourism NT](https://tourismnt.nt.gov.au/industry-toolkit/tourism-distribution/working-trade-distribution/pricing-rates-and-commissions)).
- One comparison claims some marketplaces sell aggregated inventory that routes through the same operator with an extra margin
  layer ([ShopBack](https://www.shopback.sg/blog/travel/klook-vs-viator-vs-kkday-sg-2026-tours-activities); **unverified**,
  affiliate content).
- In hotels the same multi-hop resale is documented: an Expedia study reports that 49% of wholesale sales went to unintended
  partners ([Expedia Group](https://partner.expediagroup.com/en-us/resources/blog/hotel-b2b-distribution-study); a vendor study).

So for an aggregator with several activity suppliers, a "duplicate" is often **one operator's product bought through two
paths**. Recognising that collapses the listing to one card, and it also picks the cheaper or more reliable path, which is
the statement's "price competitiveness" objective in its most direct form. We found no product that does this for
activities. The evidence is weaker than for gap 1: the pattern is well described, but its size inside TBO's own supply is
unknown until we see TBO data.

### Gap 3 (moderate, partly built in-house everywhere). Offers are not comparable

- **There is no shared standard for cancellation terms.** Booking.com uses numeric policy codes with penalty rules
  ([Booking.com Policies API](https://developers.booking.com/connectivity/docs/policies-api/understanding-cancellation-policy)).
  Other schemas reduce terms to three classes, and connectivity hubs write per-supplier translation helpers
  ([Travelgate](https://docs.travelgate.com/docs/apis/for-sellers/connectors-pull-developers-api/tools-and-helpers/policies-helpers/)).
  Every aggregator normalises its own way.
- **There is no published standard for supplier reliability.** What exists is patents describing time-decayed booking-failure
  rates used to demote or blacklist inventory ([US 9298837](https://image-ppubs.uspto.gov/dirsearch-public/print/downloadPdf/9298837)),
  and vendor blogs ([Vervotech](https://vervotech.com/pt/blog/5-data-metrics-every-b2b-hotel-booking-platform-should-track-in-2026/)).
- **This is a real need named in the statement** ("price, availability, cancellation policies, payment terms, and supplier
  reliability"). But large aggregators usually build it themselves, so it is a capability to offer inside Canon, not a market
  to claim. For activities it is less mature still: cancellation terms are free text (we parse them in
  `canon/activities.py: parse_policy`).

## 3. How Canon should change

**From:** "an entity-resolution system for hotels, rooms and tours".
**To:** **"the matching layer for experiences that hotel mapping vendors are for hotels, and that sits beside the hotel vendor TBO already uses."**

### What changes in the product

1. **Lead with sightseeing.** The product-option graph with typed relations (same, variant, includes, different) becomes the
   centre, at **option level**, not only product titles: start time, language, pickup, meal, access type, age band. The
   relation logic exists in `canon/activities.py`; it needs option-level inputs from real supplier feeds.
2. **Add operator identity: "same product, different path".** Resolve the operator behind each listing from its name, meeting
   point coordinates, schedule, duration and option structure. Attach every supplier's listing of that operator's product to
   one node. The listing page then shows one card per real product, with each supplier's offer underneath. This reuses what
   Canon already does well: our attraction matcher resolves 228,165 attraction listings across four sources in 12 cities
   (`numbers.json → data.attraction_listings`), which gives the anchor points that products and operators hang from.
3. **One offer model for both verticals.** Cancellation becomes a penalty schedule (a refund fraction as a function of time
   before the start), payment terms are normalised, and each supplier path carries a time-decayed failure rate. The best offer
   is chosen on a reliability-adjusted price, and the "cheapest path" for the same product becomes visible to agents. Today
   this is a simulated panel; it becomes a component with a measurable baseline (cheapest price wins).
4. **Hotels: consume, audit, fill in.** Take Vervotech and GIATA IDs as input, flag disagreements with Canon's own model for
   review, and fill in properties a vendor has not mapped. The leave-one-city-out results stay as evidence that the matcher is
   good enough to audit with. They are no longer the headline.
5. **Ranking stays designed, not claimed,** until it is measured.

### What changes in the evidence

- **Activities need a real second supplier.** The biggest weakness today is that the activities results use a simulated second
  supplier. Next: pull real listings for the same Singapore and Dubai attractions from two sources (Viator Basic Access is free
  with sign-up; Hotelbeds Activities evaluation keys; the Klook data we already have), and hand-label a few hundred product
  and option pairs.
- **New metrics that match the gap:**
  - duplicate cards per attraction page, before and after;
  - share of variants kept apart (the inverse of the deduplicator's 95% merge);
  - same-product pairs found across different suppliers;
  - price gap between the cheapest path and the path a naive merge would show.
- Keep the honesty rules: each number says what it was measured against.

### What stays exactly as it is

The cascade (cheapest tool first), the typed relations, the room/rate split, the evidence tagging, and the "works beside the
existing vendor" adoption story. The repositioning changes the emphasis and adds operator identity; it does not throw away
built work.

## 4. Open questions to put to TBO (do not assume the answers)

1. Which sightseeing suppliers does TBO integrate today, and how many of them resell each other's inventory?
2. Does TBO already group duplicate activities in-house? If yes, does it keep variants apart?
3. Does TBO keep booking-failure and price-change data per supplier for sightseeing? Without that, reliability stays simulated.
4. Would TBO use a matching layer for experiences the way it uses Vervotech for hotels, or does it want this in-house?

## 5. What this research could not establish

- Whether any vendor sells activity matching that the searches missed: absence of evidence is not proof, so the pitch should
  say "we found no vendor that…", not "nobody does…".
- How big the same-operator, multi-path effect is in TBO's own supply: there are no public numbers.
- Reseller price-gap figures (5–20% between platforms): these come from affiliate content and conflict with each other. Don't quote them.
