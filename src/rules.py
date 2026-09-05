"""Rule registry (Phase 3.1): stable identifiers for every deterministic Layer 1 check.

The linter has always tagged each check with a `reference` such as `euthanasia:CO2` or
`severity:analgesia:exp-2`. Those references ARE the rule identifiers: short, namespaced
by domain, already used by the golden dataset's ground truth and by the UI. This module
makes them explicit — one registry entry per rule, a canonical `rule_id` on every
checklist item (instance suffixes such as `:exp-2` stripped), and a ruleset version on
the report — so committees can cite "fails euthanasia:secondary-method under ruleset
1.0.0", suppression lists and per-rule noise tracking have a key, and jurisdiction packs
have something to select on.

Behaviour of the checks themselves is untouched; this file only names them.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Dict, Optional

RULESET_VERSION = "1.0.0"  # bump when a rule is added, removed, or its trigger changes

_INSTANCE_SUFFIX = re.compile(r":exp-\d+$")


@dataclass(frozen=True)
class Rule:
    id: str
    domain: str
    kind: str           # structural | law_critical | advisory | required
    jurisdiction: str   # IL-form: Israeli request-form / Council specific; generic: welfare/science, any jurisdiction
    title: str


def _r(rule_id: str, kind: str, jurisdiction: str, title: str) -> Rule:
    return Rule(rule_id, rule_id.split(":", 1)[0], kind, jurisdiction, title)


RULES: Dict[str, Rule] = {r.id: r for r in [
    # --- structure of the request (Israeli Council export) ---
    _r("required", "required", "IL-form", "Required fields present at a given path"),
    _r("header", "structural", "IL-form", "Header block present"),
    _r("research", "structural", "IL-form", "Research block present"),
    _r("pi", "structural", "IL-form", "Principal-investigator block present"),
    _r("pi:training", "structural", "generic", "PI has training entries"),
    _r("participant:training", "structural", "generic", "Every participant has training entries"),
    _r("participant:certified-without-training", "advisory", "generic", "Participant marked certified but lists no training"),
    _r("animals:totals-vs-exps", "structural", "generic", "Animal totals match the sum over experiments"),
    _r("continuation", "structural", "IL-form", "Continuation request references its predecessor"),
    _r("third-party", "structural", "IL-form", "Third-party research block complete"),
    _r("colony:no-invasive", "structural", "IL-form", "Colony protocol contains no invasive experiments"),
    _r("colony:breeding-plan", "advisory", "generic", "Colony protocol has a colony-management plan"),
    _r("term:track", "structural", "IL-form", "Approval term consistent with request type"),
    _r("title:track", "law_critical", "IL-form", "Title consistent with request type (pilot vs regular)"),
    _r("title:pilot-label", "advisory", "IL-form", "Pilot request title carries the pilot label"),
    _r("scope:pilot-size", "advisory", "IL-form", "Pilot request stays within pilot-sized scope"),
    # --- euthanasia (AVMA 2020 matrix) ---
    _r("euthanasia:overdose-confirm", "law_critical", "generic", "Anaesthetic overdose has a confirmation step"),
    _r("euthanasia:CO2", "law_critical", "generic", "CO2 euthanasia has an explicit confirmation step"),
    _r("euthanasia:species-method", "law_critical", "generic", "Method acceptable for the species (AVMA)"),
    _r("euthanasia:conditions-missing", "law_critical", "generic", "Conditionally acceptable method documents its conditions"),
    _r("euthanasia:displacement-rate", "law_critical", "generic", "CO2 displacement rate specified"),
    _r("euthanasia:secondary-method", "law_critical", "generic", "Inhalant euthanasia has a secondary physical method"),
    _r("euthanasia:precharged-chamber", "law_critical", "generic", "No pre-charged CO2 chamber"),
    _r("euthanasia:cervical-weight", "law_critical", "generic", "Cervical dislocation within species weight limit"),
    _r("special:neonatal-CO2", "law_critical", "generic", "CO2 not the sole method for neonates"),
    # --- severity, endpoints, monitoring ---
    _r("severity:monitoring", "law_critical", "generic", "Monitoring plan present for the declared severity"),
    _r("severity:analgesia", "law_critical", "generic", "Analgesia present for invasive severity >= 3"),
    _r("endpoints:20%-only", "law_critical", "generic", "Humane endpoints beyond 20% weight loss"),
    _r("endpoints:death-only", "law_critical", "generic", "Death/moribundity not the sole endpoint"),
    _r("endpoints:generic-consult", "advisory", "generic", "Endpoints not just 'consult the vet'"),
    _r("postop:monitoring", "law_critical", "generic", "Survival surgery has a post-operative monitoring plan"),
    _r("pain:category-consistency", "law_critical", "generic", "Declared pain category consistent with procedures"),
    _r("paralytic:without-anesthesia", "law_critical", "generic", "No paralytic agent without anaesthesia"),
    _r("vet:consultation", "advisory", "generic", "Severity 4-5 documents veterinary consultation"),
    _r("surgery:multiple-survival", "advisory", "generic", "Multiple survival surgeries justified"),
    _r("deprivation:protocol", "advisory", "generic", "Food/water deprivation has weight monitoring and endpoints"),
    _r("restraint:duration", "advisory", "generic", "Restraint specifies duration, acclimation and endpoints"),
    _r("housing:density", "advisory", "generic", "Housing density within guidance"),
    _r("reuse:justification", "law_critical", "generic", "Animal reuse justified"),
    _r("permits:field-study", "law_critical", "generic", "Field study lists required permits (CITES is international)"),
    # --- 3Rs, numbers, sex ---
    _r("alts:missing", "law_critical", "generic", "Alternatives search present"),
    _r("alts:engines", "law_critical", "IL-form", "Alternatives search lists the databases used"),
    _r("alts:queries", "advisory", "generic", "Alternatives search lists queries"),
    _r("alts:conclusion", "advisory", "generic", "Alternatives search states a conclusion"),
    _r("cosmetics:ban", "law_critical", "generic", "No cosmetics / household-product testing (banned in IL, EU and elsewhere)"),
    _r("N:justification-detail", "advisory", "generic", "Animal numbers justified in detail"),
    _r("N:power-analysis", "advisory", "generic", "Non-trivial N has a power analysis or precedent"),
    _r("sex:rationale", "advisory", "generic", "Sex choice has a rationale"),
    _r("sex:sabv", "advisory", "generic", "Sex as a biological variable considered"),
    # --- special contexts ---
    _r("special:stereotaxic", "advisory", "generic", "Stereotaxic/DBS work has an implant block"),
    _r("special:oncology", "advisory", "generic", "Tumour work states burden cap and ulceration policy"),
    _r("special:diabetes", "advisory", "generic", "Diabetes model states measurement mode and threshold"),
    _r("special:biosafety", "advisory", "generic", "Infectious work has biosafety metadata"),
    _r("special:nanomaterials", "advisory", "generic", "Nanomaterial work has a nanomaterials block"),
    _r("special:ocular", "advisory", "generic", "Ocular work has an ocular-procedures block"),
    _r("gma:ibc", "advisory", "generic", "Genetically modified animals reference IBC approval"),
    _r("ascites:in-vitro", "advisory", "generic", "Ascites production justifies over in-vitro alternatives"),
    # --- writing ---
    _r("summaries:scientific-length", "advisory", "IL-form", "Scientific summary within the word limit"),
    _r("summaries:lay-length", "advisory", "IL-form", "Lay summary within the word limit"),
]}


def rule_id_from_ref(ref: Optional[str]) -> Optional[str]:
    """`euthanasia:CO2:exp-3` -> `euthanasia:CO2`; `required:header` -> `required`; unknown -> None."""
    if not ref:
        return None
    base = _INSTANCE_SUFFIX.sub("", ref)
    if base.startswith("required:"):
        base = "required"
    return base if base in RULES else None


def annotate_report(report: Dict[str, Any]) -> Dict[str, Any]:
    """Add `rule_id` to every checklist item and `ruleset_version` to the report. In place."""
    for item in report.get("checklist") or []:
        item["rule_id"] = rule_id_from_ref(item.get("reference"))
    report["ruleset_version"] = RULESET_VERSION
    return report


# ---------------------------------------------------------------------------
# Jurisdiction packs (Phase 3.2, step 1): a pack = rule set + corpus filter + theme config,
# selected by ETIQTECH_JURISDICTION. "IL" is today's behaviour and the default. The EU pack
# is not registered until docs/eu-directive-spike.md has been reviewed and its rules exist.
# ---------------------------------------------------------------------------
PACKS: Dict[str, Dict[str, Any]] = {
    "IL": {
        "label": "Israel — National Council request form",
        "rule_jurisdictions": ("IL-form", "generic"),   # every registered rule
        "corpus_jurisdictions": ("IL",),
        "excluded_themes": (),
    },
    "generic": {
        "label": "Generic — welfare/science rules only (no Israeli form rules)",
        "rule_jurisdictions": ("generic",),
        "corpus_jurisdictions": ("IL",),  # the only corpus we have; guidance is still useful context
        "excluded_themes": ("writing_quality",),  # scores Hebrew answers 0 — an IL form-workflow rule
    },
}
DEFAULT_PACK = "IL"


def active_pack() -> str:
    import os
    name = os.getenv("ETIQTECH_JURISDICTION", DEFAULT_PACK).strip() or DEFAULT_PACK
    return name if name in PACKS else DEFAULT_PACK


def rule_active(rule_id: Optional[str], pack: Optional[str] = None) -> bool:
    rule = RULES.get(rule_id or "")
    if rule is None:
        return True  # unregistered refs are never dropped silently
    return rule.jurisdiction in PACKS[pack or active_pack()]["rule_jurisdictions"]


def apply_pack(report: Dict[str, Any], pack: Optional[str] = None) -> Dict[str, Any]:
    """Drop checklist items whose rule is outside the pack and recompute the counters.

    This is configuration, not review logic: the checks still ran; a pack only decides which
    rules belong to the jurisdiction being reviewed. Never called with LLM output.
    """
    name = pack or active_pack()
    report["jurisdiction"] = name
    if name == DEFAULT_PACK:
        return report
    kept = [c for c in report.get("checklist") or [] if rule_active(c.get("rule_id"), name)]
    dropped = len(report.get("checklist") or []) - len(kept)
    report["checklist"] = kept
    report["errors"] = sum(1 for c in kept if c.get("status") == "fail" and c.get("severity") == "error")
    report["warnings"] = sum(1 for c in kept if c.get("status") == "fail" and c.get("severity") != "error")
    report["status"] = "pass" if report["errors"] == 0 else "fail"
    for field, kind, sev in (("structural_errors", "structural", "error"), ("law_critical_errors", "law_critical", "error"),
                             ("advisory_warnings", "advisory", "warning")):
        report[field] = sum(1 for c in kept if c.get("status") == "fail" and RULES.get(c.get("rule_id") or "") is not None
                            and RULES[c["rule_id"]].kind == kind and (c.get("severity") == "error") == (sev == "error"))
    report["rules_outside_pack"] = dropped
    return report
