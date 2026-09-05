# Privacy

EtiqTech reviews draft animal-research protocols before they reach the ethics
committee. Drafts are sensitive, so the tool is built to hold them for as short
a time as possible, in as few places as possible. This document states the
guarantees, how they are enforced, and how you can verify them without reading
the source.

## Guarantees

1. **Protocols are never written to disk.** An upload is parsed in memory,
   linted in memory, and (optionally) sent to the LLM from memory. There is no
   database, no upload folder, no cache file. The container's only writable
   paths are `/tmp` and `/app/output`, and the server writes to neither.
2. **Protocols live in process memory for about one hour, at most.** A review
   session is a UUID4 key in a dict (`server/app.py: _analysis_cache`).
   Entries older than one hour are evicted on the next upload; the dict is
   capped at 100 sessions. Restarting the process erases everything.
3. **No protocol text ever appears in logs, at any log level.** Logs carry
   session UUIDs, timings, token counts, prompt *sizes* and fixed error
   strings. Exceptions are logged with tracebacks, which contain source lines
   but never request bodies or LLM responses.
4. **The LLM runs locally by default.** `OLLAMA_BASE_URL` defaults to
   `127.0.0.1`. The app refuses to send anything to a host that is not
   loopback, private-network or cluster-internal unless the operator sets
   `ETIQTECH_ALLOW_REMOTE_LLM=1`, and logs a startup warning when they do.
   `/api/health` reports `llm_local`. The reference Kubernetes manifests
   target an in-cluster Ollama and their NetworkPolicy blocks other egress.
5. **No user accounts, no tracking.** The app has no authentication layer and
   no analytics. Access control is the reverse proxy's job (the reference
   deployment uses Cloudflare Access), which is also where any access log
   lives — and that log sees URLs and identities, never protocol content,
   because uploads are POST bodies.

## What is *not* covered

- Your browser holds the rendered report until you close the tab; printing or
  exporting the report is your action and your file.
- If you opt in to a remote LLM (guarantee 4), the provider's privacy terms
  apply to everything sent. That is your decision to make and disclose.
- The reverse proxy in front of the app (auth, TLS termination) is outside the
  app's control; configure its logging to your institution's policy.

## How it is enforced

| Guarantee | Enforcement |
|-----------|-------------|
| 1, 2 | No persistence code path exists; `tests/test_privacy_canary.py` runs the full pipeline and the HTTP API on a protocol carrying a unique marker string and fails if the marker reaches any log, stdout or stderr. Adding persistence would have to add code that this test then has to be taught to ignore — a deliberate act, not an accident. |
| 3 | Logging is configured once in `server/app.py` (default INFO); the canary runs at DEBUG. |
| 4 | `src/llm_clients.ollama_base_url()` gate + `tests/test_local_first.py`; k8s NetworkPolicy. |
| 5 | Documented design decision; see SECURITY.md. |

## What a future feature may store

The roadmap includes a metadata-only feedback loop (thumbs up/down per finding).
It will store rule identifiers, verdicts and timestamps — never protocol text,
never free-text comments. The canary test above will be extended to cover that
store before it ships. Any change to these guarantees is a documented,
maintainer-approved decision, not an implementation detail.

## Verify it yourself

```bash
python -m pytest tests/test_privacy_canary.py tests/test_local_first.py -q
curl -s localhost:4242/api/health      # llm_local: true, law_loaded: true
```
