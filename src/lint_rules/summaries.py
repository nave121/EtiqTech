"""summaries:* rules. Verbatim move from linter_renderer.lint() (P3.1 batch 1)."""
import re

from .context import RuleContext, _rule


def run(ctx: RuleContext) -> None:
    instance = ctx.instance
    # --- summaries word limits (simple word count) ---
    summaries = instance.get("summaries") or {}
    sci = summaries.get("scientific_en_≤300w", "") or ""
    lay = summaries.get("lay_he_≤150w", "") or ""
    sci_wc = len(re.findall(r"\w+", sci))
    lay_wc = len(re.findall(r"\w+", lay))

    # Relaxed for Council Exports which often dump full proposal (>1000 words)
    ok_sci = sci_wc <= 2500
    if not ok_sci:
        ctx.warnings += 1

    ctx.checks.append(
        _rule(
            ok_sci,
            f"Scientific abstract within 2500 words ({sci_wc}).",
            f"Scientific abstract too long ({sci_wc} words, limit 2500).",
            fix="Shorten or move methodological detail to later sections.",
            severity="warning",
            ref="summaries:scientific-length",
        )
    )

    ctx.checks.append(
        _rule(
            lay_wc <= 150,
            f"Lay summary within 150 words ({lay_wc}).",
            f"Lay summary too long ({lay_wc} words, limit 150).",
            fix="Shorten and remove technical detail; keep as lay explanation.",
            severity="warning",
            ref="summaries:lay-length",
        )
    )
    if lay_wc > 150:
        ctx.warnings += 1
