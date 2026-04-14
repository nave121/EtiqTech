import csv
import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple

from .html_to_json import parse_html
from .linter_renderer import ADVISORY_REFS, LAW_CRITICAL_REFS, STRUCTURAL_REFS, lint
from .llm_agent import THEME_SPECS

ROOT_DIR = Path(__file__).parent.parent
GOLDEN_DATASET_DIR = ROOT_DIR / "examples" / "golden-dataset"
INDEX_PATH = GOLDEN_DATASET_DIR / "index.json"

LAYER3_SECTIONS = {
    "scientific_justification",
    "alternatives_search",
    "animal_numbers",
    "severity_classification",
    "monitoring_and_endpoints",
    "analgesia_and_anesthesia",
    "euthanasia",
    "personnel",
    "housing",
}

MUST_NOT_MISS_TAGS = {
    "unacceptable_euthanasia_for_species",
    "category_e_without_justification",
    "missing_humane_endpoints_high_severity",
    "paralytic_without_anesthesia",
    "multiple_major_survival_without_justification",
    "death_as_endpoint_without_justification",
    "no_alternatives_search_category_de",
    "pain_underclassification",
    "severe_long_lasting_suffering",
    "cosmetics_testing_ban",
}

KNOWN_L1_BASE_REFS = STRUCTURAL_REFS | LAW_CRITICAL_REFS | ADVISORY_REFS


def _normalize_ref(ref: str) -> str:
    return ref.rsplit(":exp-", 1)[0] if ":exp-" in ref else ref


def _read_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _resolve(rel_path: str) -> Path:
    return ROOT_DIR / rel_path


def load_case_instance(path: Path) -> Dict[str, Any]:
    if path.suffix.lower() == ".html":
        return parse_html(path.read_text(encoding="utf-8"))
    if path.suffix.lower() == ".json":
        return _read_json(path)
    raise ValueError(f"Unsupported case file type: {path}")


def lint_base_refs(instance: Dict[str, Any], profile: str = "default") -> List[str]:
    report = lint(instance, profile=profile)
    refs = {
        _normalize_ref(c.get("reference") or "")
        for c in report.get("checklist", [])
        if c.get("status") == "fail" and c.get("reference")
    }
    return sorted(r for r in refs if r)


def load_index() -> Dict[str, Any]:
    if not INDEX_PATH.exists():
        raise FileNotFoundError(f"Golden dataset index missing: {INDEX_PATH}")
    return _read_json(INDEX_PATH)


def load_case(case_json_path: Path) -> Dict[str, Any]:
    case = _read_json(case_json_path)
    case["_case_json_path"] = case_json_path
    return case


def load_golden_dataset(include_excluded: bool = False) -> Dict[str, Any]:
    index = load_index()
    cases = []
    for rel_path in index.get("cases", []):
        case = load_case(_resolve(rel_path))
        if include_excluded or not case.get("excluded", False):
            cases.append(case)
    return {"index": index, "cases": cases}


def validate_case(case: Dict[str, Any]) -> List[str]:
    errors: List[str] = []
    case_id = case.get("case_id", "<unknown>")

    for key in (
        "case_id",
        "case_type",
        "review_status",
        "source_origin",
        "species",
        "pain_category",
        "procedure_types",
        "primary_risks",
        "files",
        "ground_truth",
        "dependencies",
    ):
        if key not in case:
            errors.append(f"{case_id}: missing required field '{key}'")

    files = case.get("files") or {}
    for rel_path in files.values():
        path = _resolve(rel_path)
        if not path.exists():
            errors.append(f"{case_id}: file does not exist: {rel_path}")

    gt = case.get("ground_truth") or {}
    for key in (
        "bad_expected_l1_refs",
        "good_expected_l1_refs",
        "target_l2_themes",
        "target_l3_sections",
        "must_not_miss_tags",
        "notes_for_reviewers",
    ):
        if key not in gt:
            errors.append(f"{case_id}: missing ground_truth.{key}")

    for ref_group in ("bad_expected_l1_refs", "good_expected_l1_refs"):
        for ref in gt.get(ref_group, []):
            base_ref = _normalize_ref(ref)
            if base_ref not in KNOWN_L1_BASE_REFS:
                errors.append(f"{case_id}: unknown linter ref in {ref_group}: {ref}")

    for theme in gt.get("target_l2_themes", []):
        if theme not in THEME_SPECS:
            errors.append(f"{case_id}: unknown Layer 2 theme: {theme}")

    for section in gt.get("target_l3_sections", []):
        if section not in LAYER3_SECTIONS:
            errors.append(f"{case_id}: unknown Layer 3 section: {section}")

    for tag in gt.get("must_not_miss_tags", []):
        if tag not in MUST_NOT_MISS_TAGS:
            errors.append(f"{case_id}: unknown must-not-miss tag: {tag}")

    deps = case.get("dependencies") or {}
    for key in ("blocked_by_rules", "current_expected_status"):
        if key not in deps:
            errors.append(f"{case_id}: missing dependencies.{key}")

    if deps.get("current_expected_status") not in {
        "fully_testable",
        "partially_testable",
        "future_capability",
    }:
        errors.append(
            f"{case_id}: invalid dependencies.current_expected_status={deps.get('current_expected_status')!r}"
        )

    return errors


