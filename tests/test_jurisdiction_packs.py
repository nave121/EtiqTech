"""P3.2 step 1: jurisdiction packs select rules/themes by configuration; IL is today's behaviour."""
import json
from pathlib import Path

import pytest

import src.llm_agent as llm_agent
from src.contracts import LinterResult
from src.html_to_json import parse_html
from src.linter_renderer import lint
from src.rules import PACKS, RULES, active_pack, apply_pack, rule_active

ROOT = Path(__file__).resolve().parents[1]
INSTANCE = parse_html((ROOT / "examples" / "known-bad" / "bad_IL-001-01-2000.html").read_text(encoding="utf-8"))


def test_default_pack_is_israel_and_changes_nothing(monkeypatch):
    monkeypatch.delenv("ETIQTECH_JURISDICTION", raising=False)
    report = lint(INSTANCE)
    assert active_pack() == "IL" and report["jurisdiction"] == "IL" and "rules_outside_pack" not in report
    assert all(rule_active(r) for r in RULES)


def test_unknown_pack_falls_back_to_default(monkeypatch):
    monkeypatch.setenv("ETIQTECH_JURISDICTION", "mars")
    assert active_pack() == "IL"


def test_generic_pack_drops_il_form_rules_and_recomputes_counts(monkeypatch):
    monkeypatch.delenv("ETIQTECH_JURISDICTION", raising=False)
    il = lint(INSTANCE, profile="strict_law")
    monkeypatch.setenv("ETIQTECH_JURISDICTION", "generic")
    generic = lint(INSTANCE, profile="strict_law")
    assert generic["jurisdiction"] == "generic"
    il_form_ids = {r.id for r in RULES.values() if r.jurisdiction == "IL-form"}
    assert not any(c["rule_id"] in il_form_ids for c in generic["checklist"])
    assert generic["rules_outside_pack"] == len(il["checklist"]) - len(generic["checklist"]) > 0
    fails = [c for c in generic["checklist"] if c["status"] == "fail"]
    assert generic["errors"] == sum(c["severity"] == "error" for c in fails)
    assert generic["warnings"] == sum(c["severity"] != "error" for c in fails)
    assert generic["status"] == ("pass" if generic["errors"] == 0 else "fail")
    assert generic["law_critical_errors"] <= il["law_critical_errors"]
    LinterResult(**generic)


def test_apply_pack_never_drops_unregistered_refs():
    report = {"checklist": [{"status": "fail", "severity": "error", "reference": "custom:x", "rule_id": None}]}
    out = apply_pack(report, "generic")
    assert len(out["checklist"]) == 1 and out["errors"] == 1


def test_generic_pack_skips_writing_quality_theme(monkeypatch):
    monkeypatch.setenv("ETIQTECH_JURISDICTION", "generic")
    monkeypatch.setattr(llm_agent, "call_llm_stream", lambda *a, **k: iter(["{}"]))
    events = list(llm_agent.run_verification_stream({"animals_total": []}, {"checklist": []}))
    themes = events[-1]["result"]["themes"]
    assert "writing_quality" not in themes and len(themes) == len(llm_agent.THEME_SPECS) - 1
    assert events[-1]["result"]["disagreement_summary"]["total_themes"] == len(themes)
    starts = [e for e in events if e["type"] == "theme_start"]
    assert all(e["total"] == len(themes) for e in starts)


def test_batch_verification_also_respects_pack(monkeypatch):
    monkeypatch.setenv("ETIQTECH_JURISDICTION", "generic")
    monkeypatch.setattr(llm_agent, "call_llm", lambda *a, **k: "{}")
    result = llm_agent.run_verification({"animals_total": []}, {"checklist": []})
    assert "writing_quality" not in result["themes"]
    assert result["disagreement_summary"]["total_themes"] == len(result["themes"])


def test_packs_reference_known_things():
    for name, pack in PACKS.items():
        assert set(pack["rule_jurisdictions"]) <= {"IL-form", "generic"}
        assert set(pack["excluded_themes"]) <= set(llm_agent.THEME_SPECS), name


def test_generic_pack_still_rejects_an_incomplete_submission(monkeypatch):
    monkeypatch.setenv("ETIQTECH_JURISDICTION", "generic")
    report = lint({})
    assert report["status"] == "fail" and report["errors"] >= 3
    assert {"header", "research", "pi"} <= {c["rule_id"] for c in report["checklist"] if c["status"] == "fail"}
