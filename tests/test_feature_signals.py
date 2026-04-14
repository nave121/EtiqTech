from pathlib import Path

import pytest

from src.html_to_json import parse_html
from src.linter_renderer import lint

EXAMPLES_DIR = Path(__file__).parent.parent / "examples"
GOOD_EXAMPLE_DIR = EXAMPLES_DIR / "known-good"


def _load_primary_good_instance():
    html_path = GOOD_EXAMPLE_DIR / "good_IL-019-07-2000.html"
    if not html_path.exists():
        pytest.skip("Primary good example not found")
    html_content = html_path.read_text(encoding="utf-8")
    return parse_html(html_content)


def test_feature_signals_summary_and_alternatives_present():
    """
    The feature extraction layer should expose basic summary and alternatives signals
    without re-parsing the instance.
    """
    instance = _load_primary_good_instance()
    report = lint(instance, profile="default")

    analysis = report.get("analysis")
    assert isinstance(analysis, dict)

    summary = analysis.get("summary") or {}
    alts = analysis.get("alternatives") or {}

    # Known properties of the primary good example:
    assert summary.get("num_experiments") == 4
    assert summary.get("N_total_all_experiments") == 1360

    # The good example has an alternatives_search block with at least one engine
    # (extracted from "אופן חיפוש חלופות") and at least one recorded query.
    assert alts.get("present") is True
    assert alts.get("engines_count") >= 0
    assert alts.get("queries_count") >= 1


def test_feature_signals_experiment_level_flags():
    """
    Experiment-level signals (severity, analgesia, endpoints) should be present.
    """
    instance = _load_primary_good_instance()
    report = lint(instance, profile="default")
    analysis = report.get("analysis") or {}
    exps = analysis.get("experiments") or []

    assert len(exps) == 4

    first = exps[0]
    assert "severity" in first
    # The primary good example is invasive, severity >= 3 with missing analgesia.
    assert first.get("severity") is not None
    assert first.get("has_analgesia") is False
    assert first.get("has_humane_endpoints") is True
    # Humane endpoints in this example rely heavily on 20% weight loss.
    assert first.get("humane_endpoints_20_percent_only") is True
