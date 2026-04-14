"""
Inter-stage schema contract tests.

These tests validate that each pipeline stage produces output that conforms to
the Pydantic contracts in src/contracts.py. A failure here means a stage silently
changed its output shape, which would corrupt all downstream stages.

Priority 1 from professor feedback: highest blast-radius, cheapest gap to close.
"""

import re
import pytest
from pathlib import Path
from pydantic import ValidationError

from src.html_to_json import parse_html
from src.linter_renderer import (
    lint,
    STRUCTURAL_REFS,
    LAW_CRITICAL_REFS,
    ADVISORY_REFS,
)
from src.contracts import LinterResult
from src.schema import IACUC_SCHEMA_V2

EXAMPLES_DIR = Path(__file__).parent.parent / "examples"
GOOD_EXAMPLE_DIR = EXAMPLES_DIR / "known-good"
BAD_EXAMPLE_DIR = EXAMPLES_DIR / "known-bad"

# Per-experiment dynamic ref pattern: e.g. "severity:analgesia:exp-2"
_EXP_REF_RE = re.compile(r"^[a-z]+:[a-zA-Z0-9%\-]+:exp-\d+$")


def _primary_good_instance():
    path = GOOD_EXAMPLE_DIR / "good_IL-019-07-2000.html"
    if not path.exists():
        pytest.skip("Primary good example not found")
    return parse_html(path.read_text(encoding="utf-8"))


def _primary_bad_instance():
    path = BAD_EXAMPLE_DIR / "bad_IL-019-07-2000.html"
    if not path.exists():
        pytest.skip("Primary bad example not found")
    return parse_html(path.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# 1. Parser output — required top-level keys present
# ---------------------------------------------------------------------------

def test_parser_output_has_required_keys():
    """parse_html() must return a dict with all top-level required keys."""
    instance = _primary_good_instance()
    required = IACUC_SCHEMA_V2.get("required", [])
    assert required, "IACUC_SCHEMA_V2 must declare required keys"
    missing = [k for k in required if k not in instance]
    assert not missing, f"Parser output missing required keys: {missing}"


# ---------------------------------------------------------------------------
# 2. Linter output — shape conforms to LinterResult contract
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("fixture,profile", [
    ("good", "default"),
    ("good", "strict_law"),
    ("bad", "default"),
    ("bad", "strict_law"),
])
def test_linter_result_conforms_to_contract(fixture, profile):
    """lint() output must validate against the LinterResult Pydantic model."""
    instance = _primary_good_instance() if fixture == "good" else _primary_bad_instance()
    report = lint(instance, profile=profile)
    try:
        LinterResult.model_validate(report)
    except ValidationError as exc:
        pytest.fail(
            f"LinterResult contract violated for profile={profile!r}, fixture={fixture!r}:\n{exc}"
        )


# ---------------------------------------------------------------------------
# 3. Checklist refs — every reference is a known ref (guards against typos)
# ---------------------------------------------------------------------------

ALL_KNOWN_STATIC_REFS = STRUCTURAL_REFS | LAW_CRITICAL_REFS | ADVISORY_REFS


def _ref_is_known(ref: str) -> bool:
    """Return True if ref is in a known static set or matches the per-exp pattern."""
    if ref in ALL_KNOWN_STATIC_REFS:
        return True
    if _EXP_REF_RE.match(ref):
        # e.g. "severity:analgesia:exp-1" — check the base ref is known
        base = ":".join(ref.split(":")[:2])
        return base in ALL_KNOWN_STATIC_REFS
    return False


@pytest.mark.parametrize("fixture,profile", [
    ("good", "default"),
    ("good", "strict_law"),
    ("bad", "default"),
    ("bad", "strict_law"),
])
def test_linter_checklist_refs_are_known(fixture, profile):
    """Every 'reference' in the checklist must be a known ref code."""
    instance = _primary_good_instance() if fixture == "good" else _primary_bad_instance()
    report = lint(instance, profile=profile)
    unknown = [
        item["reference"]
        for item in report["checklist"]
        if not _ref_is_known(item["reference"])
    ]
    assert not unknown, (
        f"Unknown ref codes in checklist (profile={profile!r}, fixture={fixture!r}): {unknown}"
    )


# ---------------------------------------------------------------------------
# 4. Parser → linter roundtrip — no crash on all known-good files
# ---------------------------------------------------------------------------

def _all_known_good_html():
    paths = list(GOOD_EXAMPLE_DIR.glob("*.html"))
    if not paths:
        pytest.skip("No HTML files in known-good/")
    return paths


@pytest.mark.parametrize("html_path", _all_known_good_html(), ids=lambda p: p.name)
def test_parser_linter_roundtrip_does_not_crash(html_path):
    """lint(parse_html(html)) must not raise for any known-good file."""
    html = html_path.read_text(encoding="utf-8")
    instance = parse_html(html)
    report = lint(instance, profile="default")
    # Must produce a valid shape — not testing pass/fail, just no exception
    LinterResult.model_validate(report)
