import json
import logging
import os
import re
from pathlib import Path
from typing import Any, Dict, Generator, List, Optional

from .llm_clients import LLMError, call_llm, call_llm_stream, call_llm_two_step, context_budget_warning
from .schema import IACUC_SCHEMA_V2
from .xmeta_catalog import load_high_leverage_catalog

PROMPTS_DIR = Path(__file__).parent.parent / "llm"
LAW_PATH = Path(__file__).parent.parent / "resources" / "law" / "the_law-english_translation.txt"
HEAD_TO_HEAD_DIR = Path(__file__).parent.parent / "examples" / "head-to-head"

logger = logging.getLogger(__name__)


def law_loaded() -> bool:
    """True when the law text is present and non-empty (surfaced in /api/health)."""
    try:
        return LAW_PATH.stat().st_size > 0
    except OSError:
        return False

GRADE_LABELS = {
    0: "not_addressed",
    1: "inadequate",
    2: "partially_adequate",
    3: "adequate",
}
VALID_GRADE_LABELS = set(GRADE_LABELS.values())

# Theme specifications for small, focused prompts.
THEME_SPECS: Dict[str, Dict[str, Any]] = {
    "three_Rs_alternatives": {
        "label": "3Rs / Alternatives Search",
        "ref_prefixes": ["alts:"],
        "analysis_keys": ["alternatives"],
        "sub_questions": [
            "Is a non-duplication assurance present?",
            "Does the narrative address Replacement, Reduction, AND Refinement separately?",
            "Are at least 2 named databases listed in the alternatives search?",
            "Is a search date present and recent (within the last 3 years)?",
            "Are specific search queries or terms listed?",
            "Is the conclusion substantive and specific to why no validated alternative fits this model?",
        ],
        "rubric_examples": {
            3: "Two databases, dated queries, separate discussion of replacement/reduction/refinement, and a model-specific conclusion are all present.",
            2: "The protocol cites one database and a search date, but covers the 3Rs unevenly or gives only a partly specific conclusion.",
            1: "Alternatives are mentioned in general terms, but key evidence such as databases, queries, or distinct 3R discussion is missing.",
            0: "No alternatives-search narrative or non-duplication assurance is provided.",
        },
    },
    "N_and_justification": {
        "label": "Animal numbers and justification",
        "ref_prefixes": ["animals:", "N:"],
        "analysis_keys": ["summary"],
        "sub_questions": [
            "Is a formal power analysis (alpha, power, effect size) or a reference to published precedent cited?",
            "Is the stated N consistent with the statistical analysis plan described?",
            "Is the attrition reserve reasonable (typically 10 to 20%) and justified?",
            "Are all animals accounted for, including breeding colony, genotyping, donors, and anticipated losses?",
        ],
        "rubric_examples": {
            3: "The protocol reconciles total animal counts with experiments, includes attrition logic, and accounts for breeders, genotyping, and losses.",
            2: "The main experimental N is justified, but reserve animals or supporting animals are only partially accounted for.",
            1: "The protocol gives a vague animal-count justification and does not fully reconcile totals across supporting cohorts.",
            0: "No usable numerical justification or accounting of total animals is provided.",
        },
    },
    "severity_monitoring_analgesia": {
        "label": "Severity, monitoring, analgesia",
        "ref_prefixes": ["severity:", "postop:", "surgery:"],
        "analysis_keys": ["summary", "experiments"],
        "sub_questions": [
            "Does the assigned severity level match the procedures described?",
            "Is the USDA pain category (B/C/D/E) assigned and consistent with described procedures?",
            "Is monitoring frequency adequate for the severity level (for example daily for severity >=4)?",
            "Is an analgesic agent specified for each invasive or painful procedure?",
            "Are doses, routes, and frequency provided for each analgesic or anesthetic?",
            "For Category E procedures, is there written scientific justification for withholding pain relief?",
        ],
        "rubric_examples": {
            3: "Severity, USDA pain category, monitoring, and analgesia details all match the procedures, with Category E justified where relevant.",
            2: "Severity and analgesia are mostly coherent, but one supporting element such as pain category or dosing detail is incomplete.",
            1: "Painful procedures are described, but monitoring or analgesia detail is inadequate or inconsistent with the claimed severity.",
            0: "Severity, pain category, and analgesia planning are effectively absent.",
        },
    },
    "euthanasia_and_endpoints": {
        "label": "Euthanasia and humane endpoints",
        "ref_prefixes": ["euthanasia:", "endpoints:", "postop:"],
        "analysis_keys": ["experiments"],
        "sub_questions": [
            "Is the euthanasia method AVMA-compliant for the species described?",
            "Is the euthanasia method listed as Acceptable, not merely Conditionally Acceptable, for this species when the protocol implies routine use?",
            "For carbon dioxide or injectable overdose, is a death-confirmation step specified?",
            "If carbon dioxide is used, is the displacement rate within the species-specific range and is a physical secondary method specified?",
            "Are humane endpoints model-specific rather than generic only?",
            "Are multiple endpoint criteria provided so animals are not euthanized only at death or moribundity?",
            "Is a body condition score specified for tumor or wasting disease models?",
        ],
        "rubric_examples": {
            3: "The protocol uses a species-appropriate AVMA method, documents confirmation, and gives multiple model-specific humane endpoints with body-condition scoring where relevant.",
            2: "The euthanasia method is mostly acceptable and endpoints are present, but one condition such as confirmation detail or body-condition scoring is incomplete.",
            1: "Endpoints are generic or euthanasia conditions are under-specified for the species and model.",
            0: "The protocol does not meaningfully address euthanasia compliance or humane endpoints.",
        },
    },
    "harm_benefit_analysis": {
        "label": "Harm-benefit analysis",
        "ref_prefixes": ["severity:", "N:", "alts:"],
        "analysis_keys": ["summary", "experiments", "alternatives"],
        "sub_questions": [
            "Are the scientific or medical benefits of the research clearly stated?",
            "Are the harms to animals (pain, distress, death) clearly identified and proportionate to the stated benefit?",
            "Have the 3Rs been applied to minimize harm?",
            "Are harm factors identified using the Five Freedoms framework?",
            "Is severity classification assigned using the non-recovery / mild / moderate / severe framework?",
            "Does the protocol involve severe, long-lasting suffering that cannot be ameliorated, contrary to EU Directive Article 15(2)?",
        ],
        "rubric_examples": {
            3: "Benefits, harms, 3Rs, Five Freedoms, and severity classification are all discussed with no sign of prohibited severe unameliorated suffering.",
            2: "Benefits and harms are described, but the protocol omits one structured framework such as Five Freedoms or explicit severity classification.",
            1: "The protocol asserts benefit in broad terms but does not seriously weigh animal harms or possible severe unameliorated suffering.",
            0: "There is no meaningful harm-benefit analysis.",
        },
    },
    "sex_and_reuse": {
        "label": "Sex choice and reuse",
        "ref_prefixes": ["sex:", "colony", "reuse:"],
        "analysis_keys": ["summary"],
        "sub_questions": [
            "If only one sex is used, is the single-sex design scientifically justified rather than based on convenience?",
            "If animals are reused across experiments, has cumulative suffering been considered and documented?",
        ],
        "rubric_examples": {
            3: "The protocol clearly justifies any single-sex design and documents reuse decisions with cumulative-suffering reasoning.",
            2: "Sex choice is justified, but reuse implications or cumulative-suffering discussion is only partial.",
            1: "Single-sex or reuse decisions are present but weakly justified.",
            0: "No explanation is provided for sex restriction or reuse when those choices appear in the protocol.",
        },
    },
    "housing_and_husbandry": {
        "label": "Housing and husbandry",
        "ref_prefixes": ["housing:", "restraint:", "permits:field-study"],
        "analysis_keys": ["experiments"],
        "sub_questions": [
            "Are housing conditions specified (group versus single housing, cage type, enrichment)?",
            "Is social housing appropriate for the species and experimental model?",
            "Are special husbandry requirements justified for the experimental design?",
            "For food restriction, is a monitoring plan with weight-loss thresholds specified (15% enhanced monitoring, 20% humane endpoint)?",
        ],
        "rubric_examples": {
            3: "Housing, enrichment, social structure, and any food-restriction monitoring thresholds are clearly specified and justified.",
            2: "Routine husbandry is described, but one specialized need such as food-restriction thresholds or enrichment rationale is only partly covered.",
            1: "Housing is mentioned only generally and monitoring or restriction thresholds are weak or missing.",
            0: "Housing and husbandry are not meaningfully described.",
        },
    },
    "scientific_coherence": {
        "label": "Scientific coherence",
        "ref_prefixes": ["N:", "animals:"],
        "analysis_keys": ["summary", "experiments"],
        "sub_questions": [
            "Are group labels consistent between the scientific summary and the experiments table?",
            "Does the total N in animals_total match or reconcile with the sum across experiments?",
            "Are the procedures in the procedure timeline consistent with the stated research question?",
            "Is the species or strain choice justified for the experimental model described?",
        ],
        "rubric_examples": {
            3: "The scientific narrative, procedures, species choice, and animal totals are internally consistent throughout the protocol.",
            2: "The core study design is coherent, but one reconciliation issue such as group labeling or totals remains slightly unclear.",
            1: "Important elements such as totals, groups, or procedures do not align cleanly with the stated aims.",
            0: "The protocol lacks enough coherent information to judge scientific consistency.",
        },
    },
    "personnel_and_training": {
        "label": "Personnel and training",
        "ref_prefixes": ["pi:", "participant:"],
        "analysis_keys": ["summary"],
        "sub_questions": [
            "Do all listed personnel have training records for the procedures described?",
            "Is species-specific training documented for the animal types used?",
            "Are specialty procedures performed without matching specialist credentials?",
        ],
        "rubric_examples": {
            3: "All personnel are trained for the species and procedures, and specialist work matches documented credentials.",
            2: "Training is generally documented, but one role or species-specific qualification is only partially evidenced.",
            1: "Personnel are named, but training or specialist credential coverage is incomplete.",
            0: "Training documentation is effectively absent for the personnel performing the work.",
        },
    },
    "surgical_standards": {
        "label": "Surgical standards and post-operative care",
        "ref_prefixes": ["postop:", "surgery:"],
        "analysis_keys": ["experiments"],
        "sub_questions": [
            "Is aseptic technique described for survival surgery?",
            "Is the distinction between major and minor surgery clearly made?",
            "For multiple survival surgeries, is there written scientific justification that is not based solely on cost savings or animal-number reduction?",
            "Is a post-operative care plan specified with monitoring frequency, analgesic protocol, criteria for veterinary intervention, weekend or holiday monitoring, and thermal support during recovery?",
        ],
        "rubric_examples": {
            3: "The protocol describes aseptic survival surgery, classifies the surgery type, justifies any repeated survival surgery properly, and details post-op care.",
            2: "Surgical care is mostly described, but one element such as surgery classification or weekend monitoring is only partly addressed.",
            1: "Surgery is described but essential aseptic or post-op standards are incomplete.",
            0: "The protocol does not meaningfully describe surgical standards or post-operative care.",
        },
    },
    "hazardous_agents": {
        "label": "Hazardous agents and personnel safety",
        "ref_prefixes": ["special:biosafety", "gma:ibc", "hazard:ehs", "hazard:radiation"],
        "analysis_keys": ["summary", "experiments"],
        "sub_questions": [
            "Are hazardous agents (biological, chemical, radiological) identified in the protocol?",
            "Is Environmental Health & Safety (EH&S) consultation documented?",
            "Is Institutional Biosafety Committee (IBC) approval documented for biological agents?",
            "Is Radiation Safety Committee approval documented for radioactive materials?",
            "Are personnel protective measures specified for the identified hazards?",
        ],
        "rubric_examples": {
            3: "All hazardous agents are identified, relevant safety committees (IBC/Radiation/EH&S) have documented approvals, and PPE measures are specified.",
            2: "Hazardous agents are identified and some committee approvals are documented, but one safety clearance or PPE specification is missing.",
            1: "Hazardous agents are mentioned but key safety approvals or protective measures are largely absent.",
            0: "No hazardous agent identification or safety documentation is provided despite protocol involving biological, chemical, or radiological materials.",
        },
    },
    "writing_quality": {
        "label": "Writing quality and language",
        "ref_prefixes": [],
        "analysis_keys": ["summary", "experiments", "alternatives"],
        "sub_questions": [
            "Is the protocol written in English throughout (excluding form headers)?",
            "Are there any answer fields containing Hebrew text that should have been written in English?",
            "Is the English grammar correct and free of major errors?",
            "Is scientific terminology used accurately and consistently?",
            "Are methods and procedures described with sufficient clarity and precision?",
            "Are sentences concise and unambiguous, avoiding vague or filler language?",
        ],
        "rubric_examples": {
            3: "All answer fields are in English with correct grammar, precise scientific terminology, and clear unambiguous descriptions.",
            2: "Answers are in English with minor grammatical issues; scientific writing is mostly clear but occasionally vague.",
            1: "Significant grammar errors, imprecise terminology, or some answer fields still contain Hebrew text.",
            0: "Multiple answer fields are in Hebrew, or English text has pervasive grammar and clarity problems.",
        },
    },
}


