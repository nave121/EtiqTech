# src/linter_renderer.py

"""
Linter + HTML renderer for IACUC_SCHEMA_V2 instances.

- lint(instance)  -> report dict with a pass/fail checklist and fix suggestions.
- render_html(instance, out_html_path=None) -> HTML string (and optionally writes file).

This is deliberately pure stdlib: no external dependencies required.
"""

import argparse
import datetime
import html
import json
import re
from pathlib import Path
from typing import Any, Dict, List, Tuple

from .schema import IACUC_SCHEMA_V2  # not used for strict validation yet, but here for future use
from .rules import annotate_report, apply_pack
from .lint_rules.context import RuleContext, _rule  # noqa: F401  (_rule stays importable from here)
from .lint_rules import colony, summaries
from .avma_matrix import (
    normalize_species,
    normalize_method,
    check_method_for_species,
    get_displacement_rate_range,
)


CSS = """
body{
  direction:rtl;
  color:#000;
  font-size:11pt;
  font-family:Arial, Helvetica, sans-serif;
}
.header{
  font-size:14pt;
  font-weight:bold;
  text-align:center;
}
.content {
  padding: 30px 5%;
}
.sub-header{
  text-decoration:underline;
  font-weight:bold;
  padding:10px;
}
.table-header{
  padding-top:6px;
  padding-bottom:6px;
}
.table {
  width:100%;
}
.table table{
  width:100%;
  border-collapse:collapse;
  font-size:11pt;
  padding-right:6px;
  table-layout:fixed;
}
.table table td {
  border: 1px solid #000;
  line-height:24px;
  height:24px;
  padding:3px;
  padding-right:6px;
  word-break: normal;
  word-wrap: break-word;
}
.table table tr td.even {
  background-color: lightgrey;
}
.table.horizontal th{
  background-color: lightgrey;
  text-align:right;
  border: 1px solid #000;
  line-height:16px;
  height:24px;
}
.table div{
  line-height:24px;
}
.padding{
  padding-top: 10px;
}
tr,td{
  max-width: 100% !important;
  table-layout: auto !important;
  width: auto !important;
}
table{
  width: 100% !important;
}
"""


def _e(val: Any) -> str:
    """HTML-escape helper."""
    return html.escape("" if val is None else str(val))


def _flatten_text(value: Any) -> str:
    """Collapse nested strings, lists, and dicts into searchable text."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        return " ".join(_flatten_text(v) for v in value.values())
    if isinstance(value, list):
        return " ".join(_flatten_text(v) for v in value)
    return str(value)


def _canonical_species_key(animals: Dict[str, Any]) -> str:
    """Prefer explicit structured species and fall back to normalized legacy species."""
    structured = (animals.get("species_standard") or "").strip()
    if structured:
        return normalize_species(structured) or structured
    return normalize_species((animals.get("species") or "").strip()) or ""


def _canonical_method_key(euthanasia: Dict[str, Any]) -> str:
    """Prefer explicit structured euthanasia method and fall back to primary text."""
    structured = (euthanasia.get("method_standard") or "").strip()
    if structured:
        return normalize_method(structured) or structured
    return normalize_method((euthanasia.get("primary") or "").strip()) or ""


def _euthanasia_conditions_text(euthanasia: Dict[str, Any]) -> str:
    """Prefer explicit structured conditions text but preserve legacy parameters fallback."""
    return (
        euthanasia.get("conditions_text")
        or euthanasia.get("parameters")
        or ""
    )


def _anesthesia_rows(exp: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Prefer structured anesthesia drugs and fall back to legacy anesthesia rows."""
    return (exp.get("anesthesia_drugs") or exp.get("anesthesia") or [])


def _anesthesia_text(exp: Dict[str, Any]) -> str:
    return _flatten_text(_anesthesia_rows(exp)).lower()


def _pain_category(exp: Dict[str, Any]) -> str:
    raw = (exp.get("pain_category") or "").strip().upper()
    if raw in {"B", "C", "D", "E"}:
        return raw
    structured = exp.get("pain_category_structured") or {}
    parsed = (structured.get("parsed") or "").strip().upper()
    return parsed if parsed in {"B", "C", "D", "E"} else ""


def _coerce_float(value: Any) -> float | None:
    try:
        if value in (None, ""):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _coerce_int(value: Any) -> int | None:
    try:
        if value in (None, ""):
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def _animal_weight_grams(animals: Dict[str, Any]) -> float | None:
    weight = animals.get("weight") or {}
    value = _coerce_float(weight.get("value"))
    if value is None:
        return None
    unit = (weight.get("unit") or "g").lower()
    if unit == "kg":
        return value * 1000.0
    return value


def _nonempty(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, list):
        return any(_nonempty(item) for item in value)
    return True


# Classification of checks for reporting / analysis.
# This does NOT change behavior; it only affects summary counters in the report.
STRUCTURAL_REFS = {
    "header",
    "research",
    "pi",
    "pi:training",
    "participant:training",
    "animals:totals-vs-exps",
    "continuation",
    "third-party",
    "colony:no-invasive",
    "term:track",
}

LAW_CRITICAL_REFS = {
    "title:track",
    "euthanasia:overdose-confirm",
    "euthanasia:CO2",        # AVMA 2020 mandatory language; NRC Guide has legal force in Israel
    "severity:monitoring",
    "severity:analgesia",    # §1 Schedule + §23 criminal penalties; error in both profiles
    "endpoints:20%-only",    # Committee-level rejection pattern; warning→error in strict_law
    "endpoints:death-only",   # Death/moribundity as sole endpoint without prior criteria
    "postop:monitoring",      # Survival surgery missing post-op monitoring plan
    "special:neonatal-CO2",   # CO₂ as sole method for neonates (AVMA 50-min requirement)
    "alts:missing",
    "alts:engines",
    "paralytic:without-anesthesia",
    "pain:category-consistency",
    "cosmetics:ban",
    # --- AVMA species-euthanasia matrix rules (P1 epic) ---
    "euthanasia:species-method",      # Unacceptable method for species — error in BOTH profiles
    "euthanasia:conditions-missing",  # Conditionally acceptable without documented conditions
    "euthanasia:displacement-rate",   # CO₂ without displacement rate specified
    "euthanasia:secondary-method",    # CO₂/inhalant without secondary physical confirmation
    "euthanasia:precharged-chamber",  # Pre-charged CO₂ chamber — error in BOTH profiles
    "euthanasia:cervical-weight",     # Cervical dislocation exceeding species weight limit
    "reuse:justification",
    "permits:field-study",
}

ADVISORY_REFS = {
    "title:pilot-label",
    "participant:certified-without-training",
    "scope:pilot-size",
    "sex:rationale",
    "sex:sabv",
    "N:justification-detail",
    "endpoints:generic-consult",
    "surgery:multiple-survival",  # Multiple survival experiments, possible animal reuse
    "N:power-analysis",           # Non-trivial N without power analysis or precedent method
    "alts:queries",
    "alts:conclusion",
    "summaries:scientific-length",
    "summaries:lay-length",
    "special:stereotaxic",
    "special:oncology",
    "special:diabetes",
    "special:biosafety",
    "special:nanomaterials",
    "special:ocular",
    "vet:consultation",           # Severity 4-5 requires documented vet consultation
    "deprivation:protocol",       # Food/water deprivation needs weight monitoring + endpoints
    "gma:ibc",                    # Genetically modified animals may need IBC approval
    "ascites:in-vitro",           # Ascites method requires in vitro alternatives justification
    "colony:breeding-plan",       # Colony protocols require colony management plan
    "housing:density",
    "restraint:duration",
}

