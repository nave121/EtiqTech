"""Severity / pain / endpoints rules: severity:monitoring, severity:analgesia,
paralytic:without-anesthesia, pain:category-consistency, cosmetics:ban,
endpoints:generic-consult, endpoints:20%-only. Verbatim move from
linter_renderer.lint() (P3.1 batch 4).

Two entry points because the alternatives block (batch 5) sits between
pain:category-consistency and cosmetics:ban in source order; a single run()
would reorder checklist rows. invasive_keywords is published to
ctx.invasive_keywords where it is defined and read back from ctx at the
pain:category-consistency site.
"""
import re

from .context import RuleContext, _rule
from .helpers import _anesthesia_text, _flatten_text, _mentions, _monitoring_text, _pain_category

# Checks more often than once a week, in English or Hebrew: once a week alone is not enough at severity >=4
# (committee letters). "יומי" not followed by "ים" is daily ("יומיים" is every two days); hours stop below a week.
# shortcut: matches frequency words, not what is checked ("daily dose" passes); upgrade if feedback shows false passes.
_HOURS = r"(?:16[0-7]|1[0-5]\d|[1-9]?\d)(?:\.\d+)?(?!\d)"  # 0-167
_DAYS = r"[1-6](?!\d)"
_TO = r"\s*(?:-|–|to|עד)\s*"
_CHECK_FREQUENCY = re.compile(
    rf"\b(?:daily|hourly|q(?:[1-9]|1\d|2[0-4])h)\b|\balternate days?\b"
    rf"|\b(?:every|each) (?:day|morning|evening|night|other day|(?:second|third|2nd|3rd) day|(?:two|three|four|five|six) days)\b"
    rf"|\b(?:every|each) {_HOURS}(?:{_TO}{_HOURS})?\s*(?:h|hrs?|hours?)\b|\b(?:every|each) {_DAYS}(?:{_TO}{_DAYS})? days?\b"
    rf"|\b(?:once|one time|1 ?x) ?(?:/ ?|a |per |each )?day\b"
    rf"|\b(?:twice|thrice|(?:two|three|four|several|multiple) times|(?:[2-9]|[1-9]\d) ?(?:x|times))[ -]?(?:/ ?|a |per |each )?(?:day|week)(?:ly)?\b"
    rf"|(?<![א-ת])[הובלמשכ]?יומי(?!ים)"
    rf"|(?:כל|מדי|מידי) (?:יום(?! (?:ראשון|שני|שלישי|רביעי|חמישי|שישי|שבת))|יממה|בוקר|ערב|שעה|שעתיים|{_HOURS}(?:{_TO}{_HOURS})? שעות)"
    rf"|(?:(?:כל|מדי|מידי) |אחת ל|פעם ב)(?:יומיים|(?:שלושה|ארבעה|חמישה|שישה|{_DAYS}(?:{_TO}{_DAYS})?) ימים)"
    rf"|(?:פעם|פעמיים|שלוש פעמים|\d+ פעמים) ב(?:יום|יממה)|(?:פעמיים|שלוש פעמים|ארבע פעמים|(?:[2-9]|[1-9]\d) פעמים) בשבוע"
)


