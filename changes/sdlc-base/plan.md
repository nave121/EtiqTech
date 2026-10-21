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
- `git diff main -- Makefile` -> one `-`/`+` pair for the `.PHONY` line (it gains `lint check`); every other changed line is a `+`; no recipe line removed (R6).
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

**D2. Plain `make lint`, `make check` and `make test` fail in this shell; the green run needs the repo's venv (2026-10-21).** In the Bash tool's shell, `python` resolves to `/data/data/com.termux/files/usr/bin/python` and `python3` to `/usr/bin/python3`; neither has flake8 or pytest. The untouched `make test` fails with the identical "No module named pytest", so the cause is the interpreter, not the new targets. The project's dependencies live in `.venv/` (gitignored), and `make check PYTHON=.venv/bin/python` is green: flake8 prints no findings (one `RuntimeWarning: invalid signal number 32` from the interpreter, not a finding), then `879 passed, 5 skipped in 27.39s` (the verifier agent's run, wall 29.1 s; the implementing session was denied the same command by the permission system, so the verifier's output is the record). An earlier version of this paragraph blamed PATH order and prescribed `PYTHON=python3`; the verifier showed that interpreter lacks flake8 too, so the correction is recorded here rather than silently rewritten. Nothing in the Makefile changes for this: `PYTHON ?= python` is the existing contract (an activated venv or an explicit `PYTHON=` on the command line), and altering the default would change every existing target (R6).

**D3. Plan corrections after the verifier's report (2026-10-21).** (a) The Makefile proof line originally said "no `-` lines"; the `.PHONY` line is rewritten, as the file list above already said, so the proof now names that one pair. (b) The commits `23c545a`, `4e781bb` and `9828b2c` carry `Change: sdlc-base` in a paragraph of its own, separated from `Co-Authored-By` by a blank line, so git's trailer parser (`git log --format=%(trailers)`) does not return it for them; `dcd4957` and `e00ab7c` parse. History is not rewritten (that needs Razy's OK); from the next commit on, `Change:` and `Co-Authored-By:` sit in one final paragraph. Whether the plugin's hooks use git's parser or a plain grep is unverified. (c) `CLAUDE.md` line 37 names `REVIEW.md`, which exists on this branch only once Razy writes it (D1); both land in the same PR.

**D4. One flaky timing test on the phone (2026-10-21).** On the first `make check PYTHON=.venv/bin/python` after D1 was applied, `tests/test_l2_parallel.py::test_parallel_calls_overlap` failed its wall-clock bound (1.52 s against `< 1.5`). The same command was green three times earlier today and again on the immediate rerun (`879 passed, 5 skipped in 50.16s`). This change touches no code under test; the test is not edited. Candidate intent: `l2-parallel-timing-margin` (widen the bound or measure overlap by ordering, not wall time). D1 was applied by Razy's delegate session from the content above; `git diff main -- .github/workflows/ci.yml` shows the single two-line step.
