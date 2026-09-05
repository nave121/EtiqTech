"""Privacy canary (P1.2): protocol text must never reach logs, stdout or stderr.

A unique marker is planted in every free-text field of a fixture (and in the raw
HTML). The whole pipeline — parser, linter, renderer, Layer 2 (stream + batch),
Layer 3, and the Flask API including SSE — runs with the LLM mocked to echo the
marker back, at DEBUG level, while everything the process emits is captured.
If the marker shows up anywhere, a new code path is leaking protocol content.
"""
import json
import types
import logging
import uuid
from pathlib import Path

import pytest

import src.llm_agent as llm_agent
import src.llm_layer3 as llm_layer3
from src.html_to_json import parse_html
from src.linter_renderer import lint, render_html_with_refs
from server.app import app, _analysis_cache

REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURE = REPO_ROOT / "examples" / "known-good" / "good_IL-001-01-2000.html"
INSTITUTION = "מכון אודין למחקר (דוגמא)"  # appears verbatim in the fixture; parsed into header.institution


def _plant(obj, marker):
    """Append the marker to every free-text string in the parsed instance."""
    if isinstance(obj, dict):
        return {k: _plant(v, marker) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_plant(v, marker) for v in obj]
    if isinstance(obj, str) and len(obj) > 20:
        return f"{obj} {marker}"
    return obj


def _fake_llm_response(marker):
    # An LLM that parrots the protocol back — if anyone logs responses, the marker surfaces.
    return json.dumps({"three_Rs_alternatives": {"score": 2, "rationale": f"echo {marker}"}, "questions": []})


@pytest.fixture
def marker():
    return f"CANARY-{uuid.uuid4()}"


@pytest.fixture
def quiet_llm(monkeypatch, marker):
    resp = _fake_llm_response(marker)
    monkeypatch.setattr(llm_agent, "call_llm_stream", lambda *a, **k: iter([resp]))
    monkeypatch.setattr(llm_agent, "call_llm", lambda *a, **k: resp)
    monkeypatch.setattr(llm_agent, "call_llm_two_step", lambda *a, **k: resp)
    monkeypatch.setattr(llm_layer3, "call_llm_stream", lambda *a, **k: iter([resp]))
    monkeypatch.setattr(llm_layer3, "call_llm", lambda *a, **k: resp)
    monkeypatch.setenv("LAYER3_SAMPLING_RATE", "0")


def _assert_clean(marker, caplog, capfd):
    out, err = capfd.readouterr()
    assert marker not in caplog.text, "marker leaked into a log record"
    assert marker not in out, "marker leaked to stdout"
    assert marker not in err, "marker leaked to stderr"


def test_pipeline_functions_never_log_protocol_text(marker, quiet_llm, caplog, capfd):
    caplog.set_level(logging.DEBUG)
    html = FIXTURE.read_text(encoding="utf-8").replace(INSTITUTION, marker)
    assert marker in html
    instance = _plant(parse_html(html), marker)
    assert marker in json.dumps(instance, ensure_ascii=False)

    report = lint(instance, profile="default")
    render_html_with_refs(instance)
    events = list(llm_agent.run_verification_stream(instance, report))
    assert events[-1]["type"] == "complete"
    llm_agent.run_verification(instance, report)
    l3 = list(llm_layer3.run_human_eye_stream(instance, report, events[-1]["result"], force=True))
    assert l3[-1]["type"] == "complete"
    llm_layer3.run_human_eye(instance, report, events[-1]["result"], force=True)

    _assert_clean(marker, caplog, capfd)


def test_http_api_never_logs_protocol_text(marker, quiet_llm, caplog, capfd):
    caplog.set_level(logging.DEBUG)
    html = FIXTURE.read_text(encoding="utf-8").replace(INSTITUTION, marker)
    _analysis_cache.clear()
    app.config["TESTING"] = True
    with app.test_client() as client:
        r = client.post("/api/analyze", json={"html_content": html})
        assert r.status_code == 200
        r = client.post("/api/analyze-with-session", json={"html_content": html})
        assert r.status_code == 200
        sid = r.get_json()["session_id"]
        sse = client.get(f"/api/llm-verify-stream/{sid}").get_data(as_text=True)
        assert '"type": "complete"' in sse
        sse3 = client.get(f"/api/human-eye-stream/{sid}?force=1").get_data(as_text=True)
        assert '"type": "complete"' in sse3
        # error paths log too: a malformed upload must not echo the body
        r = client.post("/api/analyze", json={"html_content": f"<html><body>{marker}</body></html>"})
        assert r.status_code in (200, 500)
    _analysis_cache.clear()

    _assert_clean(marker, caplog, capfd)


