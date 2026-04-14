"""
Layer 3 "Human Eye" contract and behavioral tests.

All tests are deterministic and mock LLM calls.
"""

import json
from unittest.mock import patch

import pytest
from pydantic import ValidationError

from src.contracts import HumanEyeResult
from src.linter_renderer import lint
from src.llm_agent import THEME_SPECS
from src.llm_layer3 import run_human_eye, run_human_eye_stream, should_trigger_layer3


def _minimal_instance():
    return {
        "header": {"protocol_id": "99999", "institution": "Test"},
        "research": {
            "title_he": "כותרת", "title_en": "Title", "request_type": "regular",
            "is_continuation": False, "third_party_service": False,
            "approval_term_years": 3, "sites": [],
        },
        "pi": {
            "id_type": "TZ", "id_number": "1", "last_name_he": "כ", "first_name_he": "ד",
            "last_name_en": "K", "first_name_en": "D", "email": "d@t.il",
            "phone_primary": "050", "phone_secondary": "", "institutional_cert_no": "C1",
            "faculty": "Med", "department": "Bio",
            "training": [{"cert_no": "C1", "issuer": "T", "animal_scope": "rodents", "date": "2023-01-01"}],
        },
        "participants": [],
        "summaries": {"scientific_en_≤300w": "Short.", "lay_he_≤150w": "קצר."},
        "alternatives_search": {
            "engines": ["PubMed"], "date": "2025-01-01",
            "queries": ["query"], "conclusion": "No alternative.",
        },
        "animals_total": [
            {"species": "mouse", "strain": "C57BL/6", "sex": "both",
             "genetic_status": "WT", "source": "vendor", "n_total": 20}
        ],
        "n_justification": {"method": "power", "details": "Power analysis.", "attachments": []},
        "experiments": [
            {
                "label": "Exp 1", "question": "Does X affect Y?",
                "animals": {"species": "mouse", "strain": "C57BL/6", "sex": "both",
                            "genetic_status": "WT", "n": 20},
                "housing": {"group_housed": True},
                "procedure_timeline": [], "analgesia": [], "anesthesia": [],
                "severity_level_1_to_5": 1,
                "monitoring": {"plan": "Daily."},
                "humane_endpoints": {"general": [], "specific": []},
                "euthanasia": {"primary": "cervical dislocation", "parameters": "", "confirmation": ""},
                "fate": "euthanized",
            }
        ],
        "pi_declaration": {"affirmed": True},
        "is_colony": False,
    }


def _good_layer2_result():
    return {
        "themes": {
            key: {
                "score": 3,
                "label": "adequate",
                "rationale": "Good.",
                "sub_questions": [
                    {
                        "question": question,
                        "score": 3,
                        "label": "adequate",
                        "rationale": "Good.",
                    }
                    for question in THEME_SPECS[key]["sub_questions"]
                ],
            }
            for key in THEME_SPECS
        },
        "questions": [],
        "checklist_items": [],
    }


def _canned_pass1_response() -> str:
    return json.dumps({
        "sections": [
            {
                "section": "Alternatives Search",
                "status": "Deficiency",
                "severity": "Major",
                "finding": "Search conclusion is generic.",
                "regulatory_basis": "Israeli Law Art. 17",
                "explanation": "The conclusion does not describe what alternatives were considered.",
                "action_required": "Provide a substantive alternatives conclusion.",
            }
        ]
    })


def _canned_pass2_response() -> str:
    return json.dumps({
        "cross_reference_issues": [],
        "overall_verdict": "revise_minor",
        "risk_profile": "medium",
        "summary": "Protocol is mostly compliant but the alternatives search needs improvement.",
    })


def test_human_eye_result_contract():
    instance = _minimal_instance()
    report = lint(instance, profile="strict_law")

    call_count = [0]

    def fake_call_llm(prompt, **kwargs):
        call_count[0] += 1
        if call_count[0] == 1:
            return _canned_pass1_response()
        return _canned_pass2_response()

    with patch("src.llm_layer3.call_llm", side_effect=fake_call_llm):
        result = run_human_eye(instance, report, force=True)

    try:
        HumanEyeResult.model_validate(result)
    except ValidationError as exc:
        pytest.fail(f"HumanEyeResult contract violated:\n{exc}")