def lint(instance: Dict[str, Any], profile: str = "default") -> Dict[str, Any]:
    """
    Run deterministic checks on a concrete instance.

    This is not a full JSON Schema validator – it assumes the basic shape is already OK.
    It focuses on the cross-field logic and domain rules that typically break in raw requests.

    Profiles:
    - "default": only structural + clear law minima increment the global error counter.
    - "strict_law": selected law-critical checks (e.g. alternatives search) are upgraded from warnings to errors.
    """
    if profile not in ("default", "strict_law"):
        profile = "default"

    ctx = RuleContext(instance=instance, profile=profile)

    # --- header ---
    if "header" not in instance:
        ctx.errors += 1
        ctx.checks.append(_rule(False, "", "Missing 'header' block.", ref="header"))
    else:
        ctx.req("header", instance["header"], ["protocol_id", "institution"])

    # --- research ---
    if "research" not in instance:
        ctx.errors += 1
        ctx.checks.append(_rule(False, "", "Missing 'research' block.", ref="research"))
    else:
        r = instance["research"]
        ctx.req(
            "research",
            r,
            [
                "title_he",
                "title_en",
                "request_type",
                "is_continuation",
                "third_party_service",
                "approval_term_years",
                "sites",
            ],
        )
        rt = r.get("request_type")
        title_he = r.get("title_he", "") or ""
        title_en = r.get("title_en", "") or ""

        # Title vs track
        if rt == "regular":
            bad = any(w in title_he for w in ["פיילוט", "פילוט"]) or "Pilot" in title_en
            ctx.checks.append(
                _rule(
                    not bad,
                    "Regular track: title does not contain 'Pilot/פיילוט'.",
                    "Regular track: title should not contain 'Pilot/פיילוט'.",
                    fix="Remove 'Pilot/פיילוט' indicators or change request_type to 'pilot'.",
                    ref="title:track",
                )
            )
            if bad:
                ctx.errors += 1
        if rt == "pilot":
            has_pilot = ("פיילוט" in title_he) or ("Pilot" in title_en)
            ctx.checks.append(
                _rule(
                    has_pilot,
                    "Pilot track: title clearly marked as Pilot.",
                    "Pilot track: title should explicitly include 'Pilot/פיילוט'.",
                    fix="Add 'פיילוט' to Hebrew title and 'Pilot' to English title.",
                    ref="title:pilot-label",
                )
            )
            if not has_pilot:
                ctx.warnings += 1

        # term vs track
        term = r.get("approval_term_years")
        if isinstance(term, int) and rt:
            # Relaxed to warning: Pilot 'should' be 1 year, but sometimes 4 is requested/approved.
            is_pilot = (rt == "pilot")
            ok_term = 1 <= term <= 4
            ideal_term = (term == 1) if is_pilot else True
            
            severity = "warning" if (ok_term and not ideal_term) else "error"
            if not ok_term: ctx.errors += 1 # Strict range check
            if ok_term and not ideal_term: ctx.warnings += 1

            fix_term = (
                "Pilot track ideally 1 year; regular/colony/continuation 1–4 years."
            )
            ctx.checks.append(
                _rule(
                    ideal_term,
                    "Approval term consistent with request type.",
                    f"Approval term {term} years is inconsistent with request_type='{rt}'.",
                    fix=fix_term,
                    severity=severity,
                    ref="term:track",
                )
            )

        # continuation metadata
        if r.get("is_continuation"):
            ok_cont = bool(r.get("prior_protocol_id")) and bool(
                r.get("continuation_reason")
            )
            ctx.checks.append(
                _rule(
                    ok_cont,
                    "Continuation has previous protocol ID and reason.",
                    "Continuation requires 'prior_protocol_id' and 'continuation_reason'.",
                    ref="continuation",
                )
            )
            if not ok_cont:
                ctx.errors += 1

        # third-party
        if r.get("third_party_service"):
            t = instance.get("third_party") or {}
            ok_tp = all(
                bool(t.get(k)) 
                for k in ["sponsor_org", "ordering_investigator_name", "sponsor_approver_name"]
            )
            fix_tp = (
                "Fill third_party.sponsor_org, ordering_investigator_name, "
                "sponsor_approver_name, and ideally declaration_url."
            )
            ctx.checks.append(
                _rule(
                    ok_tp,
                    "Third-party metadata is present.",
                    "Third-party service missing sponsor/ordering/approver details.",
                    fix=fix_tp,
                    ref="third-party",
                )
            )
            if not ok_tp:
                ctx.errors += 1

    # --- PI & training ---
    pi = instance.get("pi") or {}
    if not pi:
        ctx.errors += 1
        ctx.checks.append(_rule(False, "", "Missing 'pi' block.", ref="pi"))
    else:
        ctx.req(
            "pi",
            pi,
            [
                "id_type",
                "id_number",
                "last_name_he",
                "first_name_he",
                "last_name_en",
                "first_name_en",
                "email",
                "phone_primary",
                "institutional_cert_no",
            ],
        )
        has_pi_training = bool(pi.get("training"))
        ctx.checks.append(
            _rule(
                has_pi_training,
                "PI has at least one training certificate recorded.",
                "PI has no training certificate in 'pi.training'.",
                fix="Add at least one entry to pi.training[].",
                ref="pi:training",
            )
        )
        if not has_pi_training:
            ctx.errors += 1

    # --- participants & training ---
    participants = instance.get("participants") or []
    for idx, p in enumerate(participants, start=1):
        role = p.get("role")
        training = p.get("training") or []
        certified = bool(p.get("certified"))

        if role == "performs_procedures":
            ok_tr = bool(training)
            ctx.checks.append(
                _rule(
                    ok_tr,
                    f"Participant {idx} performs procedures and has training.",
                    f"Participant {idx} performs procedures but has no training entries.",
                    fix="Add at least one training certificate to this participant.",
                    ref="participant:training",
                )
            )
            if not ok_tr:
                ctx.errors += 1

        if certified and not training:
            ctx.checks.append(
                _rule(
                    False,
                    "",
                    f"Participant {idx} is marked 'certified' but has no training entries.",
                    fix="Either mark 'certified=false' or add training[].",
                    severity="warning",
                    ref="participant:certified-without-training",
                )
            )
            ctx.warnings += 1

    # --- animals totals vs experiments sums ---
    totals = instance.get("animals_total") or []
    exps = instance.get("experiments") or []

    # Per-experiment signals for downstream analysis (feature layer).
    exp_signals: List[Dict[str, Any]] = []
    for idx, e in enumerate(exps, start=1):
        sev = e.get("severity_level_1_to_5")
        eu = e.get("euthanasia") or {}
        animals = e.get("animals") or {}
        species_key = _canonical_species_key(animals)
        method_key = _canonical_method_key(eu)
        exp_signals.append(
            {
                "index": idx,
                "label": e.get("label") or "",
                "severity": sev,
                "has_analgesia": False,
                "has_anesthesia": bool(_anesthesia_rows(e)),
                "has_humane_endpoints": False,
                "humane_endpoints_20_percent_only": False,
                "euthanasia_primary": eu.get("method_standard") or eu.get("primary") or "",
                "pain_category": _pain_category(e),
                "species_normalized": species_key,
                "avma_status": (
                    check_method_for_species(
                        species_key,
                        method_key,
                    ).get("status")
                    if species_key and method_key
                    else None
                ),
                "specialty_flags": {
                    "stereotaxic_context": False,
                    "oncology_context": False,
                    "diabetes_context": False,
                    "biosafety_context": False,
                    "nanomaterials_context": False,
                    "ocular_context": False,
                },
            }
        )

    # Build sums from experiments
    exp_sums: Dict[Tuple[str, str, str, str], int] = {}
    for e in exps:
        a = e.get("animals") or {}
        key = (
            a.get("species"),
            a.get("strain"),
            a.get("sex"),
            a.get("genetic_status"),
        )
        if any(k is None for k in key):
            continue
        n = int(a.get("n") or 0)
        exp_sums[key] = exp_sums.get(key, 0) + n

    mismatch_details: List[str] = []
    total_n_all = sum(int(t.get("n_total") or 0) for t in totals)
    ctx.exps, ctx.totals, ctx.exp_signals, ctx.total_n_all = exps, totals, exp_signals, total_n_all
    
    # Check if totals are simplified (missing strain/genetics, or combined
    # multi-strain totals that can't match individual experiment strains)
    is_simplified_total = any(
        (not t.get("strain") and not t.get("genetic_status"))
        or ("," in (t.get("strain") or ""))
        for t in totals
    )

    if is_simplified_total and totals:
        # Validate by species sum only
        total_by_species: Dict[str, int] = {}
        for t in totals:
            s = (t.get("species") or "").strip()
            n = int(t.get("n_total") or 0)
            total_by_species[s] = total_by_species.get(s, 0) + n
            
        exp_by_species: Dict[str, int] = {}
        for (sp, _, _, _), n in exp_sums.items():
            sp_str = (sp or "").strip()
            exp_by_species[sp_str] = exp_by_species.get(sp_str, 0) + n
            
        # Compare
        all_species = set(total_by_species.keys()) | set(exp_by_species.keys())
        for sp in all_species:
            tot_n = total_by_species.get(sp, 0)
            exp_n = exp_by_species.get(sp, 0)
            if tot_n != exp_n:
                mismatch_details.append(f"Species '{sp}': totals={tot_n}, experiments={exp_n}")
    else:
        # Strict validation
        for t in totals:
            key = (
                t.get("species"),
                t.get("strain"),
                t.get("sex"),
                t.get("genetic_status"),
            )
            total_n = int(t.get("n_total") or 0)
            exp_n = exp_sums.get(key, 0)
            if total_n != exp_n:
                 mismatch_details.append(f"{key}: totals={total_n}, experiments={exp_n}")

    if totals:
        ok_totals = len(mismatch_details) == 0
        fix_totals = (
            "Adjust animals_total[].n_total or per-experiment animals.n so that totals "
            "equal the sum per species (if simplified) or per detailed subgroup."
        )
        ctx.checks.append(
            _rule(
                ok_totals,
                "Animals totals match the sum over experiments.",
                "Animals totals mismatch: " + "; ".join(mismatch_details),
                fix=fix_totals,
                ref="animals:totals-vs-exps",
            )
        )
        if not ok_totals:
            ctx.errors += 1

    # --- pilot scope heuristic (soft) ---
    research = instance.get("research") or {}
    req_type = research.get("request_type")
    is_pilot = req_type == "pilot"
    if is_pilot and totals:
        # Heuristic only: very large N or many experiments in a pilot may indicate over-scoping.
        over_n = total_n_all > 500
        many_exps = len(exps) > 5
        if over_n or many_exps:
            fix_scope = (
                "Pilot requests are expected to be short and small-N. "
                "Consider staging feasibility in a smaller protocol or using 'regular/continuation' track."
            )
            ctx.checks.append(
                _rule(
                    False,
                    "",
                    f"Pilot request looks large (total N={total_n_all}, experiments={len(exps)}); "
                    "committee may expect a staged or regular-track design.",
                    fix=fix_scope,
                    severity="warning",
                    ref="scope:pilot-size",
                )
            )
            ctx.warnings += 1

    # --- single-sex justification heuristic (soft) ---
    sexes_seen: set = set()
    for e in exps:
        a = e.get("animals") or {}
        sex = a.get("sex")
        if isinstance(sex, str) and sex:
            sexes_seen.add(sex)
    if sexes_seen in ({"M"}, {"F"}):
        has_sex_just = False
        sex_keywords = [
            "sex",
            "זוויג",
            "זכרים",
            "נקבות",
            "male",
            "female",
            "males",
            "females",
        ]
        for e in exps:
            rationale = (e.get("rationale_species_strain_sex") or "").lower()
            if any(k in rationale for k in sex_keywords):
                has_sex_just = True
                break
        if not has_sex_just:
            fix_sex = (
                "All experiments use a single sex; add an explicit justification in "
                "rationale_species_strain_sex explaining why only this sex is used "
                "and how this reduces total animal use."
            )
            ctx.checks.append(
                _rule(
                    False,
                    "",
                    "All experiments use a single sex but no explicit sex-selection justification was found.",
                    fix=fix_sex,
                    severity="warning",
                    ref="sex:rationale",
                )
            )
            ctx.warnings += 1

        full_rationale = " ".join(
            (e.get("rationale_species_strain_sex") or "").strip() for e in exps
        ).lower()
        sabv_scientific_keywords = [
            "sex as a biological variable",
            "biological variable",
            "sex-specific",
            "estrous",
            "oestrous",
            "horm",
            "ovar",
            "testis",
            "pregnan",
            "prostate",
            "ovarian",
            "uter",
            "זוויג",
            "זכרים",
            "נקבות",
        ]
        sabv_convenience_keywords = [
            "convenien",
            "availability",
            "avoid variability",
            "less variable",
            "reduce variability",
            "easier",
            "easier handling",
            "זמינות",
            "נוחות",
            "להפחית שונות",
            "פחות שונות",
            "קל יותר",
        ]
        has_sabv_scientific_basis = any(
            kw in full_rationale for kw in sabv_scientific_keywords
        )
        sabv_convenience_only = any(
            kw in full_rationale for kw in sabv_convenience_keywords
        )
        if not full_rationale or sabv_convenience_only or not has_sabv_scientific_basis:
            ctx.checks.append(
                _rule(
                    False,
                    "",
                    "Single-sex design lacks a clear scientific Sex as a Biological Variable rationale.",
                    fix=(
                        "Explain why a single-sex design is scientifically necessary and why "
                        "sex was considered as a biological variable, not only for convenience."
                    ),
                    severity="warning",
                    ref="sex:sabv",
                )
            )
            ctx.warnings += 1

    # --- large-N justification heuristic (soft) ---
    n_just = instance.get("n_justification") or {}
    details_text = (n_just.get("details") or "").strip()
    if total_n_all >= 500 and len(details_text) < 80:
        fix_n = (
            "For large total N, expand n_justification.details with numeric reasoning "
            "(group sizes, endpoints, expected attrition) rather than a brief statement."
        )
        ctx.checks.append(
            _rule(
                False,
                "",
                f"Large overall N ({total_n_all}) with very short n_justification.details.",
                fix=fix_n,
                severity="warning",
                ref="N:justification-detail",
            )
        )
        ctx.warnings += 1

    # --- power analysis method check (advisory) ---
    # Israeli law §8(b): minimal number required. PHS Policy IV.C.1.a: appropriateness of numbers.
    # For non-pilot, non-trivial N, a power analysis or reference to prior work is expected.
    request_type = (instance.get("research") or {}).get("request_type") or ""
    n_method = (n_just.get("method") or "").lower()
    non_pilot = request_type not in ("pilot",)
    # Only flag when: non-pilot track + total N >50 + method is not power/pilot/precedent
    adequate_method_keywords = ["power", "pilot", "prior", "precedent", "published", "literature", "previous"]
    has_adequate_method = any(kw in n_method for kw in adequate_method_keywords) or \
                          any(kw in details_text.lower() for kw in adequate_method_keywords)
    if non_pilot and total_n_all > 50 and not has_adequate_method:
        ctx.checks.append(
            _rule(
                False,
                "",
                f"N={total_n_all} on a non-pilot track without power analysis or reference to "
                "pilot/published precedent in n_justification.",
                fix=(
                    "Provide a formal power analysis (α, 1-β, effect size, group sizes) "
                    "or cite comparable published work justifying this sample size."
                ),
                severity="warning",
                ref="N:power-analysis",
            )
        )
        ctx.warnings += 1

    # --- euthanasia rules ---
    for idx, e in enumerate(exps, start=1):
        eu = e.get("euthanasia") or {}
        primary = eu.get("primary") or ""
        method_key = _canonical_method_key(eu)
        params = _euthanasia_conditions_text(eu)
        confirmation = eu.get("confirmation") or ""

        # Relaxed CO2 Check
        if method_key == "CO2":
            # For Council exports, "CO2" often appears alone.
            # If no parameters/confirmation, we warn but do not fail, assuming implicit SOP compliance.
            has_confirm = bool(confirmation)

            # Check for anesthesia in other fields if confirmation missing
            timeline_txt = " ".join((step.get("step") or "") for step in e.get("procedure_timeline") or [])
            anest_txt = _anesthesia_text(e)

            if not has_confirm:
                if "isoflurane" in anest_txt.lower() or "anesthe" in timeline_txt.lower() or "ketamine" in anest_txt.lower() or "xylazine" in anest_txt.lower():
                    has_confirm = True  # Implicitly confirmed via anesthesia protocols

            if not has_confirm:
                ctx.checks.append(
                    _rule(
                        False,
                        "",
                        f"Experiment {idx}: CO₂ euthanasia missing explicit confirmation step.",
                        fix="Specify confirmation method (e.g. cervical dislocation, thoracotomy).",
                        severity="error" if profile == "strict_law" else "warning",
                        ref=f"euthanasia:CO2:exp-{idx}",
                    )
                )
                if profile == "strict_law":
                    ctx.errors += 1
                else:
                    ctx.warnings += 1

        if method_key == "inhalant_overdose":
            ok_overdose = bool(confirmation)
            ctx.checks.append(
                _rule(
                    ok_overdose,
                    f"Experiment {idx}: inhalant overdose has confirmation step.",
                    f"Experiment {idx}: inhalant overdose missing confirmation step.",
                    fix="Add a confirmation method (thoracotomy, exsanguination, etc.).",
                    ref=f"euthanasia:overdose-confirm:exp-{idx}",
                )
            )
            if not ok_overdose:
                ctx.errors += 1

    # --- neonatal CO₂ check (law-critical) ---
    # AVMA 2020: CO₂ requires 50-min exposure for mice/rats on day of birth, or a
    # secondary physical method. NRC Guide standards have legal force via Council Rules §4-5.
    # Substring-safe keywords (e.g. "neonat" is safe — always indicates neonatal).
    # Short/ambiguous keywords use regex word boundaries to avoid false matches
    # like "day 1" matching "day 14" or "pup" matching "popup".
    _neonatal_substring_kws = ["neonat", "postnatal", "post-natal", "newborn", "new-born"]
    _neonatal_regex_kws = re.compile(
        r"\b(?:pups?|p[0-3]|day [0-3])\b", re.IGNORECASE
    )
    secondary_keywords = ["secondary", "decapitat", "cervical", "thoracotomy", "exsanguination",
                          "physical", "50 min", "50-min", "50min"]
    for idx, e in enumerate(exps, start=1):
        eu = e.get("euthanasia") or {}
        method_key = _canonical_method_key(eu)
        if method_key != "CO2":
            continue
        label = (e.get("label") or "") + " " + (e.get("question") or "")
        timeline_txt = " ".join(
            (step.get("step") or "") for step in e.get("procedure_timeline") or []
        )
        confirmation_txt = (eu.get("confirmation") or "") + " " + _euthanasia_conditions_text(eu)
        all_text = (label + " " + timeline_txt + " " + confirmation_txt).lower()
        is_neonatal = (
            any(kw in all_text for kw in _neonatal_substring_kws)
            or bool(_neonatal_regex_kws.search(all_text))
        )
        if not is_neonatal:
            continue
        has_secondary = any(kw in all_text for kw in secondary_keywords)
        if not has_secondary:
            ctx.checks.append(
                _rule(
                    False,
                    "",
                    f"Experiment {idx}: CO₂ euthanasia in neonatal animals requires extended "
                    "exposure (≥50 min for mice/rats at birth) or a secondary physical method.",
                    fix=(
                        "Add a secondary physical method (e.g. decapitation, cervical dislocation) "
                        "or document the extended 50-minute CO₂ exposure protocol per AVMA 2020."
                    ),
                    severity="error" if profile == "strict_law" else "warning",
                    ref=f"special:neonatal-CO2:exp-{idx}",
                )
            )
            if profile == "strict_law":
                ctx.errors += 1
            else:
                ctx.warnings += 1

    # --- AVMA species-euthanasia matrix rules ---
    # Cross-reference declared species × euthanasia method against AVMA 2020 matrix.
    # These rules are the highest-value single addition (email 07 Q1.4).
    for idx, e in enumerate(exps, start=1):
        animals = e.get("animals") or {}
        eu = e.get("euthanasia") or {}

        raw_species = animals.get("species") or ""
        raw_method = eu.get("method_standard") or eu.get("primary") or ""
        params = _euthanasia_conditions_text(eu)
        confirmation = eu.get("confirmation") or ""

        species_key = _canonical_species_key(animals)
        method_key = _canonical_method_key(eu)

        # Skip if species or method can't be resolved (separate structural issue)
        if not species_key or not method_key:
            continue

        avma_result = check_method_for_species(species_key, method_key)

        # Rule: euthanasia:species-method — UNACCEPTABLE method for species
        # Error in BOTH profiles (absolute prohibition).
        if avma_result["status"] == "unacceptable":
            ctx.checks.append(
                _rule(
                    False,
                    "",
                    f"Experiment {idx}: '{raw_method}' is UNACCEPTABLE for {raw_species} "
                    "per AVMA 2020 Guidelines.",
                    fix=(
                        f"Use an acceptable euthanasia method for {raw_species}. "
                        "See AVMA Guidelines for the Euthanasia of Animals (2020)."
                    ),
                    severity="error",
                    ref=f"euthanasia:species-method:exp-{idx}",
                )
            )
            ctx.errors += 1

        # Rule: euthanasia:precharged-chamber — pre-charged CO₂ chamber detection
        # Error in BOTH profiles (universal prohibition AVMA M3.2).
        all_eu_text = (raw_method + " " + params + " " + confirmation).lower()
        timeline_txt = " ".join(
            (s.get("step") or "") for s in e.get("procedure_timeline") or []
        ).lower()
        precharged_keywords = [
            "pre-charged", "precharged", "pre charged", "prefilled",
            "pre-filled", "pre filled",
        ]
        if any(kw in all_eu_text or kw in timeline_txt for kw in precharged_keywords):
            ctx.checks.append(
                _rule(
                    False,
                    "",
                    f"Experiment {idx}: Pre-charged CO₂ chamber is unacceptable for "
                    "all species (AVMA 2020 M3.2).",
                    fix="Use gradual-fill CO₂ displacement method instead of pre-charged chamber.",
                    severity="error",
                    ref=f"euthanasia:precharged-chamber:exp-{idx}",
                )
            )
            ctx.errors += 1

        # Rule: euthanasia:displacement-rate — CO₂ without displacement rate
        if method_key == "CO2":
            rate_range = get_displacement_rate_range(species_key)
            if rate_range:
                # Look for any number + % pattern, or displacement-related keywords
                rate_pattern = re.search(r"\d+[\s\-–]*(to|-)?\s*\d*\s*%", params.lower())
                displacement_mentioned = "displacement" in params.lower() or "vol/min" in params.lower()
                has_rate = bool(rate_pattern) or displacement_mentioned
                if not has_rate:
                    ctx.checks.append(
                        _rule(
                            False,
                            "",
                            f"Experiment {idx}: CO₂ euthanasia for {raw_species} requires "
                            f"displacement rate ({rate_range[0]}–{rate_range[1]}% chamber "
                            "vol/min) per AVMA 2020.",
                            fix=(
                                f"Specify CO₂ displacement rate "
                                f"({rate_range[0]}–{rate_range[1]}% chamber volume/min)."
                            ),
                            severity="error" if profile == "strict_law" else "warning",
                            ref=f"euthanasia:displacement-rate:exp-{idx}",
                        )
                    )
                    if profile == "strict_law":
                        ctx.errors += 1
                    else:
                        ctx.warnings += 1

        # Rule: euthanasia:secondary-method — CO₂/inhalant without physical secondary
        if method_key in ("CO2", "inhalant_overdose"):
            physical_kws = [
                "cervical", "decapitat", "thoracotomy", "exsanguination",
                "bilateral thoracotomy",
            ]
            confirm_text = (confirmation + " " + params).lower()
            has_physical = any(kw in confirm_text for kw in physical_kws)
            if not has_physical:
                ctx.checks.append(
                    _rule(
                        False,
                        "",
                        f"Experiment {idx}: {raw_method} euthanasia requires a secondary "
                        "physical death confirmation method (AVMA 2020).",
                        fix=(
                            "Specify a physical secondary method: cervical dislocation, "
                            "thoracotomy, exsanguination, or decapitation."
                        ),
                        severity="error" if profile == "strict_law" else "warning",
                        ref=f"euthanasia:secondary-method:exp-{idx}",
                    )
                )
                if profile == "strict_law":
                    ctx.errors += 1
                else:
                    ctx.warnings += 1

        # Rule: euthanasia:cervical-weight — cervical dislocation exceeding weight limit
        if method_key == "cervical_dislocation":
            max_wt = avma_result.get("max_weight_g")
            if max_wt is not None:
                weight_obj = animals.get("weight") or {}
                wt_val = weight_obj.get("value")
                wt_unit = (weight_obj.get("unit") or "g").lower()
                if wt_val is not None:
                    wt_g = wt_val if wt_unit == "g" else wt_val * 1000
                    if wt_g > max_wt:
                        ctx.checks.append(
                            _rule(
                                False,
                                "",
                                f"Experiment {idx}: Cervical dislocation is not acceptable "
                                f"for {raw_species} >{max_wt}g (AVMA 2020). "
                                f"Declared weight: {wt_val}{wt_unit}.",
                                fix=(
                                    f"Use an alternative euthanasia method for "
                                    f"{raw_species} exceeding {max_wt}g."
                                ),
                                severity="error" if profile == "strict_law" else "warning",
                                ref=f"euthanasia:cervical-weight:exp-{idx}",
                            )
                        )
                        if profile == "strict_law":
                            ctx.errors += 1
                        else:
                            ctx.warnings += 1
                else:
                    # Weight not specified but species has a limit — flag it
                    ctx.checks.append(
                        _rule(
                            False,
                            "",
                            f"Experiment {idx}: Cervical dislocation for {raw_species} "
                            f"requires weight ≤{max_wt}g but weight is not specified.",
                            fix=(
                                f"Specify animal weight to confirm eligibility for "
                                f"cervical dislocation (AVMA limit: {max_wt}g for {raw_species})."
                            ),
                            severity="error" if profile == "strict_law" else "warning",
                            ref=f"euthanasia:cervical-weight:exp-{idx}",
                        )
                    )
                    if profile == "strict_law":
                        ctx.errors += 1
                    else:
                        ctx.warnings += 1

        # Rule: euthanasia:conditions-missing — conditionally acceptable without documentation
        if avma_result["status"] == "conditionally_acceptable":
            conditions = avma_result.get("conditions") or []
            # Skip conditions already checked by more specific rules above
            # (displacement rate, secondary method, weight limit)
            remaining_conditions = [
                c for c in conditions
                if not any(skip in c.lower() for skip in [
                    "displacement", "secondary", "weight",
                ])
            ]
            if remaining_conditions:
                # Check if any condition-related documentation exists
                all_text = (
                    params + " " + confirmation + " " +
                    " ".join(
                        (s.get("step") or "") for s in e.get("procedure_timeline") or []
                    )
                ).lower()
                condition_kws = ["trained", "justified", "anesthesia", "anesthe", "sedat"]
                has_documentation = any(kw in all_text for kw in condition_kws)
                if not has_documentation:
                    ctx.checks.append(
                        _rule(
                            False,
                            "",
                            f"Experiment {idx}: '{raw_method}' is conditionally acceptable "
                            f"for {raw_species} but required conditions are not documented.",
                            fix=(
                                "Document the required conditions: "
                                + "; ".join(remaining_conditions)
                            ),
                            severity="error" if profile == "strict_law" else "warning",
                            ref=f"euthanasia:conditions-missing:exp-{idx}",
                        )
                    )
                    if profile == "strict_law":
                        ctx.errors += 1
                    else:
                        ctx.warnings += 1

    # --- severity vs monitoring ---
    for idx, e in enumerate(exps, start=1):
        sev = e.get("severity_level_1_to_5")
        mon = e.get("monitoring") or {}
        if isinstance(sev, int) and sev >= 4:
            # Relaxed: check boolean OR check if text description is substantive
            daily_flag = bool(mon.get("initial_72h_daily"))
            param_text = " ".join(mon.get("parameters") or [])

            # Heuristic: if text contains "daily", "every day", "24h", "72h" or is long enough (>50 chars)
            text_ok = len(param_text) > 50 or any(w in param_text.lower() for w in ["daily", "every day", "24", "72"])

            ok_mon = daily_flag or text_ok

            fix_mon = (
                "For severity ≥4, monitoring must be daily during the first 72h and at "
                "least once per week afterwards."
            )
            ctx.checks.append(
                _rule(
                    ok_mon,
                    f"Experiment {idx}: severity≥4 has adequate monitoring.",
                    f"Experiment {idx}: severity≥4 lacks daily 72h or sufficient weekly monitoring.",
                    fix=fix_mon,
                    ref=f"severity:monitoring:exp-{idx}",
                )
            )
            if not ok_mon:
                ctx.errors += 1

    # --- analgesia presence for invasive, moderate-severity work (soft) ---
    invasive_keywords = [
        "surgery",
        "operation",
        "incision",
        "crush",
        "optic nerve",
        "flap",
        "wound",
        "craniotomy",
        "laparotomy",
        "stereotax",
        "implant",
    ]
    ctx.invasive_keywords = invasive_keywords
    for idx, e in enumerate(exps, start=1):
        sev = e.get("severity_level_1_to_5")
        if not isinstance(sev, int) or sev < 3:
            continue
        label = (e.get("label") or "") + " " + (e.get("question") or "")
        timeline_txt = " ".join(
            (step.get("step") or "") for step in e.get("procedure_timeline") or []
        )
        joined = (label + " " + timeline_txt).lower()
        invasive = any(k in joined for k in invasive_keywords)
        if not invasive:
            continue
        analgesia_rows = e.get("analgesia") or []
        has_analgesia = any((row.get("agent") or "").strip() for row in analgesia_rows)
        # Feature signal: record analgesia presence per experiment.
        if 1 <= idx <= len(exp_signals):
            exp_signals[idx - 1]["has_analgesia"] = has_analgesia
        if not has_analgesia:
            fix_an = (
                "Add peri- and post-operative analgesia (agent, dose, route, frequency) "
                "for invasive, severity≥3 procedures, or document a strong justification "
                "for omitting analgesics (especially for severity grades 4–5)."
            )
            sev_msg = (
                f"Experiment {idx}: severity≥3 with invasive steps but no analgesia entries."
            )
            # Israeli law §1 Schedule: experiments causing pain must use anesthesia/analgesia.
            # §23: criminal penalties for non-compliance. Error in both profiles.
            ctx.checks.append(
                _rule(
                    False,
                    "",
                    sev_msg,
                    fix=fix_an,
                    severity="error",
                    ref=f"severity:analgesia:exp-{idx}",
                )
            )
            ctx.errors += 1

    # --- paralytic agents without concurrent anesthesia (law-critical) ---
    paralytic_keywords = [
        "vecuronium",
        "rocuronium",
        "pancuronium",
        "cisatracurium",
        "atracurium",
        "succinylcholine",
        "neuromuscular blocker",
        "paraly",
        "muscle relaxant",
    ]
    anesthesia_keywords = [
        "isoflurane",
        "sevoflurane",
        "ketamine",
        "xylazine",
        "propofol",
        "pentobarbital",
        "anesthe",
        "general anesthesia",
        "general anaesthesia",
    ]
    for idx, e in enumerate(exps, start=1):
        timeline_txt = " ".join(
            (step.get("step") or "") for step in e.get("procedure_timeline") or []
        ).lower()
        anesthesia_txt = _anesthesia_text(e)
        joined = " ".join(
            [
                (e.get("label") or "").lower(),
                (e.get("question") or "").lower(),
                timeline_txt,
                anesthesia_txt,
            ]
        )
        has_paralytic = any(kw in joined for kw in paralytic_keywords)
        if not has_paralytic:
            continue
        has_general_anesthesia = any(
            kw in anesthesia_txt or kw in timeline_txt for kw in anesthesia_keywords
        )
        if not has_general_anesthesia:
            ctx.checks.append(
                _rule(
                    False,
                    "",
                    f"Experiment {idx}: paralytic agent detected without documented concurrent general anesthesia.",
                    fix=(
                        "Document the concurrent general anesthetic agent, dose, route, and monitoring "
                        "plan whenever paralytic or neuromuscular-blocking agents are used."
                    ),
                    severity="error" if profile == "strict_law" else "warning",
                    ref=f"paralytic:without-anesthesia:exp-{idx}",
                )
            )
            if profile == "strict_law":
                ctx.errors += 1
            else:
                ctx.warnings += 1

    # --- pain/severity category consistency (law-critical) ---
    moderate_burden_keywords = invasive_keywords + [
        "fracture",
        "nerve crush",
        "tumor implant",
        "tumour implant",
        "xenograft",
        "restraint",
        "food deprivation",
        "water restriction",
    ]
    severe_burden_keywords = [
        "thoracotomy",
        "amputation",
        "spinal cord",
        "burn",
        "sepsis",
        "stroke",
        "neuropathic pain",
        "tumor burden",
        "ulceration",
        "death endpoint",
    ]
    for idx, e in enumerate(exps, start=1):
        sev = e.get("severity_level_1_to_5")
        joined = " ".join(
            [
                (e.get("label") or "").lower(),
                (e.get("question") or "").lower(),
                " ".join((step.get("step") or "") for step in e.get("procedure_timeline") or []).lower(),
            ]
        )
        has_moderate_burden = any(kw in joined for kw in moderate_burden_keywords)
        has_severe_burden = any(kw in joined for kw in severe_burden_keywords)
        pain_category = _pain_category(e)
        if pain_category:
            underclassified = (
                (pain_category in {"B", "C"} and (has_moderate_burden or has_severe_burden))
                or (pain_category == "D" and has_severe_burden)
            )
        else:
            if not isinstance(sev, int):
                continue
            underclassified = (
                (sev <= 2 and has_moderate_burden)
                or (sev <= 3 and has_severe_burden)
            )
        if not underclassified:
            continue
        ctx.checks.append(
            _rule(
                False,
                "",
                f"Experiment {idx}: declared severity/pain category appears too low for the described procedures.",
                fix=(
                    "Reassess pain_category and/or severity_level_1_to_5 and align them with the "
                    "actual procedure burden, monitoring plan, analgesia strategy, and humane endpoints."
                ),
                severity="error" if profile == "strict_law" else "warning",
                ref=f"pain:category-consistency:exp-{idx}",
            )
        )
        if profile == "strict_law":
            ctx.errors += 1
        else:
            ctx.warnings += 1

    # --- alternatives search content ---
    alts = instance.get("alternatives_search") or {}
    alts_engines = alts.get("engines") or []
    alts_queries = alts.get("queries") or []
    alts_conclusion = (alts.get("conclusion") or "").strip()

    # alts:missing — entire block absent or all three fields empty
    if not alts or (not alts_engines and not alts_queries and not alts_conclusion):
        ctx.checks.append(
            _rule(
                False,
                "",
                "Alternatives search section is missing or completely empty.",
                fix="Add alternatives_search with engines, queries, and conclusion.",
                severity="error" if profile == "strict_law" else "warning",
                ref="alts:missing",
            )
        )
        if profile == "strict_law":
            ctx.errors += 1
        else:
            ctx.warnings += 1
    else:
        # alts:engines — databases listed (law-critical: proves systematic search)
        if not alts_engines:
            ctx.checks.append(
                _rule(
                    False,
                    "",
                    "Alternatives search: engines[] is empty. List the databases searched (e.g. PubMed, Embase).",
                    fix="Add the names of databases consulted to alternatives_search.engines.",
                    severity="error" if profile == "strict_law" else "warning",
                    ref="alts:engines",
                )
            )
            if profile == "strict_law":
                ctx.errors += 1
            else:
                ctx.warnings += 1

        # alts:queries — at least one search query present
        # Standardized search systems (e.g. EU "Good Search Practice") have
        # built-in query workflows, so empty queries[] is expected.
        _STANDARDIZED_ENGINES = {"good search practice on animal alternative-eu"}
        _uses_standardized = any(
            e.strip().lower() in _STANDARDIZED_ENGINES for e in alts_engines
        )
        if not alts_queries and not _uses_standardized:
            ctx.checks.append(
                _rule(
                    False,
                    "",
                    "Alternatives search: queries[] is empty. Provide at least one search query used.",
                    fix="Add the search queries to alternatives_search.queries.",
                    severity="warning",
                    ref="alts:queries",
                )
            )
            ctx.warnings += 1

        # alts:conclusion — conclusion text present
        if not alts_conclusion:
            ctx.checks.append(
                _rule(
                    False,
                    "",
                    "Alternatives search: conclusion is empty. Summarize why no animal-free alternative exists.",
                    fix="Add a conclusion to alternatives_search.conclusion.",
                    severity="warning",
                    ref="alts:conclusion",
                )
            )
            ctx.warnings += 1

    # --- cosmetics / cleaning-products testing ban (law-critical) ---
    cosmetics_keywords = [
        "cosmetic",
        "cosmetics",
        "makeup",
        "mascara",
        "lipstick",
        "skin cream",
        "shampoo",
        "toothpaste",
        "household cleaner",
        "cleaning product",
        "cleaning products",
        "personal care product",
        "personal care products",
        "קוסמט",
        "איפור",
        "שמפו",
        "משחת שיניים",
        "חומרי ניקוי",
        "מוצרי ניקוי",
        "מוצרי קוסמטיקה",
    ]
    protocol_text = " ".join(
        [
            _flatten_text(instance.get("research")),
            _flatten_text(instance.get("summaries")),
            _flatten_text(instance.get("n_justification")),
            _flatten_text(instance.get("experiments")),
        ]
    ).lower()
    if any(kw in protocol_text for kw in cosmetics_keywords):
        ctx.checks.append(
            _rule(
                False,
                "",
                "Protocol appears to involve cosmetics or household cleaning-product testing, which is prohibited.",
                fix=(
                    "Remove cosmetics/cleaning-product animal testing aims or document that the "
                    "work is not product-safety testing in those banned categories."
                ),
                severity="error" if profile == "strict_law" else "warning",
                ref="cosmetics:ban",
            )
        )
        if profile == "strict_law":
            ctx.errors += 1
        else:
            ctx.warnings += 1

    # --- humane endpoints heuristics (soft) ---
    for idx, e in enumerate(exps, start=1):
        he = e.get("humane_endpoints") or {}
        texts = (he.get("general") or []) + (he.get("specific") or [])
        text = " ".join(texts).lower()
        has_text = bool(text)
        if 1 <= idx <= len(exp_signals):
            exp_signals[idx - 1]["has_humane_endpoints"] = has_text
        if not has_text:
            continue
        # Flag endpoints that rely only on "consult veterinarian" without concrete criteria.
        generic_consult = "consult" in text and ("vet" in text or "veterin" in text)
        has_quant = any(
            kw in text
            for kw in ["score", "tumor", "ulcer", "necros", "cm", "mm", "%", "scale"]
        )
        if generic_consult and not has_quant:
            fix_he = (
                "Replace generic 'consult veterinarian' endpoints with concrete, model-specific "
                "criteria (e.g. tumor size/ulceration, weight-loss thresholds, clinical scores)."
            )
            ctx.checks.append(
                _rule(
                    False,
                    "",
                    f"Experiment {idx}: humane endpoints rely on generic veterinarian consultation without concrete criteria.",
                    fix=fix_he,
                    severity="warning",
                    ref=f"endpoints:generic-consult:exp-{idx}",
                )
            )
            ctx.warnings += 1

        # Flag endpoints that only mention 20% weight loss without other model-specific indices.
        has_20 = "20%" in text or "20 percent" in text
        has_10 = "10%" in text or "10 percent" in text
        only_20 = has_20 and not has_10 and not any(
            kw in text for kw in ["tumor", "ulcer", "necros", "score", "scale"]
        )
        if 1 <= idx <= len(exp_signals):
            exp_signals[idx - 1]["humane_endpoints_20_percent_only"] = bool(only_20)
        if only_20:
            fix_w = (
                "Weight loss of 20% alone is not a sufficient humane endpoint. "
                "Add earlier and model-specific criteria (e.g. 10% weight loss plus tumor/wound/behavioral indices)."
            )
            ctx.checks.append(
                _rule(
                    False,
                    "",
                    f"Experiment {idx}: humane endpoints mention only 20% weight loss without model-specific criteria.",
                    fix=fix_w,
                    severity="error" if profile == "strict_law" else "warning",
                    ref=f"endpoints:20%-only:exp-{idx}",
                )
            )
            if profile == "strict_law":
                ctx.errors += 1
            else:
                ctx.warnings += 1

    # --- death-only endpoint check (law-critical) ---
    # Israeli law Schedule Item 3: euthanasia mandated for strong pain/suffering even if
    # objectives unmet; PHS Policy and Guide require humane endpoints "wherever possible".
    # Death or moribundity as the *sole* endpoint violates this requirement.
    death_keywords = ["death", "moribund", "moribundity", "dying", "lethal"]
    clinical_score_keywords = ["score", "scale", "weight", "%", "clinical", "behavior", "righting", "posture", "grooming"]
    for idx, e in enumerate(exps, start=1):
        he = e.get("humane_endpoints") or {}
        texts = (he.get("general") or []) + (he.get("specific") or [])
        text = " ".join(texts).lower()
        if not text:
            continue
        has_death_endpoint = any(kw in text for kw in death_keywords)
        has_other_criteria = any(kw in text for kw in clinical_score_keywords)
        if has_death_endpoint and not has_other_criteria:
            ctx.checks.append(
                _rule(
                    False,
                    "",
                    f"Experiment {idx}: death or moribundity is the only humane endpoint; "
                    "no earlier clinical scoring criteria specified.",
                    fix=(
                        "Add earlier, observable endpoints (clinical scoring scale, weight loss %, "
                        "behavioral indicators) per PHS Policy and Israeli law Schedule Item 3."
                    ),
                    severity="error" if profile == "strict_law" else "warning",
                    ref=f"endpoints:death-only:exp-{idx}",
                )
            )
            if profile == "strict_law":
                ctx.errors += 1
            else:
                ctx.warnings += 1

    # --- post-operative monitoring for survival surgeries (law-critical) ---
    # NRC Guide post-op standards have legal force in Israel via Council Rules §4-5.
    # 9 CFR 2.31(d)(1)(ix) and Guide require monitoring frequency, analgesic plan,
    # and vet consultation criteria for survival surgeries.
    survival_surgery_keywords = ["surgery", "operation", "incision", "laparotomy", "craniotomy",
                                  "implant", "flap", "laminectomy", "thoracotomy"]
    for idx, e in enumerate(exps, start=1):
        fate = (e.get("fate") or "").lower()
        if "euthanized" in fate or "euthanasia" in fate:
            continue  # Non-survival procedure — post-op monitoring requirement doesn't apply
        label = (e.get("label") or "") + " " + (e.get("question") or "")
        timeline_txt = " ".join(
            (step.get("step") or "") for step in e.get("procedure_timeline") or []
        )
        joined = (label + " " + timeline_txt).lower()
        has_surgery = any(kw in joined for kw in survival_surgery_keywords)
        if not has_surgery:
            continue
        mon = e.get("monitoring") or {}
        mon_text = (mon.get("plan") or "") + " ".join(mon.get("parameters") or [])
        has_postop = any(
            kw in mon_text.lower()
            for kw in ["post", "recover", "daily", "hour", "analges", "pain", "wound"]
        )
        if not has_postop:
            ctx.checks.append(
                _rule(
                    False,
                    "",
                    f"Experiment {idx}: survival surgery detected but no post-operative "
                    "monitoring plan specified.",
                    fix=(
                        "Document post-op monitoring: frequency, analgesic regimen, "
                        "wound-check schedule, and criteria for veterinary consultation."
                    ),
                    severity="error" if profile == "strict_law" else "warning",
                    ref=f"postop:monitoring:exp-{idx}",
                )
            )
            if profile == "strict_law":
                ctx.errors += 1
            else:
                ctx.warnings += 1

    # --- multiple survival experiments (advisory) ---
    # Israeli Rules §§6-7 prohibit reuse for cost savings; cumulative suffering must be
    # considered. Flag when more than one survival experiment exists on the same species.
    survival_exps_by_species: Dict[str, list] = {}
    for idx, e in enumerate(exps, start=1):
        fate = (e.get("fate") or "").lower()
        if "euthanized" in fate or "euthanasia" in fate:
            continue
        species = (e.get("animals") or {}).get("species") or "unknown"
        survival_exps_by_species.setdefault(species, []).append(idx)
    for species, exp_indices in survival_exps_by_species.items():
        if len(exp_indices) > 1:
            ctx.checks.append(
                _rule(
                    False,
                    "",
                    f"Multiple survival experiments on {species} (experiments {exp_indices}); "
                    "possible animal reuse — provide written scientific justification.",
                    fix=(
                        "If animals are reused across experiments, document scientific necessity. "
                        "Cost savings alone is insufficient justification (Israeli Rules §§6-7)."
                    ),
                    severity="warning",
                    ref="surgery:multiple-survival",
                )
            )
            ctx.warnings += 1

    # --- vet consultation for high-severity experiments (law-critical advisory) ---
    # Israeli Law §12(2): veterinary consultation required for severe procedures.
    # NRC Guide Ch. 4: anesthetic/analgesic plan requires veterinary input at severity ≥4.
    vet_keywords = ["vet", "veterinar", "dvm", "consultation"]
    for idx, e in enumerate(exps, start=1):
        sev = e.get("severity_level_1_to_5")
        if not isinstance(sev, int) or sev < 4:
            continue
        mon = e.get("monitoring") or {}
        mon_text = (mon.get("plan") or "") + " ".join(mon.get("parameters") or [])
        has_vet_consult = any(kw in mon_text.lower() for kw in vet_keywords)
        if not has_vet_consult:
            ctx.checks.append(
                _rule(
                    False,
                    "",
                    f"Experiment {idx}: severity {sev} procedures require documented veterinary "
                    "consultation on anesthetic/analgesic plan (Israeli Law §12(2); NRC Guide Ch. 4).",
                    fix=(
                        "Document veterinary consultation in monitoring.plan — include the consulting "
                        "veterinarian's role in reviewing the anesthetic/analgesic protocol."
                    ),
                    severity="warning",
                    ref=f"vet:consultation:exp-{idx}",
                )
            )
            ctx.warnings += 1

    # --- housing density and single housing justification (advisory) ---
    social_species = {
        "mouse",
        "rat",
        "guinea_pig",
        "rabbit",
        "hamster",
        "gerbil",
        "pig",
        "zebrafish",
    }
    for idx, e in enumerate(exps, start=1):
        animals = e.get("animals") or {}
        housing = e.get("housing") or {}
        density = e.get("housing_density") or {}
        species_key = _canonical_species_key(animals)
        weight_g = _animal_weight_grams(animals)

        threshold_cm2 = None
        threshold_note = ""
        if species_key == "mouse":
            if weight_g is not None and weight_g > 25:
                threshold_cm2 = 96.8
                threshold_note = "mouse >25g requires at least 96.8 cm2 per animal"
            else:
                # Conservative fallback: use smallest NRC Guide minimum (mouse ≤25g)
                threshold_cm2 = 77.4
                threshold_note = "mouse requires at least 77.4 cm2 per animal"
        elif species_key == "rat":
            if density.get("breeding_with_litter"):
                threshold_cm2 = 800.0
                threshold_note = "rat with litter requires at least 800 cm2 per enclosure"
            elif weight_g is not None and weight_g > 500:
                threshold_cm2 = 451.6
                threshold_note = "rat >500g requires at least 451.6 cm2 per animal"
            else:
                # Conservative fallback: use smallest NRC Guide minimum (rat <100g)
                threshold_cm2 = 109.7
                threshold_note = "rat requires at least 109.7 cm2 per animal"

        cage_floor_area_cm2 = _coerce_float(density.get("cage_floor_area_cm2"))
        animals_per_enclosure = _coerce_int(density.get("animals_per_enclosure"))
        if threshold_cm2 is not None and cage_floor_area_cm2 is not None and animals_per_enclosure:
            required_area = threshold_cm2
            if not density.get("breeding_with_litter"):
                required_area = threshold_cm2 * animals_per_enclosure
            if cage_floor_area_cm2 < required_area:
                ctx.checks.append(
                    _rule(
                        False,
                        "",
                        f"Experiment {idx}: housing density is below Guide minimums; "
                        f"declared {cage_floor_area_cm2:g} cm2 for {animals_per_enclosure} animals "
                        f"but {required_area:g} cm2 is required ({threshold_note}).",
                        fix=(
                            "Increase enclosure floor area or reduce the number of animals per enclosure. "
                            "Document cage-level housing density using housing_density."
                        ),
                        severity="warning",
                        ref=f"housing:density:exp-{idx}",
                    )
                )
                ctx.warnings += 1

        if (
            species_key in social_species
            and housing.get("group_housed") is False
            and not _nonempty(housing.get("single_housing_reason"))
        ):
            ctx.checks.append(
                _rule(
                    False,
                    "",
                    f"Experiment {idx}: {species_key} are typically socially housed but single housing "
                    "has no documented scientific or veterinary justification.",
                    fix=(
                        "Document the scientific or veterinary reason for single housing and, if relevant, "
                        "the expected duration in housing.single_housing_reason."
                    ),
                    severity="warning",
                    ref=f"housing:density:exp-{idx}",
                )
            )
            ctx.warnings += 1

    # --- restraint duration completeness (advisory) ---
    restraint_keywords = [
        "restraint",
        "restrain",
        "immobiliz",
        "jacket",
        "tether",
        "tube restraint",
        "head fixation",
        "head restraint",
    ]
    for idx, e in enumerate(exps, start=1):
        restraint = e.get("restraint") or {}
        timeline_txt = " ".join(
            (step.get("step") or "") for step in e.get("procedure_timeline") or []
        ).lower()
        joined = " ".join(
            [
                (e.get("label") or "").lower(),
                (e.get("question") or "").lower(),
                timeline_txt,
                _flatten_text(restraint).lower(),
            ]
        )
        has_restraint_context = restraint.get("used") is True or any(
            kw in joined for kw in restraint_keywords
        )
        if not has_restraint_context:
            continue

        missing_parts = []
        if _coerce_float(restraint.get("max_duration_minutes")) is None:
            missing_parts.append("maximum duration")
        if not _nonempty(restraint.get("acclimation")):
            missing_parts.append("acclimation procedure")
        if not _nonempty(restraint.get("humane_removal_criteria")):
            missing_parts.append("humane removal criteria")
        if not _nonempty(restraint.get("monitoring")):
            missing_parts.append("restraint monitoring plan")
        if missing_parts:
            ctx.checks.append(
                _rule(
                    False,
                    "",
                    f"Experiment {idx}: restraint is described but the protocol is missing "
                    f"{', '.join(missing_parts)}.",
                    fix=(
                        "Complete the restraint block with maximum duration, acclimation, monitoring, "
                        "and humane-removal criteria."
                    ),
                    severity="warning",
                    ref=f"restraint:duration:exp-{idx}",
                )
            )
            ctx.warnings += 1

        max_duration = _coerce_float(restraint.get("max_duration_minutes"))
        if max_duration is not None and max_duration > 15 and not _nonempty(restraint.get("justification")):
            ctx.checks.append(
                _rule(
                    False,
                    "",
                    f"Experiment {idx}: restraint exceeds 15 minutes but no justification is documented.",
                    fix=(
                        "Explain why prolonged restraint is necessary and how acclimation/monitoring "
                        "will reduce distress."
                    ),
                    severity="warning",
                    ref=f"restraint:duration:exp-{idx}",
                )
            )
            ctx.warnings += 1
        if max_duration is not None and max_duration > 360 and not _nonempty(restraint.get("food_water_plan")):
            ctx.checks.append(
                _rule(
                    False,
                    "",
                    f"Experiment {idx}: restraint exceeds 6 hours but no food/water management plan is documented.",
                    fix=(
                        "Document how animals will access food/water or why withholding it is scientifically "
                        "necessary during prolonged restraint."
                    ),
                    severity="warning",
                    ref=f"restraint:duration:exp-{idx}",
                )
            )
            ctx.warnings += 1

    # --- animal reuse justification (law-critical) ---
    allowed_prior_severity = {"mild", "moderate"}
    allowed_new_severity = {"mild", "moderate", "non_recovery"}
    for idx, e in enumerate(exps, start=1):
        prior = e.get("reuse_or_prior_procedures") or {}
        review = e.get("reuse_review") or {}
        has_reuse_context = bool(prior.get("has_prior")) or bool(review)
        if not has_reuse_context:
            continue

        missing_or_invalid = []
        prior_severity = (review.get("prior_severity") or "").strip()
        if prior_severity not in allowed_prior_severity:
            missing_or_invalid.append("prior severity limited to mild/moderate")
        if review.get("fully_recovered") is not True:
            missing_or_invalid.append("full recovery confirmation")
        new_severity = (review.get("new_procedure_severity") or "").strip()
        if new_severity not in allowed_new_severity:
            missing_or_invalid.append("new procedure severity limited to mild/moderate/non-recovery")
        if review.get("vet_consulted") is not True:
            missing_or_invalid.append("veterinarian consultation")
        if missing_or_invalid:
            ctx.checks.append(
                _rule(
                    False,
                    "",
                    f"Experiment {idx}: animal reuse is indicated but the protocol does not document "
                    f"{', '.join(missing_or_invalid)}.",
                    fix=(
                        "Complete the reuse_review block and document that prior procedures were mild/moderate, "
                        "the animal fully recovered, the new procedure is mild/moderate/non-recovery, "
                        "and a veterinarian reviewed the reuse decision."
                    ),
                    severity="error" if profile == "strict_law" else "warning",
                    ref=f"reuse:justification:exp-{idx}",
                )
            )
            if profile == "strict_law":
                ctx.errors += 1
            else:
                ctx.warnings += 1

    # --- field-study permits (law-critical) ---
    field_keywords = [
        "field study",
        "field work",
        "wildlife",
        "wild-caught",
        "animal trapping",
        "animal capture",
        "live trapping",
        "live capture",
        "capture permit",
        "free-ranging",
        "free ranging",
    ]
    pathogen_keywords = ["pathogen", "zoonotic", "rabies", "influenza", "salmonella"]
    for idx, e in enumerate(exps, start=1):
        permits = e.get("field_study_permits") or {}
        timeline_txt = " ".join(
            (step.get("step") or "") for step in e.get("procedure_timeline") or []
        ).lower()
        joined = " ".join(
            [
                (e.get("label") or "").lower(),
                (e.get("question") or "").lower(),
                timeline_txt,
                _flatten_text(permits).lower(),
            ]
        )
        has_field_context = (
            permits.get("field_study") is True
            or permits.get("wildlife") is True
            or any(kw in joined for kw in field_keywords)
        )
        if not has_field_context:
            continue

        missing_docs = []
        if not _nonempty(permits.get("collection_permit_ids")):
            missing_docs.append("collection permit identifiers")
        if permits.get("protected_species") is True and not _nonempty(permits.get("cites_documentation")):
            missing_docs.append("CITES/protected-species documentation")
        needs_biosafety = permits.get("wildlife_pathogen_handling") is True or (
            permits.get("wildlife") is True and any(kw in joined for kw in pathogen_keywords)
        )
        if needs_biosafety and not _nonempty(permits.get("biosafety_approval_id")):
            missing_docs.append("wildlife-pathogen biosafety approval")
        if not _nonempty(permits.get("field_euthanasia_method")):
            missing_docs.append("field euthanasia method")
        if missing_docs:
            ctx.checks.append(
                _rule(
                    False,
                    "",
                    f"Experiment {idx}: field or wildlife work is described but the protocol is missing "
                    f"{', '.join(missing_docs)}.",
                    fix=(
                        "Complete the field_study_permits block with collection permits, conditional CITES "
                        "or biosafety approvals, and the field euthanasia method/details."
                    ),
                    severity="error" if profile == "strict_law" else "warning",
                    ref=f"permits:field-study:exp-{idx}",
                )
            )
            if profile == "strict_law":
                ctx.errors += 1
            else:
                ctx.warnings += 1

    # --- food/water deprivation protocol (advisory) ---
    # NRC Guide p. 30: deprivation requires documented max duration, body-weight monitoring,
    # and intervention criteria. Body-weight checks are the primary welfare safeguard.
    deprivation_keywords = [
        "food deprivation", "water deprivation", "fasted", "fasting", "water restrict",
    ]
    weight_keywords = ["weight loss", "body weight", "intervention", "endpoint", "%"]
    for idx, e in enumerate(exps, start=1):
        timeline_txt = " ".join(
            (step.get("step") or "") for step in e.get("procedure_timeline") or []
        ).lower()
        has_deprivation = any(kw in timeline_txt for kw in deprivation_keywords)
        if not has_deprivation:
            continue
        mon = e.get("monitoring") or {}
        mon_text = ((mon.get("plan") or "") + " " + " ".join(mon.get("parameters") or [])).lower()
        has_weight_criterion = any(kw in mon_text for kw in weight_keywords)
        if not has_weight_criterion:
            ctx.checks.append(
                _rule(
                    False,
                    "",
                    f"Experiment {idx}: food/water deprivation detected but monitoring plan lacks "
                    "body-weight monitoring and intervention criteria.",
                    fix=(
                        "Document maximum deprivation duration, body-weight monitoring frequency, "
                        "and intervention thresholds (e.g. >15% weight loss triggers re-feeding) "
                        "per NRC Guide p. 30."
                    ),
                    severity="warning",
                    ref=f"deprivation:protocol:exp-{idx}",
                )
            )
            ctx.warnings += 1

    # --- genetically modified animals — IBC check (advisory) ---
    # NRC Guide; Israeli Rules §4: GM animals may require Institutional Biosafety Committee
    # approval and a phenotype monitoring plan for unexpected adverse phenotypes.
    gm_keywords = [
        "transgenic", "knockout", "ko", "crispr", "ge", "gene edit",
        "knock-in", "ki", "genetically modified", "gm",
    ]
    for idx, e in enumerate(exps, start=1):
        genetic_status = ((e.get("animals") or {}).get("genetic_status") or "").lower()
        is_gm = any(kw in genetic_status for kw in gm_keywords)
        if is_gm:
            ctx.checks.append(
                _rule(
                    False,
                    "",
                    f"Experiment {idx}: genetically modified animals ('{e['animals']['genetic_status']}') "
                    "may require IBC approval and a phenotype monitoring plan for unexpected adverse phenotypes.",
                    fix=(
                        "Verify IBC approval for the GM line and document a phenotype monitoring plan "
                        "per NRC Guide and Israeli Rules §4."
                    ),
                    severity="warning",
                    ref=f"gma:ibc:exp-{idx}",
                )
            )
            ctx.warnings += 1

    # --- ascites antibody production (advisory) ---
    # NRC 1999; OLAW guidance: ascites method requires documentation that in vitro
    # alternatives were attempted and failed before using mouse ascites.
    for idx, e in enumerate(exps, start=1):
        timeline_txt = " ".join(
            (step.get("step") or "") for step in e.get("procedure_timeline") or []
        ).lower()
        if "ascites" in timeline_txt:
            ctx.checks.append(
                _rule(
                    False,
                    "",
                    f"Experiment {idx}: ascites antibody production detected. Document that in vitro "
                    "alternatives were attempted and failed before using the mouse ascites method.",
                    fix=(
                        "Add documentation that in vitro hybridoma culture was attempted "
                        "and was insufficient for the required antibody quantity/quality "
                        "(NRC 1999; OLAW guidance)."
                    ),
                    severity="warning",
                    ref=f"ascites:in-vitro:exp-{idx}",
                )
            )
            ctx.warnings += 1

    colony.run_breeding_plan(ctx)

    # --- specialty triggers based on text patterns ---
    for idx, e in enumerate(exps, start=1):
        label = (e.get("label") or "") + " " + (e.get("question") or "")
        timeline_txt = " ".join(
            (step.get("step") or "") for step in e.get("procedure_timeline") or []
        )
        joined = (label + " " + timeline_txt).lower()

        # DBS / stereotaxic
        has_stereotaxic = any(
            k in joined
            for k in ["dbs", "stereotax", "stereotactic", "craniotomy", "headcap", "implant"]
        )
        if 1 <= idx <= len(exp_signals):
            exp_signals[idx - 1]["specialty_flags"]["stereotaxic_context"] = bool(
                has_stereotaxic
            )
        if has_stereotaxic:
            st = e.get("stereotaxic_implant") or {}
            # Warn only if missing
            ok_st = bool(st.get("implant_type") or st.get("craniotomy") is not None)
            severity = "warning" if not ok_st else "error"
            if not ok_st:
                 ctx.warnings += 1
            ctx.checks.append(
                _rule(
                    ok_st,
                    f"Experiment {idx}: stereotaxic/implant details present.",
                    f"Experiment {idx}: stereotaxic/DBS context but stereotaxic_implant block is incomplete.",
                    fix="Fill stereotaxic_implant block.",
                    severity=severity,
                    ref=f"special:stereotaxic:exp-{idx}",
                )
            )

        # Oncology / tumor
        has_onc = any(
            k in joined
            for k in [
                "tumor",
                "melanoma",
                "xenograft",
                "metastasis",
                "metastases",
                "muspelheim neoplasm",
                "alfheim neoplasm",
                "nidavellir tumor",
            ]
        )
        if 1 <= idx <= len(exp_signals):
            exp_signals[idx - 1]["specialty_flags"]["oncology_context"] = bool(has_onc)
        if has_onc:
            on = e.get("oncology") or {}
            ok_onc = bool(on.get("tumor_burden_cap")) and bool(on.get("ulceration_policy"))
            # Warn only
            severity = "warning" if not ok_onc else "error"
            if not ok_onc: ctx.warnings += 1
            ctx.checks.append(
                _rule(
                    ok_onc,
                    f"Experiment {idx}: oncology block has burden cap and ulceration policy.",
                    f"Experiment {idx}: tumor work requires tumor_burden_cap and ulceration_policy.",
                    fix="Fill oncology.tumor_burden_cap and ulceration_policy.",
                    severity=severity,
                    ref=f"special:oncology:exp-{idx}",
                )
            )

        # Diabetes
        has_db = any(
            k in joined
            for k in [
                "diabetes",
                "bg ",
                "blood glucose",
                "hyperglycemia",
                "jotunheim metabolic condition",
                "skadi-zotocin",
            ]
        )
        if 1 <= idx <= len(exp_signals):
            exp_signals[idx - 1]["specialty_flags"]["diabetes_context"] = bool(has_db)
        if has_db:
            db = e.get("diabetes") or {}
            ok_db = db.get("measurement") in ("fasted", "non_fasted")
            # Warn only
            severity = "warning" if not ok_db else "error"
            if not ok_db: ctx.warnings += 1
            ctx.checks.append(
                _rule(
                    ok_db,
                    f"Experiment {idx}: diabetes block has measurement mode.",
                    f"Experiment {idx}: diabetes context requires measurement mode and BG threshold.",
                    fix="Fill diabetes block.",
                    severity=severity,
                    ref=f"special:diabetes:exp-{idx}",
                )
            )

        # Biosafety / viruses
        has_bio = any(
            k in joined
            for k in [
                "virus",
                "viral",
                "reovirus",
                "lentivirus",
                "aav",
                "infectious",
                "niflheim-v7",
            ]
        )
        if 1 <= idx <= len(exp_signals):
            exp_signals[idx - 1]["specialty_flags"]["biosafety_context"] = bool(has_bio)
        if has_bio:
            bs = e.get("biosafety_infectious_agents") or {}
            ok_bs = bool(bs.get("agent_name"))
            # Warn only
            severity = "warning" if not ok_bs else "error"
            if not ok_bs: ctx.warnings += 1
            ctx.checks.append(
                _rule(
                    ok_bs,
                    f"Experiment {idx}: biosafety agent documented.",
                    f"Experiment {idx}: viral/infectious work requires biosafety metadata.",
                    fix="Fill biosafety_infectious_agents block.",
                    severity=severity,
                    ref=f"special:biosafety:exp-{idx}",
                )
            )

        # Nanomaterials / VOCs
        # Reduced triggers (removed 'nano-' to avoid 'nanodrop', kept 'nanoparticle')
        has_nano = any(
            k in joined
            for k in [
                "nanoparticle",
                "volatile organic compound",
                "rune-particle",
                "rune-particles",
                "norn-corona",
                "nano-ghost",
                "nano-ghosts",
            ]
        )
        if 1 <= idx <= len(exp_signals):
            exp_signals[idx - 1]["specialty_flags"]["nanomaterials_context"] = bool(has_nano)
        if has_nano:
            nm = e.get("nanomaterials") or {}
            ok_nm = bool(nm.get("particle_type"))
            # Warn only
            severity = "warning" if not ok_nm else "error"
            if not ok_nm: ctx.warnings += 1
            ctx.checks.append(
                _rule(
                    ok_nm,
                    f"Experiment {idx}: nanomaterials metadata present.",
                    f"Experiment {idx}: nanoparticle/VOC context requires nanomaterials block.",
                    fix="Fill nanomaterials block.",
                    severity=severity,
                    ref=f"special:nanomaterials:exp-{idx}",
                )
            )

        # Ocular / optic nerve
        # Reduced triggers (removed 'eye ')
        has_oc = any(
            k in joined
            for k in [
                "optic nerve",
                "bifrost nerve",
                "retina",
                "corneal",
                "ocular",
            ]
        )
        if 1 <= idx <= len(exp_signals):
            exp_signals[idx - 1]["specialty_flags"]["ocular_context"] = bool(has_oc)
        if has_oc:
            oc = e.get("ocular_procedures") or {}
            ok_oc = bool(oc.get("topical_anesthesia")) or bool(oc.get("ocular_lubrication"))
            # Warn only
            severity = "warning" if not ok_oc else "error"
            if not ok_oc: ctx.warnings += 1
            ctx.checks.append(
                _rule(
                    ok_oc,
                    f"Experiment {idx}: ocular procedures metadata present.",
                    f"Experiment {idx}: ocular/optic nerve work requires ocular_procedures block.",
                    fix="Fill ocular_procedures block.",
                    severity=severity,
                    ref=f"special:ocular:exp-{idx}",
                )
            )

    colony.run_no_invasive(ctx)

    summaries.run(ctx)

    status = "pass" if ctx.errors == 0 else "fail"

    # Feature extraction layer: high-level signals for LLM and dashboards.
    # These avoid re-walking the instance when building prompts or visualizations.
    sexes_seen: set = set()
    for e in exps:
        a = e.get("animals") or {}
        sex = a.get("sex")
        if isinstance(sex, str) and sex:
            sexes_seen.add(sex)

    alts = instance.get("alternatives_search") or {}
    engines = alts.get("engines") or []
    queries = alts.get("queries") or []
    conclusion = (alts.get("conclusion") or "").strip()

    single_sex_design = sexes_seen in ({"M"}, {"F"})
    analysis = {
        "summary": {
            "N_total_all_experiments": total_n_all,
            "num_experiments": len(exps),
            "sexes_seen": sorted(sexes_seen),
            "single_sex_design": single_sex_design,
            "is_colony": bool(instance.get("is_colony")),
        },
        "alternatives": {
            "present": bool(alts),
            "engines_count": len(engines),
            "queries_count": len(queries),
            "conclusion_length": len(conclusion),
        },
        "experiments": exp_signals,
    }

    # Summaries by category for downstream analysis (does not affect status).
    structural_errors = 0
    law_critical_errors = 0
    advisory_warnings = 0

    def ref_matches(ref: str, ref_set: set) -> bool:
        """Check if ref matches any pattern in ref_set (exact match or prefix before :exp-)."""
        if ref in ref_set:
            return True
        # Handle experiment-suffixed refs like "euthanasia:CO2:exp-1"
        if ":exp-" in ref:
            base_ref = ref.rsplit(":exp-", 1)[0]
            return base_ref in ref_set
        return False

    for c in ctx.checks:
        if c.get("status") != "fail":
            continue
        ref = c.get("reference") or ""
        sev = c.get("severity") or "error"
        if ref_matches(ref, STRUCTURAL_REFS) and sev == "error":
            structural_errors += 1
        elif ref_matches(ref, LAW_CRITICAL_REFS) and sev == "error":
            law_critical_errors += 1
        elif ref_matches(ref, ADVISORY_REFS) and sev != "error":
            advisory_warnings += 1

    report = {
        "status": status,
        "profile": profile,
        "errors": ctx.errors,
        "warnings": ctx.warnings,
        "structural_errors": structural_errors,
        "law_critical_errors": law_critical_errors,
        "advisory_warnings": advisory_warnings,
        "analysis": analysis,
        "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "checklist": ctx.checks,
    }
    return apply_pack(annotate_report(report))