def run(ctx: RuleContext) -> None:
    exps = ctx.exps
    exp_signals = ctx.exp_signals
    profile = ctx.profile
    # --- severity vs monitoring ---
    # Ruleset 1.3.0 (maintainer decision): severity >=4 must say how often animals are checked, in the monitoring
    # or humane-endpoints text or the export's 72h / weekly cells. No monitoring text at all stays an error.
    for idx, e in enumerate(exps, start=1):
        sev = e.get("severity_level_1_to_5")
        mon = e.get("monitoring") or {}
        if isinstance(sev, int) and sev >= 4:
            mon_text = _monitoring_text(mon)
            per_week = mon.get("ongoing_per_week")
            stated = (
                mon.get("initial_72h_daily") is True
                or (isinstance(per_week, (int, float)) and per_week >= 2)
                or bool(_CHECK_FREQUENCY.search(mon_text + " " + _flatten_text(e.get("humane_endpoints")).lower()))
            )
            # A schedule cell, even once a week, is a plan: "no monitoring plan" means no text and no cell.
            no_plan = not stated and not mon_text.strip() and per_week is None and mon.get("initial_72h_daily") is None
            severity = "error" if no_plan or profile == "strict_law" else "warning"
            ctx.checks.append(
                _rule(
                    stated,
                    f"Experiment {idx}: severity≥4 monitoring states how often animals are checked.",
                    f"Experiment {idx}: severity≥4 has no monitoring plan." if no_plan
                    else f"Experiment {idx}: severity≥4 monitoring does not say how often animals are checked "
                    "(once a week alone is not enough).",
                    fix=(
                        "State how often animals are checked. Committees expect frequent early checks (daily or "
                        "every 12-48 h after the intervention) and a stated schedule afterwards."
                    ),
                    severity=severity,
                    ref=f"severity:monitoring:exp-{idx}",
                )
            )
            if not stated:
                if severity == "error":
                    ctx.errors += 1
                else:
                    ctx.warnings += 1

    # --- analgesia presence for invasive, moderate-severity work (soft) ---
    invasive_keywords = [
        "surgery",
        "operation",
        "incision",
        "crush",
        "optic nerve",
        "flap",
        "wound",
        "craniotomy",
        "laparotomy",
        "stereotax",
        "implant",
    ]
    ctx.invasive_keywords = invasive_keywords
    for idx, e in enumerate(exps, start=1):
        sev = e.get("severity_level_1_to_5")
        if not isinstance(sev, int) or sev < 3:
            continue
        label = (e.get("label") or "") + " " + (e.get("question") or "")
        timeline_txt = " ".join(
            (step.get("step") or "") for step in e.get("procedure_timeline") or []
        )
        joined = (label + " " + timeline_txt).lower()
        invasive = any(k in joined for k in invasive_keywords)
        if not invasive:
            continue
        analgesia_rows = e.get("analgesia") or []
        has_analgesia = any((row.get("agent") or "").strip() for row in analgesia_rows)
        # Feature signal: record analgesia presence per experiment.
        if 1 <= idx <= len(exp_signals):
            exp_signals[idx - 1]["has_analgesia"] = has_analgesia
        if not has_analgesia:
            fix_an = (
                "Add peri- and post-operative analgesia (agent, dose, route, frequency) "
                "for invasive, severity≥3 procedures, or document a strong justification "
                "for omitting analgesics (especially for severity grades 4–5)."
            )
            sev_msg = (
                f"Experiment {idx}: severity≥3 with invasive steps but no analgesia entries."
            )
            # Israeli law §1 Schedule: experiments causing pain must use anesthesia/analgesia.
            # §23: criminal penalties for non-compliance. Error in both profiles.
            ctx.checks.append(
                _rule(
                    False,
                    "",
                    sev_msg,
                    fix=fix_an,
                    severity="error",
                    ref=f"severity:analgesia:exp-{idx}",
                )
            )
            ctx.errors += 1

    # --- paralytic agents without concurrent anesthesia (law-critical) ---
    paralytic_keywords = [
        "vecuronium",
        "rocuronium",
        "pancuronium",
        "cisatracurium",
        "atracurium",
        "succinylcholine",
        "neuromuscular blocker",
        "paraly",
        "muscle relaxant",
    ]
    anesthesia_keywords = [
        "isoflurane",
        "sevoflurane",
        "ketamine",
        "xylazine",
        "propofol",
        "pentobarbital",
        "anesthe",
        "general anesthesia",
        "general anaesthesia",
    ]
    for idx, e in enumerate(exps, start=1):
        timeline_txt = " ".join(
            (step.get("step") or "") for step in e.get("procedure_timeline") or []
        ).lower()
        anesthesia_txt = _anesthesia_text(e)
        joined = " ".join(
            [
                (e.get("label") or "").lower(),
                (e.get("question") or "").lower(),
                timeline_txt,
                anesthesia_txt,
            ]
        )
        has_paralytic = any(kw in joined for kw in paralytic_keywords)
        if not has_paralytic:
            continue
        has_general_anesthesia = any(
            kw in anesthesia_txt or kw in timeline_txt for kw in anesthesia_keywords
        )
        if not has_general_anesthesia:
            ctx.checks.append(
                _rule(
                    False,
                    "",
                    f"Experiment {idx}: paralytic agent detected without documented concurrent general anesthesia.",
                    fix=(
                        "Document the concurrent general anesthetic agent, dose, route, and monitoring "
                        "plan whenever paralytic or neuromuscular-blocking agents are used."
                    ),
                    severity="error" if profile == "strict_law" else "warning",
                    ref=f"paralytic:without-anesthesia:exp-{idx}",
                )
            )
            if profile == "strict_law":
                ctx.errors += 1
            else:
                ctx.warnings += 1

    # --- pain/severity category consistency (law-critical) ---
    moderate_burden_keywords = ctx.invasive_keywords + [
        "fracture",
        "nerve crush",
        "tumor implant",
        "tumour implant",
        "xenograft",
        "restraint",
        "food deprivation",
        "water restriction",
    ]
    severe_burden_keywords = [
        "thoracotomy",
        "amputation",
        "spinal cord",
        "burn",
        "sepsis",
        "stroke",
        "neuropathic pain",
        "ulceration",
        "death endpoint",
    ]
    for idx, e in enumerate(exps, start=1):
        sev = e.get("severity_level_1_to_5")
        joined = " ".join(
            [
                (e.get("label") or "").lower(),
                (e.get("question") or "").lower(),
                " ".join((step.get("step") or "") for step in e.get("procedure_timeline") or []).lower(),
            ]
        )
        has_moderate_burden = _mentions(joined, moderate_burden_keywords)
        has_severe_burden = _mentions(joined, severe_burden_keywords)
        pain_category = _pain_category(e)
        if pain_category:
            underclassified = (
                (pain_category in {"B", "C"} and (has_moderate_burden or has_severe_burden))
                or (pain_category == "D" and has_severe_burden)
            )
        else:
            if not isinstance(sev, int):
                continue
            underclassified = (
                (sev <= 2 and has_moderate_burden)
                or (sev <= 3 and has_severe_burden)
            )
        if not underclassified:
            continue
        ctx.checks.append(
            _rule(
                False,
                "",
                f"Experiment {idx}: declared severity/pain category appears too low for the described procedures.",
                fix=(
                    "Reassess pain_category and/or severity_level_1_to_5 and align them with the "
                    "actual procedure burden, monitoring plan, analgesia strategy, and humane endpoints."
                ),
                severity="error" if profile == "strict_law" else "warning",
                ref=f"pain:category-consistency:exp-{idx}",
            )
        )
        if profile == "strict_law":
            ctx.errors += 1
        else:
            ctx.warnings += 1