_ALLOWED_PROMPTS = frozenset({
    "llm_verifier_prompt.md",
    "llm_autofix_prompt.md",
    "llm_human_eye_prompt.md",
})


def load_prompt(filename: str) -> str:
    if filename not in _ALLOWED_PROMPTS:
        raise ValueError(f"Unknown prompt: {filename}")
    return (PROMPTS_DIR / filename).read_text(encoding="utf-8")


_law_missing_warned = False


def _load_law_text(max_chars: int = 1200) -> str:
    global _law_missing_warned
    if law_loaded():
        text = LAW_PATH.read_text(encoding="utf-8")
        return text[:max_chars]
    if not _law_missing_warned:
        logger.warning("Law text missing at %s — LLM review runs WITHOUT law grounding", LAW_PATH)
        _law_missing_warned = True
    return ""


def _load_case_reports(max_chars: int = 2000) -> str:
    """
    Load a trimmed global ethics report + CASE_REPORTs to ground thematic reasoning.
    """
    texts: List[str] = []
    global_report = HEAD_TO_HEAD_DIR / "GLOBAL_ETHICS_REPORT.md"
    if global_report.exists():
        texts.append("# GLOBAL_ETHICS_REPORT\n" + global_report.read_text(encoding="utf-8"))

    if HEAD_TO_HEAD_DIR.exists():
        for p in HEAD_TO_HEAD_DIR.rglob("CASE_REPORT.md"):
            try:
                texts.append(f"# CASE_REPORT: {p.parent.name}\n" + p.read_text(encoding="utf-8"))
            except OSError:
                continue
    joined = "\n\n---\n\n".join(texts)
    return joined[:max_chars]


