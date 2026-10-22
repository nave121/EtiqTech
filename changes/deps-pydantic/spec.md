# Spec: bump pydantic to 2.14.1

Slug: deps-pydantic. From: intent.md @ 85705a0. Date: 2026-10-22. Status: accepted (by Razy in chat, 2026-10-22; see plan.md).
Policies applied: sdlc-artifacts, security-baseline, as of 2026-10-22. No `policy-*` skill exists in this repo (`.claude/skills/` is absent).

## Summary
`requirements.txt` pins `pydantic==2.14.1` instead of `2.13.5`, and nothing else in the
repo moves. The full suite and every CI job are green on the new pin, and the Docker image's
health check still passes. Dependabot's PR #46 is closed as superseded by this change's PR.

## Requirements
Numbered, each testable, each traceable to a line in intent.md.

1. **R1. One pin moves.** `requirements.txt` line 10 reads `pydantic==2.14.1`; the diff
   against `main` for `requirements.txt` is exactly that one line replaced, matching PR #46's
   commit 3063e08 byte for byte (`git show FETCH_HEAD --stat`, read 2026-10-22: one file,
   one insertion, one deletion). (intent.md:7-10, :23, :37)
2. **R2. The floor stays.** `pyproject.toml` line 28 still reads `"pydantic>=2.10",` and
   `pyproject.toml` is not in the diff. (intent.md:38)
3. **R3. Local gate green on the new pin.** In a venv where `pip install -r requirements.txt`
   has installed 2.14.1, `make check` prints a flake8 pass followed by `N passed` with no
   failures, where N equals the count `make check` prints on `main` the same day. (intent.md:23)
4. **R4. CI green.** All four jobs in `.github/workflows/ci.yml` pass on the PR: `test`
   (Python 3.14, `make lint`, then pytest `-x -q`; ci.yml:18, :26, :30), `security` (bandit
   gate, ci.yml:55), `audit` (`pip-audit -r requirements.txt --strict`, ci.yml:70, which means
   2.14.1 and the tree it resolves carry no known advisory at merge time), and `docker`
   (image builds from the new pin and `/api/health` answers with `law_loaded: true`,
   ci.yml:78-88). (intent.md:24, :30-33)
5. **R5. No test edited.** `git diff main --stat -- tests/` is empty. (intent.md:39)
6. **R6. The contract models are untouched and still validate.** `git diff main --
   src/contracts.py` is empty, and the three contract files `tests/test_layer3_contracts.py`,
   `tests/test_llm_contracts.py`, `tests/test_schema_contracts.py` pass on 2.14.1 (15 test
   functions, 55 collected cases as of 2026-10-22). If 2.14.1 forced a change to
   `src/contracts.py`, that is a new flagged concern, not a silent edit. (intent.md:16-20, :40-41)
7. **R7. PR #46 closed, not merged.** PR #46 ends in state `closed` with a comment naming
   this change's PR. (intent.md:24-26)

## Design
There is no code design: the change is the one-line pin. What the spec records is why the
bump is safe for this repo, derived from where pydantic is used.

**Where pydantic is used.** `grep -rln pydantic` over code and config files (2026-10-22,
`.venv`, `output` and `.git` excluded) finds six files: `pyproject.toml` (the floor),
`requirements.txt` (the pin), `src/contracts.py` (the only import in `src/`), and the three
contract test files, each importing `ValidationError` and calling `Model.model_validate(...)`
on a real pipeline result (`test_layer3_contracts.py:129, :231`, `test_llm_contracts.py:191`,
`test_schema_contracts.py:76, :139`). No file under `server/`, `scripts/` or `examples/`
imports pydantic, and `grep -rn contracts src server scripts examples` matches only the
module's own docstring: nothing in the running service imports `src.contracts`. The models
are exercised by the test suite only; the image installs pydantic but the server never loads it.
This narrows intent.md:29 ("the running service"), see C6.

