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
from .lint_rules import colony, endpoints_pain, husbandry, misc_exp, specialty, summaries
from .lint_rules.helpers import (  # noqa: F401  (helpers stay importable from here)
    _flatten_text,
    _canonical_species_key,
    _canonical_method_key,
    _euthanasia_conditions_text,
    _anesthesia_rows,
    _anesthesia_text,
    _pain_category,
    _coerce_float,
    _coerce_int,
    _animal_weight_grams,
    _nonempty,
)
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

    endpoints_pain.run(ctx)

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

    endpoints_pain.run_cosmetics_endpoints(ctx)

    husbandry.run_surgery(ctx)

    misc_exp.run_vet_consultation(ctx)

    husbandry.run(ctx)

    misc_exp.run(ctx)

    colony.run_breeding_plan(ctx)

    specialty.run(ctx)

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