def _filter_checks(lint_report: Dict[str, Any], prefixes: List[str]) -> List[Dict[str, Any]]:
    checks = lint_report.get("checklist") or []
    if not prefixes:
        return checks
    out = []
    for c in checks:
        ref = c.get("reference") or ""
        if any(ref.startswith(p) for p in prefixes):
            out.append(c)
    return out


def _slice_analysis(analysis: Dict[str, Any], keys: List[str]) -> Dict[str, Any]:
    if not analysis:
        return {}
    return {k: analysis.get(k) for k in keys if k in analysis}


def _score_to_label(score: int) -> str:
    return GRADE_LABELS.get(score, "inadequate")


def _normalize_score(value: Any, default: int = 1) -> int:
    if isinstance(value, bool):
        return default
    if isinstance(value, int):
        return value if value in GRADE_LABELS else default
    if isinstance(value, str):
        value = value.strip()
        if value.isdigit():
            score = int(value)
            return score if score in GRADE_LABELS else default
        normalized = value.lower().strip().replace("-", "_").replace(" ", "_")
        alias_map = {
            "not_addressed": 0,
            "missing": 0,
            "inadequate": 1,
            "poor": 1,
            "partially_adequate": 2,
            "partial": 2,
            "partially_addressed": 2,
            "adequate": 3,
            "good": 3,
        }
        return alias_map.get(normalized, default)
    return default


