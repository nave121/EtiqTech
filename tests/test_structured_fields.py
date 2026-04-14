import copy

from src.html_to_json import parse_html
from src.linter_renderer import lint, render_html
from src.schema import IACUC_SCHEMA_V2


_BASE_INSTANCE = {
    "header": {"protocol_id": "99999", "institution": "Test University"},
    "research": {
        "title_he": "כותרת בדיקה",
        "title_en": "Structured Fields Test",
        "request_type": "regular",
        "is_continuation": False,
        "third_party_service": False,
        "approval_term_years": 3,
        "sites": [{"name": "במוסד עצמו", "steps": ["כל השלבים"]}],
    },
    "pi": {
        "id_type": "TZ",
        "id_number": "123456789",
        "last_name_he": "כהן",
        "first_name_he": "דוד",
        "last_name_en": "Cohen",
        "first_name_en": "David",
        "email": "d@test.ac.il",
        "phone_primary": "SYNTH-0000000",
        "phone_secondary": "",
        "institutional_cert_no": "CERT-1",
        "faculty": "Medicine",
        "department": "Physiology",
        "training": [
            {"cert_no": "C1", "issuer": "TAMIR", "animal_scope": "rodents", "date": "2023-01-01"}
        ],
    },
    "participants": [],
    "summaries": {
        "scientific_en_≤300w": "A structured-fields test protocol summary.",
        "lay_he_≤150w": "תקציר לציבור.",
    },
    "alternatives_search": {
        "engines": ["PubMed"],
        "date": "2025-01-01",
        "queries": ["animal alternatives rodent model"],
        "conclusion": "No validated alternative exists for this model.",
    },
    "animals_total": [
        {
            "species": "mouse",
            "species_standard": "mouse",
            "strain": "C57BL/6",
            "sex": "both",
            "genetic_status": "WT",
            "source": "vendor",
            "n_total": 20,
            "age": "8 weeks",
        }
    ],
    "n_justification": {
        "method": "power",
        "details": "Power analysis at alpha=0.05 and power=0.8 requires n=10 per group.",
        "attachments": [],
    },
    "experiments": [
        {
            "label": "Experiment 1",
            "question": "Does treatment X affect Y?",
            "animals": {
                "species": "mouse",
                "species_standard": "mouse",
                "strain": "C57BL/6",
                "sex": "both",
                "genetic_status": "WT",
                "n": 20,
                "age": {"value": 8, "unit": "weeks"},
                "source": "vendor",
            },
            "housing": {"group_housed": True, "enrichment": "standard"},
            "housing_density": {
                "cage_floor_area_cm2": 193.6,
                "animals_per_enclosure": 2,
                "breeding_with_litter": False,
            },
            "rationale_species_strain_sex": "C57BL/6 mice are standard for this model.",
            "procedure_timeline": [{"day_or_timepoint": "Day 0", "step": "Thoracotomy surgery."}],
            "restraint": {
                "used": True,
                "method": "brief tube restraint",
                "max_duration_minutes": 10,
                "sessions_per_animal": 1,
                "acclimation": "Handled for two days before restraint.",
                "monitoring": "Continuous observation during restraint.",
                "humane_removal_criteria": "Stop if dyspnea or persistent struggling occurs.",
                "food_water_plan": "",
                "justification": "Needed for standardized imaging setup.",
            },
            "analgesia": [{"phase": "post", "agent": "buprenorphine", "dose": "0.05 mg/kg", "route": "SC", "frequency": "q8h"}],
            "anesthesia": [],
            "anesthesia_drugs": [
                {
                    "agent": "isoflurane",
                    "dose": "2%",
                    "route": "inhalation",
                    "frequency": "continuous",
                    "monitoring": "respiratory rate",
                }
            ],
            "severity_level_1_to_5": 4,
            "pain_category": "D",
            "monitoring": {
                "initial_72h_daily": True,
                "ongoing_per_week": 7,
                "parameters": ["weight", "activity"],
                "documentation": "Score sheets retained.",
            },
            "humane_endpoints": {"general": ["Weight loss >10%."], "specific": []},
            "euthanasia": {
                "primary": "CO2",
                "method_standard": "CO2",
                "parameters": "Gradual fill 30-70% chamber volume per minute.",
                "conditions_text": "Gradual fill 30-70% chamber volume per minute with secondary cervical dislocation.",
                "confirmation": "cervical dislocation",
            },
            "reuse_or_prior_procedures": {
                "has_prior": True,
                "prior_protocol_ids": ["PREV-100"],
            },
            "reuse_review": {
                "prior_severity": "mild",
                "fully_recovered": True,
                "new_procedure_severity": "moderate",
                "vet_consulted": True,
            },
            "field_study_permits": {
                "field_study": True,
                "wildlife": True,
                "collection_permit_ids": "COL-10",
                "protected_species": False,
                "cites_documentation": "",
                "wildlife_pathogen_handling": True,
                "biosafety_approval_id": "BSL2-2025-001",
                "field_euthanasia_method": "Isoflurane overdose",
                "field_euthanasia_details": "Performed in portable chamber before transport.",
            },
            "fate": "euthanasia",
        }
    ],
    "pi_declaration": {"name": "David Cohen", "date": "2025-01-01"},
    "is_colony": False,
    "colony_block": {},
    "postmortem_processing": {"used": False},
    "chair_statement": {},
}


