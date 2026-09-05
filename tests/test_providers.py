"""P3.4 provider contract tests with recorded responses: same text/stream surface for every provider,
every provider behind the local-first gate, no redirects, credentials only in headers."""
import json
import types

import pytest
import requests

from src import llm_clients
from src.llm_clients import LLMError, PROVIDERS, call_llm, call_llm_stream, provider_name


class _Resp:
    def __init__(self, status=200, body=None, lines=None):
        self.status_code = status
        self._body = body
        self._lines = lines or []
        self.text = json.dumps(body) if body is not None else ""
    def json(self):
        return self._body
    def iter_lines(self):
        return iter(self._lines)


# ---- recorded responses -------------------------------------------------------
OPENAI_CHAT = {"id": "chatcmpl-1", "choices": [{"index": 0, "message": {"role": "assistant", "content": '{"a": 1}'}, "finish_reason": "stop"}],
               "usage": {"prompt_tokens": 10, "completion_tokens": 4}}
OPENAI_STREAM = [
    b'data: {"choices":[{"delta":{"role":"assistant"},"index":0}]}',
    b'',
    b'data: {"choices":[{"delta":{"content":"{\\"a\\""},"index":0}]}',
    b'data: {"choices":[{"delta":{"content":": 1}"},"index":0}]}',
    b'data: {"choices":[{"delta":{},"finish_reason":"stop","index":0}]}',
    b'data: [DONE]',
]


def test_provider_aliases_and_unknown():
    assert provider_name("OpenAI-Compatible") == "openai" and provider_name("vllm") == "openai"
    with pytest.raises(LLMError, match="Unsupported"):
        provider_name("bard")


def test_registry_has_capabilities_for_docs():
    for name, spec in PROVIDERS.items():
        assert {"base_url_env", "base_url_default", "model_env", "key_env", "streaming", "json_mode", "thinking", "two_step", "local_capable"} <= set(spec), name


# ---- OpenAI-compatible -----------------------------------------------------------

def test_openai_compat_local_server_needs_no_opt_in(monkeypatch):
    monkeypatch.setenv("OPENAI_BASE_URL", "http://localhost:8000/v1")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("OPENAI_MODEL", "local-model")
    monkeypatch.delenv("ETIQTECH_ALLOW_REMOTE_LLM", raising=False)
    seen = {}
    def fake_post(url, json=None, headers=None, **kw):
        seen.update(url=url, json=json, headers=headers, kw=kw)
        return _Resp(body=OPENAI_CHAT)
    monkeypatch.setattr(requests, "post", fake_post)
    assert call_llm("prompt", provider="openai") == '{"a": 1}'
    assert seen["url"] == "http://localhost:8000/v1/chat/completions"
    assert seen["headers"] == {"Authorization": "Bearer sk-test"} and seen["kw"]["allow_redirects"] is False
    assert seen["json"]["model"] == "local-model" and seen["json"]["messages"][0]["content"] == "prompt"
    assert "sk-test" not in json.dumps(seen["json"])  # key travels in the header only


def test_openai_compat_public_endpoint_refused_without_flag(monkeypatch):
    monkeypatch.setenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
    monkeypatch.setenv("OPENAI_MODEL", "m")
    monkeypatch.delenv("ETIQTECH_ALLOW_REMOTE_LLM", raising=False)
    monkeypatch.setattr(requests, "post", lambda *a, **k: pytest.fail("must not send"))
    with pytest.raises(LLMError, match="ETIQTECH_ALLOW_REMOTE_LLM"):
        call_llm("prompt", provider="openai")


def test_openai_compat_requires_a_model(monkeypatch):
    monkeypatch.setenv("OPENAI_BASE_URL", "http://localhost:8000/v1")
    monkeypatch.delenv("OPENAI_MODEL", raising=False)
    with pytest.raises(LLMError, match="OPENAI_MODEL"):
        call_llm("prompt", provider="openai")


def test_openai_compat_stream_parses_sse_chunks(monkeypatch):
    monkeypatch.setenv("OPENAI_BASE_URL", "http://localhost:8000/v1")
    monkeypatch.setenv("OPENAI_MODEL", "m")
    monkeypatch.setattr(requests, "post", lambda *a, **k: _Resp(lines=OPENAI_STREAM))
    assert "".join(call_llm_stream("prompt", provider="openai")) == '{"a": 1}'


def test_openai_compat_errors_are_llm_errors(monkeypatch):
    monkeypatch.setenv("OPENAI_BASE_URL", "http://localhost:8000/v1")
    monkeypatch.setenv("OPENAI_MODEL", "m")
    monkeypatch.setattr(requests, "post", lambda *a, **k: _Resp(status=302))
    with pytest.raises(LLMError, match="302"):
        call_llm("prompt", provider="openai")
    monkeypatch.setattr(requests, "post", lambda *a, **k: _Resp(body={"choices": []}))
    with pytest.raises(LLMError, match="unexpected shape"):
        call_llm("prompt", provider="openai")


# ---- Anthropic (SDK faked; the adapter only depends on messages.create / messages.stream) ----

class _Block:
    def __init__(self, type_, text=""):
        self.type, self.text = type_, text


class _Message:
    def __init__(self, blocks, stop_reason="end_turn"):
        self.content, self.stop_reason = blocks, stop_reason


class _Stream:
    def __init__(self, chunks, final):
        self.text_stream, self._final = iter(chunks), final
    def __enter__(self):
        return self
    def __exit__(self, *a):
        return False
    def get_final_message(self):
        return self._final