def _normalize_label(value: Any, score: int) -> str:
    if isinstance(value, str):
        normalized = value.lower().strip().replace("-", "_").replace(" ", "_")
        if normalized in VALID_GRADE_LABELS:
            return normalized
    return _score_to_label(score)


def _build_fallback_theme(theme_spec: Dict[str, Any], rationale: str) -> Dict[str, Any]:
    return {
        "score": 1,
        "label": _score_to_label(1),
        "rationale": rationale,
        "sub_questions": [
            {
                "question": question,
                "score": 1,
                "label": _score_to_label(1),
                "rationale": "LLM response was unavailable, so this sub-question defaults to inadequate for manual review.",
            }
            for question in theme_spec.get("sub_questions") or []
        ],
    }


def _normalize_theme_payload(theme_spec: Dict[str, Any], theme_payload: Any, fallback_rationale: str) -> Dict[str, Any]:
    if not isinstance(theme_payload, dict):
        return _build_fallback_theme(theme_spec, fallback_rationale)

    score = _normalize_score(theme_payload.get("score"))
    rationale = str(theme_payload.get("rationale") or fallback_rationale).strip()
    if not rationale:
        rationale = fallback_rationale

    sub_questions = []
    expected_questions = theme_spec.get("sub_questions") or []
    raw_sub_questions = theme_payload.get("sub_questions")
    if isinstance(raw_sub_questions, list):
        for idx, item in enumerate(raw_sub_questions):
            if not isinstance(item, dict):
                continue
            sub_score = _normalize_score(item.get("score"), default=score)
            question = str(item.get("question") or "").strip()
            if not question and idx < len(expected_questions):
                question = expected_questions[idx]
            if not question:
                continue
            sub_rationale = str(item.get("rationale") or rationale).strip() or rationale
            sub_questions.append({
                "question": question,
                "score": sub_score,
                "label": _normalize_label(item.get("label"), sub_score),
                "rationale": sub_rationale,
            })

    if not sub_questions:
        sub_questions = [
            {
                "question": question,
                "score": score,
                "label": _score_to_label(score),
                "rationale": rationale,
            }
            for question in expected_questions
        ]

    return {
        "score": score,
        "label": _normalize_label(theme_payload.get("label"), score),
        "rationale": rationale,
        "sub_questions": sub_questions,
    }


def _format_rubric_examples(theme_spec: Dict[str, Any]) -> str:
    examples = theme_spec.get("rubric_examples") or {}
    lines = [
        "Use this grading rubric for every sub-question and for the overall theme score:",
        "- 3 (adequate): criterion is fully addressed and committee-ready.",
        "- 2 (partially_adequate): criterion is present but incomplete or weak in one important way.",
        "- 1 (inadequate): criterion is addressed poorly and needs substantial revision.",
        "- 0 (not_addressed): criterion is missing or unsupported.",
    ]
    if examples:
        lines.extend([
            "",
            "Theme-specific score examples:",
            f"- 3 example: {examples.get(3, '')}",
            f"- 2 example: {examples.get(2, '')}",
            f"- 1 example: {examples.get(1, '')}",
            f"- 0 example: {examples.get(0, '')}",
        ])
    return "\n".join(lines)


def _build_expected_theme_shape(theme_key: str) -> Dict[str, Any]:
    return {
        theme_key: {
            "score": "0 | 1 | 2 | 3",
            "label": "not_addressed | inadequate | partially_adequate | adequate",
            "rationale": "short explanation grounded in law/x_meta/signals",
            "sub_questions": [
                {
                    "question": "repeat the sub-question text",
                    "score": "0 | 1 | 2 | 3",
                    "label": "not_addressed | inadequate | partially_adequate | adequate",
                    "rationale": "short explanation grounded in the protocol",
                }
            ],
        },
        "questions": [
            {
                "field_path": "json.path",
                "question": "clarification you would ask the PI",
                "blocking": True,
            }
        ],
    }


def _build_avma_grounding_block(theme_key: str, instance: Dict[str, Any]) -> str:
    if theme_key != "euthanasia_and_endpoints":
        return ""

    from .avma_matrix import format_avma_summary_for_species, normalize_species

    species_in_protocol: set[str] = set()
    for exp in instance.get("experiments") or []:
        sp = normalize_species((exp.get("animals") or {}).get("species") or "")
        if sp:
            species_in_protocol.add(sp)

    if not species_in_protocol:
        return ""

    avma_lines = ["## AVMA 2020 Euthanasia Guidelines for species in this protocol:\n"]
    for sp in sorted(species_in_protocol):
        avma_lines.append(format_avma_summary_for_species(sp))
    avma_lines.append(
        "\nNote: Pre-charged CO₂ chambers are UNACCEPTABLE for ALL species. "
        "CO₂ always requires a secondary physical confirmation method."
    )
    return "\n".join(avma_lines) + "\n\n"


def _build_sub_questions_block(theme_spec: Dict[str, Any]) -> str:
    sub_questions = theme_spec.get("sub_questions") or []
    if not sub_questions:
        return ""
    sq_lines = "\n".join(f"- {q}" for q in sub_questions)
    return (
        "\nFor each sub-question below, assign a score from 0 to 3 and briefly explain your reasoning "
        "before giving the overall theme score:\n"
        f"{sq_lines}\n"
    )


