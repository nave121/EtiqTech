"""Regression test for P0.1: sessions must survive the real gunicorn process model.

Spawns gunicorn with the shipped gunicorn.conf.py (the same file the Dockerfile
uses), then runs analyze -> SSE round-trips against it. With more than one
worker the EventSource GET can land on a process that never saw the POST and
answers "Session not found"; with the shipped config every round-trip must
complete.

Ollama is pointed at a closed port so every LLM call fails fast and each
theme falls back — the stream still runs end-to-end and ends with `complete`.
"""
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import pytest
import requests

REPO_ROOT = Path(__file__).resolve().parents[1]
GOOD_HTML = REPO_ROOT / "examples" / "known-good" / "good_IL-010-05-2000.html"
ROUND_TRIPS = int(os.getenv("SESSION_ROUND_TRIPS", "50"))

pytestmark = pytest.mark.skipif(shutil.which("gunicorn") is None, reason="gunicorn not installed")


def _free_port() -> int:
    # bind-close-reuse race is possible under parallel runners; cost is a 30s startup timeout, not a false pass
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def gunicorn_url():
    port = _free_port()
    env = {
        **os.environ,
        "PYTHONPATH": str(REPO_ROOT),
        "OLLAMA_BASE_URL": "http://127.0.0.1:1",  # closed port: connection refused immediately
        "OLLAMA_TIMEOUT_SECONDS": "2",
        "LAYER3_SAMPLING_RATE": "0",
        "RATELIMIT_ENABLED": "false",  # 50 POSTs in a row would trip the 10/min analyze limit
    }
    # stderr goes to a file, never a PIPE: an undrained pipe fills up under gunicorn's
    # logging and blocks the worker, which looks exactly like a lost session.
    stderr = tempfile.TemporaryFile()
    proc = subprocess.Popen(
        [sys.executable, "-m", "gunicorn", "-c", "gunicorn.conf.py", "-b", f"127.0.0.1:{port}", "server.app:app"],
        cwd=REPO_ROOT,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=stderr,
    )

    def _stderr_tail() -> str:
        stderr.seek(0)
        return stderr.read().decode(errors="replace")[-2000:]

    url = f"http://127.0.0.1:{port}"
    try:
        deadline = time.time() + 30
        while time.time() < deadline:
            if proc.poll() is not None:
                raise RuntimeError(f"gunicorn exited early: {_stderr_tail()}")
            try:
                if requests.get(f"{url}/api/health", timeout=1).ok:
                    break
            except requests.ConnectionError:
                time.sleep(0.2)
        else:
            raise RuntimeError("gunicorn did not become healthy in 30s")
        yield url
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
        stderr.close()


def _round_trip(url: str, html: str) -> list:
    resp = requests.post(f"{url}/api/analyze-with-session", json={"html_content": html}, timeout=30)
    assert resp.status_code == 200, resp.text[:300]
    session_id = resp.json()["session_id"]

    events = []
    with requests.get(f"{url}/api/llm-verify-stream/{session_id}", stream=True, timeout=60) as sse:
        assert sse.status_code == 200
        for line in sse.iter_lines(decode_unicode=True):
            if not line or not line.startswith("data: "):
                continue
            payload = line[6:]
            events.append(payload)
            if '"type": "complete"' in payload or '"type": "error"' in payload:
                break
    return events


def test_shipped_gunicorn_config_is_single_worker():
    ns: dict = {}
    exec((REPO_ROOT / "gunicorn.conf.py").read_text(), ns)
    assert ns["workers"] == 1, "sessions are per-process; see gunicorn.conf.py"
    assert ns["threads"] >= 8
    # the Dockerfile must actually use this file, or the test guards nothing
    assert '"-c", "gunicorn.conf.py"' in (REPO_ROOT / "Dockerfile").read_text()


def test_analyze_then_sse_round_trips_never_lose_session(gunicorn_url):
    html = GOOD_HTML.read_text(encoding="utf-8")
    lost = 0
    for _ in range(ROUND_TRIPS):
        events = _round_trip(gunicorn_url, html)
        assert events, "no SSE events received"
        if "Session not found" in events[0]:
            lost += 1
            continue
        assert '"type": "complete"' in events[-1], events[-1][:200]
    assert lost == 0, f"{lost}/{ROUND_TRIPS} round-trips lost their session"
