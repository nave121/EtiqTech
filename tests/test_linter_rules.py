"""
Per-rule parametrized linter tests (ESLint RuleTester pattern).

Each rule gets 2-4 focused test cases using minimal synthetic protocol instances.
This scales independently of fixture files — adding a new rule means adding a
new parametrize block, not a new HTML fixture.

Per professor feedback: this tier covers ~80% of test cases and is the most
maintainable approach for a 100+ rule system.
"""

import copy
import pytest
from src.linter_renderer import lint

# ---------------------------------------------------------------------------
# Minimal valid instance factory
# ---------------------------------------------------------------------------

_BASE_INSTANCE = {
    "header": {"protocol_id": "99999", "institution": "Test University"},
    "research": {
        "title_he": "כותרת בדיקה",
        "title_en": "Test Protocol",
        "request_type": "regular",
        "is_continuation": False,
        "third_party_service": False,
        "approval_term_years": 3,
        "sites": [],
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
        "scientific_en_≤300w": "A test protocol summary.",
        "lay_he_≤150w": "תקציר לציבור.",
    },
    "alternatives_search": {
        "engines": ["PubMed", "Embase"],
        "date": "2025-01-01",
        "queries": ["animal alternatives rodent model"],
        "conclusion": "No validated alternative exists for this model.",
    },
    "animals_total": [
        {"species": "mouse", "strain": "C57BL/6", "sex": "both",
         "genetic_status": "WT", "source": "vendor", "n_total": 20}
    ],
    "n_justification": {
        "method": "power",
        "details": "Power analysis at α=0.05, β=0.8 with expected effect size d=0.8 requires n=10 per group.",
        "attachments": [],
    },
    "experiments": [
        {
            "label": "Experiment 1",
            "question": "Does treatment X affect Y?",
            "animals": {
                "species": "mouse", "strain": "C57BL/6", "sex": "both",
                "genetic_status": "WT", "n": 20,
            },
            "housing": {"group_housed": True},
            "procedure_timeline": [],
            "analgesia": [],
            "anesthesia": [],
            "severity_level_1_to_5": 1,
            "monitoring": {"plan": "Daily observation."},
            "humane_endpoints": {"general": ["Severe weight loss >20%."], "specific": []},
            "euthanasia": {"primary": "cervical dislocation", "parameters": "", "confirmation": ""},
            "fate": "euthanized",
        }
    ],
    "pi_declaration": {"affirmed": True},
    "is_colony": False,
}


def _make(**overrides):
    """Return a deep copy of the base instance with top-level keys overridden."""
    inst = copy.deepcopy(_BASE_INSTANCE)
    inst.update(overrides)
    return inst


def _get_checks(report, ref_prefix):
    """Return all checklist items whose reference starts with ref_prefix."""
    return [
        c for c in report["checklist"]
        if c.get("reference", "").startswith(ref_prefix)
    ]


def _failed_checks(report, ref_prefix):
    return [c for c in _get_checks(report, ref_prefix) if c.get("status") == "fail"]


# ---------------------------------------------------------------------------
# Rule: animals:totals-vs-exps
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("animals_total,exp_n,should_fail", [
    # Mismatch: total says 100 but experiment has 20
    ([{"species": "mouse", "strain": "C57BL/6", "sex": "both",
       "genetic_status": "WT", "source": "vendor", "n_total": 100}], 20, True),
    # Match: total == experiment n
    ([{"species": "mouse", "strain": "C57BL/6", "sex": "both",
       "genetic_status": "WT", "source": "vendor", "n_total": 20}], 20, False),
    # Mismatch: 0 declared but 20 used
    ([{"species": "mouse", "strain": "C57BL/6", "sex": "both",
       "genetic_status": "WT", "source": "vendor", "n_total": 0}], 20, True),
])
def test_animals_totals_vs_exps(animals_total, exp_n, should_fail):
    experiments = copy.deepcopy(_BASE_INSTANCE["experiments"])
    experiments[0]["animals"]["n"] = exp_n
    inst = _make(animals_total=animals_total, experiments=experiments)
    report = lint(inst, profile="default")
    failed = _failed_checks(report, "animals:totals-vs-exps")
    if should_fail:
        assert failed, "Expected animals:totals-vs-exps to fail"
        assert report["status"] == "fail"
    else:
        assert not failed, f"Expected animals:totals-vs-exps to pass, got: {failed}"


# ---------------------------------------------------------------------------
# Rule: term:track
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("request_type,years,should_fail,expected_severity", [
    # Pilot + 4 years → warning (in-range but not ideal for pilot)
    ("pilot", 4, True, "warning"),
    # Pilot + 2 years → warning (in-range but not ideal for pilot)
    ("pilot", 2, True, "warning"),
    # Pilot + 1 year → pass (ideal)
    ("pilot", 1, False, None),
    # Regular + 3 years → pass
    ("regular", 3, False, None),
])
def test_term_track(request_type, years, should_fail, expected_severity):
    research = copy.deepcopy(_BASE_INSTANCE["research"])
    research["request_type"] = request_type
    research["approval_term_years"] = years
    inst = _make(research=research)
    report = lint(inst, profile="default")
    failed = _failed_checks(report, "term:track")
    if should_fail:
        assert failed, f"Expected term:track to fail for {request_type}/{years}y"
        if expected_severity:
            assert failed[0]["severity"] == expected_severity
    else:
        assert not failed, f"Expected term:track to pass for {request_type}/{years}y"


# ---------------------------------------------------------------------------
# Rule: alts:missing
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("alts,profile,expected_status,expected_severity", [
    # All empty → missing
    ({}, "default", "fail", "warning"),
    ({}, "strict_law", "fail", "error"),
    # All fields None → missing
    ({"engines": None, "queries": None, "conclusion": None}, "default", "fail", "warning"),
    # Has queries and conclusion but no engines → NOT missing (alts:engines fires instead)
    ({"engines": [], "queries": ["q1"], "conclusion": "c"}, "default", "pass", None),
])
def test_alts_missing(alts, profile, expected_status, expected_severity):
    inst = _make(alternatives_search=alts)
    report = lint(inst, profile=profile)
    items = _failed_checks(report, "alts:missing")
    if expected_status == "fail":
        assert items, f"Expected alts:missing to fire (profile={profile!r})"
        if expected_severity:
            assert items[0]["severity"] == expected_severity
    else:
        assert not items, f"Expected alts:missing not to fire"


# ---------------------------------------------------------------------------
# Rule: alts:engines  (law-critical: warning in default, error in strict_law)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("engines,profile,should_fail,expected_severity", [
    # Empty engines, default → warning
    ([], "default", True, "warning"),
    # Empty engines, strict_law → error
    ([], "strict_law", True, "error"),
    # Non-empty engines → pass
    (["PubMed"], "default", False, None),
    (["PubMed", "Embase"], "strict_law", False, None),
])
def test_alts_engines(engines, profile, should_fail, expected_severity):
    alts = {"engines": engines, "queries": ["q1"], "conclusion": "c"}
    inst = _make(alternatives_search=alts)
    report = lint(inst, profile=profile)
    items = _failed_checks(report, "alts:engines")
    if should_fail:
        assert items, f"Expected alts:engines to fire (engines={engines!r}, profile={profile!r})"
        if expected_severity:
            assert items[0]["severity"] == expected_severity
    else:
        assert not items, f"Expected alts:engines not to fire (engines={engines!r})"


