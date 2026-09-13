"""
Layer 3 — "Human Eye" holistic protocol review.

Reads the protocol the way a senior committee member would: starting from the
protocol text (not the linter's flags), using adversarial framing to find ALL
deficiencies, and producing a structured section-by-section + cross-reference
report with an overall verdict and risk profile.

Architecture
------------
- 2-pass pipeline:
    Pass 1: section-by-section review (adversarial, rubric-based CoT)
    Pass 2: cross-reference consistency + holistic synthesis
- Context: full law text + all CASE_REPORTs + high-leverage x_meta catalog
  (no truncation — relies on OLLAMA_NUM_CTX=32768)
- Additive: Layer 3 adds findings; it never removes Layer 1/2 items
- Conditional trigger: run when Layer 1 has errors, Layer 2 grades indicate
  material deficiencies, severity ≥ 3, or random 10 % sampling
"""

import hashlib
import json
import re
from pathlib import Path
from typing import Any, Dict, Generator, List, Optional, Tuple

from .llm_agent import LAW_PATH
from .llm_clients import _env_int, call_llm, call_llm_stream, context_budget_warning
from .xmeta_catalog import load_high_leverage_catalog

PROMPTS_DIR = Path(__file__).parent.parent / "llm"


def layer3_num_ctx() -> int:
    """Layer 3 injects the whole protocol plus its context (~28k tokens on a typical export), so it
    runs with a wider Ollama window than Layer 2. Maintainer decision 2026-09-06: raise the window
    rather than trim the prompt for now; OpenAI/Anthropic providers ignore this (their windows are larger)."""
    return _env_int("OLLAMA_NUM_CTX_LAYER3", 65536)
HEAD_TO_HEAD_DIR = Path(__file__).parent.parent / "examples" / "head-to-head"

# ---------------------------------------------------------------------------
# Context loading (no truncation — rely on 32 k context window)
# ---------------------------------------------------------------------------


def _load_full_law_text() -> str:
    if LAW_PATH.exists():
        return LAW_PATH.read_text(encoding="utf-8")
    return ""


def _load_all_case_reports() -> str:
    texts: List[str] = []
    global_report = HEAD_TO_HEAD_DIR / "GLOBAL_ETHICS_REPORT.md"
    if global_report.exists():
        texts.append("# GLOBAL_ETHICS_REPORT\n" + global_report.read_text(encoding="utf-8"))
    if HEAD_TO_HEAD_DIR.exists():
        for p in sorted(HEAD_TO_HEAD_DIR.rglob("CASE_REPORT.md")):
            try:
                texts.append(f"# CASE_REPORT: {p.parent.name}\n" + p.read_text(encoding="utf-8"))
            except OSError:
                continue
    return "\n\n---\n\n".join(texts)


def _build_layer3_blind_context(instance: Dict[str, Any], lint_report: Dict[str, Any]) -> str:
    """
    Assemble context for Layer 3 blind prompts.
    Deliberately omits Layer 1 and Layer 2 findings.
    """
    law_text = _load_full_law_text()
    case_reports = _load_all_case_reports()
    catalog = json.dumps(load_high_leverage_catalog(), ensure_ascii=False, indent=2)

    analysis = lint_report.get("analysis") or {}
    analysis_str = json.dumps(analysis, ensure_ascii=False, indent=2)

    instance_str = json.dumps(instance, ensure_ascii=False, indent=2)

    return (
        f"### Israeli Animal Experimentation Law (full text)\n{law_text}\n\n"
        f"### Head-to-head committee case reports\n{case_reports}\n\n"
        f"### High-leverage x_meta reference catalog\n```json\n{catalog}\n```\n\n"
        f"### Analysis signals\n```json\n{analysis_str}\n```\n\n"
        f"### Protocol instance (full JSON)\n```json\n{instance_str}\n```"
    )


def _build_layer3_informed_context(instance: Dict[str, Any], lint_report: Dict[str, Any]) -> str:
    blind_context = _build_layer3_blind_context(instance, lint_report)
    failing = [
        c for c in (lint_report.get("checklist") or [])
        if c.get("status") == "fail"
    ]
    failing_str = json.dumps(failing, ensure_ascii=False, indent=2)
    return (
        f"{blind_context}\n\n"
        f"### Layer 1 linter — failing items only\n```json\n{failing_str}\n```"
    )


# ---------------------------------------------------------------------------
# Prompt builders
# ---------------------------------------------------------------------------

def _load_prompt() -> str:
    return (PROMPTS_DIR / "llm_human_eye_prompt.md").read_text(encoding="utf-8")


