"""Per-domain lint rule modules, split out of linter_renderer.lint() by verbatim
cut-and-paste (docs/dev-log/linter-split-plan.md, P3.1). Each module exposes one
or more ``run*(ctx: RuleContext) -> None`` entry points that append rows to
``ctx.checks`` and bump ``ctx.errors`` / ``ctx.warnings`` exactly as the inline
block did; nothing returns rows. The call order in ``lint()`` is fixed and equals
the original source order, because checklist row order is part of the frozen
report: header.run -> animals.run (the prelude; publishes ctx.exps / ctx.totals /
ctx.exp_signals / ctx.total_n_all, which every later module reads) ->
euthanasia.run -> endpoints_pain.run -> alternatives.run ->
endpoints_pain.run_cosmetics_endpoints -> husbandry.run_surgery ->
misc_exp.run_vet_consultation -> husbandry.run -> misc_exp.run ->
colony.run_breeding_plan -> specialty.run -> colony.run_no_invasive ->
summaries.run. Split entry points exist only where another module's block sat
between two blocks of the same domain. ``context.py`` holds RuleContext and
``_rule``; ``helpers.py`` holds the shared text/species/weight helpers.
"""
