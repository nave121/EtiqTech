# Benchmarks

Results produced by `scripts/ab_presence_penalty.py` and `scripts/eval_grounding.py`. Every
table names its model, sample and settings. Anything run on a model other than the production
default (`qwen3.5:35b`) is directional; the harnesses are resumable so the maintainer can rerun
them on the production model overnight (`--out` JSONL keeps completed calls).

## presence_penalty A/B — 2026-09-05

**Question (handoff P0.3):** `OLLAMA_PRESENCE_PENALTY=1.5` is aggressive for structured JSON;
does 0 or 0.5 give fewer parse failures or more stable / more discriminating theme scores?

**Setup.** Model `qwen3.6:27b-mlx` (local Ollama 0.32, ~6 tok/s on this machine; the closest
local Qwen to the production default), Layer 2 *blind* theme prompt, temperature 0.2,
`LLM_MAX_TOKENS=2048`, 4 protocols (2 known-good, 2 known-bad) × 3 themes
(`three_Rs_alternatives`, `N_and_justification`, `writing_quality`) × 3 penalties × 2 repeats
= 72 calls. Metrics: parse failure rate, score flips between repeats, mean score on good vs bad.

**Result (72/72 calls).**

| penalty | calls | parse fail | score flips between repeats | good mean | bad mean | gap (good − bad) | sec/call |
|---|---|---|---|---|---|---|---|
| 0.0 | 24 | 8% | 9% | 0.40 | 0.75 | −0.35 | 134 |
| 0.5 | 24 | 0% | 8% | 0.50 | 0.75 | −0.25 | 131 |
| **1.5 (current default)** | 24 | **0%** | **0%** | 0.67 | 0.50 | **+0.17** | 134 |

**Reading.** The hypothesis that 1.5 penalises repeated JSON keys and hurts parsing is not
supported on this model: 1.5 had zero parse failures and the most repeatable scores; 0.0 had the
two failures. Per theme, `N_and_justification` scored 0 on every protocol at every penalty and
`three_Rs_alternatives` scored 1 everywhere — the penalty does not move them; all of the
good/bad gap comes from `writing_quality`, whose scores are noisy (a 3 and a 0 for the same
protocol at pp=0). n is small (4 protocols) and the model is not the production one.

**Decision.** Keep `OLLAMA_PRESENCE_PENALTY=1.5`. Nothing in the data argues for a change and
the cheapest alternative (0.0) was worse on the one metric the brief cared about.

**Finding that matters more than the penalty.** On this model the blind pass barely
discriminates known-good from known-bad protocols for the themes tested (gap ≤ 0.35 on a 0–3
scale, and the sign is wrong at 0.0/0.5). Any grounding gain in the next section is measured
against that weak baseline; the retrieval eval must be read with the same caution.
## Grounded vs ungrounded Layer 2 — 2026-09-05

Model: `qwen3.6:27b-mlx` · blind pass only · temperature 0.2 · cases: 6 golden pairs · themes: target_l2_themes per case · retrieval: k=5 over `resources/corpus/guidance_il.jsonl`

| condition | pairs | pair_acc | bad_hit | good_clean | gap | json_ok | cited | sec/call |
|---|---|---|---|---|---|---|---|---|
| ungrounded | 18 | 6% | 94% | 6% | +0.06 | 100% | — | 150 |
| grounded | 18 | 0% | 94% | 6% | +0.00 | 100% | 100% | 176 |

Per theme:

