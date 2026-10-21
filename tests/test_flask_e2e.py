import json
from pathlib import Path
from unittest.mock import patch

import pytest

from server.app import _analysis_cache, app


REPO_ROOT = Path(__file__).resolve().parents[1]
GOOD_HTML = (
    REPO_ROOT
    / "examples"
    / "known-good"
    / "good_IL-010-05-2000.html"
)


def _load_html() -> str:
    return GOOD_HTML.read_text(encoding="utf-8")


def _parse_sse(response):
    events = []
    for line in response.get_data(as_text=True).splitlines():
        if line.startswith("data: "):
            events.append(json.loads(line[6:]))
    return events


@pytest.fixture()
def client():
    _analysis_cache.clear()
    app.config["TESTING"] = True
    with app.test_client() as test_client:
        yield test_client
    _analysis_cache.clear()


def test_analyze_with_session_rejects_missing_html_content(client):
    response = client.post("/api/analyze-with-session", json={})

    assert response.status_code == 400
    assert response.get_json()["error"].startswith("Missing html_content")


def test_flask_e2e_stream_chain_preserves_session_and_event_order(client):
    analyze_response = client.post(
        "/api/analyze-with-session",
        json={"html_content": _load_html()},
    )

    assert analyze_response.status_code == 200
    payload = analyze_response.get_json()
    assert payload["success"] is True
    session_id = payload["session_id"]
    assert session_id in _analysis_cache

    layer2_result = {
        "themes": {
            "three_Rs_alternatives": {
                "score": 2,
                "label": "partially_adequate",
                "rationale": "Alternatives search is sufficient.",
                "sub_questions": [],
            },
            "scientific_coherence": {
                "score": 1,
                "label": "inadequate",
                "rationale": "Group labels need clarification.",
                "sub_questions": [],
            },
        },
        "questions": [
            {
                "field_path": "experiments[0].label",
                "question": "Clarify the control group label.",
                "blocking": True,
            }
        ],
        "checklist_items": [],
    }
    captured_layer3 = {}

    def fake_layer2_stream(instance, lint_report, stance="committee", **kwargs):
        yield {
            "type": "theme_start",
            "theme": "three_Rs_alternatives",
            "label": "3Rs / Alternatives Search",
            "progress": 1,
            "total": 2,
        }
        yield {
            "type": "token",
            "theme": "three_Rs_alternatives",
            "token": "Working",
        }
        yield {
            "type": "theme_done",
            "theme": "three_Rs_alternatives",
            "label": "3Rs / Alternatives Search",
            "result": layer2_result["themes"]["three_Rs_alternatives"],
            "skipped": False,
        }
        yield {
            "type": "theme_start",
            "theme": "scientific_coherence",
            "label": "Scientific coherence",
            "progress": 2,
            "total": 2,
        }
        yield {
            "type": "token",
            "theme": "scientific_coherence",
            "token": "More work",
        }
        yield {
            "type": "theme_done",
            "theme": "scientific_coherence",
            "label": "Scientific coherence",
            "result": layer2_result["themes"]["scientific_coherence"],
            "skipped": False,
        }
        yield {"type": "complete", "result": layer2_result}

    def fake_layer3_stream(
        instance,
        lint_report,
        layer2_result_arg,
        **kwargs,
    ):
        captured_layer3["layer2_result"] = layer2_result_arg
        yield {
            "type": "layer3_trigger",
            "reason": "always",
        }
        yield {
            "type": "pass_start",
            "pass": 1,
            "label": "Section-by-section review",
        }
        yield {"type": "token", "pass": 1, "token": "Inspecting"}
        yield {
            "type": "pass_done",
            "pass": 1,
            "result": {"sections": []},
        }
        yield {
            "type": "pass_start",
            "pass": 2,
            "label": "Cross-reference & synthesis",
        }
        yield {"type": "token", "pass": 2, "token": "Reconciling"}
        final_result = {
            "sections": [],
            "cross_reference_issues": [],
            "overall_verdict": "revise_minor",
            "risk_profile": "medium",
            "summary": "Route integration test completed.",
            "triggered_by": "always",
        }
        yield {
            "type": "pass_done",
            "pass": 2,
            "result": {
                "cross_reference_issues": [],
                "overall_verdict": "revise_minor",
                "risk_profile": "medium",
                "summary": "Route integration test completed.",
            },
        }
        yield {"type": "complete", "result": final_result}

    with patch(
        "server.app.run_verification_stream",
        side_effect=fake_layer2_stream,
    ):
        llm_response = client.get(f"/api/llm-verify-stream/{session_id}")
    llm_events = _parse_sse(llm_response)

    assert [event["type"] for event in llm_events] == [
        "theme_start",
        "token",
        "theme_done",
        "theme_start",
        "token",
        "theme_done",
        "complete",
    ]
    assert _analysis_cache[session_id]["layer2_result"] == layer2_result

    with patch(
        "server.app.run_human_eye_stream",
        side_effect=fake_layer3_stream,
    ):
        layer3_response = client.get(f"/api/human-eye-stream/{session_id}")
    layer3_events = _parse_sse(layer3_response)

    assert [event["type"] for event in layer3_events] == [
        "layer3_trigger",
        "pass_start",
        "token",
        "pass_done",
        "pass_start",
        "token",
        "pass_done",
        "complete",
    ]
    assert captured_layer3["layer2_result"] == layer2_result
    assert layer3_events[-1]["result"]["overall_verdict"] == "revise_minor"


