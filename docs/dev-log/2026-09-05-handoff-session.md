# Dev session log — 2026-09-05 — handoff execution

Source brief: `~/Downloads/etiqtech_dev_handoff.md` (Engineering Handoff Brief).
Operator: Claude (Fable 5.1) working autonomously; every commit reviewed by a Sonnet subagent (code review + security) before the next step.
Baseline at start: `cdfc44f docs: polish launch roadmap`, `PYTHONPATH=. python -m pytest tests/ -q` -> 440 passed, 2 skipped (2.65s). Python 3.13.11 (miniconda). Docker daemon was down at start; Docker Desktop launched.

Conventions in this log: one entry per step, with **What**, **Why/decision**, **Evidence**, and **Review** (subagent findings + what was done about them).

---

## Step 1 — P0.1 sessions under gunicorn (commit `ec0519f`)

**What.** `gunicorn.conf.py` (1 worker, gthread, 16 threads, timeout 300) is now the only place the process model is defined; the Dockerfile CMD is `gunicorn -c gunicorn.conf.py server.app:app`. New `tests/test_gunicorn_sessions.py` spawns the real config on a free port and runs 50 analyze->SSE round-trips with Ollama pointed at a closed port (fast fallback per theme); asserts zero "Session not found" and a `complete` event on every stream. `RATELIMIT_ENABLED=false` env switch added (flask-limiter's own config key) because 50 POSTs trip the 10/min limit. flask-limiter `memory://` per-process caveat documented in the conf, app.py and README.

**Decision.** Single worker + threads over a shared store (Redis), per the brief's recommendation: gthread's poll loop keeps heart-beating the arbiter while request threads are busy, so long SSE streams are not killed by `timeout`; adding Redis would add an infra dependency for a tool sold on simple deployment. Scale-out path documented in the conf docstring.

**Evidence.** `PYTHONPATH=. python -m pytest tests/test_gunicorn_sessions.py -q` -> 2 passed in 2.3s (50 round-trips). Full suite 442 passed, 2 skipped.

**Gotcha found while writing the test.** First version piped gunicorn's stderr and never drained it; the DEBUG-level logging (the P0.3 `basicConfig` hijack) filled the pipe and blocked the worker after ~12 round-trips, which looked exactly like a lost session. Manual reproduction with curl proved the server fine (20/20 at 0.03s). stderr now goes to a temp file.

## Step 2 — P0.2 law corpus in the image (commit pending review)

**What.** `examples/general-concepts/` -> `resources/law/` (`git mv`; PDF renamed to `national-guidance-2025-he.pdf`), with a README describing each file. `src/llm_agent.law_loaded()` is the one check; `/api/health` returns `law_loaded`, the server logs `LAW TEXT NOT FOUND` at startup when false, `_load_law_text` warns once instead of silently returning "". `llm_layer3` imports `LAW_PATH` from `llm_agent` (was a duplicate constant). Dockerfile `COPY resources/ resources/`. CI gains a `docker` job: build, run, curl health, assert `law_loaded` true, fail if the warning appears in logs. `tests/test_law_resources.py` (3 tests) covers the path, the health flag, and the missing-file behaviour.

**Decision.** Took the brief's "better" option (move out of examples) rather than just adding a COPY line: the files are runtime assets and the old location is why they were skipped.

**Evidence.** Local `docker build` + `docker run` -> `{"law_loaded":true,"status":"ok"}`; container log shows `Using worker: gthread`, one worker booted. Suite 445 passed, 2 skipped.
