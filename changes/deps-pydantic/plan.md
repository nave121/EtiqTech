# Plan: bump pydantic to 2.14.1

Slug: deps-pydantic. From: spec.md @ 9251d4a. Date: 2026-10-22. Status: draft.

Spec acceptance: Razy accepted spec.md in chat on 2026-10-22 and asked for the build in the
same turn; it is not merged on `main` (`git branch --contains 9251d4a` lists only
`change/deps-pydantic`). As with intent.md (spec C2) and as `deps-hypothesis` did, one PR
carries intent, spec and plan together, and its merge is the decision for all three.

## Files that change
- `requirements.txt`: modified. Line 10, `pydantic==2.13.5` -> `pydantic==2.14.1`.
  Arrives by cherry-pick of dependabot's commit 3063e08 (fetched as `FETCH_HEAD`); the diff
  is that one line and nothing else (`git show FETCH_HEAD --stat`: 1 file, +1 -1).
- `changes/deps-pydantic/plan.md`: new (this file).
- `changes/deps-pydantic/spec.md`: modified. Status line `draft` -> `accepted`, in the plan
  commit, per sdlc-artifacts "flip the line in the next stage's first commit".
- `changes/deps-pydantic/intent.md`: unchanged by this stage, but present in
  `git diff main --stat` because the intent and spec commits ride on this same branch.

Not touched: `pyproject.toml` (floor `pydantic>=2.10` at line 28 stays, R2), `tests/` (R5),
`src/contracts.py` (R6), every other pin in `requirements.txt` (R1), `.github/workflows/`
(protected).

## Order of work
1. Commit plan.md and the spec Status flip on `change/deps-pydantic`, trailer
   `Change: deps-pydantic`, before any code change.
