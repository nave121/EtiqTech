# Handoff execution — live status (resume anchor)

> Read this first after a context reset. It is updated with every commit. The narrative with
> evidence per step is `2026-09-05-handoff-session.md` (same folder); the plan is
> `~/Downloads/etiqtech_dev_handoff.md`.

## Standing instructions from Razy (this sprint)
- Execute the handoff phase by phase; **git commit each change**; after each commit run a **Sonnet
  subagent code + security review** and apply/record its findings.
- Working alone: **study decisions online first**, then decide; record the reasoning in the log.
- Keep a full step log (the session log) and this status file **updated with each commit**, so a
  compacted session can continue without loss.
- Added 2026-09-05: **ULTRACODE** — substantive tasks run as Workflow orchestrations. **Hard cap: at most 15 agents per workflow, Sonnet for most of them** (Razy stopped a 110-agent audit: "wayyyy too much"); Opus for skeptic/verify roles, Fable only for the biggest synthesis/implementation steps.
- Added 2026-09-05: **Design task** — near the end of the sprint, make the product super easy and
  self-explanatory for non-technical people (researchers, committee staff): onboarding copy,
  plain-language findings, guided first run. Done (spec commits 1–9 on main).

## Invariants (never break)
All tests green (696 now, 440 original untouched) · no protocol text persisted or logged at any
level · local-first LLM by default · LLM never gates/filters/rewrites Layer 1 · advisory framing
permanent · auth stays at the reverse proxy.

## Phase checklist
| Item | State | Commits |
|---|---|---|
| P0.1 sessions under gunicorn | done | ec0519f, 8924589 |
| P0.2 law corpus in image + health flag | done | 4dc607f |
| P0.3 hygiene (logging, lock, context guard, md5, pyproject, lxml) | done | 7928aad |
| P0.3 presence_penalty A/B | done — keep 1.5 | 1c4b295 (docs/benchmarks.md) |
| P1.1 local-first gate + k8s | done | ec9fd6e, f868a1a |
| P1.2 PRIVACY.md + canary | done | e6bffde, fb89ffe |
| P1.3 supply chain + CSP nonce | done | 91d1083 |
| P1.4 advisory banner | done (wording = maintainer) | 737e831 |
| P2 corpus (IL guidance EN+HE + the 1994 statute and 2001 rules, HE+EN) | done: 178 records, section boundaries verified by read-through | 72ce96e … 7e87e5f … 233da23 |
| P2 retrieval layer + cited grounding | done, **off by default** | 3b67301, 64ca1ed |
| P2 eval gate (grounded vs ungrounded) | done (subset): **no gain, grounding stays off by default**; rerun conditions in docs/benchmarks.md | 342092b, bf331e4 |
| P2 Norecopa ingest | **blocked on maintainer** (access path) | — |
| P3.1 rule registry + module split | **done**: 59 ids, `src/lint_rules/` package, snapshot byte-identical through 8 batches | 592aa81, 9e04573, bd2e383, 9f90148..35856f3 |
| P3.2 pack mechanism + EU spike | done (EU rules await review) | 6a173f9 |
| P3.3 schema contract + adapters | done | 20ef270, 77158b0, f71c98a |
| P3.4 providers (OpenAI-compat, Anthropic) | done | c5287c3, 6e00a43 |
| P3.5 feedback loop (metadata only) | done | a62cd84, 398ef47 |
| P4 prepare-mapping, demo mode, README diagram, acknowledgements | done | 8449d66, 9ce976b |
| Rule coverage fixtures (23 of 27 never-firing rules) | done, merged | 9a6648b |
| P4 demo GIF, social preview, i18n toggle, public deploy | not done | — |
| Design (non-tech-friendly UX) | all 9 commits on main; commit 8 landed English-only (Hebrew drafts dropped, kept on branch `design-ux`) | 3af9372 … 74eabdc |

