# Linter split plan (handoff P3.1): feasibility report

Date: 2026-09-05. Scope: `src/linter_renderer.py::lint()` (lines 287 to 2376, 63 `_rule(...)` call sites, 59 rule ids in `src/rules.py`). Nothing was modified for this report; every line number below was checked against the file at commit `cdfc44f`.

Invariant for the refactor: the pytest suite (662 collected today, the handoff says 660) passes, and the report JSON for every fixture is byte-identical to a pre-split snapshot. No rule may change trigger, severity, message, ref string, or position in `checklist`.

## 1. Verdict

A mechanical per-domain split with identical behaviour is achievable. The function is long but it is not tangled: apart from one data prelude (animals totals, lines 512 to 631) and a handful of block-to-block locals, the 63 checks are independent `if` blocks that append to one list and bump two ints. There is no post-pass that rewrites severities, no rule reads another rule's checklist row, and only one closure (`req`, line 305) captures function state.

The minimal mechanism, and the one to use, is a mutable context object plus a fixed call order. Nothing fancier is needed and anything fancier is where behaviour drifts.

```python
# src/lint_ctx.py
@dataclass
class RuleContext:
    instance: dict
    profile: str                 # already normalised to "default" | "strict_law" at line 298
    checks: list = field(default_factory=list)
    errors: int = 0
    warnings: int = 0
    # cross-region values, filled by the prelude (today lines 512 to 579)
    exps: list = None            # instance["experiments"] or []
    totals: list = None          # instance["animals_total"] or []
    exp_signals: list = None     # the SAME list object; mutated in place by 9 later sites, published by reference at 2334
    total_n_all: int = 0         # line 571; read at 639, 760, 787, 2322
    invasive_keywords: list = None  # defined at 1149, re-read at 1264 by pain:category-consistency
```

Each domain module exposes `run(ctx: RuleContext) -> None` and does exactly what the block does today: `ctx.checks.append(_rule(...))`, `ctx.errors += 1`, `ctx.warnings += 1`, in the same order. `lint()` becomes: build ctx, call the modules in the fixed order listed in section 3, then run the unchanged report assembly (lines 2303 to 2376).

Three deliberate non-choices:

- Do not derive counters from the emitted row's severity. Section 5 lists the four places where that derivation gives a different number from today.
- Do not make `run()` return checks for the caller to concatenate. Two rules write `exp_signals` for experiments that emit no row (1461, 2059 and siblings), and `term:track` bumps a counter before appending; a return-value design forces those into special cases. Appending to `ctx.checks` directly keeps every block a verbatim cut-and-paste.
- Do not pass `profile` only to the modules that read it. All modules take the same `ctx`; the ones that never branch on profile simply never touch it.

`req` (305 to 319, `nonlocal errors`) moves to the context as a method with identical body (`ctx.errors += 1; ctx.checks.append(...)`); its bool return is unused at all three call sites (326, 334, 450) and stays.

## 2. Dependency graph between regions

Arrow means "consumes a value produced by". Everything not listed is independent and only shares `checks`, `errors`, `warnings`, `profile`.

```
prelude (512-579): exps, totals, exp_sums, mismatch_details, total_n_all, is_simplified_total, exp_signals
  |-- animals:totals-vs-exps (615-631)         reads exp_sums, mismatch_details, totals
  |-- scope:pilot-size (634-657)               reads total_n_all, exps, totals
  |-- N:justification-detail (757-775)         reads total_n_all; WRITES n_just, details_text
  |     `-- N:power-analysis (777-802)         reads n_just, details_text, total_n_all
  |-- every per-experiment loop (805 .. 2243)  reads exps
  |-- exp_signals writers (in place):
  |     severity:analgesia 1178, endpoints:generic-consult 1461, endpoints:20%-only 1494,
  |     six specialty flags 2059/2095/2126/2158/2191/2222
  `-- report analysis (2320-2335)              reads total_n_all (2322), exp_signals by reference (2334)

research else-branch (332-442): r, rt, title_he, title_en
  `-- title:track, title:pilot-label, term:track, continuation, third-party
      (only reachable when "research" is present; req("research") always precedes them)

