# Spec: bump hypothesis to 6.170.1

Slug: deps-hypothesis. From: intent.md @ c94e571. Date: 2026-10-21. Status: draft.
Policies applied: sdlc-artifacts, security-baseline, as of 2026-10-21. No `policy-*` skill exists in this repo (`.claude/skills/` is empty).

## Summary
`requirements.txt` pins `hypothesis==6.170.1` instead of `6.168.3`, and nothing else in the
repo moves. The full suite and every CI job are green on the new pin. Dependabot's PR #47 is
closed as superseded by this change's PR.

## Requirements
Numbered, each testable, each traceable to a line in intent.md.

1. **R1. One pin moves.** `requirements.txt` line 12 reads `hypothesis==6.170.1`; the diff
   against `main` for `requirements.txt` is exactly that one line replaced, matching PR #47's
   commit f3cabea byte for byte (`git show FETCH_HEAD`, read 2026-10-21). (intent.md:17, :31)
2. **R2. The floor stays.** `pyproject.toml` line 38 still reads `"hypothesis>=6.120",` and
   `pyproject.toml` is not in the diff. (intent.md:30)
3. **R3. Local gate green on the new pin.** In a venv where `pip install -r requirements.txt`
   has installed 6.170.1, `make check` prints a flake8 pass followed by `N passed` with no
   failures, where N equals the count `make check` prints on `main` the same day. (intent.md:17-18)
4. **R4. CI green.** All three jobs in `.github/workflows/ci.yml` pass on the PR: `test`
   (pytest on Python 3.14, ci.yml:18, :30), the bandit job (ci.yml:43), and `pip-audit
   -r requirements.txt --strict` (ci.yml:70), which means 6.170.1 carries no known advisory
   at merge time. (intent.md:18, :24)
5. **R5. No test edited.** `git diff main --stat -- tests/` is empty. (intent.md:35)
6. **R6. The property tests still exercise what they claim.** `tests/test_linter_properties.py`
   passes with its two `@settings(max_examples=200)` tests unchanged, at lines 102 and 128.
   (intent.md:22-23)
7. **R7. PR #47 closed, not merged.** PR #47 ends in state `closed` with a comment naming
   this change's PR. (intent.md:19-20)

## Design
There is no code design: the change is the one-line pin. What the spec records is why the
bump is safe for this repo, derived from where hypothesis is used.

**Where hypothesis is used.** `git grep -n hypothesis` over code and config files finds
exactly one import site: `tests/test_linter_properties.py` lines 17-18 (`given`, `settings`,
`strategies as st`). Strategies in use: `st.text(max_size=...)`, `st.integers(min_value=...,
max_value=...)`, `st.booleans()`. Decorators: `@settings(max_examples=200)`, `@given(...)`.
The test functions carry no type annotations. No `src/`, `server/` or `scripts/` file imports
it; `pyproject.toml` lists it only under the `dev` extra (line 38).

**Changelog surfaces versus this repo** (changelog 6.168.4 through 6.170.1 as supplied by Razy,
read 2026-10-21 from hypothesis.readthedocs.io; not re-read from this session, see C3):

| Changelog entry | Used here? |
|---|---|
| 6.169.0 drops Python 3.10 | No. CI and the image run 3.14 (ci.yml:18); `requires-python = ">=3.11"` (pyproject.toml:11). |
| 6.170.1 changes unique-collection generation (`sets()`, `lists(unique=True)`) | No. Neither strategy appears. |
| 6.169.3 widens `randoms().seed()` arguments | No. `randoms()` not used. |
| 6.169.1 changes an error type for `data().map()` with keyword arguments | No. `data()` not used. |
| 6.169.4 fixes a Python 3.14 annotation edge case with `@given` | Relevant platform, but the decorated functions have no annotations. |
| No deprecations, no settings changes | `@settings(max_examples=200)` keeps its meaning. |

**Interfaces that consume the pin.** `make install` (`pip install -r requirements.txt`),
the CI `test` and bandit jobs (ci.yml:23, :43), the `pip-audit` job (ci.yml:70), and the
Docker image build. Nothing reads the version at runtime.

**State of the checkout.** The local venv already holds 6.170.1: `.venv/lib/*/site-packages/`
contains `hypothesis-6.170.1.dist-info` (listed 2026-10-21; `pip show` was not run). So any
recent local `make check` already ran against the new version, and the pin change makes the
file match what is installed. The plan's proof must still reinstall from the file (R3), so the
green is attributed to the pin and not to a venv that got ahead of it.

**Transitive dependencies.** hypothesis depends on `attrs` and `sortedcontainers`; neither is
pinned in `requirements.txt` (the file has 14 lines, none for them). That is pre-existing and
out of this change's scope (C5).

## Flagged concerns
Each: the concern, the policy it touches, the owner who resolves it, the resolution.

- **C1. This is the version bump itself.** security-baseline rule 6 ("version bumps are their
  own change with their own slug, never a side effect"). Owner: Razy. Resolution: satisfied by
  construction; R1 keeps every other pin still, and `deps-pydantic` stays its own slug
  (intent.md:34, sdlc-base spec C5).
- **C2. intent.md is not merged on `main`.** sdlc-artifacts, "Status and acceptance": a stage
  starts only after the previous file's PR merges, and `git log main -- changes/deps-hypothesis/intent.md`
  is empty. Razy accepted the intent in chat on 2026-10-21 and asked for the spec in the same
  turn; commit c94e571 rides on this branch, so one PR will carry intent and spec together.
  Owner: Razy. Resolution: intent.md's Status line is flipped to `accepted` in this spec commit
  with the chat acceptance named, per the skill's "flip the line in the next stage's first
  commit". The merge of this change's PR is the decision for both files.
- **C3. The changelog was not re-read from this session.** how-to-work-with-me "Before you
  build" 6 (verify a mechanism against the vendor's docs). The entries above come from Razy's
  read on 2026-10-21; this session's fetch was denied (no network). Owner: Razy. Resolution:
  carried as stated. The suite run (R3, R4) is the gate; the changelog table is advisory and
  says only that no listed surface is used here.
- **C4. Closing PR #47 is an outward action on the repo.** my-rules 12 ("who hits send").
  Owner: Razy. Resolution: the plan prepares the closing comment paste-ready; Razy closes, or
  hands the `gh pr close` to Claude explicitly. R7 is checked after that click.
- **C5. Transitive test dependencies are unpinned** (`attrs`, `sortedcontainers`).
  security-baseline rule 6 ("pinned"). Pre-existing on `main`, untouched by this change.
  Owner: Razy. Resolution: out of scope here; a new intent if Razy wants the whole tree pinned
  (a lock file or `pip-compile`), otherwise accepted as the current practice.

## Open questions carried from intent.md
None in intent.md (intent.md:38). None new.

## Acceptance criteria
What the product owner checks before accepting the eventual PR.

1. `git diff main -- requirements.txt` shows one removed line `hypothesis==6.168.3` and one
   added line `hypothesis==6.170.1`, and `git diff main --stat` lists only `requirements.txt`
   and files under `changes/deps-hypothesis/` (R1, R2, R5).
2. The PR body's Testing section quotes `make check` output from a fresh install of the file:
   flake8 pass, then `N passed`, with N stated against `main`'s N (R3, R6).
3. All three CI jobs green on the PR's head commit (R4).
4. PR #47 is closed with a comment that links this PR (R7), after Razy's click (C4).
5. The PR body's Risk section names C3 (changelog not re-read) and C5 (unpinned transitives)
   as known, and How to revert is `git revert` of the pin commit.
