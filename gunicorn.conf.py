"""Gunicorn configuration — the single source of truth for how EtiqTech is served.

Used by the Dockerfile CMD and by tests/test_gunicorn_sessions.py, so the
shipped process model and the tested process model are the same file.

Why exactly one worker
----------------------
Analysis sessions live in a per-process dict (server.app._analysis_cache).
With two workers the browser's POST /api/analyze-with-session lands on one
process and the follow-up EventSource GET can land on the other, which then
answers "Session not found". Threads share memory, processes do not, so we
scale with gthread threads inside one worker instead.

Threads are sized generously: every SSE stream (Layer 2 / Layer 3) occupies a
thread for the whole LLM run. gthread's poll loop keeps heart-beating the
arbiter while request threads are busy, so long streams are not killed by
`timeout`.

Scale-out path (not built; not needed at current scale)
------------------------------------------------------
Run one container replica per node behind Cloudflare with sticky sessions
per container. If more than one process ever needs to share sessions, move
_analysis_cache to a shared store (Redis) and point flask-limiter at the
same store via `storage_uri="redis://..."` — its default `memory://` storage
is also per-process, so rate limits are per-worker today (fine with 1).
"""
import os

bind = f"0.0.0.0:{os.getenv('PORT', '4242')}"
workers = 1
worker_class = "gthread"
threads = int(os.getenv("GUNICORN_THREADS", "16"))
timeout = 300
keepalive = 5
accesslog = None  # ponytail: no access log; request paths carry session UUIDs, not protocol text
