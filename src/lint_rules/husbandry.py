"""Husbandry / procedure-context rules: endpoints:death-only, postop:monitoring,
surgery:multiple-survival, housing:density, restraint:duration, reuse:justification,
permits:field-study. Verbatim move from linter_renderer.lint() (P3.1 batch 3).

Two entry points because misc_exp.run_vet_consultation sits between
surgery:multiple-survival and housing:density in source order; a single run()
would reorder checklist rows.
"""
from typing import Dict

from .context import RuleContext, _rule
from .helpers import (
    _animal_weight_grams,
    _canonical_species_key,
    _coerce_float,
    _coerce_int,
    _flatten_text,
    _nonempty,
)


def run_surgery(ctx: RuleContext) -> None:
    exps = ctx.exps
    profile = ctx.profile
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


def run(ctx: RuleContext) -> None:
    exps = ctx.exps
    profile = ctx.profile
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