**Pydantic surfaces in `src/contracts.py`** (read 2026-10-22): `BaseModel`, `Field` with
`min_length` (lines 80, 83, 101), `pattern` (line 89) and `default_factory` (lines 102-103,
120, 125-133, 135, 137, 168-169, 173); field types `str`, `int`, `bool`, `Optional[...]`,
`list[...]`, `dict[str, ...]`, `dict[str, Any]`, nested models, and `Literal[...]` of strings
and of the ints `0, 1, 2, 3` (lines 28, 31, 60, 81-82, 99-100, 110-113, 146-147, 157,
170-171). `from __future__ import annotations` at line 16, so every annotation is a string
pydantic resolves at class creation. No `model_config` or `ConfigDict`, no `Enum`, no
`Decimal`, no `datetime` or `timedelta` (`generated_at` is `str`, line 68), no `TypedDict`,
no `NamedTuple`, no `NameEmail`, no `multiple_of`, no `model_json_schema`, no `model_dump`
or any serialization call in the module or the three tests. The tests consume
`ValidationError` only as `f"{exc}"` inside `pytest.fail(...)`, so error-message wording
cannot flip a verdict.

**Release notes versus this repo** (2.14.0 of 2026-10-08 and 2.14.1 of 2026-10-11, as read
by Razy on 2026-10-22 from github.com/pydantic/pydantic/releases and quoted in the stage
brief; not re-read from this session, see C3). The notes say "several minor changes are
considered non-breaking according to our versioning policy, make sure to look into them
before upgrading"; each is checked against the surfaces above:

| Release note | Used here? |
|---|---|
| 2.14.0 drops Python 3.9, adds 3.15 | No. `requires-python = ">=3.11"` (pyproject.toml:11); CI and the image run 3.14 (ci.yml:18, Dockerfile:1). |
| `model_config` attribute no longer mutated | No. No model sets `model_config`; all run on the default config. |
| Enum constructors called in both validation modes | No. No `Enum`; the choice fields are `Literal` of `str` and `int`. |
| `multiple_of` must be positive | No. Constraints in use: `min_length`, `pattern`, `default_factory`. |
| Newlines rejected in `NameEmail` | No. Not used; the `email` extra is not installed. |
| Exceptions during `Decimal` validation handled; 2.14.1 enforces `max_digits` whole-digit limit | No. All numeric fields are plain `int`. |
| JSON schema defaults encoded consistently | No. No `model_json_schema` call; the repo's JSON schema (`IACUC_SCHEMA_V2`, `src/schema.py`) is hand-written and validated with `jsonschema`, not pydantic. |
| `ser_json_timedelta` no longer applied to all datetime types; 2.14.1 rejects out-of-range ints for `timedelta` | No. No `datetime`/`timedelta` field; no serialization call. |
| 2.14.1 named tuples in `Sequence` validation | No. Sequences are `list[str]`, `list[dict[str, Any]]`, `list[<model>]`. |
| 2.14.1 `TypedDict` closed/`extra_items` via inheritance | No. No `TypedDict`. |
| Fewer allocations in model validation | Neutral. |
| No deprecations listed | Nothing to migrate. |

Pre-existing and unchanged by this bump: the models run on the default config, so unknown
keys in a validated result are ignored, not rejected. That is acceptable because these models
are test-side contracts, not a trust boundary (the LLM's JSON is parsed by `parse_llm_json` in
`src/llm_agent.py` before any model sees it); noted here so the reader does not mistake them
for input validation under security-baseline rule 3.

**Interfaces that consume the pin.** `make install` (`pip install -r requirements.txt`),
the CI `test` and `security` jobs (ci.yml:23, :43), the `audit` job (ci.yml:70), and the
Docker image build (`Dockerfile` installs from `requirements.txt`; the `docker` job builds and
health-checks it, ci.yml:78-88). Nothing reads the version at runtime.

**State of the checkout.** The local venv already holds the new version: `.venv/bin/pip show
pydantic` prints `Version: 2.14.1` with `Requires: annotated-types, pydantic-core,
typing-extensions, typing-inspection`, and `pydantic_core` is `2.50.1` (both read
2026-10-22). On that venv the three contract files pass today: `55 passed in 3.13s`
(`.venv/bin/python -m pytest tests/test_layer3_contracts.py tests/test_llm_contracts.py
tests/test_schema_contracts.py -q`). The full `make check` was not run from this session
(the command needs an approval this headless run does not have); that is the plan's proof
(R3), and it must reinstall from the file so the green is attributed to the pin, not to a venv
that got ahead of it.

