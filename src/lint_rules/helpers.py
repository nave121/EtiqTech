"""Pure text/number helpers shared by lint rule modules. Verbatim move from linter_renderer (P3.1 batch 3)."""
import re
from typing import Any, Dict, Iterable, List

from ..avma_matrix import normalize_species, normalize_method


def _mentions(text: str, terms: Iterable[str]) -> bool:
    """True if any term occurs in text. Terms under 5 characters must be whole words (plus
    s/ed/ing), so 'burn' does not match 'Burnett' and 'ko' does not match 'kosher'; longer
    terms keep substring matching, so 'craniotomy' still matches 'hemicraniotomy'."""
    for term in terms:
        if len(term) < 5:
            if re.search(rf"(?<!\w){re.escape(term)}(?:s|ed|ing)?(?!\w)", text):
                return True
        elif term in text:
            return True
    return False


def _monitoring_text(monitoring: Dict[str, Any]) -> str:
    """The monitoring plan as free text: the schema's `documentation` plus the parameter list."""
    return ((monitoring.get("documentation") or "") + " " + " ".join(monitoring.get("parameters") or [])).lower()


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
    """Prefer explicit structured euthanasia method and fall back to primary text. An
    unrecognised value gives "" (no AVMA verdict), never a key the matrix would call unacceptable."""
    structured = (euthanasia.get("method_standard") or "").strip()
    return normalize_method(structured) or normalize_method((euthanasia.get("primary") or "").strip()) or ""


def _euthanasia_conditions_text(euthanasia: Dict[str, Any]) -> str:
    """Structured conditions text and the legacy parameters field, both (once each when equal)."""
    parts = [euthanasia.get("conditions_text") or "", euthanasia.get("parameters") or ""]
    return " ".join(dict.fromkeys(p for p in parts if p))


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