def _build_pass1_prompt(instance: Dict[str, Any], lint_report: Dict[str, Any]) -> str:
    base = _load_prompt()
    if "## Pass 2" not in base:
        raise RuntimeError(
            "llm_human_eye_prompt.md is missing the '## Pass 2' section marker"
        )
    context = _build_layer3_blind_context(instance, lint_report)
    # Extract only the Pass 1 section of the prompt (up to the Pass 2 heading)
    pass1_section = base.split("## Pass 2")[0].strip()
    return f"{pass1_section}\n\n---\n\n{context}"


def _build_pass2_prompt(
    instance: Dict[str, Any],
    lint_report: Dict[str, Any],
    pass1_result: Dict[str, Any],
    layer2_result: Optional[Dict[str, Any]],
) -> str:
    base = _load_prompt()
    if "## Pass 2" not in base:
        raise RuntimeError(
            "llm_human_eye_prompt.md is missing the '## Pass 2' section marker"
        )
    context = _build_layer3_informed_context(instance, lint_report)
    # Extract only the Pass 2 section
    pass2_section = base[base.index("## Pass 2"):].strip()

    pass1_str = json.dumps(pass1_result, ensure_ascii=False, indent=2)
    layer2_str = json.dumps(layer2_result or {}, ensure_ascii=False, indent=2)

    return (
        f"{pass2_section}\n\n---\n\n"
        f"{context}\n\n"
        f"### Pass 1 findings (section-by-section)\n```json\n{pass1_str}\n```\n\n"
        f"### Layer 2 theme verdicts\n"
        f"```json\n{layer2_str}\n```"
    )


# ---------------------------------------------------------------------------
# JSON parsing (reuse same approach as llm_agent.py)
# ---------------------------------------------------------------------------

def _parse_layer3_json(text: str) -> Dict[str, Any]:
    cleaned = text.strip()
    cleaned = re.sub(r'<think(?:ing)?>.*?</think(?:ing)?>', '', cleaned, flags=re.DOTALL | re.IGNORECASE)
    cleaned = cleaned.strip()

    # Strip code fence
    code_block = re.search(r'```(?:json)?\s*\n?(.*?)\n?```', cleaned, flags=re.DOTALL)
    if code_block:
        cleaned = code_block.group(1).strip()

    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass

    start = cleaned.find("{")
    if start == -1:
        raise ValueError("No JSON object found in LLM response")

    depth = 0
    end = -1
    in_string = False
    escape_next = False
    for i, char in enumerate(cleaned[start:], start):
        if escape_next:
            escape_next = False
            continue
        if char == '\\' and in_string:
            escape_next = True
            continue
        if char == '"' and not escape_next:
            in_string = not in_string
            continue
        if in_string:
            continue
        if char == '{':
            depth += 1
        elif char == '}':
            depth -= 1
            if depth == 0:
                end = i
                break

    if end != -1:
        try:
            return json.loads(cleaned[start:end + 1])
        except json.JSONDecodeError:
            pass

    end = cleaned.rfind("}")
    if start != -1 and end > start:
        try:
            return json.loads(cleaned[start:end + 1])
        except json.JSONDecodeError:
            pass

    raise ValueError("Layer 3 response was not valid JSON.")


# ---------------------------------------------------------------------------
# Trigger logic
# ---------------------------------------------------------------------------

def should_trigger_layer3(
    lint_report: Dict[str, Any],
    layer2_result: Optional[Dict[str, Any]],
    instance: Optional[Dict[str, Any]] = None,
    *,
    sampling_rate: float = 0.10,
) -> Tuple[bool, str]:
    """
    Returns (True, reason_string) if Layer 3 should run.

    Conditions (first match wins):
    1. Layer 1 has any error-severity checklist item
    2. Layer 2 has any theme with legacy low confidence or graded score <= 1
    3. Layer 2 has >= 2 themes with legacy needs_fixes or graded score <= 2
    4. Any experiment has severity_level_1_to_5 >= 3
    5. Random 10 % sampling (seeded by protocol_id hash for reproducibility)
    """
    # Condition 1 — Layer 1 errors
    checklist = lint_report.get("checklist") or []
    if any(c.get("status") == "fail" and c.get("severity") == "error" for c in checklist):
        return True, "layer1_errors"

    # Condition 2 and 3 — Layer 2 thresholds
    if layer2_result:
        themes = layer2_result.get("themes") or {}
        if any(
            isinstance(v, dict) and v.get("confidence") == "low"
            for v in themes.values()
        ):
            return True, "layer2_low_confidence"
        if any(_theme_score_at_most(v, 1) for v in themes.values()):
            return True, "layer2_low_score"
        legacy_needs_fixes_count = sum(
            1 for v in themes.values()
            if isinstance(v, dict) and v.get("verdict") == "needs_fixes"
        )
        if legacy_needs_fixes_count >= 2:
            return True, "layer2_multiple_needs_fixes"
        low_or_partial_count = sum(
            1 for v in themes.values()
            if _theme_score_at_most(v, 2)
        )
        if low_or_partial_count >= 2:
            return True, "layer2_multiple_low_scores"

    # Condition 4 — high severity experiments
    if instance:
        for exp in (instance.get("experiments") or []):
            if isinstance(exp.get("severity_level_1_to_5"), int) and exp["severity_level_1_to_5"] >= 3:
                return True, "high_severity_experiment"

    # Condition 5 — random sampling (seeded by protocol_id for reproducibility)
    if sampling_rate > 0:
        protocol_id = ""
        if instance:
            protocol_id = str((instance.get("header") or {}).get("protocol_id", ""))
        seed = int(hashlib.md5(protocol_id.encode(), usedforsecurity=False).hexdigest(), 16) % 1000
        if seed < int(sampling_rate * 1000):
            return True, "random_sampling"

    return False, "trigger_conditions_not_met"


