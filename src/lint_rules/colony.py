"""colony:* rules. Verbatim move from linter_renderer.lint() (P3.1 batch 1).

Two entry points because the specialty loop sits between the two blocks in
source order; a single run() would reorder checklist rows.
"""
from typing import List, Tuple

from .context import RuleContext, _rule


def run_breeding_plan(ctx: RuleContext) -> None:
    instance = ctx.instance
    # --- colony breeding plan (advisory) ---
    # Israeli Rules §6-7: colony protocols require colony management plan including expected
    # surplus animal numbers and disposition plan.
    if instance.get("is_colony"):
        n_just = instance.get("n_justification") or {}
        details_text_colony = (n_just.get("details") or "").lower()
        colony_plan_keywords = ["colony", "breeding", "surplus", "disposition"]
        has_colony_plan = any(kw in details_text_colony for kw in colony_plan_keywords)
        if not has_colony_plan:
            ctx.checks.append(
                _rule(
                    False,
                    "",
                    "Colony protocol: n_justification lacks a colony management plan with expected "
                    "surplus animal numbers and disposition plan.",
                    fix=(
                        "Add colony management details to n_justification.details: expected breeding "
                        "output, surplus animal numbers, and disposition (e.g. culling, transfer, "
                        "adoption) per Israeli Rules §6-7."
                    ),
                    severity="warning",
                    ref="colony:breeding-plan",
                )
            )
            ctx.warnings += 1


def run_no_invasive(ctx: RuleContext) -> None:
    instance = ctx.instance
    exps = ctx.exps
    # --- colony constraint ---
    if instance.get("is_colony"):
        invasive_hits: List[Tuple[int, str]] = []
        for idx, e in enumerate(exps, start=1):
            for step in e.get("procedure_timeline") or []:
                s = (step.get("step") or "").lower()
                if any(k in s for k in ["surgery", "implant", "dbs", "tumor", "craniotomy"]):
                    invasive_hits.append((idx, s))
        ok_colony = len(invasive_hits) == 0
        fix_colony = (
            "Colony-only protocols may include breeding, identification, and genotyping steps only. "
            "Move invasive procedures into a separate non-colony protocol."
        )
        ctx.checks.append(
            _rule(
                ok_colony,
                "Colony protocol contains no invasive steps.",
                "Colony protocol contains invasive steps: " + "; ".join(
                    f"Exp {i}: {txt}" for i, txt in invasive_hits
                ),
                fix=fix_colony,
                ref="colony:no-invasive",
            )
        )
        if not ok_colony:
            ctx.errors += 1
