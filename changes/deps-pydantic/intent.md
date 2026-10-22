# Intent: bump pydantic to 2.14.1

Slug: deps-pydantic. Author: Razy (maintainer). Date: 2026-10-22. Status: draft.
Source: ticket PR #46 (dependabot, "build(deps): bump pydantic from 2.13.5 to 2.14.1").

## Problem
The pinned runtime dependency `pydantic` is one minor version behind. `requirements.txt`
line 10 pins `pydantic==2.13.5` (verified in the checkout); dependabot's PR #46 proposes
2.14.1 in one commit, 3063e08, touching only that line (verified: the commit was fetched
as FETCH_HEAD and its diff is the one-line change to `requirements.txt`).

Repo policy says a version bump is its own change with its own slug, so the bump goes
through the intent -> spec -> plan chain instead of being merged from the bot's PR
directly. Precedent: `changes/deps-hypothesis` (PR #54, merged).

Unlike hypothesis, pydantic is a runtime dependency. `src/contracts.py` defines the
models that the Layer 2 and Layer 3 LLM contracts are validated with, and three test
files cover them: `tests/test_layer3_contracts.py`, `tests/test_llm_contracts.py`,
`tests/test_schema_contracts.py` (grep of src, server, scripts, tests in the checkout:
these four files are the only ones that mention pydantic).

## Proposed outcome
`requirements.txt` pins `pydantic==2.14.1`. The full suite is green on that version,
locally and in CI. The CI docker job's health check passes. PR #46 is closed as
superseded by this change's own PR.
Success is measured as: this change's PR merged with CI green, and PR #46 closed.

## Affected users and systems
- The running service: contract validation of LLM output in `src/contracts.py`.
- The Docker image (`Dockerfile` installs from `requirements.txt`; the CI `docker` job
  builds it and checks `/api/health`).
- CI (`.github/workflows/ci.yml`: test, security, audit and docker jobs all install
  from `requirements.txt`).
- Developers' venvs.

## Constraints
- No other pin in `requirements.txt` moves.
- `pyproject.toml`'s floor `pydantic>=2.10` (line 28) stays.
- No edit to any test.
- No change to `src/contracts.py` unless the new version forces one. If it does, that
  is a flagged concern in spec.md, not a silent fix.

## Out of scope
Anything else.

## Open questions
None.