def _row(cells: List[Any], even_idx: int = 0) -> str:
    tds = []
    for i, c in enumerate(cells):
        cls = ' class="even"' if i == even_idx else ""
        tds.append(f"<td{cls}>{_e(c)}</td>")
    return "<tr>" + "".join(tds) + "</tr>"

def render_html(instance: Dict[str, Any], out_html_path: str = None, with_refs: bool = False) -> str:
    """
    Render a schema instance to Council-style RTL HTML.

    If out_html_path is given, writes the file and returns the HTML string.
    If with_refs is True, adds data-ref attributes to major sections for error mapping.
    """
    header = instance.get("header") or {}
    research = instance.get("research") or {}
    pi = instance.get("pi") or {}
    participants = instance.get("participants") or []
    animals_total = instance.get("animals_total") or []
    n_just = instance.get("n_justification") or {}
    summaries = instance.get("summaries") or {}
    alts = instance.get("alternatives_search") or {}
    exps = instance.get("experiments") or []
    pm = instance.get("postmortem_processing") or {}
    pi_decl = instance.get("pi_declaration") or {}
    chair = instance.get("chair_statement") or {}

    def _ref(ref_name: str) -> str:
        """Return data-ref attribute if with_refs is True."""
        return f' data-ref="{ref_name}"' if with_refs else ""

    H: List[str] = []
    H.append('<html lang="he"><head><meta charset="utf-8"/>')
    H.append("<title>Experiment Request</title>")
    H.append(f"<style>{CSS}</style></head><body>")
    H.append("<div>")
    H.append(f'<div class="header"{_ref("header")}>')
    H.append(
        f'<div>בקשת ניסוי מס <span>{_e(header.get("protocol_id", ""))}</span></div><br/>'
    )
    H.append(
        f'<div>שם המוסד - <span>{_e(header.get("institution", ""))}</span></div>'
    )
    H.append("</div>")  # header

    H.append('<div class="content">')

    # --- Research section ---
    H.append(f'<div class="section"{_ref("research")}>')
    H.append('<div class="sub-header">המחקר</div>')
    H.append('<div class="table vertical"><table><tbody>')
    H.append(
        _row(
            [
                "נושא המחקר בעברית",
                research.get("title_he", ""),
            ]
        )
    )
    H.append(
        _row(
            [
                "נושא המחקר באנגלית",
                research.get("title_en", ""),
            ]
        )
    )
    H.append(
        _row(
            [
                "האם זה מחקר המשך?",
                "המשך" if research.get("is_continuation") else "חדש",
            ]
        )
    )
    if research.get("is_continuation"):
        H.append(
            _row(
                [
                    "סיבה למחקר המשך",
                    research.get("continuation_reason", ""),
                ]
            )
        )
        H.append(
            _row(
                [
                    "ציין את מס' הבקשה הקודם",
                    research.get("prior_protocol_id", ""),
                ]
            )
        )
    H.append(
        _row(
            [
                "המחקר הוא מחקר שרות עבור מוסד צד ג?",
                "כן" if research.get("third_party_service") else "לא",
            ]
        )
    )
    term = research.get("approval_term_years")
    if term == 1:
        term_str = "שנה"
    elif isinstance(term, int):
        term_str = f"{term} שנים"
    else:
        term_str = ""
    H.append(_row(["תוקף האישור המבוקש (שנים)", term_str]))
    H.append(
        _row(
            [
                "אתר ביצוע המחקר",
                ", ".join(s.get("name", "") for s in research.get("sites") or []),
            ]
        )
    )
    H.append("</tbody></table></div>")
    if research.get("primary_purpose") or research.get("secondary_purpose"):
        H.append('<div class="table vertical"><table><tbody>')
        if research.get("primary_purpose"):
            H.append(_row(["מטרה ראשית", research["primary_purpose"]]))
        if research.get("secondary_purpose"):
            H.append(_row(["מטרה משנית", research["secondary_purpose"]]))
        H.append("</tbody></table></div>")
    H.append("</div>")  # close research section
    H.append('<p style="page-break-after: always;"></p>')

    # --- PI section ---
    H.append(f'<div class="section"{_ref("pi")}>')
    H.append('<div class="sub-header">החוקר הראשי</div>')
    H.append('<div class="table vertical"><table><tbody>')
    H.append(
        "<tr>"
        f'<td class="even" style="width:20%">סוג זהוי</td>'
        f"<td>{_e('ת.ז.' if pi.get('id_type') == 'TZ' else 'דרכון')}</td>"
        f'<td class="even" style="width:20%">מספר זהוי</td>'
        f"<td>{_e(pi.get('id_number', ''))}</td>"
        "</tr>"
    )
    H.append(
        _row(
            [
                "שם משפחה בעברית",
                pi.get("last_name_he", ""),
                "שם פרטי בעברית",
                pi.get("first_name_he", ""),
            ]
        )
    )
    H.append(
        _row(
            [
                "שם משפחה באנגלית",
                pi.get("last_name_en", ""),
                "שם פרטי באנגלית",
                pi.get("first_name_en", ""),
            ]
        )
    )
    H.append(
        _row(
            [
                "שם המוסד",
                header.get("institution", ""),
                "",
                "",
            ]
        )
    )
    H.append(
        _row(
            [
                "תאריך לידה",
                "",
                "דואר אלקטרוני",
                pi.get("email", ""),
            ]
        )
    )
    H.append(
        _row(
            [
                "טלפון נייד",
                pi.get("phone_primary", ""),
                "טלפון נוסף",
                pi.get("phone_secondary", ""),
            ]
        )
    )
    H.append(
        _row(
            [
                "מס' הסמכה במוסד המחקר",
                pi.get("institutional_cert_no", ""),
                "תת ועדה",
                header.get("subcommittee", ""),
            ]
        )
    )
    H.append(
        _row(
            [
                "פקולטה",
                pi.get("faculty", ""),
                "מחלקה",
                pi.get("department", ""),
            ]
        )
    )
    H.append("</tbody></table></div>")

    # PI training
    if pi.get("training"):
        H.append('<div class="table-header">הכשרות החוקר</div>')
        H.append('<div class="table horizontal"><table><tbody>')
        H.append(
            "<tr>"
            "<th>מס' תעודה</th><th>מוסד נותן התעודה</th>"
            "<th>סוג בע\"ח</th><th>תאריך תעודה</th>"
            "</tr>"
        )
        for row in pi["training"]:
            H.append(
                _row(
                    [
                        row.get("cert_no", ""),
                        row.get("issuer", ""),
                        row.get("animal_scope", ""),
                        row.get("date", ""),
                    ],
                    even_idx=0,
                )
            )
        H.append("</tbody></table></div>")

    H.append("</div>")  # close PI section
    H.append('<p style="page-break-after: always;"></p>')

    # --- Participants ---
    if participants:
        H.append(f'<div class="section"{_ref("participants")}>')
        H.append('<div class="sub-header">משתתפים במחקר והכשרותיהם</div>')
        for idx, p in enumerate(participants, start=1):
            H.append(f'<div class="table-header">משתתף מס  {idx}:</div>')
            H.append('<div class="table horizontal"><table><tbody>')
            H.append(
                "<tr>"
                "<th>שם משפחה</th><th>שם פרטי</th>"
                "<th>מספר ת.ז / דרכון</th><th>קשר למחקר</th><th>מוסמך</th>"
                "</tr>"
            )
            role = p.get("role")
            if role == "performs_procedures":
                role_he = "עובד עם בעל חיים בניסוי"
            elif role == "participant":
                role_he = "משתתף בניסוי"
            elif role == "PI":
                role_he = "חוקר ראשי"
            else:
                role_he = role or ""
            H.append(
                _row(
                    [
                        p.get("family_name", ""),
                        p.get("given_name", ""),
                        p.get("national_id_or_passport", ""),
                        role_he,
                        "כן" if p.get("certified") else "לא",
                    ]
                )
            )
            H.append("</tbody></table></div>")
            if p.get("training"):
                H.append('<div class="table-header">הכשרות</div>')
                H.append('<div class="table horizontal"><table><tbody>')
                H.append(
                    "<tr>"
                    "<th>מס'</th><th>מס' תעודה</th><th>מוסד נותן תעודה</th><th>סוג בע\"ח</th>"
                    "</tr>"
                )
                for j, t in enumerate(p["training"], start=1):
                    H.append(
                        _row(
                            [
                                j,
                                t.get("cert_no", ""),
                                t.get("issuer", ""),
                                t.get("animal_scope", ""),
                            ]
                        )
                    )
                H.append("</tbody></table></div>")

        H.append("</div>")  # close participants section
        H.append('<p style="page-break-after: always;"></p>')

    # --- Animals totals ---
    if animals_total:
        H.append(f'<div class="section"{_ref("animals-totals")}>')
        H.append('<div class="sub-header">בעלי החיים הדרושים למחקר</div>')
        H.append('<div class="table horizontal"><table><tbody>')
        H.append(
            "<tr>"
            "<th>מין מובנה</th><th>מין</th><th>זן/קווים</th><th>סטטוס גנטי</th>"
            "<th>זוויג</th><th>גיל</th><th>כמות</th><th>מקור</th>"
            "</tr>"
        )
        for t in animals_total:
            H.append(
                _row(
                    [
                        t.get("species_standard", ""),
                        t.get("species", ""),
                        t.get("strain", ""),
                        t.get("genetic_status", ""),
                        t.get("sex", ""),
                        t.get("age", ""),
                        t.get("n_total", ""),
                        t.get("source", ""),
                    ]
                )
            )
        H.append("</tbody></table></div>")
        H.append("</div>")  # close animals-totals section

    # Justification and summaries
    H.append(f'<div class="section"{_ref("summaries")}>')
    H.append('<div class="sub-header">נימוק למספר בעלי החיים</div>')
    H.append(
        '<div class="table"><div>'
        f'{_e(n_just.get("method", ""))}: {_e(n_just.get("details", ""))}'
        "</div></div>"
    )

    H.append('<div class="sub-header">תקציר מדעי (EN)</div>')
    H.append(
        '<div class="table"><div>'
        f'{_e(summaries.get("scientific_en_≤300w", ""))}'
        "</div></div>"
    )

    H.append('<div class="sub-header">תקציר לקהל הרחב (HE)</div>')
    H.append(
        '<div class="table"><div>'
        f'{_e(summaries.get("lay_he_≤150w", ""))}'
        "</div></div>"
    )

    H.append("</div>")  # close summaries section

    # Alternatives
    if alts:
        H.append(f'<div class="section"{_ref("alternatives")}>')
        H.append('<div class="sub-header">חיפוש חלופות</div>')
        H.append(
            '<div class="table"><div>מנועים: '
            + _e(", ".join(alts.get("engines") or []))
            + "</div></div>"
        )
        H.append(
            '<div class="table"><div>תאריך: '
            + _e(alts.get("date", ""))
            + "</div></div>"
        )
        if alts.get("queries"):
            H.append(
                '<div class="table"><div>שאילתות: '
                + _e("; ".join(alts.get("queries") or []))
                + "</div></div>"
            )
        H.append(
            '<div class="table"><div>מסקנה: '
            + _e(alts.get("conclusion", ""))
            + "</div></div>"
        )
        prelim = alts.get("preliminary_experiments") or {}
        if prelim.get("had_alternative_methods") is not None or prelim.get("details"):
            H.append('<div class="sub-header">ניסויים מקדימים בשיטות חלופיות</div>')
            H.append('<div class="table"><div>')
            if prelim.get("had_alternative_methods") is not None:
                H.append(
                    f'האם היו שלבים בשיטות חלופיות: {"כן" if prelim["had_alternative_methods"] else "לא"}'
                )
            if prelim.get("details"):
                H.append(f'<br>{_e(prelim["details"])}')
            H.append("</div></div>")
        H.append("</div>")  # close alternatives section

    # --- Experiments ---
    for idx, e in enumerate(exps, start=1):
        H.append('<p style="page-break-after: always;"></p>')
        H.append(f'<div class="section experiment"{_ref(f"experiment-{idx}")}>')
        H.append(f'<div class="sub-header">ניסוי {idx}</div>')

        if e.get("question"):
            H.append(
                '<div class="table"><div class="table-header">'
                "שאלת המחקר הספציפית"
                "</div></div>"
            )
            H.append(
                '<div class="table"><div>'
                f'{_e(e["question"])}'
                "</div></div>"
            )

        # Animals table
        a = e.get("animals") or {}
        age = a.get("age") or {}
        age_str = f'{age.get("value", "")} {age.get("unit", "")}'.strip()
        H.append('<div class="table horizontal"><table><tbody>')
        H.append(
            "<tr>"
            "<th>מין מובנה</th><th>מין</th><th>זן/קווים</th><th>סטטוס גנטי</th>"
            "<th>זוויג</th><th>גיל</th><th>כמות</th><th>מקור</th>"
            "</tr>"
        )
        H.append(
            _row(
                [
                    a.get("species_standard", ""),
                    a.get("species", ""),
                    a.get("strain", ""),
                    a.get("genetic_status", ""),
                    a.get("sex", ""),
                    age_str,
                    a.get("n", ""),
                    a.get("source", ""),
                ]
            )
        )
        H.append("</tbody></table></div>")
        # Weight & supplier
        weight = a.get("weight") or {}
        supplier = a.get("supplier", "")
        if weight or supplier:
            parts = []
            if weight:
                parts.append(f'משקל: {weight.get("value", "")} {weight.get("unit", "")}')
            if supplier:
                parts.append(f'ספק: {_e(supplier)}')
            H.append(f'<div class="table"><div>{" | ".join(parts)}</div></div>')
        # Per-group breakdown
        if a.get("groups"):
            H.append('<div class="table horizontal"><table><tbody>')
            H.append(
                "<tr><th>קבוצה</th><th>זן</th><th>שינוי גנטי</th>"
                "<th>כמות</th><th>משקל</th><th>ספק</th></tr>"
            )
            for gi, g in enumerate(a["groups"], 1):
                gw = g.get("weight") or {}
                H.append(
                    _row([
                        gi,
                        g.get("strain", ""),
                        g.get("genetic_modification", ""),
                        g.get("n", ""),
                        f'{gw.get("value", "")} {gw.get("unit", "")}'.strip() if gw else "",
                        g.get("supplier", ""),
                    ])
                )
            H.append("</tbody></table></div>")

        # Housing
        h = e.get("housing") or {}
        H.append('<div class="table horizontal"><table><tbody>')
        H.append(
            "<tr>"
            "<th>שיכון</th><th>העשרה</th>"
            "<th>סיבת שיכון בודד</th><th>משך שיכון בודד (ימים)</th>"
            "</tr>"
        )
        H.append(
            _row(
                [
                    "קבוצתי" if h.get("group_housed") else "בודד",
                    h.get("enrichment", ""),
                    h.get("single_housing_reason", ""),
                    h.get("single_housing_duration_days", ""),
                ]
            )
        )
        H.append("</tbody></table></div>")

        # rationale & timeline
        H.append(
            '<div class="table"><div class="table-header">'
            "נימוק לבחירת מין/זן/זוויג"
            "</div></div>"
        )
        H.append(
            '<div class="table"><div>'
            f'{_e(e.get("rationale_species_strain_sex", ""))}'
            "</div></div>"
        )

        if e.get("n_justification_detail"):
            H.append(
                '<div class="table"><div class="table-header">'
                "נימוק למספר בעלי החיים בניסוי"
                "</div></div>"
            )
            H.append(
                '<div class="table"><div>'
                f'{_e(e["n_justification_detail"])}'
                "</div></div>"
            )

        if e.get("regulatory_requirement") is not None:
            H.append(
                '<div class="table"><div>'
                f'מחקר הנובע מצורך רגולטורי: {"כן" if e["regulatory_requirement"] else "לא"}'
                "</div></div>"
            )

        H.append(
            '<div class="table"><div class="table-header">'
            "תיאור הניסוי ולו\"ז"
            "</div></div>"
        )
        H.append('<div class="table horizontal"><table><tbody>')
        H.append(
            "<tr>"
            "<th>זמן/יום</th><th>שלב</th><th>מסלול/איבר</th>"
            "<th>נפח/מינון</th><th>מכשור/חומר</th>"
            "</tr>"
        )
        for step in e.get("procedure_timeline") or []:
            H.append(
                _row(
                    [
                        step.get("day_or_timepoint", ""),
                        step.get("step", ""),
                        step.get("route_or_site", ""),
                        step.get("volume_or_dose", ""),
                        step.get("device_or_material", ""),
                    ]
                )
            )
        H.append("</tbody></table></div>")

        # Analgesia
        if e.get("analgesia_used") is not None or e.get("analgesia"):
            H.append('<div class="table-header">משככי כאבים (Analgesia)</div>')
            if e.get("analgesia_used") is not None:
                H.append(
                    '<div class="table"><div>'
                    f'שימוש במשככי כאבים: {"כן" if e["analgesia_used"] else "לא"}'
                    "</div></div>"
                )
            if not e.get("analgesia_used") and e.get("analgesia_justification_for_omission"):
                H.append(
                    '<div class="table"><div>'
                    f'סיבה לאי שימוש: {_e(e["analgesia_justification_for_omission"])}'
                    "</div></div>"
                )
            if e.get("analgesia"):
                H.append('<div class="table horizontal"><table><tbody>')
                H.append(
                    "<tr>"
                    "<th>Phase</th><th>Agent</th><th>Dose</th><th>Route</th><th>Frequency</th>"
                    "</tr>"
                )
                for row in e["analgesia"]:
                    H.append(
                        _row(
                            [
                                row.get("phase", ""),
                                row.get("agent", ""),
                                row.get("dose", ""),
                                row.get("route", ""),
                                row.get("frequency", ""),
                            ]
                        )
                    )
                H.append("</tbody></table></div>")

        # Anesthesia
        if e.get("anesthesia_used") is not None and not e.get("anesthesia") and not e.get("anesthesia_drugs"):
            H.append('<div class="table-header">חומרי הרדמה (Anesthesia)</div>')
            H.append(
                '<div class="table"><div>'
                f'שימוש בחומרי הרדמה: {"כן" if e["anesthesia_used"] else "לא"}'
                "</div></div>"
            )
        if e.get("anesthesia"):
            H.append('<div class="table-header">Anesthesia</div>')
            H.append('<div class="table horizontal"><table><tbody>')
            H.append(
                "<tr>"
                "<th>Agent</th><th>Induction</th><th>Maintenance</th>"
                "<th>Route</th><th>Monitoring</th>"
                "</tr>"
            )
            for row in e["anesthesia"]:
                H.append(
                    _row(
                        [
                            row.get("agent", ""),
                            row.get("induction", ""),
                            row.get("maintenance", ""),
                            row.get("route", ""),
                            row.get("monitoring", ""),
                        ]
                    )
                )
            H.append("</tbody></table></div>")

        if e.get("anesthesia_drugs"):
            H.append('<div class="table-header">Structured Anesthesia Drugs</div>')
            H.append('<div class="table horizontal"><table><tbody>')
            H.append(
                "<tr>"
                "<th>Agent</th><th>Dose</th><th>Route</th><th>Frequency</th>"
                "<th>Rationale</th><th>Monitoring</th>"
                "</tr>"
            )
            for row in e["anesthesia_drugs"]:
                H.append(
                    _row(
                        [
                            row.get("agent", ""),
                            row.get("dose", ""),
                            row.get("route", ""),
                            row.get("frequency", ""),
                            row.get("rationale", ""),
                            row.get("monitoring", ""),
                        ]
                    )
                )
            H.append("</tbody></table></div>")

        # Severity & monitoring
        mon = e.get("monitoring") or {}
        H.append(f'<div class="monitoring"{_ref(f"monitoring-{idx}")}>')
        H.append('<div class="table horizontal"><table><tbody>')
        H.append(
            "<tr>"
            "<th>דרגת כאב וסבל</th><th>ניטור 72ש ראשונות</th>"
            "<th>ניטור שבועי</th><th>פרמטרים</th><th>קטגוריית כאב</th>"
            "</tr>"
        )
        H.append(
            _row(
                [
                    e.get("severity_level_1_to_5", ""),
                    "כן" if mon.get("initial_72h_daily") else "לא",
                    mon.get("ongoing_per_week", ""),
                    ", ".join(mon.get("parameters") or []),
                    e.get("pain_category", ""),
                ]
            )
        )
        H.append("</tbody></table></div>")
        H.append("</div>")  # close monitoring

        # Endpoints
        he = e.get("humane_endpoints") or {}
        H.append('<div class="table-header">נקודות סיום הומאניות</div>')
        if he.get("general"):
            H.append(
                '<div class="table"><div>כלליות: '
                + _e("; ".join(he.get("general") or []))
                + "</div></div>"
            )
        if he.get("specific"):
            H.append(
                '<div class="table"><div>ספציפיות: '
                + _e("; ".join(he.get("specific") or []))
                + "</div></div>"
            )

        # Euthanasia
        eu = e.get("euthanasia") or {}
        H.append(f'<div class="euthanasia"{_ref(f"euthanasia-{idx}")}>')
        H.append('<div class="table-header">שיטת המתה</div>')
        H.append('<div class="table horizontal"><table><tbody>')
        H.append(
            "<tr><th>שיטה מובנית</th><th>ראשית</th><th>פרמטרים</th><th>תנאים</th><th>אישור מוות</th></tr>"
        )
        H.append(
            _row(
                [
                    eu.get("method_standard", ""),
                    eu.get("primary", ""),
                    eu.get("parameters", ""),
                    eu.get("conditions_text", ""),
                    eu.get("confirmation", ""),
                ]
            )
        )
        H.append("</tbody></table></div>")
        H.append("</div>")  # close euthanasia

        # Specialty mini-blocks
        def render_kv_block(title: str, data: Dict[str, Any]) -> None:
            if not data:
                return
            H.append(f'<div class="table-header">{_e(title)}</div>')
            H.append('<div class="table"><div>')
            for k, v in data.items():
                H.append(f"<div><b>{_e(k)}:</b> {_e(v)}</div>")
            H.append("</div></div>")

        render_kv_block("Stereotaxic / Implant", e.get("stereotaxic_implant") or {})
        render_kv_block("Oncology", e.get("oncology") or {})
        render_kv_block("Diabetes", e.get("diabetes") or {})
        render_kv_block(
            "Biosafety & Infectious Agents",
            e.get("biosafety_infectious_agents") or {},
        )
        render_kv_block("Nanomaterials", e.get("nanomaterials") or {})
        render_kv_block("Ocular Procedures", e.get("ocular_procedures") or {})
        render_kv_block("Housing Density", e.get("housing_density") or {})
        render_kv_block("Restraint", e.get("restraint") or {})
        render_kv_block("Reuse Review", e.get("reuse_review") or {})
        render_kv_block("Field Study Permits", e.get("field_study_permits") or {})

        # Fate
        H.append('<div class="table-header">מצב אחרי הניסוי</div>')
        H.append(
            '<div class="table"><div>'
            f'{_e(e.get("fate", ""))}'
            "</div></div>"
        )
        H.append("</div>")  # close experiment section

    # --- Postmortem processing ---
    if pm.get("used"):
        H.append('<div class="sub-header">עיבוד לאחר המתה</div>')
        H.append(
            '<div class="table"><div>Perfusion: '
            + _e(pm.get("perfusion", ""))
            + "</div></div>"
        )
        H.append(
            '<div class="table"><div>Fixation: '
            + _e(pm.get("fixation", ""))
            + "</div></div>"
        )
        H.append(
            '<div class="table"><div>Technique: '
            + _e(pm.get("clearing_or_special_technique", ""))
            + "</div></div>"
        )
        H.append(
            '<div class="table"><div>Safety: '
            + _e(pm.get("chemical_safety_notes", ""))
            + "</div></div>"
        )

    # --- PI declaration ---
    H.append('<div class="sub-header">הצהרת החוקר</div>')
    H.append(
        '<div class="table"><div>שם: ' + _e(pi_decl.get("name", "")) + "</div></div>"
    )
    H.append(
        '<div class="table"><div>תאריך: '
        + _e(pi_decl.get("date", ""))
        + "</div></div>"
    )

    # --- Chair statement ---
    if chair.get("decision") or chair.get("comments"):
        H.append('<div class="sub-header">החלטת יו"ר</div>')
        H.append(
            '<div class="table"><div>החלטה: '
            + _e(chair.get("decision", ""))
            + "</div></div>"
        )
        H.append(
            '<div class="table"><div>הערות: '
            + _e(chair.get("comments", ""))
            + "</div></div>"
        )

    H.append("</div></div></body></html>")
    html_str = "".join(H)

    if out_html_path:
        Path(out_html_path).write_text(html_str, encoding="utf-8")
    return html_str


