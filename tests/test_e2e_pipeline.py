import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest
import requests

from src.html_to_json import parse_html
from src.linter_renderer import lint
from src.llm_agent import THEME_SPECS, run_verification
from src.llm_layer3 import run_human_eye


REPO_ROOT = Path(__file__).resolve().parents[1]
GOOD_HTML = (
    REPO_ROOT
    / "examples"
    / "known-good"
    / "good_IL-010-05-2000.html"
)
BAD_HTML = (
    REPO_ROOT
    / "examples"
    / "known-bad"
    / "bad_IL-019-07-2000.html"
)
FALLBACK_LAYER3_SUMMARY = (
    "Layer 3 could not complete review due to an LLM error; "
    "defaulting to revise_major."
)


def _load_report(html_path: Path):
    html_content = html_path.read_text(encoding="utf-8")
    instance = parse_html(html_content)
    report = lint(instance, profile="default")
    return instance, report


def _theme_key_from_prompt(prompt: str) -> str:
    for theme_key in THEME_SPECS:
        if theme_key in prompt:
            return theme_key
    raise AssertionError(
        f"Could not determine theme from prompt: {prompt[:200]!r}"
    )


def _theme_response(
    theme_key: str,
    *,
    score: int,
    label: str,
    rationale: str,
    questions=None,
) -> str:
    return json.dumps(
        {
            theme_key: {
                "score": score,
                "label": label,
                "rationale": rationale,
            },
            "questions": questions or [],
        }
    )


def _layer3_pass1() -> str:
    return json.dumps(
        {
            "sections": [
                {
                    "section": "Scientific coherence",
                    "status": "Deficiency",
                    "severity": "Major",
                    "finding": "Animal numbers are inconsistent.",
                    "regulatory_basis": "Israeli Law §8(b)",
                    "explanation": (
                        "The totals table does not reconcile with the "
                        "experiment counts."
                    ),
                    "action_required": (
                        "Correct the declared total animal counts."
                    ),
                }
            ]
        }
    )


def _layer3_pass2() -> str:
    return json.dumps(
        {
            "cross_reference_issues": [
                {
                    "fields": ["animals_total", "experiments"],
                    "issue": "Layer 1 and Layer 2 both identified an animal "
                    "numbers mismatch.",
                    "severity": "Major",
                }
            ],
            "overall_verdict": "revise_major",
            "risk_profile": "high",
            "summary": (
                "Numbers inconsistency requires revision before review can "
                "continue."
            ),
        }
    )


def _all_ok_theme_side_effect(prompt: str, **kwargs) -> str:
    theme_key = _theme_key_from_prompt(prompt)
    return _theme_response(
        theme_key,
        score=3,
        label="adequate",
        rationale=f"{theme_key} is acceptable for this protocol.",
    )


def test_e2e_clean_protocol_skips_layer3_when_all_layers_are_clean():
    instance, report = _load_report(GOOD_HTML)

    assert report["status"] == "pass"
    assert report["errors"] == 0
    assert (
        max(
            exp["severity_level_1_to_5"]
            for exp in instance["experiments"]
        ) < 3
    )

    with patch(
        "src.llm_agent.call_llm",
        side_effect=_all_ok_theme_side_effect,
    ):
        layer2 = run_verification(instance, report, stance="committee")

    assert set(layer2["themes"]) == set(THEME_SPECS)
    assert all(
        theme["label"] == "adequate"
        for theme in layer2["themes"].values()
    )

    with patch("src.llm_layer3.call_llm") as mock_layer3:
        layer3 = run_human_eye(instance, report, layer2, force=False)

    assert layer3["skipped"] is True
    assert layer3["overall_verdict"] == "approve"
    mock_layer3.assert_not_called()


def test_e2e_known_bad_protocol_triggers_layer3_on_layer1_errors():
    instance, report = _load_report(BAD_HTML)

    assert report["status"] == "fail"
    assert any(
        item["reference"] == "animals:totals-vs-exps"
        and item["status"] == "fail"
        and item["severity"] == "error"
        for item in report["checklist"]
    )

    def layer2_side_effect(prompt: str, **kwargs) -> str:
        theme_key = _theme_key_from_prompt(prompt)
        score = (
            1 if theme_key == "scientific_coherence" else 3
        )
        label = (
            "inadequate"
            if theme_key == "scientific_coherence"
            else "adequate"
        )
        return _theme_response(
            theme_key,
            score=score,
            label=label,
            rationale=f"{theme_key} reviewed during E2E regression.",
        )

    with patch("src.llm_agent.call_llm", side_effect=layer2_side_effect):
        layer2 = run_verification(instance, report, stance="committee")

    llm_responses = [_layer3_pass1(), _layer3_pass2()]
    with patch("src.llm_layer3.call_llm", side_effect=llm_responses):
        layer3 = run_human_eye(instance, report, layer2, force=False)

    assert layer2["themes"]["scientific_coherence"]["label"] == "inadequate"
    assert layer3["skipped"] is False
    assert layer3["triggered_by"] == "layer1_errors"
    assert layer3["overall_verdict"] == "revise_major"
    assert layer3["cross_reference_issues"]