def _build_theme_prompt(
    theme_key: str,
    theme_spec: Dict[str, Any],
    instance: Dict[str, Any],
    lint_report: Dict[str, Any],
    *,
    pass_name: str,
    pass1_theme: Optional[Dict[str, Any]] = None,
    pass1_questions: Optional[List[Dict[str, Any]]] = None,
) -> str:
    """
    Build a small, theme-focused prompt to reduce load on the model.
    """
    analysis = lint_report.get("analysis") or {}
    analysis_subset = _slice_analysis(analysis, theme_spec.get("analysis_keys", []))
    law_text = _load_law_text()
    case_reports = _load_case_reports()
    analysis_str = json.dumps(analysis_subset, ensure_ascii=False, indent=2)
    expected_str = json.dumps(
        _build_expected_theme_shape(theme_key),
        ensure_ascii=False,
        indent=2,
    )
    avma_grounding_block = _build_avma_grounding_block(theme_key, instance)
    sub_questions_block = _build_sub_questions_block(theme_spec)

    prompt_lines = [
        f"Theme key: {theme_key}",
        f"Theme label: {theme_spec['label']}",
        "",
    ]

    if pass_name == "blind":
        prompt_lines.extend(
            [
                (
                    f"You are an ethics reviewer performing Pass 1 (blind review) for the theme "
                    f"'{theme_spec['label']}' on this animal experiment request."
                ),
                (
                    "Use only the raw protocol, law excerpt, head-to-head committee notes, AVMA "
                    "grounding when provided, and the analysis signals below. Do not assume any "
                    "prior automated review exists. Respond ONLY with valid JSON."
                ),
                "Do not return binary verdicts or confidence ratings.",
                "",
                f"Law excerpt (trimmed):\n{law_text}\n",
                f"Head-to-head committee notes (trimmed):\n{case_reports}\n",
            ]
        )
    else:
        checks = _filter_checks(lint_report, theme_spec.get("ref_prefixes", []))
        checks_str = json.dumps(checks, ensure_ascii=False, indent=2)
        pass1_theme_str = json.dumps(pass1_theme or {}, ensure_ascii=False, indent=2)
        pass1_questions_str = json.dumps(pass1_questions or [], ensure_ascii=False, indent=2)
        prompt_lines.extend(
            [
                (
                    f"You are an ethics reviewer performing Pass 2 (reconciliation) for the theme "
                    f"'{theme_spec['label']}' on this animal experiment request."
                ),
                (
                    "Start from the blind Pass 1 result, then reconcile it with the theme-relevant "
                    "linter findings. Confirm shared findings, resolve discrepancies, and produce the "
                    "final graded theme verdict. Respond ONLY with valid JSON."
                ),
                "Do not return binary verdicts or confidence ratings.",
                "",
                f"Law excerpt (trimmed):\n{law_text}\n",
                f"Head-to-head committee notes (trimmed):\n{case_reports}\n",
                "Blind Pass 1 result:\n"
                f"```json\n{pass1_theme_str}\n```\n",
                "Blind Pass 1 PI questions:\n"
                f"```json\n{pass1_questions_str}\n```\n",
                "Theme-relevant linter items:\n"
                f"```json\n{checks_str}\n```\n",
            ]
        )

    prompt_lines.extend(
        [
            avma_grounding_block,
            "Analysis signals (subset):\n"
            f"```json\n{analysis_str}\n```\n",
            f"{_format_rubric_examples(theme_spec)}\n",
            sub_questions_block,
            (
                "You may think through your reasoning first. After your analysis, output the graded "
                "result as a JSON object with this exact structure:\n"
                f"```json\n{expected_str}\n```"
            ),
            "",
            'If you have no questions, set "questions": [].',
        ]
    )

    return "\n".join(part for part in prompt_lines if part is not None)


def _question_signature(question: Dict[str, Any]) -> str:
    return json.dumps(
        {
            "field_path": question.get("field_path"),
            "question": question.get("question"),
            "blocking": bool(question.get("blocking")),
        },
        sort_keys=True,
        ensure_ascii=False,
    )


def _normalize_questions(payload: Any) -> List[Dict[str, Any]]:
    if not isinstance(payload, list):
        return []

    seen = set()
    normalized: List[Dict[str, Any]] = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        question = {
            "field_path": str(item.get("field_path") or "").strip(),
            "question": str(item.get("question") or "").strip(),
            "blocking": bool(item.get("blocking")),
        }
        if not question["question"]:
            continue
        signature = _question_signature(question)
        if signature in seen:
            continue
        seen.add(signature)
        normalized.append(question)
    return normalized