def run_cosmetics_endpoints(ctx: RuleContext) -> None:
    instance = ctx.instance
    exps = ctx.exps
    exp_signals = ctx.exp_signals
    profile = ctx.profile
    # --- cosmetics / cleaning-products testing ban (law-critical) ---
    cosmetics_keywords = [
        "cosmetic",
        "cosmetics",
        "makeup",
        "mascara",
        "lipstick",
        "skin cream",
        "shampoo",
        "toothpaste",
        "household cleaner",
        "cleaning product",
        "cleaning products",
        "personal care product",
        "personal care products",
        "קוסמט",
        "איפור",
        "שמפו",
        "משחת שיניים",
        "חומרי ניקוי",
        "מוצרי ניקוי",
        "מוצרי קוסמטיקה",
    ]
    protocol_text = " ".join(
        [
            _flatten_text(instance.get("research")),
            _flatten_text(instance.get("summaries")),
            _flatten_text(instance.get("n_justification")),
            _flatten_text(instance.get("experiments")),
        ]
    ).lower()
    # The ban is on testing cosmetic products; a patient's cosmetic surgery is not one.
    protocol_text = re.sub(r"cosmetic\s+surg\w*|ניתוח\w*\s+קוסמט\w*", " ", protocol_text)
    if any(kw in protocol_text for kw in cosmetics_keywords):
        ctx.checks.append(
            _rule(
                False,
                "",
                "Protocol appears to involve cosmetics or household cleaning-product testing, which is prohibited.",
                fix=(
                    "Remove cosmetics/cleaning-product animal testing aims or document that the "
                    "work is not product-safety testing in those banned categories."
                ),
                severity="error" if profile == "strict_law" else "warning",
                ref="cosmetics:ban",
            )
        )
        if profile == "strict_law":
            ctx.errors += 1
        else:
            ctx.warnings += 1

    # --- humane endpoints heuristics (soft) ---
    for idx, e in enumerate(exps, start=1):
        he = e.get("humane_endpoints") or {}
        texts = (he.get("general") or []) + (he.get("specific") or [])
        text = " ".join(texts).lower()
        has_text = bool(text)
        if 1 <= idx <= len(exp_signals):
            exp_signals[idx - 1]["has_humane_endpoints"] = has_text
        if not has_text:
            continue
        # Flag endpoints that rely only on "consult veterinarian" without concrete criteria.
        generic_consult = "consult" in text and ("vet" in text or "veterin" in text)
        has_quant = any(
            kw in text
            for kw in ["score", "tumor", "ulcer", "necros", "cm", "mm", "%", "scale"]
        )
        if generic_consult and not has_quant:
            fix_he = (
                "Replace generic 'consult veterinarian' endpoints with concrete, model-specific "
                "criteria (e.g. tumor size/ulceration, weight-loss thresholds, clinical scores)."
            )
            ctx.checks.append(
                _rule(
                    False,
                    "",
                    f"Experiment {idx}: humane endpoints rely on generic veterinarian consultation without concrete criteria.",
                    fix=fix_he,
                    severity="warning",
                    ref=f"endpoints:generic-consult:exp-{idx}",
                )
            )
            ctx.warnings += 1

        # Flag endpoints that only mention 20% weight loss without other model-specific indices.
        has_20 = "20%" in text or "20 percent" in text
        has_10 = "10%" in text or "10 percent" in text
        only_20 = has_20 and not has_10 and not any(
            kw in text for kw in ["tumor", "ulcer", "necros", "score", "scale", "hunch", "letharg",
                                  "posture", "moribund", "body condition", "piloerect", "dehydrat"]
        )
        if 1 <= idx <= len(exp_signals):
            exp_signals[idx - 1]["humane_endpoints_20_percent_only"] = bool(only_20)
        if only_20:
            fix_w = (
                "Weight loss of 20% alone is not a sufficient humane endpoint. "
                "Add earlier and model-specific criteria (e.g. 10% weight loss plus tumor/wound/behavioral indices)."
            )
            ctx.checks.append(
                _rule(
                    False,
                    "",
                    f"Experiment {idx}: humane endpoints mention only 20% weight loss without model-specific criteria.",
                    fix=fix_w,
                    severity="error" if profile == "strict_law" else "warning",
                    ref=f"endpoints:20%-only:exp-{idx}",
                )
            )
            if profile == "strict_law":
                ctx.errors += 1
            else:
                ctx.warnings += 1