# ---------------------------------------------------------------------------
# Fallback results
# ---------------------------------------------------------------------------

def _fallback_pass1() -> Dict[str, Any]:
    return {"sections": []}


def _fallback_pass2() -> Dict[str, Any]:
    return {
        "cross_reference_issues": [],
        "overall_verdict": "revise_major",
        "risk_profile": "high",
        "summary": "Layer 3 could not complete review due to an LLM error; defaulting to revise_major.",
    }


def _derive_pass1_assessment(pass1: Dict[str, Any]) -> Tuple[str, str]:
    severities = [
        section.get("severity")
        for section in (pass1.get("sections") or [])
        if isinstance(section, dict)
    ]
    if "Critical" in severities:
        return "reject", "critical"
    if "Major" in severities:
        return "revise_major", "high"
    if "Minor" in severities:
        return "revise_minor", "medium"
    if "Recommendation" in severities:
        return "approve", "low"
    return "approve", "low"


def _build_layer3_disagreement_summary(
    pass1: Dict[str, Any],
    pass2: Dict[str, Any],
) -> Dict[str, Any]:
    pass1_verdict, pass1_risk = _derive_pass1_assessment(pass1)
    final_verdict = pass2.get("overall_verdict") or "revise_major"
    final_risk = pass2.get("risk_profile") or "high"
    cross_reference_issues = pass2.get("cross_reference_issues") or []
    return {
        "verdict_changed": pass1_verdict != final_verdict,
        "risk_changed": pass1_risk != final_risk,
        "new_cross_reference_issues": len(cross_reference_issues),
    }


def _build_final_result(
    pass1: Dict[str, Any],
    pass2: Dict[str, Any],
    reason: str,
) -> Dict[str, Any]:
    pass1_sections = pass1.get("sections") or []
    return {
        "sections": pass1_sections,
        "pass1_sections": pass1_sections,
        "cross_reference_issues": pass2.get("cross_reference_issues") or [],
        "overall_verdict": pass2.get("overall_verdict") or "revise_major",
        "risk_profile": pass2.get("risk_profile") or "high",
        "summary": pass2.get("summary") or "",
        "disagreement_summary": _build_layer3_disagreement_summary(pass1, pass2),
        "triggered_by": reason,
        "skipped": False,
    }


def _theme_score_at_most(theme_value: Any, threshold: int) -> bool:
    if not isinstance(theme_value, dict) or theme_value.get("unavailable"):
        return False  # no verdict at all is not a low verdict
    score = theme_value.get("score")
    return isinstance(score, int) and score <= threshold


def _skipped_result() -> Dict[str, Any]:
    return {
        "sections": [],
        "pass1_sections": [],
        "cross_reference_issues": [],
        "overall_verdict": "approve",
        "risk_profile": "low",
        "summary": "Layer 3 was not triggered for this protocol.",
        "disagreement_summary": {
            "verdict_changed": False,
            "risk_changed": False,
            "new_cross_reference_issues": 0,
        },
        "triggered_by": "",
        "skipped": True,
    }


# ---------------------------------------------------------------------------
# Synchronous entry point
# ---------------------------------------------------------------------------

