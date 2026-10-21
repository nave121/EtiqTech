# CLAUDE.md: EtiqTech

## What this is
AI-assisted pre-submission review for animal research ethics protocols (IACUC-style).
A researcher uploads an HTML protocol export and gets a report: a deterministic
linter (Layer 1) plus a local-LLM thematic review (Layer 2). Stateless on purpose:
protocols are never saved. Details: `README.md`, `docs/dev-log/STATUS.md`, `docs/design/`.

## How to run
```bash
make install            # deps from requirements.txt
make check              # flake8 + full pytest suite; the done-when gate
make run FILE=x.html    # parse + lint one export into output/dev_runs/
python server/app.py    # web UI on http://localhost:4242
```
Imports are `from src.x import ...` from the repo root; pytest sets `pythonpath` in
`pyproject.toml`. CI runs the same suite with `-x -q` (`.github/workflows/ci.yml`).

## Invariants
Quoted from `docs/dev-log/STATUS.md`, "Invariants (never break)"; that file is the source:

> All tests green (824 now, 440 original untouched) · no protocol text persisted or logged at any
> level · local-first LLM by default · LLM never gates/filters/rewrites Layer 1 · advisory framing
> permanent · auth stays at the reverse proxy.

The live test count is whatever `make check` prints today.

## How a change moves
Every change has a folder `changes/<slug>/` on branch `change/<slug>`:

`intent.md -> spec.md -> plan.md -> PR`

- Each file follows the headings of its template, in order, none missing.
- A stage starts only when the previous file is accepted (its PR merged).
- Commits carry the trailer `Change: <slug>`. PR title: `<slug>: <what changes>`.
- Departures from `plan.md` go under its `## Deviations` in the same commit.
- Reviewers, human or agent, read `REVIEW.md`.

## Done-when
A session is not done until:
1. `make check` is green (flake8 pass, then `N passed` with no failures).
2. The proof commands in `plan.md` ran and their output is in the report.
3. The PR body fills all three template sections: Testing, Risk, How to revert.

## Never
- Commit protocol text, fixtures from real protocols, or any secret.
- Edit a test to make a fix pass; fix the code or open a new intent.
- Touch the invariants section of `docs/dev-log/STATUS.md`.
- Run git as `git -C` or in `&&` chains; plain `git <subcommand>` from the repo root.