# ---------------------------------------------------------------------------
# Rule: alts:queries  (advisory: always warning)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("queries,engines,should_fail", [
    ([], ["PubMed"], True),
    (["at least one query"], ["PubMed"], False),
    (["q1", "q2"], ["PubMed"], False),
    # EU standardized search — empty queries is acceptable
    ([], ["Good Search Practice on Animal Alternative-EU"], False),
    ([], ["good search practice on animal alternative-eu"], False),
])
def test_alts_queries(queries, engines, should_fail):
    alts = {"engines": engines, "queries": queries, "conclusion": "c"}
    inst = _make(alternatives_search=alts)
    report = lint(inst, profile="default")
    items = _failed_checks(report, "alts:queries")
    if should_fail:
        assert items, f"Expected alts:queries to fire"
        assert items[0]["severity"] == "warning"
    else:
        assert not items, f"Expected alts:queries not to fire"


# ---------------------------------------------------------------------------
# Rule: alts:conclusion  (advisory: always warning)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("conclusion,should_fail", [
    ("", True),
    ("   ", True),
    ("No alternative exists.", False),
])
def test_alts_conclusion(conclusion, should_fail):
    alts = {"engines": ["PubMed"], "queries": ["q1"], "conclusion": conclusion}
    inst = _make(alternatives_search=alts)
    report = lint(inst, profile="default")
    items = _failed_checks(report, "alts:conclusion")
    if should_fail:
        assert items, f"Expected alts:conclusion to fire for {conclusion!r}"
        assert items[0]["severity"] == "warning"
    else:
        assert not items, f"Expected alts:conclusion not to fire"


# ---------------------------------------------------------------------------
# Rule: cosmetics:ban  (law-critical — warning/default, error/strict_law)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("title_en,question,profile,should_fire,expected_severity", [
    ("Shampoo ocular safety study", "Evaluate irritation after shampoo exposure.", "default", True, "warning"),
    ("Household cleaner toxicity study", "Assess detergent exposure.", "strict_law", True, "error"),
    ("Cancer immunology study", "Evaluate tumor growth after treatment.", "default", False, None),
])
def test_cosmetics_ban(title_en, question, profile, should_fire, expected_severity):
    research = copy.deepcopy(_BASE_INSTANCE["research"])
    research["title_en"] = title_en
    experiments = [copy.deepcopy(_BASE_INSTANCE["experiments"][0])]
    experiments[0]["question"] = question
    inst = _make(research=research, experiments=experiments)
    report = lint(inst, profile=profile)
    items = _failed_checks(report, "cosmetics:ban")
    if should_fire:
        assert items, "Expected cosmetics:ban to fire"
        assert items[0]["severity"] == expected_severity
    else:
        assert not items, "Expected cosmetics:ban not to fire"


# ---------------------------------------------------------------------------
# Rule: pi:training
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("training,should_fail", [
    ([], True),
    ([{"cert_no": "C1", "issuer": "TAMIR", "animal_scope": "rodents", "date": "2023-01-01"}], False),
])
def test_pi_training(training, should_fail):
    pi = copy.deepcopy(_BASE_INSTANCE["pi"])
    pi["training"] = training
    inst = _make(pi=pi)
    report = lint(inst, profile="default")
    failed = _failed_checks(report, "pi:training")
    if should_fail:
        assert failed, "Expected pi:training to fail"
        assert report["status"] == "fail"
    else:
        assert not failed, "Expected pi:training to pass"


# ---------------------------------------------------------------------------
# Rule: summaries:lay-length  (>150 words)
# ---------------------------------------------------------------------------

SHORT_LAY = "קצר."
LONG_LAY = " ".join(["מילה"] * 160)  # 160 Hebrew words
SHORT_SCI = "Short."
LONG_SCI = " ".join(["science"] * 2605)


@pytest.mark.parametrize("lay_text,should_fail", [
    (SHORT_LAY, False),
    (LONG_LAY, True),
])
def test_summaries_lay_length(lay_text, should_fail):
    summaries = {"scientific_en_≤300w": "Short.", "lay_he_≤150w": lay_text}
    inst = _make(summaries=summaries)
    report = lint(inst, profile="default")
    failed = _failed_checks(report, "summaries:lay-length")
    if should_fail:
        assert failed, "Expected summaries:lay-length to fail"
        assert failed[0]["severity"] == "warning"
        assert report["status"] == "pass"
    else:
        assert not failed, "Expected summaries:lay-length to pass"


# ---------------------------------------------------------------------------
# Rule: summaries:scientific-length  (>2500 words, advisory)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("scientific_text,should_fail", [
    (SHORT_SCI, False),
    (LONG_SCI, True),
])
def test_summaries_scientific_length(scientific_text, should_fail):
    summaries = {"scientific_en_≤300w": scientific_text, "lay_he_≤150w": SHORT_LAY}
    inst = _make(summaries=summaries)
    report = lint(inst, profile="default")
    failed = _failed_checks(report, "summaries:scientific-length")
    if should_fail:
        assert failed, "Expected summaries:scientific-length to fail"
        assert failed[0]["severity"] == "warning"
        assert report["status"] == "pass"
    else:
        assert not failed, "Expected summaries:scientific-length to pass"


# ---------------------------------------------------------------------------
# Rule: sex:sabv  (advisory — single-sex designs need scientific SABV rationale)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("sex,rationale,should_fire", [
    ("F", "", True),
    ("M", "Male-only design is easier operationally and reduces variability.", True),
    ("F", "Female mice are required because the ovarian hormone cycle is a core biological variable in this model.", False),
    ("both", "", False),
])
def test_sex_sabv(sex, rationale, should_fire):
    experiments = [copy.deepcopy(_BASE_INSTANCE["experiments"][0])]
    experiments[0]["animals"]["sex"] = sex
    experiments[0]["rationale_species_strain_sex"] = rationale
    animals_total = [copy.deepcopy(_BASE_INSTANCE["animals_total"][0])]
    animals_total[0]["sex"] = sex
    inst = _make(experiments=experiments, animals_total=animals_total)
    report = lint(inst, profile="default")
    items = _failed_checks(report, "sex:sabv")
    if should_fire:
        assert items, f"Expected sex:sabv to fire for sex={sex!r}"
        assert items[0]["severity"] == "warning"
    else:
        assert not items, f"Expected sex:sabv not to fire for sex={sex!r}"


# ---------------------------------------------------------------------------
# Rule: N:justification-detail  (N≥500, short details)
# ---------------------------------------------------------------------------

SHORT_JUSTIFICATION = "Standard in the field."
LONG_JUSTIFICATION = (
    "Power analysis at α=0.05, 1-β=0.8, effect size d=0.5: n=64 per group. "
    "Four groups (vehicle, low, mid, high dose) × 64 = 256. Reserve 20% for "
    "expected attrition = 308. Two cohorts = 616 total. Justified by prior pilot data."
)

