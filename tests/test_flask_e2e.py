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
    assert response.get_json()["error"] == "Missing html_content"


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
        force=False,
        **kwargs,
    ):
        captured_layer3["layer2_result"] = layer2_result_arg
        captured_layer3["force"] = force
        yield {
            "type": "layer3_trigger",
            "reason": "layer2_multiple_low_scores",
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
            "triggered_by": "layer2_multiple_low_scores",
            "skipped": False,
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
        layer3_response = client.get(
            f"/api/human-eye-stream/{session_id}?force=1"
        )
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
    assert captured_layer3["force"] is True
    assert layer3_events[-1]["result"]["overall_verdict"] == "revise_minor"


def test_flask_stream_returns_error_event_for_missing_session(client):
    response = client.get("/api/llm-verify-stream/missing-session")
    events = _parse_sse(response)

    assert events == [{"type": "error", "message": "Session not found"}]
