"""PI questions: pass 2's list replaces pass 1's, and 'blocking' must be asserted, not copied."""
import json
import re
from pathlib import Path

import pytest

import src.llm_agent as llm_agent
from src.html_to_json import parse_html
from src.linter_renderer import lint

CASE = Path(__file__).resolve().parents[1] / "examples" / "head-to-head" / "1" / "good.html"


@pytest.mark.parametrize("raw,expected", [
    (True, True), ("true", True), (" TRUE ", True),
    (False, False), ("false", False), (None, False), (1, False),
    ("true only if the committee could not approve the protocol without this answer, else false", False),
])
def test_blocking_is_parsed_strictly(raw, expected):
    q = llm_agent._normalize_questions([{"field_path": "x", "question": "q?", "blocking": raw}])
    assert q[0]["blocking"] is expected


def test_prompt_no_longer_shows_blocking_true_as_the_example():
    shape = json.dumps(llm_agent._build_expected_theme_shape("sex_and_reuse"))
    assert '"blocking": true' not in shape


@pytest.fixture(scope="module")
def protocol():
    inst = parse_html(CASE.read_text(encoding="utf-8"))
    return inst, lint(inst, profile="default")


def _llm(fail_reconcile):
    def answer(prompt, **_):
        theme = re.search(r"^Theme key: (\w+)", prompt, re.M).group(1)
        blind = "Pass 1 (blind review)" in prompt
        if not blind and fail_reconcile:
            raise RuntimeError("provider down")
        tag = "p1" if blind else "p2"
        return json.dumps({theme: {"score": 2, "rationale": tag},
                           "questions": [{"field_path": "alternatives_search", "question": f"{tag} {theme}?", "blocking": False}]})
    return answer


@pytest.mark.parametrize("parallel", ["1", "12"])
def test_pass2_questions_replace_pass1(monkeypatch, protocol, parallel):
    monkeypatch.setenv("LLM_PARALLEL", parallel)
    monkeypatch.setattr(llm_agent, "call_llm", _llm(False))
    monkeypatch.setattr(llm_agent, "call_llm_stream", lambda p, **k: iter([_llm(False)(p)]))
    qs = list(llm_agent.run_verification_stream(*protocol))[-1]["result"]["questions"]
    assert qs and all(q["question"].startswith("p2 ") for q in qs)
    assert len(qs) == len(llm_agent.active_theme_specs())


def test_pass1_questions_kept_when_reconcile_fails(monkeypatch, protocol):
    monkeypatch.setenv("LLM_PARALLEL", "12")
    monkeypatch.setattr(llm_agent, "call_llm", _llm(True))
    qs = list(llm_agent.run_verification_stream(*protocol))[-1]["result"]["questions"]
    assert qs and all(q["question"].startswith("p1 ") for q in qs)
