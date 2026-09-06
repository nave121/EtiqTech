"""Ruleset 1.1.0 (2026-09-06): the four counting quirks preserved through the split are fixed.
Each test states the old behaviour so the change is visible in review."""
import json
from pathlib import Path

from src.adapters import parse_canonical_json
from src.linter_renderer import lint
from src.rules import KNOWN_RULESET_VERSIONS, RULES, RULESET_VERSION

COV = Path(__file__).resolve().parents[1] / "examples" / "coverage"


def _lint(name):
    return lint(parse_canonical_json((COV / name).read_text(encoding="utf-8")))


def test_term_track_out_of_range_fails_visibly():
    # 1.0.0: errors += 1 but the only row was {"status": "pass", "severity": "error"} -> status fail with no failing row.
    # The schema caps approval_term_years at 4, so this input can only arrive via the HTML parser: lint a raw dict.
    r = lint({"header": {"protocol_id": "1", "institution": "x"},
              "research": {"title_he": "מחקר", "title_en": "Study", "request_type": "regular", "is_continuation": False,
                           "third_party_service": False, "approval_term_years": 5, "sites": [{"name": "x"}]}})
    rows = [c for c in r["checklist"] if c["rule_id"] == "term:track"]
    assert rows and rows[0]["status"] == "fail" and rows[0]["severity"] == "error"
    assert r["errors"] >= 1 and r["status"] == "fail"
    assert r["errors"] == sum(1 for c in r["checklist"] if c["status"] == "fail" and c["severity"] == "error")


def test_pilot_label_is_a_warning_and_counted_as_advisory():
    # 1.0.0: row severity "error" (the _rule default) against warnings += 1; counted in no category bucket
    r = _lint("title__pilot-label.json")
    rows = [c for c in r["checklist"] if c["rule_id"] == "title:pilot-label" and c["status"] == "fail"]
    assert rows and rows[0]["severity"] == "warning"
    assert r["advisory_warnings"] >= 1


def test_required_rows_count_as_structural_errors():
    # 1.0.0: required:<path> rows incremented errors but landed in no category bucket
    r = lint({"header": {}, "research": {"title_he": "x", "title_en": "x", "request_type": "regular", "is_continuation": False,
                                          "third_party_service": False, "approval_term_years": 2, "sites": []}, "pi": {}})
    req_fails = [c for c in r["checklist"] if c["status"] == "fail" and c["rule_id"] == "required"]
    assert req_fails and r["structural_errors"] >= len(req_fails)
    assert RULES["required"].kind == "structural"


def test_specialty_rules_are_warnings_on_pass_and_fail():
    # 1.0.0: passing rows were stamped severity "error" while failing rows said "warning"
    from pathlib import Path as _P
    from src.html_to_json import parse_html
    seen = set()
    for f in sorted((_P(__file__).resolve().parents[1] / "examples").rglob("*.html")):
        r = lint(parse_html(f.read_text(encoding="utf-8")))
        for c in r["checklist"]:
            if c["rule_id"] and c["rule_id"].startswith("special:") and RULES[c["rule_id"]].kind == "advisory":
                seen.add((c["status"], c["severity"]))
    assert seen and all(sev == "warning" for _s, sev in seen), seen


def test_counters_reconcile_with_rows_on_every_fixture():
    """errors/warnings equal the failing-row counts by severity, and the category buckets sum to them."""
    from src.html_to_json import parse_html
    for f in sorted((Path(__file__).resolve().parents[1] / "examples").rglob("*.html")):
        for profile in ("default", "strict_law"):
            r = lint(parse_html(f.read_text(encoding="utf-8")), profile=profile)
            fails = [c for c in r["checklist"] if c["status"] == "fail"]
            assert r["errors"] == sum(c["severity"] == "error" for c in fails), f.name
            assert r["warnings"] == sum(c["severity"] != "error" for c in fails), f.name
            assert r["structural_errors"] + r["law_critical_errors"] == r["errors"], f.name
            assert r["advisory_warnings"] <= r["warnings"], f.name


def test_ruleset_version_bumped_and_history_known():
    assert RULESET_VERSION == "1.1.0" and "1.0.0" in KNOWN_RULESET_VERSIONS