def _merge_questions(*question_lists: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    merged: List[Dict[str, Any]] = []
    seen = set()
    for questions in question_lists:
        for question in questions:
            signature = _question_signature(question)
            if signature in seen:
                continue
            seen.add(signature)
            merged.append(question)
    return merged


def _build_theme_metadata(
    pass1_theme: Dict[str, Any],
    final_theme: Dict[str, Any],
    pass1_questions: List[Dict[str, Any]],
    pass2_questions: List[Dict[str, Any]],
) -> Dict[str, Any]:
    pass1_score = pass1_theme.get("score", 1)
    final_score = final_theme.get("score", 1)
    pass1_label = pass1_theme.get("label", _score_to_label(pass1_score))
    final_label = final_theme.get("label", _score_to_label(final_score))
    pass1_question_signatures = {_question_signature(q) for q in pass1_questions}
    pass2_question_signatures = {_question_signature(q) for q in pass2_questions}
    return {
        "pass1_changed": (
            pass1_score != final_score
            or pass1_label != final_label
            or not pass2_question_signatures.issubset(pass1_question_signatures)
        ),
        "pass1_score": pass1_score,
        "final_score": final_score,
        "pass1_label": pass1_label,
        "final_label": final_label,
        "new_questions_added": not pass2_question_signatures.issubset(pass1_question_signatures),
    }


def prepare_verification_prompt(instance: Dict[str, Any], lint_report: Dict[str, Any]) -> str:
    """
    Compose the full prompt for the 'Human Verify' step (legacy single-call).
    """
    base_prompt = load_prompt("llm_verifier_prompt.md")
    reference_catalog = json.dumps(load_high_leverage_catalog(), indent=2, ensure_ascii=False)
    law_text = _load_law_text()
    case_reports = _load_case_reports()

    schema_str = json.dumps(IACUC_SCHEMA_V2, indent=2, ensure_ascii=False)
    instance_str = json.dumps(instance, indent=2, ensure_ascii=False)
    report_str = json.dumps(lint_report, indent=2, ensure_ascii=False)
    analysis_str = json.dumps(lint_report.get("analysis") or {}, indent=2, ensure_ascii=False)

    return f"""{base_prompt}

---
### 0. Law and official guidance (English translation)
{law_text}

### 0b. Head-to-head committee reasoning (GLOBAL_ETHICS_REPORT + CASE_REPORTs)
{case_reports}

### 1. High-leverage x_meta reference catalog (N, 3Rs, severity, monitoring, analgesia, endpoints, euthanasia)
```json
{reference_catalog}
```

### 2. Schema (with x_meta rules)
```json
{schema_str}
```

### 3. JSON Instance
```json
{instance_str}
```

### 4. Linter Report
```json
{report_str}
```

### 5. Extracted analysis signals (summary, alternatives, per-experiment features)
```json
{analysis_str}
```
"""


def prepare_autofix_prompt(instance: Dict[str, Any], lint_report: Dict[str, Any]) -> str:
    """
    Compose the full prompt for the 'Autofix' step.
    """
    base_prompt = load_prompt("llm_autofix_prompt.md")
    reference_catalog = json.dumps(load_high_leverage_catalog(), indent=2, ensure_ascii=False)
    law_text = _load_law_text()
    case_reports = _load_case_reports()

    schema_str = json.dumps(IACUC_SCHEMA_V2, indent=2, ensure_ascii=False)
    instance_str = json.dumps(instance, indent=2, ensure_ascii=False)
    report_str = json.dumps(lint_report, indent=2, ensure_ascii=False)
    analysis_str = json.dumps(lint_report.get("analysis") or {}, indent=2, ensure_ascii=False)

    return f"""{base_prompt}

---
### 0. Law and official guidance (English translation)
{law_text}

### 0b. Head-to-head committee reasoning (GLOBAL_ETHICS_REPORT + CASE_REPORTs)
{case_reports}

### 1. High-leverage x_meta reference catalog (N, 3Rs, severity, monitoring, analgesia, endpoints, euthanasia)
```json
{reference_catalog}
```

### 2. Schema
```json
{schema_str}
```

### 3. Input Instance
```json
{instance_str}
```

### 4. Linter Report
```json
{report_str}
```

### 5. Extracted analysis signals (summary, alternatives, per-experiment features)
```json
{analysis_str}
```
"""


def _strip_code_fence(payload: str) -> str:
    """Strip markdown code fences from payload, handling various positions."""
    payload = payload.strip()

    # Pattern to match ```json or ``` blocks
    # This extracts content from inside code fences
    code_block_match = re.search(r'```(?:json)?\s*\n?(.*?)\n?```', payload, flags=re.DOTALL)
    if code_block_match:
        return code_block_match.group(1).strip()

    # Fallback: if starts with ```, use line-based stripping
    if payload.startswith("```"):
        lines = payload.splitlines()
        if not lines:
            return payload
        lines = lines[1:]  # Drop opening fence
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]  # Drop closing fence
        return "\n".join(lines).strip()

    return payload


def parse_llm_json(response_text: str) -> Dict[str, Any]:
    """
    Parse the LLM JSON response (tolerating fenced code blocks, thinking tags, etc).
    """
    cleaned = response_text.strip()

    # Step 1: Remove <think>...</think> or <thinking>...</thinking> blocks FIRST
    cleaned = re.sub(r'<think(?:ing)?>.*?</think(?:ing)?>', '', cleaned, flags=re.DOTALL | re.IGNORECASE)
    cleaned = cleaned.strip()

    # Step 2: Strip code fences (```json ... ```)
    cleaned = _strip_code_fence(cleaned)

    # Step 3: Try direct JSON parse
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass

    # Best-effort: try to extract JSON object from the text
    # Find the first { and matching }
    start = cleaned.find("{")
    if start == -1:
        raise ValueError(f"LLM response contains no JSON object. Preview: {cleaned[:200]!r}")

    # Find matching closing brace
    depth = 0
    end = -1
    in_string = False
    escape_next = False

    for i, char in enumerate(cleaned[start:], start):
        if escape_next:
            escape_next = False
            continue
        if char == '\\' and in_string:
            escape_next = True
            continue
        if char == '"' and not escape_next:
            in_string = not in_string
            continue
        if in_string:
            continue
        if char == '{':
            depth += 1
        elif char == '}':
            depth -= 1
            if depth == 0:
                end = i
                break

    if end != -1:
        snippet = cleaned[start:end + 1]
        try:
            return json.loads(snippet)
        except json.JSONDecodeError:
            pass

    # Last resort: find first { to last }
    end = cleaned.rfind("}")
    if start != -1 and end != -1 and end > start:
        snippet = cleaned[start:end + 1]
        try:
            return json.loads(snippet)
        except json.JSONDecodeError:
            pass

    preview = cleaned[:300].replace("\n", " ")
    raise ValueError(f"LLM response was not valid JSON. Preview: {preview!r}")


