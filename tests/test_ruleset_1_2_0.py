"""Ruleset 1.2.0 (2026-10-21): trigger fixes from the 2026-10-19 audit, each one approved rule by rule
by the maintainer. Every test names the old behaviour so the change is visible in review."""
import copy

from src.adapters import schema_errors
from src.html_to_json import _parse_pain_category_structured, has_pilot_marker, parse_html
from src.linter_renderer import lint, render_html_with_refs
from src.rules import KNOWN_RULESET_VERSIONS, RULESET_VERSION

_EXP = {
    "label": "Experiment 1",
    "question": "Does treatment X affect Y?",
    "animals": {"species": "mouse", "strain": "C57BL/6", "sex": "both", "genetic_status": "WT", "n": 20,
                "age": {"value": 8, "unit": "weeks"}},
    "procedure_timeline": [],
    "severity_level_1_to_5": 1,
    "monitoring": {"parameters": [], "documentation": "Daily observation."},
    "humane_endpoints": {"general": ["Severe weight loss >20%."], "specific": []},
    "euthanasia": {"primary": "cervical dislocation", "parameters": "", "confirmation": ""},
    "fate": "euthanized",
}


def _fails(rule_id, profile="default", **exp_fields):
    exp = copy.deepcopy(_EXP)
    for key, value in exp_fields.items():
        if isinstance(value, dict) and isinstance(exp.get(key), dict):
            exp[key].update(value)
        else:
            exp[key] = value
    report = lint({"experiments": [exp]}, profile=profile)
    return [c for c in report["checklist"] if c.get("status") == "fail" and c.get("rule_id") == rule_id]


def test_version_is_1_2_0():
    assert RULESET_VERSION == "1.2.0" and "1.2.0" in KNOWN_RULESET_VERSIONS


def test_monitoring_documentation_is_read():
    # 1.1.0: three rules read monitoring.plan, which no schema or parser has
    assert not _fails("vet:consultation", severity_level_1_to_5=4,
                      monitoring={"documentation": "Veterinarian (DVM) reviewed the analgesic plan."})


def test_hebrew_vet_consultation_counts():
    assert not _fails("vet:consultation", severity_level_1_to_5=4,
                      monitoring={"documentation": "התייעצות עם וטרינר לפני כל ניתוח"})


def test_council_inhaled_anesthetic_gets_avma_checks():
    # 1.1.0: the form option was unrecognised, so every AVMA check was skipped. The missing confirmation is
    # a warning by default (the export rarely has the cell) and an error under strict_law, like CO2.
    eu = {"primary": "חומר הרדמה בשאיפה"}
    assert [c["severity"] for c in _fails("euthanasia:overdose-confirm", euthanasia=eu)] == ["warning"]
    assert [c["severity"] for c in _fails("euthanasia:overdose-confirm", "strict_law", euthanasia=eu)] == ["error"]


def test_hebrew_confirmation_counts_as_secondary_method():
    eu = {"primary": "isoflurane overdose", "confirmation": "נקע צוואר"}
    assert not _fails("euthanasia:secondary-method", euthanasia=eu)


def test_gm_status():
    # 1.1.0: substring match ('ge', 'ko' ...) and Hebrew 'yes' never matched
    assert _fails("gma:ibc", animals={"genetic_status": "כן"})
    assert _fails("gma:ibc", animals={"genetic_status": "כן, לא"})
    assert not _fails("gma:ibc", animals={"genetic_status": "not genetically modified"})
    assert not _fails("gma:ibc", animals={"genetic_status": "wild type"})
    assert _fails("gma:ibc", animals={"genetic_status": "knockout"})


def test_tumour_implant_is_not_stereotaxic():
    assert not _fails("special:stereotaxic", procedure_timeline=[{"step": "Tumors will be implanted into the right flank."}])
    assert _fails("special:stereotaxic", procedure_timeline=[{"step": "Stereotaxic injection into the striatum."}])


def test_neonatal_uses_declared_age():
    # 1.1.0: 'day 0' in the timeline made adult mice neonatal
    co2 = {"primary": "CO2", "parameters": "30% displacement per minute", "confirmation": ""}
    assert not _fails("special:neonatal-CO2", euthanasia=co2, procedure_timeline=[{"step": "Day 0: IP injection."}])
    assert _fails("special:neonatal-CO2", euthanasia=co2, animals={"age": {"value": 2, "unit": "days"}})


def test_precharged_chamber_needs_co2():
    assert not _fails("euthanasia:precharged-chamber", procedure_timeline=[{"step": "Dose from a pre-filled syringe."}])
    assert _fails("euthanasia:precharged-chamber", euthanasia={"primary": "CO2", "parameters": "pre-charged chamber"})


def test_reagents_are_not_viral_or_tumour_work():
    reagent = [{"step": "cDNA with Moloney murine leukemia virus reverse transcriptase."}]
    assert not _fails("special:biosafety", procedure_timeline=reagent)
    assert _fails("special:biosafety", procedure_timeline=[{"step": "Lentivirus injection."}])
    assert not _fails("special:oncology", procedure_timeline=[{"step": "Serum tumor necrosis factor ELISA."}])
    assert _fails("special:oncology", procedure_timeline=[{"step": "Subcutaneous tumour model."}])


