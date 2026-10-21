# Spec: a written chain from ask to merge for every change

Slug: sdlc-base. From: intent.md @ dcd4957. Date: 2026-10-21. Status: draft.
Policies applied: sdlc-artifacts, security-baseline, as of 2026-10-21. No `policy-*` skills exist in this repo (checked 2026-10-21).

## Summary
The repo gains a per-change record under `changes/<slug>/` (intent, spec, plan), a one-page root `CLAUDE.md`, a `REVIEW.md` reviewers and review agents read, a PR template, and two Makefile targets: `make lint` (flake8, zero findings on today's code) and `make check` (lint plus the full test suite, under 60 seconds). CI, the Makefile's existing targets, the deploy path from main, and the experience of an external contributor do not change. The plugin that drives the chain stays in a gitignored local-scope install.

## Requirements
Each is traceable to intent.md by line number (intent.md @ dcd4957).

1. **R1. Change records.** `changes/sdlc-base/` holds `intent.md`, `spec.md` and `plan.md`, each with the headings of the sdlc-artifacts templates, in order, none missing. (intent.md:12)
2. **R2. Root `CLAUDE.md`, one page.** Exists at the repo root, at most 60 lines, and contains: what the project is, how to run it, the invariants line from `docs/dev-log/STATUS.md` (quoted, source named), the artifact chain, and the rule that a session is not "done" until `make check` is green. (intent.md:13)
3. **R3. `REVIEW.md`.** Exists at the repo root and lists what a reviewer checks on every PR: the five invariants from `docs/dev-log/STATUS.md` (quoted, source named), CI green, the PR template's three sections filled, and no protocol text or secret in the diff. (intent.md:13)
4. **R4. `make lint`.** Runs `$(PYTHON) -m flake8 --select=E9,F63,F7,F82 src/ server/ scripts/ tests/` and exits zero on the current `main`. Measured 2026-10-21: 0 findings with this selection. (intent.md:14)
5. **R5. `make check`.** Runs `make lint` then `$(PYTHON) -m pytest tests/ -x -q` (the flags CI uses, `.github/workflows/ci.yml:27`); exits non-zero if either fails; completes in under 60 seconds on a laptop. Measured 2026-10-21: the full suite is 879 passed, 5 skipped in 27 s on the phone and 32 s on Razy's earlier run. (intent.md:14, intent.md:21)
6. **R6. Existing targets unchanged.** `make test`, `make e2e` and every other target in the Makefile keep their recipe byte for byte; `make help` lists `check` and `lint`. (intent.md:36)
7. **R7. Nothing about the plugin in the repo.** After the PR, `git ls-files .claude` prints nothing, `git grep -n "sdlc@"` prints nothing, and no tracked file names the marketplace or the company. (Neither "startup" nor "marketplace" is a usable grep: the first appears in 13 tracked lines as the ordinary word for app start, the second in intent.md:32 itself; `git grep`, 2026-10-21.) The plugin is enabled only through `.claude/settings.local.json`, which `.gitignore` already lists. (intent.md:15, intent.md:32)
8. **R8. PR template.** `.github/PULL_REQUEST_TEMPLATE.md` has exactly three headings: Testing, Risk, How to revert. It says nothing about `changes/` or Claude, so an external PR can fill it without either. (intent.md:16, intent.md:34)
9. **R9. `CONTRIBUTING.md`.** Gains one line stating that `changes/` holds maintainer change records and contributors need not touch it. No other line changes. (intent.md:17)
10. **R10. CI and deploy untouched.** `.github/workflows/ci.yml` gains no job and no workflow file is added; merge to main still publishes the image Argo CD deploys. (intent.md:33, intent.md:37) See flagged concern C2 for the one step this spec recommends adding inside the existing `test` job.
11. **R11. No new dependency.** `make lint` and `make check` use only tools already pinned in `requirements.txt` (flake8 7.4.1, pytest 9.1.1; `requirements.txt:3,5`). (security-baseline rule 6)

## Design

**Change records.** A folder per slug under `changes/`, markdown only, committed on branch `change/<slug>` with the trailer `Change: <slug>`. The folder is the audit trail the intent asks for (intent.md:7); the sdlc plugin's hooks read the `Status:` lines and the trailer, but the files themselves are plain markdown that any reader can follow without the plugin.

**`CLAUDE.md`.** Project-level instructions for Claude Code sessions in this checkout. Content is limited to what a session needs on every turn: purpose, run commands (`make install`, `make check`, `make run FILE=`), the invariants, the chain (`intent.md -> spec.md -> plan.md -> PR`), and the done-when (`make check` green, PR template filled). Everything else stays where it lives today (`README.md`, `docs/dev-log/STATUS.md`, `docs/design`). No marketplace, plugin or startup reference, because the file is public.

**`REVIEW.md`.** The checklist both a human reviewer and the plugin's adversarial-reviewer agent read. It quotes the invariants rather than pointing at them, because the agent reads it in a fresh context; `docs/dev-log/STATUS.md` stays the source and is named as such (the intent's constraint keeps that section untouched, intent.md:35).

**Makefile.** Two new phony targets, `lint` and `check`, added to `.PHONY`, `help` and the "Core workflows" block, using the existing `$(PYTHON)` variable so a venv works the same way it does for `make test`.

