"""Animals prelude + N/sex rules: builds exps, totals, exp_sums, mismatch_details,
total_n_all, is_simplified_total and exp_signals, publishes exps/totals/
exp_signals/total_n_all into ctx (same list objects, mutated in place by later
modules), then animals:totals-vs-exps, scope:pilot-size, sex:rationale,
sex:sabv, N:justification-detail, N:power-analysis. Verbatim move from
linter_renderer.lint() (P3.1 batch 7). Must run first: every other module
reads ctx.exps / ctx.exp_signals / ctx.total_n_all.
"""
from typing import Any, Dict, List, Tuple

from ..avma_matrix import check_method_for_species
from .context import RuleContext, _rule
from .helpers import (
    _anesthesia_rows,
    _canonical_method_key,
    _canonical_species_key,
    _pain_category,
)


def run(ctx: RuleContext) -> None:
    instance = ctx.instance
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