class _FakeAnthropic:
    def __init__(self, message, chunks=()):
        self.calls = []
        self.messages = types.SimpleNamespace(create=self._create, stream=self._stream)
        self._message, self._chunks = message, chunks
    def _create(self, **kw):
        self.calls.append(kw); return self._message
    def _stream(self, **kw):
        self.calls.append(kw); return _Stream(self._chunks, self._message)


@pytest.fixture
def anthropic_allowed(monkeypatch):
    monkeypatch.setenv("ETIQTECH_ALLOW_REMOTE_LLM", "1")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    monkeypatch.delenv("ANTHROPIC_MODEL", raising=False)


def test_anthropic_text_and_stream_parity(monkeypatch, anthropic_allowed):
    fake = _FakeAnthropic(_Message([_Block("thinking", ""), _Block("text", '{"a": '), _Block("text", '1}')]), chunks=['{"a": ', "1}"])
    monkeypatch.setattr(llm_clients, "_anthropic_client", lambda: fake)
    assert call_llm("prompt", provider="anthropic") == '{"a": 1}'
    assert "".join(call_llm_stream("prompt", provider="anthropic")) == '{"a": 1}'
    for kw in fake.calls:
        assert kw["model"] == "claude-opus-5" and kw["messages"] == [{"role": "user", "content": "prompt"}]
        assert "temperature" not in kw and "thinking" not in kw  # sampling params are rejected by current models


def test_anthropic_refusal_is_an_llm_error(monkeypatch, anthropic_allowed):
    fake = _FakeAnthropic(_Message([], stop_reason="refusal"))
    monkeypatch.setattr(llm_clients, "_anthropic_client", lambda: fake)
    with pytest.raises(LLMError, match="refus"):
        call_llm("prompt", provider="anthropic")


def test_anthropic_is_always_remote_and_gated(monkeypatch):
    monkeypatch.delenv("ETIQTECH_ALLOW_REMOTE_LLM", raising=False)
    monkeypatch.delenv("ANTHROPIC_BASE_URL", raising=False)
    with pytest.raises(LLMError, match="ETIQTECH_ALLOW_REMOTE_LLM"):
        call_llm("prompt", provider="anthropic")


def test_anthropic_sdk_error_does_not_leak_details(monkeypatch, anthropic_allowed):
    class Boom:
        messages = types.SimpleNamespace(create=lambda **kw: (_ for _ in ()).throw(RuntimeError("secret sk-ant-xyz in message")))
    monkeypatch.setattr(llm_clients, "_anthropic_client", lambda: Boom())
    with pytest.raises(LLMError) as ei:
        call_llm("prompt", provider="anthropic")
    assert "sk-ant" not in str(ei.value)


# ---- server surface ---------------------------------------------------------------

def test_llm_providers_endpoint_lists_configured_only(monkeypatch):
    from server.app import app
    for k in ("OPENAI_API_KEY", "OPENAI_BASE_URL", "ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ETIQTECH_ALLOW_REMOTE_LLM"):
        monkeypatch.delenv(k, raising=False)
    with app.test_client() as c:
        body = c.get("/api/llm-providers").get_json()
    assert [p["name"] for p in body["providers"]] == ["ollama"]
    monkeypatch.setenv("ANTHROPIC_API_KEY", "x")
    with app.test_client() as c:
        body = c.get("/api/llm-providers").get_json()
    anth = next(p for p in body["providers"] if p["name"] == "anthropic")
    assert anth["local"] is False and anth["usable"] is False  # remote and not opted in -> shown but disabled


def test_openai_compat_midstream_error_event_raises(monkeypatch):
    monkeypatch.setenv("OPENAI_BASE_URL", "http://localhost:8000/v1")
    monkeypatch.setenv("OPENAI_MODEL", "m")
    lines = [b'data: {"choices":[{"delta":{"content":"partial"},"index":0}]}',
             b'data: {"error":{"type":"rate_limit_exceeded","message":"slow down"}}', b'data: [DONE]']
    monkeypatch.setattr(requests, "post", lambda *a, **k: _Resp(lines=lines))
    with pytest.raises(LLMError, match="rate_limit_exceeded"):
        list(call_llm_stream("prompt", provider="openai"))


def test_openai_compat_http_error_body_stays_out_of_the_message(monkeypatch):
    monkeypatch.setenv("OPENAI_BASE_URL", "http://localhost:8000/v1")
    monkeypatch.setenv("OPENAI_MODEL", "m")
    r = _Resp(status=400, body={"error": {"message": "echoing your prompt: SECRET-PROTOCOL-TEXT"}})
    monkeypatch.setattr(requests, "post", lambda *a, **k: r)
    with pytest.raises(LLMError) as ei:
        call_llm("prompt", provider="openai")
    assert "SECRET-PROTOCOL-TEXT" not in str(ei.value) and "400" in str(ei.value)


def test_two_step_honours_the_request_provider(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "ollama")
    monkeypatch.setenv("OPENAI_BASE_URL", "http://localhost:8000/v1")
    monkeypatch.setenv("OPENAI_MODEL", "m")
    seen = []
    monkeypatch.setattr(requests, "post", lambda url, **k: seen.append(url) or _Resp(body=OPENAI_CHAT))
    llm_clients.call_llm_two_step("prompt", provider="openai")
    assert seen == ["http://localhost:8000/v1/chat/completions"], seen  # not the Ollama /api/chat two-step


def test_anthropic_client_never_follows_redirects(monkeypatch):
    anthropic = pytest.importorskip("anthropic")
    monkeypatch.setenv("ETIQTECH_ALLOW_REMOTE_LLM", "1")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    client = llm_clients._anthropic_client()
    assert client._client.follow_redirects is False