def run_human_eye(
    instance: Dict[str, Any],
    lint_report: Dict[str, Any],
    layer2_result: Optional[Dict[str, Any]] = None,
    *,
    provider: Optional[str] = None,
    model: Optional[str] = None,
    temperature: float = 0.2,
    force: bool = False,
) -> Dict[str, Any]:
    """
    Execute the 2-pass Layer 3 review and return a HumanEyeResult-shaped dict.

    Parameters
    ----------
    instance : parsed protocol JSON
    lint_report : Layer 1 linter output
    layer2_result : Layer 2 VerifierResult (optional, used in Pass 2 synthesis)
    force : bypass trigger check and always run
    """
    triggered, reason = should_trigger_layer3(lint_report, layer2_result, instance)
    if not force and not triggered:
        return _skipped_result()

    # Pass 1 — section-by-section
    p1_prompt = _build_pass1_prompt(instance, lint_report)
    context_budget_warning(p1_prompt, label="Layer 3 / pass 1", num_ctx=layer3_num_ctx())  # logs; no stream to notify
    try:
        raw1 = call_llm(p1_prompt, provider=provider, model=model, temperature=temperature, num_ctx=layer3_num_ctx())
        pass1 = _parse_layer3_json(raw1)
    except Exception:
        pass1 = _fallback_pass1()

    # Pass 2 — cross-reference + synthesis
    p2_prompt = _build_pass2_prompt(instance, lint_report, pass1, layer2_result)
    context_budget_warning(p2_prompt, label="Layer 3 / pass 2", num_ctx=layer3_num_ctx())
    try:
        raw2 = call_llm(p2_prompt, provider=provider, model=model, temperature=temperature, num_ctx=layer3_num_ctx())
        pass2 = _parse_layer3_json(raw2)
    except Exception:
        pass2 = _fallback_pass2()

    return _build_final_result(pass1, pass2, reason)


# ---------------------------------------------------------------------------
# Streaming entry point
# ---------------------------------------------------------------------------

def run_human_eye_stream(
    instance: Dict[str, Any],
    lint_report: Dict[str, Any],
    layer2_result: Optional[Dict[str, Any]] = None,
    *,
    provider: Optional[str] = None,
    model: Optional[str] = None,
    temperature: float = 0.2,
    force: bool = False,
) -> Generator[Dict[str, Any], None, None]:
    """
    Execute Layer 3 review with streaming updates.

    Yields events:
    - {"type": "layer3_trigger", "reason": "..."}
    - {"type": "layer3_skip",    "reason": "..."}
    - {"type": "pass_start",     "pass": 1, "label": "..."}
    - {"type": "token",          "pass": 1, "token": "..."}
    - {"type": "pass_done",      "pass": 1, "result": {...}}
    - {"type": "pass_start",     "pass": 2, "label": "..."}
    - {"type": "token",          "pass": 2, "token": "..."}
    - {"type": "pass_done",      "pass": 2, "result": {...}}
    - {"type": "complete",       "result": HumanEyeResult-shaped dict}
    """
    triggered, reason = should_trigger_layer3(lint_report, layer2_result, instance)

    if not force and not triggered:
        yield {"type": "layer3_skip", "reason": reason}
        yield {"type": "complete", "result": _skipped_result()}
        return

    yield {"type": "layer3_trigger", "reason": reason}

    # --- Pass 1 ---
    yield {"type": "pass_start", "pass": 1, "label": "Section-by-section review"}

    p1_prompt = _build_pass1_prompt(instance, lint_report)
    warning = context_budget_warning(p1_prompt, label="Layer 3 / pass 1", num_ctx=layer3_num_ctx())
    if warning:
        yield {**warning, "pass": 1}
    full_response1 = ""
    try:
        for token in call_llm_stream(p1_prompt, provider=provider, model=model, temperature=temperature, num_ctx=layer3_num_ctx()):
            full_response1 += token
            yield {"type": "token", "pass": 1, "token": token}
        pass1 = _parse_layer3_json(full_response1)
    except Exception as e:
        pass1 = _fallback_pass1()
        yield {"type": "token", "pass": 1, "token": f"\n[Layer 3 Pass 1 error: {type(e).__name__}]"}

    yield {"type": "pass_done", "pass": 1, "result": pass1}

    # --- Pass 2 ---
    yield {"type": "pass_start", "pass": 2, "label": "Cross-reference & synthesis"}

    p2_prompt = _build_pass2_prompt(instance, lint_report, pass1, layer2_result)
    warning = context_budget_warning(p2_prompt, label="Layer 3 / pass 2", num_ctx=layer3_num_ctx())
    if warning:
        yield {**warning, "pass": 2}
    full_response2 = ""
    try:
        for token in call_llm_stream(p2_prompt, provider=provider, model=model, temperature=temperature, num_ctx=layer3_num_ctx()):
            full_response2 += token
            yield {"type": "token", "pass": 2, "token": token}
        pass2 = _parse_layer3_json(full_response2)
    except Exception as e:
        pass2 = _fallback_pass2()
        yield {"type": "token", "pass": 2, "token": f"\n[Layer 3 Pass 2 error: {type(e).__name__}]"}

    yield {"type": "pass_done", "pass": 2, "result": pass2}

    final = _build_final_result(pass1, pass2, reason)
    yield {"type": "complete", "result": final}
