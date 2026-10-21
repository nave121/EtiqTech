# Plan: a written chain from ask to merge for every change

Slug: sdlc-base. From: spec.md @ e00ab7c. Date: 2026-10-21. Status: draft.

## Files that change
- `changes/sdlc-base/plan.md`: new (this file).
- `.gitignore`: modified. One line `.claude/` added under the "Claude Code local config" block (spec decision C1). Existing lines stay.
- `Makefile`: modified. `lint` and `check` added to `.PHONY`, two lines added to `help`, two targets added at the end of "Core workflows". No existing recipe changes (R6).
- `CLAUDE.md`: new, at most 60 lines (R2).
- `REVIEW.md`: new (R3). Protected path in a headless run; see Deviations if it was not written.
- `.github/PULL_REQUEST_TEMPLATE.md`: new, three headings only (R8).
- `CONTRIBUTING.md`: modified. One numbered line added after item 5 (R9).
- `.github/workflows/ci.yml`: modified. One step `run: make lint` inserted in the `test` job before "Run tests" (spec decision C2). Protected path; see Deviations.

## Order of work
1. Commit this plan on `change/sdlc-base` with trailer `Change: sdlc-base`.
2. `.gitignore`: add `.claude/`. Proof: `git check-ignore -v .claude/settings.json` names the new line.
3. `Makefile`: add `lint` and `check`. Proof: `make lint`, `make check`, `make help` below.
4. `CLAUDE.md`: write from spec Design. Proof: `wc -l CLAUDE.md` at most 60.
5. `.github/PULL_REQUEST_TEMPLATE.md`: three headings. Proof: `grep -c '^## ' .github/PULL_REQUEST_TEMPLATE.md` prints 3.
6. `CONTRIBUTING.md`: add the one line. Proof: `git diff --stat CONTRIBUTING.md` shows one insertion, zero deletions.
7. `REVIEW.md`: write the checklist. Proof: the five invariants appear verbatim and `docs/dev-log/STATUS.md` is named.
8. `.github/workflows/ci.yml`: insert the lint step. Proof: `git diff .github/workflows/ci.yml` is two added lines inside the `test` job, nothing else.
9. Run every proof, append Deviations, commit all code and this file together with trailer `Change: sdlc-base`.
10. Hand the branch to the verifier agent; include its report.

## Risks
- **Riskiest: the Makefile (step 3).** A typo in `.PHONY` or a tab-vs-space slip breaks every target. Blast radius: local workflows and, after step 8, CI. Mitigation: `make help`, `make lint`, `make check`, `make test` and `make e2e` all run after the edit, and `git diff Makefile` is read to confirm only additions.
- **CI step (step 8).** `make lint` in CI runs `python -m flake8`; setup-python puts `python` on PATH and flake8 is pinned in `requirements.txt`, which the previous step installs. If flake8's selection ever fails on a contributor PR, the PR goes red before tests; that is the behaviour decision C2 asked for.
- **R7's grep.** `git grep -n "sdlc@"` matches `changes/sdlc-base/spec.md:18` and `:70`, because the spec names the grep string itself, and it will match this plan for the same reason. The proof below excludes `changes/` so the check tests the code and docs, which is what R7 is about. Razy's read of the new files (acceptance criterion 3) covers the change records.
- **STATUS.md's invariants line says "824 now"** while the suite is at 879. R2 and R3 say quote it and name the source, so the quote is verbatim and `make check` is named as the live count. The line itself is not edited (intent constraint, intent.md:35).
- **Protected paths.** `REVIEW.md` and `.github/workflows/ci.yml` may be denied in a headless session. If so, their exact content goes under Deviations and Razy writes them; nothing else depends on their presence except CI's lint gate.

## Not chosen
- **Replacing the two `.claude/...` lines in `.gitignore` with `.claude/`.** Same effect, but it deletes lines, and deletion needs an explicit OK; adding one line keeps the decision visible and is reversible by removing it.
- **A `check` recipe that calls `$(MAKE) lint`.** A prerequisite (`check: lint`) is the make idiom already implied by "runs lint then the suite" and stops on lint failure without extra shell.
- **A unit-test subset for `make check`.** Spec decision C3: the full suite runs in under 60 s.
- **Widening flake8 beyond E9,F63,F7,F82.** 30 findings today; its own slug (spec open question).
- **A `changes/` link in the PR template.** Would break dependabot and external PRs (spec Design, R8).

## Proof
Run from the repo root on `change/sdlc-base`.
- `make lint` -> prints the flake8 command line, no findings, exit 0.
- `make check` -> the flake8 line, then pytest ending `879 passed, 5 skipped in <n>s` with n under 60, exit 0.
- `make help` -> the existing list plus `make lint` and `make check` lines.
- `make test` -> `879 passed, 5 skipped` (recipe unchanged, R6).
- `git ls-files .claude` -> empty (R7).
- `git grep -n "sdlc@" -- ':!changes/'` -> empty (R7; see Risks for why `changes/` is excluded).
- `git check-ignore -v .claude/settings.json` -> `.gitignore:<line>:.claude/	.claude/settings.json`.
- `wc -l CLAUDE.md` -> 60 or fewer (R2).
- `grep -c '^## ' .github/PULL_REQUEST_TEMPLATE.md` -> `3` (R8).
- `git diff main --stat -- CONTRIBUTING.md` -> `1 +` (R9).
- `git diff main -- Makefile` -> only `+` lines, no `-` lines (R6).
- `git diff main -- .github/workflows/ci.yml` -> two `+` lines, no `-` lines, no new file under `.github/workflows/` (R10).

## Deviations
