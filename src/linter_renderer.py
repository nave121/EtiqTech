# src/linter_renderer.py

"""
Linter + HTML renderer for IACUC_SCHEMA_V2 instances.

- lint(instance)  -> report dict with a pass/fail checklist and fix suggestions.
- render_html(instance, out_html_path=None) -> HTML string (and optionally writes file).

This is deliberately pure stdlib: no external dependencies required.
"""

import argparse
import datetime
import html
import json
from pathlib import Path
from typing import Any, Dict, List

from .schema import IACUC_SCHEMA_V2  # not used for strict validation yet, but here for future use
from .rules import annotate_report, apply_pack
from .lint_rules.context import RuleContext, _rule  # noqa: F401  (_rule stays importable from here)
from .lint_rules import (
    alternatives,
    animals,
    colony,
    endpoints_pain,
    euthanasia,
    header,
    husbandry,
    misc_exp,
    specialty,
    summaries,
)
from .lint_rules.helpers import (  # noqa: F401  (helpers stay importable from here)
    _flatten_text,
    _canonical_species_key,
    _canonical_method_key,
    _euthanasia_conditions_text,
    _anesthesia_rows,
    _anesthesia_text,
    _pain_category,
    _coerce_float,
    _coerce_int,
    _animal_weight_grams,
    _nonempty,
)


CSS = """
body{
  direction:rtl;
  color:#000;
  font-size:11pt;
  font-family:Arial, Helvetica, sans-serif;
}
.header{
  font-size:14pt;
  font-weight:bold;
  text-align:center;
}
.content {
  padding: 30px 5%;
}
.sub-header{
  text-decoration:underline;
  font-weight:bold;
  padding:10px;
}
.table-header{
  padding-top:6px;
  padding-bottom:6px;
}
.table {
  width:100%;
}
.table table{
  width:100%;
  border-collapse:collapse;
  font-size:11pt;
  padding-right:6px;
  table-layout:fixed;
}
.table table td {
  border: 1px solid #000;
  line-height:24px;
  height:24px;
  padding:3px;
  padding-right:6px;
  word-break: normal;
  word-wrap: break-word;
}
.table table tr td.even {
  background-color: lightgrey;
}
.table.horizontal th{
  background-color: lightgrey;
  text-align:right;
  border: 1px solid #000;
  line-height:16px;
  height:24px;
}
.table div{
  line-height:24px;
}
.padding{
  padding-top: 10px;
}
tr,td{
  max-width: 100% !important;
  table-layout: auto !important;
  width: auto !important;
}
table{
  width: 100% !important;
}
"""


def _e(val: Any) -> str:
    """HTML-escape helper."""
    return html.escape("" if val is None else str(val))


# Classification of checks for reporting / analysis.
# This does NOT change behavior; it only affects summary counters in the report.
STRUCTURAL_REFS = {
    "required",  # required:<path> family (ruleset 1.1.0)
    "header",
    "research",
    "pi",
    "pi:training",
    "participant:training",
    "animals:totals-vs-exps",
    "continuation",
    "third-party",
    "colony:no-invasive",
    "term:track",
}

LAW_CRITICAL_REFS = {
    "title:track",
    "euthanasia:overdose-confirm",
    "euthanasia:CO2",        # AVMA 2020 mandatory language; NRC Guide has legal force in Israel
    "severity:monitoring",
    "severity:analgesia",    # §1 Schedule + §23 criminal penalties; error in both profiles
    "endpoints:20%-only",    # Committee-level rejection pattern; warning→error in strict_law
    "endpoints:death-only",   # Death/moribundity as sole endpoint without prior criteria
    "postop:monitoring",      # Survival surgery missing post-op monitoring plan
    "special:neonatal-CO2",   # CO₂ as sole method for neonates (AVMA 50-min requirement)
    "alts:missing",
    "alts:engines",
    "paralytic:without-anesthesia",
    "pain:category-consistency",
    "cosmetics:ban",
    # --- AVMA species-euthanasia matrix rules (P1 epic) ---
    "euthanasia:species-method",      # Unacceptable method for species — error in BOTH profiles
    "euthanasia:conditions-missing",  # Conditionally acceptable without documented conditions
    "euthanasia:displacement-rate",   # CO₂ without displacement rate specified
    "euthanasia:secondary-method",    # CO₂/inhalant without secondary physical confirmation
    "euthanasia:precharged-chamber",  # Pre-charged CO₂ chamber — error in BOTH profiles
    "euthanasia:cervical-weight",     # Cervical dislocation exceeding species weight limit
    "reuse:justification",
    "permits:field-study",
}

