# Foursquare Location Matching, pipeline v2: retrieval, collective GBDT, cross-encoder

Kaggle kernels `canon-fsq-v2-stage1` (`kaggle/fsq_v2/stage1.py`) and `canon-fsq-v2-xenc` (`kaggle/fsq_v2_xenc/stage2.py`), T4 GPUs. **Research benchmark only**: the data is under competition terms. Its job is to measure the matching method against a published state of the art on real labels; the shipped matcher is trained on open data only.

## Protocol

- 1,138,812 records of 739,972 places, split by place 50 / 50 into worlds A and B (570,024 records in B, close to the competition's hidden test of about 600k). v1 used a 20% world, which has fewer near-duplicates per record and so flatters every method; the v1 recipe is re-run below at the new density so the comparison is like for like.
- Everything is cross-fitted: the encoder that embeds world A is fine-tuned on world B's duplicates and the reverse, the GBDT trained on A scores B and the reverse. Thresholds are picked on A; **every headline number is world B**, which no model or threshold was tuned on.
- Score: the competition metric, mean per-record IoU between the predicted match set (with itself) and the true set. Predicted sets are each record's accepted candidates plus two-hop neighbours through confident edges (thresholds picked on A); connected components are reported in the JSON.

## Results on world B

| Method | IoU | Pair AUC |
|---|---:|---:|
| Rule: best of three name + distance rules (no training) | 0.7598 | — |
| v1 recipe at the same density (10 geo neighbours + exact name, 23 features) | 0.8420 | 0.9824 |
| v2 stage 1: encoder retrieval + ~60 pair features | 0.8874 | 0.9877 |
| v2 stage 2: + collective features (competing candidates, two-hop) | 0.8970 | 0.9921 |
| v2 + cross-encoder re-ranking (xlm-roberta-base, stack chosen on A) | **0.9165** | 0.9939 |
| Retrieval ceiling, every true candidate accepted, direct links only | 0.9826 | — |
| Retrieval ceiling, same, with transitive closure | 0.9941 | — |
| v1 retrieval ceiling at this density | 0.9407 | — |

Stability check, everything picked on B and scored on A: stage 2 IoU 0.8970, with the cross-encoder 0.9183.

## Against the published state of the art

The 2022 competition had 1,079 teams. Leaderboard scores are inflated by a train/test overlap that participants found during the competition (top teams exploited it), so the comparable figures are the winners' own cross-validation scores on the training data:

| | Published 1st place (CV) | This pipeline (world B) |
|---|---:|---:|
| Retrieval max IoU | 0.979 (about 40 candidates per record) | 0.9826 direct candidates only, 0.9941 with transitive closure (14.9 candidate pairs per record) |
| GBDT stage | 0.875 (LightGBM, ~120 features) | 0.8970 (XGBoost, two stages) |
| Transformer re-ranking, before post-processing | 0.911 (xlm-roberta-large + mdeberta-v3 + CatBoost) | not measured separately |
| Final, with post-processing | 0.9166 (merge rule + xlm-roberta-large on new pairs) | 0.9165 (one xlm-roberta-base cross-encoder, two-hop completion) |

The CV splits are not identical (their folds, our 50/50 place split), so read the comparison as the same order of magnitude, not a ranking. Source: the 1st-place write-up (Kaggle discussion, team "Re:waiwai"), as reposted; the 7th-place write-up reports a 0.9778 retrieval ceiling.

## Retrieval

| | World A | World B |
|---|---:|---:|
| Records | 568,788 | 570,024 |
| True duplicate pairs | 510,739 | 439,764 |
| Candidate pairs | 8,457,545 | 8,479,706 |
| Candidates per record | 14.87 | 14.88 |
| Share of true pairs that are candidates | 60.3% | 70.4% |
| Ceiling IoU | 0.9936 | 0.9941 |
| v1 retrieval: share of true pairs | 44.1% | 51.1% |
| v1 retrieval: ceiling IoU | 0.9416 | 0.9407 |

True pairs found only by one generator (world B): geo 15,062, emb 22,925, glob 32,009, name 3,311. `emb` is the fine-tuned encoder inside the 100-neighbour geo pool, `glob` the country-wide encoder search (within 100 km).

## Cross-encoder band

| | World A | World B |
|---|---:|---:|
| Pairs re-scored | 902,155 | 887,589 |
| Share of candidates | 10.7% | 10.5% |
| GBDT AUC inside the band | 0.9375 | 0.9309 |
| Cross-encoder AUC inside the band | 0.9510 | 0.9482 |

## Feature importance, stage 2 trained on A (gain share, top 15)

| Feature | Share |
|---|---:|
| p1_logit | 33.2% |
| p1 | 19.0% |
| rank_max | 15.9% |
| twohop_sum | 11.1% |
| twohop_cnt | 3.4% |
| cnt5_max | 2.8% |
| emb_cos | 1.7% |
| p_minus_other | 1.5% |
| name_tfidf_char | 0.8% |
| cnt5_min | 0.6% |
| psum_min | 0.6% |
| rank_min | 0.4% |
| country_eq | 0.3% |
| psum_max | 0.3% |
| other_max_min | 0.3% |

## Travel slices (world B, stage 2)

| Slice (both records) | Pairs | Matches | AUC | Average precision |
|---|---:|---:|---:|---:|
| lodging | 48,291 | 7,075 | 0.9904 | 0.9500 |
| attraction | 65,833 | 11,564 | 0.9824 | 0.9195 |

## What changed from v1, and what it bought

- v1 reported IoU 0.878 on a 20% world. At competition density the same recipe scores 0.8420: the old figure was flattered by sparsity, not wrong. The v2 rows are measured at the harder density.
- Retrieval is no longer the binding constraint: the fine-tuned encoder and the country-wide search lift the ceiling from 0.9407 to 0.9941. (Encoder fine-tuning with in-batch negatives is the dense channel of the BER v7 entity-resolution pipeline built for the Amazon ML Challenge.)
- Increments on world B: retrieval and the richer pair features add +0.045 IoU over the v1 recipe; the collective stage (a pair judged together with each record's other candidates) adds +0.010; the cross-encoder adds +0.019.
- Run time: stage 1 77 min on one T4, stage 2 125 min on two T4s.
