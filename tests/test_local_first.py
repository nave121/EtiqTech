"""P1.1: protocol text never leaves the machine unless the operator opts in explicitly."""
import pytest
import requests

from src import llm_clients
from src.llm_clients import LLMError, is_remote_llm_url, ollama_base_url
from server.app import app


@pytest.mark.parametrize("url", [
    "http://127.0.0.1:11434", "http://localhost:11434", "http://[::1]:11434",
    "http://host.docker.internal:11434", "http://ollama:11434", "http://ollama.default.svc:11434",
    "http://ollama.default.svc.cluster.local:11434", "http://10.0.0.5:11434", "http://192.168.1.20:11434",
    "http://172.16.0.9:11434", "http://gpu-box.local:11434", "http://llm.internal:11434",
])
def test_local_endpoints_need_no_opt_in(url):
    assert is_remote_llm_url(url) is False


@pytest.mark.parametrize("url", [
    "https://ollama.com", "https://api.openai.com/v1", "http://8.8.8.8:11434",
    "https://my-gpu.example.org:11434", "",
])
def test_public_endpoints_are_remote(url):
    assert is_remote_llm_url(url) is True


def test_remote_url_refused_without_flag(monkeypatch):
    monkeypatch.setenv("OLLAMA_BASE_URL", "https://ollama.com")
    monkeypatch.delenv("ETIQTECH_ALLOW_REMOTE_LLM", raising=False)
    sent = []
    monkeypatch.setattr(requests, "post", lambda *a, **k: sent.append(a) or pytest.fail("must not send"))
    with pytest.raises(LLMError, match="ETIQTECH_ALLOW_REMOTE_LLM"):
        ollama_base_url()
    with pytest.raises(LLMError):
        llm_clients.call_llm("prompt", provider="ollama", model="m")
    with pytest.raises(LLMError):
        list(llm_clients.call_llm_stream("prompt", provider="ollama", model="m"))
    assert sent == []


def test_remote_url_allowed_with_flag(monkeypatch):
    monkeypatch.setenv("OLLAMA_BASE_URL", "https://ollama.com/")
    monkeypatch.setenv("ETIQTECH_ALLOW_REMOTE_LLM", "1")
    assert ollama_base_url() == "https://ollama.com"


def test_health_exposes_llm_locality(monkeypatch):
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://ollama:11434")
    with app.test_client() as c:
        body = c.get("/api/health").get_json()
    assert body["llm_local"] is True and body["llm_remote_allowed"] is False


def test_model_list_proxy_goes_through_gate(monkeypatch):
    monkeypatch.setenv("OLLAMA_BASE_URL", "https://ollama.com")
    monkeypatch.delenv("ETIQTECH_ALLOW_REMOTE_LLM", raising=False)
    import server.app as app_module
    monkeypatch.setattr(app_module.http_requests, "get", lambda *a, **k: pytest.fail("must not reach remote"))
    with app.test_client() as c:
        body = c.get("/api/ollama-models").get_json()
    assert body["success"] is False and body["models"] == []


def test_ollama_calls_never_follow_redirects(monkeypatch):
    """A 3xx from a 'local' Ollama must not carry the protocol (and API key) elsewhere."""
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434")
    seen = []

    class _Resp:
        status_code = 200
        text = ""
        def json(self):
            return {"response": "ok", "message": {"content": "ok"}}
        def iter_lines(self):
            return iter([b'{"response": "ok", "done": true}'])

    def fake_post(url, **kwargs):
        seen.append(kwargs.get("allow_redirects"))
        return _Resp()
    monkeypatch.setattr(requests, "post", fake_post)
    llm_clients.call_llm("p", provider="ollama", model="m")
    list(llm_clients.call_llm_stream("p", provider="ollama", model="m"))
    llm_clients.call_llm_two_step("p", model="m")
    assert seen and all(v is False for v in seen), seen


def test_gate_error_does_not_echo_endpoint(monkeypatch):
    monkeypatch.setenv("OLLAMA_BASE_URL", "https://secret-gpu.example.org:11434")
    monkeypatch.delenv("ETIQTECH_ALLOW_REMOTE_LLM", raising=False)
    with pytest.raises(LLMError) as ei:
        ollama_base_url()
    assert "secret-gpu" not in str(ei.value)


def test_redirect_response_is_refused_not_parsed(monkeypatch):
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434")

    class _Redirect:
        status_code = 302
        text = ""
        headers = {"Location": "https://evil.example/collect"}
        def json(self):
            pytest.fail("a 3xx body must never be parsed")
        def iter_lines(self):
            pytest.fail("a 3xx body must never be streamed")
    monkeypatch.setattr(requests, "post", lambda *a, **k: _Redirect())
    with pytest.raises(LLMError, match="302"):
        llm_clients.call_llm("p", provider="ollama", model="m")
    with pytest.raises(LLMError, match="302"):
        list(llm_clients.call_llm_stream("p", provider="ollama", model="m"))
    with pytest.raises(LLMError, match="302"):
        llm_clients.call_llm_two_step("p", model="m")
    import server.app as app_module
    monkeypatch.setattr(app_module.http_requests, "get", lambda *a, **k: _Redirect())
    with app.test_client() as c:
        assert c.get("/api/ollama-models").get_json()["success"] is False
