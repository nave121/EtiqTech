import argparse
import json
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, List, Tuple

from .html_to_json import parse_html
from .schema import IACUC_SCHEMA_V2

ROOT_DIR = Path(__file__).parent.parent
KNOWN_GOOD_DIR = ROOT_DIR / "examples" / "known-good"
HEAD_TO_HEAD_DIR = ROOT_DIR / "examples" / "head-to-head"

# Capture up to this many distinct example snippets per field.
# Slightly higher so x_meta can show both classic and head-to-head patterns.
DEFAULT_MAX_EXAMPLES = 3
MAX_SNIPPET_CHARS = 800


PathTokens = Tuple[str, ...]


def _tokens_to_path(tokens: PathTokens) -> str:
    return ".".join(tokens)


def _iter_schema(node: Any, path: PathTokens = ()) -> Iterator[Tuple[PathTokens, Dict[str, Any]]]:
    if not isinstance(node, dict):
        return

    x_meta = node.get("x_meta")
    if isinstance(x_meta, dict):
        yield path, x_meta

    for key in ("properties", "patternProperties"):
        props = node.get(key)
        if isinstance(props, dict):
            for name, child in props.items():
                yield from _iter_schema(child, path + (name,))

    items = node.get("items")
    if isinstance(items, dict):
        yield from _iter_schema(items, path + ("[]",))
    elif isinstance(items, list):
        for child in items:
            yield from _iter_schema(child, path + ("[]",))

    for keyword in ("allOf", "anyOf", "oneOf"):
        children = node.get(keyword)
        if isinstance(children, list):
            for child in children:
                yield from _iter_schema(child, path)


def _extract_values(data: Any, tokens: PathTokens) -> Iterable[Any]:
    if not tokens:
        if data is None:
            return
        yield data
        return

    head, *tail = tokens

    if head == "[]":
        if isinstance(data, list):
            for item in data:
                yield from _extract_values(item, tuple(tail))
        return

    if isinstance(data, dict) and head in data:
        yield from _extract_values(data[head], tuple(tail))


def _stringify_value(value: Any, max_chars: int = MAX_SNIPPET_CHARS) -> str:
    if isinstance(value, str):
        text = " ".join(value.split())
    else:
        text = json.dumps(value, ensure_ascii=False, sort_keys=True)

    text = text.strip()
    if not text:
        return ""

    if len(text) > max_chars:
        return text[: max_chars - 3] + "..."
    return text


def _load_known_good_instances() -> List[Tuple[Path, Dict[str, Any]]]:
    """
    Load known-good instances from:
    - examples/known-good/*.html
    - examples/head-to-head/**/good*.html  (only 'good' variants from head-to-head pairs)
    """
    instances: List[Tuple[Path, Dict[str, Any]]] = []

    html_paths: List[Path] = []
    if KNOWN_GOOD_DIR.exists():
        html_paths.extend(sorted(KNOWN_GOOD_DIR.glob("*.html")))

    # Include only "good" head-to-head examples to avoid training on known-bad cases.
    if HEAD_TO_HEAD_DIR.exists():
        html_paths.extend(sorted(HEAD_TO_HEAD_DIR.rglob("good*.html")))

    for html_path in html_paths:
        html_text = html_path.read_text(encoding="utf-8")
        instance = parse_html(html_text)
        instances.append((html_path, instance))

    return instances


def generate_catalog(
    *,
    max_examples_per_field: int = DEFAULT_MAX_EXAMPLES,
    max_snippet_chars: int = MAX_SNIPPET_CHARS,
) -> List[Dict[str, Any]]:
    entries: List[Dict[str, Any]] = []
    instances = _load_known_good_instances()

    schema_fields = [
        {"tokens": tokens, "path": _tokens_to_path(tokens), "x_meta": x_meta}
        for tokens, x_meta in _iter_schema(IACUC_SCHEMA_V2)
    ]

    for field in schema_fields:
        samples: List[Dict[str, Any]] = []
        seen_values = set()
        for source_path, instance in instances:
            if len(samples) >= max_examples_per_field:
                break
            values = _extract_values(instance, field["tokens"])
            for raw_value in values:
                text_value = _stringify_value(raw_value, max_chars=max_snippet_chars)
                if not text_value or text_value in seen_values:
                    continue
                seen_values.add(text_value)
                try:
                    rel_path = source_path.relative_to(ROOT_DIR)
                except ValueError:
                    rel_path = source_path
                source_name = source_path.name
                relative_path = str(rel_path)
                samples.append(
                    {
                        "source": source_name,
                        "source_file": source_name,
                        "source_path": relative_path,
                        "value": text_value,
                    }
                )
                if len(samples) >= max_examples_per_field:
                    break

        entries.append(
            {
                "path": field["path"],
                "x_meta": field["x_meta"],
                "examples": samples,
            }
        )

    return entries


HIGH_LEVERAGE_PREFIXES: Tuple[str, ...] = (
    # Global N and justification
    "animals_total",
    "n_justification",
    "alternatives_search",
    # Per-experiment burden & welfare
    "experiments.[].severity_level_1_to_5",
    "experiments.[].monitoring",
    "experiments.[].analgesia",
    "experiments.[].euthanasia",
    "experiments.[].humane_endpoints",
)


def filter_high_leverage_fields(catalog: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Return only catalog entries that correspond to high-leverage welfare/usage fields:
    totals/N, N-justification, severity, monitoring, analgesia, endpoints, euthanasia.
    """
    filtered: List[Dict[str, Any]] = []
    for entry in catalog:
        path = entry.get("path", "")
        if any(path.startswith(pref) for pref in HIGH_LEVERAGE_PREFIXES):
            filtered.append(entry)
    return filtered


@lru_cache(maxsize=1)
def load_reference_catalog() -> List[Dict[str, Any]]:
    return generate_catalog()


@lru_cache(maxsize=1)
def load_high_leverage_catalog() -> List[Dict[str, Any]]:
    """
    Cached accessor for the high-leverage subset of the catalog:
    totals/N, N-justification, alternatives search, severity, monitoring, analgesia,
    humane endpoints, euthanasia.
    """
    full = load_reference_catalog()
    return filter_high_leverage_fields(full)


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate the x_meta reference catalog.")
    parser.add_argument(
        "--max-examples",
        type=int,
        default=DEFAULT_MAX_EXAMPLES,
        help=f"Maximum number of known-good snippets to capture per field (default: {DEFAULT_MAX_EXAMPLES}).",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Optional path to write the catalog JSON; if omitted, prints to stdout.",
    )
    parser.add_argument(
        "--high-leverage-only",
        action="store_true",
        help="If set, output only high-leverage welfare/usage fields (N, severity, monitoring, analgesia, endpoints, euthanasia).",
    )
    args = parser.parse_args()

    catalog = generate_catalog(max_examples_per_field=max(args.max_examples, 1))
    if args.high_leverage_only:
        catalog = filter_high_leverage_fields(catalog)

    payload = json.dumps(catalog, indent=2, ensure_ascii=False)

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload, encoding="utf-8")
        print(f"Wrote catalog with {len(catalog)} entries to {args.output}")
    else:
        print(payload)


if __name__ == "__main__":
    main()
