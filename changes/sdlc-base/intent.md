# Intent: a written chain from ask to merge for every change

Slug: sdlc-base. Author: Razy (maintainer). Date: 2026-10-21. Status: draft.
Source: idea.

## Problem
EtiqTech is built solo with Claude. The decisions behind each change live in chat transcripts and in `docs/dev-log/STATUS.md`; there is no per-change record that runs from the ask to the merge. Nothing deterministic guards the work: a test can be edited in the middle of a fix, and a session can report "done" with a red suite. Merging to main deploys prod-remote through Argo CD, and that path has no written gate.

Evidence: the repo has no `changes/` folder, no root `CLAUDE.md`, no `REVIEW.md`, no PR template, and no `check` target in the Makefile (checked 2026-10-21).

## Proposed outcome
- Every change gets `changes/<slug>/intent.md`, then `spec.md`, then `plan.md`.
- A root `CLAUDE.md` under one page, and a `REVIEW.md`.
- A fast local `make check`: flake8 plus the unit test subset. The full suite stays in CI.
- The sdlc plugin's hooks run from a local-scope install. Nothing about the plugin lands in the repo.
- A PR template with three sections: Testing, Risk, How to revert.
- One line in `CONTRIBUTING.md` saying `changes/` is for maintainers.

Success looks like:
- PR `sdlc-base` merged with CI green.
- `make check` runs in under 60 seconds on a laptop.
- The next change (dependabot bumps #46 and #47) goes through the chain end to end.

## Affected users and systems
- Razy (maintainer, does the work).
- Dvir Mintz (co-developer, reviews).
- External contributors: must stay unaffected.
- prod-remote users: the deploy path from main does not change.
- Systems: the GitHub repo, CI, the Makefile, Argo CD (unchanged, named because merge to main deploys through it).

## Constraints
- Public repo: no reference to any private marketplace or to the startup.
- No new CI workflows.
- External PRs keep working without Claude.
- The invariants under "Invariants (never break)" in `docs/dev-log/STATUS.md` stay untouched.
- Existing Makefile targets keep their behaviour.
- CI remains the merge gate; merge to main remains the deploy.

## Out of scope
- Code Review service or an @claude action.
- CODEOWNERS.
- Bands and security-scan workflows.
- Changing `docs/design`.

## Open questions
- Dvir Mintz: his view on the `changes/` folder. Asked, not yet answered.