@pytest.mark.parametrize("n_total,details,should_fire", [
    # Large N with short justification → fires
    (600, SHORT_JUSTIFICATION, True),
    # Large N with long justification → no fire
    (600, LONG_JUSTIFICATION, False),
    # Small N → no fire regardless
    (10, SHORT_JUSTIFICATION, False),
])
def test_N_justification_detail(n_total, details, should_fire):
    animals_total = [{"species": "mouse", "strain": "C57BL/6", "sex": "both",
                      "genetic_status": "WT", "source": "vendor", "n_total": n_total}]
    experiments = [copy.deepcopy(_BASE_INSTANCE["experiments"][0])]
    experiments[0]["animals"]["n"] = n_total
    n_just = {"method": "power", "details": details, "attachments": []}
    inst = _make(animals_total=animals_total, experiments=experiments, n_justification=n_just)
    report = lint(inst, profile="default")
    items = _failed_checks(report, "N:justification-detail")
    if should_fire:
        assert items, f"Expected N:justification-detail to fire (N={n_total})"
        assert items[0]["severity"] == "warning"
    else:
        assert not items, f"Expected N:justification-detail not to fire (N={n_total})"


# ---------------------------------------------------------------------------
# Rule: euthanasia:CO2  (law-critical — warning in default, error in strict_law)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("primary,confirmation,profile,should_fire,expected_severity", [
    ("CO2", "", "default", True, "warning"),
    ("CO2", "", "strict_law", True, "error"),
    ("CO2", "Confirmed by cessation of breathing and cardiac arrest.", "default", False, None),
    ("cervical dislocation", "", "default", False, None),
])
def test_euthanasia_CO2(primary, confirmation, profile, should_fire, expected_severity):
    experiments = [copy.deepcopy(_BASE_INSTANCE["experiments"][0])]
    experiments[0]["euthanasia"] = {"primary": primary, "parameters": "", "confirmation": confirmation}
    inst = _make(experiments=experiments)
    report = lint(inst, profile=profile)
    items = _failed_checks(report, "euthanasia:CO2")
    if should_fire:
        assert items, f"Expected euthanasia:CO2 to fire (primary={primary!r}, profile={profile!r})"
        assert items[0]["severity"] == expected_severity
    else:
        assert not items, f"Expected euthanasia:CO2 not to fire"


# ---------------------------------------------------------------------------
# Rule: severity:analgesia  (law-critical — error in BOTH profiles per §1 Schedule + §23)
# ---------------------------------------------------------------------------

INVASIVE_PROCEDURE = [{"step": "laparotomy and tumor resection"}]
NON_INVASIVE_PROCEDURE = [{"step": "oral gavage and blood draw"}]
ANALGESIA_ROW = [{"agent": "buprenorphine", "dose": "0.05 mg/kg", "route": "SC", "frequency": "q8h"}]

@pytest.mark.parametrize("severity,timeline,analgesia,profile,should_fire", [
    # Severity 3 + invasive + no analgesia → fires as error in both profiles
    (3, INVASIVE_PROCEDURE, [], "default", True),
    (3, INVASIVE_PROCEDURE, [], "strict_law", True),
    # Severity 3 + invasive + analgesia present → no fire
    (3, INVASIVE_PROCEDURE, ANALGESIA_ROW, "default", False),
    # Severity 2 + invasive → no fire (below threshold)
    (2, INVASIVE_PROCEDURE, [], "default", False),
    # Severity 4 + non-invasive keywords → no fire (not detected as invasive)
    (4, NON_INVASIVE_PROCEDURE, [], "default", False),
])
def test_severity_analgesia(severity, timeline, analgesia, profile, should_fire):
    experiments = [copy.deepcopy(_BASE_INSTANCE["experiments"][0])]
    experiments[0]["severity_level_1_to_5"] = severity
    experiments[0]["procedure_timeline"] = timeline
    experiments[0]["analgesia"] = analgesia
    inst = _make(experiments=experiments)
    report = lint(inst, profile=profile)
    items = _failed_checks(report, "severity:analgesia")
    if should_fire:
        assert items, f"Expected severity:analgesia to fire (sev={severity}, profile={profile!r})"
        assert items[0]["severity"] == "error", (
            f"severity:analgesia must be 'error' in both profiles (got {items[0]['severity']!r})"
        )
    else:
        assert not items, f"Expected severity:analgesia not to fire (sev={severity})"


# ---------------------------------------------------------------------------
# Rule: paralytic:without-anesthesia  (law-critical — warning/default, error/strict_law)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("timeline,anesthesia,profile,should_fire,expected_severity", [
    ([{"step": "Administer vecuronium to induce paralysis for imaging."}], [], "default", True, "warning"),
    ([{"step": "Administer vecuronium to induce paralysis for imaging."}], [], "strict_law", True, "error"),
    (
        [{"step": "Administer vecuronium to induce paralysis for imaging."}],
        [{"agent": "isoflurane", "dose": "2%", "route": "inhalation", "frequency": "continuous"}],
        "default",
        False,
        None,
    ),
    ([{"step": "Tail-vein injection of compound X."}], [], "default", False, None),
])
def test_paralytic_without_anesthesia(timeline, anesthesia, profile, should_fire, expected_severity):
    experiments = [copy.deepcopy(_BASE_INSTANCE["experiments"][0])]
    experiments[0]["procedure_timeline"] = timeline
    experiments[0]["anesthesia"] = anesthesia
    inst = _make(experiments=experiments)
    report = lint(inst, profile=profile)
    items = _failed_checks(report, "paralytic:without-anesthesia")
    if should_fire:
        assert items, "Expected paralytic:without-anesthesia to fire"
        assert items[0]["severity"] == expected_severity
    else:
        assert not items, "Expected paralytic:without-anesthesia not to fire"


# ---------------------------------------------------------------------------
# Rule: pain:category-consistency  (law-critical — low declared severity vs painful procedures)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("severity,pain_category_structured,timeline,profile,should_fire,expected_severity", [
    (2, None, [{"step": "Perform laparotomy and tumor implant."}], "default", True, "warning"),
    (2, None, [{"step": "Perform laparotomy and tumor implant."}], "strict_law", True, "error"),
    (3, None, [{"step": "Thoracotomy with post-procedure monitoring."}], "default", True, "warning"),
    (4, None, [{"step": "Thoracotomy with post-procedure monitoring."}], "strict_law", False, None),
    (2, None, [{"step": "Tail-vein injection and body weight follow-up."}], "default", False, None),
    (
        5,
        {"raw": "Category C", "parsed": "C"},
        [{"step": "Perform laparotomy and tumor implant."}],
        "default",
        True,
        "warning",
    ),
    (
        5,
        {"raw": "USDA category D", "parsed": "D"},
        [{"step": "Thoracotomy with post-procedure monitoring."}],
        "strict_law",
        True,
        "error",
    ),
    (
        1,
        {"raw": "Category E", "parsed": "E"},
        [{"step": "Thoracotomy with post-procedure monitoring."}],
        "strict_law",
        False,
        None,
    ),
    (
        2,
        {"raw": "דרגה 2", "parsed": None},
        [{"step": "Perform laparotomy and tumor implant."}],
        "default",
        True,
        "warning",
    ),
])
def test_pain_category_consistency(
    severity,
    pain_category_structured,
    timeline,
    profile,
    should_fire,
    expected_severity,
):
    experiments = [copy.deepcopy(_BASE_INSTANCE["experiments"][0])]
    experiments[0]["severity_level_1_to_5"] = severity
    if pain_category_structured is not None:
        experiments[0]["pain_category_structured"] = pain_category_structured
    experiments[0]["procedure_timeline"] = timeline
    inst = _make(experiments=experiments)
    report = lint(inst, profile=profile)
    items = _failed_checks(report, "pain:category-consistency")
    if should_fire:
        assert items, "Expected pain:category-consistency to fire"
        assert items[0]["severity"] == expected_severity
    else:
        assert not items, "Expected pain:category-consistency not to fire"


