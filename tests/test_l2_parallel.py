"""Layer 2 runs its themes on a thread pool when the provider takes concurrent calls.

Serial (pool of 1) must behave as before; parallel must give the same final result,
in THEME_SPECS order, without token events, and actually overlap the calls.
"""
import json
import re
import time
from pathlib import Path

import pytest

import src.llm_agent as llm_agent
from src.html_to_json import parse_html
from src.linter_renderer import lint

CASE = Path(__file__).resolve().parents[1] / "examples" / "head-to-head" / "1" / "good.html"


def _answer(prompt):
    theme = re.search(r"^Theme key: (\w+)", prompt, re.M).group(1)
    score = len(theme) % 4  # deterministic, differs across themes
    return json.dumps({theme: {"score": score, "rationale": f"r-{theme}"},
                       "questions": [{"field_path": theme, "question": f"q-{theme}", "blocking": False}]})


@pytest.fixture(scope="module")
def protocol():
    inst = parse_html(CASE.read_text(encoding="utf-8"))
    return inst, lint(inst, profile="default")


@pytest.fixture
def fake_llm(monkeypatch):
    monkeypatch.setattr(llm_agent, "call_llm", lambda p, **_: _answer(p))
    monkeypatch.setattr(llm_agent, "call_llm_stream", lambda p, **_: iter([_answer(p)]))


def _run(monkeypatch, protocol, parallel):
    monkeypatch.setenv("LLM_PARALLEL", str(parallel))
    return list(llm_agent.run_verification_stream(*protocol))


def test_parallel_result_matches_serial(monkeypatch, protocol, fake_llm):
    serial = _run(monkeypatch, protocol, 1)[-1]["result"]
    order = list(llm_agent.active_theme_specs())

    def reversed_finish(p, **_):  # later themes answer first, so completion order != THEME_SPECS order
        theme = re.search(r"^Theme key: (\w+)", p, re.M).group(1)
        time.sleep(0.02 * (len(order) - order.index(theme)))
        return _answer(p)
    monkeypatch.setattr(llm_agent, "call_llm", reversed_finish)
    parallel = _run(monkeypatch, protocol, 12)[-1]["result"]
    assert parallel == serial
    assert list(parallel["themes"]) == list(llm_agent.active_theme_specs())


def test_parallel_events_count_finished_themes_and_skip_tokens(monkeypatch, protocol, fake_llm):
    events = _run(monkeypatch, protocol, 12)
    total = len(llm_agent.active_theme_specs())
    assert not [e for e in events if e["type"] == "token"]
    assert [e["progress"] for e in events if e["type"] == "theme_done"] == list(range(1, total + 1))
    assert all(e["total"] == total for e in events if e["type"] in ("theme_start", "theme_done"))
    assert events[-1]["type"] == "complete"


def test_serial_still_streams_tokens(monkeypatch, protocol, fake_llm):
    events = _run(monkeypatch, protocol, 1)
    assert [e for e in events if e["type"] == "token"]
    starts = [e["progress"] for e in events if e["type"] == "theme_start"]
    assert starts == list(range(1, len(starts) + 1))


def test_parallel_calls_overlap(monkeypatch, protocol):
    def slow(p, **_):
        time.sleep(0.2)
        return _answer(p)
    monkeypatch.setattr(llm_agent, "call_llm", slow)
    t0 = time.monotonic()
    _run(monkeypatch, protocol, 12)
    # serial would be themes x 2 passes x 0.2 s (~4.4 s for 11 themes)
    assert time.monotonic() - t0 < 1.5


def test_a_bug_in_a_worker_surfaces(monkeypatch, protocol, fake_llm):
    def broken(*a, **k):
        raise ValueError("prompt builder bug")
    monkeypatch.setattr(llm_agent, "_build_theme_prompt", broken)
    with pytest.raises(ValueError, match="prompt builder bug"):
        _run(monkeypatch, protocol, 12)


@pytest.mark.parametrize("provider,env,expected", [
    ("openai", "", 12), ("anthropic", "", 12), ("ollama", "", 1), ("ollama", "4", 4), ("openai", "nope", 12),
])
def test_pool_size_defaults(monkeypatch, provider, env, expected):
    monkeypatch.setenv("LLM_PARALLEL", env)
    assert llm_agent._parallel_themes(provider) == expected
