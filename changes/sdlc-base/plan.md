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

**D1. `REVIEW.md` and `.github/workflows/ci.yml` were not written (2026-10-21).** Both are protected paths and the headless session was denied on write. Razy writes them with the exact content below; the diff for each is then re-checked against the Proof section.

`REVIEW.md` (new file, full content):

````markdown
# REVIEW.md: what a reviewer checks on every PR

For humans and review agents alike. Read it in full before approving; a review agent
reads it in a fresh context, so the invariants are quoted here, not linked.

## 1. The invariants still hold
Source: `docs/dev-log/STATUS.md`, section "Invariants (never break)". Quoted verbatim:

> All tests green (824 now, 440 original untouched) · no protocol text persisted or logged at any
> level · local-first LLM by default · LLM never gates/filters/rewrites Layer 1 · advisory framing
> permanent · auth stays at the reverse proxy.

As five checks on the diff:
1. **All tests green.** No test was deleted, skipped or weakened to make the change pass. The count only goes up.
2. **No protocol text persisted or logged at any level.** No new write of protocol content to disk, database, log line, error message or external service.
3. **Local-first LLM by default.** No new default that sends protocol text to a remote provider; remote stays opt-in behind `ETIQTECH_ALLOW_REMOTE_LLM`.
4. **LLM never gates, filters or rewrites Layer 1.** Linter findings reach the report unchanged by any model output.
5. **Advisory framing permanent; auth stays at the reverse proxy.** No wording that presents the tool as an approval, and no authentication added inside the app.

## 2. CI is green
The `test`, `security`, `audit` and `docker` jobs pass on the PR head. A red job is a stop, not a note.

## 3. The PR template is filled
All three sections carry real content: **Testing** (what ran and what it printed), **Risk** (what could break and who notices), **How to revert** (the concrete undo).

## 4. Nothing sensitive in the diff
No protocol text, no fixture derived from a real protocol, no secret, token, key or credential, in code, tests, docs or examples.

## Verdict
PASS only when all four sections hold. Any failed item is named with the file and line.
````

`.github/workflows/ci.yml` (insert in the `test` job, between the "Install dependencies" step and the "Run tests" step, same indentation as its neighbours):

````yaml
      - name: Lint
        run: make lint
````

**D2. `make lint`, `make check` and `make test` could not run green in this session (2026-10-21).** In the Bash tool's shell, `python` resolves to `/data/data/com.termux/files/usr/bin/python`, which has neither flake8 nor pytest; the Ubuntu `/usr/bin/python3` is second on PATH. The untouched `make test` on this branch fails with the identical "No module named pytest", so the cause is the shell's PATH, not the new targets. The allow list for this run covers only the plain `make <target>` forms, so `make check PYTHON=python3` and an `env PATH=...` prefix were both denied. The spec's own measurement (0 flake8 findings with this selection, 879 passed / 5 skipped, 2026-10-21) was taken on the same tree with the Ubuntu interpreter; no `.py` file changed since. What is proven here: `make help` lists both targets, the Makefile diff is additive only, and the recipes invoke the exact command lines R4 and R5 specify. The green run is Razy's: `make check` from a shell where `python` is the project interpreter (or `make check PYTHON=python3`), and the CI `test` job once D1 lands. If `python` on Razy's shell also resolves to the Termux interpreter, the fix is outside this change (a `python-is-python3` package or PATH order), because changing the Makefile's `PYTHON ?= python` default would alter the behaviour of every existing target (R6).
