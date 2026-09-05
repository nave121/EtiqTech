"""Synthetic canonical-JSON fixtures under examples/coverage/ each trip a failing item for the rule named in the filename (unrelated rules may also fire; see examples/coverage/README.md)
(`alts__engines.json` -> `alts:engines`), so a rule that no real example exercises still has a guard.
See examples/coverage/README.md for how to add one and which rules cannot be reached from canonical JSON."""
import glob
from pathlib import Path

import pytest

from src.adapters import parse_canonical_json
from src.linter_renderer import lint
from src.rules import RULES, rule_id_from_ref

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = sorted(glob.glob(str(ROOT / "examples" / "coverage" / "*.json")))

# Keep in sync with the files: a fixture that disappears (or a new one) must be a deliberate edit here too.
COVERED = {
    "N:justification-detail", "N:power-analysis",
    "alts:conclusion", "alts:engines", "alts:missing", "alts:queries",
    "ascites:in-vitro",
    "colony:breeding-plan", "colony:no-invasive",
    "endpoints:generic-consult",
    "euthanasia:cervical-weight", "euthanasia:overdose-confirm", "euthanasia:precharged-chamber", "euthanasia:species-method",
    "gma:ibc",
    "housing:density",
    "paralytic:without-anesthesia",
    "permits:field-study",
    "reuse:justification",
    "scope:pilot-size",
    "sex:rationale", "sex:sabv",
    "special:neonatal-CO2",
}


def rule_id_of(path: str) -> str:
    return Path(path).stem.replace("__", ":")


@pytest.mark.parametrize("path", FIXTURES, ids=lambda p: Path(p).name)
def test_fixture_validates_and_trips_its_rule(path):
    rid = rule_id_of(path)
    assert rid in RULES, f"{Path(path).name} names an unregistered rule {rid!r}"
    instance = parse_canonical_json(Path(path).read_text(encoding="utf-8"))
    fired = {
        rule_id_from_ref(item.get("reference"))
        for profile in ("default", "strict_law")
        for item in lint(instance, profile=profile)["checklist"]
        if item["status"] == "fail"
    }
    assert rid in fired, f"{Path(path).name} did not trip {rid}; failing rules: {sorted(r for r in fired if r)}"


def test_covered_set_matches_fixtures():
    assert {rule_id_of(p) for p in FIXTURES} == COVERED