def _make_instance():
    return copy.deepcopy(_BASE_INSTANCE)


def test_schema_exposes_structured_fields():
    animals_total_props = IACUC_SCHEMA_V2["properties"]["animals_total"]["items"]["properties"]
    exp_props = IACUC_SCHEMA_V2["properties"]["experiments"]["items"]["properties"]
    animal_props = exp_props["animals"]["properties"]
    euthanasia_props = exp_props["euthanasia"]["properties"]

    assert "species_standard" in animals_total_props
    assert "species_standard" in animal_props
    assert "pain_category" in exp_props
    assert "anesthesia_drugs" in exp_props
    assert "housing_density" in exp_props
    assert "restraint" in exp_props
    assert "reuse_review" in exp_props
    assert "field_study_permits" in exp_props
    assert "method_standard" in euthanasia_props
    assert "conditions_text" in euthanasia_props


def test_render_and_parse_roundtrip_preserves_structured_fields():
    instance = _make_instance()

    html = render_html(instance)
    parsed = parse_html(html)

    parsed_exp = parsed["experiments"][0]
    assert parsed["animals_total"][0]["species_standard"] == "mouse"
    assert parsed_exp["animals"]["species_standard"] == "mouse"
    assert parsed_exp["pain_category"] == "D"
    assert parsed_exp["euthanasia"]["method_standard"] == "CO2"
    assert "secondary cervical dislocation" in parsed_exp["euthanasia"]["conditions_text"]
    assert parsed_exp["anesthesia_drugs"][0]["agent"] == "isoflurane"
    assert parsed_exp["anesthesia_drugs"][0]["frequency"] == "continuous"
    assert parsed_exp["housing_density"]["cage_floor_area_cm2"] == 193.6
    assert parsed_exp["restraint"]["max_duration_minutes"] == 10
    assert parsed_exp["reuse_review"]["vet_consulted"] is True
    assert parsed_exp["field_study_permits"]["biosafety_approval_id"] == "BSL2-2025-001"


def test_linter_prefers_structured_species_and_method():
    instance = _make_instance()
    exp = instance["experiments"][0]

    exp["animals"]["species"] = "mouse"
    exp["animals"]["species_standard"] = "zebrafish"
    exp["euthanasia"]["primary"] = "cervical dislocation"
    exp["euthanasia"]["method_standard"] = "CO2"
    exp["euthanasia"]["confirmation"] = "no opercular movement"
    exp["euthanasia"]["conditions_text"] = ""

    report = lint(instance, profile="default")
    refs = {item["reference"] for item in report["checklist"] if item["status"] == "fail"}

    assert "euthanasia:species-method:exp-1" in refs


def test_linter_prefers_structured_pain_category():
    instance = _make_instance()
    exp = instance["experiments"][0]

    exp["severity_level_1_to_5"] = 5
    exp["pain_category"] = "C"

    report = lint(instance, profile="default")
    refs = {item["reference"] for item in report["checklist"] if item["status"] == "fail"}

    assert "pain:category-consistency:exp-1" in refs


def test_linter_prefers_structured_anesthesia_drugs():
    instance = _make_instance()
    exp = instance["experiments"][0]

    exp["procedure_timeline"] = [{"day_or_timepoint": "Day 0", "step": "Vecuronium infusion for imaging."}]
    exp["anesthesia"] = []
    exp["anesthesia_drugs"] = [
        {
            "agent": "isoflurane",
            "dose": "2%",
            "route": "inhalation",
            "frequency": "continuous",
            "monitoring": "respiratory rate",
        }
    ]

    report = lint(instance, profile="default")
    refs = {item["reference"] for item in report["checklist"] if item["status"] == "fail"}

    assert "paralytic:without-anesthesia:exp-1" not in refs