ADVISORY_REFS = {
    "title:pilot-label",
    "participant:certified-without-training",
    "scope:pilot-size",
    "sex:rationale",
    "sex:sabv",
    "N:justification-detail",
    "endpoints:generic-consult",
    "surgery:multiple-survival",  # Multiple survival experiments, possible animal reuse
    "N:power-analysis",           # Non-trivial N without power analysis or precedent method
    "alts:queries",
    "alts:conclusion",
    "summaries:scientific-length",
    "summaries:lay-length",
    "special:stereotaxic",
    "special:oncology",
    "special:diabetes",
    "special:biosafety",
    "special:nanomaterials",
    "special:ocular",
    "vet:consultation",           # Severity 4-5 requires documented vet consultation
    "deprivation:protocol",       # Food/water deprivation needs weight monitoring + endpoints
    "gma:ibc",                    # Genetically modified animals may need IBC approval
    "ascites:in-vitro",           # Ascites method requires in vitro alternatives justification
    "colony:breeding-plan",       # Colony protocols require colony management plan
    "housing:density",
    "restraint:duration",
}

def lint(instance: Dict[str, Any], profile: str = "default") -> Dict[str, Any]:
    """
    Run deterministic checks on a concrete instance.

    This is not a full JSON Schema validator – it assumes the basic shape is already OK.
    It focuses on the cross-field logic and domain rules that typically break in raw requests.

    Profiles:
    - "default": only structural + clear law minima increment the global error counter.
    - "strict_law": selected law-critical checks (e.g. alternatives search) are upgraded from warnings to errors.
    """
    if profile not in ("default", "strict_law"):
        profile = "default"

    ctx = RuleContext(instance=instance, profile=profile)

    header.run(ctx)

    animals.run(ctx)

    euthanasia.run(ctx)

    endpoints_pain.run(ctx)

    alternatives.run(ctx)

    endpoints_pain.run_cosmetics_endpoints(ctx)

    husbandry.run_surgery(ctx)

    misc_exp.run_vet_consultation(ctx)

    husbandry.run(ctx)

    misc_exp.run(ctx)

    colony.run_breeding_plan(ctx)

    specialty.run(ctx)

    colony.run_no_invasive(ctx)

    summaries.run(ctx)

    exps, exp_signals, total_n_all = ctx.exps, ctx.exp_signals, ctx.total_n_all

    status = "pass" if ctx.errors == 0 else "fail"

    # Feature extraction layer: high-level signals for LLM and dashboards.
    # These avoid re-walking the instance when building prompts or visualizations.
    sexes_seen: set = set()
    for e in exps:
        a = e.get("animals") or {}
        sex = a.get("sex")
        if isinstance(sex, str) and sex:
            sexes_seen.add(sex)

    alts = instance.get("alternatives_search") or {}
    engines = alts.get("engines") or []
    queries = alts.get("queries") or []
    conclusion = (alts.get("conclusion") or "").strip()

    single_sex_design = sexes_seen in ({"M"}, {"F"})
    analysis = {
        "summary": {
            "N_total_all_experiments": total_n_all,
            "num_experiments": len(exps),
            "sexes_seen": sorted(sexes_seen),
            "single_sex_design": single_sex_design,
            "is_colony": bool(instance.get("is_colony")),
        },
        "alternatives": {
            "present": bool(alts),
            "engines_count": len(engines),
            "queries_count": len(queries),
            "conclusion_length": len(conclusion),
        },
        "experiments": exp_signals,
    }

    # Summaries by category for downstream analysis (does not affect status).
    structural_errors = 0
    law_critical_errors = 0
    advisory_warnings = 0

    def ref_matches(ref: str, ref_set: set) -> bool:
        """Check if ref matches any pattern in ref_set (exact match or prefix before :exp-)."""
        if ref in ref_set:
            return True
        if ref.startswith("required:") and "required" in ref_set:  # ruleset 1.1.0: missing-field rows are structural
            return True
        # Handle experiment-suffixed refs like "euthanasia:CO2:exp-1"
        if ":exp-" in ref:
            base_ref = ref.rsplit(":exp-", 1)[0]
            return base_ref in ref_set
        return False

    for c in ctx.checks:
        if c.get("status") != "fail":
            continue
        ref = c.get("reference") or ""
        sev = c.get("severity") or "error"
        if ref_matches(ref, STRUCTURAL_REFS) and sev == "error":
            structural_errors += 1
        elif ref_matches(ref, LAW_CRITICAL_REFS) and sev == "error":
            law_critical_errors += 1
        elif ref_matches(ref, ADVISORY_REFS) and sev != "error":
            advisory_warnings += 1

    report = {
        "status": status,
        "profile": profile,
        "errors": ctx.errors,
        "warnings": ctx.warnings,
        "structural_errors": structural_errors,
        "law_critical_errors": law_critical_errors,
        "advisory_warnings": advisory_warnings,
        "analysis": analysis,
        "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "checklist": ctx.checks,
    }
    return apply_pack(annotate_report(report))


