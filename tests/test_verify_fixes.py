import json
from pathlib import Path
import pytest
from src.html_to_json import parse_html
from src.linter_renderer import lint

EXAMPLES_DIR = Path(__file__).parent.parent / "examples"
BAD_DIR = EXAMPLES_DIR / "known-bad"
GOOD_DIR = EXAMPLES_DIR / "known-good"

def get_report(html_path):
    if not html_path.exists():
        pytest.skip(f"File not found: {html_path}")
    html_content = html_path.read_text(encoding="utf-8")
    instance = parse_html(html_content)
    return lint(instance)

def test_sharon_fix_verification():
    """
    Case IL-019:
    - Bad: Animals Total Mismatch (totals=4080 vs exps=1360).
    - Good: Animals Total Match (Passed).
    """
    bad_path = BAD_DIR / "bad_IL-019-07-2000.html"
    good_path = GOOD_DIR / "good_IL-019-07-2000.html"

    report_bad = get_report(bad_path)
    report_good = get_report(good_path)

    # Check Bad
    animals_errors_bad = [c for c in report_bad["checklist"] if c["reference"] == "animals:totals-vs-exps" and c["status"] == "fail"]
    assert len(animals_errors_bad) == 1, "Bad IL-019 should fail Animals Total check"
    
    # Check Good
    animals_errors_good = [c for c in report_good["checklist"] if c["reference"] == "animals:totals-vs-exps" and c["status"] == "fail"]
    assert len(animals_errors_good) == 0, "Good IL-019 should PASS Animals Total check"

def test_case_027_fix_verification():
    """
    Case IL-027:
    - Bad: Term/Track Mismatch (Pilot with 4 years).
    - Good: Term/Track Match (Regular with 4 years).
    """
    bad_path = BAD_DIR / "bad_IL-027-07-2000.html"
    good_path = GOOD_DIR / "good_IL-027-07-2000.html"

    report_bad = get_report(bad_path)
    report_good = get_report(good_path)

    # Check Bad: Term vs Track
    # We relaxed this rule to a WARNING because some approved pilots have 4 years.
    # So we check for status='pass' (or fail if other errors) but ensure the specific check is present as warning or fail.
    term_checks_bad = [c for c in report_bad["checklist"] if c["reference"] == "term:track"]
    assert len(term_checks_bad) == 1
    # It should be fail OR warning depending on strictness
    assert term_checks_bad[0]["status"] == "fail" or term_checks_bad[0]["severity"] == "warning"
    assert "inconsistent with request_type='pilot'" in term_checks_bad[0]["message"]

    # Check Good: Term vs Track
    term_errors_good = [c for c in report_good["checklist"] if c["reference"] == "term:track" and c["status"] == "fail"]
    assert len(term_errors_good) == 0, "Good IL-027 should PASS Term/Track consistency"

    # Note: Englander Good seemingly introduces a new error (Abstract Length), 
    # but we are testing the specific fix here.
