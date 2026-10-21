"""Ruleset 1.3.0 (2026-10-21): severity:monitoring asks how often animals are checked, decided by the maintainer
after measuring every real export (changes/severity-monitoring/). The tests name the old behaviour."""
import pytest

from src.linter_renderer import lint
from src.rules import KNOWN_RULESET_VERSIONS, RULESET_VERSION

_NO_SCHEDULE = "Body weight, posture, coat condition and signs of distress are recorded on the score sheet."


def _report(parameters, endpoints="Severe weight loss >20%.", profile="default", **cells):
    exp = {
        "label": "Experiment 1",
        "severity_level_1_to_5": 4,
        "monitoring": {"parameters": [parameters] if parameters else [], "documentation": "", **cells},
        "humane_endpoints": {"general": [endpoints], "specific": []},
    }
    return lint({"experiments": [exp]}, profile=profile)


def _monitoring_fails(parameters, endpoints="Severe weight loss >20%.", profile="default", **cells):
    report = _report(parameters, endpoints, profile, **cells)
    return [c for c in report["checklist"] if c["status"] == "fail" and c.get("rule_id") == "severity:monitoring"]


def _severities(*args, **kwargs):
    return [c["severity"] for c in _monitoring_fails(*args, **kwargs)]


def test_version_is_1_3_0():
    assert RULESET_VERSION == "1.3.0" and "1.3.0" in KNOWN_RULESET_VERSIONS


def test_severity_monitoring_needs_a_stated_check_frequency():
    # 1.2.0: any monitoring text over 50 characters, or containing "24" / "72", passed
    assert _severities(_NO_SCHEDULE) == ["warning"]
    assert _severities(_NO_SCHEDULE, profile="strict_law") == ["error"]
    assert _severities("") == ["error"]  # no monitoring text at all stays an error by default
    assert _severities("Checked once a week.") == ["warning"]  # once a week alone is not enough
    assert not _severities("העכברים ייבדקו אחת ליומיים.")
    assert not _severities(_NO_SCHEDULE, endpoints="Animals are weighed every 3 days; a 15% loss ends the study.")


@pytest.mark.parametrize("text", [
    "Scored twice weekly.", "Checked 2x/week.", "Analgesia check q12h.", "Weighed on alternate days.",
    "Checked every 24 to 48 h after surgery.", "נבדקים פעמיים ביממה.", "נבדקים כל 2-3 ימים.", "נשקלים כל שלושה ימים.",
])
def test_more_than_weekly_passes(text):
    assert not _severities(text)


@pytest.mark.parametrize("text", [
    "Checked weekly.", "Checked every two weeks.", "Checked every 10 days.", "Checked every 6-7 days.",
    "Checked every 200 hours.", "נבדקים כל שבועיים.", "נבדקים כל יום שני.", "תיעוד קיומי של סימני מצוקה.",
])
def test_weekly_or_rarer_warns(text):
    assert _severities(text) == ["warning"]


def test_export_cells_count_as_a_stated_schedule():
    assert not _severities("", initial_72h_daily=True)
    assert not _severities("", ongoing_per_week=2)
    assert not _severities("", ongoing_per_week=2.0)  # the schema accepts 2.0 as an integer
    once = _monitoring_fails("", ongoing_per_week=1)  # a stated once-a-week plan: not enough, but not "no plan"
    assert [c["severity"] for c in once] == ["warning"] and "no monitoring plan" not in once[0]["message"]


def test_finding_is_counted_once_at_its_severity():
    # default: one more warning and no extra error, so the verdict cannot move; strict_law: one more error
    for profile, counter, other in (("default", "warnings", "errors"), ("strict_law", "errors", "warnings")):
        unstated = _report(_NO_SCHEDULE, profile=profile)
        baseline = _report("Checked daily.", profile=profile)
        assert unstated[counter] == baseline[counter] + 1
        assert unstated[other] == baseline[other]
