"""
LLM verification output contract tests.

These tests validate the shape and behavioral invariants of run_verification()
and run_verification_stream() without requiring Ollama to be running.
"""

import json
from unittest.mock import patch

import pytest
from pydantic import ValidationError

from src.contracts import VerifierResult
from src.linter_renderer import lint
from src.llm_agent import THEME_SPECS, run_verification, run_verification_stream


ALL_THEME_KEYS = list(THEME_SPECS.keys())
assert len(ALL_THEME_KEYS) == 12, "Expected 12 LLM themes"

HAZARDOUS_REF_PREFIXES = [
    "special:biosafety",
    "gma:ibc",
    "hazard:ehs",
    "hazard:radiation",
]
SURGICAL_SUB_QUESTIONS = [
    "Is aseptic technique described for survival surgery?",
    "Is the distinction between major and minor surgery clearly made?",
    "For multiple survival surgeries, is there written scientific justification that is not based solely on cost savings or animal-number reduction?",
    "Is a post-operative care plan specified with monitoring frequency, analgesic protocol, criteria for veterinary intervention, weekend or holiday monitoring, and thermal support during recovery?",
]
SEVERITY_CATEGORY_E_QUESTION = (
    "For Category E procedures, is there written scientific justification for withholding pain relief?"
)


def _graded_theme_payload(theme_key: str, score: int = 3) -> dict:
    return {
        theme_key: {
            "score": score,
            "label": {
                0: "not_addressed",
                1: "inadequate",
                2: "partially_adequate",
                3: "adequate",
            }[score],
            "rationale": f"Canned rationale for {theme_key}.",
            "sub_questions": [
                {
                    "question": question,
                    "score": score,
                    "label": {
                        0: "not_addressed",
                        1: "inadequate",
                        2: "partially_adequate",
                        3: "adequate",
                    }[score],
                    "rationale": f"Canned rationale for {question}",
                }
                for question in THEME_SPECS[theme_key]["sub_questions"]
            ],
        },
        "questions": [],
    }


def _minimal_instance():
    return {
        "header": {"protocol_id": "99999", "institution": "Test"},
        "research": {
            "title_he": "כותרת",
            "title_en": "Title",
            "request_type": "regular",
            "is_continuation": False,
            "third_party_service": False,
            "approval_term_years": 3,
            "sites": [],
        },
        "pi": {
            "id_type": "TZ",
            "id_number": "1",
            "last_name_he": "כ",
            "first_name_he": "ד",
            "last_name_en": "K",
            "first_name_en": "D",
            "email": "d@t.il",
            "phone_primary": "050",
            "phone_secondary": "",
            "institutional_cert_no": "C1",
            "faculty": "Med",
            "department": "Bio",
            "training": [
                {
                    "cert_no": "C1",
                    "issuer": "T",
                    "animal_scope": "rodents",
                    "date": "2023-01-01",
                }
            ],
        },
        "participants": [],
        "summaries": {"scientific_en_≤300w": "Short.", "lay_he_≤150w": "קצר."},
        "alternatives_search": {
            "engines": ["PubMed"],
            "date": "2025-01-01",
            "queries": ["query"],
            "conclusion": "No alternative.",
        },
        "animals_total": [
            {
                "species": "mouse",
                "strain": "C57BL/6",
                "sex": "both",
                "genetic_status": "WT",
                "source": "vendor",
                "n_total": 20,
            }
        ],
        "n_justification": {
            "method": "power",
            "details": "Power analysis.",
            "attachments": [],
        },
        "experiments": [
            {
                "label": "Exp 1",
                "question": "Does X affect Y?",
                "animals": {
                    "species": "mouse",
                    "strain": "C57BL/6",
                    "sex": "both",
                    "genetic_status": "WT",
                    "n": 20,
                },
                "housing": {"group_housed": True},
                "procedure_timeline": [],
                "analgesia": [],
                "anesthesia": [],
                "severity_level_1_to_5": 1,
                "monitoring": {"plan": "Daily."},
                "humane_endpoints": {"general": [], "specific": []},
                "euthanasia": {
                    "primary": "cervical dislocation",
                    "parameters": "",
                    "confirmation": "",
                },
                "fate": "euthanized",
            }
        ],
        "pi_declaration": {"affirmed": True},
        "is_colony": False,
    }


def _theme_response_for_prompt(prompt: str, score: int = 3) -> str:
    for key in ALL_THEME_KEYS:
        if key in prompt:
            return json.dumps(_graded_theme_payload(key, score=score))
    return json.dumps(_graded_theme_payload(ALL_THEME_KEYS[0], score=score))


