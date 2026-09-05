"""Shared state for lint rule modules. `_rule` moved here unchanged from linter_renderer."""
from dataclasses import dataclass, field
from typing import Any, Dict, List


def _rule(
    ok: bool,
    msg_ok: str,
    msg_fail: str,
    fix: str = "",
    severity: str = "error",
    ref: str = "",
) -> Dict[str, Any]:
    return {
        "status": "pass" if ok else "fail",
        "message": msg_ok if ok else msg_fail,
        "suggested_fix": fix,
        "severity": severity,
        "reference": ref,
    }


@dataclass
class RuleContext:
    instance: Dict[str, Any]
    profile: str  # already normalised to "default" | "strict_law" by lint()
    checks: List[Dict[str, Any]] = field(default_factory=list)
    errors: int = 0
    warnings: int = 0
    # cross-region values, filled by the animals prelude in lint()
    exps: list = None  # instance["experiments"] or []
    totals: list = None  # instance["animals_total"] or []
    exp_signals: list = None  # the SAME list object built in the prelude; mutated in place, published by reference
    total_n_all: int = 0
    invasive_keywords: list = None  # defined by severity:analgesia, re-read by pain:category-consistency

    def req(self, path: str, obj: Dict[str, Any], keys: List[str]) -> bool:
        missing = [k for k in keys if k not in obj]
        if missing:
            self.errors += 1
            self.checks.append(
                _rule(
                    False,
                    "",
                    f"Missing required fields at {path}: {missing}",
                    ref=f"required:{path}",
                )
            )
            return False
        return True