single-sex guard (666): sexes_seen (660-665)
  `-- sex:rationale (690-699) and sex:sabv (743-755) are siblings inside ONE if

AVMA loop (909-1116): per-iteration raw_species, raw_method, params, confirmation,
                      species_key, method_key, avma_result (910-925, `continue` at 923)
  `-- euthanasia:species-method, precharged-chamber, displacement-rate,
      secondary-method, cervical-weight (2 sites), conditions-missing
      -> one indivisible unit; check_method_for_species is called once per experiment

severity:analgesia (1148-1200): invasive_keywords (1149-1161)
  `-- pain:category-consistency (1263-1328) builds moderate_burden_keywords from it

alternatives (1330-1402): one if/else; alts:missing excludes alts:engines/queries/conclusion

humane-endpoints loop (1455-1513): shared `text`, shared `continue` at 1463
  `-- endpoints:generic-consult and endpoints:20%-only

specialty loop (2046-2238): joined (2051) shared by six checks; flag write is OUTSIDE the if body

summaries (2268-2272): sci_wc, lay_wc
  `-- summaries:scientific-length, summaries:lay-length

colony:no-invasive (2240-2265): last errors += 1 in the function; must precede status at 2303
```

Recomputed rather than shared (and therefore free to extract independently): `request_type` (635 and 780), `sexes_seen` (660 and 2307), `n_just` (758 and 2023), humane-endpoints text (1456 and 1522), `procedure_timeline` joins (six blocks), `_coerce_float(max_duration_minutes)` (1765 and 1790). Keep the duplicates; do not hoist them.

## 3. Ordered batch plan

Rules per batch, module name, and why it sits where it does. Order of the `run()` calls inside `lint()` is the source order of the blocks; every batch keeps that order. After every batch: `pytest -q` and the section 4 equivalence check, then one commit.

Batch 0, infrastructure (no rules). Add `RuleContext`, move `_rule` untouched, take the snapshot described in section 4. `lint()` still contains every check inline but writes through `ctx`. This batch is the one that changes the plumbing for all 63 sites, so it gets its own equivalence run before any block moves.

Batch 1, safest: `rules_summaries.py` and `rules_colony.py` (4 rules: summaries:scientific-length, summaries:lay-length, colony:breeding-plan, colony:no-invasive). Protocol-level, no loop, no profile branch, no exp_signals, no cross-block locals except the two summaries word counts which move together. Only trap: colony:no-invasive has no `severity=` and increments `errors` after the append; copy it verbatim.

Batch 2: `rules_specialty.py` (6 rules, one loop: special:stereotaxic, oncology, diabetes, biosafety, nanomaterials, ocular) plus `rules_misc_exp.py` for the four stragglers ascites:in-vitro, gma:ibc, deprivation:protocol, vet:consultation. No profile branch anywhere. The specialty flag writes (2059 and siblings) stay on the always-path, outside `if has_X`. Note `timeline_txt` is lowercased at 1998 (ascites) and not at 2048 (specialty; the `.lower()` is on `joined`).

Batch 3: `rules_husbandry.py` (7 rules: postop:monitoring, surgery:multiple-survival, housing:density, restraint:duration, reuse:justification, permits:field-study, endpoints:death-only). Multi-site refs (housing 2, restraint 3) keep their emit order inside the iteration. `mon_text` seams differ (1568 and 1630 have no separator, 1947 has one); copy each literally. Three of these branch on profile.

Batch 4: `rules_endpoints_pain.py` (7 rules: severity:monitoring, severity:analgesia, paralytic:without-anesthesia, pain:category-consistency, endpoints:generic-consult, endpoints:20%-only, plus the protocol-level cosmetics:ban that sits between them in source order). `invasive_keywords` becomes `ctx.invasive_keywords`, assigned exactly where line 1149 assigns it today and read at the 1264 site. The humane-endpoints pair keeps one loop and one `continue`.

Batch 5: `rules_alternatives.py` (4 rules: alts:missing, alts:engines, alts:queries, alts:conclusion). One if/else, extracted as one function. Small, but isolated because a flattened version is the most tempting wrong refactor.