def validate_dataset(dataset: Dict[str, Any]) -> List[str]:
    errors: List[str] = []
    for case in dataset.get("cases", []):
        errors.extend(validate_case(case))
    return errors


def collect_coverage(cases: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
    cases = list(cases)
    canonical_pairs = 0
    species = set()
    pain_categories = set()
    tags = set()
    blocked = []

    for case in cases:
        files = case.get("files") or {}
        if files.get("bad_html") or files.get("bad_json"):
            if files.get("good_html") or files.get("good_json"):
                canonical_pairs += 1
        species.add(case.get("species"))
        pain_categories.add(case.get("pain_category"))
        gt = case.get("ground_truth") or {}
        tags.update(gt.get("must_not_miss_tags", []))
        deps = case.get("dependencies") or {}
        if deps.get("current_expected_status") != "fully_testable":
            blocked.append(
                {
                    "case_id": case.get("case_id"),
                    "status": deps.get("current_expected_status"),
                    "blocked_by_rules": deps.get("blocked_by_rules", []),
                }
            )

    return {
        "case_count": len(cases),
        "canonical_pairs": canonical_pairs,
        "species": sorted(s for s in species if s),
        "pain_categories": sorted(c for c in pain_categories if c),
        "must_not_miss_tags": sorted(tags),
        "blocked_cases": blocked,
    }


def iter_case_files(case: Dict[str, Any]) -> Iterable[Tuple[str, Path]]:
    files = case.get("files") or {}
    for key in ("bad_html", "good_html", "bad_json", "good_json", "case_report"):
        rel_path = files.get(key)
        if rel_path:
            yield key, _resolve(rel_path)


def case_variant_path(case: Dict[str, Any], variant: str) -> Path:
    files = case.get("files") or {}
    for key in (f"{variant}_html", f"{variant}_json"):
        rel_path = files.get(key)
        if rel_path:
            return _resolve(rel_path)
    raise KeyError(f"Case {case.get('case_id')} missing variant '{variant}'")


def review_rows(cases: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for case in cases:
        gt = case.get("ground_truth") or {}
        files = case.get("files") or {}
        rows.append(
            {
                "case_id": case.get("case_id"),
                "case_type": case.get("case_type"),
                "review_status": case.get("review_status"),
                "species": case.get("species"),
                "pain_category": case.get("pain_category"),
                "procedure_types": "|".join(case.get("procedure_types", [])),
                "primary_risks": "|".join(case.get("primary_risks", [])),
                "must_not_miss_tags": "|".join(gt.get("must_not_miss_tags", [])),
                "bad_file": files.get("bad_html") or files.get("bad_json") or "",
                "good_file": files.get("good_html") or files.get("good_json") or "",
                "case_report": files.get("case_report") or "",
                "overall_disposition": "",
                "law_critical_findings": "",
                "advisory_findings": "",
                "per_theme_comments": "",
                "disagreement_notes": "",
            }
        )
    return rows


def write_review_csv(rows: List[Dict[str, Any]], out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        out_path.write_text("", encoding="utf-8")
        return
    with out_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