def run_verification(
    instance: Dict[str, Any],
    lint_report: Dict[str, Any],
    *,
    provider: Optional[str] = None,
    model: Optional[str] = None,
    temperature: float = 0.2,
    mode: str = "multi",  # "multi" (per-theme small prompts) or "single" (legacy mega prompt)
    stance: str = "law",  # "law" (strict) or "committee" (legacy/approved softness)
) -> Dict[str, Any]:
    """
    Execute the verification prompt against the configured LLM provider
    and return the parsed JSON verdict.
    """
    if mode == "single":
        prompt = prepare_verification_prompt(instance, lint_report)
        try:
            raw_response = call_llm(prompt, provider=provider, model=model, temperature=temperature)
        except LLMError as exc:
            raise RuntimeError(f"LLM verification call failed: {exc}") from exc
        return parse_llm_json(raw_response)

    # Default: multi-theme, smaller prompts to reduce model load.
    themes: Dict[str, Any] = {}
    pass1_themes: Dict[str, Any] = {}
    theme_metadata: Dict[str, Any] = {}
    questions: List[Dict[str, Any]] = []
    disagreement_theme_keys: List[str] = []

    use_two_step = os.getenv("OLLAMA_TWO_STEP", "").lower() in ("1", "true")

    for theme_key, theme_spec in THEME_SPECS.items():
        blind_prompt = _build_theme_prompt(
            theme_key,
            theme_spec,
            instance,
            lint_report,
            pass_name="blind",
        )
        fallback_rationale = (
            "LLM did not return a usable graded result; defaulting to inadequate."
        )
        try:
            if use_two_step:
                raw = call_llm_two_step(blind_prompt, model=model, temperature=temperature)
            else:
                raw = call_llm(
                    blind_prompt,
                    provider=provider,
                    model=model,
                    temperature=temperature,
                )
            blind_parsed = parse_llm_json(raw)
        except Exception:
            blind_parsed = {
                theme_key: _build_fallback_theme(theme_spec, fallback_rationale),
                "questions": [],
            }

        blind_theme_payload = (
            blind_parsed.get(theme_key) if isinstance(blind_parsed, dict) else None
        )
        pass1_themes[theme_key] = _normalize_theme_payload(
            theme_spec,
            blind_theme_payload,
            fallback_rationale="LLM did not return the expected graded structure.",
        )
        pass1_questions = (
            _normalize_questions(blind_parsed.get("questions"))
            if isinstance(blind_parsed, dict)
            else []
        )

        reconcile_prompt = _build_theme_prompt(
            theme_key,
            theme_spec,
            instance,
            lint_report,
            pass_name="reconcile",
            pass1_theme=pass1_themes[theme_key],
            pass1_questions=pass1_questions,
        )
        reconcile_fallback = (
            "LLM did not return a usable reconciled graded result; defaulting to inadequate."
        )
        try:
            if use_two_step:
                raw = call_llm_two_step(
                    reconcile_prompt,
                    model=model,
                    temperature=temperature,
                )
            else:
                raw = call_llm(
                    reconcile_prompt,
                    provider=provider,
                    model=model,
                    temperature=temperature,
                )
            reconcile_parsed = parse_llm_json(raw)
        except Exception:
            reconcile_parsed = {
                theme_key: _build_fallback_theme(theme_spec, reconcile_fallback),
                "questions": [],
            }

        theme_payload = (
            reconcile_parsed.get(theme_key)
            if isinstance(reconcile_parsed, dict)
            else None
        )
        themes[theme_key] = _normalize_theme_payload(
            theme_spec,
            theme_payload,
            fallback_rationale=(
                "LLM did not return the expected reconciled graded structure."
            ),
        )
        pass2_questions = (
            _normalize_questions(reconcile_parsed.get("questions"))
            if isinstance(reconcile_parsed, dict)
            else []
        )

        metadata = _build_theme_metadata(
            pass1_themes[theme_key],
            themes[theme_key],
            pass1_questions,
            pass2_questions,
        )
        theme_metadata[theme_key] = metadata
        if metadata["pass1_changed"]:
            disagreement_theme_keys.append(theme_key)

        questions = _merge_questions(questions, pass1_questions, pass2_questions)

    return {
        "themes": themes,
        "pass1_themes": pass1_themes,
        "theme_metadata": theme_metadata,
        "disagreement_summary": {
            "themes_with_disagreement": len(disagreement_theme_keys),
            "total_themes": len(THEME_SPECS),
            "theme_keys": disagreement_theme_keys,
        },
        "checklist_items": [],  # keep empty; this flow focuses on thematic verdicts
        "questions": questions,
    }