def test_e2e_layer_findings_propagate_through_layer2_and_layer3():
    instance, report = _load_report(BAD_HTML)
    layer2_prompts = []

    def layer2_side_effect(prompt: str, **kwargs) -> str:
        layer2_prompts.append(prompt)
        theme_key = _theme_key_from_prompt(prompt)
        if theme_key == "scientific_coherence":
            return _theme_response(
                theme_key,
                score=1,
                label="inadequate",
                rationale=(
                    "Experiment totals do not reconcile with the summary."
                ),
                questions=[
                    {
                        "field_path": "animals_total",
                        "question": (
                            "Which total N is correct after corrections?"
                        ),
                        "blocking": True,
                    }
                ],
            )
        return _theme_response(
            theme_key,
            score=3,
            label="adequate",
            rationale=(
                f"{theme_key} accepted for this propagation test."
            ),
        )

    with patch("src.llm_agent.call_llm", side_effect=layer2_side_effect):
        layer2 = run_verification(instance, report, stance="committee")

    scientific_prompts = [
        prompt for prompt in layer2_prompts
        if "scientific_coherence" in prompt
    ]
    assert len(scientific_prompts) == 2
    blind_prompt = next(
        prompt for prompt in scientific_prompts
        if "Pass 1 (blind review)" in prompt
    )
    reconcile_prompt = next(
        prompt for prompt in scientific_prompts
        if "Pass 2 (reconciliation)" in prompt
    )
    assert "animals:totals-vs-exps" not in blind_prompt
    assert '"status": "fail"' not in blind_prompt
    assert "animals:totals-vs-exps" in reconcile_prompt
    assert '"status": "fail"' in reconcile_prompt
    assert any(
        question.get("question") == "Which total N is correct after corrections?"
        for question in layer2["questions"]
    )

    layer3_prompts = []
    layer3_responses = [_layer3_pass1(), _layer3_pass2()]

    def layer3_side_effect(prompt: str, **kwargs) -> str:
        layer3_prompts.append(prompt)
        return layer3_responses[len(layer3_prompts) - 1]

    with patch("src.llm_layer3.call_llm", side_effect=layer3_side_effect):
        run_human_eye(instance, report, layer2, force=False)

    assert "animals:totals-vs-exps" not in layer3_prompts[0]
    assert '"scientific_coherence"' in layer3_prompts[1]
    assert '"label": "inadequate"' in layer3_prompts[1]
    assert "Which total N is correct after corrections?" in layer3_prompts[1]
    assert "animals:totals-vs-exps" in layer3_prompts[1]


@pytest.mark.skipif(
    os.getenv("RUN_LIVE_LLM_E2E", "").lower() not in {"1", "true", "yes"},
    reason=(
        "Set RUN_LIVE_LLM_E2E=1 to run live Ollama end-to-end smoke tests."
    ),
)
def test_live_llm_e2e_smoke():
    base_url = os.getenv(
        "OLLAMA_BASE_URL",
        "http://127.0.0.1:11434",
    ).rstrip("/")
    try:
        response = requests.get(f"{base_url}/api/tags", timeout=2)
        response.raise_for_status()
    except requests.RequestException as exc:
        pytest.skip(
            f"Ollama is not reachable for live E2E smoke testing: {exc}"
        )

    instance, report = _load_report(GOOD_HTML)

    layer2 = run_verification(instance, report, stance="committee")
    assert set(layer2["themes"]) == set(THEME_SPECS)
    assert any(
        isinstance(theme.get("score"), int)
        and 0 <= theme["score"] <= 3
        and not theme["rationale"].startswith("LLM did not return")
        and not theme["rationale"].startswith("LLM response was unavailable")
        for theme in layer2["themes"].values()
    )

    layer3 = run_human_eye(instance, report, layer2, force=True)
    assert layer3["skipped"] is False
    assert layer3["summary"] != FALLBACK_LAYER3_SUMMARY