## Decisions taken 2026-09-06 (Razy, second round)
| # | Decision | Answer | Owner / state |
|---|---|---|---|
| 1 | delete `resources/law/the_law.txt` | yes | done (this commit) |
| 2 | Weizmann English translation redistribution terms | Razy asks Weizmann | **Razy**; README keeps "unverified" until then |
| 3 | grounding default | rerun the eval on `qwen3.5:397b-cloud`, all 20 pairs, two-pass; flip only if the pre-set rule in docs/benchmarks.md is met | in progress |
| 4 | EU seed rules (`docs/eu-directive-spike.md`) | Israel-only for launch; EU is the first post-launch feature | parked |
| 5 | advisory notice / scope sentence / acknowledgements wording | Razy edits | **Razy** |
| 6 | Hebrew landing copy | not needed now | branch `design-ux` (75dd5f0) stays parked, no work |
| 7 | parser output vs canonical schema (0/94) | normalize the parser, schema stays strict; fate normalization may silence `postop:monitoring` / `surgery:multiple-survival` on euthanasia-fated experiments (accepted) | in progress |

Decided memos (kept for the record): `statute-sources.md` (statute imported), `layer3-context-options.md` (num_ctx 65536), `design/spec.md` §8 (English-only).

## Open findings for the maintainer (do not fix without a decision)
1. ~~Statute not in repo~~ added 2026-09-06 (Hebrew from WikiSource + Weizmann English translation; `LAW_PATH` now the statute). Translation's redistribution terms unverified.
2. Parser output validates against the schema on 0/94 fixtures — **decision 2026-09-06: normalize the parser** (in progress). `analysis.summary.single_sex_design` is always False on real exports until then.
3. ~~Layer 3 window~~ Layer 3 runs at `OLLAMA_NUM_CTX_LAYER3=65536` (2026-09-06); prompt trimming deferred until OpenAI/Anthropic use.
4. ~~Four linter counting quirks~~ fixed in ruleset 1.1.0 (2026-09-06, Razy's decision).
5. 4 of 59 rules (`header`, `research`, `pi`, `required`) fire on no fixture (unreachable from canonical JSON; need a broken HTML export); `three_Rs_alternatives` is a target theme in only 3 of 28 golden cases.
6. On the 27B test model the blind pass barely separates good from bad protocols (see docs/benchmarks.md).
7. ~~`the_law.txt`~~ deleted 2026-09-06 on Razy's OK.

## Running jobs (as of step 25, resumed after the 21:00 limit reset)
- Nothing running. Done: split, coverage, eval, research memos, design 1–9 (8 English-only), the four maintainer decisions (statute import, Layer 3 window, ruleset 1.1.0, landing English-only), reviews.

## Branches / worktrees
- `design-ux` (branch only, worktree removed): holds the Hebrew landing drafts (75dd5f0) for a native review; everything else from it is on main.
- `rule-coverage`: merged and removed.

## How to resume
```bash
python -m pytest tests/ -q                       # expect all green
git log --oneline fe3cb01..HEAD                  # what landed
tail -40 docs/dev-log/2026-09-05-handoff-session.md
python scripts/eval_grounding.py --report         # if output/eval_grounding.jsonl exists
```
Long LLM jobs write resumable JSONL under `output/` (gitignored); relaunch the same command to continue.

## Next steps (in order) — plan: ~/.claude/plans/golden-sauteeing-teapot.md
1. Grounding eval: add `--two-pass` to `scripts/eval_grounding.py`, run on `qwen3.5:397b-cloud` (all 20 pairs), report into docs/benchmarks.md, apply the pre-set decision rule.
2. Parser normalization (decision 7): Hebrew vocab → schema enums in `src/html_to_json.py`, two enum additions in `src/schema.py`, snapshot diff reviewed, docs regenerated, new `tests/test_parser_schema.py` (94/94 valid).
3. Close decisions 3 and 7 in this file and the dev log.
4. Razy's items: translation licence (2), wording (5). Optional later: i18n toggle, P4 leftovers.
