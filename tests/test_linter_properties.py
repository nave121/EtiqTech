"""
Property-based and metamorphic tests for the linter (email 02 recommendation).

Uses Hypothesis to generate random inputs and verify invariants, plus deterministic
metamorphic tests that check directional behavior when violations are introduced.

Three tests:
1. test_linter_never_crashes     — Hypothesis: lint() never raises for any random text
2. test_strict_law_is_superset   — Hypothesis: strict_law errors >= default errors always
3. test_adding_violation_increases_flags — metamorphic: removing analgesia from a clean
   instance increases the error+warning count
"""

import copy

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from src.linter_renderer import lint

# ---------------------------------------------------------------------------
# Shared minimal valid instance (same structure as test_linter_rules.py)
# ---------------------------------------------------------------------------

_BASE_INSTANCE = {
    "header": {"protocol_id": "99999", "institution": "Test University"},
    "research": {
        "title_he": "כותרת בדיקה",
        "title_en": "Test Protocol",
        "request_type": "regular",
        "is_continuation": False,
        "third_party_service": False,
        "approval_term_years": 3,
        "sites": [],
    },
    "pi": {
        "id_type": "TZ",
        "id_number": "123456789",
        "last_name_he": "כהן",
        "first_name_he": "דוד",
        "last_name_en": "Cohen",
        "first_name_en": "David",
        "email": "d@test.ac.il",
        "phone_primary": "SYNTH-0000000",
        "phone_secondary": "",
        "institutional_cert_no": "CERT-1",
        "faculty": "Medicine",
        "department": "Physiology",
        "training": [
            {"cert_no": "C1", "issuer": "TAMIR", "animal_scope": "rodents", "date": "2023-01-01"}
        ],
    },
    "participants": [],
    "summaries": {
        "scientific_en_≤300w": "A test protocol summary.",
        "lay_he_≤150w": "תקציר לציבור.",
    },
    "alternatives_search": {
        "engines": ["PubMed", "Embase"],
        "date": "2025-01-01",
        "queries": ["animal alternatives rodent model"],
        "conclusion": "No validated alternative exists for this model.",
    },
    "animals_total": [
        {"species": "mouse", "strain": "C57BL/6", "sex": "both",
         "genetic_status": "WT", "source": "vendor", "n_total": 20}
    ],
    "n_justification": {
        "method": "power",
        "details": "Power analysis at α=0.05, β=0.8 with expected effect size d=0.8 requires n=10 per group.",
        "attachments": [],
    },
    "experiments": [
        {
            "label": "Experiment 1",
            "question": "Does treatment X affect Y?",
            "animals": {
                "species": "mouse", "strain": "C57BL/6", "sex": "both",
                "genetic_status": "WT", "n": 20,
            },
            "housing": {"group_housed": True},
            "procedure_timeline": [],
            "analgesia": [],
            "anesthesia": [],
            "severity_level_1_to_5": 1,
            "monitoring": {"plan": "Daily observation."},
            "humane_endpoints": {"general": ["Severe weight loss >20%."], "specific": []},
            "euthanasia": {"primary": "cervical dislocation", "parameters": "", "confirmation": ""},
            "fate": "euthanized",
        }
    ],
    "pi_declaration": {"affirmed": True},
    "is_colony": False,
}


# ---------------------------------------------------------------------------
# Property test 1: lint() never crashes for random monitoring.plan text
# ---------------------------------------------------------------------------

@settings(max_examples=200)
@given(
    monitoring_plan=st.text(max_size=500),
    timeline_step=st.text(max_size=200),
    severity=st.integers(min_value=1, max_value=5),
)
def test_linter_never_crashes(monitoring_plan, timeline_step, severity):
    """
    lint() must never raise an exception regardless of arbitrary text input in
    monitoring.plan and procedure_timeline entries.
    """
    instance = copy.deepcopy(_BASE_INSTANCE)
    instance["experiments"][0]["monitoring"]["plan"] = monitoring_plan
    instance["experiments"][0]["procedure_timeline"] = [{"step": timeline_step}]
    instance["experiments"][0]["severity_level_1_to_5"] = severity

    # Must not raise anything
    report = lint(instance, profile="default")
    assert "checklist" in report
    assert isinstance(report["checklist"], list)