# ---------------------------------------------------------------------------
# Rule: endpoints:20%-only  (law-critical — warning in default, error in strict_law)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("endpoints_text,profile,should_fire,expected_severity", [
    # Only mentions weight loss — default: warning
    (["Animals will be euthanized upon 20% weight loss."], "default", True, "warning"),
    # Only mentions weight loss — strict_law: error
    (["Animals will be euthanized upon 20% weight loss."], "strict_law", True, "error"),
    # Weight loss + model-specific criterion (tumor) — no fire
    (["20% weight loss or tumor volume >1000 mm³."], "default", False, None),
    # No endpoint text — no fire
    ([], "default", False, None),
    # Specific score-based endpoint — no fire
    (["Neurological score ≥3 or loss of righting reflex."], "default", False, None),
])
def test_endpoints_20_percent_only(endpoints_text, profile, should_fire, expected_severity):
    experiments = [copy.deepcopy(_BASE_INSTANCE["experiments"][0])]
    experiments[0]["humane_endpoints"] = {"general": endpoints_text, "specific": []}
    inst = _make(experiments=experiments)
    report = lint(inst, profile=profile)
    items = _failed_checks(report, "endpoints:20%-only")
    if should_fire:
        assert items, f"Expected endpoints:20%-only to fire (profile={profile!r})"
        assert items[0]["severity"] == expected_severity
    else:
        assert not items, f"Expected endpoints:20%-only not to fire (text={endpoints_text!r})"


# ---------------------------------------------------------------------------
# Rule: endpoints:death-only  (law-critical — death/moribundity as sole endpoint)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("endpoints_text,profile,should_fire,expected_severity", [
    # Death as only criterion — default: warning
    (["Animals will be euthanized at death or moribundity."], "default", True, "warning"),
    # Death as only criterion — strict_law: error
    (["Animals will be euthanized at death or moribundity."], "strict_law", True, "error"),
    # Death mentioned but clinical scoring also present — no fire
    (["Moribundity or clinical score ≥3 (righting reflex, posture, grooming)."], "default", False, None),
    # No endpoints text at all — no fire (different rule)
    ([], "default", False, None),
    # Weight-based endpoint only — no fire (covered by endpoints:20%-only, not death-only)
    (["Animals will be euthanized upon 20% weight loss."], "default", False, None),
])
def test_endpoints_death_only(endpoints_text, profile, should_fire, expected_severity):
    experiments = [copy.deepcopy(_BASE_INSTANCE["experiments"][0])]
    experiments[0]["humane_endpoints"] = {"general": endpoints_text, "specific": []}
    inst = _make(experiments=experiments)
    report = lint(inst, profile=profile)
    items = _failed_checks(report, "endpoints:death-only")
    if should_fire:
        assert items, f"Expected endpoints:death-only to fire (profile={profile!r})"
        assert items[0]["severity"] == expected_severity
    else:
        assert not items, f"Expected endpoints:death-only not to fire (text={endpoints_text!r})"


# ---------------------------------------------------------------------------
# Rule: postop:monitoring  (law-critical — survival surgery missing post-op plan)
# ---------------------------------------------------------------------------

SURVIVAL_FATE = "transferred to colony"
EUTHANIZED_FATE = "euthanized"
SURGERY_TIMELINE = [{"step": "craniotomy and electrode implantation"}]
NONSURGERY_TIMELINE = [{"step": "IP injection of compound X"}]

@pytest.mark.parametrize("fate,timeline,monitoring_plan,profile,should_fire,expected_severity", [
    # Survival + surgery + no post-op keywords → fires (default: warning)
    (SURVIVAL_FATE, SURGERY_TIMELINE, "Standard observation.", "default", True, "warning"),
    # Survival + surgery + no post-op keywords → fires (strict_law: error)
    (SURVIVAL_FATE, SURGERY_TIMELINE, "Standard observation.", "strict_law", True, "error"),
    # Survival + surgery + post-op plan described → no fire
    (SURVIVAL_FATE, SURGERY_TIMELINE, "Post-operative daily wound checks; buprenorphine 0.05 mg/kg q8h.", "default", False, None),
    # Euthanized fate → no fire (not a survival surgery)
    (EUTHANIZED_FATE, SURGERY_TIMELINE, "Standard observation.", "default", False, None),
    # Survival but no surgery keywords → no fire
    (SURVIVAL_FATE, NONSURGERY_TIMELINE, "Standard observation.", "default", False, None),
])
def test_postop_monitoring(fate, timeline, monitoring_plan, profile, should_fire, expected_severity):
    experiments = [copy.deepcopy(_BASE_INSTANCE["experiments"][0])]
    experiments[0]["fate"] = fate
    experiments[0]["procedure_timeline"] = timeline
    experiments[0]["monitoring"] = {"plan": monitoring_plan}
    inst = _make(experiments=experiments)
    report = lint(inst, profile=profile)
    items = _failed_checks(report, "postop:monitoring")
    if should_fire:
        assert items, f"Expected postop:monitoring to fire (fate={fate!r}, profile={profile!r})"
        assert items[0]["severity"] == expected_severity
    else:
        assert not items, f"Expected postop:monitoring not to fire"


# ---------------------------------------------------------------------------
# Rule: surgery:multiple-survival  (advisory — potential animal reuse)
# ---------------------------------------------------------------------------

def test_surgery_multiple_survival_fires():
    """Two survival experiments on same species should trigger advisory."""
    exp1 = copy.deepcopy(_BASE_INSTANCE["experiments"][0])
    exp2 = copy.deepcopy(_BASE_INSTANCE["experiments"][0])
    exp1["fate"] = "returned to colony"
    exp2["fate"] = "transferred to colony"
    exp1["label"] = "Exp 1"
    exp2["label"] = "Exp 2"
    inst = _make(experiments=[exp1, exp2])
    report = lint(inst, profile="default")
    items = _failed_checks(report, "surgery:multiple-survival")
    assert items, "Expected surgery:multiple-survival to fire for two survival experiments"
    assert items[0]["severity"] == "warning"


def test_surgery_multiple_survival_no_fire_euthanized():
    """Two euthanized experiments should NOT trigger surgery:multiple-survival."""
    exp1 = copy.deepcopy(_BASE_INSTANCE["experiments"][0])
    exp2 = copy.deepcopy(_BASE_INSTANCE["experiments"][0])
    exp1["fate"] = "euthanized"
    exp2["fate"] = "euthanized"
    inst = _make(experiments=[exp1, exp2])
    report = lint(inst, profile="default")
    items = _failed_checks(report, "surgery:multiple-survival")
    assert not items, "Expected surgery:multiple-survival NOT to fire when all experiments are euthanized"