| theme | condition | pairs | pair_acc | bad_hit | good_clean | gap | cited |
|---|---|---|---|---|---|---|---|
| N_and_justification | ungrounded | 1 | 0% | 100% | 0% | +0.00 | — |
| N_and_justification | grounded | 1 | 0% | 100% | 0% | +0.00 | 100% |
| euthanasia_and_endpoints | ungrounded | 4 | 0% | 100% | 0% | +0.00 | — |
| euthanasia_and_endpoints | grounded | 4 | 0% | 100% | 0% | +0.00 | 100% |
| harm_benefit_analysis | ungrounded | 2 | 0% | 100% | 0% | +0.00 | — |
| harm_benefit_analysis | grounded | 2 | 0% | 100% | 0% | +0.00 | 100% |
| personnel_and_training | ungrounded | 1 | 0% | 100% | 0% | +0.00 | — |
| personnel_and_training | grounded | 1 | 0% | 100% | 0% | +0.00 | 100% |
| scientific_coherence | ungrounded | 3 | 33% | 100% | 0% | +0.33 | — |
| scientific_coherence | grounded | 3 | 0% | 100% | 0% | +0.00 | 100% |
| severity_monitoring_analgesia | ungrounded | 5 | 0% | 80% | 20% | +0.00 | — |
| severity_monitoring_analgesia | grounded | 5 | 0% | 80% | 20% | +0.00 | 100% |
| sex_and_reuse | ungrounded | 1 | 0% | 100% | 0% | +0.00 | — |
| sex_and_reuse | grounded | 1 | 0% | 100% | 0% | +0.00 | 100% |
| three_Rs_alternatives | ungrounded | 1 | 0% | 100% | 0% | +0.00 | — |
| three_Rs_alternatives | grounded | 1 | 0% | 100% | 0% | +0.00 | 100% |

pair_acc = bad variant scored strictly below good on the same theme; bad_hit = bad scored <= 1; good_clean = good scored >= 2; gap = mean(good) - mean(bad); cited = grounded rationales citing a [Gn] source.


**Reading (subset: 6 of 20 testable golden pairs, 72 calls, ~4 h GPU).** Grounding did not beat the
baseline. Every grounded rationale cited at least one retrieved guidance section (cited 100%), so
the plumbing works end to end, but pair accuracy went from 6% to 0%, the good/bad gap from +0.06
to +0.00, and latency rose 17%. The sharper finding is about the baseline itself: this model, on
the blind pass, scores almost every theme on almost every protocol at 0 or 1 (bad_hit 94% but
good_clean only 6%). It flags the known-bad variants because it flags everything. Under that
regime no prompt change can show a gain; the eval is measuring the model's ceiling, not the
grounding.

