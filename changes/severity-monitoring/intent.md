# Intent: severity:monitoring asks how often animals are checked

Slug: severity-monitoring. Author: Razy (maintainer). Date: 2026-10-21. Status: draft.
Source: the open item in `docs/dev-log/STATUS.md` (ruleset 1.2.0, card 14: leave the rule lenient until the parser stops inventing monitoring values, then revisit).

## Problem
`severity:monitoring` is a law-critical Layer 1 rule (`src/lint_rules/endpoints_pain.py`). It passes a severity ≥4 experiment when the monitoring text is longer than 50 characters, or contains "daily", "every day", "24" or "72" anywhere. Any real monitoring paragraph clears that bar, so the rule cannot fail on a protocol that states no check schedule. Committee reviewers rely on Layer 1, and a law-critical row that never fires tells them nothing.

Evidence (measured 2026-10-21 on `main` @ 15fa218, every real export in `examples/known-good`, `known-bad` and `head-to-head`):
- 78 severity ≥4 experiments; the rule passes all 78.
- Since #49 the parser leaves `initial_72h_daily` and `ongoing_per_week` out when the export does not state them; no real export states them, and `monitoring.documentation` is empty on all 78. The free-text monitoring field is the only input today.
- IL-003's monitoring text says only "examined at regular intervals"; it passes on its length and again on a buprenorphine dosing interval ("once of 72 hrs").

## Proposed outcome
- A severity ≥4 experiment passes only when it says how often animals are checked.
- What counts as "says how often" is measured on the real exports first and decided by Razy, rule call by rule call.
- The known-good protocols keep passing the default gate.
- Ruleset 1.2.0 becomes 1.3.0, with `docs/rules.md` regenerated and the STATUS open item closed.

Success looks like:
- The PR carries the before/after firing table on every real export and Razy's decisions.
- `make check` is green and `scripts/batch_process.py examples/known-good --fail-on-error` passes 35 of 35.

## Affected users and systems
- Researchers using the web UI: severity ≥4 experiments without a stated schedule get a finding.
- Committee reviewers reading the report.
- prod-remote: merging to `main` deploys within about 5 minutes.
- Feedback rows, which carry `ruleset_version`.

## Constraints
- Every rule call is Razy's.
- Known-good protocols failing the default gate: 0 of 35, before and after.
- The invariants in `docs/dev-log/STATUS.md` stay untouched; Layer 1 only, no LLM change.
- No protocol text in new tests: test strings are written fresh, not copied from the exports.

## Out of scope
- `postop:monitoring`, `vet:consultation` and the other monitoring-adjacent rules.
- Reading attached score sheets or tracking tables.
- Parser changes.

## Open questions
- What counts as a stated frequency, and how hard the rule fires. To be answered on cards with the measurement (spec.md).
