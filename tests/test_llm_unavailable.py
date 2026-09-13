"""An LLM failure must be loud, never a verdict.

2026-09-13, first production deploy: every OpenAI call failed (parameter mismatch) and the app
returned a full report scoring all twelve themes "inadequate" with the rationale "LLM error".
Health was green because it only reports configuration. These tests pin the contract that
replaced that: fallback themes carry `unavailable: True`, the result carries `llm_failures`,
the stream emits a warning per failed theme, and Layer 3 does not treat a failed theme as weak.
"""
from unittest.mock import patch

from src.html_to_json import parse_html
from src.linter_renderer import lint
from src.llm_agent import (
    THEME_SPECS,
    _build_fallback_theme,
    _normalize_theme_payload,
    llm_failures,
    run_verification,
    run_verification_stream,
)
from src.llm_clients import LLMError
from src.llm_layer3 import _theme_score_at_most

SPEC = next(iter(THEME_SPECS.values()))


def _instance():
    inst = parse_html(open("examples/head-to-head/1/good.html", encoding="utf-8").read())
    return inst, lint(inst, profile="default")


def test_fallback_theme_is_marked_unavailable():
    t = _build_fallback_theme(SPEC, "LLM error: LLMError")
    assert t["unavailable"] is True and t["rationale"] == "LLM error: LLMError"


def test_normalize_keeps_the_unavailable_flag_and_reason():
    t = _normalize_theme_payload(SPEC, _build_fallback_theme(SPEC, "LLM error: LLMError"), fallback_rationale="x")
    assert t["unavailable"] is True and t["rationale"] == "LLM error: LLMError"


def test_real_answer_is_not_unavailable():
    t = _normalize_theme_payload(SPEC, {"score": 3, "rationale": "fine", "sub_questions": []}, fallback_rationale="x")
    assert "unavailable" not in t and t["score"] == 3


def test_layer3_does_not_treat_a_failed_theme_as_weak():
    assert _theme_score_at_most(_build_fallback_theme(SPEC, "LLM error"), 1) is False
    assert _theme_score_at_most({"score": 1}, 1) is True


def test_stream_reports_every_failed_theme_and_summarises():
    inst, report = _instance()

    def boom(prompt, **kwargs):
        raise LLMError("OpenAI-compatible endpoint responded with HTTP 400")
        yield  # pragma: no cover — keep it a generator

    with patch("src.llm_agent.call_llm_stream", side_effect=boom):
        events = list(run_verification_stream(inst, report, stance="law"))
    done = [e for e in events if e["type"] == "theme_done"]
    warnings = [e for e in events if e["type"] == "warning" and e.get("code") == "llm_unavailable"]
    complete = [e for e in events if e["type"] == "complete"][0]["result"]
    assert done and all(e["result"]["unavailable"] for e in done)
    assert {w["theme"] for w in warnings} == {e["theme"] for e in done}
    assert set(complete["llm_failures"]) == {e["theme"] for e in done}
    assert all("LLMError" in reason for reason in complete["llm_failures"].values())


def test_non_stream_result_carries_failures():
    inst, report = _instance()
    with patch("src.llm_agent.call_llm", side_effect=LLMError("HTTP 400")):
        result = run_verification(inst, report, stance="law")
    assert result["llm_failures"] and set(result["llm_failures"]) == set(result["themes"])


def test_no_failures_when_the_model_answers():
    assert llm_failures({"a": {"score": 2, "rationale": "ok"}}) == {}


def test_health_probe_reports_a_failing_provider(monkeypatch):
    from server import app as appmod
    monkeypatch.delenv("ETIQTECH_LLM_DISABLED", raising=False)
    client = appmod.app.test_client()
    plain = client.get("/api/health").get_json()
    assert "llm_probe" not in plain  # config-only unless asked
    with patch.object(appmod, "call_llm", side_effect=LLMError("HTTP 400")):
        probed = client.get("/api/health?probe=llm").get_json()
    assert probed["llm_probe"] == {"ok": False, "error": "LLMError"} and probed["status"] == "degraded"
    with patch.object(appmod, "call_llm", return_value="OK"):
        assert client.get("/api/health?probe=llm").get_json()["llm_probe"] == {"ok": True}
