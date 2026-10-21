# Plan: bump hypothesis to 6.170.1

Slug: deps-hypothesis. From: spec.md @ af5f06c. Date: 2026-10-21. Status: draft.

Spec acceptance: Razy accepted spec.md in chat on 2026-10-21 and asked for the build in the
same turn; it is not merged on `main` (`git log main -- changes/deps-hypothesis` is empty).
As with intent.md (spec C2), one PR carries intent, spec and plan together, and its merge is
the decision for all three.

## Files that change
- `requirements.txt`: modified. Line 12, `hypothesis==6.168.3` -> `hypothesis==6.170.1`.
  Arrives by cherry-pick of dependabot's commit f3cabea (fetched as `FETCH_HEAD`); the diff
  is that one line and nothing else (`git show FETCH_HEAD --stat`: 1 file, +1 -1).
- `changes/deps-hypothesis/plan.md`: new (this file).
- `changes/deps-hypothesis/spec.md`: modified. Status line `draft` -> `accepted`, in the plan
  commit, per sdlc-artifacts "flip the line in the next stage's first commit".

Not touched: `pyproject.toml` (floor `hypothesis>=6.120` at line 38 stays, R2), `tests/`
(R5), every other pin in `requirements.txt` (R1), `.github/workflows/` (protected).

## Order of work
1. Commit plan.md and the spec Status flip on `change/deps-hypothesis`, trailer
   `Change: deps-hypothesis`, before any code change.
2. `git cherry-pick FETCH_HEAD`. Dependabot stays the author; the branch's
   `requirements.txt` is identical to `main`'s (`git diff main -- requirements.txt` is
   empty), so the pick applies clean.
3. `git commit --amend --no-edit --trailer "Change: deps-hypothesis"`, so the code commit
   carries the trailer CLAUDE.md requires. Author is unchanged by an amend. The trailer lands
   in the message's last paragraph, after dependabot's `Signed-off-by`, so it parses.
4. Run every command under Proof and paste the output into the report.
5. Hand the branch to `sdlc:verifier`; include its report verbatim.
6. Not in this run (Razy's call): open the PR; close PR #47 with the comment under Proof
   (spec C4, R7). CI (R4) runs on the PR.

## Risks
- **Riskiest step: 2, the cherry-pick.** It is the only code step. Blast radius: the test
  suite only; hypothesis is imported solely by `tests/test_linter_properties.py` (lines
  17-18). Conflict risk is nil (base file matches `main`). A failed pick is undone with
  `git cherry-pick --abort`.
- **Step 3 may trip the plugin's "code commit without plan.md" hook.** Nothing departs from
  this plan in that commit, so there is no Deviations line to add; if the hook denies the
  amend headless, the commit stays without the trailer and that is recorded under
  Deviations for Razy to amend.
- **R3 asks for a fresh `pip install -r requirements.txt`.** This session has no network
  (spec C3), so the proof is the weaker form: the installed dist-info folder name equals the
  new pin, plus the suite green against it. The install from the file is proven by CI's
  `test` job (ci.yml:23), which installs from `requirements.txt` on a clean runner.
- **R4 (pip-audit, bandit, pytest on 3.14 in CI) and R7 (PR #47 closed) cannot be proven
  here.** They are checked on the PR after Razy's clicks. Named in the PR body's Risk section.
- **Changelog not re-read** (spec C3) and **transitives unpinned** (spec C5): carried
  unchanged; the suite is the gate.

## Not chosen
- **Merge PR #47 directly.** security-baseline rule 6 routes version bumps through their
  own slug and the artifact chain; merging the bot's PR skips intent and spec.
- **Edit `requirements.txt` by hand.** Same diff, but loses dependabot's authorship and the
  commit's link to the PR and the upstream compare range. The cherry-pick keeps both.
- **`make install` to reinstall from the file.** No network here, and the target also runs
  `pip install --upgrade pip`, which widens what moves in the venv.
- **Pin `attrs` and `sortedcontainers` while here.** Out of scope (spec C5); a new intent.

## Proof
Run from the repo root, after step 3. Baseline measured on the branch before step 2, where
the only difference from `main` is `changes/deps-hypothesis/`: `891 passed, 5 skipped`.

- `git diff main -- requirements.txt` -> exactly one `-hypothesis==6.168.3` and one
  `+hypothesis==6.170.1`, no other `+`/`-` lines (R1).
- `git diff main --stat` -> `requirements.txt` and files under `changes/deps-hypothesis/`
  only; `pyproject.toml` absent (R1, R2).
- `git diff main --stat -- tests/` -> empty (R5).
- `grep -n hypothesis pyproject.toml` -> `38:    "hypothesis>=6.120",` (R2).
- `grep -n max_examples tests/test_linter_properties.py` -> lines 102 and 128, both
  `@settings(max_examples=200)` (R6).
- `ls -d .venv/lib/*/site-packages/hypothesis-*.dist-info` -> one entry ending
  `hypothesis-6.170.1.dist-info` (R3, installed version equals the pin).
- `make check PYTHON=.venv/bin/python` -> flake8 exits 0, then `891 passed, 5 skipped`
  (R3; N equals the baseline, so equals `main`'s N).
- `.venv/bin/python -m pytest tests/test_linter_properties.py -q` -> all passed, 0 failed (R6).
- `git log -2 --format='%h %an%n%(trailers:key=Change)'` -> top commit authored by
  `dependabot[bot]` with `Change: deps-hypothesis`; the one below by Razy or Claude with the
  same trailer.
- `git log main..HEAD --format=%s` -> four subjects: intent, spec, plan, and
  `build(deps): bump hypothesis from 6.168.3 to 6.170.1`.

Checked on the PR, not here: CI jobs `test`, `security`, `audit`, `docker` green (R4);
PR #47 state `closed` with this comment, paste-ready for Razy (spec C4, R7):

> Superseded by #<this PR> (change `deps-hypothesis`), which cherry-picks f3cabea unchanged through the repo's intent -> spec -> plan chain. Closing, not merging.

## Deviations
- Plan mode was not entered: this was a headless run and Razy pre-approved the plan in the
  invocation, conditional on it naming files, order, risks and proof.
- **The gate was red twice before it was green.** After the cherry-pick, `make check` failed
  on `tests/test_l2_parallel.py::test_parallel_calls_overlap` (line 82, a wall-clock assert
  `< 1.5 s`) with 2.5 s, then 3.1 s on a re-run alone; the file by itself failed twice more
  (3.56 s, 1.97 s). The third full `make check` passed: `891 passed, 5 skipped in 26.21s`.
  Evidence the pin is not the cause: the test imports no hypothesis; the venv held
  `hypothesis-6.170.1.dist-info` before the pin moved, so the pin edit changed no runtime
  bytes; the same test passed in the baseline run on the same venv 15 minutes earlier; a
  `ThreadPoolExecutor(12)` probe of 22 x `sleep(0.2)` ran at 0.41 s (ideal 0.40 s), so the
  thread primitive is fine; `nproc` is 4 and load average was 0.12 with nothing else running.
  Cause: inference, unverified: the parallel Layer 2 path (`src/llm_agent.py:1377`, pool of
  12 threads doing CPU-bound prompt building under the GIL on a phone) runs near the 1.5 s
  bound, and the bound is a timing claim the test machine must meet. Not touched here
  (CLAUDE.md: never edit a test to make a fix pass). Separate intent proposed: make
  `test_parallel_calls_overlap` assert overlap by counting concurrent in-flight calls, not
  wall-clock seconds. Probe files left under the gitignored `output/dev_runs/` (`probe.py`,
  `probe_test.py`); Razy deletes.