# ---------------------------------------------------------------------------
# Rule: N:power-analysis  (advisory — non-trivial N without power analysis)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("n_total,method,details,request_type,should_fire", [
    # N=200, no power method, non-pilot → fires
    (200, "convenience", "Standard in the field.", "regular", True),
    # N=200, has power method → no fire
    (200, "power", "Power analysis α=0.05, 1-β=0.8.", "regular", False),
    # N=200, details mention "prior work" → no fire
    (200, "other", "Based on prior published results showing n=50/group.", "regular", False),
    # N=30, below threshold → no fire
    (30, "convenience", "Small pilot.", "regular", False),
    # N=200 but pilot track → no fire
    (200, "convenience", "Standard in the field.", "pilot", False),
])
def test_N_power_analysis(n_total, method, details, request_type, should_fire):
    animals_total = [{"species": "mouse", "strain": "C57BL/6", "sex": "both",
                      "genetic_status": "WT", "source": "vendor", "n_total": n_total}]
    n_just = {"method": method, "details": details, "attachments": []}
    research = dict(_BASE_INSTANCE["research"])
    research["request_type"] = request_type
    inst = _make(animals_total=animals_total, n_justification=n_just, research=research)
    report = lint(inst, profile="default")
    items = _failed_checks(report, "N:power-analysis")
    if should_fire:
        assert items, f"Expected N:power-analysis to fire (n={n_total}, method={method!r})"
        assert items[0]["severity"] == "warning"
    else:
        assert not items, f"Expected N:power-analysis not to fire (n={n_total}, method={method!r})"


# ---------------------------------------------------------------------------
# Rule: special:neonatal-CO2  (law-critical — CO₂ sole method for neonates)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("timeline_text,confirmation,profile,should_fire,expected_severity", [
    # Neonatal keyword + CO2 + no secondary → fires (default: warning)
    ("CO2 euthanasia of neonatal pups on postnatal day 1.", "", "default", True, "warning"),
    # Neonatal keyword + CO2 + no secondary → fires (strict_law: error)
    ("CO2 euthanasia of neonatal pups on postnatal day 1.", "", "strict_law", True, "error"),
    # Neonatal keyword + CO2 + secondary decapitation → no fire
    ("CO2 euthanasia of P0 pups.", "Secondary decapitation confirmed.", "default", False, None),
    # No neonatal keywords → no fire (adult CO2 handled by euthanasia:CO2)
    ("CO2 euthanasia of adult mice.", "", "default", False, None),
    # "day 14" / "day 21" must NOT trigger neonatal (word-boundary regression)
    ("experiment will end on day 14 or 21. body weight monitored.", "", "default", False, None),
    # "day 1" as standalone word SHOULD still trigger
    ("on day 1 pups are euthanized via CO2.", "", "default", True, "warning"),
])
def test_special_neonatal_CO2(timeline_text, confirmation, profile, should_fire, expected_severity):
    experiments = [copy.deepcopy(_BASE_INSTANCE["experiments"][0])]
    experiments[0]["euthanasia"] = {"primary": "CO2", "parameters": "", "confirmation": confirmation}
    experiments[0]["procedure_timeline"] = [{"step": timeline_text}]
    inst = _make(experiments=experiments)
    report = lint(inst, profile=profile)
    items = _failed_checks(report, "special:neonatal-CO2")
    if should_fire:
        assert items, f"Expected special:neonatal-CO2 to fire (profile={profile!r})"
        assert items[0]["severity"] == expected_severity
    else:
        assert not items, f"Expected special:neonatal-CO2 not to fire"


# ---------------------------------------------------------------------------
# Rule: vet:consultation  (advisory — severity 4-5 needs documented vet consultation)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("severity,monitoring_plan,should_fire", [
    # Severity 4 + no vet keywords → fires
    (4, "Daily observation.", True),
    # Severity 5 + no vet keywords → fires
    (5, "Monitoring protocol in place.", True),
    # Severity 4 + vet mentioned → no fire
    (4, "Veterinary consultation on analgesia plan required.", False),
    # Severity 4 + DVM mentioned → no fire
    (4, "DVM will review anesthetic protocol bi-weekly.", False),
    # Severity 3 (below threshold) → no fire
    (3, "Daily observation.", False),
])
def test_vet_consultation(severity, monitoring_plan, should_fire):
    experiments = [copy.deepcopy(_BASE_INSTANCE["experiments"][0])]
    experiments[0]["severity_level_1_to_5"] = severity
    experiments[0]["monitoring"] = {"plan": monitoring_plan}
    inst = _make(experiments=experiments)
    report = lint(inst, profile="default")
    items = _failed_checks(report, "vet:consultation")
    if should_fire:
        assert items, f"Expected vet:consultation to fire (sev={severity})"
        assert items[0]["severity"] == "warning"
    else:
        assert not items, f"Expected vet:consultation not to fire (sev={severity})"


# ---------------------------------------------------------------------------
# Rule: deprivation:protocol  (advisory — food/water deprivation needs weight monitoring)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("timeline_steps,monitoring_plan,should_fire", [
    # Fasting + no weight monitoring → fires
    (["Fasting for 12h prior to procedure."], "Standard daily observation.", True),
    # Food deprivation + no weight criterion → fires
    (["Food deprivation for 24h."], "Monitor appearance.", True),
    # Water restrict + weight loss mentioned → no fire
    (["Water restriction protocol."], "Body weight checked daily; >15% loss triggers intervention.", False),
    # Fasting + body weight monitoring → no fire
    (["Fasted overnight."], "Monitor body weight every 2 days; intervention endpoint at 15% weight loss.", False),
    # No deprivation → no fire
    (["IP injection of compound X."], "Daily observation.", False),
])
def test_deprivation_protocol(timeline_steps, monitoring_plan, should_fire):
    experiments = [copy.deepcopy(_BASE_INSTANCE["experiments"][0])]
    experiments[0]["procedure_timeline"] = [{"step": s} for s in timeline_steps]
    experiments[0]["monitoring"] = {"plan": monitoring_plan}
    inst = _make(experiments=experiments)
    report = lint(inst, profile="default")
    items = _failed_checks(report, "deprivation:protocol")
    if should_fire:
        assert items, f"Expected deprivation:protocol to fire"
        assert items[0]["severity"] == "warning"
    else:
        assert not items, f"Expected deprivation:protocol not to fire"


# ---------------------------------------------------------------------------
# Rule: gma:ibc  (advisory — GM animals may need IBC approval)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("genetic_status,should_fire", [
    ("transgenic", True),
    ("knockout", True),
    ("KO", True),
    ("CRISPR", True),
    ("knock-in", True),
    ("WT", False),
    ("wild-type", False),
    ("outbred", False),
])
def test_gma_ibc(genetic_status, should_fire):
    experiments = [copy.deepcopy(_BASE_INSTANCE["experiments"][0])]
    experiments[0]["animals"]["genetic_status"] = genetic_status
    inst = _make(experiments=experiments)
    report = lint(inst, profile="default")
    items = _failed_checks(report, "gma:ibc")
    if should_fire:
        assert items, f"Expected gma:ibc to fire for genetic_status={genetic_status!r}"
        assert items[0]["severity"] == "warning"
    else:
        assert not items, f"Expected gma:ibc not to fire for genetic_status={genetic_status!r}"


