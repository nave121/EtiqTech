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

**Review (P0.2, Sonnet).** SHIP WITH FIXES. (1) CI `grep && { exit 1; } || true` worked only via exit-inside-brace-group semantics; rewritten as explicit `if/then` in the P0.3 commit. (2) `_law_missing_warned` check-then-set is racy under threads: accepted — worst case is a duplicate WARNING line, no lock added. (3) Only the English translation is load-bearing today (Hebrew txt + PDF are reference material); noted in `resources/law/README.md`. Import graph confirmed acyclic.

## Step 3 — P0.1 review follow-ups (commit `8924589`)

**Review (P0.1, Sonnet).** SHIP WITH FIXES. Accepted and applied: threads 16 -> 64 (each SSE stream holds a thread; the pool is a hard concurrency ceiling and the Docker HEALTHCHECK queues behind it — ceiling now documented in conf + README); `RATELIMIT_ENABLED=false` logs a WARNING and raises under `FLASK_ENV=production` (mirrors the SECRET_KEY guard); test asserts the Dockerfile CMD really uses `gunicorn.conf.py`; dropped a no-op `accesslog = None` line whose comment overstated it. Pre-existing bug the review surfaced: behind Cloudflare `remote_addr` is the proxy, so all users shared one rate-limit bucket -> `PROXY_FIX=1` opt-in wraps the app in werkzeug ProxyFix (one hop). Opt-in because trusting X-Forwarded-For without a proxy lets clients spoof past the limiter. Declined: separate health listener (over-engineering; 64 threads far exceeds what one Ollama backend can serve).

## Step 4 — P0.3 runtime hygiene (commit `7928aad`)

**What.** Logging configured once in `server/app.py` (default INFO, `LOG_LEVEL` opt-in); `llm_clients` no longer touches the root logger. `_analysis_cache` behind `threading.Lock` via `_store_session`/`_get_session`; the 100-session cap trimmed before insert (off by one) — fixed, concurrency test added (8 threads x 50 inserts, expired + fresh entries). Context-budget guard: `estimate_tokens` + `context_budget_warning` in `llm_clients`, yielded as `{type: "warning", code: "context_budget"}` once per Layer 2 stream and per Layer 3 pass, rendered in the UI via `textContent` (persistent, not dismissable). md5 `usedforsecurity=False`. `pyproject.toml` filled (setuptools; packages `src`, `server`; pytest `pythonpath=["."]`), `pip install --no-deps .` verified in a fresh venv. BeautifulSoup -> `lxml`. CI if/then fix.

**Decisions, studied first.**
- *Token estimator.* Brief suggested chars/3. Measured with the real tokenizer (Ollama `prompt_eval_count`, qwen3.6:27b-mlx): Layer 3 pass-1 prompt 113,069 chars -> 27,658 tokens (4.09 chars/token); Layer 2 theme prompt 6,186 chars -> 1,462 tokens (4.23). Chose chars/4 — still slightly conservative, and not 36% inflated.
- *Truncation semantics.* Empirically (Ollama 0.32.15): a 27,658-token prompt at `num_ctx=32768` is sent whole (`prompt_eval_count` unchanged), i.e. Ollama truncates only when the prompt exceeds `num_ctx` itself. Below that, prompt + `num_predict` still do not fit, so generation is cut short or early context is shifted out. The warning message distinguishes the two cases (`truncates_prompt` vs `overflow`).
- *lxml.* Parsed all 94 HTML fixtures with `html.parser` and `lxml`: 0 JSON diffs, 0.77s vs 0.61s. Kept the pin and used it.