def test_flask_stream_returns_error_event_for_missing_session(client):
    response = client.get("/api/llm-verify-stream/missing-session")
    events = _parse_sse(response)

    assert events == [{"type": "error", "message": "Session not found"}]


def test_expired_session_is_gone_without_a_new_upload(client):
    """PRIVACY.md guarantee 2: a session lives an hour even when no later review triggers the sweep."""
    from datetime import datetime, timedelta
    import server.app as app_module

    def old():
        return {"instance": {}, "lint_report": {}, "created_at": datetime.now() - timedelta(hours=2)}
    _analysis_cache["old"] = old()
    assert app_module._get_session("old") is None
    _analysis_cache["old"] = old()
    client.get("/api/health")  # any request sweeps; the container health check fires every 30 s
    assert "old" not in _analysis_cache
    _analysis_cache["old"] = old()
    events = _parse_sse(client.get("/api/llm-verify-stream/old"))
    assert events == [{"type": "error", "message": "Session not found"}]


def _session(client, **form):
    import io
    data = {"file": (io.BytesIO(_load_html().encode()), "p.html"), **form}
    return client.post("/api/analyze-with-session", data=data, content_type="multipart/form-data").get_json()["session_id"]


@pytest.fixture()
def no_limits(monkeypatch):
    import server.app as app_module
    monkeypatch.setattr(app_module.limiter, "enabled", False)


def test_layer2_result_is_saved_before_complete_is_sent(client, no_limits):
    """The browser opens the Layer 3 stream as soon as `complete` arrives; the save cannot wait for the next pull."""
    sid = _session(client)
    result = {"themes": {}}
    with patch("server.app.run_verification_stream", side_effect=lambda *a, **k: iter([{"type": "complete", "result": result}])):
        chunks = iter(client.get(f"/api/llm-verify-stream/{sid}", buffered=False).response)
        assert b'"complete"' in next(chunks)
        assert _analysis_cache[sid].get("layer2_result") == result


def test_browser_cannot_pick_the_model_of_a_remote_provider(client, no_limits, monkeypatch):
    """The picker lists Ollama models; on a paid provider the configured model is the budget decision."""
    sid = _session(client, provider="openai", model="gpt-6.1-sol")
    models = []

    def capture(prompt, **kw):
        models.append(kw.get("model"))
        return "{}"
    with patch("src.llm_agent.call_llm", side_effect=capture):
        _parse_sse(client.get(f"/api/llm-verify-stream/{sid}"))
    assert models and set(models) == {None}  # None: call_llm uses OPENAI_MODEL
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    assert _analysis_cache[_session(client, model="gpt-6.1-sol")]["model"] is None
    monkeypatch.setenv("LLM_PROVIDER", "ollama")
    assert _analysis_cache[_session(client, model="gemma4:e4b")]["model"] == "gemma4:e4b"
