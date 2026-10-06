"""Layer 2 theme prompts carry the protocol text, and never the people in it.

Regression for the defect where every per-theme prompt was built from the lint report
alone: the protocol's narrative fields never reached the model, so good and bad
protocols often produced byte-identical prompts. The lint report is always built from
the unmarked instance, so a marker in a prompt can only have come through the excerpt.
"""
import json
from pathlib import Path

import pytest

from src.html_to_json import parse_html
from src.linter_renderer import lint
from src.llm_agent import THEME_SPECS, _build_theme_prompt, _slice_instance

CASE = Path(__file__).resolve().parents[1] / "examples" / "head-to-head" / "1"
MARK = "NARRATIVE-MARKER-7f3a"
ID_MARK = "IDENTIFIER-MARKER-c91e"


def _load(name):
    return parse_html((CASE / name).read_text(encoding="utf-8"))


def _plant(obj, marker):
    if isinstance(obj, dict):
        return {k: _plant(v, marker) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_plant(v, marker) for v in obj]
    if isinstance(obj, str) and len(obj) > 20:
        return f"{obj} {marker}"
    return obj


def _prompts(theme, instance, report):
    spec = THEME_SPECS[theme]
    return (
        _build_theme_prompt(theme, spec, instance, report, pass_name="blind"),
        _build_theme_prompt(theme, spec, instance, report, pass_name="reconcile", pass1_theme={}, pass1_questions=[]),
    )


@pytest.fixture(scope="module")
def good():
    return _load("good.html")


@pytest.mark.parametrize("theme", list(THEME_SPECS))
def test_every_theme_prompt_carries_protocol_text(theme, good):
    report = lint(good, profile="default")
    blind, reconcile = _prompts(theme, _plant(good, MARK), report)
    assert MARK in blind, f"{theme}: no narrative field from instance_keys reached the blind prompt"
    assert MARK in reconcile


def test_good_and_bad_prompts_differ_when_the_protocol_does(good):
    bad = _load("bad.html")
    report = lint(good, profile="default")  # same report for both: only the instance can differ
    differing = 0
    for theme, spec in THEME_SPECS.items():
        if _slice_instance(good, spec["instance_keys"]) != _slice_instance(bad, spec["instance_keys"]):
            differing += 1
            assert _prompts(theme, good, report)[0] != _prompts(theme, bad, report)[0], theme
    assert differing >= 6, f"only {differing} themes see a difference between good and bad"


def test_personal_identifiers_never_reach_a_prompt(good):
    report = lint(good, profile="default")
    inst = json.loads(json.dumps(good, ensure_ascii=False))
    inst["pi"] = {k: (ID_MARK if isinstance(v, str) else v) for k, v in inst["pi"].items()}
    inst["pi"]["training"] = [{"cert_no": ID_MARK, "issuer": "PI-ISSUER", "animal_scope": "mice", "date": ""}]
    for p in inst["participants"]:
        p.update(family_name=ID_MARK, given_name=ID_MARK, national_id_or_passport=ID_MARK)
        for t in p.get("training") or []:
            t["cert_no"] = ID_MARK
    inst["pi_declaration"]["name"] = ID_MARK
    inst["third_party"] = {"sponsor_org": ID_MARK, "ordering_investigator_name": ID_MARK, "sponsor_approver_name": ID_MARK}
    for theme in THEME_SPECS:
        for prompt in _prompts(theme, inst, report):
            assert ID_MARK not in prompt, f"{theme}: a personal identifier reached the prompt"
    assert "PI-ISSUER" in _prompts("personnel_and_training", inst, report)[0]  # training itself still gets through
