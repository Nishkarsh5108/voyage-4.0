# Round 1 video: script and shot list

About 2 min 50 s, around 400 spoken words. Record the screen while clicking through `demo/index.html`; the narration below is timed to the six tabs.
Every number spoken here is in `numbers.json` and on slide 2 of the deck.

## Before recording

- Open `demo/index.html` in Chrome or Edge at 1920 × 1080, zoom 100%, bookmarks bar hidden. The page is fully offline: the map is drawn
  from bundled OpenStreetMap data, so no internet is needed. Use a normal browser window, not an editor's preview pane.
  The stills in `screens/` are the same six tabs, if you would sooner narrate over images.
- Jump straight to a tab with the address bar: `index.html#mess`, `#match`, `#rooms`, `#acts`, `#offer`, `#proof`.
- On tab 2, type `Atlantis` in the search box before you start the take so the map is already centred.
- Do one silent run first. Hover and click slowly; the viewer needs a second to read each card.
- Three screens carry a yellow tag saying which parts are simulated. Leave the tags in frame. Do not crop them out.

## Shot list and narration

| Time | Screen and action | Say |
|---|---|---|
| 0:00 – 0:22 | **Tab 1, "As the feeds deliver it".** Hover one *Hilton Dubai Jumeirah* card so its duplicates light up. At 0:15 click **Canonical view**. | "This is a search for hotels near Dubai Marina, the way four supplier feeds deliver it. Twenty-nine cards, but only nine hotels. The same Hilton shows up four times at four prices. An agent cannot compare this. Here is what the agent should see: nine cards, with every offer kept underneath." |
| 0:22 – 0:58 | **Tab 2, map on Atlantis, The Palm.** Point at the four listings, then run the cursor down the "Why they were merged" table. End on the review queue. | "Canon gets there by matching with evidence. Four independent sources list Atlantis, The Palm. One of them names it in Arabic. For every pair we show the distance, the name similarity, the model's score, and what decided it. Identifiers and phone numbers settle the easy pairs as rules. A small model settles most of the rest. Only the uncertain ones go on to heavier models or a person. Across Dubai, five thousand one hundred eighty-seven listings become four thousand and seventy-four hotels." |
| 0:58 – 1:26 | **Tab 3, Hilton Diagonal Mar.** Point at the third row, `TWN PARTIAL SV HB NRF`: the string, then its blue room chips, then its orange rate chips, then the matched room on the right. | "Hotels are only the first level. A supplier's room string mixes the room with the rate plan. Canon splits them: twin bed and partial sea view are the room; half board and non-refundable are the rate. Then it matches on room attributes only. On the real room lists of almost fifteen hundred hotels, with a simulated second supplier, it maps ninety-six percent of renamed rooms. The best fuzzy matcher manages sixty." |
| 1:26 – 1:54 | **Tab 4, Universal Studios Singapore.** Point at cards A, B, C, D in turn, then rows A → B, A → C and A → D on the right. | "For sightseeing, 'same or different' is the wrong question. These are real listings for Universal Studios Singapore. The express pass is a variant of the ticket: same park, different access. The combo-packages product covers the ticket and more. The VIP tour is a different experience. A plain deduplicator would merge ninety-five percent of variants like these and lose the very difference the customer is paying for." |
| 1:54 – 2:12 | **Tab 5.** Leave the default hotel (Hilton Dubai Jumeirah). Drag the failure-cost slider to zero, then back to the middle: the highlighted row moves from Supplier A to Supplier B. | "Once listings are merged, offers sit side by side, and reliability gets a price. Ignore risk and the cheapest offer wins. Price in the risk, and it loses to a supplier that fails far less often. These prices are simulated. The mechanism is what we are showing." |
| 2:12 – 2:38 | **Tab 6.** Point at the first chart, Bangkok bars, then the "Who settles each candidate pair" chart. | "What is measured today: on cities the model never saw, it finds eighty-eight percent of true matches where a name-and-distance rule finds fifty-eight, at the same precision. In Bangkok, where names change script, ninety-one against twenty-seven. And seventy-three percent of candidate pairs never reach an expensive model. Our truth for matching is independent identifiers, not hand labels, and we say so on the slide." |
| 2:38 – 2:52 | **Deck, thank-you slide** (or stay on tab 6). | "Canon is built to sit beside existing hotel mapping: it takes those IDs as input, keeps thresholds in configuration, and logs every merge so it can be undone. Round two adds ranking on real search logs and a second real supplier for tours. Thank you." |

## What you can and cannot say

Say freely, these are measured:

- 327,856 real listings from four independent sources in twelve cities.
- 88% against 58% of true matches at equal precision on unseen cities; Bangkok 91% against 27%. Always add "at the same precision" and that the truth is independent identifiers.
- Dubai: 5,187 lodging listings become 4,074 hotels.
- 73% of 1.23 million candidate pairs settled by rules and a small model.
- 1.14 million labelled places: cluster score 0.88 against 0.78 for the best rule.

Say only with the qualifier:

- Rooms, 96% against 60%: "real hotel room lists, simulated second supplier".
- Sightseeing, 95% of variants merged by a deduplicator, 96% accuracy for typed relations: "real Klook products, simulated second supplier". The 96% was tuned on the same pairs, so do not call it a benchmark result.
- Two Indian OTA feeds: 484 hotels matched with no retraining. There are no labels for these yet, so do not quote a precision.

Do not say:

- Any accuracy for hotel matching "against human labels". The 400-pair sheet has not been labelled.
- Any ranking or conversion number. Ranking is designed, not measured; the benchmark data is waiting on a Kaggle rules acceptance.
- That the offer panel is a result. It is a simulation of the mechanism.
- "99.99%" or "100%" for rooms. The second supplier there is simulated; the headline is coverage, 96% against 60%.
