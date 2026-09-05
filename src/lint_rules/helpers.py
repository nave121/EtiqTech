"""Pure text/number helpers shared by lint rule modules. Verbatim move from linter_renderer (P3.1 batch 3)."""
from typing import Any, Dict, List

from ..avma_matrix import normalize_species, normalize_method


def _flatten_text(value: Any) -> str:
    """Collapse nested strings, lists, and dicts into searchable text."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        return " ".join(_flatten_text(v) for v in value.values())
    if isinstance(value, list):
        return " ".join(_flatten_text(v) for v in value)
    return str(value)


def _canonical_species_key(animals: Dict[str, Any]) -> str:
    """Prefer explicit structured species and fall back to normalized legacy species."""
    structured = (animals.get("species_standard") or "").strip()
    if structured:
        return normalize_species(structured) or structured
    return normalize_species((animals.get("species") or "").strip()) or ""


def _canonical_method_key(euthanasia: Dict[str, Any]) -> str:
    """Prefer explicit structured euthanasia method and fall back to primary text."""
    structured = (euthanasia.get("method_standard") or "").strip()
    if structured:
        return normalize_method(structured) or structured
    return normalize_method((euthanasia.get("primary") or "").strip()) or ""


def _euthanasia_conditions_text(euthanasia: Dict[str, Any]) -> str:
    """Prefer explicit structured conditions text but preserve legacy parameters fallback."""
    return (
        euthanasia.get("conditions_text")
        or euthanasia.get("parameters")
        or ""
    )


def _anesthesia_rows(exp: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Prefer structured anesthesia drugs and fall back to legacy anesthesia rows."""
    return (exp.get("anesthesia_drugs") or exp.get("anesthesia") or [])


def _anesthesia_text(exp: Dict[str, Any]) -> str:
    return _flatten_text(_anesthesia_rows(exp)).lower()


def _pain_category(exp: Dict[str, Any]) -> str:
    raw = (exp.get("pain_category") or "").strip().upper()
    if raw in {"B", "C", "D", "E"}:
        return raw
    structured = exp.get("pain_category_structured") or {}
    parsed = (structured.get("parsed") or "").strip().upper()
    return parsed if parsed in {"B", "C", "D", "E"} else ""


def _coerce_float(value: Any) -> float | None:
    try:
        if value in (None, ""):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _coerce_int(value: Any) -> int | None:
    try:
        if value in (None, ""):
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def _animal_weight_grams(animals: Dict[str, Any]) -> float | None:
    weight = animals.get("weight") or {}
    value = _coerce_float(weight.get("value"))
    if value is None:
        return None
    unit = (weight.get("unit") or "g").lower()
    if unit == "kg":
        return value * 1000.0
    return value


def _nonempty(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, list):
        return any(_nonempty(item) for item in value)
    return True