def _row(cells: List[Any], even_idx: int = 0) -> str:
    tds = []
    for i, c in enumerate(cells):
        cls = ' class="even"' if i == even_idx else ""
        tds.append(f"<td{cls}>{_e(c)}</td>")
    return "<tr>" + "".join(tds) + "</tr>"

def render_html(instance: Dict[str, Any], out_html_path: str = None, with_refs: bool = False) -> str:
    """
    Render a schema instance to Council-style RTL HTML.

    If out_html_path is given, writes the file and returns the HTML string.
    If with_refs is True, adds data-ref attributes to major sections for error mapping.
    """
    header = instance.get("header") or {}
    research = instance.get("research") or {}
    pi = instance.get("pi") or {}
    participants = instance.get("participants") or []
    animals_total = instance.get("animals_total") or []
    n_just = instance.get("n_justification") or {}
    summaries = instance.get("summaries") or {}
    alts = instance.get("alternatives_search") or {}
    exps = instance.get("experiments") or []
    pm = instance.get("postmortem_processing") or {}
    pi_decl = instance.get("pi_declaration") or {}
    chair = instance.get("chair_statement") or {}

    def _ref(ref_name: str) -> str:
        """Return data-ref attribute if with_refs is True."""
        return f' data-ref="{ref_name}"' if with_refs else ""

    H: List[str] = []
    H.append('<html lang="he"><head><meta charset="utf-8"/>')
    H.append("<title>Experiment Request</title>")
    H.append(f"<style>{CSS}</style></head><body>")
    H.append("<div>")
    H.append(f'<div class="header"{_ref("header")}>')
    H.append(
        f'<div>בקשת ניסוי מס <span>{_e(header.get("protocol_id", ""))}</span></div><br/>'
    )
    H.append(
        f'<div>שם המוסד - <span>{_e(header.get("institution", ""))}</span></div>'
    )
    H.append("</div>")  # header

    H.append('<div class="content">')

    # --- Research section ---
    H.append(f'<div class="section"{_ref("research")}>')
    H.append('<div class="sub-header">המחקר</div>')
    H.append('<div class="table vertical"><table><tbody>')
    H.append(
        _row(
            [
                "נושא המחקר בעברית",
                research.get("title_he", ""),
            ]
        )
    )
    H.append(
        _row(
            [
                "נושא המחקר באנגלית",
                research.get("title_en", ""),
            ]
        )
    )
    H.append(
        _row(
            [
                "האם זה מחקר המשך?",
                "המשך" if research.get("is_continuation") else "חדש",
            ]
        )
    )
    if research.get("is_continuation"):
        H.append(
            _row(
                [
                    "סיבה למחקר המשך",
                    research.get("continuation_reason", ""),
                ]
            )
        )
        H.append(
            _row(
                [
                    "ציין את מס' הבקשה הקודם",
                    research.get("prior_protocol_id", ""),
                ]
            )
        )
    H.append(
        _row(
            [
                "המחקר הוא מחקר שרות עבור מוסד צד ג?",
                "כן" if research.get("third_party_service") else "לא",
            ]
        )
    )
    term = research.get("approval_term_years")
    if term == 1:
        term_str = "שנה"
    elif isinstance(term, int):
        term_str = f"{term} שנים"
    else:
        term_str = ""
    H.append(_row(["תוקף האישור המבוקש (שנים)", term_str]))
    H.append(
        _row(
            [
                "אתר ביצוע המחקר",
                ", ".join(s.get("name", "") for s in research.get("sites") or []),
            ]
        )
    )
    H.append("</tbody></table></div>")
    if research.get("primary_purpose") or research.get("secondary_purpose"):
        H.append('<div class="table vertical"><table><tbody>')
        if research.get("primary_purpose"):
            H.append(_row(["מטרה ראשית", research["primary_purpose"]]))
        if research.get("secondary_purpose"):
            H.append(_row(["מטרה משנית", research["secondary_purpose"]]))
        H.append("</tbody></table></div>")
    H.append("</div>")  # close research section
    H.append('<p style="page-break-after: always;"></p>')

    # --- PI section ---
    H.append(f'<div class="section"{_ref("pi")}>')
    H.append('<div class="sub-header">החוקר הראשי</div>')
    H.append('<div class="table vertical"><table><tbody>')
    H.append(
        "<tr>"
        f'<td class="even" style="width:20%">סוג זהוי</td>'
        f"<td>{_e('ת.ז.' if pi.get('id_type') == 'TZ' else 'דרכון')}</td>"
        f'<td class="even" style="width:20%">מספר זהוי</td>'
        f"<td>{_e(pi.get('id_number', ''))}</td>"
        "</tr>"
    )
    H.append(
        _row(
            [
                "שם משפחה בעברית",
                pi.get("last_name_he", ""),
                "שם פרטי בעברית",
                pi.get("first_name_he", ""),
            ]
        )
    )
    H.append(
        _row(
            [
                "שם משפחה באנגלית",
                pi.get("last_name_en", ""),
                "שם פרטי באנגלית",
                pi.get("first_name_en", ""),
            ]
        )
    )
    H.append(
        _row(
            [
                "שם המוסד",
                header.get("institution", ""),
                "",
                "",
            ]
        )
    )
    H.append(
        _row(
            [
                "תאריך לידה",
                "",
                "דואר אלקטרוני",
                pi.get("email", ""),
            ]
        )
    )
    H.append(
        _row(
            [
                "טלפון נייד",
                pi.get("phone_primary", ""),
                "טלפון נוסף",
                pi.get("phone_secondary", ""),
            ]
        )
    )
    H.append(
        _row(
            [
                "מס' הסמכה במוסד המחקר",
                pi.get("institutional_cert_no", ""),
                "תת ועדה",
                header.get("subcommittee", ""),
            ]
        )
    )
    H.append(
        _row(
            [
                "פקולטה",
                pi.get("faculty", ""),
                "מחלקה",
                pi.get("department", ""),
            ]
        )
    )
    H.append("</tbody></table></div>")

    # PI training
    if pi.get("training"):
        H.append('<div class="table-header">הכשרות החוקר</div>')
        H.append('<div class="table horizontal"><table><tbody>')
        H.append(
            "<tr>"
            "<th>מס' תעודה</th><th>מוסד נותן התעודה</th>"
            "<th>סוג בע\"ח</th><th>תאריך תעודה</th>"
            "</tr>"
        )
        for row in pi["training"]:
            H.append(
                _row(
                    [
                        row.get("cert_no", ""),
                        row.get("issuer", ""),
                        row.get("animal_scope", ""),
                        row.get("date", ""),
                    ],
                    even_idx=0,
                )
            )
        H.append("</tbody></table></div>")

    H.append("</div>")  # close PI section
    H.append('<p style="page-break-after: always;"></p>')

    # --- Participants ---
    if participants:
        H.append(f'<div class="section"{_ref("participants")}>')
        H.append('<div class="sub-header">משתתפים במחקר והכשרותיהם</div>')
        for idx, p in enumerate(participants, start=1):
            H.append(f'<div class="table-header">משתתף מס  {idx}:</div>')
            H.append('<div class="table horizontal"><table><tbody>')
            H.append(
                "<tr>"
                "<th>שם משפחה</th><th>שם פרטי</th>"
                "<th>מספר ת.ז / דרכון</th><th>קשר למחקר</th><th>מוסמך</th>"
                "</tr>"
            )
            role = p.get("role")
            if role == "performs_procedures":
                role_he = "עובד עם בעל חיים בניסוי"
            elif role == "participant":
                role_he = "משתתף בניסוי"
            elif role == "PI":
                role_he = "חוקר ראשי"
            else:
                role_he = role or ""
            H.append(
                _row(
                    [
                        p.get("family_name", ""),
                        p.get("given_name", ""),
                        p.get("national_id_or_passport", ""),
                        role_he,
                        "כן" if p.get("certified") else "לא",
                    ]
                )
            )
            H.append("</tbody></table></div>")
            if p.get("training"):
                H.append('<div class="table-header">הכשרות</div>')
                H.append('<div class="table horizontal"><table><tbody>')
                H.append(
                    "<tr>"
                    "<th>מס'</th><th>מס' תעודה</th><th>מוסד נותן תעודה</th><th>סוג בע\"ח</th>"
                    "</tr>"
                )
                for j, t in enumerate(p["training"], start=1):
                    H.append(
                        _row(
                            [
                                j,
                                t.get("cert_no", ""),
                                t.get("issuer", ""),
                                t.get("animal_scope", ""),
                            ]
                        )
                    )
                H.append("</tbody></table></div>")

        H.append("</div>")  # close participants section
        H.append('<p style="page-break-after: always;"></p>')

    # --- Animals totals ---
    if animals_total:
        H.append(f'<div class="section"{_ref("animals-totals")}>')
        H.append('<div class="sub-header">בעלי החיים הדרושים למחקר</div>')
        H.append('<div class="table horizontal"><table><tbody>')
        H.append(
            "<tr>"
            "<th>מין מובנה</th><th>מין</th><th>זן/קווים</th><th>סטטוס גנטי</th>"
            "<th>זוויג</th><th>גיל</th><th>כמות</th><th>מקור</th>"
            "</tr>"
        )
        for t in animals_total:
            H.append(
                _row(
                    [
                        t.get("species_standard", ""),
                        t.get("species", ""),
                        t.get("strain", ""),
                        t.get("genetic_status", ""),
                        t.get("sex", ""),
                        t.get("age", ""),
                        t.get("n_total", ""),
                        t.get("source", ""),
                    ]
                )
            )
        H.append("</tbody></table></div>")
        H.append("</div>")  # close animals-totals section

    # Justification and summaries
    H.append(f'<div class="section"{_ref("summaries")}>')
    H.append('<div class="sub-header">נימוק למספר בעלי החיים</div>')
    H.append(
        '<div class="table"><div>'
        f'{_e(n_just.get("method", ""))}: {_e(n_just.get("details", ""))}'
        "</div></div>"
    )

    H.append('<div class="sub-header">תקציר מדעי (EN)</div>')
    H.append(
        '<div class="table"><div>'
        f'{_e(summaries.get("scientific_en_≤300w", ""))}'
        "</div></div>"
    )

    H.append('<div class="sub-header">תקציר לקהל הרחב (HE)</div>')
    H.append(
        '<div class="table"><div>'
        f'{_e(summaries.get("lay_he_≤150w", ""))}'
        "</div></div>"
    )

    H.append("</div>")  # close summaries section

    # Alternatives
    if alts:
        H.append(f'<div class="section"{_ref("alternatives")}>')
        H.append('<div class="sub-header">חיפוש חלופות</div>')
        H.append(
            '<div class="table"><div>מנועים: '
            + _e(", ".join(alts.get("engines") or []))
            + "</div></div>"
        )
        H.append(
            '<div class="table"><div>תאריך: '
            + _e(alts.get("date", ""))
            + "</div></div>"
        )
        if alts.get("queries"):
            H.append(
                '<div class="table"><div>שאילתות: '
                + _e("; ".join(alts.get("queries") or []))
                + "</div></div>"
            )
        H.append(
            '<div class="table"><div>מסקנה: '
            + _e(alts.get("conclusion", ""))
            + "</div></div>"
        )
        prelim = alts.get("preliminary_experiments") or {}
        if prelim.get("had_alternative_methods") is not None or prelim.get("details"):
            H.append('<div class="sub-header">ניסויים מקדימים בשיטות חלופיות</div>')
            H.append('<div class="table"><div>')
            if prelim.get("had_alternative_methods") is not None:
                H.append(
                    f'האם היו שלבים בשיטות חלופיות: {"כן" if prelim["had_alternative_methods"] else "לא"}'
                )
            if prelim.get("details"):
                H.append(f'<br>{_e(prelim["details"])}')
            H.append("</div></div>")
        H.append("</div>")  # close alternatives section

    # --- Experiments ---
    for idx, e in enumerate(exps, start=1):
        H.append('<p style="page-break-after: always;"></p>')
        H.append(f'<div class="section experiment"{_ref(f"experiment-{idx}")}>')
        H.append(f'<div class="sub-header">ניסוי {idx}</div>')

        if e.get("question"):
            H.append(
                '<div class="table"><div class="table-header">'
                "שאלת המחקר הספציפית"
                "</div></div>"
            )
            H.append(
                '<div class="table"><div>'
                f'{_e(e["question"])}'
                "</div></div>"
            )

        # Animals table
        a = e.get("animals") or {}
        age = a.get("age") or {}
        age_str = f'{age.get("value", "")} {age.get("unit", "")}'.strip()
        H.append('<div class="table horizontal"><table><tbody>')
        H.append(
            "<tr>"
            "<th>מין מובנה</th><th>מין</th><th>זן/קווים</th><th>סטטוס גנטי</th>"
            "<th>זוויג</th><th>גיל</th><th>כמות</th><th>מקור</th>"
            "</tr>"
        )
        H.append(
            _row(
                [
                    a.get("species_standard", ""),
                    a.get("species", ""),
                    a.get("strain", ""),
                    a.get("genetic_status", ""),
                    a.get("sex", ""),
                    age_str,
                    a.get("n", ""),
                    a.get("source", ""),
                ]
            )
        )
        H.append("</tbody></table></div>")
        # Weight & supplier
        weight = a.get("weight") or {}
        supplier = a.get("supplier", "")
        if weight or supplier:
            parts = []
            if weight:
                parts.append(f'משקל: {weight.get("value", "")} {weight.get("unit", "")}')
            if supplier:
                parts.append(f'ספק: {_e(supplier)}')
            H.append(f'<div class="table"><div>{" | ".join(parts)}</div></div>')
        # Per-group breakdown
        if a.get("groups"):
            H.append('<div class="table horizontal"><table><tbody>')
            H.append(
                "<tr><th>קבוצה</th><th>זן</th><th>שינוי גנטי</th>"
                "<th>כמות</th><th>משקל</th><th>ספק</th></tr>"
            )
            for gi, g in enumerate(a["groups"], 1):
                gw = g.get("weight") or {}
                H.append(
                    _row([
                        gi,
                        g.get("strain", ""),
                        g.get("genetic_modification", ""),
                        g.get("n", ""),
                        f'{gw.get("value", "")} {gw.get("unit", "")}'.strip() if gw else "",
                        g.get("supplier", ""),
                    ])
                )
            H.append("</tbody></table></div>")

        # Housing
        h = e.get("housing") or {}
        H.append('<div class="table horizontal"><table><tbody>')
        H.append(
            "<tr>"
            "<th>שיכון</th><th>העשרה</th>"
            "<th>סיבת שיכון בודד</th><th>משך שיכון בודד (ימים)</th>"
            "</tr>"
        )
        H.append(
            _row(
                [
                    "קבוצתי" if h.get("group_housed") else "בודד",
                    h.get("enrichment", ""),
                    h.get("single_housing_reason", ""),
                    h.get("single_housing_duration_days", ""),
                ]
            )
        )
        H.append("</tbody></table></div>")

        # rationale & timeline
        H.append(
            '<div class="table"><div class="table-header">'
            "נימוק לבחירת מין/זן/זוויג"
            "</div></div>"
        )
        H.append(
            '<div class="table"><div>'
            f'{_e(e.get("rationale_species_strain_sex", ""))}'
            "</div></div>"
        )

        if e.get("n_justification_detail"):
            H.append(
                '<div class="table"><div class="table-header">'
                "נימוק למספר בעלי החיים בניסוי"
                "</div></div>"
            )
            H.append(
                '<div class="table"><div>'
                f'{_e(e["n_justification_detail"])}'
                "</div></div>"
            )

        if e.get("regulatory_requirement") is not None:
            H.append(
                '<div class="table"><div>'
                f'מחקר הנובע מצורך רגולטורי: {"כן" if e["regulatory_requirement"] else "לא"}'
                "</div></div>"
            )

        H.append(
            '<div class="table"><div class="table-header">'
            "תיאור הניסוי ולו\"ז"
            "</div></div>"
        )
        H.append('<div class="table horizontal"><table><tbody>')
        H.append(
            "<tr>"
            "<th>זמן/יום</th><th>שלב</th><th>מסלול/איבר</th>"
            "<th>נפח/מינון</th><th>מכשור/חומר</th>"
            "</tr>"
        )
        for step in e.get("procedure_timeline") or []:
            H.append(
                _row(
                    [
                        step.get("day_or_timepoint", ""),
                        step.get("step", ""),
                        step.get("route_or_site", ""),
                        step.get("volume_or_dose", ""),
                        step.get("device_or_material", ""),
                    ]
                )
            )
        H.append("</tbody></table></div>")

        # Analgesia
        if e.get("analgesia_used") is not None or e.get("analgesia"):
            H.append('<div class="table-header">משככי כאבים (Analgesia)</div>')
            if e.get("analgesia_used") is not None:
                H.append(
                    '<div class="table"><div>'
                    f'שימוש במשככי כאבים: {"כן" if e["analgesia_used"] else "לא"}'
                    "</div></div>"
                )
            if not e.get("analgesia_used") and e.get("analgesia_justification_for_omission"):
                H.append(
                    '<div class="table"><div>'
                    f'סיבה לאי שימוש: {_e(e["analgesia_justification_for_omission"])}'
                    "</div></div>"
                )
            if e.get("analgesia"):
                H.append('<div class="table horizontal"><table><tbody>')
                H.append(
                    "<tr>"
                    "<th>Phase</th><th>Agent</th><th>Dose</th><th>Route</th><th>Frequency</th>"
                    "</tr>"
                )
                for row in e["analgesia"]:
                    H.append(
                        _row(
                            [
                                row.get("phase", ""),
                                row.get("agent", ""),
                                row.get("dose", ""),
                                row.get("route", ""),
                                row.get("frequency", ""),
                            ]
                        )
                    )
                H.append("</tbody></table></div>")

        # Anesthesia
        if e.get("anesthesia_used") is not None and not e.get("anesthesia") and not e.get("anesthesia_drugs"):
            H.append('<div class="table-header">חומרי הרדמה (Anesthesia)</div>')
            H.append(
                '<div class="table"><div>'
                f'שימוש בחומרי הרדמה: {"כן" if e["anesthesia_used"] else "לא"}'
                "</div></div>"
            )
        if e.get("anesthesia"):
            H.append('<div class="table-header">Anesthesia</div>')
            H.append('<div class="table horizontal"><table><tbody>')
            H.append(
                "<tr>"
                "<th>Agent</th><th>Induction</th><th>Maintenance</th>"
                "<th>Route</th><th>Monitoring</th>"
                "</tr>"
            )
            for row in e["anesthesia"]:
                H.append(
                    _row(
                        [
                            row.get("agent", ""),
                            row.get("induction", ""),
                            row.get("maintenance", ""),
                            row.get("route", ""),
                            row.get("monitoring", ""),
                        ]
                    )
                )
            H.append("</tbody></table></div>")

        if e.get("anesthesia_drugs"):
            H.append('<div class="table-header">Structured Anesthesia Drugs</div>')
            H.append('<div class="table horizontal"><table><tbody>')
            H.append(
                "<tr>"
                "<th>Agent</th><th>Dose</th><th>Route</th><th>Frequency</th>"
                "<th>Rationale</th><th>Monitoring</th>"
                "</tr>"
            )
            for row in e["anesthesia_drugs"]:
                H.append(
                    _row(
                        [
                            row.get("agent", ""),
                            row.get("dose", ""),
                            row.get("route", ""),
                            row.get("frequency", ""),
                            row.get("rationale", ""),
                            row.get("monitoring", ""),
                        ]
                    )
                )
            H.append("</tbody></table></div>")

        # Severity & monitoring
        mon = e.get("monitoring") or {}
        H.append(f'<div class="monitoring"{_ref(f"monitoring-{idx}")}>')
        H.append('<div class="table horizontal"><table><tbody>')
        H.append(
            "<tr>"
            "<th>דרגת כאב וסבל</th><th>ניטור 72ש ראשונות</th>"
            "<th>ניטור שבועי</th><th>פרמטרים</th><th>קטגוריית כאב</th>"
            "</tr>"
        )
        H.append(
            _row(
                [
                    e.get("severity_level_1_to_5", ""),
                    "כן" if mon.get("initial_72h_daily") else "לא",
                    mon.get("ongoing_per_week", ""),
                    ", ".join(mon.get("parameters") or []),
                    e.get("pain_category", ""),
                ]
            )
        )
        H.append("</tbody></table></div>")
        H.append("</div>")  # close monitoring

        # Endpoints
        he = e.get("humane_endpoints") or {}
        H.append('<div class="table-header">נקודות סיום הומאניות</div>')
        if he.get("general"):
            H.append(
                '<div class="table"><div>כלליות: '
                + _e("; ".join(he.get("general") or []))
                + "</div></div>"
            )
        if he.get("specific"):
            H.append(
                '<div class="table"><div>ספציפיות: '
                + _e("; ".join(he.get("specific") or []))
                + "</div></div>"
            )

        # Euthanasia
        eu = e.get("euthanasia") or {}
        H.append(f'<div class="euthanasia"{_ref(f"euthanasia-{idx}")}>')
        H.append('<div class="table-header">שיטת המתה</div>')
        H.append('<div class="table horizontal"><table><tbody>')
        H.append(
            "<tr><th>שיטה מובנית</th><th>ראשית</th><th>פרמטרים</th><th>תנאים</th><th>אישור מוות</th></tr>"
        )
        H.append(
            _row(
                [
                    eu.get("method_standard", ""),
                    eu.get("primary", ""),
                    eu.get("parameters", ""),
                    eu.get("conditions_text", ""),
                    eu.get("confirmation", ""),
                ]
            )
        )
        H.append("</tbody></table></div>")
        H.append("</div>")  # close euthanasia

        # Specialty mini-blocks
        def render_kv_block(title: str, data: Dict[str, Any]) -> None:
            if not data:
                return
            H.append(f'<div class="table-header">{_e(title)}</div>')
            H.append('<div class="table"><div>')
            for k, v in data.items():
                H.append(f"<div><b>{_e(k)}:</b> {_e(v)}</div>")
            H.append("</div></div>")

        render_kv_block("Stereotaxic / Implant", e.get("stereotaxic_implant") or {})
        render_kv_block("Oncology", e.get("oncology") or {})
        render_kv_block("Diabetes", e.get("diabetes") or {})
        render_kv_block(
            "Biosafety & Infectious Agents",
            e.get("biosafety_infectious_agents") or {},
        )
        render_kv_block("Nanomaterials", e.get("nanomaterials") or {})
        render_kv_block("Ocular Procedures", e.get("ocular_procedures") or {})
        render_kv_block("Housing Density", e.get("housing_density") or {})
        render_kv_block("Restraint", e.get("restraint") or {})
        render_kv_block("Reuse Review", e.get("reuse_review") or {})
        render_kv_block("Field Study Permits", e.get("field_study_permits") or {})

        # Fate
        H.append('<div class="table-header">מצב אחרי הניסוי</div>')
        H.append(
            '<div class="table"><div>'
            f'{_e(e.get("fate", ""))}'
            "</div></div>"
        )
        H.append("</div>")  # close experiment section

    # --- Postmortem processing ---
    if pm.get("used"):
        H.append('<div class="sub-header">עיבוד לאחר המתה</div>')
        H.append(
            '<div class="table"><div>Perfusion: '
            + _e(pm.get("perfusion", ""))
            + "</div></div>"
        )
        H.append(
            '<div class="table"><div>Fixation: '
            + _e(pm.get("fixation", ""))
            + "</div></div>"
        )
        H.append(
            '<div class="table"><div>Technique: '
            + _e(pm.get("clearing_or_special_technique", ""))
            + "</div></div>"
        )
        H.append(
            '<div class="table"><div>Safety: '
            + _e(pm.get("chemical_safety_notes", ""))
            + "</div></div>"
        )

    # --- PI declaration ---
    H.append('<div class="sub-header">הצהרת החוקר</div>')
    H.append(
        '<div class="table"><div>שם: ' + _e(pi_decl.get("name", "")) + "</div></div>"
    )
    H.append(
        '<div class="table"><div>תאריך: '
        + _e(pi_decl.get("date", ""))
        + "</div></div>"
    )

    # --- Chair statement ---
    if chair.get("decision") or chair.get("comments"):
        H.append('<div class="sub-header">החלטת יו"ר</div>')
        H.append(
            '<div class="table"><div>החלטה: '
            + _e(chair.get("decision", ""))
            + "</div></div>"
        )
        H.append(
            '<div class="table"><div>הערות: '
            + _e(chair.get("comments", ""))
            + "</div></div>"
        )

    H.append("</div></div></body></html>")
    html_str = "".join(H)

    if out_html_path:
        Path(out_html_path).write_text(html_str, encoding="utf-8")
    return html_str


