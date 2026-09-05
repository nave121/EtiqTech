"""P0.3 runtime hygiene: context-budget guard, thread-safe session cache, no root-logger hijack."""
import logging
import threading
from datetime import datetime, timedelta

import pytest

from src.llm_clients import context_budget_warning, estimate_tokens
import server.app as app_module


def test_estimate_tokens_is_chars_over_four():
    assert estimate_tokens("a" * 400) == 100


def test_budget_warning_none_when_prompt_fits(monkeypatch):
    monkeypatch.setenv("OLLAMA_NUM_CTX", "32768")
    monkeypatch.setenv("LLM_MAX_TOKENS", "8192")
    assert context_budget_warning("x" * 4000, label="t") is None


@pytest.mark.parametrize("chars,overflow", [(int(0.9 * 24576 * 4), False), (30000 * 4, True)])
def test_budget_warning_shape(monkeypatch, chars, overflow, caplog):
    monkeypatch.setenv("OLLAMA_NUM_CTX", "32768")
    monkeypatch.setenv("LLM_MAX_TOKENS", "8192")
    with caplog.at_level(logging.WARNING, logger="src.llm_clients"):
        w = context_budget_warning("x" * chars, label="Layer 3 / pass 1")
    assert w["type"] == "warning" and w["code"] == "context_budget"
    assert w["overflow"] is overflow
    assert w["available_tokens"] == 24576
    assert "Layer 3 / pass 1" in w["message"]
    assert any("context budget" in r.message for r in caplog.records)


def test_layer2_stream_emits_budget_warning_once(monkeypatch):
    from src import llm_agent
    monkeypatch.setenv("OLLAMA_NUM_CTX", "1024")   # tiny window: every theme prompt overflows
    monkeypatch.setenv("LLM_MAX_TOKENS", "512")
    monkeypatch.setattr(llm_agent, "call_llm_stream", lambda *a, **k: iter(["{}"]))
    events = list(llm_agent.run_verification_stream({"header": {}, "experiments": []}, {"checklist": []}))
    warnings = [e for e in events if e["type"] == "warning"]
    assert len(warnings) == 1 and warnings[0]["code"] == "context_budget"
    assert events[-1]["type"] == "complete"


def test_llm_clients_import_does_not_configure_root_logger():
    import importlib, src.llm_clients
    root = logging.getLogger()
    before = list(root.handlers)
    importlib.reload(src.llm_clients)
    assert root.handlers == before


def test_session_cache_survives_concurrent_store_and_cleanup():
    app_module._analysis_cache.clear()
    old = {"created_at": datetime.now() - timedelta(hours=2)}
    errors = []

    def worker(i):
        try:
            for _ in range(50):
                app_module._store_session({**old} if i % 2 else {"created_at": datetime.now()})
        except Exception as e:  # RuntimeError: dict changed size during iteration, KeyError, ...
            errors.append(e)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors
    assert len(app_module._analysis_cache) <= app_module.MAX_SESSIONS
    app_module._analysis_cache.clear()