def run_verification_stream(
    instance: Dict[str, Any],
    lint_report: Dict[str, Any],
    *,
    provider: Optional[str] = None,
    model: Optional[str] = None,
    temperature: float = 0.2,
    stance: str = "committee",
) -> Generator[Dict[str, Any], None, None]:
    """
    Execute verification with streaming updates.

    Yields events:
    - {"type": "theme_start", "theme": "theme_key", "label": "Theme Label"}
    - {"type": "token", "theme": "theme_key", "token": "..."}
    - {"type": "theme_done", "theme": "theme_key", "result": {...}}
    - {"type": "complete", "result": {...}}
    """
    themes: Dict[str, Any] = {}
    pass1_themes: Dict[str, Any] = {}
    theme_metadata: Dict[str, Any] = {}
    questions: List[Dict[str, Any]] = []
    disagreement_theme_keys: List[str] = []

    total_themes = len(THEME_SPECS)
    processed = 0
    budget_warned = False  # one warning per stream is enough; theme prompts are all about the same size

    for theme_key, theme_spec in THEME_SPECS.items():
        processed += 1

        # Emit theme start
        yield {
            "type": "theme_start",
            "theme": theme_key,
            "label": theme_spec["label"],
            "progress": processed,
            "total": total_themes,
        }

        blind_prompt = _build_theme_prompt(
            theme_key,
            theme_spec,
            instance,
            lint_report,
            pass_name="blind",
        )

        if not budget_warned:
            warning = context_budget_warning(blind_prompt, label=f"Layer 2 / {theme_spec['label']}")
            if warning:
                budget_warned = True
                yield {**warning, "theme": theme_key}

        # Stream tokens (or fall back to two-step non-streaming if OLLAMA_TWO_STEP=1)
        full_response = ""
        use_two_step = os.getenv("OLLAMA_TWO_STEP", "").lower() in ("1", "true")
        fallback_rationale = "LLM streaming failed; defaulting to inadequate for manual review."
        try:
            if use_two_step:
                # Two-step does not support streaming; emit full response as a single token.
                full_response = call_llm_two_step(
                    blind_prompt,
                    model=model,
                    temperature=temperature,
                )
                yield {
                    "type": "token",
                    "theme": theme_key,
                    "token": full_response,
                }
            else:
                for token in call_llm_stream(
                    blind_prompt,
                    provider=provider,
                    model=model,
                    temperature=temperature,
                ):
                    full_response += token
                    yield {
                        "type": "token",
                        "theme": theme_key,
                        "token": token,
                    }

            blind_parsed = parse_llm_json(full_response)
        except Exception as e:
            blind_parsed = {
                theme_key: _build_fallback_theme(theme_spec, f"LLM error: {str(e)[:100]}"),
                "questions": [],
            }

        blind_theme_payload = (
            blind_parsed.get(theme_key) if isinstance(blind_parsed, dict) else None
        )
        pass1_themes[theme_key] = _normalize_theme_payload(
            theme_spec,
            blind_theme_payload,
            fallback_rationale=fallback_rationale,
        )
        pass1_questions = (
            _normalize_questions(blind_parsed.get("questions"))
            if isinstance(blind_parsed, dict)
            else []
        )

        reconcile_prompt = _build_theme_prompt(
            theme_key,
            theme_spec,
            instance,
            lint_report,
            pass_name="reconcile",
            pass1_theme=pass1_themes[theme_key],
            pass1_questions=pass1_questions,
        )

        full_response = ""
        reconcile_fallback = (
            "LLM streaming failed during reconciliation; defaulting to inadequate for manual review."
        )
        try:
            if use_two_step:
                full_response = call_llm_two_step(
                    reconcile_prompt,
                    model=model,
                    temperature=temperature,
                )
                yield {
                    "type": "token",
                    "theme": theme_key,
                    "token": full_response,
                }
            else:
                for token in call_llm_stream(
                    reconcile_prompt,
                    provider=provider,
                    model=model,
                    temperature=temperature,
                ):
                    full_response += token
                    yield {
                        "type": "token",
                        "theme": theme_key,
                        "token": token,
                    }

            reconcile_parsed = parse_llm_json(full_response)
        except Exception as e:
            reconcile_parsed = {
                theme_key: _build_fallback_theme(
                    theme_spec,
                    f"LLM error: {str(e)[:100]}",
                ),
                "questions": [],
            }

        theme_payload = (
            reconcile_parsed.get(theme_key)
            if isinstance(reconcile_parsed, dict)
            else None
        )
        themes[theme_key] = _normalize_theme_payload(
            theme_spec,
            theme_payload,
            fallback_rationale=reconcile_fallback,
        )
        pass2_questions = (
            _normalize_questions(reconcile_parsed.get("questions"))
            if isinstance(reconcile_parsed, dict)
            else []
        )
        metadata = _build_theme_metadata(
            pass1_themes[theme_key],
            themes[theme_key],
            pass1_questions,
            pass2_questions,
        )
        theme_metadata[theme_key] = metadata
        if metadata["pass1_changed"]:
            disagreement_theme_keys.append(theme_key)
        questions = _merge_questions(questions, pass1_questions, pass2_questions)

        yield {
            "type": "theme_done",
            "theme": theme_key,
            "label": theme_spec["label"],
            "result": themes[theme_key],
            "skipped": False,
        }

    # Final result
    final_result = {
        "themes": themes,
        "pass1_themes": pass1_themes,
        "theme_metadata": theme_metadata,
        "disagreement_summary": {
            "themes_with_disagreement": len(disagreement_theme_keys),
            "total_themes": len(THEME_SPECS),
            "theme_keys": disagreement_theme_keys,
        },
        "checklist_items": [],
        "questions": questions,
    }

    yield {
        "type": "complete",
        "result": final_result,
    }
