"""Alternatives-search rules: alts:missing, alts:engines, alts:queries,
alts:conclusion. Verbatim move from linter_renderer.lint() (P3.1 batch 5).

One if/else, moved as one function on purpose: alts:missing excludes the
other three, so flattening it would emit extra rows.
"""
from .context import RuleContext, _rule


def run(ctx: RuleContext) -> None:
    instance = ctx.instance
    profile = ctx.profile
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
