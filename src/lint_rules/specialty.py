"""special:* rules (one loop: stereotaxic, oncology, diabetes, biosafety, nanomaterials, ocular).
Verbatim move from linter_renderer.lint() (P3.1 batch 2). Flag writes stay on the always-path.
"""
from .context import RuleContext, _rule


def run(ctx: RuleContext) -> None:
    exps = ctx.exps
    exp_signals = ctx.exp_signals
    # --- specialty triggers based on text patterns ---
    for idx, e in enumerate(exps, start=1):
        label = (e.get("label") or "") + " " + (e.get("question") or "")
        timeline_txt = " ".join(
            (step.get("step") or "") for step in e.get("procedure_timeline") or []
        )
        joined = (label + " " + timeline_txt).lower()

        # DBS / stereotaxic
        has_stereotaxic = any(
            k in joined
            for k in ["dbs", "stereotax", "stereotactic", "craniotomy", "headcap", "implant"]
        )
        if 1 <= idx <= len(exp_signals):
            exp_signals[idx - 1]["specialty_flags"]["stereotaxic_context"] = bool(
                has_stereotaxic
            )
        if has_stereotaxic:
            st = e.get("stereotaxic_implant") or {}
            # Warn only if missing
            ok_st = bool(st.get("implant_type") or st.get("craniotomy") is not None)
            severity = "warning"  # ruleset 1.1.0: advisory rule, warning on pass and fail alike
            if not ok_st:
                 ctx.warnings += 1
            ctx.checks.append(
                _rule(
                    ok_st,
                    f"Experiment {idx}: stereotaxic/implant details present.",
                    f"Experiment {idx}: stereotaxic/DBS context but stereotaxic_implant block is incomplete.",
                    fix="Fill stereotaxic_implant block.",
                    severity=severity,
                    ref=f"special:stereotaxic:exp-{idx}",
                )
            )

        # Oncology / tumor
        has_onc = any(
            k in joined
            for k in [
                "tumor",
                "melanoma",
                "xenograft",
                "metastasis",
                "metastases",
                "muspelheim neoplasm",
                "alfheim neoplasm",
                "nidavellir tumor",
            ]
        )
        if 1 <= idx <= len(exp_signals):
            exp_signals[idx - 1]["specialty_flags"]["oncology_context"] = bool(has_onc)
        if has_onc:
            on = e.get("oncology") or {}
            ok_onc = bool(on.get("tumor_burden_cap")) and bool(on.get("ulceration_policy"))
            # Warn only
            severity = "warning"  # ruleset 1.1.0: advisory rule, warning on pass and fail alike
            if not ok_onc: ctx.warnings += 1
            ctx.checks.append(
                _rule(
                    ok_onc,
                    f"Experiment {idx}: oncology block has burden cap and ulceration policy.",
                    f"Experiment {idx}: tumor work requires tumor_burden_cap and ulceration_policy.",
                    fix="Fill oncology.tumor_burden_cap and ulceration_policy.",
                    severity=severity,
                    ref=f"special:oncology:exp-{idx}",
                )
            )

        # Diabetes
        has_db = any(
            k in joined
            for k in [
                "diabetes",
                "bg ",
                "blood glucose",
                "hyperglycemia",
                "jotunheim metabolic condition",
                "skadi-zotocin",
            ]
        )
        if 1 <= idx <= len(exp_signals):
            exp_signals[idx - 1]["specialty_flags"]["diabetes_context"] = bool(has_db)
        if has_db:
            db = e.get("diabetes") or {}
            ok_db = db.get("measurement") in ("fasted", "non_fasted")
            # Warn only
            severity = "warning"  # ruleset 1.1.0: advisory rule, warning on pass and fail alike
            if not ok_db: ctx.warnings += 1
            ctx.checks.append(
                _rule(
                    ok_db,
                    f"Experiment {idx}: diabetes block has measurement mode.",
                    f"Experiment {idx}: diabetes context requires measurement mode and BG threshold.",
                    fix="Fill diabetes block.",
                    severity=severity,
                    ref=f"special:diabetes:exp-{idx}",
                )
            )

        # Biosafety / viruses
        has_bio = any(
            k in joined
            for k in [
                "virus",
                "viral",
                "reovirus",
                "lentivirus",
                "aav",
                "infectious",
                "niflheim-v7",
            ]
        )
        if 1 <= idx <= len(exp_signals):
            exp_signals[idx - 1]["specialty_flags"]["biosafety_context"] = bool(has_bio)
        if has_bio:
            bs = e.get("biosafety_infectious_agents") or {}
            ok_bs = bool(bs.get("agent_name"))
            # Warn only
            severity = "warning"  # ruleset 1.1.0: advisory rule, warning on pass and fail alike
            if not ok_bs: ctx.warnings += 1
            ctx.checks.append(
                _rule(
                    ok_bs,
                    f"Experiment {idx}: biosafety agent documented.",
                    f"Experiment {idx}: viral/infectious work requires biosafety metadata.",
                    fix="Fill biosafety_infectious_agents block.",
                    severity=severity,
                    ref=f"special:biosafety:exp-{idx}",
                )
            )

        # Nanomaterials / VOCs
        # Reduced triggers (removed 'nano-' to avoid 'nanodrop', kept 'nanoparticle')
        has_nano = any(
            k in joined
            for k in [
                "nanoparticle",
                "volatile organic compound",
                "rune-particle",
                "rune-particles",
                "norn-corona",
                "nano-ghost",
                "nano-ghosts",
            ]
        )
        if 1 <= idx <= len(exp_signals):
            exp_signals[idx - 1]["specialty_flags"]["nanomaterials_context"] = bool(has_nano)
        if has_nano:
            nm = e.get("nanomaterials") or {}
            ok_nm = bool(nm.get("particle_type"))
            # Warn only
            severity = "warning"  # ruleset 1.1.0: advisory rule, warning on pass and fail alike
            if not ok_nm: ctx.warnings += 1
            ctx.checks.append(
                _rule(
                    ok_nm,
                    f"Experiment {idx}: nanomaterials metadata present.",
                    f"Experiment {idx}: nanoparticle/VOC context requires nanomaterials block.",
                    fix="Fill nanomaterials block.",
                    severity=severity,
                    ref=f"special:nanomaterials:exp-{idx}",
                )
            )

        # Ocular / optic nerve
        # Reduced triggers (removed 'eye ')
        has_oc = any(
            k in joined
            for k in [
                "optic nerve",
                "bifrost nerve",
                "retina",
                "corneal",
                "ocular",
            ]
        )
        if 1 <= idx <= len(exp_signals):
            exp_signals[idx - 1]["specialty_flags"]["ocular_context"] = bool(has_oc)
        if has_oc:
            oc = e.get("ocular_procedures") or {}
            ok_oc = bool(oc.get("topical_anesthesia")) or bool(oc.get("ocular_lubrication"))
            # Warn only
            severity = "warning"  # ruleset 1.1.0: advisory rule, warning on pass and fail alike
            if not ok_oc: ctx.warnings += 1
            ctx.checks.append(
                _rule(
                    ok_oc,
                    f"Experiment {idx}: ocular procedures metadata present.",
                    f"Experiment {idx}: ocular/optic nerve work requires ocular_procedures block.",
                    fix="Fill ocular_procedures block.",
                    severity=severity,
                    ref=f"special:ocular:exp-{idx}",
                )
            )