- `lint` selects flake8's syntax-error and undefined-name classes (E9, F63, F7, F82). Measured 2026-10-21 on this tree: no config, 1717 findings; `--max-line-length=120`, 408; `--select=E9,F` on `src/ server/ scripts/ tests/`, 30 (7× F401 unused import, 14× F541 f-string without placeholder, 9× F841 unused variable); `--select=E9,F63,F7,F82`, 0. Only the last selection passes today, so it is the gate; widening it means code changes and gets its own slug (see Open questions).
- `check` runs `lint` first (seconds) and then the full suite with CI's flags, so a local green and a CI green mean the same thing.

**PR template.** Three headings, no required `changes/` link, because dependabot and external contributors must be able to open PRs unchanged (intent.md:27). The chain for a dependabot bump lives in the maintainer's `changes/<slug>/`, not in the bot's PR body.

**Plugin install.** `.claude/settings.local.json` enables the plugin and names its marketplace. `.gitignore` lists that file (`.gitignore`, "Claude Code local config" block, checked 2026-10-21), so it never lands. `.claude/settings.json`, `.claude/skills/` and `.claude/agents/` are not ignored; see concern C1.

**Unchanged.** CI workflow structure, the `publish` job, Argo CD, `docs/design`, the invariants section of `STATUS.md`, every existing Makefile recipe.

## Flagged concerns

- **C1. The repo's `.claude/` directory is only partly gitignored** (`.gitignore` ignores `settings.local.json` and `worktrees/`; `settings.json`, `skills/`, `agents/` would be tracked). A stage that writes the template's settings pin into `.claude/settings.json` would commit the marketplace name to a public repo. Policy: intent constraint "no reference to any private marketplace" (intent.md:32); security-baseline rule 1 by analogy (local config is machine-specific). Owner: Razy. Resolution proposed: add `.claude/` to `.gitignore` as a whole in this change, and keep R7's `git ls-files .claude` check as the acceptance test. Open until Razy picks.
- **C2. `make lint` is not in CI, so an external PR can merge green and leave `main` red for `make check`.** Intent says "no new CI workflows" (intent.md:33) and "the full suite stays in CI" (intent.md:14), but says nothing about lint in CI. A single `run: make lint` step inside the existing `test` job is not a new workflow and keeps external PRs working without Claude. Policy: intent constraints (intent.md:33, intent.md:34, intent.md:37). Owner: Razy. Recommendation: add the step; R10 is written to allow it. Open until Razy picks.
- **C3. The intent assumed a unit test subset for `make check`; the full suite already meets the 60-second bar** (27 s here, 32 s on Razy's run, both 2026-10-21; slowest single test 1.8 s). A subset needs a marker or a file list that drifts from the suite, and the suite has no `unit` marker today. Recommendation: `make check` runs the full suite (R5). The intent's "The full suite stays in CI" (intent.md:14) still holds. Owner: Razy. Resolved in this spec unless Razy objects.
- **C4. "CI remains the merge gate" is unverified from this session.** Reading main's branch protection through the GitHub API was not permitted here. If main does not require the CI `test` check, the gate the intent relies on (intent.md:37) is a habit, not a setting. Owner: Razy: open `Settings > Branches` and confirm `test` is a required status check. No file in this change depends on the answer; the acceptance criteria do.
- **C5. Security-baseline rule 6 reads "version bumps are their own change with their own slug", while the intent treats "dependabot bumps #46 and #47" as one next change** (intent.md:22). The two readings conflict. Owner: Razy (policy owner and maintainer). Recommendation: one slug per dependabot PR, because each is merged on its own. Carried to the next change's intent; does not block this one.
- Security-baseline rules 2 (authentication), 3 (input validation), 4 (PII) and 5 (audit) are not touched: this change adds no endpoint, input, log line or state-changing code. Rule 1: no secret is written; `CLAUDE.md` must carry none (R2, R7). Rule 6: no dependency added (R11).

## Open questions carried from intent.md

- **Dvir Mintz's view on the `changes/` folder** (intent.md:46). Carried. Owner: Razy, who asked. Due: before the sdlc-base PR merges. If unanswered, the merge proceeds, because the folder is additive and leaves external contributors untouched (R8, R9); an objection becomes a new intent.
- **New: should the remaining 30 pyflakes findings (F401, F541, F841) be cleaned so `make lint` can widen to `--select=E9,F`?** Owner: Razy. Its own slug if yes; not part of this change.

## Acceptance criteria

The product owner (Razy) checks, on the PR for this slug:

1. `make check` on the branch prints a flake8 pass and `879 passed, 5 skipped` (or the then-current green count) and the wall time is under 60 s.
2. `make test`, `make e2e` and `make help` behave as before; `make help` lists `check` and `lint`.
3. `git ls-files .claude` and `git grep -n "sdlc@"` both print nothing; Razy reads the new files once for the marketplace and company names.
4. `CLAUDE.md` is at most 60 lines; `REVIEW.md`, `.github/PULL_REQUEST_TEMPLATE.md` and the one `CONTRIBUTING.md` line read as R2, R3, R8 and R9 say.
5. CI is green on the PR with no new workflow file, and concerns C1 and C2 each carry a decision in this file before the merge.
6. After the merge: the next change's `changes/<slug>/` folder reaches `plan.md` and a merged PR, which closes intent.md:22.
