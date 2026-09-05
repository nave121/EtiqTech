"""Header / research / PI / participants rules: required:<path> (3 ctx.req sites),
header, research, title:track, title:pilot-label, term:track, continuation,
third-party, pi, pi:training, participant:training,
participant:certified-without-training. Verbatim move from
linter_renderer.lint() (P3.1 batch 7).

term:track keeps its two counter lines ABOVE the append and passes ideal_term
(not ok_term) to _rule; title:pilot-label keeps no severity= with a warnings
counter. Both are documented quirks (plan section 5), preserved on purpose.
"""
from .context import RuleContext, _rule


def run(ctx: RuleContext) -> None:
    instance = ctx.instance
    # --- header ---
    if "header" not in instance:
        ctx.errors += 1
        ctx.checks.append(_rule(False, "", "Missing 'header' block.", ref="header"))
    else:
        ctx.req("header", instance["header"], ["protocol_id", "institution"])

    # --- research ---
    if "research" not in instance:
        ctx.errors += 1
        ctx.checks.append(_rule(False, "", "Missing 'research' block.", ref="research"))
    else:
        r = instance["research"]
        ctx.req(
            "research",
            r,
            [
                "title_he",
                "title_en",
                "request_type",
                "is_continuation",
                "third_party_service",
                "approval_term_years",
                "sites",
            ],
        )
        rt = r.get("request_type")
        title_he = r.get("title_he", "") or ""
        title_en = r.get("title_en", "") or ""

        # Title vs track
        if rt == "regular":
            bad = any(w in title_he for w in ["פיילוט", "פילוט"]) or "Pilot" in title_en
            ctx.checks.append(
                _rule(
                    not bad,
                    "Regular track: title does not contain 'Pilot/פיילוט'.",
                    "Regular track: title should not contain 'Pilot/פיילוט'.",
                    fix="Remove 'Pilot/פיילוט' indicators or change request_type to 'pilot'.",
                    ref="title:track",
                )
            )
            if bad:
                ctx.errors += 1
        if rt == "pilot":
            has_pilot = ("פיילוט" in title_he) or ("Pilot" in title_en)
            ctx.checks.append(
                _rule(
                    has_pilot,
                    "Pilot track: title clearly marked as Pilot.",
                    "Pilot track: title should explicitly include 'Pilot/פיילוט'.",
                    fix="Add 'פיילוט' to Hebrew title and 'Pilot' to English title.",
                    ref="title:pilot-label",
                )
            )
            if not has_pilot:
                ctx.warnings += 1

        # term vs track
        term = r.get("approval_term_years")
        if isinstance(term, int) and rt:
            # Relaxed to warning: Pilot 'should' be 1 year, but sometimes 4 is requested/approved.
            is_pilot = (rt == "pilot")
            ok_term = 1 <= term <= 4
            ideal_term = (term == 1) if is_pilot else True
            
            severity = "warning" if (ok_term and not ideal_term) else "error"
            if not ok_term: ctx.errors += 1 # Strict range check
            if ok_term and not ideal_term: ctx.warnings += 1

            fix_term = (
                "Pilot track ideally 1 year; regular/colony/continuation 1–4 years."
            )
            ctx.checks.append(
                _rule(
                    ideal_term,
                    "Approval term consistent with request type.",
                    f"Approval term {term} years is inconsistent with request_type='{rt}'.",
                    fix=fix_term,
                    severity=severity,
                    ref="term:track",
                )
            )

        # continuation metadata
        if r.get("is_continuation"):
            ok_cont = bool(r.get("prior_protocol_id")) and bool(
                r.get("continuation_reason")
            )
            ctx.checks.append(
                _rule(
                    ok_cont,
                    "Continuation has previous protocol ID and reason.",
                    "Continuation requires 'prior_protocol_id' and 'continuation_reason'.",
                    ref="continuation",
                )
            )
            if not ok_cont:
                ctx.errors += 1

        # third-party
        if r.get("third_party_service"):
            t = instance.get("third_party") or {}
            ok_tp = all(
                bool(t.get(k)) 
                for k in ["sponsor_org", "ordering_investigator_name", "sponsor_approver_name"]
            )
            fix_tp = (
                "Fill third_party.sponsor_org, ordering_investigator_name, "
                "sponsor_approver_name, and ideally declaration_url."
            )
            ctx.checks.append(
                _rule(
                    ok_tp,
                    "Third-party metadata is present.",
                    "Third-party service missing sponsor/ordering/approver details.",
                    fix=fix_tp,
                    ref="third-party",
                )
            )
            if not ok_tp:
                ctx.errors += 1

    # --- PI & training ---
    pi = instance.get("pi") or {}
    if not pi:
        ctx.errors += 1
        ctx.checks.append(_rule(False, "", "Missing 'pi' block.", ref="pi"))
    else:
        ctx.req(
            "pi",
            pi,
            [
                "id_type",
                "id_number",
                "last_name_he",
                "first_name_he",
                "last_name_en",
                "first_name_en",
                "email",
                "phone_primary",
                "institutional_cert_no",
            ],
        )
        has_pi_training = bool(pi.get("training"))
        ctx.checks.append(
            _rule(
                has_pi_training,
                "PI has at least one training certificate recorded.",
                "PI has no training certificate in 'pi.training'.",
                fix="Add at least one entry to pi.training[].",
                ref="pi:training",
            )
        )
        if not has_pi_training:
            ctx.errors += 1

    # --- participants & training ---
    participants = instance.get("participants") or []
    for idx, p in enumerate(participants, start=1):
        role = p.get("role")
        training = p.get("training") or []
        certified = bool(p.get("certified"))

        if role == "performs_procedures":
            ok_tr = bool(training)
            ctx.checks.append(
                _rule(
                    ok_tr,
                    f"Participant {idx} performs procedures and has training.",
                    f"Participant {idx} performs procedures but has no training entries.",
                    fix="Add at least one training certificate to this participant.",
                    ref="participant:training",
                )
            )
            if not ok_tr:
                ctx.errors += 1

        if certified and not training:
            ctx.checks.append(
                _rule(
                    False,
                    "",
                    f"Participant {idx} is marked 'certified' but has no training entries.",
                    fix="Either mark 'certified=false' or add training[].",
                    severity="warning",
                    ref="participant:certified-without-training",
                )
            )
            ctx.warnings += 1