def test_theme_specs_include_hazardous_agents_and_surgical_expansion():
    hazardous = THEME_SPECS["hazardous_agents"]
    assert hazardous["ref_prefixes"] == HAZARDOUS_REF_PREFIXES
    assert len(hazardous["sub_questions"]) == 5

    severity = THEME_SPECS["severity_monitoring_analgesia"]
    assert severity["ref_prefixes"] == ["severity:", "postop:", "surgery:"]
    assert SEVERITY_CATEGORY_E_QUESTION in severity["sub_questions"]

    surgical = THEME_SPECS["surgical_standards"]
    assert surgical["ref_prefixes"] == ["postop:", "surgery:"]
    assert len(surgical["sub_questions"]) == 4
    for question in SURGICAL_SUB_QUESTIONS:
        assert question in surgical["sub_questions"]


def test_verification_result_conforms_to_contract():
    instance = _minimal_instance()
    report = lint(instance, profile="strict_law")

    with patch(
        "src.llm_agent.call_llm",
        side_effect=(lambda prompt, **kwargs: _theme_response_for_prompt(prompt)),
    ):
        result = run_verification(instance, report, stance="law")

    try:
        VerifierResult.model_validate(result)
    except ValidationError as exc:
        pytest.fail(f"VerifierResult contract violated:\n{exc}")


def test_verification_all_eleven_themes_present():
    instance = _minimal_instance()
    report = lint(instance, profile="strict_law")

    with patch(
        "src.llm_agent.call_llm",
        side_effect=(lambda prompt, **kwargs: _theme_response_for_prompt(prompt)),
    ):
        result = run_verification(instance, report, stance="law")

    assert len(result["themes"]) == 12
    assert len(result["pass1_themes"]) == 12
    for key in ALL_THEME_KEYS:
        assert key in result["themes"], f"Theme {key!r} missing from result"
        assert key in result["pass1_themes"], f"Pass 1 theme {key!r} missing from result"


def test_committee_mode_calls_llm_for_all_themes():
    instance = _minimal_instance()
    instance["alternatives_search"]["engines"] = []
    report = lint(instance, profile="default")

    alts_engines_items = [
        c
        for c in report["checklist"]
        if c.get("reference") == "alts:engines" and c.get("status") == "fail"
    ]
    assert alts_engines_items, "Setup: expected alts:engines to fire"
    assert alts_engines_items[0]["severity"] == "warning"

    call_count = 0

    def counting_call_llm(prompt, **kwargs):
        nonlocal call_count
        call_count += 1
        return _theme_response_for_prompt(prompt)

    with patch("src.llm_agent.call_llm", side_effect=counting_call_llm):
        result = run_verification(instance, report, stance="committee")

    for key in ALL_THEME_KEYS:
        assert key in result["themes"], f"Theme {key!r} missing from committee result"
    assert call_count == 24, (
        "Expected exactly 24 LLM calls in committee mode (blind + reconcile), "
        f"got {call_count}"
    )
    assert result["disagreement_summary"]["total_themes"] == 12
    assert set(result["theme_metadata"]) == set(ALL_THEME_KEYS)


def test_stream_yields_correct_event_sequence():
    instance = _minimal_instance()
    report = lint(instance, profile="default")

    def fake_stream(prompt, **kwargs):
        payload = _theme_response_for_prompt(prompt)
        for ch in payload:
            yield ch

    with patch("src.llm_agent.call_llm_stream", side_effect=fake_stream):
        events = list(run_verification_stream(instance, report, stance="law"))

    event_types = [e["type"] for e in events]
    assert event_types[-1] == "complete", (
        "Last event must be 'complete', "
        f"got: {event_types[-1]}"
    )

    starts = [e for e in events if e["type"] == "theme_start"]
    assert len(starts) == 12, f"Expected 12 theme_start events, got {len(starts)}"

    dones = [e for e in events if e["type"] == "theme_done"]
    assert len(dones) == 12, f"Expected 12 theme_done events, got {len(dones)}"

    for key in ALL_THEME_KEYS:
        start_idx = next(
            (
                i
                for i, event in enumerate(events)
                if event["type"] == "theme_start" and event.get("theme") == key
            ),
            None,
        )
        done_idx = next(
            (
                i
                for i, event in enumerate(events)
                if event["type"] == "theme_done" and event.get("theme") == key
            ),
            None,
        )
        assert start_idx is not None, f"Missing theme_start for {key!r}"
        assert done_idx is not None, f"Missing theme_done for {key!r}"
        assert start_idx < done_idx, (
            f"theme_start must precede theme_done for {key!r}"
        )

    complete_event = events[-1]
    assert "result" in complete_event
    assert len(complete_event["result"].get("themes", {})) == 12
    for key in ALL_THEME_KEYS:
        assert key in complete_event["result"].get("themes", {}), (
            f"Theme {key!r} missing from complete event result"
        )
