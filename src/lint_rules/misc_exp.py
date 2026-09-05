"""Straggler per-experiment rules: vet:consultation, deprivation:protocol, gma:ibc, ascites:in-vitro.
Verbatim move from linter_renderer.lint() (P3.1 batch 2).

Two entry points because husbandry blocks (batch 3) sit between vet:consultation and the
other three in source order; a single run() would reorder checklist rows.
"""
from .context import RuleContext, _rule


def run_vet_consultation(ctx: RuleContext) -> None:
    exps = ctx.exps
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


def run(ctx: RuleContext) -> None:
    exps = ctx.exps
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
