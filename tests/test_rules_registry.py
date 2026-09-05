"""P3.1: every linter check has a stable, registered rule id; docs/rules.md is generated and current."""
import glob
import subprocess
import sys
from pathlib import Path

import pytest

from src.contracts import LinterResult
from src.html_to_json import parse_html
from src.linter_renderer import lint
from src.rules import RULES, RULESET_VERSION, rule_id_from_ref

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = sorted(set(glob.glob(str(ROOT / "examples" / "**" / "*.html"), recursive=True)))


def test_rule_id_normalization():
    assert rule_id_from_ref("euthanasia:CO2:exp-3") == "euthanasia:CO2"
    assert rule_id_from_ref("required:header") == "required"
    assert rule_id_from_ref("severity:analgesia") == "severity:analgesia"
    assert rule_id_from_ref("no:such:rule") is None and rule_id_from_ref("") is None


def test_registry_ids_are_well_formed_and_domains_match():
    for rid, rule in RULES.items():
        assert rule.id == rid and rule.domain == rid.split(":", 1)[0]
        assert rule.kind in ("structural", "law_critical", "advisory", "required")
        assert rule.jurisdiction in ("IL-form", "generic")
        assert rule.title


@pytest.mark.parametrize("path", FIXTURES, ids=lambda p: Path(p).name)
def test_every_emitted_check_maps_to_a_registered_rule(path):
    instance = parse_html(Path(path).read_text(encoding="utf-8"))
    for profile in ("default", "strict_law"):
        report = lint(instance, profile=profile)
        assert report["ruleset_version"] == RULESET_VERSION
        unregistered = [c["reference"] for c in report["checklist"] if c["rule_id"] is None]
        assert unregistered == [], unregistered
        LinterResult(**report)


def test_registry_covers_every_severity_class_set():
    from src.linter_renderer import ADVISORY_REFS, LAW_CRITICAL_REFS, STRUCTURAL_REFS
    for name, refs in (("structural", STRUCTURAL_REFS), ("law_critical", LAW_CRITICAL_REFS), ("advisory", ADVISORY_REFS)):
        missing = sorted(r for r in refs if r not in RULES)
        assert missing == [], (name, missing)


def test_rules_doc_is_generated_and_current():
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "gen_rules_doc.py"), "--check"], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
