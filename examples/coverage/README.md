# Rule-coverage fixtures

Synthetic canonical-JSON instances, one per rule, for the Layer 1 rules that no real example under `examples/`
trips. Each file is the smallest instance that (a) passes the canonical schema via `src.adapters.parse_canonical_json`
and (b) makes `lint()` (either profile) emit a failing checklist item for the rule named in the filename.
`tests/test_rule_coverage.py` guards every file, and `scripts/gen_rules_doc.py` counts them in the `fixtures` column
of `docs/rules.md`.

## Adding one

1. Name the file after the rule id with `:` replaced by `__`: `euthanasia:cervical-weight` -> `euthanasia__cervical-weight.json`.
2. Start from a neighbouring fixture; change only what the rule needs. Keep other rules quiet where cheap, but a fixture
   that also trips unrelated rules is fine (the test asserts the named rule fires, not that it fires alone).
3. Add the rule id to `COVERED` in `tests/test_rule_coverage.py`, then run `python -m pytest tests/test_rule_coverage.py -q`
   and `python scripts/gen_rules_doc.py` (commit the regenerated `docs/rules.md`).

## Rules not reachable from canonical JSON

These fire only on instances the schema rejects, so `parse_canonical_json` raises before `lint()` runs. They are
reachable through the HTML parser path (`src/html_to_json.py`) only and stay in the "never appear" list on purpose.

| rule id | why |
|---|---|
| `header` | Fires only when `header` is absent from the instance (`src/linter_renderer.py:207`, `if "header" not in instance`). `header` is in the schema's top-level `required` list (`src/schema.py:16`). Verified: dropping it from `schema_skeleton()` -> `<root>: 'header' is a required property`. |
| `research` | Same shape: fires only when `research` is absent (`src/linter_renderer.py:214`); `research` is top-level required. Verified: `<root>: 'research' is a required property`. |
| `pi` | Fires when `not pi` (`src/linter_renderer.py:330-333`): missing, `{}` or `null`. All three are rejected first: `pi` is top-level required, `{}` fails its 9 required keys (`id_type` ... `institutional_cert_no`), `null` fails `type: object`. Verified all three. |
| `required` | Emitted only by `RuleContext.req` (`src/lint_rules/context.py:37-50`, ref `required:<path>`), from three callers in `src/linter_renderer.py`: header -> [protocol_id, institution]; research -> [title_he, title_en, request_type, is_continuation, third_party_service, approval_term_years, sites]; pi -> [id_type, id_number, last_name_he, first_name_he, last_name_en, first_name_en, email, phone_primary, institutional_cert_no]. Each list equals the schema's `required` list for that object (`src/schema.py:31`, `:85`, `:235`), so any instance missing one is rejected first. Verified with header minus institution, research minus sites, pi minus phone_primary. |