Batch 6: `rules_euthanasia.py` (10 rules: euthanasia:CO2, overdose-confirm, special:neonatal-CO2, species-method, precharged-chamber, displacement-rate, secondary-method, cervical-weight (2 sites), conditions-missing). Three loops (805, 868, 909) move as they are; the 909 loop body, lines 909 to 1116, is one function. The neonatal `re.compile` at 863 stays inside the function for this pass.

Batch 7: `rules_animals.py` and `rules_header.py` (last, because they own the shared state everyone else already consumes). animals: the prelude 512 to 579 plus animals:totals-vs-exps, scope:pilot-size, sex:rationale, sex:sabv, N:justification-detail, N:power-analysis (7 rules). The prelude writes `ctx.exps`, `ctx.totals`, `ctx.exp_signals`, `ctx.total_n_all`; by this batch every consumer already reads them from `ctx`, so the move is a pure cut. header: required (3 call sites via `req`), header, research, title:track, title:pilot-label, term:track, continuation, third-party, pi, pi:training, participant:training, participant:certified-without-training (12 rules). term:track is copied with its counter lines 388 to 389 above the append, untouched.

Total after batch 7: `lint()` is the ctx build, eight `run()` calls, and the report assembly (`ref_matches` may move to module scope; it closes over nothing).

## 4. Equivalence check after every batch

Fixtures: the 94 `.html` files under `examples/` (known-good, known-bad, golden-dataset, head-to-head, adapters). Two profiles each: 188 reports.

Before batch 0, on the untouched tree:

```bash
ETIQTECH_JURISDICTION= python3 - <<'EOF'
import json, pathlib, sys
from src.html_to_json import parse_html
from src.linter_renderer import lint
out = pathlib.Path("build/lint-snapshot"); out.mkdir(parents=True, exist_ok=True)
for f in sorted(pathlib.Path("examples").rglob("*.html")):
    inst = parse_html(f.read_text(encoding="utf-8"))
    for prof in ("default", "strict_law"):
        rep = lint(inst, profile=prof); rep.pop("generated_at")
        name = f"{f.relative_to('examples')}".replace("/", "__") + f".{prof}.json"
        (out / name).write_text(json.dumps(rep, ensure_ascii=False, sort_keys=False, indent=1))
EOF
```

After every batch, run the same script into `build/lint-current` and `diff -r build/lint-snapshot build/lint-current`. Empty diff or the batch does not land. Points that matter:

- `generated_at` is the only non-deterministic key (line 2373); it is popped, nothing else is normalised.
- `sort_keys=False`. Key order in `report` and in each checklist row is part of what is being frozen.
- `ETIQTECH_JURISDICTION` is pinned empty so `apply_pack` (rules.py 161) takes the default pack and does not recount. Run a second pass with each non-default pack name in `PACKS` if the pack filter is in scope for the release; it re-derives `errors` and `warnings` from the rows, so it hides exactly the counter bugs in section 5 and must not be the only check.
- Row order in `checklist`, the `reference` string including the `:exp-N` suffix, and the `severity` string on passing rows are all in the diff by construction. That is intended.
- `build/lint-snapshot` is regenerated only from the pre-split commit, never from a post-batch tree.

## 5. Pre-existing counting bugs: preserve, do not fix

Verified by arithmetic over the whole function: 63 appends, 34 `errors += 1`, 47 `warnings += 1`; 17 profile if/else pairs account for 34 counter lines against 17 appends, leaving 46 appends against 47 counter lines. The one surplus line, and the three severity/counter mismatches, are:

