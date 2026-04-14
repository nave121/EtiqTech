import pytest

from src.golden_dataset import (
    MUST_NOT_MISS_TAGS,
    case_variant_path,
    collect_coverage,
    lint_base_refs,
    load_case_instance,
    load_golden_dataset,
    review_rows,
    validate_dataset,
    write_review_csv,
)


def test_golden_dataset_validates():
    dataset = load_golden_dataset()
    errors = validate_dataset(dataset)
    assert not errors, "Golden dataset validation errors:\n" + "\n".join(errors)


def test_golden_dataset_coverage_targets():
    dataset = load_golden_dataset()
    coverage = collect_coverage(dataset["cases"])

    assert coverage["canonical_pairs"] >= 10
    assert len(coverage["species"]) >= 3
    assert {"B", "C", "D", "E"}.issubset(set(coverage["pain_categories"]))
    assert MUST_NOT_MISS_TAGS.issubset(set(coverage["must_not_miss_tags"]))


def test_epic4_synthetic_pairs_have_case_reports():
    dataset = load_golden_dataset()
    synthetic_cases = [
        case
        for case in dataset["cases"]
        if case["case_id"] in {"SYNTH-008", "SYNTH-009"}
    ]

    assert synthetic_cases
    for case in synthetic_cases:
        assert "case_report" in case["files"], case["case_id"]


def test_manifest_backed_l1_expectations():
    dataset = load_golden_dataset()
    cases = [
        case
        for case in dataset["cases"]
        if case["dependencies"]["current_expected_status"] != "future_capability"
    ]

    for case in cases:
        bad_refs = lint_base_refs(load_case_instance(case_variant_path(case, "bad")))
        good_refs = lint_base_refs(load_case_instance(case_variant_path(case, "good")))

        assert bad_refs == sorted(case["ground_truth"]["bad_expected_l1_refs"]), case["case_id"]
        assert good_refs == sorted(case["ground_truth"]["good_expected_l1_refs"]), case["case_id"]


@pytest.mark.parametrize(
    "case_id",
    [
        case["case_id"]
        for case in load_golden_dataset()["cases"]
        if case["case_type"] == "real_pair"
    ],
)
def test_real_head_to_head_pairs_have_stable_manifest_expectations(case_id):
    dataset = load_golden_dataset()
    case = next(case for case in dataset["cases"] if case["case_id"] == case_id)

    bad_refs = lint_base_refs(load_case_instance(case_variant_path(case, "bad")))
    good_refs = lint_base_refs(load_case_instance(case_variant_path(case, "good")))

    assert bad_refs == sorted(case["ground_truth"]["bad_expected_l1_refs"])
    assert good_refs == sorted(case["ground_truth"]["good_expected_l1_refs"])


def test_reviewer_export_rows(tmp_path):
    dataset = load_golden_dataset()
    rows = review_rows(dataset["cases"])

    assert rows
    out_path = tmp_path / "review.csv"
    write_review_csv(rows, out_path)

    text = out_path.read_text(encoding="utf-8")
    assert "case_id" in text
    assert "overall_disposition" in text