def render_html_with_refs(instance: Dict[str, Any], out_html_path: str = None) -> str:
    """
    Convenience wrapper that renders HTML with data-ref attributes for web UI error mapping.
    """
    return render_html(instance, out_html_path, with_refs=True)


def _load_json(path: str) -> Dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))

def _save_json(obj: Any, path: str) -> None:
    Path(path).write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Lint and/or render IACUC_SCHEMA_V2 JSON instances."
    )
    parser.add_argument("mode", choices=["lint", "render", "both"])
    parser.add_argument("instance", help="Path to JSON instance file.")
    parser.add_argument(
        "--profile",
        choices=["default", "strict_law"],
        default="default",
        help=(
            "Linting profile: 'default' (structural + minimal law) or "
            "'strict_law' (upgrade law-critical checks such as alternatives search to errors)."
        ),
    )
    parser.add_argument("--report", default="lint_report.json")
    parser.add_argument("--html", default="render.html")
    args = parser.parse_args()

    instance = _load_json(args.instance)

    if args.mode in ("lint", "both"):
        rep = lint(instance, profile=args.profile)
        _save_json(rep, args.report)
        print(
            f"[lint] status={rep['status']} errors={rep['errors']} warnings={rep['warnings']} "
            f"report={args.report}"
        )

    if args.mode in ("render", "both"):
        out = render_html(instance, args.html)
        print(f"[render] wrote {args.html} ({len(out)} bytes)")


if __name__ == "__main__":
    main()