1. term:track (379 to 403). `if not ok_term: errors += 1` (388) and `if ok_term and not ideal_term: warnings += 1` (389) run before the append, and the flag passed to `_rule` is `ideal_term`, not `ok_term`. Trigger: `isinstance(term, int)`, `rt` truthy and not `"pilot"`, term outside 1 to 4. Result: `errors` goes up by one, `status` flips to `fail`, and the only row emitted is `{"status": "pass", "severity": "error", "message": "Approval term consistent with request type."}`. This is the one place in `lint()` where a counter moves without a failing row. Extract verbatim, counter lines above the append.
2. title:pilot-label (365 to 377). Append carries no `severity=` (so `"error"` from the `_rule` default at line 110) but the counter is `warnings += 1`. The ref is in `ADVISORY_REFS` (259) and the tally at 2361 requires `sev != "error"`, so a failing row is counted in `warnings` and in no category counter. Keep the missing argument.
3. `required:<path>` (via `req`, 305 to 319). Emitted refs are `required:header`, `required:research`, `required:pi`. The registry key in `rules.py` is `required`, and it is the one id in none of `STRUCTURAL_REFS`, `LAW_CRITICAL_REFS`, `ADVISORY_REFS`. `ref_matches` strips only `:exp-`, so a failing `required:*` row increments `errors` and no category counter. Keep it.
4. Passing rows stamped `severity="error"`: severity:monitoring (1118 to 1146, no `severity=` argument, only rule with a pass path in its region) and the six specialty rules (`severity = "warning" if not ok_X else "error"`, 2066 and siblings). Nothing counts them today because the tally loop skips non-fail rows, but the string is in the JSON. A tidy-up to `"warning"` changes the payload.

Also to keep unchanged, not bugs but load-bearing quirks: counter-before-append ordering in term:track, scientific-length (2277 before 2279) and the six specialty rules; append-before-counter everywhere else; `pi = instance.get("pi") or {}` treating an empty dict as missing (445); `if totals:` discarding a computed `mismatch_details` (615); `gm_keywords` containing bare `"ko"`, `"ki"`, `"ge"`, `"gm"`; vet:consultation and pain fallback requiring `isinstance(sev, int)`; the non-ASCII summaries keys `scientific_en_≤300w` and `lay_he_≤150w` with the enforced 2500-word limit despite the key name.

Fixing any of items 1 to 4 changes `report["errors"]`, `report["status"]` or the checklist payload for real inputs. Each fix is a separate change, with its own fixture, approved by the maintainer, after the split has landed and the snapshot has been re-taken.

## 6. Risks, and what would make me stop

Risks, ranked:

1. Splitting the 909 to 1116 AVMA loop. It is five rule ids in one loop body sharing `avma_result`. Two loops mean two `check_method_for_species` calls per experiment and a checklist that is grouped per rule instead of interleaved per experiment. The diff catches it, but only if batch 6 is not "helpfully" reorganised first.
2. Deriving counters from severity. Correct for 59 of 63 sites, wrong for the four in section 5. It will pass most tests and fail the snapshot on a minority of fixtures, which is the kind of failure that gets waved through as "the fixture was wrong".
3. `exp_signals` identity. The report publishes the list by reference (2334) and `annotate_report`/`apply_pack` run on the same dict. Any module that builds a new list or copies dicts changes what later code sees. `ctx.exp_signals` must be the list built at 517.
4. Losing an always-path write when a block is turned into an early-return function: `has_humane_endpoints` (1461, above the `continue` at 1463) and the six specialty flags (outside the `if has_X`). The check rows stay identical; only `analysis.experiments` changes, so this one is caught only by the snapshot, not by most unit tests.
5. Keyword lists drifting during the paste (`invasive_keywords`, the 20 cosmetics keywords at 1406 to 1425, the neonatal regex at 863). Lowest probability, highest chance of silently changing a trigger on a fixture the suite does not exercise.
6. Fixture coverage. 94 fixtures do not exercise every branch (term:track's phantom error needs an out-of-range term on a non-pilot request; nothing guarantees a fixture has one). The snapshot proves equality on the inputs we have, not on all inputs; verbatim cut-and-paste is what covers the rest, which is why the plan forbids any rewording inside a block.

Stop conditions:

- A non-empty snapshot diff that cannot be traced to a specific line I moved within the batch. Revert the batch; do not adjust the snapshot.
- Any batch that needs a change to `src/rules.py`, to a ref string, to a message string, or to `_rule`. Those are not part of a mechanical split.
- The urge to fix a section 5 item mid-batch. Note it, finish the batch, raise it separately.
- A test that asserts on `generated_at` or on wall-clock behaviour appearing in the diff. That is a test problem to raise, not a reason to normalise more keys.
- The 662-collected count changing. The split adds no tests and removes none; a different number means a module import broke collection.