def test_layer3_skips_when_trigger_false():
    instance = _minimal_instance()
    report = lint(instance, profile="default")
    layer2 = _good_layer2_result()

    triggered, reason = should_trigger_layer3(report, layer2, instance, sampling_rate=0.0)
    assert not triggered, f"Expected no trigger, got reason: {reason!r}"

    with patch("src.llm_layer3.call_llm") as mock_llm:
        result = run_human_eye(instance, report, layer2, force=False)

    assert result["skipped"] is True
    mock_llm.assert_not_called()


def test_layer3_triggers_on_layer1_errors():
    instance = _minimal_instance()
    report = lint(instance, profile="strict_law")
    report["checklist"].append({
        "status": "fail",
        "severity": "error",
        "message": "Synthetic test error",
        "reference": "test:synthetic",
        "suggested_fix": None,
    })

    triggered, reason = should_trigger_layer3(report, None, instance, sampling_rate=0.0)
    assert triggered, "Expected trigger on layer1 errors"
    assert reason == "layer1_errors"


def test_layer3_triggers_on_low_score():
    instance = _minimal_instance()
    report = lint(instance, profile="default")

    layer2 = _good_layer2_result()
    layer2["themes"]["N_and_justification"]["score"] = 1
    layer2["themes"]["N_and_justification"]["label"] = "inadequate"

    triggered, reason = should_trigger_layer3(report, layer2, instance, sampling_rate=0.0)
    assert triggered, "Expected trigger on low score"
    assert reason == "layer2_low_score"


def test_layer3_stream_event_sequence():
    instance = _minimal_instance()
    report = lint(instance, profile="default")

    call_count = [0]

    def fake_stream(prompt, **kwargs):
        call_count[0] += 1
        payload = _canned_pass1_response() if call_count[0] == 1 else _canned_pass2_response()
        for ch in payload:
            yield ch

    with patch("src.llm_layer3.call_llm_stream", side_effect=fake_stream):
        events = list(run_human_eye_stream(instance, report, force=True))

    types = [e["type"] for e in events]
    assert types[0] == "layer3_trigger", f"First event must be layer3_trigger, got: {types[0]}"
    assert types[-1] == "complete", f"Last event must be complete, got: {types[-1]}"

    pass_starts = [e for e in events if e["type"] == "pass_start"]
    assert len(pass_starts) == 2, f"Expected 2 pass_start events, got {len(pass_starts)}"
    assert pass_starts[0]["pass"] == 1
    assert pass_starts[1]["pass"] == 2

    pass_dones = [e for e in events if e["type"] == "pass_done"]
    assert len(pass_dones) == 2, f"Expected 2 pass_done events, got {len(pass_dones)}"

    for pass_num in (1, 2):
        start_idx = next(i for i, e in enumerate(events) if e["type"] == "pass_start" and e.get("pass") == pass_num)
        done_idx = next(i for i, e in enumerate(events) if e["type"] == "pass_done" and e.get("pass") == pass_num)
        assert start_idx < done_idx, f"pass_start({pass_num}) must precede pass_done({pass_num})"

    complete = events[-1]
    assert "result" in complete
    assert "overall_verdict" in complete["result"]
    assert "sections" in complete["result"]


def test_additive_union():
    instance = _minimal_instance()
    report = lint(instance, profile="strict_law")
    original_checklist = [dict(c) for c in report["checklist"]]

    call_count = [0]

    def fake_call_llm(prompt, **kwargs):
        call_count[0] += 1
        if call_count[0] == 1:
            return _canned_pass1_response()
        return _canned_pass2_response()

    with patch("src.llm_layer3.call_llm", side_effect=fake_call_llm):
        run_human_eye(instance, report, force=True)

    assert report["checklist"] == original_checklist
