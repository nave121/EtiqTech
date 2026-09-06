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
  plain-language findings, guided first run. Not started; scheduled after the eval gate.

## Invariants (never break)
All tests green (692 now, 440 original untouched) · no protocol text persisted or logged at any
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
| P2 corpus (IL guidance EN+HE) | done | 72ce96e, 39f396f, b593a54 |
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

## Memos awaiting a decision
- `docs/dev-log/statute-sources.md` — the statute and rules are not in the repo; sources, licences and a recommendation for `resources/law/`.
- `docs/dev-log/layer3-context-options.md` — Layer 3 is ~27.7k tokens; three designs + num_ctx option, ranked.
- `docs/design/spec.md` §8 — open wording/Hebrew questions; commit 8 (landing Hebrew drafts) needs Razy's Hebrew review before merge.
- `docs/eu-directive-spike.md` — EU seed rules (decision #6).
- `docs/benchmarks.md` — grounding stays off; rerun conditions.

## Open findings for the maintainer (do not fix without a decision)
1. ~~Statute not in repo~~ added 2026-09-06 (Hebrew from WikiSource + Weizmann English translation; `LAW_PATH` now the statute). Translation's redistribution terms unverified.
2. Parser output validates against the schema on 0/94 fixtures (Hebrew enums, missing summary key) — normalize parser vs widen schema. `analysis.summary.single_sex_design` is always False on real exports as a consequence.
3. ~~Layer 3 window~~ Layer 3 runs at `OLLAMA_NUM_CTX_LAYER3=65536` (2026-09-06); prompt trimming deferred until OpenAI/Anthropic use.
4. ~~Four linter counting quirks~~ fixed in ruleset 1.1.0 (2026-09-06, Razy's decision).
5. 4 of 59 rules (`header`, `research`, `pi`, `required`) fire on no fixture (unreachable from canonical JSON; need a broken HTML export); `three_Rs_alternatives` is a target theme in only 3 of 28 golden cases.
6. On the 27B test model the blind pass barely separates good from bad protocols (see docs/benchmarks.md).
7. `the_law.txt` is a word-reversed duplicate of the PDF text — candidate for deletion (rule: never delete without OK).

## Running jobs (as of step 25, resumed after the 21:00 limit reset)
- Nothing running. Done: split, coverage, eval, research memos, design 1–9 (8 held), reviews.

## Branches / worktrees
- `design-ux` at `../EtiqTech-design`: design commits land here; merge into main after the linter split finishes (files disjoint except src/rules.py additive fields).
- `rule-coverage`: merged and removed.

## How to resume
```bash
python -m pytest tests/ -q                       # expect all green
git log --oneline fe3cb01..HEAD                  # what landed
tail -40 docs/dev-log/2026-09-05-handoff-session.md
python scripts/eval_grounding.py --report         # if output/eval_grounding.jsonl exists
```
Long LLM jobs write resumable JSONL under `output/` (gitignored); relaunch the same command to continue.

## Next steps (in order)
1. Hebrew for the landing copy: a native review of the drafts on branch `design-ux` (75dd5f0) when convenient.
2. Remaining decisions: grounding default (eval rerun on the production model), EU seed rules, advisory/scope wording.
2. Review follow-ups as they arrive.
3. Design task (non-technical UX) — plan first, then build.
4. Optional if time: P3.1 module split in small batches; i18n toggle.
