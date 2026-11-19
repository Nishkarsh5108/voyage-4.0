# Sightseeing typed relations: model stage (open LLM) on held-out phrasings

Kaggle kernel `canon-activities-llm` (`kaggle/activities_llm/relate_llm.py`) scores every pair with **Qwen/Qwen2.5-7B-Instruct** (Apache-2.0, fp16 on two T4s), zero-shot with four in-sample examples, reading the probability of each answer letter (no free text, deterministic). This script (`scripts/train/activities_llm_report.py`) compares it with the rules on the held-out set of `activities_heldout.md`: 783 pairs over 87 real Klook products, second supplier simulated with templates written after the rules were frozen.

| Method | Held-out accuracy | Held-out macro-F1 | In-sample accuracy |
|---|---:|---:|---:|
| Rules (`canon/activities.py`) | 74.2% | 0.742 | 96.4% (tuned on it) |
| LLM alone | 87.4% | 0.877 | 88.1% |
| Cascade, policy cross-fitted on held-out halves | **87.2%** | **0.876** | — |

The cascade's policy and threshold are chosen on one half of the held-out products and scored on the other, both ways round:

- chosen on half 0: llm when confident, else rules (confidence threshold 0.5)
- chosen on half 1: llm when confident, else rules (confidence threshold 0.8)

Share right by template family (held out):

| Truth / template | Pairs | Rules | LLM | Cascade |
|---|---:|---:|---:|---:|
| DIFFERENT/other | 174 | 100.0% | 93.7% | 94.3% |
| INCLUDES/combo | 174 | 94.3% | 100.0% | 100.0% |
| SAME_AS/rename | 174 | 58.6% | 74.7% | 74.7% |
| VARIANT_OF/child | 39 | 76.9% | 87.2% | 89.7% |
| VARIANT_OF/guide | 33 | 6.1% | 42.4% | 39.4% |
| VARIANT_OF/meal | 21 | 81.0% | 57.1% | 52.4% |
| VARIANT_OF/private | 37 | 0.0% | 89.2% | 89.2% |
| VARIANT_OF/senior | 38 | 81.6% | 92.1% | 92.1% |
| VARIANT_OF/skip_the_line | 30 | 66.7% | 96.7% | 93.3% |
| VARIANT_OF/time | 30 | 70.0% | 96.7% | 96.7% |
| VARIANT_OF/transfer | 33 | 60.6% | 93.9% | 93.9% |

## Reading the numbers

- The rules are precise where their lexicon has the word (attraction sets from the open-data gazetteer, meals) and blind where it does not ("private tour", "guided tour", new marketing noise). The LLM reads phrasing it has never seen but is looser on some attribute words. The cascade keeps the gazetteer's set logic and lets the model judge what the lexicon cannot.
- The kernel's own cascade was chosen on the in-sample set, where the rules were tuned; it trusted the rules and scored 75.9% held out. That number is in `kaggle/activities_llm/output/metrics_llm.json` and is not used.
- Synthetic second supplier: this measures robustness to unseen phrasings, not accuracy on a live feed. Cost: one forward pass per pair for 1,566 pairs took about 10 minutes including the model download; in the cascade only pairs the rules cannot settle need it.