def render_html_with_refs(instance: Dict[str, Any], out_html_path: str = None) -> str:
    """
    Convenience wrapper that renders HTML with data-ref attributes for web UI error mapping.
    """
    return render_html(instance, out_html_path, with_refs=True)


def _load_json(path: str) -> Dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))

def _save_json(obj: Any, path: str) -> None:
    Path(path).write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Lint and/or render IACUC_SCHEMA_V2 JSON instances."
    )
    parser.add_argument("mode", choices=["lint", "render", "both"])
    parser.add_argument("instance", help="Path to JSON instance file.")
    parser.add_argument(
        "--profile",
        choices=["default", "strict_law"],
        default="default",
        help=(
            "Linting profile: 'default' (structural + minimal law) or "
            "'strict_law' (upgrade law-critical checks such as alternatives search to errors)."
        ),
    )
    parser.add_argument("--report", default="lint_report.json")
    parser.add_argument("--html", default="render.html")
    args = parser.parse_args()

    instance = _load_json(args.instance)

    if args.mode in ("lint", "both"):
        rep = lint(instance, profile=args.profile)
        _save_json(rep, args.report)
        print(
            f"[lint] status={rep['status']} errors={rep['errors']} warnings={rep['warnings']} "
            f"report={args.report}"
        )

    if args.mode in ("render", "both"):
        out = render_html(instance, args.html)
        print(f"[render] wrote {args.html} ({len(out)} bytes)")


if __name__ == "__main__":
    main()
