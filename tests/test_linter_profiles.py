import pytest
from pathlib import Path

from src.html_to_json import parse_html
from src.linter_renderer import lint

EXAMPLES_DIR = Path(__file__).parent.parent / "examples"
GOOD_EXAMPLE_DIR = EXAMPLES_DIR / "known-good"
BAD_EXAMPLE_DIR = EXAMPLES_DIR / "known-bad"


def _load_primary_good():
    html_path = GOOD_EXAMPLE_DIR / "good_IL-019-07-2000.html"
    if not html_path.exists():
        pytest.skip("Primary good example not found")
    html_content = html_path.read_text(encoding="utf-8")
    return parse_html(html_content)


def test_profile_default_vs_strict_law_on_good_example():
    """
    Default profile should pass structurally good 'known good' examples,
    while strict_law treats missing law-critical alternatives fields as errors.
    """
    instance = _load_primary_good()

    rep_default = lint(instance, profile="default")
    rep_strict = lint(instance, profile="strict_law")

    assert rep_default["profile"] == "default"
    assert rep_strict["profile"] == "strict_law"

    # Default: structurally OK, so overall status should be pass.
    assert rep_default["status"] == "pass"
    # Strict law: same instance should fail due to law-critical checks.
    assert rep_strict["status"] == "fail"

    # Euthanasia CO₂ confirmation should be a warning in default and an error in strict_law.
    co2_default = [
        c for c in rep_default["checklist"]
        if "euthanasia:CO2" in (c.get("reference") or "") and c.get("status") == "fail"
    ]
    co2_strict = [
        c for c in rep_strict["checklist"]
        if "euthanasia:CO2" in (c.get("reference") or "") and c.get("status") == "fail"
    ]
    assert co2_default and co2_strict
    assert co2_default[0]["severity"] == "warning"
    assert co2_strict[0]["severity"] == "error"


def test_structural_error_present_in_both_profiles_for_bad_example():
    """
    Structural errors (like animals totals mismatch) must cause failure
    in both default and strict_law profiles.
    """
    bad_path = BAD_EXAMPLE_DIR / "bad_IL-019-07-2000.html"
    if not bad_path.exists():
        pytest.skip("Primary bad example not found")

    html_content = bad_path.read_text(encoding="utf-8")
    instance = parse_html(html_content)

    rep_default = lint(instance, profile="default")
    rep_strict = lint(instance, profile="strict_law")

    animals_default = [
        c for c in rep_default["checklist"]
        if c.get("reference") == "animals:totals-vs-exps" and c.get("status") == "fail"
    ]
    animals_strict = [
        c for c in rep_strict["checklist"]
        if c.get("reference") == "animals:totals-vs-exps" and c.get("status") == "fail"
    ]
    assert animals_default and animals_strict
    assert rep_default["status"] == "fail"
    assert rep_strict["status"] == "fail"


def test_reclassified_summary_rules_are_advisory_and_new_law_critical_rules_upgrade_in_strict():
    """
    Summary-length rules should stay warnings in both profiles, while new
    law-critical rules still upgrade from warning to error in strict_law.
    """
    instance = _load_primary_good()

    instance["summaries"]["lay_he_≤150w"] = " ".join(["מילה"] * 160)
    instance["summaries"]["scientific_en_≤300w"] = " ".join(["science"] * 2605)
    instance["experiments"][0]["procedure_timeline"] = [
        {"step": "Administer vecuronium to induce paralysis for imaging."}
    ]
    instance["experiments"][0]["anesthesia"] = []

    rep_default = lint(instance, profile="default")
    rep_strict = lint(instance, profile="strict_law")

    lay_default = [
        c for c in rep_default["checklist"]
        if c.get("reference") == "summaries:lay-length" and c.get("status") == "fail"
    ]
    sci_strict = [
        c for c in rep_strict["checklist"]
        if c.get("reference") == "summaries:scientific-length" and c.get("status") == "fail"
    ]
    paralytic_default = [
        c for c in rep_default["checklist"]
        if c.get("reference", "").startswith("paralytic:without-anesthesia")
        and c.get("status") == "fail"
    ]
    paralytic_strict = [
        c for c in rep_strict["checklist"]
        if c.get("reference", "").startswith("paralytic:without-anesthesia")
        and c.get("status") == "fail"
    ]

    assert lay_default and sci_strict
    assert lay_default[0]["severity"] == "warning"
    assert sci_strict[0]["severity"] == "warning"
    assert paralytic_default and paralytic_strict
    assert paralytic_default[0]["severity"] == "warning"
    assert paralytic_strict[0]["severity"] == "error"
