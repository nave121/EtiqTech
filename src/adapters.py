"""Ingest adapters (Phase 3.3): anything that produces the canonical protocol JSON can be reviewed.

The durable public contract is the canonical instance shape (src/schema.py, rendered in
docs/schema.md). Institutions with other protocol systems (Cayuse, Topaz, Tick@lab, iRIS…)
write an adapter that emits that shape; the linter and LLM layers never see the source
format. Two adapters ship:

- ``il-council-html``  the reference adapter: the Israeli Council HTML export (src/html_to_json).
- ``canonical-json``   a canonical instance as JSON, validated strictly against the schema.

An adapter is a pair of callables registered in ADAPTERS: ``detect(content) -> bool`` and
``parse(content) -> instance``. ``ingest()`` picks the adapter by filename extension when
given, else by detection, and raises ``IngestError`` with a plain message otherwise.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Tuple, Union

import jsonschema

from .html_to_json import parse_html
from .schema import IACUC_SCHEMA_V2

Content = Union[str, bytes]


class IngestError(ValueError):
    """Bad input, safe to show to the user (never includes the content itself)."""


@dataclass(frozen=True)
class Adapter:
    name: str
    description: str
    extensions: Tuple[str, ...]
    detect: Callable[[str], bool]
    parse: Callable[[str], Dict[str, Any]]


def _text(content: Content) -> str:
    if isinstance(content, bytes):
        try:
            return content.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise IngestError("Could not decode file. Please ensure the file is UTF-8 encoded.") from exc
    return content


_validator = jsonschema.validators.validator_for(IACUC_SCHEMA_V2)(IACUC_SCHEMA_V2)


def schema_errors(instance: Any, limit: int = 20) -> List[str]:
    """Human-readable schema violations as 'path: message' (paths only — no values echoed)."""
    out = []
    for err in sorted(_validator.iter_errors(instance), key=lambda e: list(map(str, e.absolute_path))):
        path = "/".join(str(p) for p in err.absolute_path) or "<root>"
        msg = err.message
        if err.validator == "enum":  # do not echo the offending value; name the allowed set
            msg = f"must be one of {err.validator_value}"
        elif err.validator in ("type", "required", "minimum", "maximum", "minLength", "maxLength", "pattern"):
            msg = err.message if err.validator == "required" else f"failed '{err.validator}' ({err.validator_value})"
        out.append(f"{path}: {msg}")
        if len(out) >= limit:
            break
    return out


def schema_skeleton(node: Optional[Dict[str, Any]] = None) -> Any:
    """A minimal instance that satisfies the schema: required properties only, filled from
    x_meta examples / enum / type defaults. Adapter authors start here and overlay their data."""
    node = IACUC_SCHEMA_V2 if node is None else node
    t = node.get("type")
    if isinstance(t, list):
        t = next((x for x in t if x != "null"), t[0])
    if "enum" in node:
        return node["enum"][0]
    meta = node.get("x_meta") or {}
    if t == "object" or "properties" in node:
        props = node.get("properties") or {}
        return {k: schema_skeleton(props[k]) for k in node.get("required", []) if k in props}
    if t == "array":
        items = node.get("items")
        return [schema_skeleton(items)] if node.get("minItems", 0) > 0 and isinstance(items, dict) else []
    if t == "string":
        ex = meta.get("examples") or node.get("examples")
        return str(ex[0]) if ex else "x" * max(int(node.get("minLength", 0)), 1)
    if t == "integer":
        return int(node.get("minimum", 1))
    if t == "number":
        return float(node.get("minimum", 1))
    if t == "boolean":
        return False
    return None


def item_skeleton(*path: str) -> Any:
    """Skeleton of one element of an array field, e.g. item_skeleton("experiments")
    or item_skeleton("experiments", "procedure_timeline")."""
    node: Dict[str, Any] = IACUC_SCHEMA_V2
    for key in path:
        node = (node.get("properties") or {}).get(key) or {}
        if node.get("type") == "array" and key != path[-1]:
            node = node.get("items") or {}
    if node.get("type") != "array" or not isinstance(node.get("items"), dict):
        raise KeyError(f"{'.'.join(path)} is not an array field of the schema")
    return schema_skeleton(node["items"])


def parse_canonical_json(content: str) -> Dict[str, Any]:
    try:
        instance = json.loads(content)
    except ValueError as exc:
        raise IngestError("Invalid JSON.") from exc
    if not isinstance(instance, dict):
        raise IngestError("Canonical JSON must be an object.")
    errors = schema_errors(instance)
    if errors:
        raise IngestError("Instance does not match the canonical schema: " + "; ".join(errors))
    return instance


def _looks_like_html(text: str) -> bool:
    head = text.lstrip()[:512].lower()
    return head.startswith("<") and ("<html" in head or "<!doctype" in head or "<table" in head or "<div" in head)


def _looks_like_json(text: str) -> bool:
    return text.lstrip()[:1] == "{"


ADAPTERS: Dict[str, Adapter] = {
    "il-council-html": Adapter(
        "il-council-html", "Israeli National Council request-form HTML export (reference adapter)",
        ("html", "htm"), _looks_like_html, parse_html,
    ),
    "canonical-json": Adapter(
        "canonical-json", "Canonical protocol instance as JSON, validated against src/schema.py",
        ("json",), _looks_like_json, parse_canonical_json,
    ),
}


def ingest(content: Content, filename: Optional[str] = None) -> Tuple[Dict[str, Any], str]:
    """Return (instance, adapter_name). Raises IngestError on unsupported or invalid input."""
    text = _text(content)
    ext = (filename or "").rsplit(".", 1)[-1].lower() if filename and "." in filename else None
    for adapter in ADAPTERS.values():
        if ext and ext in adapter.extensions:
            return adapter.parse(text), adapter.name
    if ext:
        raise IngestError("Invalid file type. Please upload an HTML export or a canonical JSON instance.")
    for adapter in ADAPTERS.values():
        if adapter.detect(text):
            return adapter.parse(text), adapter.name
    raise IngestError("Unrecognized input: expected an HTML export or a canonical JSON instance.")