# ---------------------------------------------------------------------------
# Rule: ascites:in-vitro  (advisory — ascites method needs in vitro alternatives justification)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("timeline_steps,should_fire", [
    # Ascites mentioned → fires
    (["Inject hybridoma cells for ascites production."], True),
    (["Ascites fluid collection on day 14."], True),
    # No ascites → no fire
    (["IP injection of antibody."], False),
    (["Blood draw for serum collection."], False),
])
def test_ascites_in_vitro(timeline_steps, should_fire):
    experiments = [copy.deepcopy(_BASE_INSTANCE["experiments"][0])]
    experiments[0]["procedure_timeline"] = [{"step": s} for s in timeline_steps]
    inst = _make(experiments=experiments)
    report = lint(inst, profile="default")
    items = _failed_checks(report, "ascites:in-vitro")
    if should_fire:
        assert items, f"Expected ascites:in-vitro to fire"
        assert items[0]["severity"] == "warning"
    else:
        assert not items, f"Expected ascites:in-vitro not to fire"


# ---------------------------------------------------------------------------
# Rule: colony:breeding-plan  (advisory — colony protocols need management plan)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("is_colony,n_just_details,should_fire", [
    # Colony + no colony management language → fires
    (True, "Power analysis at α=0.05 requires n=10 per group.", True),
    # Colony + mentions colony management → no fire
    (True, "Colony management plan: expected surplus of 20 mice per month, disposition by transfer to other labs.", False),
    # Colony + mentions breeding → no fire
    (True, "Breeding pairs produce approximately 8 pups per litter.", False),
    # Not a colony → no fire regardless of details
    (False, "Power analysis at α=0.05 requires n=10 per group.", False),
])
def test_colony_breeding_plan(is_colony, n_just_details, should_fire):
    n_just = {"method": "power", "details": n_just_details, "attachments": []}
    inst = _make(is_colony=is_colony, n_justification=n_just)
    report = lint(inst, profile="default")
    items = _failed_checks(report, "colony:breeding-plan")
    if should_fire:
        assert items, f"Expected colony:breeding-plan to fire (is_colony={is_colony})"
        assert items[0]["severity"] == "warning"
    else:
        assert not items, f"Expected colony:breeding-plan not to fire (is_colony={is_colony})"


# ---------------------------------------------------------------------------
# Cross-profile invariant: strict_law is a superset of default errors
# ---------------------------------------------------------------------------

def test_strict_law_catches_at_least_everything_default_catches():
    """strict_law error count must be >= default error count for any instance."""
    # Use an instance with known issues: empty alternatives + animals mismatch
    alts = {"engines": [], "queries": [], "conclusion": ""}
    animals_total = [{"species": "mouse", "strain": "C57BL/6", "sex": "both",
                      "genetic_status": "WT", "source": "vendor", "n_total": 99}]
    experiments = [copy.deepcopy(_BASE_INSTANCE["experiments"][0])]
    experiments[0]["animals"]["n"] = 20  # mismatch
    inst = _make(alternatives_search=alts, animals_total=animals_total, experiments=experiments)

    rep_default = lint(inst, profile="default")
    rep_strict = lint(inst, profile="strict_law")

    assert rep_strict["errors"] >= rep_default["errors"], (
        f"strict_law errors ({rep_strict['errors']}) < default errors ({rep_default['errors']})"
    )


# ===========================================================================
# AVMA Species-Euthanasia Matrix Rules (P1 epic)
# ===========================================================================

def _make_exp_with_species(species, primary, params="", confirmation="",
                            weight=None, age=None, timeline=None):
    """Helper: create a single experiment with specific species/euthanasia."""
    exp = copy.deepcopy(_BASE_INSTANCE["experiments"][0])
    exp["animals"]["species"] = species
    exp["euthanasia"] = {
        "primary": primary,
        "parameters": params,
        "confirmation": confirmation,
    }
    if weight is not None:
        exp["animals"]["weight"] = {"value": weight, "unit": "g"}
    if age is not None:
        exp["animals"]["age"] = age
    if timeline is not None:
        exp["procedure_timeline"] = timeline
    return exp


# ---------------------------------------------------------------------------
# Rule: euthanasia:species-method  (error in BOTH profiles)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("species,primary,should_fire", [
    # Acceptable for species → no fire
    ("mouse", "CO2", False),
    ("mouse", "barbiturate", False),
    ("rat", "CO2", False),
    ("rabbit", "barbiturate", False),
    ("zebrafish", "MS-222", False),
    # Conditionally acceptable → no fire (separate rule checks conditions)
    ("mouse", "cervical dislocation", False),
    ("rat", "cervical dislocation", False),
    # Unacceptable → FIRE
    ("zebrafish", "CO2", True),
    ("guinea_pig", "cervical dislocation", True),
    ("pig", "cervical dislocation", True),
    ("pig", "decapitation", True),
    # Unknown species → no fire (skip)
    ("dog", "CO2", False),
    # Unknown method → no fire (skip)
    ("mouse", "unknown method xyz", False),
])
def test_euthanasia_species_method(species, primary, should_fire):
    exp = _make_exp_with_species(species, primary)
    inst = _make(experiments=[exp])
    report = lint(inst, profile="default")
    items = _failed_checks(report, "euthanasia:species-method")
    if should_fire:
        assert items, f"Expected euthanasia:species-method to fire for {species}/{primary}"
        assert items[0]["severity"] == "error"  # Error in BOTH profiles
    else:
        assert not items, f"Expected euthanasia:species-method NOT to fire for {species}/{primary}"


def test_euthanasia_species_method_error_in_both_profiles():
    """Verify that species-method is error in both default and strict_law."""
    exp = _make_exp_with_species("zebrafish", "CO2")
    inst = _make(experiments=[exp])
    for profile in ("default", "strict_law"):
        report = lint(inst, profile=profile)
        items = _failed_checks(report, "euthanasia:species-method")
        assert items, f"Should fire in {profile}"
        assert items[0]["severity"] == "error", f"Should be error in {profile}"


# ---------------------------------------------------------------------------
# Rule: euthanasia:precharged-chamber  (error in BOTH profiles)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("params,should_fire", [
    ("pre-charged CO2 chamber", True),
    ("precharged chamber method", True),
    ("pre charged co2", True),
    ("prefilled chamber", True),
    ("Gradual fill 30-70% of chamber volume per minute", False),
    ("CO2 displacement method", False),
    ("", False),
])
def test_euthanasia_precharged_chamber(params, should_fire):
    exp = _make_exp_with_species("mouse", "CO2", params=params)
    inst = _make(experiments=[exp])
    report = lint(inst, profile="default")
    items = _failed_checks(report, "euthanasia:precharged-chamber")
    if should_fire:
        assert items, f"Expected precharged-chamber to fire for params={params!r}"
        assert items[0]["severity"] == "error"
    else:
        assert not items, f"Expected precharged-chamber NOT to fire for params={params!r}"


def test_euthanasia_precharged_in_timeline():
    """Pre-charged keyword in procedure timeline should also fire."""
    exp = _make_exp_with_species("mouse", "CO2")
    exp["procedure_timeline"] = [{"step": "Euthanize using pre-charged CO2 chamber"}]
    inst = _make(experiments=[exp])
    report = lint(inst, profile="default")
    items = _failed_checks(report, "euthanasia:precharged-chamber")
    assert items, "Should detect pre-charged in timeline"


