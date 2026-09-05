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
