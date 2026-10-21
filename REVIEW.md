# REVIEW.md: what a reviewer checks on every PR

For humans and review agents alike. Read it in full before approving; a review agent
reads it in a fresh context, so the invariants are quoted here, not linked.

## 1. The invariants still hold
Source: `docs/dev-log/STATUS.md`, section "Invariants (never break)". Quoted verbatim:

> All tests green (824 now, 440 original untouched) · no protocol text persisted or logged at any
> level · local-first LLM by default · LLM never gates/filters/rewrites Layer 1 · advisory framing
> permanent · auth stays at the reverse proxy.

As five checks on the diff:
1. **All tests green.** No test was deleted, skipped or weakened to make the change pass. The count only goes up.
2. **No protocol text persisted or logged at any level.** No new write of protocol content to disk, database, log line, error message or external service.
3. **Local-first LLM by default.** No new default that sends protocol text to a remote provider; remote stays opt-in behind `ETIQTECH_ALLOW_REMOTE_LLM`.
4. **LLM never gates, filters or rewrites Layer 1.** Linter findings reach the report unchanged by any model output.
5. **Advisory framing permanent; auth stays at the reverse proxy.** No wording that presents the tool as an approval, and no authentication added inside the app.

## 2. CI is green
The `test`, `security`, `audit` and `docker` jobs pass on the PR head. A red job is a stop, not a note.

## 3. The PR template is filled
All three sections carry real content: **Testing** (what ran and what it printed), **Risk** (what could break and who notices), **How to revert** (the concrete undo).

## 4. Nothing sensitive in the diff
No protocol text, no fixture derived from a real protocol, no secret, token, key or credential, in code, tests, docs or examples.

## Verdict
PASS only when all four sections hold. Any failed item is named with the file and line.