**Transitive dependencies.** pydantic 2.14.1's own metadata
(`pydantic-2.14.1.dist-info/METADATA`, read 2026-10-22) declares
`pydantic-core==2.50.1`, `annotated-types>=0.6.0`, `typing-extensions>=4.16.0`,
`typing-inspection>=0.4.4`. So the bump also moves `pydantic-core` (pinned exactly by
pydantic itself; the version 2.13.5 required was not checked here) and raises the
`typing-extensions` floor. None of the four is pinned in `requirements.txt` (14 lines, none
for them). That is pre-existing and out of this change's scope (C5).

## Flagged concerns
Each: the concern, the policy it touches, the owner who resolves it, the resolution.

- **C1. This is the version bump itself.** security-baseline rule 6 ("version bumps are their
  own change with their own slug, never a side effect"). Owner: Razy. Resolution: satisfied by
  construction; R1 keeps every other pin still, and this slug carries only pydantic
  (intent.md:37, sdlc-base spec C5).
- **C2. intent.md is not merged on `main`.** sdlc-artifacts, "Status and acceptance": a stage
  starts only after the previous file's PR merges, and `git log main --
  changes/deps-pydantic/intent.md` is empty (2026-10-22). Razy accepted the intent in chat on
  2026-10-22 and asked for the spec in the same turn; commit 85705a0 rides on this branch, so
  one PR will carry intent and spec together, as `deps-hypothesis` did (its spec C2). Owner:
  Razy. Resolution: intent.md's Status line is flipped to `accepted` in this spec commit with
  the chat acceptance named, per the skill's "flip the line in the next stage's first commit".
  The merge of this change's PR is the decision for both files.
- **C3. The release notes were not re-read from this session.** how-to-work-with-me "Before
  you build" 6 (verify a mechanism against the vendor's docs). The table above comes from
  Razy's read on 2026-10-22 as quoted in the stage brief; this session's fetch of
  github.com/pydantic/pydantic/releases was denied (no WebFetch grant). Owner: Razy.
  Resolution: carried as stated. The suite run (R3, R4, R6) is the gate; the table is advisory
  and says only that no listed surface is used here.
- **C4. Closing PR #46 is an outward action on the repo.** my-rules 12 ("who hits send").
  Owner: Razy. Resolution: the plan prepares the closing comment paste-ready; Razy closes, or
  hands the `gh pr close` to Claude explicitly. R7 is checked after that click.
- **C5. Transitive runtime dependencies are unpinned** (`pydantic-core`, `annotated-types`,
  `typing-extensions`, `typing-inspection`). security-baseline rule 6 ("pinned"). Pre-existing
  on `main`, untouched by this change; `pip-audit` (R4) still audits whatever they resolve to.
  Owner: Razy. Resolution: out of scope here; the same open item as `deps-hypothesis` C5 (a
  lock file or `pip-compile` as a new intent), otherwise accepted as the current practice.
- **C6. intent.md:29 names "the running service" as affected; the code says the server never
  imports `src.contracts`.** my-rules 7 ("docs match reality"). The intent stays in the
  originator's words (sdlc-artifacts, "Writing rules"); the correction is recorded here, in
  Design. Practical effect: the runtime blast radius of this bump is the installed package in
  the image, not any code path a user hits; the suite is where a regression would show. Owner:
  Razy. Resolution: recorded; no edit to intent.md beyond the Status line.

## Open questions carried from intent.md
None in intent.md (intent.md:46-47). One new, answered: does 2.14.1 force a change to
`src/contracts.py` (intent.md:40-41)? No, by the surface check above and by the 55 passing
contract cases on 2.14.1; R6 makes that a checked condition on the PR.

## Acceptance criteria
What the product owner checks before accepting the eventual PR.

1. `git diff main -- requirements.txt` shows one removed line `pydantic==2.13.5` and one
   added line `pydantic==2.14.1`, and `git diff main --stat` lists only `requirements.txt`
   and files under `changes/deps-pydantic/` (R1, R2, R5, R6).
2. The PR body's Testing section quotes `make check` output from a fresh install of the file:
   flake8 pass, then `N passed`, with N stated against `main`'s N (R3, R6).
3. All four CI jobs green on the PR's head commit, including the `docker` job's health check
   (R4).
4. PR #46 is closed with a comment that links this PR (R7), after Razy's click (C4).
5. The PR body's Risk section names C3 (release notes not re-read), C5 (unpinned transitives,
   `pydantic-core` moving with the pin) and C6 (test-side only; no server import) as known,
   and How to revert is `git revert` of the pin commit.
