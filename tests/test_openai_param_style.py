"""OpenAI-compatible payloads: api.openai.com needs max_completion_tokens and no temperature
(reasoning models reject both max_tokens and a non-default temperature: HTTP 400 in production,
2026-09-13); vLLM / LM Studio / llama.cpp still expect max_tokens + temperature."""
import pytest

from src.llm_clients import _openai_param_style, _openai_payload


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    for k in ("OPENAI_PARAM_STYLE", "OPENAI_BASE_URL", "LLM_TEMPERATURE", "LLM_MAX_TOKENS"):
        monkeypatch.delenv(k, raising=False)


def test_default_base_url_is_openai_and_uses_modern_params():
    assert _openai_param_style() == "modern"
    p = _openai_payload("hi", "gpt-5.6-luna", 0.2, 4096, False)
    assert p["max_completion_tokens"] == 4096
    assert "max_tokens" not in p and "temperature" not in p


def test_local_server_uses_legacy_params(monkeypatch):
    monkeypatch.setenv("OPENAI_BASE_URL", "http://localhost:8000/v1")
    assert _openai_param_style() == "legacy"
    p = _openai_payload("hi", "qwen", None, None, True)
    assert p["max_tokens"] == 8192 and p["temperature"] == 0.2 and "max_completion_tokens" not in p


@pytest.mark.parametrize("style", ["modern", "legacy"])
def test_explicit_override_wins(monkeypatch, style):
    monkeypatch.setenv("OPENAI_BASE_URL", "http://localhost:8000/v1" if style == "modern" else "https://api.openai.com/v1")
    monkeypatch.setenv("OPENAI_PARAM_STYLE", style)
    assert _openai_param_style() == style


def test_openai_subdomains_count_as_openai(monkeypatch):
    monkeypatch.setenv("OPENAI_BASE_URL", "https://eu.api.openai.com/v1")
    assert _openai_param_style() == "modern"
