# City matcher, stage 3: multilingual cross-encoder on the 12-city benchmark

Kaggle kernel `canon-city-xenc` (`kaggle/city_xenc/city_xenc.py`), xlm-roberta-base fine-tuned on T4 GPUs. Same **weak labels** as `city_matcher.md`. The cross-encoder reads both records as text (name, alternate names, kind and category, street, and the distance); phone, website and Wikidata QID never reach it because they define the labels.

Protocol: three folds of four cities dubai/delhi/london/barcelona; bangkok/mumbai/paris/vienna; singapore/goa/amsterdam/milan. Each fold's cities are scored by a cross-encoder and a stacker trained only on the other eight cities, and stage 2's scores are the nested out-of-city scores of `city_matcher_stage2.md`.

## All labelled pairs, pooled over held-out cities

| Model | AUC | Average precision | Recall at 99% precision | Recall at 99.5% precision | Precision at 95% recall |
|---|---:|---:|---:|---:|---:|
| stage 1 (pair model) | 0.9944 | 0.9761 | 61.4% | 49.7% | 88.8% |
| stage 2 (+ collective) | 0.9957 | 0.9824 | 69.8% | 52.7% | 92.7% |
| cross-encoder alone | 0.9943 | 0.9753 | 51.3% | 25.0% | 90.4% |
| stage 3 (stage 2 + cross-encoder) | 0.9960 | 0.9833 | 68.8% | 51.4% | 93.5% |

## Inside stage 2's uncertain band (0.01 <= p <= 0.99, 35,011 labelled pairs)

| Model | AUC | Average precision |
|---|---:|---:|
| stage 1 (pair model) | 0.9550 | 0.9457 |
| stage 2 (+ collective) | 0.9687 | 0.9613 |
| cross-encoder alone | 0.9629 | 0.9514 |
| stage 3 (stage 2 + cross-encoder) | 0.9723 | 0.9634 |

## Average precision per held-out city

| City | stage 1 (pair model) | stage 2 (+ collective) | cross-encoder alone | stage 3 (stage 2 + cross-encoder) |
|---|---:|---:|---:|---:|
| dubai | 0.9661 | 0.9645 | 0.9655 | 0.9760 |
| bangkok | 0.9792 | 0.9838 | 0.9809 | 0.9865 |
| singapore | 0.9796 | 0.9823 | 0.9808 | 0.9851 |
| delhi | 0.9629 | 0.9665 | 0.9463 | 0.9652 |
| mumbai | 0.9747 | 0.9777 | 0.9765 | 0.9821 |
| goa | 0.9566 | 0.9698 | 0.9558 | 0.9718 |
| london | 0.9802 | 0.9869 | 0.9812 | 0.9873 |
| paris | 0.9809 | 0.9866 | 0.9762 | 0.9872 |
| amsterdam | 0.9838 | 0.9868 | 0.9829 | 0.9877 |
| barcelona | 0.9637 | 0.9725 | 0.9647 | 0.9752 |
| vienna | 0.9685 | 0.9785 | 0.9716 | 0.9828 |
| milan | 0.9712 | 0.9781 | 0.9680 | 0.9781 |

Weak labels carry the noise described in `city_matcher_stage2.md` (duplicate Wikidata items of one place), which caps the top of the ranking.

## Reading the numbers (notes added after the run)

- The cross-encoder alone, reading only text and distance, reaches the same average precision as the stage-1 GBDT built on 30 engineered
  features (0.975 vs 0.976). Stacked on stage 2 it adds a small, consistent gain: average precision 0.9824 -> 0.9833, precision at 95% recall
  92.7% -> 93.5%, and the uncertain band's AUC 0.969 -> 0.972. Dubai, where stage 2 suffered from duplicate Wikidata items, recovers
  (0.965 -> 0.976).
- Recall at 99% precision moves by about a point between stages 2 and 3; as noted in `city_matcher_stage2.md`, that measure hinges on a
  handful of mislabelled top-ranked pairs, so a one-point move is not a difference.
- Cost: about 19 minutes of T4 time per fold to fine-tune on ~160k pairs; at inference only the uncertain band (22% of labelled pairs here)
  needs it. The website runs stage 1; stages 2 and 3 are batch results.
