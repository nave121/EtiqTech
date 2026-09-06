"""The reference adapter (il-council-html) must emit canonical-schema vocabulary.

Decision 2026-09-06 (maintainer): normalize the parser, keep the schema strict. Before this the
parser passed Hebrew form values straight through and 0 of 94 fixtures validated.
"""
import glob
import pathlib

import pytest

from src.adapters import schema_errors
from src.html_to_json import _norm, _norm_enrichment, _norm_fate, _norm_sex, _norm_source, _AGE_UNIT, _WEIGHT_UNIT, parse_html
from src.linter_renderer import lint

ROOT = pathlib.Path(__file__).resolve().parents[1]
FIXTURES = sorted(glob.glob(str(ROOT / "examples" / "**" / "*.html"), recursive=True))
# demo_render.html is a hand-made demo page without the rationale / timeline / humane-endpoint
# sections; the schema requires them and the parser does not invent absent sections.
KNOWN_INCOMPLETE = {"demo_render.html"}


def _instances():
    for path in FIXTURES:
        yield path, parse_html(pathlib.Path(path).read_text(encoding="utf-8"))


def test_fixture_count():
    assert len(FIXTURES) == 94


@pytest.mark.parametrize("path", FIXTURES, ids=lambda p: pathlib.Path(p).name)
def test_parser_output_validates_against_schema(path):
    inst = parse_html(pathlib.Path(path).read_text(encoding="utf-8"))
    errs = [str(e) for e in schema_errors(inst)]
    if pathlib.Path(path).name in KNOWN_INCOMPLETE:
        assert errs and all("is a required property" in e for e in errs), errs
        return
    assert errs == []


def test_no_hebrew_left_in_enum_fields():
    hebrew = lambda s: any("֐" <= ch <= "׿" for ch in str(s))  # noqa: E731
    for path, inst in _instances():
        for at in inst.get("animals_total", []):
            assert not hebrew(at["sex"]) and not hebrew(at["source"]), (path, at)
        for e in inst.get("experiments", []):
            a = e.get("animals") or {}
            assert not hebrew(a.get("sex", "")), (path, a.get("sex"))
            assert not hebrew((a.get("age") or {}).get("unit", "")), path
            assert not hebrew((a.get("weight") or {}).get("unit", "")), path
            assert not hebrew(e.get("fate", "")), (path, e.get("fate"))
            assert (e.get("housing") or {}).get("enrichment", "standard") in ("standard", "custom"), path


def test_single_sex_design_is_detected_on_real_exports():
    flags = [lint(inst, profile="default")["analysis"]["summary"]["single_sex_design"] for _, inst in _instances()]
    assert any(flags), "no fixture is recognised as single-sex; sex normalization is not reaching the linter"


@pytest.mark.parametrize(
    "fn, raw, expected",
    [
        (_norm_sex, "זכר", "M"),
        (_norm_sex, "נקבה", "F"),
        (_norm_sex, "זכר, נקבה", "both"),
        (_norm_sex, "לא חשוב", "unknown"),
        (_norm_sex, None, "unknown"),
        (_norm_sex, "F", "F"),
        (_norm_source, "מקור חיצוני", "vendor"),
        (_norm_source, "גידול עצמי", "in-house"),
        (_norm_source, "גידול עצמי, מקור חיצוני", "other"),
        (_norm_source, "vendor", "vendor"),
        (_norm_fate, "המתה", "euthanasia"),
        (_norm_fate, "euthanasia", "euthanasia"),
        (_norm_fate, "משהו אחר", "other"),
        (_norm_fate, "", ""),
        (lambda v: _norm(_AGE_UNIT, v), "שבוע", "weeks"),
        (lambda v: _norm(_AGE_UNIT, v), "שנה", "years"),
        (lambda v: _norm(_WEIGHT_UNIT, v), "גרם", "g"),
        (lambda v: _norm(_WEIGHT_UNIT, v), 'ק"ג', "kg"),
        (lambda v: _norm(_WEIGHT_UNIT, v), "kg", "kg"),
    ],
)
def test_vocabulary_maps(fn, raw, expected):
    assert fn(raw) == expected


def test_unknown_values_pass_through_unchanged():
    assert _norm_sex("hermaphrodite") == "hermaphrodite"
    assert _norm(_AGE_UNIT, "fortnights") == "fortnights"


def test_enrichment_prose_moves_to_enrichment_custom():
    assert _norm_enrichment("") == {"enrichment": "standard"}
    assert _norm_enrichment("אין") == {"enrichment": "standard"}
    assert _norm_enrichment("גליל פלסטיק, ריפוד") == {"enrichment": "custom", "enrichment_custom": "גליל פלסטיק, ריפוד"}
