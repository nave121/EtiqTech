# Intent: bump hypothesis to 6.170.1

Slug: deps-hypothesis. Author: Razy (maintainer). Date: 2026-10-21. Status: accepted (by Razy in chat, 2026-10-21; see spec.md C2).
Source: ticket PR #47 (dependabot, "build(deps): bump hypothesis from 6.168.3 to 6.170.1").

## Problem
The pinned test dependency `hypothesis` is two minor versions behind. `requirements.txt`
line 12 pins `hypothesis==6.168.3` (verified in the checkout); dependabot's PR #47
proposes 6.170.1 in one commit, f3cabea, touching only that line (per the ticket; the
PR was not re-read from this session).

Repo policy (security-baseline rule 6, per the ticket) says a version bump is its own
change with its own slug, so the bump goes through the intent -> spec -> plan chain
instead of being merged from the bot's PR directly.

## Proposed outcome
`requirements.txt` pins `hypothesis==6.170.1`. The full suite is green on that version,
locally and in CI. PR #47 is closed as superseded by this change's own PR.
Success is measured as: this change's PR merged with CI green, and PR #47 closed.

## Affected users and systems
- The test suite: hypothesis is test-only. It is imported in
  `tests/test_linter_properties.py` and nowhere else (grep of tests, src, server,
  scripts in the checkout).
- CI (`.github/workflows/ci.yml`), which installs from `requirements.txt`.
- Developers' venvs.

## Constraints
- Test-only dependency; no runtime change.
- `pyproject.toml`'s floor `hypothesis>=6.120` (line 38) stays.
- No other pin in `requirements.txt` moves.

## Out of scope
- The pydantic bump, PR #46: its own slug, `deps-pydantic`.
- Any edit to a test.

## Open questions
None.
