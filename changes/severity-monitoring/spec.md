# Spec: severity:monitoring asks how often animals are checked

Slug: severity-monitoring. From: intent.md @ f04fbc9. Date: 2026-10-21. Status: draft.
Policies applied: REVIEW.md. No endpoint, input path, log line, dependency or LLM call is touched.

## Summary
`severity:monitoring` passes a severity ≥4 experiment only when its monitoring or humane-endpoints text states checks more often than once a week, or the export's own 72h / weekly cells say so. A text with no such frequency is a warning by default and an error under strict_law; an experiment with no monitoring text at all stays an error in both profiles. On the real exports the rule goes from 0 to 21 firing experiments, and the known-good default gate stays at 0 of 35 failing. Ruleset 1.3.0.

## Requirements
1. **R1. Inputs.** The rule reads `monitoring.documentation` + `monitoring.parameters` (via `_monitoring_text`) and `humane_endpoints` (via `_flatten_text`). It passes on `initial_72h_daily is True` or an integer `ongoing_per_week >= 2`. (intent.md:15, decisions D1, D2)
2. **R2. Frequency.** Passes on daily, every N hours, every 1-6 days, every other day, twice or more a day or a week, in English and Hebrew (`יומי` but not `יומיים` as daily, `כל יומיים`, `אחת ליומיים`, `פעמיים בשבוע`, `כל N שעות`). Once a week alone, every week, weekly and every 7 or more days do not pass. (intent.md:16, D1, D2)
3. **R3. Severity.** No frequency and no monitoring text: error in both profiles. No frequency with monitoring text: warning by default, error under strict_law. (intent.md:42, D3)
4. **R4. Message.** Fail: "Experiment N: severity≥4 monitoring does not say how often animals are checked (once a week alone is not enough)." or "Experiment N: severity≥4 has no monitoring plan." Fix: the text Razy approved on the card. (D1)
5. **R5. Version.** `RULESET_VERSION = "1.3.0"`, `"1.3.0"` added to `KNOWN_RULESET_VERSIONS`, the registry title says what the rule now checks, and `docs/rules.md` is regenerated (`gen_rules_doc.py --check` passes). (intent.md:18)
6. **R6. STATUS.** The 1.2.0 "Open" item is replaced by a pointer, and a "Ruleset 1.3.0" section records the change and the gate count. The invariants section is not touched. (intent.md:18, intent.md:33)
7. **R7. Test.** `tests/test_ruleset_1_3_0.py` pins the version and has one rule test that fails on the 1.2.0 code. Its strings are written fresh, not copied from an export. (intent.md:34)
8. **R8. Gate.** `scripts/batch_process.py examples/known-good --fail-on-error` passes 35 of 35. (intent.md:22, intent.md:32)

## Design
**Measured first** (read-only scratch scripts, every real export, `main` @ 15fa218, identical to #49's head 53b7e0d on every file this change touches):
- 78 severity ≥4 experiments (known-good 28, known-bad 13, head-to-head 37). None states `initial_72h_daily` or `ongoing_per_week`; `documentation` is empty on all 78. Before #49 the parser filled in `False` / `1` on all 78.
- 26 distinct monitoring texts. Some approved protocols state the frequency in the humane endpoints instead (IL-003: "weigh the animals every 3 days"; IL-020: "monitored daily"), so the rule reads both fields.
- Law texts in `resources/law/`: the 2025 national guidance asks for a designated monitoring procedure and stated monitoring conditions at severity 4-5. The old fix text ("daily during the first 72h and at least once per week afterwards") appears in no law text in the repo.
- Committee letters (`examples/head-to-head/*/CASE_REPORT.md`, written from the letters): the global report says once-weekly checks are not acceptable for grades 3-5 and expects daily or 12-48 h checks early on; IL-015's committee asked for checks every 1-2 days and approved "אחת ליומיים"; IL-003's asked for the monitoring frequency in the main form.

**Variants put to Razy** (severity ≥4 experiments / files that fire, default profile; `main` fires 0 everywhere):

| variant | known-good (35) | known-bad (23) | head-to-head (35) |
|---|---|---|---|
| V1 any stated frequency | 4 / 3 | 2 / 2 | 3 / 3 |
| V1, once a week alone does not count (chosen) | 12 / 5 | 2 / 2 | 7 / 4 |
| V2 early checks every 48 h or more often | 14 / 7 | 9 / 9 | 16 / 13 |
| V3 daily, the old fix text | 18 / 11 | 11 / 11 | 20 / 17 |

V3 contradicts IL-015 (approved at every 1-2 days). The chosen variant flags these known-good files, all as warnings: IL-004 and IL-013 (×2), which list signs with no schedule, and good.html and IL-019 (identical texts), which state only weekly weight and glucose checks.

**Code.** One compiled regex `_CHECK_FREQUENCY` next to the rule in `src/lint_rules/endpoints_pain.py`, reusing `_monitoring_text` and `_flatten_text` from `helpers.py`. The severity split follows `postop:monitoring` (`src/lint_rules/husbandry.py`): warning by default, error under strict_law, `ctx.warnings` / `ctx.errors` counted to match. The rule's `kind` stays `law_critical`.

## Flagged concerns
- **F1. A version pin test is edited.** `test_version_is_1_2_0` becomes `test_version_1_2_0_stays_known` and the pin moves to the 1.3.0 test, as the 1.1.0 to 1.2.0 bump did (`tests/test_ruleset_1_1_0.py:73`). CLAUDE.md says never edit a test to make a fix pass. Owner: Razy. Decided D4.
- **F2. Two golden manifests gain `severity:monitoring`.** REAL-001 good (`examples/head-to-head/1/case.json`) and REAL-077 good (`examples/head-to-head/IL-013-05-2000, 90013/case.json`) now fire the rule, which the manifests pin exactly. SYNTH-004 bad keeps its expected `severity:monitoring` only because of D2. Owner: Razy. Decided D4.
- **F3. The detector does not know what is being checked.** "Tumour imaging twice a week" passes as monitoring. That is a false pass, not a false alarm; no real export shows it today.
- **F4. The brief counted 79 severity ≥4 experiments; 78 is what both `main` and #49's head parse.** The 79 was not reproduced.
- **F5. Warnings by default on a `law_critical` rule.** Same pattern as `postop:monitoring`; strict_law keeps it an error.

## Decisions (Razy, 2026-10-21)
- D1: detector V1, any stated check frequency, reading the monitoring and humane-endpoints text. Fix text as on the card.
- D2: once a week alone does not count (follow-up card, after SYNTH-004 showed V1 accepting "Weekly check."). Accepted cost: good.html, IL-019 and head-to-head 1/good get warnings.
- D3: warning by default, error under strict_law; no monitoring text at all stays an error in both profiles.
- D4: one PR with staged commits for intent, spec and plan, then code (as #50); F1 and F2 edited and named in the PR Risk section.

## Open questions carried from intent.md
- Intent's open question (what counts, how hard it fires) is answered by D1-D3. None left.

## Acceptance criteria
Razy checks, on the PR for this slug:
1. `make check` prints a flake8 pass and pytest with no failures, two more passed than on `main` (the two 1.3.0 tests).
2. The before/after table in the PR body matches the chosen row above, and no export changes its default or strict_law status.
3. `scripts/batch_process.py examples/known-good --fail-on-error` prints `Passed: 35`, `Failed: 0`.
4. `tests/test_ruleset_1_3_0.py` fails on the 1.2.0 code (shown in the PR body).
5. F1 and F2 are the only test or manifest edits in the diff.