def test_llm_failure_path_never_logs_prompt(marker, monkeypatch, caplog, capfd):
    """When the LLM call blows up, the exception text is shown to the user, not logged."""
    caplog.set_level(logging.DEBUG)
    html = FIXTURE.read_text(encoding="utf-8").replace(INSTITUTION, marker)
    instance = _plant(parse_html(html), marker)
    report = lint(instance, profile="default")

    def boom(prompt, **_):
        raise RuntimeError(f"provider exploded while reading {prompt[:200]}")
    monkeypatch.setattr(llm_agent, "call_llm_stream", boom)
    monkeypatch.setattr(llm_agent, "call_llm", boom)
    events = list(llm_agent.run_verification_stream(instance, report))
    assert events[-1]["type"] == "complete"
    _assert_clean(marker, caplog, capfd)


def test_canary_detects_a_leak(marker, monkeypatch, caplog, capfd):
    """Prove the harness bites: an LLM wrapper that logs its prompt must be caught."""
    caplog.set_level(logging.DEBUG)
    html = FIXTURE.read_text(encoding="utf-8").replace(INSTITUTION, marker)
    instance = _plant(parse_html(html), marker)
    report = lint(instance, profile="default")
    leaky_logger = logging.getLogger("leaky.provider")

    def leaky(prompt, **_):
        leaky_logger.debug("sending prompt: %s", prompt)  # the kind of line this test exists to forbid
        return iter([_fake_llm_response(marker)])
    monkeypatch.setattr(llm_agent, "call_llm_stream", leaky)
    list(llm_agent.run_verification_stream(instance, report))
    with pytest.raises(AssertionError, match="log record"):
        _assert_clean(marker, caplog, capfd)


def test_invalid_llm_json_path_never_logs_response(marker, monkeypatch, caplog, capfd):
    """parse_llm_json embeds a preview of the raw response in its ValueError; that text reaches the
    fallback rationale (UI) — it must never reach a log."""
    caplog.set_level(logging.DEBUG)
    html = FIXTURE.read_text(encoding="utf-8").replace(INSTITUTION, marker)
    instance = _plant(parse_html(html), marker)
    report = lint(instance, profile="default")
    garbage = f"Sure! Here is my analysis of {marker} — no JSON for you"
    monkeypatch.setattr(llm_agent, "call_llm_stream", lambda *a, **k: iter([garbage]))
    monkeypatch.setattr(llm_agent, "call_llm", lambda *a, **k: garbage)
    monkeypatch.setattr(llm_layer3, "call_llm_stream", lambda *a, **k: iter([garbage]))
    monkeypatch.setattr(llm_layer3, "call_llm", lambda *a, **k: garbage)
    events = list(llm_agent.run_verification_stream(instance, report))
    assert events[-1]["type"] == "complete"
    l3 = list(llm_layer3.run_human_eye_stream(instance, report, events[-1]["result"], force=True))
    assert l3[-1]["type"] == "complete"
    _assert_clean(marker, caplog, capfd)


def test_server_error_path_never_logs_body(marker, monkeypatch, caplog, capfd):
    """Force the generic 500 branch: the traceback is logged, the body must not be."""
    caplog.set_level(logging.DEBUG)
    import server.app as app_module

    def explode(content, filename=None):
        raise RuntimeError("parser died")  # message deliberately free of the body; the test checks the frames
    monkeypatch.setattr(app_module, "ingest", explode)
    app.config["TESTING"] = True
    with app.test_client() as client:
        for route in ("/api/analyze", "/api/analyze-with-session"):
            caplog.clear()
            r = client.post(route, json={"html_content": f"<html><body>{marker}</body></html>"})
            assert r.status_code == 500
            assert any("Analysis" in rec.message and rec.exc_info for rec in caplog.records), route
            _assert_clean(marker, caplog, capfd)


def test_canary_detects_stdout_and_stderr_leaks(marker, capfd, caplog):
    import sys
    print(marker)
    with pytest.raises(AssertionError, match="stdout"):
        _assert_clean(marker, caplog, capfd)
    sys.stderr.write(marker + "\n")
    with pytest.raises(AssertionError, match="stderr"):
        _assert_clean(marker, caplog, capfd)