**Decision (per the handoff's exit criterion: no gain, do not ship).** `ETIQTECH_GROUNDING`
stays **off by default**. The retrieval layer, corpus and citation UI remain in the tree as an
opt-in, because the citations are the visible attribution path NORINA content will need, and
because the eval must be rerun before the decision is final:

1. on the production model (`qwen3.5:35b`) or a stronger local model, all 20 testable pairs
   (`python scripts/eval_grounding.py --model <m>`; ~9 h on this machine at 27B speeds);
2. with the full two-pass flow (blind → reconcile with linter findings), which is what users get
   and which this harness does not exercise (blind pass only, for cost);
3. after the Layer 2 rubric/prompt is checked against a model that separates good from bad at
   all: until `good_clean` is well above 6% ungrounded, grounding cannot register.

Caveats: blind pass only; 6 pairs; `three_Rs_alternatives` (the theme the brief most wanted to
improve) has one pair in the subset and three in the whole golden set.
## Grounded vs ungrounded Layer 2 — 2026-09-06

Model: `gemma4:31b-cloud` · two-pass (blind → reconcile), reconciled verdict scored · temperature 0.2 · cases: 20 golden pairs · themes: target_l2_themes per case · retrieval: k=5 over `resources/corpus/guidance_il.jsonl`

| condition | pairs | pair_acc | bad_hit | good_clean | gap | json_ok | cited | sec/call |
|---|---|---|---|---|---|---|---|---|
| ungrounded | 51 | 18% | 100% | 16% | +0.18 | 100% | — | 5 |
| grounded | 51 | 18% | 100% | 14% | +0.20 | 100% | 96% | 5 |

Per theme:

| theme | condition | pairs | pair_acc | bad_hit | good_clean | gap | cited |
|---|---|---|---|---|---|---|---|
| N_and_justification | ungrounded | 3 | 0% | 100% | 0% | +0.00 | — |
| N_and_justification | grounded | 3 | 0% | 100% | 0% | +0.00 | 100% |
| euthanasia_and_endpoints | ungrounded | 13 | 54% | 100% | 54% | +0.54 | — |
| euthanasia_and_endpoints | grounded | 13 | 54% | 100% | 54% | +0.62 | 100% |
| harm_benefit_analysis | ungrounded | 13 | 8% | 100% | 0% | +0.08 | — |
| harm_benefit_analysis | grounded | 13 | 8% | 100% | 0% | +0.08 | 96% |
| personnel_and_training | ungrounded | 1 | 0% | 100% | 0% | +0.00 | — |
| personnel_and_training | grounded | 1 | 0% | 100% | 0% | +0.00 | 100% |
| scientific_coherence | ungrounded | 5 | 0% | 100% | 0% | -0.20 | — |
| scientific_coherence | grounded | 5 | 0% | 100% | 0% | +0.00 | 80% |
| severity_monitoring_analgesia | ungrounded | 12 | 0% | 100% | 0% | +0.00 | — |
| severity_monitoring_analgesia | grounded | 12 | 0% | 100% | 0% | +0.00 | 96% |
| sex_and_reuse | ungrounded | 2 | 0% | 100% | 0% | +0.00 | — |
| sex_and_reuse | grounded | 2 | 0% | 100% | 0% | +0.00 | 100% |
| three_Rs_alternatives | ungrounded | 2 | 50% | 100% | 50% | +1.00 | — |
| three_Rs_alternatives | grounded | 2 | 50% | 100% | 0% | +0.50 | 100% |

pair_acc = bad variant scored strictly below good on the same theme; bad_hit = bad scored <= 1; good_clean = good scored >= 2; gap = mean(good) - mean(bad); cited = grounded rationales citing a [Gn] source.

**Setup notes.** Rerun requested by the maintainer (2026-09-06) to close the grounding decision. Production default `qwen3.5:35b` is not on the eval machine (32 GB) and `qwen3.5:397b-cloud` is subscription-gated, so the maintainer chose `gemma4:31b-cloud` (Ollama cloud; the golden set is committed to this public repo, nothing non-public left the machine). First run of the full harness: all 20 testable pairs (51 target-theme pairs, 204 calls, 0 errors), production two-pass flow (blind → reconcile), reconciled verdict scored. Blind-pass view of the same run: ungrounded pair_acc 12 % / gap +0.12, grounded 14 % / +0.16; reconcile changed the blind score in 5 of 204 calls.

**Reading.** Grounding changes nothing that matters: pair_acc 18 % → 18 %, gap +0.18 → +0.20, good_clean 16 % → 14 %. The retrieval itself works (96 % of grounded rationales cite a `[Gn]` source, embedding index built), but there is nothing for it to improve on: `bad_hit` is 100 % because the model scores nearly *every* protocol ≤ 1, including the known-good ones (good_clean 16 %). Only `euthanasia_and_endpoints` (54 %) and `three_Rs_alternatives` (2 pairs) separate good from bad at all; five themes have pair_acc 0 %. Rerun condition 3 from the previous section (a model that separates good from bad) is therefore still unmet, and until it is, no grounding experiment can register a gain.

**Decision (pre-registered rule: flip only if grounded beats ungrounded on pair_acc AND gap, json_ok not lower, cited ≥ 50 %).** pair_acc is tied, so `ETIQTECH_GROUNDING` **stays off by default**. Retrieval, corpus and citation UI stay in the tree as opt-in. The next experiment is not about grounding: it is the Layer 2 rubric/prompt (why do known-good protocols score ≤ 1 on seven of eight target themes?) on the production model, and only after `good_clean` is in a usable range does the grounding question reopen. Directional caveat: gemma4 is not the production model family. `sec/call` is ~5 s here vs ~150 s in the 27B table: cloud inference, not a change in the harness.