def test_twenty_percent_with_clinical_signs_is_not_only_twenty():
    he = {"general": ["20% weight loss, hunched posture, lethargy"], "specific": []}
    assert not _fails("endpoints:20%-only", humane_endpoints=he)


def test_burden_keywords_are_whole_words():
    # 1.1.0: 'burn' matched the author name 'Burnett'; 'tumor burden' counted as a severe procedure
    burnett = [{"step": "References: Joseph Burnett C, et al."}]
    assert not _fails("pain:category-consistency", severity_level_1_to_5=3, procedure_timeline=burnett)
    calipers = [{"step": "Tumor burden measured by calipers."}]
    assert not _fails("pain:category-consistency", pain_category="D", procedure_timeline=calipers)
    assert _fails("pain:category-consistency", severity_level_1_to_5=3, procedure_timeline=[{"step": "Full-thickness burn model."}])


def test_cosmetic_surgery_is_not_cosmetics_testing():
    def cosmetics_fails(text):
        report = lint({"research": {"title_en": text}, "experiments": [copy.deepcopy(_EXP)]})
        return [c for c in report["checklist"] if c.get("rule_id") == "cosmetics:ban" and c.get("status") == "fail"]
    assert not cosmetics_fails("Patients not eligible to undergo cosmetic surgeries")
    assert cosmetics_fails("Skin irritation of a cosmetic cream")


def test_unknown_structured_method_gives_no_verdict():
    # 1.1.0: an unrecognised method_standard passed through and was reported UNACCEPTABLE
    assert not _fails("euthanasia:species-method", euthanasia={"primary": "", "method_standard": "Pentobarbital overdose IP"})


def test_co2_rate_reads_both_fields_and_ignores_purity():
    # 1.1.0: "100% CO2" (gas purity) counted as a displacement rate
    eu = {"primary": "CO2", "parameters": "100% CO2", "confirmation": "cervical dislocation"}
    assert _fails("euthanasia:displacement-rate", euthanasia=eu)
    # 1.1.0: conditions_text hid parameters, so a rate stated in parameters was not seen
    eu = {"primary": "CO2", "conditions_text": "Gradual fill.", "parameters": "30% chamber volume per minute",
          "confirmation": "cervical dislocation"}
    assert not _fails("euthanasia:displacement-rate", euthanasia=eu)


def test_postop_survival_is_recovery_not_final_fate():
    # 1.1.0: any experiment ending in euthanasia was skipped, so the rule never fired on a real export
    surgery = [{"step": "Craniotomy; recovery for 14 days, then euthanasia."}]
    assert _fails("postop:monitoring", procedure_timeline=surgery, monitoring={"documentation": "Standard observation."})
    assert not _fails("postop:monitoring", procedure_timeline=[{"step": "Terminal craniotomy under anesthesia."}])


def test_stray_letter_is_not_a_pain_category():
    # 1.1.0: 'e.g.' was read as USDA category E
    assert _parse_pain_category_structured("דרגה 2, e.g. weight loss")["parsed"] is None
    assert _parse_pain_category_structured("USDA category D")["parsed"] == "D"


def test_pilot_markers_cover_both_spellings():
    # 1.1.0: the parser knew only פיילוט / Pilot, the rule also פילוט, so a correct pilot failed title:track
    assert has_pilot_marker("מחקר פילוט", "") and has_pilot_marker("", "PILOT study") and not has_pilot_marker("מחקר", "Study")


def test_weight_is_escaped_in_render():
    exp = copy.deepcopy(_EXP)
    exp["animals"]["weight"] = {"value": 25, "unit": "<img src=x onerror=alert(1)>"}
    assert "<img src=x" not in render_html_with_refs({"experiments": [exp]})


def test_monitoring_fields_not_stated_are_optional_and_render_empty():
    exp = copy.deepcopy(_EXP)  # no initial_72h_daily / ongoing_per_week: the export did not state them
    assert not [e for e in schema_errors({"experiments": [exp]}) if "initial_72h_daily" in e or "ongoing_per_week" in e]
    def monitoring_block(e):
        return render_html_with_refs({"experiments": [e]}).split('class="monitoring"')[1].split("</table>")[0]
    assert "לא" not in monitoring_block(exp)
    exp["monitoring"]["initial_72h_daily"] = False
    assert "לא" in monitoring_block(exp)


def test_empty_section_does_not_take_the_next_sections_text():
    html = ('<html><body><div class="sub-header">תקציר לקהל הרחב</div>'
            '<div class="sub-header">חיפוש חלופות</div><div class="table"><div>מנועים: PubMed</div></div></body></html>')
    assert parse_html(html)["summaries"]["lay_he_≤150w"] == ""


def test_experiment_age_is_the_youngest_animal_row():
    # 1.1.0: the last animal row's age overwrote the others, so neonates listed first read as adults
    from pathlib import Path
    from bs4 import BeautifulSoup
    soup = BeautifulSoup((Path(__file__).resolve().parents[1] / "examples" / "known-good" / "good_IL-033-11-2000.html")
                         .read_text(encoding="utf-8"), "lxml")
    rows = [t for t in soup.find_all("table") if "תקופת גיל" in t.get_text() and not t.find("table")]
    rows[0].insert_before(next(t for t in rows if "יום" in t.get_text()).extract())  # the 8-day row first, 8-week rows last
    assert parse_html(str(soup))["experiments"][0]["animals"]["age"] == {"value": 8.0, "unit": "days"}