def test_feedback_store_never_contains_protocol_text(marker, quiet_llm, monkeypatch, tmp_path, caplog, capfd):
    """The only persistence path in the app: after a marked review plus feedback on its findings,
    the database file must not contain the marker."""
    caplog.set_level(logging.DEBUG)
    db_file = tmp_path / "fb.sqlite"
    monkeypatch.setenv("FEEDBACK_DB", str(db_file))
    monkeypatch.setenv("RATELIMIT_ENABLED", "false")
    app.config["RATELIMIT_ENABLED"] = False
    html = FIXTURE.read_text(encoding="utf-8").replace(INSTITUTION, marker)
    _analysis_cache.clear()
    try:
        with app.test_client() as client:
            r = client.post("/api/analyze-with-session", json={"html_content": html})
            report = r.get_json()["lint_report"]
            for item in report["checklist"]:
                if item["status"] == "fail" and item["rule_id"]:
                    client.post("/api/feedback", json={"kind": "lint", "key": item["rule_id"], "verdict": "down",
                                                       "ruleset_version": report["ruleset_version"], "profile": report["profile"]})
            client.post("/api/feedback", json={"kind": "llm", "key": "three_Rs_alternatives", "verdict": "up"})
            # attempts to smuggle text in must be refused, not stored — extra field, and text in the two optional fields
            assert client.post("/api/feedback", json={"kind": "llm", "key": "three_Rs_alternatives", "verdict": "up", "note": marker}).status_code == 400
            assert client.post("/api/feedback", json={"kind": "llm", "key": "three_Rs_alternatives", "verdict": "up", "profile": marker[:32]}).status_code == 400
            assert client.post("/api/feedback", json={"kind": "llm", "key": "three_Rs_alternatives", "verdict": "up", "ruleset_version": marker[:32]}).status_code == 400
    finally:
        app.config["RATELIMIT_ENABLED"] = True
        _analysis_cache.clear()
    assert db_file.exists()
    assert marker.encode() not in db_file.read_bytes()
    assert "CANARY" not in db_file.read_bytes().decode(errors="ignore")
    _assert_clean(marker, caplog, capfd)


def test_provider_error_bodies_never_reach_logs(marker, monkeypatch, caplog, capfd):
    """A gateway that echoes the request into its error body must not get that echo into our logs,
    for any provider path — patched at the HTTP layer, below call_llm."""
    import requests
    from src import llm_clients
    caplog.set_level(logging.DEBUG)
    monkeypatch.setenv("OPENAI_BASE_URL", "http://localhost:8000/v1")
    monkeypatch.setenv("OPENAI_MODEL", "m")
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434")

    class _Body:
        # A 4xx/5xx from any provider: the code must raise from the status code alone and never read
        # the body (which a gateway may fill with an echo of the request).
        status_code = 400
        text = f"validation error: prompt contained {marker}"
        def json(self):
            pytest.fail("an error body must never be parsed")
        def iter_lines(self):
            pytest.fail("an error body must never be streamed")
    monkeypatch.setattr(requests, "post", lambda *a, **k: _Body())
    for call in (lambda: llm_clients.call_llm("p", provider="openai"),
                 lambda: list(llm_clients.call_llm_stream("p", provider="openai")),
                 lambda: llm_clients.call_llm("p", provider="ollama", model="m"),
                 lambda: list(llm_clients.call_llm_stream("p", provider="ollama", model="m"))):
        with pytest.raises(Exception) as ei:
            call()
        assert marker not in str(ei.value)

    class _Ok:
        status_code = 200
        text = ""
        def json(self):
            return {"response": ""}
        def iter_lines(self):
            return iter([f'data: {{"error": {{"type": "overflow", "message": "{marker}"}}}}'.encode()])
    monkeypatch.setattr(requests, "post", lambda *a, **k: _Ok())
    with pytest.raises(Exception):
        list(llm_clients.call_llm_stream("p", provider="openai"))

    class _Boom:
        messages = types.SimpleNamespace(create=lambda **kw: (_ for _ in ()).throw(RuntimeError(f"SDK saw {marker}")))
    monkeypatch.setenv("ETIQTECH_ALLOW_REMOTE_LLM", "1")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    monkeypatch.setattr(llm_clients, "_anthropic_client", lambda: _Boom())
    with pytest.raises(Exception) as ei:
        llm_clients.call_llm("p", provider="anthropic")
    assert marker not in str(ei.value)
    _assert_clean(marker, caplog, capfd)