2. `git cherry-pick FETCH_HEAD`. Dependabot stays the author. The pick's parent (febddfc)
   has `hypothesis==6.168.3` at line 12 and `main` now has `6.170.1` there (PR #54); the
   pick changes line 10 only, with line 11 untouched between them, so the 3-way merge should
   apply clean. If `requirements.txt` conflicts anyway, resolve to `pydantic==2.14.1` with
   `hypothesis==6.170.1` kept, `git add requirements.txt`, `git cherry-pick --continue`.
3. `git commit --amend --no-edit --trailer "Change: deps-pydantic"`, so the code commit
   carries the trailer CLAUDE.md requires. Author is unchanged by an amend. The trailer lands
   in the message's last paragraph, after dependabot's `Signed-off-by`, so it parses.
4. Run every command under Proof and paste the output into the report. A red gate gets one
   rerun; if `tests/test_l2_parallel.py::test_parallel_calls_overlap` alone is red twice, record
   the measured values under Deviations and move on (CI is the gate; deps-hypothesis Deviations
   documents the same wall-clock flake, which imports no pydantic).
5. Hand the branch to `sdlc:verifier`; include its report verbatim.
6. Not in this run (Razy's call): open the PR; close PR #46 with the comment under Proof
   (spec C4, R7). CI (R4) runs on the PR.

## Risks
- **Riskiest step: 2, the cherry-pick.** It is the only code step. Blast radius: the installed
  package in every venv and the Docker image, plus `src/contracts.py`, the only importer, which
  the server never loads (spec C6); a regression shows in the three contract test files, not in
  a user path. A failed pick is undone with `git cherry-pick --abort`.
- **The venv is already on 2.14.1** (`pydantic-2.14.1.dist-info`, `pydantic_core-2.50.1.dist-info`
  in `.venv/lib/python3.14/site-packages`, read 2026-10-22 before step 2), so the local green
  proves the suite against the new version but not the install from the file. R3's fresh
  `pip install -r requirements.txt` cannot run here (no network, no pip grant; spec Design,
  "State of the checkout"); the install from the file is proven by CI's `test` job (ci.yml:23)
  on a clean runner.
- **Step 3 may trip the plugin's "code commit without plan.md" hook.** Nothing departs from this
  plan in that commit; if the hook denies the amend headless, the commit stays without the
  trailer and that is recorded under Deviations for Razy to amend.
- **R4 (four CI jobs incl. pip-audit and the docker health check) and R7 (PR #46 closed)
  cannot be proven here.** Checked on the PR after Razy's clicks. Named in the PR body's Risk
  section.
- **Release notes not re-read** (spec C3) and **transitives unpinned, `pydantic-core` moves with
  the pin** (spec C5): carried unchanged; the suite is the gate.
- **The wall-clock test `test_parallel_calls_overlap` is flaky on this phone** (deps-hypothesis
  Deviations: 1 green in 6 full runs). It passed in today's baseline. Step 4 bounds the reruns.

## Not chosen
- **Merge PR #46 directly.** security-baseline rule 6 routes version bumps through their own
  slug and the artifact chain; merging the bot's PR skips intent and spec.
- **Edit `requirements.txt` by hand.** Same diff, but loses dependabot's authorship and the
  commit's link to the PR and the upstream compare range. The cherry-pick keeps both.
- **`make install` to reinstall from the file.** No network here, and the target also runs
  `pip install --upgrade pip`, which widens what moves in the venv.
- **Pin `pydantic-core`, `annotated-types`, `typing-extensions`, `typing-inspection` while
  here.** Out of scope (spec C5); a new intent, the same one deps-hypothesis left open.

## Proof
Run from the repo root, after step 3. Baseline measured on the branch before step 2, where
the only difference from `main` is `changes/deps-pydantic/`: `make check PYTHON=.venv/bin/python`
-> flake8 exit 0, `916 passed, 5 skipped in 38.10s` (2026-10-22).

- `git diff main -- requirements.txt` -> exactly one `-pydantic==2.13.5` and one
  `+pydantic==2.14.1`, no other `+`/`-` lines (R1).
- `git diff main --stat` -> `requirements.txt` and files under `changes/deps-pydantic/`
  only; `pyproject.toml`, `src/contracts.py` absent (R1, R2, R6).
- `git diff main --stat -- tests/` -> empty (R5).
- `grep -n pydantic pyproject.toml` -> `28:    "pydantic>=2.10",` (R2).
- `ls -d .venv/lib/*/site-packages/pydantic-*.dist-info` -> one entry ending
  `pydantic-2.14.1.dist-info` (R3, installed version equals the pin).
- `make check PYTHON=.venv/bin/python` -> flake8 exits 0, then `916 passed, 5 skipped`
  (R3; N equals the baseline, so equals `main`'s N).
- `.venv/bin/python -m pytest tests/test_layer3_contracts.py tests/test_llm_contracts.py tests/test_schema_contracts.py -q -p no:cacheprovider`
  -> `55 passed`, 0 failed (R6).
- `git log main..HEAD --format='%h %an%n%(trailers:key=Change)'` -> every commit carries
  `Change: deps-pydantic`; exactly one is authored by `dependabot[bot]` (the pin commit);
  the rest show the committer identity of this env, `root`.
- `git log main..HEAD --format=%s` -> intent, spec, plan,
  `build(deps): bump pydantic from 2.13.5 to 2.14.1`, plus any deviations commit(s). The pin
  commit stays the only code commit.

Checked on the PR, not here: CI jobs `test`, `security`, `audit`, `docker` green (R4);
PR #46 state `closed` with this comment, paste-ready for Razy (spec C4, R7):

> Superseded by #<this PR> (change `deps-pydantic`), which cherry-picks 3063e08 unchanged through the repo's intent -> spec -> plan chain. Closing, not merging.

## Deviations
- Plan mode was not entered: this was a headless run and Razy pre-approved the plan in the
  invocation, conditional on it naming files, order, risks and proof.
- **The gate is green on the builder's run and red on the verifier's, on the same wall-clock
  test as deps-hypothesis.** Builder's `make check PYTHON=.venv/bin/python` after the pick:
  `916 passed, 5 skipped in 40.19s`, flake8 clean, first run, no rerun needed
  (`output/dev_runs/check_run1.txt`). The verifier's two runs, about ten minutes later on the
  same venv, both stopped at `tests/test_l2_parallel.py::test_parallel_calls_overlap` (line 82,
  assert `< 1.5` s): 1.97 s, then 1.78 s (`1 failed, 226 passed, 4 skipped`, `-x` stops the
  suite); the file alone failed again at 1.71 s. With that one test deselected, the verifier's
  full run was `915 passed, 5 skipped, 1 deselected in 40.19s`, so nothing else in the suite is
  red on 2.14.1. The test imports no pydantic (`grep -rln pydantic src server tests` lists only
  `src/contracts.py` and the three contract files), so the pin is not on its code path. Not
  touched here (CLAUDE.md: never edit a test to make a fix pass); the follow-up intent proposed
  in deps-hypothesis Deviations (assert overlap by counting in-flight calls, not seconds) still
  stands. Done-when item 1 is met by the builder's run quoted above and not on demand; CI's
  `test` job on the PR (ci.yml:23) is the gate record. Verifier output files under the
  gitignored `output/dev_runs/` (`verifier_check.txt`, `verifier_check2.txt`,
  `verifier_full_noflake.txt`, plus the builder's `baseline_check.txt`, `check_run1.txt`);
  Razy deletes.
- The Deviations update is its own commit above the pin commit (the code commit departed from
  nothing), so the branch carries five commits, not the four first listed under Proof.