# ---------------------------------------------------------------------------
# Property test 2: strict_law error count is always >= default error count
# ---------------------------------------------------------------------------

@settings(max_examples=200)
@given(
    severity=st.integers(min_value=1, max_value=5),
    has_analgesia=st.booleans(),
    has_engines=st.booleans(),
    confirmation=st.text(max_size=100),
)
def test_strict_law_is_superset_of_default(severity, has_analgesia, has_engines, confirmation):
    """
    For any instance configuration, strict_law must produce >= errors as default.
    This is the property-level extension of the single-case superset test.
    """
    instance = copy.deepcopy(_BASE_INSTANCE)

    # Vary severity and analgesia
    instance["experiments"][0]["severity_level_1_to_5"] = severity
    if has_analgesia:
        instance["experiments"][0]["analgesia"] = [
            {"agent": "buprenorphine", "dose": "0.05 mg/kg", "route": "SC", "frequency": "q8h"}
        ]
    else:
        instance["experiments"][0]["analgesia"] = []

    # Add invasive step so analgesia rule can trigger at severity >= 3
    instance["experiments"][0]["procedure_timeline"] = [{"step": "laparotomy"}]

    # Vary alternatives search engines
    if not has_engines:
        instance["alternatives_search"]["engines"] = []

    # Vary CO2 confirmation
    instance["experiments"][0]["euthanasia"] = {
        "primary": "CO2", "parameters": "", "confirmation": confirmation
    }

    rep_default = lint(instance, profile="default")
    rep_strict = lint(instance, profile="strict_law")

    assert rep_strict["errors"] >= rep_default["errors"], (
        f"strict_law errors ({rep_strict['errors']}) < default errors ({rep_default['errors']}) "
        f"for severity={severity}, has_analgesia={has_analgesia}, has_engines={has_engines}"
    )


# ---------------------------------------------------------------------------
# Metamorphic test 3: removing analgesia from a clean instance increases flags
# ---------------------------------------------------------------------------

def test_adding_violation_increases_or_maintains_flags():
    """
    Directional metamorphic test: start from an instance that passes severity:analgesia,
    remove the analgesic agent, and verify that error+warning count increases.

    This is deterministic (not Hypothesis-random) — it tests the monotonic property
    that introducing a clear violation never reduces the flag count.
    """
    # Baseline: severity 3, invasive procedure, analgesia present → no severity:analgesia error
    baseline = copy.deepcopy(_BASE_INSTANCE)
    baseline["experiments"][0]["severity_level_1_to_5"] = 3
    baseline["experiments"][0]["procedure_timeline"] = [{"step": "laparotomy and tumor resection"}]
    baseline["experiments"][0]["analgesia"] = [
        {"agent": "buprenorphine", "dose": "0.05 mg/kg", "route": "SC", "frequency": "q8h"}
    ]

    report_baseline = lint(baseline, profile="default")
    baseline_total = report_baseline["errors"] + report_baseline["warnings"]

    # Verify baseline does NOT fire severity:analgesia
    analgesia_violations = [
        c for c in report_baseline["checklist"]
        if c.get("reference", "").startswith("severity:analgesia") and c.get("status") == "fail"
    ]
    assert not analgesia_violations, (
        "Baseline setup error: severity:analgesia should not fire when analgesia is present"
    )

    # Mutated: same instance but analgesia removed → should fire severity:analgesia
    mutated = copy.deepcopy(baseline)
    mutated["experiments"][0]["analgesia"] = []

    report_mutated = lint(mutated, profile="default")
    mutated_total = report_mutated["errors"] + report_mutated["warnings"]

    # Verify severity:analgesia now fires
    analgesia_violations_mutated = [
        c for c in report_mutated["checklist"]
        if c.get("reference", "").startswith("severity:analgesia") and c.get("status") == "fail"
    ]
    assert analgesia_violations_mutated, (
        "severity:analgesia must fire after removing analgesia from invasive severity-3 experiment"
    )

    # The total flag count must be strictly higher
    assert mutated_total > baseline_total, (
        f"Introducing a violation should increase error+warning count "
        f"(baseline={baseline_total}, mutated={mutated_total})"
    )