# ---------------------------------------------------------------------------
# Rule: euthanasia:displacement-rate  (warning default, error strict_law)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("species,params,profile,should_fire,expected_severity", [
    # No rate specified → fires
    ("mouse", "", "default", True, "warning"),
    ("mouse", "", "strict_law", True, "error"),
    # Rate present → no fire
    ("mouse", "Gradual fill 30-70% of chamber volume per minute", "default", False, None),
    ("mouse", "50% displacement rate", "default", False, None),
    ("mouse", "displacement 40% vol/min", "default", False, None),
    # Rabbit-specific rate
    ("rabbit", "", "strict_law", True, "error"),
    ("rabbit", "50-60% chamber displacement", "default", False, None),
    # Non-CO2 method → no fire (rule only applies to CO2)
    ("mouse", "", "default", False, None),  # This case needs method != CO2
])
def test_euthanasia_displacement_rate(species, params, profile, should_fire, expected_severity):
    # Last case: non-CO2 method
    if species == "mouse" and params == "" and profile == "default" and not should_fire:
        exp = _make_exp_with_species(species, "barbiturate", params=params)
    else:
        exp = _make_exp_with_species(species, "CO2", params=params,
                                      confirmation="cervical_dislocation")
    inst = _make(experiments=[exp])
    report = lint(inst, profile=profile)
    items = _failed_checks(report, "euthanasia:displacement-rate")
    if should_fire:
        assert items, f"Expected displacement-rate to fire for {species}/{params!r}/{profile}"
        assert items[0]["severity"] == expected_severity
    else:
        assert not items, f"Expected displacement-rate NOT to fire"


# ---------------------------------------------------------------------------
# Rule: euthanasia:secondary-method  (warning default, error strict_law)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("primary,confirmation,params,profile,should_fire,expected_severity", [
    # Physical secondary present → no fire
    ("CO2", "cervical_dislocation", "", "default", False, None),
    ("CO2", "thoracotomy", "", "default", False, None),
    ("CO2", "", "secondary cervical dislocation", "default", False, None),
    ("inhalant_overdose", "exsanguination", "", "default", False, None),
    # No physical secondary → fires
    ("CO2", "", "", "default", True, "warning"),
    ("CO2", "", "", "strict_law", True, "error"),
    ("CO2", "other", "", "default", True, "warning"),
    ("inhalant_overdose", "", "", "default", True, "warning"),
    # Non-CO2/inhalant method → no fire
    ("barbiturate", "", "", "default", False, None),
    ("cervical dislocation", "", "", "default", False, None),
])
def test_euthanasia_secondary_method(primary, confirmation, params, profile,
                                      should_fire, expected_severity):
    exp = _make_exp_with_species("mouse", primary, params=params, confirmation=confirmation)
    inst = _make(experiments=[exp])
    report = lint(inst, profile=profile)
    items = _failed_checks(report, "euthanasia:secondary-method")
    if should_fire:
        assert items, f"Expected secondary-method to fire for {primary}/{confirmation!r}/{profile}"
        assert items[0]["severity"] == expected_severity
    else:
        assert not items, f"Expected secondary-method NOT to fire"


# ---------------------------------------------------------------------------
# Rule: euthanasia:cervical-weight  (warning default, error strict_law)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("species,weight_g,profile,should_fire,expected_severity", [
    # Rat under 200g → no fire
    ("rat", 150, "default", False, None),
    ("rat", 200, "default", False, None),
    # Rat over 200g → fires
    ("rat", 250, "default", True, "warning"),
    ("rat", 250, "strict_law", True, "error"),
    # Rat with no weight → fires (weight required)
    ("rat", None, "default", True, "warning"),
    ("rat", None, "strict_law", True, "error"),
    # Mouse (no weight limit) → no fire even without weight
    ("mouse", None, "default", False, None),
    ("mouse", 30, "default", False, None),
    # Rabbit with cervical dislocation (max 1000g)
    ("rabbit", 800, "default", False, None),
    ("rabbit", 1200, "default", True, "warning"),
])
def test_euthanasia_cervical_weight(species, weight_g, profile, should_fire, expected_severity):
    exp = _make_exp_with_species(species, "cervical dislocation", weight=weight_g)
    inst = _make(experiments=[exp])
    report = lint(inst, profile=profile)
    items = _failed_checks(report, "euthanasia:cervical-weight")
    if should_fire:
        assert items, (
            f"Expected cervical-weight to fire for {species}/weight={weight_g}/{profile}"
        )
        assert items[0]["severity"] == expected_severity
    else:
        assert not items, (
            f"Expected cervical-weight NOT to fire for {species}/weight={weight_g}/{profile}"
        )


# ---------------------------------------------------------------------------
# Rule: euthanasia:conditions-missing  (warning default, error strict_law)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("species,primary,params,profile,should_fire", [
    # Cervical dislocation with training documented → no fire
    ("mouse", "cervical dislocation", "trained personnel under anesthesia", "default", False),
    # Cervical dislocation with no documentation → fires
    ("mouse", "cervical dislocation", "", "default", True),
    # Decapitation with justification → no fire
    ("mouse", "decapitation", "scientifically justified, trained operator", "default", False),
    # Decapitation with no docs → fires
    ("mouse", "decapitation", "", "default", True),
])
def test_euthanasia_conditions_missing(species, primary, params, profile, should_fire):
    exp = _make_exp_with_species(species, primary, params=params)
    inst = _make(experiments=[exp])
    report = lint(inst, profile=profile)
    items = _failed_checks(report, "euthanasia:conditions-missing")
    if should_fire:
        assert items, f"Expected conditions-missing to fire for {species}/{primary}/{params!r}"
    else:
        assert not items, f"Expected conditions-missing NOT to fire"


# ---------------------------------------------------------------------------
# AVMA rules: exp_signals enrichment
# ---------------------------------------------------------------------------

def test_exp_signals_include_avma_fields():
    """Verify exp_signals contain species_normalized and avma_status."""
    exp = _make_exp_with_species("mouse", "CO2")
    inst = _make(experiments=[exp])
    report = lint(inst)
    signals = report.get("analysis", {}).get("experiments", [])
    assert len(signals) >= 1
    assert signals[0].get("species_normalized") == "mouse"
    assert signals[0].get("avma_status") == "conditionally_acceptable"


def test_exp_signals_avma_status_unacceptable():
    """Verify avma_status shows unacceptable for zebrafish+CO2."""
    exp = _make_exp_with_species("zebrafish", "CO2")
    inst = _make(experiments=[exp])
    report = lint(inst)
    signals = report.get("analysis", {}).get("experiments", [])
    assert signals[0].get("avma_status") == "unacceptable"


def test_exp_signals_avma_status_none_for_unknown():
    """Verify avma_status is None for unknown species."""
    exp = _make_exp_with_species("dog", "CO2")
    inst = _make(experiments=[exp])
    report = lint(inst)
    signals = report.get("analysis", {}).get("experiments", [])
    assert signals[0].get("avma_status") is None


# ---------------------------------------------------------------------------
# Regression: existing euthanasia rules still work alongside new AVMA rules
# ---------------------------------------------------------------------------

def test_existing_co2_rule_still_fires():
    """Existing euthanasia:CO2 rule should still fire alongside new AVMA rules."""
    exp = _make_exp_with_species("mouse", "CO2", confirmation="")
    inst = _make(experiments=[exp])
    report = lint(inst, profile="strict_law")
    co2_items = _failed_checks(report, "euthanasia:CO2")
    assert co2_items, "Existing euthanasia:CO2 rule should still fire"


