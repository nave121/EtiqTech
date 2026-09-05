"""Euthanasia rules: euthanasia:CO2, euthanasia:overdose-confirm,
special:neonatal-CO2, euthanasia:species-method, euthanasia:precharged-chamber,
euthanasia:displacement-rate, euthanasia:secondary-method,
euthanasia:cervical-weight (2 sites), euthanasia:conditions-missing.
Verbatim move from linter_renderer.lint() (P3.1 batch 6).

Three loops, moved as they are. The AVMA matrix loop is one indivisible unit:
check_method_for_species is called once per experiment and the five rule ids
share its result, so splitting it would double the call and regroup the rows.
The neonatal re.compile stays inside the function for this pass.
"""
import re

from .context import RuleContext, _rule
from .helpers import (
    _anesthesia_text,
    _canonical_method_key,
    _canonical_species_key,
    _euthanasia_conditions_text,
)
from ..avma_matrix import check_method_for_species, get_displacement_rate_range


def run(ctx: RuleContext) -> None:
    exps = ctx.exps
    profile = ctx.profile
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