**FINDING FOR THE MAINTAINER (not fixed here, by design).** Layer 3 pass 1 is ~27.7k real tokens on a typical known-good fixture (36-42k by the old chars/3 estimate) because it injects the full law text (42 KB), all CASE_REPORTs, the x_meta catalog and the full protocol JSON. With the default `OLLAMA_NUM_CTX=32768` and `LLM_MAX_TOKENS=8192` this leaves ~5k tokens of output before the window is exhausted — on every protocol, not just large ones. The new guard now says so on every Layer 3 run. Options: raise the default window for Layer 3 (memory cost), trim Layer 3 context, or let Phase 2 retrieval replace the full-law injection (the brief's plan). Recommend the third; flagged rather than changed because it alters review behaviour.

**Evidence.** Suite 452 passed, 2 skipped. `pip show etiqtech` in the venv -> 0.1.0.

**Review (P0.3, Sonnet).** SHIP WITH FIXES. One real finding: the SSE generator's `cached["layer2_result"] = ...` bypassed the new lock and could write into an entry already evicted by the TTL sweep or the 100-cap, leaving Layer 3 with "Session not found". Fixed in `91d1083` via `_update_session()` (lock, re-fetch by id, no-op if gone). Confirmed by the reviewer: gunicorn loggers have `propagate=False` (no duplicate lines from the new `basicConfig`); urllib3 DEBUG logs request lines, never bodies; lxml swap differential-tested against deep nesting, charset mismatch and an entity-bomb DOCTYPE — no regression.

## Step 5 — P1.1 local-first by default (commit `ec9fd6e`)

**What.** Runtime gate `src/llm_clients.ollama_base_url()`: classifies the configured host (loopback, RFC1918/link-local/ULA IPs, docker host aliases, single-label k8s service names, `*.svc`/`*.cluster.local`/`*.internal`/`*.local`/`*.lan`/`*.home.arpa` are local; public DNS names or IPs are remote) and raises `LLMError` *before* any request object is built unless `ETIQTECH_ALLOW_REMOTE_LLM=1`. All three Ollama call paths and the `/api/ollama-models` proxy use it. Startup: ERROR when remote and not allowed (LLM refused, linter still works), WARNING when remote and allowed. `/api/health` adds `llm_local`, `llm_remote_allowed`. k8s: `ethicchecker.yaml` now targets `http://ollama:11434`; new `ollama-local.yaml` (Deployment/Service/PVC, `app=ollama` to match the existing NetworkPolicy); cloud config moved to `k8s/overlays/remote-llm/` as a strategic-merge patch with a loud header; secret template moved with it, `.gitignore` updated; `k8s/README.md`. README + SECURITY.md reworded to "when configured with local Ollama (the default)". 21 new tests (`tests/test_local_first.py`).

**Decision.** Env flag over a config field (brief left it open): the deployment surface is env-only today (Dockerfile, k8s), so a flag is the smallest informed-consent mechanism that shows up in a manifest diff. Fail-closed on an unparsable URL. Known limit, documented in code: classification is by hostname, not by resolved IP (DNS rebinding is out of scope for a same-operator threat model). Noted in passing: the shipped NetworkPolicy already blocked egress to ollama.com, so the old manifest was contradictory as well as leaky.

## Step 6 — P1.2 PRIVACY.md + canary (commit `e6bffde`)

**What.** `PRIVACY.md`: five guarantees (no disk; ~1h in-memory TTL; no protocol text in logs at any level; local LLM by default with explicit opt-in; no accounts/tracking), what is not covered, an enforcement table, the metadata-only future feedback store, verify-it-yourself commands. `tests/test_privacy_canary.py`: plants `CANARY-<uuid>` in every free-text field of a fixture and in the raw HTML (institution string), runs parser → linter → renderer → Layer 2 stream + batch → Layer 3 stream + batch → Flask API (both analyze routes, both SSE routes, an error path), at DEBUG, LLM mocked to echo the marker; asserts marker absent from caplog, stdout, stderr (fd-level via `capfd`). A fourth test proves the harness catches a deliberately leaky provider (`pytest.raises(AssertionError)`).

## Step 7 — P1.3 supply-chain gates + CSP nonce (commit `91d1083`)

**What.** `pip-audit -r requirements.txt` found 6 known vulnerabilities in 5 pins (lxml 6.0.2, pytest 9.0.2, requests 2.32.5, flask 3.1.2, werkzeug 3.1.5); bumped to the fixed versions (6.1.0 / 9.0.3 / 2.33.0 / 3.1.3 / 3.1.6), re-audit clean, suite green. CI: new `audit` job (`pip-audit --strict`), bandit gate made explicit (`-ll`, medium+ fails; all current findings are Low B105/B106 false positives on the `blind`/`reconcile` pass names). `dependabot.yml` already existed (brief thought it missing) — added the `docker` ecosystem for the digest-pinned base image. CSP: `script-src 'self' 'nonce-<per-request>'` replaces `'unsafe-inline'`; the single inline `<script>` (Tailwind config in landing.html) carries the nonce; styles keep `unsafe-inline` for Tailwind's runtime styles. `tests/test_security_headers.py` (2 tests). SECURITY.md updated.

**Decision.** Went for the CSP nonce now rather than deferring: the repo has exactly one inline script and zero inline event handlers, so the cost was ~15 lines.

**Review (P1.1, Sonnet).** SHIP WITH FIXES, applied in `f868a1a`: (HIGH, agreed) `requests` follows redirects, so a compromised/misbound local Ollama could 302 the protocol POST plus `OLLAMA_API_KEY` to a public host with the gate never seeing the real destination — `allow_redirects=False` on all four calls, test asserts it. (MED) `.internal` is not in IANA's special-use registry (checked live by the reviewer) — wording softened to "convention". (MED) README/SECURITY linked to a PRIVACY.md that did not exist *at that commit* — it landed in the next commit (`e6bffde`). (LOW) the gate's error text carried the literal `OLLAMA_BASE_URL` into theme fallback rationales visible in the browser — URL now logged server-side only. (LOW) syntactic-check limit documented. Reviewer confirmed: IPv4-mapped IPv6, zone ids, userinfo tricks and suffix-substring tricks all classify correctly; `kubectl patch` defaults to strategic merge for Deployments and the env list merges by name; the NetworkPolicy still blocks the overlay as its header says.

## Step 8 — P1.4 advisory framing (commit `737e831`)

**What.** One constant `server/app.ADVISORY_NOTICE` ("Advisory only: LLM findings (Layers 2 and 3) are generated by a language model, can be influenced by the protocol's own wording, and do not replace review by the ethics committee." — wording reserved for the maintainer, decision #2) rendered into the Layer 2 progress card (outside the collapsible body), the Layer 3 progress card, the Layer 3 results panel, the LLM detail panel (JS reads it from the template so there is one wording), and a print-only footer on every exported report. No close button; `.advisory-banner[hidden] { display:block !important }`. `tests/test_advisory_banner.py` asserts the four placements, that none sits under `llm-progress-body`/`layer3-results-body`, and the CSS guard. Suite 484 passed.

**Review (P1.2 + P1.3, Sonnet).** P1.3 SHIP (CSP nonce verified on 200/404/static/429 paths; tailwind.js has no eval/new Function; every cache mutation is under the lock; pins effective; `pip-audit --strict` and `bandit -ll` both green live). P1.2 SHIP WITH FIXES, applied in `fb89ffe`: the canary never exercised `parse_llm_json`'s ValueError (embeds up to 300 chars of raw LLM response — reaches the UI fallback rationale, must never reach a log), its "error path" never actually errored (a bare `<html><body>` parses fine), and the self-check proved only caplog. Three tests added; suite 492.

## Step 9 — P2 corpus: Israeli guidance sectionized (commit `72ce96e`)

**What.** `scripts/build_law_corpus.py` → `resources/corpus/guidance_il.jsonl` (89 records; 46 EN from the markdown-ish headings incl. merged wrapped headings, 43 HE from a clean `pdftotext` extraction; ≤1600 chars per chunk; brief's schema + `lang`, `section_path`, `source`). Committed; `tests/test_law_corpus.py` rebuilds and fails on staleness, checks unique stable ids, schema, chunk bounds, Hebrew logical order ("בשנת 1994 חוקקה כנסת ישראל" present — the old file has the words reversed), merged headings, and that key topics (alternatives search, severity classification, euthanasia, N justification, analgesia) are retrievable units.

**Findings for the maintainer.** (1) `the_law-english_translation.txt` is the Council's explanatory guidance for the request form (the same document as the 2025 PDF), not the 1994 statute. The statute text is not in the repo; "law grounding" has been guidance grounding all along. (2) `the_law.txt` is a word-reversed extraction of the same PDF; not used by any code; flagged for removal, not deleted (rule 2). (3) No public URL is known for the guidance PDF, so records carry a local `etiqtech://` anchor; license field says "government publication; terms unverified" rather than guessing.

**Review (f868a1a + 737e831, Sonnet).** SHIP WITH FIXES on both, applied in `c3cce8f`: `/api/ollama-models` used `raise_for_status()` which lets a 3xx through (now explicit `!= 200`, and a 302 test drives all call paths); one advisory test assertion was vacuous (`js.split("advisoryNotice")[0]` truncated at the first *call*, leaving a 20-char fragment) — replaced by a per-line scan of app.js for any remove/hide near "advisory"; `html.parser` does not know void elements — ancestor check now uses lxml; the JS fallback wording (a second copy of the notice) removed. Reviewer confirmed: on every UI transition a visible advisory accompanies any visible LLM verdict; in print, the panels are hidden but the print footer survives; dark theme unaffected (hardcoded colours).

## Step 10 — P2 retrieval engine decision (studied before building)

Maintainer decision #4 (LightRAG vs simpler store) is reserved, so the engine is built behind a tiny interface and the recommendation is recorded here rather than assumed:
- Corpus today: 89 chunks; NORINA later: thousands of short records. Hard requirements: metadata filter (`species`, `doc_type`), multilingual embeddings (Hebrew query → English record), fully local.
- Measured locally: `qwen3-embedding` (7.6B, 4096 dims) via Ollama `/api/embed`; cosine(EN question, its Hebrew translation) = 0.842 — cross-lingual retrieval works out of the box.
- LightRAG needs an LLM pass per chunk for entity/relationship extraction (graph build) — with the 27B at ~6 tok/s that is hours per refresh and it adds a heavyweight dependency, for a corpus whose retrieval need is "find the 5 guidance sections about X for species Y". Recommendation: **plain embedding index with metadata filter + lexical fallback**, zero new Python dependencies, index cached on disk under `output/` (gitignored — embeddings are model-specific). Swap point: `src/retrieval.Retriever` (one class, `search(query, k, filters)`). If graph traversal ever proves necessary (e.g. NORINA cross-references), LightRAG slots in behind it.

## Step 11 — P2 retrieval layer (commit `3b67301`)

**What.** `src/retrieval.py` (Retriever: embeddings via Ollama `/api/embed`, metadata filters, disk cache, BM25-lite fallback, 60s failure cooldown, never raises), `THEME_GROUNDING` in `llm_agent` (per-theme queries + doc_type filters, k=5), grounding block replaces the fixed law prefix when `ETIQTECH_GROUNDING=1`, `[Gn]` citations requested, `grounding` refs on every theme result (contract extended: `GroundingRef`, `grounding_notice`), one SSE warning when degraded, UI sources in detail panel + print (escaped; only http(s) links). 11 tests with a deterministic hashing embedder. Suite 504.

**Decisions.** Off by default until the eval gate (brief §6.3: "if grounding doesn't beat the baseline, report it and stop"). Lexical fallback on purpose: a keyword-matched guidance section with a visible "degraded" notice beats silently reverting to the 1,200-char prefix. Smoke test with a dead embed endpoint: lexical search returned the "manner of search for alternatives" sections for the English query and the Hebrew "תהליך חיפוש חלופות" section for the Hebrew query.

**Review (72ce96e + fb89ffe + c3cce8f, Sonnet).** SHIP WITH FIXES on all three, applied in `39f396f`: (HIGH) the Hebrew normalizer corrupted URLs and Latin spans in committed retrieval text ("https: //eurl-ecvam. jrc…", "()EURL ECVAM") — URLs/Latin runs are now stashed before the RTL rules and the mirrored `)(Latin` pattern is fixed explicitly; (HIGH) `# Part C` swallowed `## The Principal Investigator` — merges now require the same heading level, regression test added; (MED) Hebrew ids were positional → sha1(chunk)[:8], plus `source_sha256` provenance on every record; README table row corrected; canary asserts `exc_info` per route (the reviewer proved the old `any()` passed with one route broken); banner scan follows identifiers across the file; two-step redirect test. Confirmed clean: determinism, no fixture text in the corpus, `pdftotext` optional in CI.

**Eval-gate design note.** Measured on this machine: qwen3.6:27b ≈ 6 tok/s (a blind theme call ≈ 100–190 s), gemma4:e4b ≈ 25 tok/s. Machine has 34 GB; both fit. Full golden A/B on the 27B (20 testable cases × 2 variants × ~3 target themes × 2 conditions ≈ 240 calls) ≈ 9 h — the harness is written to be resumable so the maintainer can run it overnight on the production model; the in-session result will be a smaller sample and labelled directional. Golden coverage finding: `three_Rs_alternatives` is a target theme in only 3 of 28 cases (harm_benefit 17, severity 16, euthanasia 16), so the brief's "documented gain on three_Rs" cannot be statistically strong from this dataset alone.

**Follow-up (commit `b593a54`).** The `(EURL ECVAM)` repair ran before the global parenthesis swap, which undid it; order fixed (swap → fix `()Latin` → protect Latin/URLs → Hebrew rules). Suite 507. `scripts/eval_grounding.py` written (resumable JSONL, `--report` renders `docs/benchmarks.md`); not yet run — waiting for the presence_penalty A/B to release the GPU (11/72 at this point).

## Step 12 — P3.1 rule registry: design (studied before touching the 3,200-line linter)

Inventory: 64 `_rule(...)` call sites inside one 2,100-line `lint()`; every check already carries a `ref` of the form `domain:name`, with per-experiment instances suffixed `:exp-{idx}` and one dynamic family `required:{path}`. Three severity classes exist as sets (`STRUCTURAL_REFS`, `LAW_CRITICAL_REFS`, `ADVISORY_REFS`). The golden dataset's ground truth (`bad_expected_l1_refs`) and many tests are keyed on these exact strings.

Decision: **the existing refs become the stable rule IDs** (`rule_id = ref` with the instance suffix stripped). Renaming to an `ET-ANIM-004` scheme would break the golden ground truth and dozens of tests for no functional gain; the refs are already short, grep-able and namespaced by domain. What is added: a registry (`src/rules.py`) with one entry per rule (id, domain, class, jurisdiction, title), a `rule_id` on every checklist item, a `ruleset_version` on the report, the ID in the UI detail panel and print, a generated `docs/rules.md`, and tests that (a) every ref the linter emits across all fixtures is registered and (b) every registered rule fires on at least one fixture. Moving check bodies into per-domain modules is the risky half; it stays a follow-up done in small batches if time allows, never mixed with behaviour changes.

**Review (3b67301 retrieval, Sonnet).** SHIP WITH FIXES, applied in `64ca1ed`: (1) `href` built with the text-node escaper (quotes unescaped) — attribute breakout possible once external URLs enter the corpus; CSP would block script execution but not attribute rewriting → `escapeAttr`. (2) Cache key ignored `title` although title is embedded → stale vectors after a heading edit. (3) Non-atomic cache write across processes → temp file + `os.replace`, torn files rebuilt. (4) Norm recomputation → cached; numpy threshold documented (~2k records; JSON float cache becomes the bottleneck first). (5)–(7) shape guards, flag read once per review, and a vacuous `or True` assertion removed. Confirmed by the reviewer: no protocol text reaches the cache or the embed endpoint (queries are theme constants; species is an in-memory filter), embed calls go through the gate with no redirects, reconcile prompts receive the same hits as blind.

## Step 13 — P3.1 rule registry, step 1 (commit `592aa81`)

**What.** `src/rules.py` registers all 62 rules (id = existing ref, domain, kind from the linter's severity-class sets, first-pass jurisdiction tag IL-form/generic, title). `lint()` annotates every checklist item with `rule_id` and the report with `ruleset_version` (contracts extended). UI detail panel + print show the id. `docs/rules.md` generated with fixture coverage; tests: normalization, registry integrity vs the three ref sets, staleness of the doc, and a per-fixture parametrized test (94 files × 2 profiles) that every emitted check is registered. Suite 608.

**Finding.** 27 of 62 rules never appear on any fixture (they only emit on failure and nothing trips them): the 3Rs rules (`alts:*`), `N:*`, `sex:*`, `colony:*`, several euthanasia rules. The golden dataset does not exercise them; per-rule noise tracking (P3.5) and any rule refactor need fixtures for them first.

**Not done (deliberately).** Moving check bodies out of the 2,100-line `lint()` into per-domain modules — the risky half of P3.1. The registry gives every downstream consumer (citations, suppression, feedback keys, jurisdiction packs) the stable key now; the module split can follow in small batches with the 608 tests as the invariant.

## Step 14 — P3.4 provider abstraction (commit `c5287c3`)

**What.** `PROVIDERS` registry + `gated_base_url()` (the local-first gate now covers every provider's base URL), dispatch in `call_llm`/`call_llm_stream`, OpenAI-compatible adapter (requests; SSE chunk parsing; `OPENAI_JSON_MODE` opt-in), Anthropic adapter via the official `anthropic` SDK (optional extra), `/api/llm-providers` + UI provider list, `docs/providers.md` capability matrix, 12 contract tests with recorded responses. Suite 620.

**Decisions, studied first (claude-api skill loaded).** Official SDK for Anthropic rather than raw HTTP (skill rule; never mix). Default model `claude-opus-5` (skill mandate). No `temperature` sent to Anthropic — current models return 400 on sampling params. Did **not** enable the skill's suggested server-side refusal `fallbacks`: silently re-running an ethics review on a different model is the opposite of the advisory-transparency stance, so a refusal surfaces as a per-theme LLM error instead. OpenAI-compatible adapter has no default model on purpose (I do not reliably know current OpenAI model names; guessing one would ship a wrong default). Anthropic is always remote → usable only with `ETIQTECH_ALLOW_REMOTE_LLM=1`; UI shows it disabled otherwise.

**Review (64ca1ed + 592aa81, Sonnet).** SHIP WITH FIXES on both, applied in `9e04573`: a valid-JSON cache of the wrong shape raised `TypeError` past the "never raises" contract (shape check moved into `_set_vectors`; `scripts/eval_grounding.py` would have crashed on it); `cosmetics:ban` tagged IL-form although the ban is EU/US-state/Indian law too, and `permits:field-study` checks CITES (international) — both retagged `generic` before any pack split uses the tags; tmp file leak on replace failure; dead `_cosine`; my commit message said 62 rules, the registry has 59 (10 structural + 22 law_critical + 26 advisory + 1 required — an exact bijection with the three ref sets). Reviewer confirmed: registry complete against all 63 `_rule` call sites, `kind` consistent with the sets, no pre-existing test file modified since `fe3cb01`, doc generation deterministic (~0.9s), nothing touches invariant 4.

## Step 15 — P3.5 metadata-only feedback loop (commit `a62cd84`)

**What.** `src/feedback.py` (stdlib SQLite, allowlisted schema: kind, key, verdict, ruleset_version, profile, UTC timestamp; `validate()` rejects unknown fields and unregistered keys), `POST /api/feedback` (30/min) + `GET /api/feedback/report`, `ETIQTECH_FEEDBACK=0` kill switch, `scripts/feedback_report.py`, thumbs in the detail panel per lint issue (by `rule_id`) and per LLM theme (event-delegated for CSP, hidden in print). Canary extended: after a marked review with feedback on every failing finding, the DB bytes must not contain the marker; a smuggled `note` field is a 400. PRIVACY.md now describes the one stored thing. Suite 633.

**Decision.** The store is the brief's sanctioned exception (7.5) and lives under `output/` — the container's only writable path, an `emptyDir` in the reference k8s manifest, so it is ephemeral until the maintainer mounts a volume; documented rather than adding a PVC unasked (decision #5 territory).

**Review (c5287c3 P3.4, Sonnet).** SHIP WITH FIXES, applied in `6e00a43`: (HIGH, reproduced by the reviewer against anthropic 1.4.0) the SDK client follows redirects by default — the one adapter carrying prompts to a remote host was the one not covered by the no-redirect rule → `DefaultHttpxClient(follow_redirects=False)`, test asserts the real client's attribute; (MED-HIGH) mid-stream `{"error": ...}` events from OpenAI-compatible gateways were swallowed and the truncated text became an "inadequate" verdict indistinguishable from a real finding → raised as `LLMError`; (MED) `call_llm_two_step` ignored the per-request provider (UI choice replaced by env default) → `provider=` threaded through all four call sites; (MED) `resp.text[:300]` could reflect a gateway's echo of the request into the browser → server log only; Anthropic failures now logged server-side before sanitizing. Honest caveat recorded: the Anthropic fake proves kwargs and control flow, not the live SDK; only construction (`follow_redirects`) is tested against the real package.

**Review (9e04573 + a62cd84, Sonnet).** a62cd84 **BLOCK** — correct call. `profile`/`ruleset_version` were type+length filtered (≤32 chars), so a raw POST could persist 32 bytes of protocol text in the one file the app writes, while PRIVACY.md claimed an allowlist. Fixed in `398ef47`: `profile ∈ {default, strict_law}`, `ruleset_version ∈ {RULESET_VERSION}`; canary plants the marker in both fields and expects 400; `feedbackGiven` UI state reset per analysis (was per session); connections closed. 9e04573 SHIP WITH FIXES: the "never raises" guard still let `[["a","b"]]` through to a `TypeError` → element-numeric + equal-length check and `TypeError` in the loader's except. Reviewer agreed with both jurisdiction retags.

## Step 16 — P3.3 canonical schema + adapters (commit `20ef270`)

**What.** `docs/schema.md` generated from `src/schema.py` (types, required, `x_meta` meaning/expected/examples, field rules) with a **measured conformance section**; `src/adapters.py` (registry; `il-council-html` reference adapter; `canonical-json` with strict jsonschema validation whose errors name paths and allowed sets, never values; `ingest()` by extension or detection; `schema_skeleton()`/`item_skeleton()`); both analyze routes accept `.json` uploads and `{"instance": ...}` bodies and report the adapter; `docs/adapters.md`; `examples/adapters/minimal_adapter.py` (validates, lints, exercised by tests). Suite 647.

**FINDING FOR THE MAINTAINER.** The reference adapter's output validates against the published schema on **0 of 94 fixtures** (1,091 violations, 13 classes): the Council export carries Hebrew enum values (`נקבה`/`לא חשוב` for sex, `גרם`, `שבוע`, `המתה`, `מקור חיצוני`) where the schema declares English enums; `summaries.lay_he_≤150w` is required but never produced; analgesia timing `unknown` is not in the enum. The linter is written against the parser's actual values (and, as a side effect, `analysis.summary.single_sex_design` compares against `{"M"}`/`{"F"}` — so it is always False on real exports). Options: normalize in the parser (behaviour change; touches tests), or widen the schema to the bilingual reality. Not changed here — it alters review behaviour. A third-party adapter following the schema literally is valid but feeds different vocabularies than the reference adapter; documented in `docs/adapters.md`.

## Step 17 — P3.2 step 1: pack mechanism + EU spike (commit `6a173f9`)

**What.** `PACKS` in `src/rules.py` (IL = default = today's behaviour; generic = welfare/science rules only, `writing_quality` skipped, counters recomputed, `rules_outside_pack` reported), selected by `ETIQTECH_JURISDICTION`. `docs/eu-directive-spike.md`: Directive 2010/63/EU (read from EUR-Lex consolidated text and Annex VIII on legislation.gov.uk) mapped article by article to existing rule ids and gaps; IL 1–5 → EU four-category mapping proposal; five seed EU rule candidates; Annex IV vs AVMA 2020 conflict named. Suite 654.

**Decision.** Stopped exactly where the brief says a human must step in (decision #6): no EU rule implemented, no EU pack registered, no synthetic EU fixtures — the spike is the artefact for the maintainer to review first. The pack mechanism itself is data + a post-filter on the report; it never touches LLM output (invariant 4) and it extracts Israel as the first pack without moving a single check body.

## Step 18 — P4 dev items (commits `8449d66`, `9ce976b`)

**What.** `docs/prepare-mapping.md` (PREPARE's 15 topics → rule ids/themes with coverage judgements; gaps: quarantine/health monitoring, necropsy, randomisation/blinding, waste/decontamination, harm-benefit as a structural field; CC BY 4.0 attribution and paper citation). Linter-only mode `ETIQTECH_LLM_DISABLED=1` for a public demo without GPU (server + UI + tests). README: mermaid architecture diagram, demo section, acknowledgements skeleton with wording left to the maintainer (decision #2), env rows. Suite 656. Not done from P4: demo GIF and social preview (need a browser/screen capture), i18n string extraction (deferred — a large UI change late in the session; flagged for the maintainer), public demo deployment (maintainer's infrastructure).

**Review (6e00a43 + 398ef47 + 20ef270, Sonnet).** 6e00a43 **BLOCK** — correct, and mine to own: fixing the "error body reaches the browser" finding, I had moved the bodies into server logs at WARNING, which violates PRIVACY.md guarantee 3 verbatim ("never request bodies or LLM responses"); the existing canary could not see it because it patches `call_llm*`, above the HTTP layer. Fixed in `77158b0`: logs carry status codes and error-type tokens only; the pre-existing Ollama messages that embedded raw bodies were sanitized too; a new canary patches `requests.post` and the SDK client with a marker-echoing body. 20ef270 SHIP WITH FIXES (applied): `schema_errors` was safe-by-allowlist for known validators but unsafe-by-default for unknown ones (`anyOf`, `uniqueItems`, `additionalProperties` messages embed the value) — now whitelist-only with a generic fallback and a keyword-sweep test; `RecursionError` on 20k-deep JSON was an opaque 500. 398ef47 SHIP. Lesson recorded: every "move it to the log instead" fix has to be checked against guarantee 3 — the log is not a safe place for anything a provider returns.

## Step 19 — P0.3 presence_penalty A/B result (commit `1c4b295`)

72 calls, qwen3.6:27b-mlx, 4 protocols × 3 themes × 3 penalties × 2 repeats (~2.6 h of GPU). **Keep 1.5**: 0% parse failures and 0% score flips vs 8%/9% at 0.0; gap +0.17 vs −0.35. The brief's hypothesis (1.5 penalises repeated JSON keys) is not supported on this model. The larger finding: the blind pass does not discriminate good from bad on `N_and_justification` (0 everywhere) or `three_Rs_alternatives` (1 everywhere); only `writing_quality` moves, noisily. Written to `docs/benchmarks.md` with the caveats (small n, non-production model). The grounding eval (`scripts/eval_grounding.py`) is ready to run against this baseline; not started yet — GPU is now free.

**Pause requested by Razy at this point** (mid-turn message: "can you pause when ending this phase and explain what you did?"). Two Sonnet reviews still in flight: 6a173f9 (packs + EU spike) and 9ce976b + 77158b0 (demo mode; privacy log fix).

## Step 20 — resume (Razy: "keep running") — review follow-ups + resume anchor

**Standing instructions added by Razy.** (1) A **design task** — make the product super easy and self-explanatory for non-technical people — scheduled near the end of the sprint. (2) Documentation built along the way with each commit so a compacted session loses nothing → `docs/dev-log/STATUS.md` created as the resume anchor (standing instructions, invariants, phase checklist with commit hashes, open maintainer findings, how to resume, next steps); updated with every commit from here on.

**Reviews applied (6a173f9 packs; 9ce976b demo; 77158b0 privacy).** Completeness rules `header`/`research`/`pi`/`required` retagged `generic` — an empty upload reported "pass" under the generic pack (regression test added). `/api/ollama-models` gated by the linter-only switch. Canary's Ollama fixture was OpenAI-shaped so the Ollama hint path was never exercised — the fake now alternates flat-string and dict bodies and every provider call runs twice. Decision on the 120-char Ollama `error` pass-through: **dropped** — status code only, same as the other providers; a server controls that field and LLMError text can reach the browser. Legacy `mode="single"` RuntimeError now carries the exception type only (kept, since pre-existing tests exercise the path). EU spike Art. 16 row corrected (further procedure may be mild, moderate **or non-recovery**; exceptional reuse after severe with authority approval, Art. 16(2)). The two pre-existing linter counting bugs (`term:track`, `title:pilot-label`) are logged as maintainer findings, not fixed — behaviour changes.

## Step 21 — ULTRACODE mode (Razy: "use ULTRACODE to keep on running; opus mostly, fable for bigger tasks, sonnet for smaller")

Switched substantive tasks to Workflow orchestration with model tiers. Launched: (1) `review-5afa4fc` — three Sonnet lenses (correctness, security, docs) with two-skeptic adversarial verification per finding (the plain Sonnet review of that commit had died on a session rate limit, reset 16:00 Jerusalem); (2) `design-nontech-ux` — grounding reader (Opus) → three independent designers (minimal-change / guided flow / report-first, Opus) → three judges each (researcher, maintainer, committee; Opus) → Fable synthesis into `docs/design/spec.md` with a commit plan. The grounding eval subset (`scripts/eval_grounding.py --limit 6`, qwen3.6:27b) is running on the GPU meanwhile; embedding index built (5 MB cache).

**Workflow review of 5afa4fc (3 Sonnet lenses, 2 skeptics per finding).** 2 findings, both confirmed by both skeptics, none refuted, both low: the canary's flat-string/dict alternation was dead weight (a 400 raises before `.json()` is ever called — the skeptics instrumented it: 8 posts, 0 json calls) and `_ollama_error_hint` was a no-op at four sites. Fixed in `f71c98a`: helper deleted, status-only messages inline, and the canary's error fixture now *fails* if any provider path ever parses or streams a non-200 body. Honest note: my previous commit message claimed the alternation exercised both shapes; it did not.

**Review (f71c98a, Sonnet).** SHIP. Adjacent gap it flagged (pre-existing since 6e00a43): the mid-stream error `type`/`code` was echoed (60-char cap) into a log line and the error text — a provider-controlled field. Fixed in `b9b80d7` with a whitelist of known error types; canary now plants the marker in `type`, `code` and `message`.

**Review (b9b80d7, Sonnet).** SHIP; exhaustive grep of logger/LLMError sites in the four LLM modules found them clean. Adjacent pre-existing item fixed in `17d67ba`: non-JSON model output was previewed (200–300 chars) inside ValueErrors and reached the UI as fallback rationale text and Layer 3 stream tokens. Not a privacy breach (same user, same call) but raw model text dressed as a finding; now error type only, with the canary asserting on stream content, not just logs.

**Review (17d67ba, Sonnet).** SHIP WITH FIXES: confirmed the removed previews were an API-response exposure (fallback rationale is rendered as a finding), not a logging one, so `type(e).__name__` is the only safe form; the token assertion relied on the fixture wording not containing "error" → replaced by a full-shape match in `72829b7`.

## Step 22 — P3.1 module split, executing (workflow `linter-module-split`)

Plan (`docs/dev-log/linter-split-plan.md`, from the map workflow) accepted as the contract. Pre-split snapshot taken (188 reports, reproducible with an empty diff). Workflow: Fable executor per batch (verbatim moves into `src/lint_rules/`, pytest 660 + `diff -r` snapshot must be empty, one commit per batch, `git checkout -- src/` and STOP on an untraceable diff), Opus verifier per batch (pure-move check: strings/refs/severity/counter placement byte-identical, `_rule(` count unchanged, `src/rules.py` and tests untouched, §5 quirks preserved). Halts on the first non-ok verdict. `docs/design/plan.md` committed alongside (design task plan for Razy's review; the judge-panel workflow is producing the spec).

## Step 23 — design task, executing (workflow `design-ux-implement`)

Judge-panel outcome: minimal-diff 90, report-first 90, guided flow 89 → Fable synthesis `docs/design/spec.md` (committed `3af9372`). Key design decision the judges converged on: finding priority is a pure function of `(severity, rule kind)` — three tiers: FAILS THE CHECK / LEGAL REQUIREMENT / WORTH FIXING — because the web UI lints the `default` profile only, where law-critical rules fire as warnings 253 times vs error once across the fixtures. Headline pattern "Requirement not met: <registry title>" makes all 59 satisfied-condition titles read correctly on a failure without rewriting them. Nine commits (~22 h), Python touched only in commit 3 (rule_title/rule_kind on checklist items). Executing in a separate worktree `../EtiqTech-design` (branch `design-ux`) because the split workflow owns the main tree; Fable executor + Opus verifier per commit, halts on the first failed verification. Commit 8 (landing Hebrew drafts) stays on the branch until Razy reviews the Hebrew (spec §8.3).

## Step 24 — three more large workflows (Razy: "send now large workflows for next action — ULTRACODE")

Running concurrently with the split and design workflows and the eval (26/72):
1. `sprint-audit` (read-only): six Opus lenses over everything since `fe3cb01` (privacy, security, correctness, test quality, docs accuracy, invariants 4/5), loop-until-dry, three skeptics per finding (reproduce / by-design? / impact), Fable report → to become `docs/dev-log/sprint-audit-2026-09-05.md`.
2. `rule-coverage-fixtures` (worktree `../EtiqTech-coverage`, branch `rule-coverage`): six Fable crafters write synthetic canonical-JSON fixtures for the 27 never-firing rules, Opus verifies each fires the named rule and validates, one wiring commit adds `tests/test_rule_coverage.py`, `examples/coverage/README.md` and extends `docs/rules.md` coverage counts.
3. `research-statute-and-layer3` (read-only, web): where the 1994 statute and its rules are published (Hebrew/English, licensing) and a measured breakdown of the Layer 3 prompt with three designs to fit 24k tokens → two memos for Razy's decision.
Split progress meanwhile: batches 0–3 landed on main (RuleContext, summaries/colony, specialty/misc, husbandry), each snapshot byte-identical.

## Step 25 — session limit hit and reset; eval result; workflows resumed

**Rate limit.** The session limit hit at ~18:30 and reset at 21:00 (Jerusalem). Every workflow lost its in-flight agents; completed agents are cached, so all five were resumed from their run ids. State at the pause: split batches 0–4 landed on main; design commits 1–3 landed on `design-ux` (commit 4 was mid-edit — worktree reset with `git checkout -- .` before resuming); 23 coverage fixtures crafted but unverified/uncommitted; audit and research had produced nothing yet.

**P2 eval gate — result (commit `bf331e4`).** 72/72 calls, 6 golden pairs. Grounded rationales cited retrieved sections 100% of the time, but pair accuracy 6% → 0%, gap +0.06 → +0.00, latency +17%. Baseline finding: the model scores nearly every theme 0–1 on good and bad alike (good_clean 6%), so the eval measured the model's ceiling, not the grounding. **Decision per the brief's exit criterion: `ETIQTECH_GROUNDING` stays off by default**; retrieval, corpus and citation UI stay in the tree as opt-in; rerun conditions written into `docs/benchmarks.md` (production model, all 20 pairs, two-pass flow, and first a model that separates good from bad at all).

**Workflow `rule-coverage-fixtures` — done (branch `rule-coverage`, commit `9a6648b`).** 23 synthetic canonical-JSON fixtures under `examples/coverage/` (six Fable crafters, each fixture independently verified by Opus to validate against the schema and to make its named rule emit a failing checklist item under at least one profile; synthetic names only), `tests/test_rule_coverage.py` (23 parametrized + a COVERED-set guard), `examples/coverage/README.md`, `gen_rules_doc.py` coverage now includes JSON fixtures → "never appear" list 27 → 4. The four remaining (`header`, `research`, `pi`, `required`) are unreachable from canonical JSON by construction: the schema's `required` lists are identical to what the checks test, so `parse_canonical_json` rejects the instance before `lint()` runs; they fire only via the HTML parser path (an HTML fixture with a missing block would cover them — maintainer's call whether a deliberately broken export is a fixture worth keeping). Merge deferred until the split finishes: the split executors are instructed to expect exactly 660 tests.

## Step 26 — split complete, branches merged (Razy: "merge the branches when the split is done and keep going")

**P3.1 module split — done.** Batches 0–7 landed on main (`9f90148` … `35856f3`), each verified by an independent Opus agent as a pure move with a byte-identical 188-report snapshot. `lint()` is now a RuleContext build, the module `run()` calls in source order (`src/lint_rules/`: context, helpers, header, animals, alternatives, endpoints_pain, euthanasia, husbandry, specialty, misc_exp, colony, summaries) and the unchanged report assembly. The four counting quirks from plan §5 are preserved exactly (fixing them is a separate maintainer-approved change). Batch-0 verifier flagged that the explicit `packages` list left `src.lint_rules` out of the wheel → fixed in `75bd40c`, verified in a clean venv.

**Merges.** `rule-coverage` (fast, clean) then `design-ux` commits 1–4 (one conflict: the generated `docs/rules.md`, resolved by regenerating). Post-merge: 684 passed; snapshot re-baselined (design commit 3 adds `rule_title`/`rule_kind` to checklist items, additive) and reproducible; schema/corpus/rules docs all current; Bandit medium+ clean after `cede04c` (two findings of mine: f-string SQL shape in feedback.py, inline timeout expression in retrieval.py). The design workflow continues on `design-ux` (commits 5–9); it will be merged again when done.

**Standing instruction (Razy, mid-turn): workflows use at most 15 agents, mostly Sonnet.** He stopped `sprint-audit` at ~110 agents (6 lenses × loop-until-dry × 3 skeptics per finding was the wrong shape at this scale). I stopped my own uncapped `review-split-and-merge` before it grew and relaunched it capped: 4 Sonnet reviewers (≤4 findings each), the 11 most severe findings verified by one Opus skeptic each, 15 agents maximum. The sprint-wide audit is not re-run; the capped split/merge review covers what changed since the earlier per-commit reviews.

**Split workflow final report.** All 8 batches `ok=true` from the independent verifier; every note non-blocking: module names follow the package layout rather than the plan's `rules_*.py`; four modules expose two entry points to keep checklist row order where another domain's block sits between theirs (verifier confirmed each against source order and the empty snapshot diff); the plan header cited the wrong baseline commit (cdfc44f vs the real pre-split parent d972ecc — the verifier regenerated an independent baseline from d972ecc and it matched); one 17-space indent and one dead `primary =` assignment were moved verbatim on purpose. Dead imports left in `linter_renderer.py` removed in the follow-up commit. Pre-existing linter counting quirks (plan §5) confirmed preserved in the moved code.

## Step 27 (2026-09-06, after the 02:00 limit reset) — merges, capped review, memos

**Design commits 5–6 merged** (progress/status strings in plain language; the finding card: tier chip, "Requirement not met: <title>", what/why/what-to-change, rule id line, thumbs). `rule_title`/`rule_kind` are now read by the UI, which retires one review finding. Commits 7–9 (summary node, landing copy, START-HERE) resume on `design-ux`.

**Capped review (`review-split-and-merge-capped`, 4 Sonnet lenses).** Six findings; the Opus skeptics died on the limit, so I verified them myself: (1) `title:pilot-label` severity/counter mismatch and (2) `required:*` counted in no category — both real, both pre-existing, both already on the maintainer list as behaviour changes (plan §5); not touched. (3) docs claimed `rule_title`/`rule_kind` reach the UI before the UI read them — true at the time of the review, resolved by design commit 6. (4) coverage README cited line numbers the split moved — fixed. (5) Ollama model `<option value>` used the text escaper — fixed (`escapeAttr`). (6) coverage test docstring overclaimed isolation — fixed. Commit `67a4cb9`.

**Research memos (7 agents, verified by a cross-check agent).** `statute-sources.md`: the statute and the 2001 rules are not in the repo in any language; Hebrew primary text exists as Reshumot scans (Knesset file server) and consolidated on WikiSource (CC BY-SA) with the 2024 rules amendment (online submission with 11 mandatory items); no official English translation exists and the private ones all descend from one translation; Nevo mirrors carry restrictive terms; the Layer 3 prompt's "cite Israeli Law Art. N" instruction is answered from model memory today because the prompt contains only form guidance. `layer3-context-options.md`: measured breakdown of the 27.7k-token prompt (the guidance block alone is 10,640 tokens), three designs, num_ctx cost, ranked recommendation for Razy to decide.

**Review (design merges 5a997dd + ec0ea8e, and 67a4cb9; Sonnet).** SHIP on all three: every status string and finding-card element matched the spec verbatim (tier table, four why-strings, headline rule, card order, thumbs bound once), every new interpolation escaped for its context, print block keeps "Human Eye Review (Layer 3)", advisory rendered exactly 4×, zero files under `src/` touched, memos' verified/unverified markers consistent. Two low notes deferred until design commits 7–9 are merged (both live in files that workflow is editing): `server/templates/index.html` (orphaned, no route) still carries the deleted Layer-3 button — whether to delete the file is the maintainer's call; three `layer3StatusText.textContent = escapeHtml(...)` sites double-escape harmlessly — drop the escaper on textContent.

## Step 28 — design commits 7 and 9 on main; commit 8 held

Design workflow completed 9/9 (18 agents — launched before the 15-agent rule; noted). Commit 7 (`#report-summary`: tiered verdict sentence, static scope sentence, "Start with these", provenance line, print-first) and commit 9 (`docs/START-HERE.md` + README link) cherry-picked onto main (`a568df0`, `3e5a90b`). Commit 8 (landing copy with Hebrew drafts) stays on `design-ux` per spec §8.3 until Razy reviews the Hebrew; its footer link target `docs/START-HERE.md` now exists on main. Commit 9's verifier returned ok=false on three doc inaccuracies (provenance line position, grey-line quote missing the per-experiment reference, singular/plural) — corrected against the live rendering in `55a2510`, together with the deferred textContent double-escape cleanup. START-HERE walk-through executed literally on a linter-only gunicorn: `bad_IL-001-01-2000.html` → pass / 0 errors / 3 warnings, tiers 0/1/2, first fix "Humane endpoints beyond 20% weight loss"; `bad.html` → fail / 1 / 17, tiers 1/16/1 — matches the quoted numbers. Coverage worktree and branch removed (merged). Suite 684.

**Review (a568df0 + 3e5a90b + 55a2510, Sonnet).** SHIP ×3. Verified live: verdict sentences match spec 4.1 word for word on both walk-through fixtures; tiers from `checklist`, not the data-ref map; every innerHTML interpolation escaped for its context; advisory inserted by JS only when LLM results exist; linter-only provenance ends "AI review: not run"; the head-to-head `cosmetics:ban` case reaches the top-3 with the "no section on screen" fallback. Notes: tier-per-rule assumption commented; no JS unit tests exist for the summary logic (verified by acceptance runs only — a JS test runner is out of scope this sprint); the `.advisory-banner[hidden]` rule it queried is the intentional invariant-5 guard.

## Closing gate (2026-09-06, 79 commits since fe3cb01)
684 passed / 2 skipped · Bandit medium+ clean · pip-audit clean · docs/rules.md, docs/schema.md, corpus all current · linter snapshot byte-identical · no original test file modified · Docker image builds and serves (health ok, law loaded, summary node present, no errors in logs).

## Step 29 (2026-09-06) — Razy's four decisions, executed

Asked via AskUserQuestion; answers and actions:
1. **Design commit 8 → English only, drop the Hebrew drafts.** Landed as `74eabdc` with the 10 drafted `data-he` twins removed (toggle shows English there until a native review); branch `design-ux` kept for the drafts, worktree removed.
2. **Statute → Hebrew (WikiSource) + Weizmann English translation.** `scripts/import_statute.py` + corpus extension: 174 records now (89 guidance + 85 law/rules sections); `LAW_PATH` points at the statute translation, so the Layer 2 "law excerpt" quotes the law for the first time; provenance/licence table in `resources/law/README.md` (translation's redistribution terms marked unverified, as agreed). Commits `7e87e5f`, `66d2958`, `f793f2b`.
3. **Layer 3 → raise the Ollama window.** `OLLAMA_NUM_CTX_LAYER3` (default 65536) threaded through `call_llm`/`call_llm_stream` and the context guard; Layer 2 keeps 32k. Commit `a03f31b`.
4. **Fix all four linter counting quirks with fixtures** → next.

**Decision 4 executed — ruleset 1.1.0 (`d9d6a14`).** All four counting quirks fixed; the pre-change snapshot diff was inspected first and contained only the intended changes (188 version bumps, 26 specialty passing-row severity flips), then re-baselined. Two of the fixes (`term:track` out-of-range, `required:*`) cannot be reached from canonical JSON because the schema forbids the inputs, so they are covered by raw-dict tests; `title:pilot-label` got a coverage fixture. New reconciliation test asserts errors/warnings equal the failing rows and the category buckets sum to errors on every fixture × profile. Feedback rows from ruleset 1.0.0 stay valid.

**Review (decision commits a03f31b, statute trio, 74eabdc, d9d6a14; Sonnet).** SHIP on Layer 3 window, landing English-only, ruleset 1.1.0 (all four fixes confirmed trigger-preserving; pilot+4y warning / regular+5y error / regular+3y pass verified; generic-pack recomputation verified by hand across 188 combos — test added). Statute import SHIP WITH FIXES, applied in `fbb6280`: a nested note template leaked into a chapter header and onto rules s.11 (Hebrew); WikiSource category links passed through; the English rules' Schedule placeholder was glued to s.11. All three fixed; corpus has no template residue; CC BY-SA 4.0 URL and changes-made note added. Suite 694.

**Review (fbb6280 + 344583b, Sonnet).** Residue scan of all 85 law records clean; he/en section-count cross-check found a real defect: English statute ss. 21–25 were merged into s.20 because the PDF indents those five headers and the sectionizer required column 0. Fixed in `4cf401f`; all 29 English sections present (Hebrew s.27 is an empty stub in the source, correctly skipped). Lesson: pattern-based residue scans miss merged sections; count-based cross-checks per language catch them.

**Correction (`145c36f`).** My first fix for ss. 21–25 over-corrected (statute headers themselves start with "(a)") and dropped 12 sections; caught by re-running the per-language section-count check before committing further. Final rule: a header continues the part's numbering (gap of one allowed for the omitted s. 27). Verified: law EN 1–29 complete, HE 1–29 minus the empty s. 27 stub, rules 1–11 in both languages, schedule 3+3, no residue. Suite 694.

**Verification (4cf401f + 145c36f, Sonnet) — BLOCK, fixed in `9c954d0`.** Section counts were right, but reading the records showed every English section ending with the *next* section's title (the PDF prints titles above the numbers; the sectionizer appended them to the previous buffer) — 39 of 40 records. Fixed by holding back the last line until the next header decides whether it is body or title; English records now carry their titles; a boundary test guards it. Lesson for the log: counting sections proves coverage, only reading them proves boundaries — the reviewer's 9-record read is what caught it.

**Re-verification (9c954d0, Sonnet) — SHIP WITH FIXES, applied in `233da23`.** Ordinary sections all clean now; two leftovers: the English Schedule's items have no title lines, so my title hold-back truncated items 1–2 and misfiled their last sentences as titles of items 2–3; and the law's "Definitions" title (before s.1) was dropped. Fixed, test extended to those records. Hebrew records were clean throughout.

**Final verification (233da23, Sonnet) — SHIP.** All eleven sampled records (law s.1–3 incl. chunk boundaries, rules s.1–3, English and Hebrew Schedule items) diff exactly against the source texts; titles correct; the one oddity (a footnote inside law s.3) exists identically in the translation PDF and is preserved faithfully.

## Closing gate (2026-09-06, 102 commits since fe3cb01)
696 passed / 2 skipped · Bandit medium+ clean · pip-audit clean · docs/rules.md, docs/schema.md, corpus all current · linter snapshot reproducible at ruleset 1.1.0 · no original test file modified · Docker image builds and serves (health ok, law loaded) · working tree clean. Open items for Razy are listed in STATUS.md (Hebrew landing copy review, grounding rerun on the production model, EU seed rules, wording).

## Step 30 (2026-09-06) — second decision round, housekeeping
Razy answered the seven open items (see STATUS "Decisions taken 2026-09-06"). Plan approved in plan mode
(`~/.claude/plans/golden-sauteeing-teapot.md`). Two extra calls he made when asked: the grounding eval reruns on
`qwen3.5:397b-cloud` (the production `qwen3.5:35b` is not on this 32 GB Mac; the golden set is public in the repo, so
the cloud run discloses nothing new), and the fate normalization's effect on two linter rules is accepted.
This commit: `the_law.txt` removed (no code read it; three doc/comment mentions dropped), STATUS memos and next steps
brought current (statute/Layer 3 memos were still listed as open; design task still listed as not started).

## Step 31 (2026-09-06) — grounding eval harness: two-pass + JSON cases (b4cea27)
Two defects found while preparing the rerun: the harness only ran the blind pass (rerun condition 2 asks for the
production blind → reconcile flow) and it crashed with KeyError on the 10 SYNTH/ADV golden cases, whose files are
canonical JSON, so the earlier "6 pairs" eval was the most it could ever run. Added `--two-pass` (same prompt builder
and normalizers as `src/llm_agent.py`, reconciled verdict scored, blind score kept as `blind_score`), JSON loading,
pass-aware resume keys, and a `--report` guard against mixed-pass files. Wiring test (lesson: offline green is not
wired): SYNTH-001 with gemma4:e4b, 8 calls, blind and reconcile both parsed, grounded rows cite [Gn]. Side finding for
the maintainer: the SYNTH/ADV `good.json`/`bad.json` fixtures themselves fail the canonical schema (15 errors on
SYNTH-001); the linter accepts them, so no functional effect, but the golden set does not follow its own contract.

Model for the rerun: Razy first chose `qwen3.5:397b-cloud`; Ollama answered "requires a subscription or extra usage".
Of the cloud aliases on this Mac only `gemma4:31b-cloud` answers (qwen3-next and kimi were retired). Razy chose
gemma4:31b-cloud (free now, directional for the qwen3.5:35b production default). Run launched with all 20 pairs,
two-pass, `ETIQTECH_ALLOW_REMOTE_LLM=1` set for honesty (the local daemon proxies to ollama.com, so the hostname
gate does not fire). Disclosure: the golden set is committed to the public repo, nothing non-public left the machine.

## Step 32 (2026-09-06) — parser normalization (decision 7)
`src/html_to_json.py`: Hebrew form vocabulary → schema enums (sex, source, age/weight units, fate, enrichment →
standard|custom + `enrichment_custom`), `lay_he_≤150w` always present (empty when absent), `method_standard` omitted
when unresolved, backfilled totals normalized too, totals sex default `unknown` (was `both`). `src/schema.py`: three
enum additions (`experiments[].animals.sex` += unknown to match totals; `age.unit` += years, 24 real occurrences;
`analgesia[].phase` += unknown, the export has no phase column). Conformance 0/94 → **93/94**; the one holdout is
`examples/demo_render.html`, a hand-made demo page missing three required sections the parser does not invent.

Snapshot review (188 reports, pre-change baseline verified byte-identical first): 186 changed. Every checklist delta
classified by rule id, no unexpected rule moved:
- removed: `postop:monitoring` 34 items, `surgery:multiple-survival` 32 items (fate `המתה` now reads as euthanasia,
  the rules' existing non-survival skip applies; accepted by Razy).
- added: `sex:sabv` 42, `sex:rationale` 28 (single-sex designs are finally detected on real exports;
  `analysis.summary.single_sex_design` flipped in 64 reports, `sexes_seen` changed in all 186).
- no status flips, `errors`/`warnings` counts moved only where those items moved.
Golden manifests: 6 of 10 REAL `case.json` files carried `bad/good_expected_l1_refs` that encoded the old behaviour
(surgery:multiple-survival on REAL-001/003, postop:monitoring on REAL-036/077/084/115, and the sex rules now firing
on REAL-036/115). Updated to the new output, test file untouched. **Razy: these manifests are hand-written ground
truth; please eyeball the six diffs** (`git show <commit> -- examples/head-to-head`). Ruleset stays 1.1.0 (no rule
logic changed). New `tests/test_parser_schema.py` (118 tests: per-fixture validation, no Hebrew in enum fields,
single-sex detection, map table). Suite 814 passed / 2 skipped. Live check in linter-only mode: real export →
`sexes_seen ["F"]`, `single_sex_design true`, no protocol text in the server log. Bandit clean on changed files.

## Step 33 (2026-09-06) — Sonnet review of b4cea27 + 2ffb3e9, fixes
Review verdicts: harness matches production's reconcile flow, privacy invariant holds (lengths only in the JSONL);
method_standard omission safe (all four readers use .get); backfill sentinel change is a correctness improvement.
Three findings, all fixed in this commit:
1. **FIX (regression, human-facing)** — `src/linter_renderer.py` housing table read only `enrichment`, so after the
   normalization a non-standard enrichment rendered as the word "custom" instead of the description. My live check had
   tested for the column header, not the prose — a weak check. Now renders `enrichment_custom or enrichment`; verified
   on head-to-head/1: prose present, no bare "custom" cell. Snapshot unaffected (render is not part of the report).
2. FIX — blank fate produced `""`, outside the required enum. Parser now leaves `fate` absent when blank so schema
   validation reports the real gap instead of a wrong value (same policy as `method_standard`).
3. FIX — eval JSONL kept the blind response length in `chars` when the reconcile call failed; cleared on error.
NOTE (not changed): the eval progress counter counts rows, not LLM calls (2 per row under --two-pass).
Also: `tests/test_gunicorn_sessions.py` (a test from this sprint) flaked once under load — the 1 s health poll raised
ReadTimeout, which the loop did not catch; it now tolerates any RequestException inside the 30 s deadline. Passed
alone and in the full run after the change.

## Step 34 (2026-09-06) — grounding eval verdict: stays off
Full run on `gemma4:31b-cloud`: 20 pairs, 51 theme pairs, 204 calls, 0 errors, ~17 min. Reconciled verdicts:
ungrounded pair_acc 18 % / gap +0.18 / good_clean 16 %; grounded 18 % / +0.20 / 14 %; cited 96 %. Pre-registered rule
(grounded must beat ungrounded on pair_acc AND gap) not met → `ETIQTECH_GROUNDING` stays off. Blind-pass view of the
same rows agrees (12 % vs 14 %); reconcile changed 5 of 204 scores. The finding that matters: the model scores nearly
every protocol ≤ 1, good ones included (bad_hit 100 %, good_clean 16 %), so five of eight target themes cannot separate
good from bad at all — the Layer 2 rubric/prompt is the next experiment, grounding is not. Full write-up appended to
docs/benchmarks.md (generated table + Setup / Reading / Decision). No code change follows from this decision.

## Step 35 (2026-09-06) — closing gate, Bandit on scripts/
Running Bandit over `scripts/` as well as the CI scope (`src/ server/`) showed two pre-existing Highs in
`scripts/build_law_corpus.py` (present at 585f3e2): B613 trojan-source (literal bidi control characters inside the
`_BIDI` regex) and B324 (sha1 for stable chunk ids without `usedforsecurity=False`). Neither is a vulnerability — the
regex is a filter for exactly those characters and sha1 only names corpus chunks — but both are one-token fixes with
identical behaviour: escapes instead of literal characters, `usedforsecurity=False`. `build_law_corpus.py --check`
confirms the corpus ids are unchanged. Bandit `-ll` is now clean over src/, server/ and scripts/. CI scope unchanged.

## Closing gate (2026-09-06 late, 110 commits since fe3cb01)
Second decision round complete. Commits this round: a32bf03 housekeeping, b4cea27 eval harness, 2ffb3e9 parser
normalization, b4292c9 review fixes, d1f9483 eval verdict, 3df494e Bandit hygiene, de8aafe denominator fix. Every
commit Sonnet-reviewed; every FIX applied (enrichment render regression, blank fate, stale chars, theme denominator).
Gate: 814 passed / 2 skipped (440 originals untouched); linter snapshot byte-identical after refresh; docs/schema.md,
docs/rules.md and the corpus current (--check); Bandit -ll clean over src/, server/ and scripts/; pip-audit as CI runs
it: no known vulnerabilities; working tree clean. Open for Razy: eyeball the six golden manifest diffs
(`git show 2ffb3e9 -- examples/head-to-head`), translation licence (decision 2), wording (decision 5).

## Step 36 (2026-09-06) — first push; CI red on a test of mine
Pushed cdfc44f..cf9b78c (110 commits). CI `test` job failed on `tests/test_providers.py::test_anthropic_is_always_remote_and_gated`:
the runner has no optional `anthropic` SDK, so `_anthropic_client()` raised "needs the 'anthropic' package" before
reaching the remote gate. Locally the SDK is installed, so 814 passed here and the gap never showed — the same
lesson as "verify the environment before promising to test in it". Fix is in the code, not the test: the gate
(`gated_base_url("anthropic")`) now runs before the import, so the local-first refusal holds whether or not the SDK
is present. Reproduced CI locally by hiding the module (`sys.modules["anthropic"] = None`): 1 failed → all green.
Note: the two pre-sprint CI runs on main (April) were also red; not investigated here, different cause.

## Step 37 (2026-09-13) — Razy boots it: "I can't even load a protocol"
He was right, and every gate was green while it was broken. Three defects, found by loading the page the way a user
does (headless Chrome over the DevTools protocol, real file set on the hidden input):
1. **The upload did nothing.** `server/static/js/app.js:813` had a `// ponytail:` comment inserted mid-object-literal
   in **6ba084a** — the last commit of the first sprint, titled "docs: … comment the tier-per-rule assumption", made
   after every review had run. The comment swallowed `items: [] };`, the browser dropped the whole script, nothing on
   the page bound. Every design commit before it parsed cleanly (checked per revision with `node --check`).
2. **English UI in an RTL shell.** `app.html` carried `lang="he" dir="rtl"` from the original release; the design
   commits made every string English and never flipped the document. Now `lang="en" dir="ltr"`; Hebrew protocol
   values inside English sentences render via Unicode bidi (verified on head-to-head/1).
3. **CSRF allowlist hardcoded port 4242.** Any other port refused the browser's own origin with 403. Same-origin
   (`request.host_url`) is now always allowed; `ALLOWED_ORIGINS` still extends it.
Why the gates missed it: no test loaded the JavaScript; the reviewers read the Python diff of a "docs" commit; my
live check posted to the API with curl instead of loading the page. Fixes to the gate, not just the code:
`tests/test_static_js_syntax.py` (node --check on every served script + the LTR shell), and
`scripts/browser_smoke.py` (Chrome uploads a fixture, prints verdict and console errors; exit 1 on exception or no
verdict). Both variants of head-to-head/1 render: bad → "1 finding fails the automated check … 16 more are tied to a
legal requirement"; good → "Nothing fails … 15 findings are tied to a legal requirement … 4 more are worth fixing".
Suite 819 passed / 2 skipped. His running server caches templates: restart to pick up the direction fix.
Open NOTE: `server/static/js/tailwind.js` is the Tailwind play-CDN build and warns in the console about production
use — a build step or a static CSS export before public deploy.

## Step 38 (2026-09-13) — review of 40b7507: the CSRF fix was too trusting behind a proxy
Sonnet's adversarial read: adding `request.host_url` to the CSRF allowlist is safe on direct access (a browser
cannot forge its own Host) but under `PROXY_FIX=1` the host comes from `X-Forwarded-Host`, which the app never
verifies; today only the absence of CORS keeps that closed. Fixed: same-origin-by-host is added only when not behind
the proxy; behind it the deployment must name its public origin in `ALLOWED_ORIGINS` (README env table, k8s manifest
comment). `tests/test_csrf_origin.py` covers all five cases including the forwarded-host spoof (the check had no
tests at all before). Also from the review: an unscoped `text-align: right` on protocol tables became wrong under the
LTR shell → `text-align: start`; `browser_smoke.py` now waits for Chrome and deletes its temp profile (two leaked
profiles from earlier runs removed). Dead template `server/templates/index.html` still says rtl; no route renders it.
Suite 824 passed / 2 skipped; browser smoke clean on the new build.

## Step 39 (2026-09-13) — Argo CD deployment scaffold, remote LLM, old name gone
Razy: deploy via Argo; he owns secrets and ingress, wants remote Anthropic/OpenAI and GHCR. Built, not applied:
`k8s/` is now kustomize — `base/` (app, rbac, local-first NetworkPolicy), `overlays/local-ollama` (GPU, privacy-complete),
`overlays/remote-llm` (Ollama Cloud, unchanged semantics), `overlays/prod-remote` (the Argo target: Anthropic default with
an OpenAI block commented, Secrets `etiqtech-app`/`etiqtech-llm` by reference, `PROXY_FIX=1` + `ALLOWED_ORIGINS`
placeholder, feedback store off, egress opened to 443 non-private, image `ghcr.io/nave121/etiqtech`). `argocd/application.yaml`
points at that overlay with automated prune/self-heal. CI gains a `publish` job (main only, after the four gates) pushing
`sha-<short>` and `main` tags to GHCR with the workflow token. `k8s/README.md` is the operator document: prerequisites,
Secret commands, every env var, deploy and verification commands. All four kustomize targets render with kubectl.
Razy mid-build: "ethicchecker — this was the old name!" Renamed every k8s object, file and the Argo app to `etiqtech`
(plus one docstring in src/contracts.py). Nothing was deployed yet, so no selector churn. Repo-wide grep clean.
Not done (his lane, documented): Secrets, Cloudflare Tunnel/Access, package visibility on GHCR, the real `ALLOWED_ORIGINS`.

## Step 40 (2026-09-13) — review of 81b98a4 + first publish run
Review FIX applied: the prod egress `except` list now also blocks 169.254.0.0/16 (cloud metadata) and 100.64.0.0/10
(shared address space) — a pod that parses untrusted uploads must not reach IMDS even on 443. NOTEs applied: a scoped
`argocd/appproject.yaml` (one repo, one namespace, whitelisted kinds) replaces `project: default`; stale `kubectl apply -f`
paths in the Ollama Cloud patch header; README says a floating `main` tag needs a rollout restart to pick up a new image.
CI on 81b98a4: test/security/audit/docker green; **publish failed** with `denied: permission_denied: write_package` on
the first push to ghcr.io/nave121/etiqtech. The job's token permissions are correct (`packages: write`); the denial is on
the GitHub side (repository → Settings → Actions → General → Workflow permissions must allow write, or an existing
`etiqtech` package under the user must grant this repository write access). Razy's lane; documented in k8s/README.md.

## Step 41 (2026-09-13) — publish still denied after the permission change
Razy set the workflow permission; `gh run rerun` gave him 500s. Re-triggered twice with empty commits (this gh login is
the Rhino account, no admin on nave121/EtiqTech, so rerun/cancel are refused). Run 34748702430 sat in `queued` with zero
jobs for 11+ minutes (GitHub-side; status page green); run 34748953890 ran: four gates green, publish denied again with
`permission_denied: write_package`. The job token asks for `packages: write`, so the remaining causes are on the GitHub
side: the setting changed on a different repo/account, or a pre-existing `etiqtech` package under nave121 not linked to
this repository (registry answers 401 to anonymous pulls, so it is either private or absent — cannot tell from here).
Fallback wired: the login step uses `secrets.GHCR_TOKEN` (classic PAT, write:packages) when present, else GITHUB_TOKEN.

## Step 42 (2026-09-13) — image published
Razy re-authenticated gh as nave121 and added package scopes. Found two private container packages from 2026-03-21,
`etiqtech` and `ethicchecker`, linked to no repository — GHCR refuses a workflow token pushing into an unlinked package,
which explains every `write_package` denial (the workflow-permission setting was already `write`). With his OK both
were deleted via the API; the next run (34763184075) went fully green and created `ghcr.io/nave121/etiqtech` linked to
nave121/EtiqTech, public, tags `sha-fca384c` and `main`. Overlay pinned to `sha-fca384c`; README corrected.

## Step 43 (2026-09-13) — image verified under the pod's security context; multi-arch
Docker back on: pulled `sha-fca384c`, health OK, law loaded, browser smoke through the container renders the verdict.
Two gaps: amd64-only (this Mac ran it under emulation) and the image user was uid 100 while the manifest says 1000.
Ran the image exactly as the pod would (`--user 1000:1000 --read-only --tmpfs /tmp --tmpfs /app/output`): health and
upload both fine, so the mismatch was harmless; aligned anyway (`adduser --uid 1000 --gid 1000`) and made the publish
multi-arch (QEMU + buildx, linux/amd64 + linux/arm64). Run 34763703890 green; `sha-586cc30` manifest lists both
platforms (plus the two `unknown/unknown` provenance entries buildx adds; containerd ignores them). Native arm64 pull:
uid 1000, aarch64. Overlay pinned to `sha-586cc30`. Review FIX applied: README no longer states "public" as a rule —
it is what happened once; GitHub documents private as the personal-account default, so the operator checks visibility.