def test_existing_neonatal_rule_still_fires():
    """Existing special:neonatal-CO2 rule should still fire alongside new AVMA rules."""
    exp = _make_exp_with_species("mouse", "CO2", confirmation="")
    exp["procedure_timeline"] = [{"step": "Euthanize neonatal pups at P2 using CO2"}]
    inst = _make(experiments=[exp])
    report = lint(inst, profile="strict_law")
    neo_items = _failed_checks(report, "special:neonatal-CO2")
    assert neo_items, "Existing neonatal-CO2 rule should still fire"


# ---------------------------------------------------------------------------
# Rule: housing:density  (advisory)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("weight_g,floor_area,animals_per_enclosure,group_housed,single_reason,should_fire", [
    (30, 150.0, 2, True, "", True),
    (30, 193.6, 2, True, "", False),
    (30, None, None, False, "", True),
    (30, None, None, False, "Required for post-surgical separation.", False),
    # Weight unknown → conservative 77.4 cm2 fallback for mouse
    (None, 60.0, 1, True, "", True),
    (None, 80.0, 1, True, "", False),
])
def test_housing_density(weight_g, floor_area, animals_per_enclosure, group_housed, single_reason, should_fire):
    exp = copy.deepcopy(_BASE_INSTANCE["experiments"][0])
    exp["animals"]["species"] = "mouse"
    exp["animals"]["species_standard"] = "mouse"
    if weight_g is not None:
        exp["animals"]["weight"] = {"value": weight_g, "unit": "g"}
    exp["housing"] = {
        "group_housed": group_housed,
        "enrichment": "standard",
        "single_housing_reason": single_reason,
    }
    if floor_area is not None:
        exp["housing_density"] = {
            "cage_floor_area_cm2": floor_area,
            "animals_per_enclosure": animals_per_enclosure,
            "breeding_with_litter": False,
        }
    inst = _make(experiments=[exp])
    report = lint(inst, profile="default")
    items = _failed_checks(report, "housing:density")
    if should_fire:
        assert items, "Expected housing:density to fire"
        assert items[0]["severity"] == "warning"
    else:
        assert not items, f"Expected housing:density not to fire, got {items}"


# ---------------------------------------------------------------------------
# Rule: restraint:duration  (advisory)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "restraint,should_fire",
    [
        (
            {
                "used": True,
                "method": "tube restraint",
                "acclimation": "Handled for two days first.",
                "monitoring": "Observed continuously.",
                "humane_removal_criteria": "Stop if persistent struggling occurs.",
            },
            True,
        ),
        (
            {
                "used": True,
                "method": "tube restraint",
                "max_duration_minutes": 20,
                "acclimation": "Handled for two days first.",
                "monitoring": "Observed continuously.",
                "humane_removal_criteria": "Stop if persistent struggling occurs.",
            },
            True,
        ),
        (
            {
                "used": True,
                "method": "jacket restraint",
                "max_duration_minutes": 400,
                "acclimation": "Gradual acclimation over three days.",
                "monitoring": "Observed continuously.",
                "humane_removal_criteria": "Remove for dyspnea or escape attempts.",
                "justification": "Needed for continuous telemetry calibration.",
            },
            True,
        ),
        (
            {
                "used": True,
                "method": "tube restraint",
                "max_duration_minutes": 10,
                "acclimation": "Handled for two days first.",
                "monitoring": "Observed continuously.",
                "humane_removal_criteria": "Stop if persistent struggling occurs.",
                "justification": "Required for imaging alignment.",
                "food_water_plan": "",
            },
            False,
        ),
    ],
)
def test_restraint_duration(restraint, should_fire):
    exp = copy.deepcopy(_BASE_INSTANCE["experiments"][0])
    exp["restraint"] = restraint
    exp["procedure_timeline"] = [{"step": "Animals undergo restraint before imaging."}]
    inst = _make(experiments=[exp])
    report = lint(inst, profile="default")
    items = _failed_checks(report, "restraint:duration")
    if should_fire:
        assert items, "Expected restraint:duration to fire"
        assert items[0]["severity"] == "warning"
    else:
        assert not items, f"Expected restraint:duration not to fire, got {items}"


# ---------------------------------------------------------------------------
# Rule: reuse:justification  (law-critical)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("reuse_review,profile,should_fire,expected_severity", [
    (
        {
            "prior_severity": "severe",
            "fully_recovered": False,
            "new_procedure_severity": "severe",
            "vet_consulted": False,
        },
        "default",
        True,
        "warning",
    ),
    (
        {
            "prior_severity": "mild",
            "fully_recovered": True,
            "new_procedure_severity": "moderate",
            "vet_consulted": True,
        },
        "default",
        False,
        None,
    ),
    (
        {
            "prior_severity": "mild",
            "fully_recovered": False,
            "new_procedure_severity": "moderate",
            "vet_consulted": True,
        },
        "strict_law",
        True,
        "error",
    ),
])
def test_reuse_justification(reuse_review, profile, should_fire, expected_severity):
    exp = copy.deepcopy(_BASE_INSTANCE["experiments"][0])
    exp["reuse_or_prior_procedures"] = {"has_prior": True, "prior_protocol_ids": ["P-1"]}
    exp["reuse_review"] = reuse_review
    inst = _make(experiments=[exp])
    report = lint(inst, profile=profile)
    items = _failed_checks(report, "reuse:justification")
    if should_fire:
        assert items, "Expected reuse:justification to fire"
        assert items[0]["severity"] == expected_severity
    else:
        assert not items, f"Expected reuse:justification not to fire, got {items}"


# ---------------------------------------------------------------------------
# Rule: permits:field-study  (law-critical)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("permits,profile,should_fire,expected_severity", [
    (
        {
            "field_study": True,
            "wildlife": True,
            "collection_permit_ids": "",
            "protected_species": False,
            "wildlife_pathogen_handling": False,
            "field_euthanasia_method": "",
        },
        "default",
        True,
        "warning",
    ),
    (
        {
            "field_study": True,
            "wildlife": True,
            "collection_permit_ids": "COL-12",
            "protected_species": True,
            "cites_documentation": "",
            "wildlife_pathogen_handling": True,
            "biosafety_approval_id": "",
            "field_euthanasia_method": "Isoflurane overdose",
        },
        "strict_law",
        True,
        "error",
    ),
    (
        {
            "field_study": True,
            "wildlife": True,
            "collection_permit_ids": "COL-12",
            "protected_species": True,
            "cites_documentation": "CITES-55",
            "wildlife_pathogen_handling": True,
            "biosafety_approval_id": "IBC-90",
            "field_euthanasia_method": "Isoflurane overdose",
        },
        "default",
        False,
        None,
    ),
])
def test_field_study_permits(permits, profile, should_fire, expected_severity):
    exp = copy.deepcopy(_BASE_INSTANCE["experiments"][0])
    exp["field_study_permits"] = permits
    exp["procedure_timeline"] = [{"step": "Capture wild birds in a field study and collect swabs."}]
    inst = _make(experiments=[exp])
    report = lint(inst, profile=profile)
    items = _failed_checks(report, "permits:field-study")
    if should_fire:
        assert items, "Expected permits:field-study to fire"
        assert items[0]["severity"] == expected_severity
    else:
        assert not items, f"Expected permits:field-study not to fire, got {items}"
